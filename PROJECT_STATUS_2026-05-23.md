# Project Status 2026-05-23

Current stable tag: `v4.48-lecture-explanation-tables-stable`
Current branch: `phase11-fastfacts-stability`
Last committed HEAD: `f3b2bc9` (Render lecture-slide explanation tables instead of placeholder note)

Supersedes `docs/archive/PROJECT_STATUS_2026-05-21.md`.

## What Is New Since 2026-05-21

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

## What Was Investigated But NOT Fixed

### Lecture-slide chunk-planning silent-loss (live diagnosis 2026-05-23)

Symptom: same input PDF can produce 16 questions in one run and 7 in the next without any explanation in the report. `validationWarnings` and `validationErrors` come back empty in both cases. The generator silently accepts short Gemini returns.

Root cause: `call_generation_once` in `generate_lecture_slide_questions.py` passes `require_exact_count=False` to `extract_generated_question_items`. When Gemini returns fewer questions than the chunk's allocated count, the partial output is kept with only a `warn()` call to stderr. No retry, no sub-chunking, no escalation.

Attempted fix and rollback: flipping the flag to `True` causes the existing retry path to engage as designed (repair → sub-chunk in halves → single-slide attempts). A live test (`/private/tmp/chunk-fix-live-test-1779546582/`) confirmed the retry path engages correctly, but the recursion multiplier was enough to deplete the user's Gemini prepayment credits mid-run (HTTP 429). Once 429s started, every remaining slide got skipped. Final outcome was 0 questions, worse than the original 7. Change reverted in HEAD; packaged app rebuilt to match.

Open work item: implement a smarter recovery that does NOT cascade-multiply API calls. See `NEXT_STEPS_PRIORITY.md`.

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
| Divine Transcript | Shared-ingestion transcript profile validated | Live Gemini, audio, and transcription not validated |
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
- Live Gemini generation is not validated for Anki / OME / Divine Transcript.
- OME packaged output writes under packaged resources; app-data migration is future work.

## Working Tree Notes At This Snapshot

- HEAD is `f3b2bc9` on `phase11-fastfacts-stability`.
- Working tree has untracked generated artifacts under `tools/lecture-slide-question-generator/output_assets/` and `tools/shared-ingestion/output/`. These are workflow/validation artifacts, not source-controlled docs. Leave untracked.
- The previous `PHASE_10A_UNCOMMITTED_CHECKPOINT.patch` snapshot was deleted during this hygiene pass — the work it captured was already committed across the v4.41–v4.47 tag line.
- `PROJECT_STATUS_2026-05-21.md` was moved to `docs/archive/`.
- `docs/RUNTIME_ARCHITECTURE_AUDIT_2026-05-21.md` was moved to `docs/archive/`. The runtime architecture it audits is largely still accurate at the structural level, but the surrounding git state in that document (main branch, v4.15 latest) is from before Phase 10C and Phase 11 work.
