# Known Limitations

Last updated: 2026-05-23

Current stable tag: `v4.48-lecture-explanation-tables-stable`.

## UWorld-Family Review-Survivor Flow (RESOLVED 2026-05-23, tagged v4.53)

History:

Before v4.53, the review-survivor flow that lets the user accept / edit / reject questions that failed validation only existed in the lecture-slide generator (Fast Facts / Emma / AMBOSS) via the v4.50 review-survivor work. The UWorld-wrapping generators (Anki, OME, Mehlman, Divine, UWorld) fell back to keeping failed-repair questions with `extractionWarnings` appended — visible in the imported test's metadata but never surfaced for human review. Identified as a gap by the user after the v4.52 Anki run finished 15/15 clean ("if it returns 12/15, I should be able to review then accept/reject/edit the failed ones just like for Emma, right?"). At v4.52 the answer was no; at v4.53 the answer is yes.

Resolution (tagged `v4.53-uworld-family-review-survivor-stable`, commit `8f213d5`):

Single source change in `tools/uworld-notes-question-generator/generate_uworld_questions.py` (the shared UWorld machinery that OME, Mehlman, Divine, Anki, and UWorld all import via `import generate_uworld_questions as _uw`):

- New `write_uworld_family_review_draft()` helper writes a `uworld_family_review_draft.json` matching the same schema BIC's `discover_review_draft()` and the renderer's `read-review-draft` IPC handler already expect for the lecture-slide generator (`draftVersion: 1`, `status: "needs_review"`, populated `candidateQuestions[]`, empty `validQuestionIndexes[]`, `reviewItems[]` with per-question error messages and `chunkIndex`).
- New `_resolve_review_dir()` helper picks `BIC_JOB_OUTPUT_ROOT/review` when BIC sets that env var, falls back to `BASE_DIR/review` for standalone CLI. Computed at call time so per-wrapper `BASE_DIR` monkey-patching is honored.
- `call_gemini_with_retry()` gained an optional `needs_review_collector` parameter. When set, questions that fail BOTH initial validation AND repair are appended to it instead of being added to the returned `questions` list with `extractionWarnings`. When None (the historical default), behavior is backward-compatible.
- `process_file()` initializes `needs_review_entries: List[Dict] = []` at the top, always passes it to `call_gemini_with_retry`, and after the chunk loop calls `write_uworld_family_review_draft()` when the list is non-empty.

End-to-end behavior for a partial-failure run:

- The N − K clean / repair-succeeded questions go into the app-ready output as before; BIC auto-imports them as a new test.
- The K failed-repair questions go into `<BIC_JOB_OUTPUT_ROOT>/review/uworld_family_review_draft.json`.
- BIC's `discover_review_draft()` picks it up unchanged (it scans `<jobOutputRoot>/review/*_review_draft.json`).
- The renderer's existing BIC review modal surfaces the K candidates.
- User accepts / edits / rejects through the v4.50 review-survivor flow.
- Accepted candidates go through `canonicalizeReviewedSurvivorQuestion()` (already-canonical UWorld-family questions pass through unchanged) and merge into the same auto-imported test via the v4.50 `appendToTestId` path.

No regression for the clean case: if all questions pass (the user's v4.52 Anki run was 15/15 clean), the collector stays empty, no review draft is written, and BIC behaves exactly as it did at v4.52.

Offline-validated:

- `write_uworld_family_review_draft()` with empty input returns None; with 2 entries it writes a valid `uworld_family_review_draft.json` matching the BIC schema.
- `_resolve_review_dir()` routes correctly with and without `BIC_JOB_OUTPUT_ROOT`.
- Syntax check passes.

Not field-validated by this milestone: the failure path itself requires Gemini to produce a question that fails both initial validation and repair on a live run. The user chose to wait for it to happen organically rather than synthesizing now.

Migration note: forward-only. Any pre-v4.53 partial-failure run already silently included failed-repair questions in the app-ready output with `extractionWarnings`. Those tests are unaffected; the new flow applies only to subsequent runs.

## Anki Live BIC Generation Plus Cross-Generator Chunking And Token-Cap Fix (RESOLVED 2026-05-23, tagged v4.52)

History:

The user's first live Anki BIC run on a 15-card .txt (32,803 chars) produced 0 questions even though BIC orchestration ran cleanly to completion. The Anki wrapper's output had an empty `questions` array and one `extractionWarning` reading `Chunk 1 JSON parse error: Expecting value: line 1 column 2 (char 1)`. The Gemini response was wrapped in markdown fences AND truncated mid-string at 23 KB, so all three JSON cleanup stages failed.

Two compounding bugs were diagnosed in the shared UWorld machinery (which OME, Mehlman, Divine, Anki, and UWorld all reuse via `import generate_uworld_questions as _uw`):

1. **`split_into_chunks()` silently bypassed its own `max_chars=3000` cap.** The function's "paragraph-boundary fallback" re-splits on `\n{2,}` — the same boundary that already produced the segment list. When the input has no double-newlines (which Anki .txt exports usually don't — each card is one tab-separated line), the segment list is one big block and the fallback returns `[seg]` unchanged. The 32 K Anki text collapsed to one chunk that asked Gemini for all 15 questions in a single response.

2. **`_raw_gemini_call()` set `maxOutputTokens=8192`.** Asking for 15 questions worth of JSON in a single chunk needs ~22 K tokens. Gemini truncated mid-string. The 3-stage JSON cleanup (`_clean_llm_json` → `_extract_json_payload` → final raw retry) cannot recover invalid (truncated) JSON.

Resolution (tagged `v4.52-uworld-chunk-and-token-fix-stable`, commits `f99ded6` + `3772d7a`):

- **Anki BIC enablement** (`tools/shared-ingestion/anki_profile_runner.py` + `tools/batch-import-center/pipeline_registry.json`): same OME-pattern fix from v4.51. Runner now has `--mode {dry-run, generate}` and always invokes the downstream wrapper. Registry's `anki_notes` entry has `requiresGemini: true` and `liveSteps` invoking `--mode generate --limit 0` with 60s heartbeat. Distinct output subdirs for live vs dry-run.

- **UWorld chunking + token fix** (`tools/uworld-notes-question-generator/generate_uworld_questions.py`): `split_into_chunks()` gains a force-slice pass after heading and paragraph splits. Any chunk that still exceeds `max_chars` is sliced at the nearest single-newline boundary, falling back to whitespace, then a hard byte boundary. `_raw_gemini_call()` `maxOutputTokens` raised 8192 → 16384 for ~2x headroom even when per-chunk question counts are uneven. The lecture-slide generator already uses 12000 for comparison and was unaffected.

Field-validated on user's 15-card Anki .txt: 15 questions generated cleanly with proper stems, choices, and explanations. Offline test of the chunking fix exercised a 281 K synthetic input with no double-newlines and got 94 properly-sized chunks (all ≤ 3000 chars).

Migration note: any test imported via the buggy pre-v4.52 live Anki BIC path will have 0 questions or partial truncated questions. Re-run with the new build.

## Organic-Generator Stems Missing Final Question Sentence (RESOLVED 2026-05-23, tagged v4.51)

History:

The user's first live OME BIC run produced 7 questions where none of the stems ended with a question mark — every vignette stopped mid-narrative without a one-best-answer prompt, so the user could not tell what each question was asking. Same class of bug Fast Facts hit previously and was thought to be fixed for all organic generators, but the prior fix only landed in the lecture-slide generator (which serves Fast Facts, Emma, and AMBOSS). OME, UWorld, Mehlman, Divine, and Anki all had neither the prompt rule nor a stem-quality validator.

Resolution (tagged `v4.51-stem-quality-and-ome-live-stable`, commit `4b2d847`):

1. **Stem-quality validator** in `tools/uworld-notes-question-generator/generate_uworld_questions.py`. Adds `stem_has_explicit_final_question(stem)` and supporting helpers. Wired into `validate_question(q)`: a stem that doesn't end with '?' or doesn't contain a recognizable one-best-answer prompt (`which of the following`, `next step`, `most appropriate`, etc.) is rejected. The existing repair-retry path then re-asks Gemini. If repair still fails, the question is kept with `extractionWarnings` rather than silently dropped. Because OME, Mehlman, Divine, and Anki all monkey-patch `_uw.PROMPT_FILE` and reuse this `validate_question()`, the fix takes effect across all 5 wrapping generators.

2. **STEM FORMAT RULES** block added to all 5 prompt files (`notes_to_questions_prompt.txt`, `ome_to_questions_prompt.txt`, `mehlman_pdf_to_questions_prompt.txt`, `divine_audio_to_questions_prompt.txt`, `anki_notes_to_questions_prompt.txt`). Same wording as the lecture-slide prompt: every stem must end with a clear final question sentence ending in '?', with acceptable wording examples.

Field-validated on user's small OME PDF live BIC run: generated questions now end with proper "Which of the following is the most likely diagnosis?" / "What is the most appropriate next step?" style sentences. The lecture-slide generator (Fast Facts, Emma, AMBOSS) already had both halves; all 6 organic generation paths now enforce the same stem-format contract.

Migration note: any test imported via the buggy pre-v4.51 path still has stems without final question sentences. Re-running the source through BIC with the new build produces the correct shape; for one-off recovery without re-running Gemini, the existing data is unsalvageable (the missing final sentence cannot be inferred from what was emitted).

## OME Live Generation Through BIC (NEW capability, validated 2026-05-23, tagged v4.51)

The OME source was previously dry-run only through BIC by design — the `ome_pdf` registry entry pointed `liveSteps` at the same dry-run handoff. v4.51 enables live Gemini OME generation:

- `tools/shared-ingestion/ome_profile_runner.py` gained `--mode {dry-run, generate}` following the Emma runner pattern. The old `--emit-app-ready-dry-run` flag is kept as a backward-compatible alias for `--mode dry-run`. Default `--limit` changed from 5 to 0 so a live run processes the full PDF. Dry-run and live outputs land in separate subdirs (`ome_app_ready_dry_run/` and `ome_app_ready_live/`).
- `tools/batch-import-center/pipeline_registry.json` `ome_pdf` entry now has `requiresGemini: true`, `liveSteps` that invoke `--mode generate --limit 0` with heartbeat 60s, and `outputDirectories` listing both live and dry-run subdirs so BIC output discovery works for either mode.

Field-validated on user's small OME PDF live BIC run (alongside the stem-quality fix). Implementation work was authored in a prior cowork session; today's run was the first end-to-end live BIC validation.

Not validated yet:

- Broad OME PDF variety. The validated run used a small user-supplied OME PDF.
- Asset extraction quality for OME (figures and tables present in the source).
- Signed / notarized distribution behavior of the live OME output paths.
- Allocated-vs-generated parity check for OME (analogous to the lecture-slide chunk-planning audit at v4.49) — if OME ever short-returns, the same recovery pattern would need porting to `generate_ome_questions.py`. The stem-quality validator and existing UWorld repair path do catch missing final questions, but not silently-lost questions at the chunk boundary.

## Fast Facts Review-Survivor Import Bugs (RESOLVED 2026-05-23, tagged v4.50)

History:

A small Fast Facts PPTX produced 1 validated question (auto-imported as a new test) and 2 questions that needed human review. After the user accepted both reviewed questions, two problems surfaced:

1. **Wrong test target.** The 2 accepted-reviewed questions landed in a separate new test instead of being merged into the existing auto-imported test for the same BIC job. The user expected one 3-question test; the library showed a 1-question test plus a parallel 2-question test.

2. **Missing explanations for wrong answers.** The 2 reviewed-accepted questions had empty `explanationSections[]` and so rendered with no explanations at all, violating the canonical schema. The raw Gemini fields (`correctExplanation`, `incorrectExplanations`, `educationalObjective`) WERE present on the question objects, but the renderer reads only from the canonical `explanationSections[]` shape and has no fallback. The lecture-slide generator normally runs a `build_explanation_sections()` step that assembles `explanationSections[]` from the raw fields, but the review-survivor write path skipped that step because it copied questions straight from the review draft's `candidateQuestions` list.

Resolution (tagged `v4.50-fastfacts-review-merge-stable`, commit `64a8e14`):

1. **`electron/main.js`** gained `assembleReviewedQuestionExplanationSections()` and `canonicalizeReviewedSurvivorQuestion()`. The `write-accepted-review-survivors` IPC handler runs every accepted question through the canonicalizer before serializing the survivor JSON. The output now carries assembled `explanationSections[]` plus empty `figureRefs`/`images`/`explanationImages`/`tables` arrays, matching the shape the renderer import path expects.

2. **`index.html`** `importValidatedBatchOutputJsonText` now accepts an `appendToTestId` destination option. When the referenced test exists, the new questions are renumbered to continue from the existing question count and merged via `DB.updateTest()` instead of `DB.createTest()`. `_persistLandingJsonInlineImages` then runs against the merged test so `FigureStore` keys stay unique per `(testId, questionNumber)`. The renderer's `importAcceptedBatchReviewQuestions` passes `appendToTestId = job.importedTestId || job.report.importedTestId || job.report.acceptedSurvivorsImportedTestId`. Falls back to creating a new test (with a status warning) if the referenced test was deleted between auto-import and review-import.

Field-validated on the user's small Fast Facts PPTX BIC live run: 1 validated question auto-imported as a new test, 2 reviewed questions appended to that same test on accept, all 3 visible together in one library test with full Correct + Incorrect + Educational Objective sections.

Migration note for the leftover state from the buggy run:

The fix is forward-only. Any test imported via the buggy review-survivor path before `v4.50` will still have:

- A separate parallel test in the library for the reviewed-accepted questions.
- Empty `explanationSections[]` on those reviewed questions.

The raw `correctExplanation` / `incorrectExplanations` data is preserved in the corresponding `accepted_survivors_app_ready.json` file under the BIC job's `review/` directory, so a one-shot recovery is possible (read the survivor JSON, run it through the new canonicalizer, append to the originally-intended test, delete the orphan). Easier path: delete the orphan test and re-run the PPTX through BIC with the new build.

## Lecture-Slide Chunk-Planning Silent Loss (RESOLVED 2026-05-23, tagged v4.49)

History:

The lecture-slide generator originally accepted short Gemini returns silently. In `call_generation_once`, `extract_generated_question_items` was called with `require_exact_count=False`. When Gemini returned fewer questions than the chunk's allocated count, the partial output was kept with only a `warn()` call to stderr — no retry, no surfaced error. Diagnosed 2026-05-23: the same Test_Emma input produced 16 questions in one BIC run and 7 in the next (chunk1 returned 4 of 8 expected, chunk2 returned 3 of 5 expected).

A naive strict-count flip was attempted and reverted: it engaged the existing recursive retry path (repair → halve → single-slide), but the recursion multiplier was aggressive enough to deplete a Gemini prepayment budget mid-run. Live test outcome was 0 questions for the same input.

Resolution (tagged `v4.49-lecture-chunk-recovery-stable`, commits `1c1f744` + `6c0ce4f`):

Two complementary changes in `tools/lecture-slide-question-generator/generate_lecture_slide_questions.py`:

1. **Quota-aware retry stop** — `is_quota_failure(error)` detects HTTP 429 / `RESOURCE_EXHAUSTED` / prepayment-depleted text. A module-level `_QUOTA_EXHAUSTED` latch is set on first occurrence. Every retry boundary in `generate_question_chunk_with_retries` (initial-attempt failure, repair-retry failure, sub-chunk recursion, single-slide recursion) and the cross-chunk loop in `generate_questions` checks the latch and bails to `[]` instead of making more API calls. Field-proven on 2026-05-23 by the depleted-credits run: 1 HTTP 429 caught, all further retries skipped, runtime 10.5s vs 148s for the naive cascade.

2. **Targeted missing-slide recovery** — the chunk loop still uses partial-accept (`require_exact_count=False`) to preserve the historical behavior that prevents unbounded sub-chunking. After all chunks complete, `generate_questions` compares allocated-vs-generated counts per slide and calls `retry_missing_slide_questions()` for each under-delivered slide. That function makes up to `MAX_RECOVERY_ATTEMPTS_PER_SLIDE` (=2) focused single-slide attempts with `require_exact_count=True`. Bounded worst-case extra API calls: `len(work) * 2`. Field-validated on Test_Emma BIC live run (job `batch-mpis1xxn-c0i3id`): 18 allocated → 17 generated, recovery loop fired for 5 short-returning slides, 4 successfully recovered, 1 stopped cleanly on a Gemini network timeout via the existing `is_network_failure` check.

Bonus: when a run ends with 0 questions because the quota latch fired, the fatal `PipelineError` message now names the cause and points the user at the billing fix instead of bubbling up as the generic "Existing Emma generator exited with code 1."

Residual considerations:

- Per-slide deficit tolerance is bounded by `MAX_RECOVERY_ATTEMPTS_PER_SLIDE` (currently 2). A slide that systematically fails this many attempts is dropped with a clear warning. Tune up if specific decks consistently see >1 dropped slide.
- This fix is in the lecture-slide generator only. The OME generator (`tools/ome-pdf-question-generator/generate_ome_questions.py`) and other source-specific generators have their own paths and have NOT been audited for the same class of silent-loss bug. Worth checking allocated-vs-generated parity the first time you live-test each.

## Fast Facts Validation Limit

Fast Facts has a narrow screening stabilization pass beyond the v4.4 cache foundation. Diagnostic reporting, a `--fast-facts-question-limit` cap, the observed Turner Syndrome screening-test ontology fix, and a visible Electron dev BIC live run were validated on one small PPTX. That run produced one final app-ready question and passed auto-import, render, score, and reload persistence.

This does not prove broad Fast Facts semantic stability, all-deck coverage, or packaged validation for the fix. The BIC registry path is currently capped at 3 attempted questions for stabilization mode. A fresh dev profile can still show the global renderer alert `Gemini key missing` while the BIC batch path has the injected Gemini key and generates successfully; that is a later UI consistency issue, not a Fast Facts blocker.

## Semantic Validator Fragility

Semantic validators can reject legitimate medical vocabulary. The Emma live run reached downstream generation and consumed normalized chunks, but semantic validation rejected Q1 for unsupported term `dystocia`. This is an unresolved validator/generation quality issue.

## OCR Limitations

OCR depends on source quality and local tooling. Images & Tables uses local `tesseract` when available. Poor screenshots, unusual fonts, low contrast, and dense tables can reduce OCR quality. OCR success does not prove semantic understanding.

## Image Classification Heuristics

Images & Tables classification is currently heuristic. It uses filename and OCR text signals to classify assets as `stem_image`, `table_image`, `algorithm`, `chart`, or `unknown`. It does not perform deep visual reasoning.

## Source-Specific Assumptions

Each source still has source-specific assumptions:

- AMBOSS uses its existing extraction path.
- NBME depends on OCR/chunking behavior and figure conventions.
- Emma uses lecture-slide downstream semantics.
- Mehlman assumes text-heavy PDF structure.
- Images & Tables assumes small image sets.
- Fast Facts has a narrow screening stabilization pass only; broad semantic quality remains unvalidated.

## Unvalidated Scaling Behavior

Large source runs are not validated for every profile. The current Images & Tables validation used a small 5-image set. Large-folder behavior, memory pressure, and UI import performance are unresolved.

## Large-Folder Limitations

Images & Tables folder ingestion is shallow and intentionally limited. It does not recursively crawl nested folders. It should be validated with 2-5 assets first.

## Anki Dry-Run Limitations

The validated Anki BIC path is a dry-run handoff. Its current app-ready questions are placeholders.

- Live Gemini Anki generation is not enabled through BIC.
- Real-world Anki export variation is not broadly validated.
- `.apkg` imports are unsupported.
- Media references and HTML variation are not validated.
- The global `schemaVersion` and `questionCount` warning contract remains unresolved.

## OME Dry-Run Limitations

The validated OME BIC path is dry-run only. Its current app-ready questions are placeholders.

- Live Gemini OME generation is not enabled through BIC.
- Real semantic OME question quality is not validated.
- Real OME PDFs beyond the tracked synthetic fixture are not validated.
- OME asset extraction has not been validated with the controlled output path.
- Packaged OME output currently writes under packaged resources. Moving generated output to a writable app-data location is future work.
- Signed or notarized distribution behavior and non-writable packaged resource tree behavior are not validated.

## Divine Transcript Dry-Run Limitations

The validated Divine Transcript BIC path is transcript-first and dry-run only.

- Audio files are not supported yet through the Divine Transcript BIC source, including `.mp3`, `.wav`, and `.m4a`.
- Live Gemini Divine generation is not enabled through BIC.
- The current Divine dry-run app-ready output keeps `sourceFormat: divine-audio` even when the selected input is a transcript.
- Packaged Divine dry-run outputs currently write under packaged resources.
- Only synthetic `.txt` and `.md` transcript fixtures are validated; real-world transcript variation is unvalidated.
- Audio ingestion, transcription, Whisper, local speech models, and Gemini audio transcription are not part of this validated path.
- Transcript chunks preserve structure and provenance but do not prove semantic medical quality.
- Retrieval, clustering, images, and assets remain out of scope.

## Remaining Multimodal Gaps

Open multimodal gaps:

- deep table parsing into rows and columns,
- visual grounding beyond OCR/filename heuristics,
- multi-asset question grounding,
- confidence calibration,
- scalable asset cache indexing,
- semantic question generation from images/tables.

## Packaged Resource Path Differences

Packaged app jobs run from app resources. A workspace path and a packaged resource path are not always the same. Existing-output validation mode handles this for selected app-ready JSONs, but future source-specific file references should still be tested in the packaged app.

## Shared Architecture Incomplete

The shared profile architecture is active but incomplete. Anki, OME, and Divine Transcript have validated dry-run shared profiles and BIC handoffs, while UWorld is not fully migrated into shared ingestion. Do not delete existing source-specific flows.
