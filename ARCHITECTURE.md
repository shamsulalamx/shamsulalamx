# Architecture

Last updated: 2026-05-23

Current stable tag: `v4.48-lecture-explanation-tables-stable`.

This document describes the current architecture through v4.48. It carries forward the v4.16 baseline plus the validated OME and Divine Transcript dry-run BIC milestones, the Phase 10C survivability layer (tagged at v4.40), the Phase 11 Fast Facts stabilization work (v4.41–v4.47), and the lecture-slide explanation-table rendering (v4.48). It distinguishes validated behavior from intended convergence.

## System Overview

The app is a vanilla `index.html` application served through Electron over local HTTP. The app imports app-ready JSON into a local quiz database, persists metadata in localStorage, stores image data in IndexedDB `FigureStore`, and can be packaged as a Mac app.

The newer ingestion architecture adds a profile layer:

```text
source input
  -> source descriptor
  -> shared normalized chunk adapter
  -> source-specific downstream or attachment-first runner
  -> *_app_ready.json
  -> Batch Import Center output discovery
  -> existing JSON validation/import
  -> DB.createTest
  -> FigureStore image persistence
  -> quiz/review/scoring
```

## Shared Ingestion Layer

`tools/shared-ingestion/` contains the shared profile infrastructure:

- `source_descriptor.py`: declares source metadata.
- `normalized_chunk_schema.py`: defines `shared-normalized-chunk-bundle-v1`.
- `pipeline_adapter.py`: converts source artifacts into normalized chunks.
- `asset_router.py`: classifies and routes image/table references.
- `chunk_pipeline.py`: runs adapter emission and validation.
- Source runners such as `emma_profile_runner.py`, `mehlman_profile_runner.py`, `images_tables_profile_runner.py`, `anki_profile_runner.py`, and `ome_profile_runner.py`.

The layer is intentionally thin. It does not replace working generators unless a real abstraction gap has been proven.

## Source Descriptors

A descriptor records:

- `source_type`
- `modality`
- `extraction_style`
- `generation_style`
- `asset_policy`
- `cache_policy`
- notes and source-specific metadata

Current shared profile descriptors include:

- `emma_holiday_pdf`
- `mehlman_pdf`
- `images_tables_source`
- `anki_notes`
- `ome_pdf`
- `divine_transcript`

The descriptor is metadata plus routing intent. It is not a runtime schema fork.

## Normalized Chunks

The normalized bundle schema is `shared-normalized-chunk-bundle-v1`.

Top-level bundle fields:

- `schemaVersion`
- `sourceDescriptor`
- `sourceFile`
- `sourcePath`
- `createdAt`
- `chunkCount`
- `chunks`
- `warnings`

Chunk fields:

- `schemaVersion`
- `chunkId`
- `chunkType`
- `sourceType`
- `sourceFile`
- `sourceGrounding`
- `text`
- `textBlocks`
- `imageRefs`
- `tableRefs`
- `confidence`
- `metadata`
- `warnings`

Validated chunk types now include `text`, `slide`, `question`, `transcript`, `image`, and `table`.

## Downstream Reuse

Shared ingestion currently feeds existing downstream generators:

- Emma normalized chunks feed the lecture-slide generator.
- Mehlman normalized chunks feed the Mehlman generator.
- Images & Tables normalized chunks feed a deterministic attachment-first runner.
- Anki normalized text chunks hand off to the existing Anki wrapper only in selected-input dry-run mode.
- OME normalized text chunks hand off to the existing OME generator only in selected-input dry-run mode.
- Divine Transcript normalized transcript chunks hand off to the existing Divine generator only in selected-input dry-run mode.

NBME, AMBOSS, and Fast Facts still use existing source-specific downstream code. Do not rewrite those generators as part of profile onboarding unless the user explicitly requests it and validation supports the change.

## Anki Dry-Run Profile

Anki is a text/card-style shared profile. The current descriptor and thin adapter emit normalized `text` chunks from plain-text Anki exports while preserving card fields and source grounding. This profile does not assume MCQ structure at ingestion time.

The downstream milestone is intentionally dry-run only:

1. Shared ingestion emits normalized Anki text chunks.
2. `anki_profile_runner.py` invokes the existing Anki wrapper with one selected input in dry-run mode.
3. The wrapper emits app-ready JSON.
4. BIC discovers that output and the renderer accepts it through the existing NBME Gemini-style importer path.

The accepted app-ready JSON proves orchestration and import compatibility for placeholder dry-run output. It is not a live semantic generator milestone and does not validate live Gemini Anki generation or question quality.

## OME Dry-Run Profile

OME is a text-first PDF source. Its shared adapter reuses native text extraction through `pdfplumber`, emits normalized text chunks, and keeps the existing OME generator as the downstream boundary.

The validated BIC route is intentionally dry-run only:

1. Shared ingestion emits normalized OME text chunks.
2. `ome_profile_runner.py` calls the existing OME generator with one selected PDF, `--dry-run`, and a controlled output directory.
3. The generator emits app-ready JSON through the existing OME formatting path.
4. BIC discovers that JSON and the renderer imports it through the existing NBME Gemini-style importer path.

That path proves selected-input orchestration, import compatibility, quiz rendering, and persistence for placeholder dry-run output. It does not validate live Gemini OME generation or real OME question quality.

## Divine Transcript Dry-Run Profile

Divine Transcript is transcript-first. Its active shared profile accepts `.txt` and `.md` transcript inputs, emits normalized chunks with `chunkType: transcript`, and keeps the existing Divine generator as the app-ready output boundary.

The validated BIC route is dry-run only:

1. Shared ingestion emits normalized Divine transcript chunks.
2. `divine_transcript_profile_runner.py` calls the existing Divine generator with one selected transcript, `--dry-run`, and a controlled output directory.
3. The existing Divine generator emits app-ready JSON from that dry-run handoff.
4. BIC discovers that JSON and the renderer imports it through the existing importer path.

That path proves transcript-first dry-run orchestration, importer compatibility, packaged auto-import, and score history persistence for `.txt` and `.md` inputs. It does not add audio support or validate live Gemini Divine generation or transcription.

## Batch Import Center

BIC lives in:

- `tools/batch-import-center/pipeline_registry.json`
- `tools/batch-import-center/run_pipeline_job.py`
- Electron IPC handlers in `electron/main.js`
- Renderer UI in `index.html`

BIC responsibilities:

- Read the source registry.
- Select files or folders through Electron native dialogs.
- Write a job manifest.
- Spawn Python jobs.
- Stream progress events.
- Discover `*_app_ready.json` outputs.
- Read output JSON for import.
- Update job history.

BIC does not judge semantic quality. It proves orchestration, discovery, validation, and import wiring.

## App-Ready JSON Flow

The app imports app-ready JSON through existing JSON import helpers in `index.html`.

Two broad JSON shapes are used:

- NBME-style `testTitle` plus `questions`.
- Internal app-ready `questions[]` with compact fields such as `t`, `o`, `c`.

Images & Tables uses internal app-ready cards with canonical fields plus compact quiz fields. This path is validated because it preserves direct `q.images[]` and persists image data into `FigureStore`.

## Validation And Import Path

The validated import path is:

1. BIC discovers output.
2. Electron reads output JSON.
3. Renderer validates the JSON.
4. Renderer imports through `importValidatedBatchOutputJsonText`.
5. `DB.createTest` saves the test.
6. `_persistLandingJsonInlineImages` writes image `dataUrl` values into `FigureStore` and removes inline image data from saved questions.

This path is validated for Images & Tables profile in packaged app at v4.15.

## FigureStore And Persistence

`FigureStore` is IndexedDB storage for large image payloads. App question metadata keeps `figureKey`, not permanent base64 blobs. The stable image rendering path is:

```text
q.images[] or q.explanationImages[]
  -> figureKey
  -> FigureStore.get(figureKey)
  -> renderStoredImagesInto()
```

Do not reintroduce large `dataUrl` storage into localStorage.

## Electron And Python Orchestration

Electron main process owns native capabilities:

- Native file/folder picker.
- Python job spawning.
- Gemini environment propagation for sources that require Gemini.
- Packaged app serving.

Python runners own source extraction/generation. Renderer code owns import and quiz state. Keep this boundary.

## Cache Layers

Cache layers are source-specific:

- Fast Facts has an incremental generation cache foundation but semantic quality remains unstable.
- Shared descriptors expose `cache_policy`, but not every profile has a fully implemented cache.
- Images & Tables currently uses source asset hashes for deterministic asset naming, not a large scalable cache index.

## Provenance Metadata

Provenance is carried in:

- normalized chunk `sourceGrounding`
- normalized chunk `metadata`
- app-ready question `metadata`
- BIC completion reports

Emma normalized-chunk downstream carries chunk bundle hash/id/count into app-ready metadata. Images & Tables carries source path, chunk id, asset kind, classification reason, OCR availability, and attachment confidence.

## Variable-Choice Support

AMBOSS introduced variable-choice support in v4.5. This is a validated AMBOSS-specific behavior. Do not assume all sources use the same number of answer choices unless the target importer/generator has been verified for that source.

## Multimodal Ingestion Architecture

Images & Tables is the first validated image-first/table-first shared profile. It validates:

- image and table chunk emission
- OCR text preservation
- asset classification
- attachment-first app-ready JSON
- BIC auto-import
- FigureStore persistence
- image/table rendering after reload
- packaged `.app` behavior

It does not validate advanced semantic visual question generation, deep table parsing, or large-folder scaling.

## Lecture-Slide Explanation Table Rendering (v4.48)

The lecture-slide downstream now renders structured `q.tables` (with `q.metadata.tables` as a fallback) inline in the explanation block instead of emitting the placeholder line `"Table used for explanation only: <tableId>"`.

Renderer:

- `renderExplanationTablesInto(q, container)` in `index.html` builds an HTML `<table class="lab-table">` from `headers[]` and `rows[]`.
- Wired into both the Quiz IIFE explanation builder and `window.buildExplanationHTML` so review-mode rendering picks it up.
- Skips silently when neither location has populated table data.

Generator:

- `build_explanation_sections` in `generate_lecture_slide_questions.py` no longer extends `extras` with `table_notes`.
- Section heading renamed `"Slide Figures and Tables"` → `"Slide Figures"`.

Validated for the Test_Emma fixture (3-column / 3-row table) in packaged `shamsulalamx.app`. Not validated across all Emma decks.

## Phase 10C Survivability Layer (v4.40)

The Batch Import queue system is hardened against process restarts, single-instance violations, and filesystem inconsistencies:

- Single-instance Electron lock (`requestSingleInstanceLock`).
- Queue corruption preservation.
- Filesystem-first queue/history reconciliation (`reconcileQueueAndHistoryOnStartup`).
- Completed-job protection from spurious filesystem artifacts.
- Durable `<outputRoot>/process_registry.json`.
- Guarded process-group cleanup.
- Startup cleanup for stale tracked runner PIDs.
- Packaged app parity with current `electron/main.js`.

These layers are required for any claimed BIC survivability behavior. Do not casually change them.

## UOGA Core Package (Phase 11)

`core/uoga/` is the Unified Organic Generation Architecture. It is currently graph-native only for `fast_facts_pptx`; every other organic source raises "not graph-native, cannot run in hybrid mode."

Modules:

- `execution_graph.py` — authoritative chunk graph with state and attempt tracking.
- `retry_engine.py` — bounded retry plan (`initial` → `repair` → `fallback`).
- `finalization.py` — deterministic single-emission `JOB_COMPLETE` gate.
- `telemetry_engine.py` — UOGA-restricted chunk events with heartbeat thread.
- `review_artifacts.py` — durable review draft writer.
- `job_contracts.py` — pipeline-route classification and chunk-event contracts.
- `validation_engine.py` — chunk accounting and cardinality reconciliation.

Domain boundaries are enforced by `scripts/uoga_dependency_graph_validator.py`:

- EXTRACTIVE and HYBRID may not depend on UOGA.
- SHARED may not depend on any runtime domain.
- `ExecutionGraph`, `CHUNK_*` symbols, and `retry_engine` are UOGA-only.

`tools/chunk_telemetry.py` is a compatibility shim that re-exports the UOGA telemetry engine for legacy callers.

## UWorld-Family Chunking And Token Headroom (v4.52, field-validated 2026-05-23)

The five UWorld-wrapping generators (UWorld, OME, Mehlman, Divine, Anki) all reuse `split_into_chunks()` and `_raw_gemini_call()` from `tools/uworld-notes-question-generator/generate_uworld_questions.py` via `import generate_uworld_questions as _uw`. Two long-standing bugs in that shared machinery were diagnosed and fixed at v4.52:

- **Chunking force-slice.** `split_into_chunks(text, max_chars=3000)` now always honors its `max_chars` cap. After heading-based and paragraph-based splits, any remaining chunk that exceeds `max_chars` is force-sliced at the nearest single-newline boundary, falling back to whitespace, then a hard byte boundary. Before this fix, inputs with no `\n{2,}` boundaries (Anki .txt exports where each card is one tab-separated line) collapsed to a single chunk regardless of size.
- **Token headroom.** `_raw_gemini_call()` `maxOutputTokens` raised 8192 → 16384. Gives ~2x headroom for chunks that ask Gemini for multiple full-JSON questions in a single response. The lecture-slide generator already used 12000 for comparison.

Together these fixes prevent the truncation pattern that produced 0 questions on the user's first live Anki BIC run. They apply automatically to OME, Mehlman, Divine, Anki, and UWorld. The lecture-slide generator is a separate codebase and is unaffected.

## Stem-Quality Contract Across Organic Generators (v4.51, field-validated 2026-05-23)

All six organic generation paths now enforce the same stem-format contract: every generated question's stem must end with a clear final question sentence that ends in `?`. The contract is enforced in two places:

- **Prompt level.** All six prompt files (`lecture-slide` + `uworld-notes` + `ome` + `mehlman` + `divine` + `anki`) carry a `STEM FORMAT RULES` block with the same wording: "Every stem must end with a clear final question sentence. No exceptions. The final sentence must ask the learner to choose one best answer and must end with a question mark." Acceptable wording examples are provided.

- **Validator level.** The `lecture-slide` generator has its own `stem_quality_errors()` validator. The five UWorld-wrapping generators (`uworld-notes`, `ome`, `mehlman`, `divine`, `anki`) share `validate_question()` in `tools/uworld-notes-question-generator/generate_uworld_questions.py`. That validator now invokes `stem_has_explicit_final_question(stem)` which walks the final sentence, requires it to end in `?`, and requires it to contain a recognizable one-best-answer prompt (`which of the following`, `next step`, `most appropriate`, etc.). Failing questions go through the existing repair-retry path; if repair still fails, the question is kept with `extractionWarnings` rather than silently dropped.

The validator is intentionally a separate concern from the v4.49 chunk-planning recovery layer. v4.49 protects against silent question loss at the chunk boundary; the v4.51 stem-quality contract protects against well-formed questions that lack a proper final question sentence. Both must remain wired for the full safety net.

## Review-Survivor Canonicalization Layer (v4.50, field-validated 2026-05-23)

When a BIC run produces some questions that pass validation and some that need human review, the validated set is auto-imported into a new library test immediately. The user later opens the review draft, accepts (and optionally edits) the questions that need review, and the renderer asks Electron to produce an "accepted survivor" JSON which is then imported through the normal BIC import path.

Two important properties of that survivor path:

1. **Canonical schema.** The `write-accepted-review-survivors` IPC handler in `electron/main.js` runs each accepted question through `canonicalizeReviewedSurvivorQuestion()` before serializing. That helper invokes `assembleReviewedQuestionExplanationSections()` to build the canonical `explanationSections[]` array from the raw Gemini-shape fields (`correctExplanation`, `incorrectExplanations`, `educationalObjective`) and fills in empty `figureRefs` / `images` / `explanationImages` / `tables` arrays. Without this step the renderer (which reads only from `explanationSections[]`) would show an empty explanation panel.

2. **Append to existing test.** The renderer's `importValidatedBatchOutputJsonText()` accepts an `appendToTestId` destination option. When set and the referenced test exists, the imported questions are renumbered to continue from the existing test's question count and merged via `DB.updateTest()` instead of creating a parallel test. `_persistLandingJsonInlineImages` then walks the merged test so `FigureStore` keys stay unique per `(testId, questionNumber)`. `importAcceptedBatchReviewQuestions()` passes `appendToTestId = job.importedTestId || job.report.importedTestId || job.report.acceptedSurvivorsImportedTestId`. Falls back to creating a new test (with a status warning) if the referenced test was deleted between auto-import and review-import.

These two together mean that a BIC run with N validated + M reviewed-accepted questions produces ONE library test with N+M questions, all carrying the canonical schema. The pattern is portable to any future source that adopts the review-survivor flow.

## Lecture-Slide Chunk-Planning Recovery Layer (v4.49, field-validated 2026-05-23)

The lecture-slide generator now defends against two failure modes that previously caused silent question loss:

**Quota-aware retry stop.** `is_quota_failure(error)` classifies HTTP 429, `RESOURCE_EXHAUSTED`, prepayment-depleted text, and similar quota signals. The first occurrence latches a module-level `_QUOTA_EXHAUSTED` flag. Every retry boundary checks the latch:

- `generate_question_chunk_with_retries` — bails at the start, after attempt0, after retry1_repair, before sub-chunk recursion, and between sub-chunk siblings.
- `generate_questions` — skips remaining chunks in the main loop and skips the entire recovery loop.
- `retry_missing_slide_questions` — bails at the start and between attempts.

The latch is reset at the top of each `generate_questions` invocation so multiple runs in the same process stay independent.

**Targeted missing-slide recovery.** The main chunk loop still uses partial-accept (`call_generation_once` default `require_exact_count=False`) so a Gemini short return does NOT cascade into recursive sub-chunking — that cascade was what previously burned the budget. After all chunks complete, `generate_questions` computes per-slide deficit (allocated vs accepted) and calls `retry_missing_slide_questions()` for each under-delivered slide. That function makes up to `MAX_RECOVERY_ATTEMPTS_PER_SLIDE` (=2) focused single-slide calls with `require_exact_count=True`, so a short single-slide return raises and triggers the next attempt rather than being accepted silently.

Worst-case extra API cost: `len(allocations_with_questions) * 2`. Bounded by design.

Status: tagged `v4.49-lecture-chunk-recovery-stable` (commits `1c1f744` + `6c0ce4f`). Field-validated 2026-05-23 on Test_Emma BIC live run (job `batch-mpis1xxn-c0i3id`): 18 allocated → 17 generated (94.4%); targeted recovery loop fired for 5 short-returning slides and successfully recovered 4 of them; the 5th stopped cleanly on a Gemini network timeout via the existing `is_network_failure` check. Auto-import and v4.48 inline table rendering both verified in the same run (4 questions carry inline tables; test imported as "Test Emma Lecture Questions"). Quota-aware retry stop was independently field-validated on an earlier depleted-credits run (job `batch-mpirtu3n-1cfsur`): single HTTP 429 caught on chunk1 attempt0, all subsequent retries skipped, runtime 10.5s vs the prior naive-cascade's 148s.
