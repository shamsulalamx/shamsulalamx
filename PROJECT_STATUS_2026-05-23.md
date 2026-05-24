# Project Status 2026-05-23

Current stable tag: `v4.60-nbme-boundary-and-auto-attach-stable`
Current branch: `phase11-fastfacts-stability`
Last committed HEAD: doc commit landing alongside the v4.60 source commit.

Supersedes `docs/archive/PROJECT_STATUS_2026-05-21.md`.

## What Is New Since 2026-05-21

### v4.60 — NBME boundary regex fix + automatic stem-image attachment (offline-validated)

Two distinct user-facing problems addressed in one milestone — both surfaced from the same first live NBME BIC import attempt on `[Medicalstudyzone.com] Internal Medicine 3 - Answers.pdf`:

1. **Live import failure: "No question boundaries found — cannot chunk."** The chunker's boundary regex required `Item N` at line start. The user's PDF format has `Exam Section : Item 1 of 50 National Board of Medical Examiners` on every question page — `Item 1` is mid-line. Fixed with a two-tier regex strategy: strong `\bItem\s+(\d+)\s+of\s+\d+\b` match anywhere on the line (NBME Self-Assessment header signature), with fallback to legacy line-start patterns plus new OCR-bullet handling (`~`, `*`, `•`, `·` before stem numbers) when the strong tier yields nothing.

2. **Manual cropping tedium.** The user said: "All other pipelines handle images differently, and I love how everything has been doing so far. The only image handling that's unique to NBME is that the stem images are separated, and shown to me during generation, and I have the ability to crop and attach them. This is tedious. (NBME has NO images in the answer explanation, so gemini involvement is none to decided whether images go in the q stem or answer explanation)." New `auto_attach_figures_to_app_ready` writes extracted PNG crops directly into `q.images[]` with inline base64 `dataUrl`, mirroring the v4.58 Mehlman / v4.56 images-tables app-ready contract. All NBME attachments use `placement: stem` (user confirmed explanations have no images). No Gemini multimodal calls.

Source changes:

- `tools/nbme-pdf-json-generator/extract_pdfs.py`: split boundary regex into `_Q_BOUNDARY_STRONG_RE` + `_Q_BOUNDARY_FALLBACK_RE`. `chunk_raw_text` tries strong first, falls back only on empty matches.
- `tools/nbme-pdf-json-generator/normalized_to_app_json.py`: `convert_normalized_file` accepts both `items` (live) and `questions` (dry-run) keys — fixes a pre-existing dry-run end-to-end bug.
- `tools/nbme-pdf-json-generator/nbme_extract_figures.py`: new `auto_attach_figures_to_app_ready` function with aspect-ratio guard (`AUTO_ATTACH_MIN_ASPECT=0.30`, `AUTO_ATTACH_MAX_ASPECT=3.00`). Real clinical images cluster 0.5-2.5; text-block false positives cluster 3.5-8.6.
- `tools/nbme-pdf-json-generator/nbme_batch_wrapper.py`: `run_app_ready` invokes the new auto-attach after the existing `build_suggested_figure_links` (which still emits the review HTML for low-confidence candidates).

Offline-validated end-to-end through the packaged `.app`:

- `Internal Medicine 3 - Questions.pdf` (10 pages): 9 chunks produced (was 0 prior to v4.60), `boundary_source: strong:item-of-M`. Figure extractor produces 14 candidates → aspect-ratio guard correctly rejects 12 text strips and retains 2 likely-real clinical images.
- `Internal Medicine 3 - Answers.pdf` (5 pages): 4 strong boundary matches, all 5 wide text-strip false positives correctly aspect-filtered except 1 borderline (aspect 2.8) which can be removed manually if wrong.

Live Gemini run on a real NBME PDF is the next field check. The chunking + auto-attach are offline-validated; live Gemini uses the same code path UWorld/Mehlman/OME/Anki use which has been live-validated since v4.51.

Tag commits: `<source-hash>` (source) + `<doc-hash>` (doc).

### v4.59 — UWorld notes BIC enablement: text-only, high-yield density, foundational generator gets first-class CLI flags (field-validated)

First BIC integration of the foundational UWorld notes generator. UWorld was the underlying module every other text-heavy source (Anki, OME, Mehlman, Divine wrappers) had been importing for months — through the v4.51 stem-quality validator, v4.53 review-survivor flow, and v4.54 chunk-planning recovery — but it had never been wired through BIC itself. The user had no "UWorld" option in the source dropdown despite having UWorld notes ready to import.

v4.59 closes that gap with the same profile-runner + shared-chunk-emitter integration the four wrappers already used, with three properties tuned to the user's UWorld content:

- **Text-only.** The user confirmed UWorld notes are "absolutely no images, just text," so the profile runner skips all image/table machinery. No deterministic figure attachment (v4.58), no Gemini multimodal call (v4.56), no figure-extraction pass.
- **High-yield density.** The user said UWorld notes are "extremely high yield" and asked for higher question frequency per content unit. After a day-1 → field retune (the user pushed back on the original 5-question floor for a 3-page note: "THESE ARE HIGH YIELD MATERIAL, and I would want more rigorous testing"), the runner auto-scales `--questions-per-file` to `max(8, chars // 150)` clamped at 80 — roughly 10× Mehlman's 1-question-per-1.5K-chars density. A 3-page UWorld note lands at 9 questions; a 10 KB note at 66; 12+ KB at the MAX clamp of 80 (cost cap ~$0.16/file). Override via explicit `--questions-per-file N`.
- **Foundational module gets first-class CLI flags.** The UWorld generator had no `--input-file` or `--output-dir` (fixed `input_notes/` scan only). v4.59 adds both, mirroring the Anki / Mehlman wrapper pattern so BIC can drive UWorld from outside the read-only `.app` bundle source tree.

Source changes:

- `tools/uworld-notes-question-generator/generate_uworld_questions.py`: new `_resolve_selected_input` and `_apply_output_dir` helpers; new `--input-file` and `--output-dir` CLI args; file-discovery branch uses the selected input when set.
- `tools/shared-ingestion/uworld_profile_runner.py` (new): mirrors `anki_profile_runner.py` / `ome_profile_runner.py`. Runs `run_shared_chunk_pipeline(source_type="uworld_notes")` then `subprocess.run` on the UWorld generator with auto-scaled `--questions-per-file`. Respects `BIC_JOB_OUTPUT_ROOT`.
- `tools/shared-ingestion/source_descriptor.py`: new `uworld_notes` `SourceDescriptor` (modality=text, asset_policy=none).
- `tools/shared-ingestion/pipeline_adapter.py`: new `uworld_notes_to_normalized_chunks` adapter that reuses the UWorld text extractor + heading-aware splitter, wired into the `emit_normalized_chunks` dispatcher.
- `tools/shared-ingestion/chunk_pipeline.py`: added `uworld_notes` to `--source-type` allowlist.
- `tools/batch-import-center/pipeline_registry.json`: new `uworld_notes` registry entry (label `UWorld Notes`, accepts `.txt .md .rtf .docx`, `requiresGemini: true`).

Field-validated through the packaged `.app` on real `/Users/shamsulalam/Desktop/Test uWorld.docx` (3-page UWorld note, 1,365 chars after `.docx` text extraction). User confirmed "everything works perfectly" on the live import. Output: `extractedChars=1365`, `questionsPerFile=9`, `chunkCount=1`, `candidateQuestionCount=9`, `outcome: completed`, no chunk failures.

Tag commits: `08862c9` (source) + `d0c5e35` (doc).

Three follow-up commits landed on top of the original `v4.59-uworld-live-stable` tag (no new tag — tuning + bug fixes only):

- `e14e811` — surfaced "UWorld Notes" in the BIC source-type dropdown. The original source commit wired the backend completely but the dropdown in `index.html` is a hardcoded `<option>` list, not a registry-driven enumeration, so the entry only appears after two parallel index.html edits.
- `cc8af39` — fixed `.docx` auto-density bug (was using `stat().st_size` which overcounts ~40× because `.docx` is a zipped XML container — a 57 KB file ≈ 1.4 KB of real text) and added a fast-fail path for missing `python-docx` / `striprtf` so the cryptic "did not produce expected app-ready JSON" error no longer hides a missing-dependency root cause. Added repo-root `requirements.txt` documenting the full system-Python dep set.
- `5495bff` — retuned density constants from MIN=5 / DEFAULT=500 to MIN=8 / DEFAULT=150 after the first live import only yielded 5 questions on the 3-page note. Final density curve: 1.4 KB → 9 q, 4 KB → 27 q, 10 KB → 66 q, 12+ KB → MAX clamp 80.

### v4.58 — Mehlman tight-focus chunking + deterministic page-proximity image attachment + full-PDF processing (offline-validated)

Three-part Mehlman rework that the user accepted from a cost/quality tradeoff table at the top of the session: 1.5K-char chunks, 1 question per chunk, deterministic image attachment by page proximity. Plus two integration bugs the first packaged live run surfaced — an out-of-tree `Path.relative_to` crash that silently dropped every chunk with figures, and a hardcoded 10-page validation cap that truncated every uploaded PDF.

Source changes:

- `tools/mehlman-pdf-question-generator/generate_mehlman_questions.py`: `_MIN_CHUNK 8_000 → 1_200`, `_MAX_CHUNK 12_000 → 1_800`; sentence-split fallback added inside the single-page overflow branch of `split_pages_into_chunks` because PDF extraction often strips `\n\n` from dense Mehlman pages; new helpers `_mime_for`, `_data_url`, `_attach_chunk_figures_to_questions`; attachment wired into both dry-run and live branches; per-figure exception isolation so a single bad image cannot kill its sibling figures or the question; `--questions-per-chunk` default `5 → 1`.
- `tools/shared-ingestion/mehlman_profile_runner.py`: drop the pre-v4.58 `--questions-per-chunk 2` override so the BIC live path inherits the new default; `--limit` default `10 → 0` (0 = process every page); omit `--max-pages` from the subprocess call when `page_limit == 0`.
- `tools/batch-import-center/pipeline_registry.json`: `mehlman_pdf` dry-run and live steps no longer pass `--limit 10`; notes updated.

Field surface from this session, in order:

1. **First packaged live run on `Test Mehlman.pdf` (19 pages): 20 questions, zero images.** Investigation showed the chunk manifest correctly tracked 19 figures across 18 chunks, but my v4.58-day-1 attachment helper called `fig_path.relative_to(_BASE)` on figures under the writable job dir while `_BASE` still pointed at the read-only `.app` bundle root. `ValueError` propagated to the chunk's `except Exception` and dropped all 8 chunks that had figures (questions + figures). 10 figure-less chunks × 2 q/chunk (profile-runner override) = 20 questions, no images. Fixed by catching the ValueError and falling back to `extracted_figures/<name>` as the informational `assetPath` (the actual binary already lives in the inline base64 `dataUrl`).
2. **User asked to lift the 10-page cap.** Profile runner default flipped to 0 / unlimited; BIC registry dropped `--limit 10`; the wrapper omits `--max-pages` when unlimited.

Field-validated end-to-end through the packaged `.app` on `Test Mehlman.pdf` (19 pages) via the profile runner: 36 chunks (avg ~1,200 chars, max 1,796, 0 over the 1,800 cap), 36 questions (1 per chunk), 12 questions with 23 figures attached spanning pages 1, 2, 3, 4, 5, 8, 9, 10, 11, 16, 17, 19. `extractionWarnings` empty. `pageLimit: 0` in the runner report.

Architecture significance: this is the first BIC source where image attachment is fully deterministic (no Gemini multimodal call) and driven entirely by chunk-to-page proximity already tracked during extraction. The same template applies cleanly to any future PDF source whose figures live on identifiable pages.

Tag commits: `369cee1` (source) + `384bd4a` (doc).

### v4.57 — AMBOSS PDF deterministic-first + Gemini-assisted extractor (field-validated)

Full rewrite of the AMBOSS PDF BIC extractor. The prior architecture ran one Gemini call per PDF page (~39 calls / ~$0.50 / ~9 min for a typical 8-question QBank export) and failed the first live BIC run with "No valid output was available to auto-import" because the duplicate-question validator rejected the multiple page views of each question. The user explicitly asked to minimize Gemini and route blown-up clinical images deterministically to explanations.

New pipeline in `tools/lecture-slide-question-generator/generate_lecture_slide_questions.py`:

1. **Stage 1 (deterministic, no Gemini)**: PyMuPDF render → tesseract OCR → page classification (`qbank_screenshot` vs `blown_up_image`) → stem fingerprinting → nav-pill detection with majority-M validation.
2. **Stage 2 (deterministic grouping)**: union-find on per-page nav-pill and stem-fingerprint signals + adjacent-component merge for nav-matching neighbors. Blown-up image pages attach to preceding question via adjacency.
3. **Stage 3a (hybrid Gemini, 1 call per question)**: each group ships up to 4 page screenshots to Gemini for structured extraction — answer choices A–H (defeated by AMBOSS's styled letter circles), correct-answer letter (GREEN choice header bar), per-choice explanations, educational objective, retrieval tag, review pearl. Uses `responseMimeType: application/json` + `maxOutputTokens: 8192` (truncated-JSON and prose-instead-of-JSON failure modes surfaced in early tests; both fixed).
4. **Stage 3b (Gemini recovery fallback)**: when a group's deterministic extraction returns None (every page misclassified due to OCR failure), one extra Gemini call asks "is there an AMBOSS question here? if yes, extract it; if no, return no_question".
5. **Stage 3c (post-extraction dedupe)**: collapses questions whose normalized stems agree on the first 40 chars (handles the OCR variance that fragments "A 27-year-old" and "A.27-year-old" into two components).

Field-validated on `Test Amboss.pdf` (8 QBank questions across 39 pages of browser screenshots + click-to-enlarge clinical images): all 8 questions extracted with clean choices, correct answers, educational objectives, retrieval tags, review pearls, and clinical images attached to the correct explanation panels. Runtime ~2.5 min, cost ~$0.11 per import (down from ~9 min / ~$0.50).

Tag commits: `9ad47c9` (source) + `0482322` (doc).

### v4.56 — Live Images & Tables generation through BIC + multi-image merge + duplicate-explanation render fix (field-validated)

Replaces the v4.15 attachment-first Images & Tables BIC path with live per-image Gemini classification + NBME-style question generation, fixes two follow-on bugs surfaced by the first real live runs (multi-file merge across BIC's per-input invocations; double-rendered explanation panel), and tightens the table-placement contract so tables and charts never appear in the question stem. Closes the last BIC source that was wired to a deliberate non-Gemini stub for live mode.

Source changes (3 source files + 1 UI file, landed across 2 source commits + 1 doc commit):

- `tools/batch-import-center/pipeline_registry.json` — `images_tables_source` entry: `requiresGemini: true`, widened `inputExtensions`, `liveSteps` now invokes the runner with `--mode generate --limit 0` (no per-file cap), updated notes.
- `tools/shared-ingestion/images_tables_profile_runner.py` — `generate` branch now delegates each input image to the real Gemini generator (`generate_images_tables_questions.py`); new `merge_per_image_outputs()` accumulates across BIC's per-input invocations using a stable filename (`images_tables_combined_app_ready.json`) and `_per_image.json` debug suffix that falls outside BIC's discovery glob.
- `tools/images-tables-question-generator/generate_images_tables_questions.py` — adds `--input-file` for single-image BIC invocations, tightens classifier prompt + post-classification override so tables/charts never land in the stem, redirects asset/log/intermediate dirs when `--output-dir` is set (for packaged-app writeability), drops duplicate plain-text `explanation` field.
- `index.html` — `buildExplanationHTML` (both copies) now uses `else if (q.explanation)` so `correctBlurb` and `explanation` never both render; backward-compatible defense for any v2-schema source that populates both fields.

Field-validated on a 5-image packaged-app BIC run (Abdominal CT, abetalipoproteinemia biopsy, alcoholic hepatic steatosis, aortic arch derivatives, Barrett's esophagus): 5 questions imported in a single test, no duplicate explanation blocks, correct stem/explanation placement per image type. Dev-Electron 4-image run (dermatology, vesicoureteral process diagram, water-soluble vitamins table, Weber/Rinne tracing) confirmed correct classification across all four placement categories; the table was relegated to the explanation panel as required. User confirmed: "Works flawlessly."

Tag commits: `70999ec` (source) + `3a8aaaf` (doc).

### v4.55 — Live Divine generation from podcast audio through BIC (field-validated)

Closes the last text-only / dry-run-only boundary in the BIC source registry. The `divine_transcript` source now accepts `.mp3 / .m4a / .wav` in addition to `.txt / .md`, relabels as "Divine (Audio + Transcript)", and `liveSteps` invokes the profile runner with `--emit-app-ready-live`. For audio inputs the profile runner skips the shared chunk pipeline (chunks don't exist until after transcription) and delegates to `tools/divine-audio-question-generator/generate_divine_questions.py --generate --input-file <audio> --output-dir <durable>`, which uploads to the Gemini File API, transcribes, cleans, chunks, and generates questions in one process. Audio + dry-run is rejected with a clear error so transcription tokens are never wasted.

Source changes:

- `tools/batch-import-center/pipeline_registry.json` — `divine_transcript` entry widened (`inputExtensions`, label, `requiresGemini`, `liveSteps`, `outputDirectories`, notes).
- `tools/shared-ingestion/divine_transcript_profile_runner.py` — text/audio extension sets, `selected_input` + `is_audio_input` helpers, `run_divine_generator(live=)` refactor, `--emit-app-ready-live` flag, audio + dry-run gating, audio path bypasses shared chunk pipeline.
- `tools/divine-audio-question-generator/generate_divine_questions.py` — `--input-file` widened to accept audio in `--generate` mode; `_apply_output_dir` now also redirects `RAW_DIR` and `CLEANED_DIR` so transcripts land under the durable job root.
- `index.html` — BIC dropdown `<option>` and `BATCH_IMPORT_SOURCE_LABELS` cache relabeled.

Field-validated on `Test Divine.mp3` (17.2 MB Divine Intervention podcast): 131s end-to-end, 7 valid questions emitted with `schemaVersion: nbme-gemini-json-v3` and `sourceFormat: divine-audio`. `.app` packaged build confirmed to contain all updated assets. User confirmed: "Divine works perfectly!"

Tag commits: `0b671fc` (source) + `faa7637` (doc).

### v4.54 — UWorld-family chunk-planning recovery + quota-aware retry stop (offline-validated)

Ports the v4.49 lecture-slide chunk-planning fix to the shared UWorld machinery, so the five UWorld-wrapping generators (Anki, OME, Mehlman, Divine, UWorld) now have the same silent-loss protection the lecture-slide generator has had since 2026-05-23.

Single source change in `tools/uworld-notes-question-generator/generate_uworld_questions.py`:

- **Quota-aware retry stop.** New `is_quota_failure(error)` predicate + `is_network_failure(error)` helper + `_QUOTA_EXHAUSTED` module-level latch + `quota_exhausted()` / `mark_quota_exhausted()` / `reset_quota_state()` helpers. Latch checked at every retry boundary in `call_gemini_with_retry`. When the repair call hits quota, waiting questions route to the v4.53 needs-review collector.
- **Per-chunk shortfall recovery.** New `MAX_RECOVERY_ATTEMPTS_PER_CHUNK = 2`. After the main chunks loop, scan for `generated < requested` and make up to 2 focused follow-up calls per short chunk asking only for the missing questions. Bounded cost: `len(chunks) * 2` extra API calls worst case.

Applies automatically to all five UWorld-wrapping generators. NBME PDF generator has its own normalization path and still needs its own port (item 0b open).

Tag commit: `0c3e389`.

### v4.53 — UWorld-family review-survivor flow (offline-validated; field validation pending organic failure)

Ports the v4.50 review-survivor flow to all five UWorld-wrapping generators (Anki, OME, Mehlman, Divine, UWorld). When a question fails BOTH initial validation AND the repair retry, it now surfaces in the existing BIC review modal for human accept/edit/reject instead of being silently included in the app-ready output with `extractionWarnings` appended.

Single source change in `tools/uworld-notes-question-generator/generate_uworld_questions.py`:

- New `write_uworld_family_review_draft()` helper writes a `uworld_family_review_draft.json` matching the same schema BIC's `discover_review_draft()` and the renderer's `read-review-draft` IPC handler already use for lecture-slide.
- New `_resolve_review_dir()` picks `BIC_JOB_OUTPUT_ROOT/review` when BIC sets that env var, falls back to `BASE_DIR/review` for standalone CLI.
- `call_gemini_with_retry()` gained an optional `needs_review_collector` parameter; failed-repair questions go there instead of being silently kept. Backward-compatible default.
- `process_file()` always passes the collector, writes the draft after all chunks complete when non-empty.

End-to-end: failed-repair questions land in the draft → BIC discovers it → renderer shows them → accept/edit/reject goes through the v4.50 canonicalize + append-to-existing-test path.

No regression for clean runs. Offline-tested. Field-validation of the failure path itself is pending an organic partial-failure run; user chose to wait rather than synthesize.

Tag commit: `8f213d5`.

### v4.52 — Live Anki generation through BIC + cross-generator chunking and token-cap fix (field-validated)

Diagnosed and resolved 2026-05-23 after the user's first live Anki BIC run on a 15-card .txt produced 0 questions even though orchestration ran cleanly.

Anki BIC enablement (same OME-pattern fix from v4.51):

- `tools/shared-ingestion/anki_profile_runner.py` gained `--mode {dry-run, generate}` and always invokes the downstream wrapper with the selected mode.
- `tools/batch-import-center/pipeline_registry.json` `anki_notes` entry flipped `requiresGemini: true` and pointed `liveSteps` at `--mode generate --limit 0`.

Cross-generator chunking + token-cap fix in `tools/uworld-notes-question-generator/generate_uworld_questions.py` (affects OME, Mehlman, Divine, Anki, and UWorld since they all reuse this module):

- `split_into_chunks()` now force-slices any chunk that exceeds `max_chars=3000` after heading and paragraph splits. The prior fallback re-split on the same boundary it already failed at; Anki .txt exports with no double-newlines collapsed to one giant chunk.
- `_raw_gemini_call()` `maxOutputTokens` raised 8192 → 16384 to give headroom for chunks that ask Gemini for multiple full-JSON questions.

Field-validated on user's 15-card Anki .txt: 15 questions generated cleanly. Offline test exercised a 281 K synthetic input with no double-newlines and got 94 properly-sized chunks (all ≤ 3000 chars).

Tag commits: `f99ded6` (Anki BIC enablement) + `3772d7a` (UWorld chunking + token fix) + doc commit.

### v4.51 — Stem-quality contract across all organic generators + OME live generation enabled (field-validated)

Two related fixes landed and field-validated in the same session after the user's first OME live BIC run surfaced that generated stems weren't ending with question marks (same class of bug Fast Facts hit earlier, but the previous fix only landed in the lecture-slide generator).

Stem-quality contract:

- `stem_has_explicit_final_question(stem)` + helpers added to `tools/uworld-notes-question-generator/generate_uworld_questions.py`, wired into `validate_question(q)`. Since OME, Mehlman, Divine, and Anki all reuse this validator via `import generate_uworld_questions`, the check fires across all 5 wrapping generators. Failing stems route into the existing repair-retry path; if repair still fails, questions are kept with `extractionWarnings` rather than silently dropped.
- A uniform `STEM FORMAT RULES` block added to all 5 prompt files. Same wording as the lecture-slide prompt: every stem must end with a clear final question sentence ending in `?`.

OME live generation:

- `tools/shared-ingestion/ome_profile_runner.py` gained `--mode {dry-run, generate}` following the Emma runner pattern. The `--emit-app-ready-dry-run` flag is kept as a backward-compatible alias.
- `tools/batch-import-center/pipeline_registry.json` `ome_pdf` entry now flips `requiresGemini: true` and points `liveSteps` at `--mode generate --limit 0`.
- Field-validated on user's small OME PDF live BIC run: questions end with proper `Which of the following is the most likely diagnosis?` style sentences, packaged auto-import succeeded, quiz and explanation panels render normally.

Tag commits: `4b2d847` (stem-quality) + `cc290d9` (OME live enablement) + doc commit.

### v4.50 — Fast Facts review-survivor import merges into the auto-imported test, with full canonical explanations (field-validated)

Two fixes to the Fast Facts review-survivor flow that close a UX bug and a schema bug discovered when the user ran a small Fast Facts PPTX that produced 1 validated question and 2 review-needed questions:

- **UX bug fix**: reviewed-accepted questions now merge into the same auto-imported test for the BIC job instead of being written into a parallel duplicate test. The user gets one 3-question test, not 1 + 2.
- **Schema bug fix**: reviewed-accepted questions are now written in canonical app-ready shape with assembled `explanationSections[]` instead of the raw Gemini fields. Users see full Correct Answer Explanation + Incorrect Answer Explanation + Educational Objective sections.

Implementation:

- `electron/main.js` gains `assembleReviewedQuestionExplanationSections()` + `canonicalizeReviewedSurvivorQuestion()`. The `write-accepted-review-survivors` IPC handler runs accepted questions through the canonicalizer.
- `index.html` `importValidatedBatchOutputJsonText()` accepts an `appendToTestId` destination option that merges via `DB.updateTest()` instead of creating a parallel test. `importAcceptedBatchReviewQuestions()` passes `job.importedTestId` so reviewed survivors land in the existing per-job test.
- Forward-only: tests imported via the buggy pre-v4.50 path still need either re-run or one-shot recovery.

Tag commit: `64a8e14`.

### v4.49 — Lecture-slide chunk-planning quota-aware recovery (field-validated)

Two complementary fixes to `tools/lecture-slide-question-generator/generate_lecture_slide_questions.py` close the chunk-planning silent-loss bug diagnosed on 2026-05-23. Field-validated on the same day by a Test_Emma BIC live run (job `batch-mpis1xxn-c0i3id`):

- 18 allocated → 17 generated. 5 short-returning slides triggered the targeted recovery loop; 4 recovered, 1 stopped cleanly on a Gemini timeout.
- Runtime 369.8s. BIC auto-imported the result as "Test Emma Lecture Questions" with no errors.
- 4 of the imported questions carry inline tables, exercising the v4.48 table renderer in the same run.

Defensive half (quota-aware retry stop) was independently field-validated on the earlier depleted-credits run (job `batch-mpirtu3n-1cfsur`): 1 HTTP 429 caught, all subsequent retries skipped, 10.5s runtime vs the prior naive-cascade's 148s.

Implementation:

- `is_quota_failure(error)` predicate (HTTP 429 / `RESOURCE_EXHAUSTED` / "prepayment credits are depleted").
- `_QUOTA_EXHAUSTED` module-level latch + `quota_exhausted()` / `mark_quota_exhausted()` / `reset_quota_state()` helpers.
- Latch checked at every retry boundary in `generate_question_chunk_with_retries`, the cross-chunk loop in `generate_questions`, and inside `retry_missing_slide_questions`.
- `retry_missing_slide_questions(allocation, missing_count, max_attempts=MAX_RECOVERY_ATTEMPTS_PER_SLIDE)`: focused per-slide recovery with `require_exact_count=True`. Worst-case extra API calls = `len(work) * 2`.
- Clearer fatal-error messaging when 0 questions exit was caused by quota exhaustion.

Tag commits: `1c1f744` (main fix) + `6c0ce4f` (error message follow-up).

### v4.48 — Lecture-slide explanation tables now render

The lecture-slide downstream (Emma Holiday and any source feeding `generate_lecture_slide_questions.py`) now renders structured tables in the explanation panel instead of emitting the placeholder line `"Table used for explanation only: <tableId>"`.

Renderer side:

- `renderExplanationTablesInto(q, container)` in `index.html` reads `q.tables` (with `q.metadata.tables` as a fallback) and renders headers/rows as an HTML `<table class="lab-table">` inside the explanation block.
- The function is wired into both the Quiz IIFE explanation builder and the standalone `window.buildExplanationHTML` so review-mode rendering also picks it up.

Generator side (`tools/lecture-slide-question-generator/generate_lecture_slide_questions.py`):

- `build_explanation_sections` no longer extends `extras` with `table_notes`.
- The section heading `"Slide Figures and Tables"` was renamed to `"Slide Figures"` because tables now render via their own block.

Validated in packaged `shamsulalamx.app` for the Test_Emma fixture (3-column / 3-row table). Not yet validated across all Emma decks.

### Phase 11 fast-facts stability work (already tagged)

These commits landed before v4.48 and remain in place:

- `v4.47-emma-pdf-batch-import-stable` — Emma PDF batch import routing stabilization.
- `v4.46-fastfacts-reviewed-import-after-auto-import-stable` — Reviewed Fast Facts import allowed after auto-import.
- `v4.45-fastfacts-review-only-completion-stable` — Fast Facts review-only completion handling.
- `v4.44-fastfacts-generation-completion-stable` — Fast Facts generation completion stabilization.
- `v4.44-phase11-observability-stable` — Phase 11.7 observability + unified chunk contract.
- `v4.43-fastfacts-limit-removal-stable` — Removed unintended Fast Facts generation caps.
- `v4.42-fastfacts-packaged-path-hotfix-stable` — Packaged Fast Facts path crash hotfix.
- `v4.42-source-type-switching` — Allow source type switching with queued files.
- `v4.41-phase11-generation-correctness-stable` — Phase 11 generation correctness hardening.
- `v4.41-per-question-review-draft-stable` — Per-question review draft wiring with manual approve/reject/import.

### UOGA package (`core/uoga/`)

The Unified Organic Generation Architecture core package is in place and enforced through `scripts/uoga_dependency_graph_validator.py`. Currently graph-native only for `fast_facts_pptx`. Other organic sources fail fast with "not graph-native, cannot run in hybrid mode."

Key modules:

- `execution_graph.py` — chunk-graph state and attempt tracking.
- `retry_engine.py` — bounded retry (`initial → repair → fallback`).
- `finalization.py` — single-emission `JOB_COMPLETE` gate.
- `telemetry_engine.py` — UOGA-restricted chunk events with heartbeat.
- `review_artifacts.py` — durable review draft writer.
- `job_contracts.py` — source-type → execution-mode routing and chunk-event contracts.
- `validation_engine.py` — chunk accounting and cardinality reconciliation.

Domain boundaries enforced: EXTRACTIVE and HYBRID may not import from UOGA; SHARED may not depend on any runtime domain; `ExecutionGraph`, `CHUNK_*` symbols, and `retry_engine` are UOGA-only.

## What Was Investigated, Fixed, And Field-Validated In One Day

### Lecture-slide chunk-planning silent-loss → resolved at v4.49

Symptom (diagnosed 2026-05-23 morning): same input PDF could produce 16 questions in one run and 7 in the next without any explanation in the report. `validationWarnings` and `validationErrors` came back empty in both cases. The generator silently accepted short Gemini returns.

Root cause: `call_generation_once` in `generate_lecture_slide_questions.py` passed `require_exact_count=False` to `extract_generated_question_items`. When Gemini returned fewer questions than the chunk's allocated count, the partial output was kept with only a `warn()` call to stderr. No retry, no sub-chunking, no escalation.

Investigation timeline:

1. **Naive fix attempted and rolled back.** Flipping the flag to `True` caused the existing retry path to engage (repair → sub-chunk in halves → single-slide attempts). A live test (`/private/tmp/chunk-fix-live-test-1779546582/`) confirmed the retry path engaged correctly, but the recursion multiplier was aggressive enough to deplete the user's Gemini prepayment credits mid-run. Once 429s started, every remaining slide got skipped. Final outcome was 0 questions, worse than the original 7. Change reverted in HEAD; packaged app rebuilt to match.

2. **Quota-aware retry stop + targeted missing-slide recovery designed and landed.** Two complementary changes in one commit (`1c1f744`): the latch protects against runaway, the recovery loop solves the original short-return problem with bounded cost.

3. **Defensive half field-validated on a depleted-credits run.** Even with no credits, the live run confirmed the 429 latch fires correctly and prevents cascade.

4. **Error message follow-up** (`6c0ce4f`): the generic "0 questions" fatal error now names quota exhaustion as the cause when relevant.

5. **Active half field-validated on the topped-up Test_Emma run.** Recovery loop fired for 5 short-returning slides, recovered 4 (the 5th cleanly stopped on a network timeout). 17 of 18 allocated questions delivered. BIC auto-imported.

6. **Tagged `v4.49-lecture-chunk-recovery-stable`.**

No open work item from this thread. See `NEXT_STEPS_PRIORITY.md` item 0b for the follow-up of auditing OME / Mehlman / NBME / Divine generators for the same silent-loss class.

## Validated Sources (Current Snapshot)

| Source | Current status | Validation level |
|---|---|---|
| AMBOSS PDF | Deterministic-first + Gemini-assisted pipeline rewritten at v4.57; 8/8 questions extracted from `Test Amboss.pdf` (39 pages of flattened browser screenshots + click-to-enlarge clinical images) in ~2.5 min for ~$0.11 | Variable-choice support and live import path tagged stable; v4.57 hybrid validated end-to-end including blown-up image routing to explanations |
| Emma Holiday | Shared profile + normalized-chunk downstream stable; explanation tables now render (v4.48) | BIC existing-output import validated; live generation has separate semantic blocker risk and chunk-planning silent-loss risk |
| Mehlman | Shared-ingestion live profile stable | Tagged v4.12 |
| NBME | BIC orchestration stable | Tagged v4.8; legacy NBME import/image workflows have earlier validation |
| Images & Tables | Shared-ingestion profile stable; v4.15 attachment-first stub superseded by v4.56 live Gemini per-image classification + NBME-style generation | Packaged `.app` 5-image BIC run validated end-to-end (one combined test, no duplicate explanation blocks, tables routed to explanation panel) |
| Anki | Shared-ingestion dry-run profile validated | Live Gemini generation and semantic quality not validated |
| OME | Shared-ingestion dry-run profile validated | Live Gemini generation and writable packaged output not validated |
| Divine (Audio + Transcript) | Shared-ingestion transcript profile validated; live BIC audio → transcribe → questions field-validated at v4.55 on a 17.2 MB MP3 (`Test Divine.mp3`, 131s, 7 valid questions) | Packaged-app live audio run via the v4.55 `.app` and long-episode (> ~90 min) behavior under transcription/cleaning caps still unverified |
| Fast Facts | Narrow screening validation + Phase 11 stabilization | Broad deck semantic stability not claimed |

## Validated Runtime Paths

As of v4.48, all paths previously validated through v4.40 (Phase 10C survivability) remain validated:

- Single-instance Electron lock.
- Filesystem-first queue/history reconciliation.
- Queue corruption preservation.
- Completed-job protection from filesystem artifacts.
- Durable `<outputRoot>/process_registry.json`.
- Guarded process-group cleanup.
- Startup cleanup for stale tracked runner PIDs.
- Packaged app parity with current `electron/main.js`.

New for v4.48:

- Explanation panel renders `q.tables` / `q.metadata.tables` as an HTML table during quiz and review modes.
- Lecture-slide generator no longer emits the `"Table used for explanation only: <tableId>"` placeholder line.

## Remaining Risks

Carried forward from prior status, with the new chunk-planning entry added:

- **Lecture-slide chunk-planning silently drops Gemini short returns.** The attempted strict-count fix can burn the Gemini quota via recursive sub-chunking. Needs a quota-aware design (see NEXT_STEPS_PRIORITY).
- Fast Facts broad semantic generation remains unvalidated outside the narrow screening stabilization pass.
- Emma live generation can fail semantic validation even after normalized chunks are consumed.
- Semantic validators may reject legitimate source terms (the `dystocia` failure pattern).
- Images & Tables classification is heuristic.
- OCR quality depends on local `tesseract` and image quality.
- Large multimodal folders are not validated.
- Shared downstream generation is not complete.
- Live Gemini generation for Divine (Audio + Transcript) is field-validated as of v4.55 on a single 17.2 MB MP3; broader Divine episode variation and the packaged-app live audio run are unverified.
- OME packaged output writes under packaged resources; app-data migration is future work.

## Working Tree Notes At This Snapshot

- HEAD is `f3b2bc9` on `phase11-fastfacts-stability`.
- Working tree has untracked generated artifacts under `tools/lecture-slide-question-generator/output_assets/` and `tools/shared-ingestion/output/`. These are workflow/validation artifacts, not source-controlled docs. Leave untracked.
- The previous `PHASE_10A_UNCOMMITTED_CHECKPOINT.patch` snapshot was deleted during this hygiene pass — the work it captured was already committed across the v4.41–v4.47 tag line.
- `PROJECT_STATUS_2026-05-21.md` was moved to `docs/archive/`.
- `docs/RUNTIME_ARCHITECTURE_AUDIT_2026-05-21.md` was moved to `docs/archive/`. The runtime architecture it audits is largely still accurate at the structural level, but the surrounding git state in that document (main branch, v4.15 latest) is from before Phase 10C and Phase 11 work.
