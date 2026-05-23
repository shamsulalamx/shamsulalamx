# Documentation Archive

Last updated: 2026-05-23

This directory contains historical documents that were moved out of the repository root during documentation hygiene passes.

The current documentation entrypoint is `docs/DOCUMENTATION_INDEX.md`.

Archived items include:

- older dated project-status snapshots (`PROJECT_STATUS_2026-05-08.md` through `PROJECT_STATUS_2026-05-21.md`),
- older Claude or Codex handoff snapshots (`CLAUDE_CODE_HANDOFF.md`, `shamsulalamx_Handoff_Context_v4.md`),
- pre-shared-ingestion architecture and pipeline summaries (`CURRENT_ARCHITECTURE.md`, `PIPELINE_ARCHITECTURE.md`),
- migration plans and operational migration prompts from earlier Electron work (`ELECTRON_MIGRATION_PLAN.md`, `ELECTRON_MIGRATION_PROMPT.md`, `ELECTRON_GEMINI.md`),
- older feature inventories, debugging notes, and source-specific references (`CURRENT_FEATURES.md`, `DEBUGGING_PITFALLS.md`, `BUGS_AND_NEXT_STEPS.md`, `NBME_JSON_IMPORT.md`, `NEXT_STEPS_OME.md`, `DIVINE_PIPELINE.md`, `RECENT_MAJOR_CHANGES.md`, `DEPLOYMENT_AND_RUNTIME_MODES.md`, `DOCUMENTATION_CLEANUP_PROMPT.md`),
- the historical runtime architecture audit `RUNTIME_ARCHITECTURE_AUDIT_2026-05-21.md` (structural ownership claims remain accurate; the git-state header is pre-Phase 10C and pre-Phase 11).

Newly archived during the 2026-05-23 hygiene pass:

- `PROJECT_STATUS_2026-05-21.md` — superseded by `PROJECT_STATUS_2026-05-23.md` in the repo root.
- `RUNTIME_ARCHITECTURE_AUDIT_2026-05-21.md` — moved from `docs/` because its git-state header (latest tag v4.15, branch `main`) is no longer current.

Also removed during the 2026-05-23 hygiene pass (not archived because the captured work was already committed):

- `PHASE_10A_UNCOMMITTED_CHECKPOINT.patch` (was a 112 KB snapshot of the v4.40 → v4.47 work in progress).
- `PHASE_10A_UNCOMMITTED_CHECKPOINT.stat.txt` (its companion stat summary).

Keep the archived files for history and rollback context. Do not treat them as current validation evidence or current workflow guidance when they conflict with the authoritative docs listed in the documentation index.
