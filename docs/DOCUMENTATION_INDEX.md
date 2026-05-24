# Documentation Index

Last updated: 2026-05-24

Use this page to decide which project document is current before reading older handoffs or milestone notes.

## Authoritative Current Docs

| Doc | Role |
|---|---|
| `PROJECT_CONTEXT.md` | Durable project rules, current source-of-truth boundaries, validation discipline |
| `PROJECT_STATUS_2026-05-24.md` | Current high-level state snapshot |
| `MIGRATION_HANDOFF.md` | Current continuation handoff and rollback notes |
| `ARCHITECTURE.md` | Current app, ingestion, importer, Electron, persistence, UOGA, Phase 10C, and v4.48 table-rendering architecture |
| `BATCH_IMPORT_ARCHITECTURE.md` | Batch Import Center ownership, workflow boundary, Phase 10C survivability, BIC job output root redirection |
| `SHARED_INGESTION_ARCHITECTURE.md` | Shared descriptor, normalized-chunk, and profile boundary |
| `VALIDATED_PIPELINES.md` | Validation matrix and source-specific evidence limits (current through v4.48) |
| `KNOWN_LIMITATIONS.md` | Known gaps and non-claims (includes the chunk-planning silent-loss issue diagnosed 2026-05-23) |
| `NEXT_STEPS_PRIORITY.md` | Current prioritized work queue (chunk-planning quota-aware recovery is top item) |
| `GIT_TAG_HISTORY.md` | Stable milestone and rollback tag history through v4.48 |

Current runtime safety baseline: `v4.40-phase10c-survivability-stable`. Current development head: `v4.67-drive-sync-hardening-stable`. Current docs should describe the Batch Import queue system as the Phase 10C survivability system, reconciliation as filesystem-first plus queue/history merge, runtime safety layer as process registry plus cleanup system, the lecture-slide generator as having quota-aware retry stop + targeted missing-slide recovery (v4.49), the review-survivor import path as canonicalized + merge-into-existing-test (v4.50), all six organic generators as enforcing an explicit-final-question stem-quality contract (v4.51), OME as having a live BIC generation path (v4.51), Anki as having a live BIC generation path (v4.52), the shared UWorld machinery as having proper chunk-size enforcement plus 16384-token output headroom (v4.52), the UWorld-family wrappers as having full parity with the lecture-slide generator for the review-survivor flow (v4.53), and the UWorld-family wrappers as having full parity with the lecture-slide generator for the chunk-planning quota-aware retry stop and per-chunk shortfall recovery (v4.54).

## Current Supporting Docs

| Doc | Role |
|---|---|
| `README.md` | User-facing project overview, deployment modes, supported sources, build commands |
| `KNOWN_GOOD_WORKFLOWS.md` | Workflow commands and known reference paths |
| tool `README.md` files | Source-specific tool entrypoints and output conventions |
| `GROUPED_QUESTION_DEBUG_PROMPT.md` | Specialized grouped-question debugging guidance |
| `PARSER_DEBUG_PROMPT.md` | Specialized parser debugging guidance |

## Archive Policy

`docs/archive/` holds superseded project status snapshots, older migration notes, older architecture summaries, stale pipeline plans, and detailed legacy references that remain useful for history. Archived docs are not current project truth unless a current doc explicitly cites a historical fact from them.

Notable archive entries:

- `docs/archive/PROJECT_STATUS_2026-05-21.md` — superseded by `docs/archive/PROJECT_STATUS_2026-05-23.md`.
- `docs/archive/PROJECT_STATUS_2026-05-23.md` — superseded by `PROJECT_STATUS_2026-05-24.md`.
- `docs/archive/RUNTIME_ARCHITECTURE_AUDIT_2026-05-21.md` — historical runtime audit. Structural claims about Electron / preload / renderer / BIC ownership are still accurate, but its git-state header (latest tag `v4.15`, branch `main`) predates Phase 10C and Phase 11 work and should not be quoted as current.

Generated outputs under tool `output_json/`, `reports/`, and shared-ingestion `output/` are workflow artifacts or validation evidence. Do not delete them as documentation clutter without checking tracked status, references, runtime discovery paths, and the validation milestone they support.
