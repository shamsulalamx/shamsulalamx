# Project Status 2026-05-23

Current stable tag: `v4.55-divine-audio-live-stable`
Current branch: `phase11-fastfacts-stability`
Last committed HEAD: doc commit landing alongside the v4.55 source commit.

Supersedes `docs/archive/PROJECT_STATUS_2026-05-21.md`.

## What Is New Since 2026-05-21

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
| AMBOSS | BIC live path stable | Variable-choice support and live import path tagged stable |
| Emma Holiday | Shared profile + normalized-chunk downstream stable; explanation tables now render (v4.48) | BIC existing-output import validated; live generation has separate semantic blocker risk and chunk-planning silent-loss risk |
| Mehlman | Shared-ingestion live profile stable | Tagged v4.12 |
| NBME | BIC orchestration stable | Tagged v4.8; legacy NBME import/image workflows have earlier validation |
| Images & Tables | Shared-ingestion profile stable | Packaged image/table rendering, FigureStore persistence, score, reload validated |
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
