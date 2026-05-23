# Project Status 2026-05-23

Current stable tag: `v4.49-lecture-chunk-recovery-stable`
Current branch: `phase11-fastfacts-stability`
Last committed HEAD: `6c0ce4f` (Surface actionable cause when 0-question fatal exit is from quota exhaustion)

Supersedes `docs/archive/PROJECT_STATUS_2026-05-21.md`.

## What Is New Since 2026-05-21

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
