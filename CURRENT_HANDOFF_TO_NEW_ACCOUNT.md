Current project: shamsulalamx
Local repo path: /Users/shamsulalam/Desktop/shamsulalamx
GitHub repo: https://github.com/shamsulalamx/shamsulalamx

Current local stable baseline:
`v4.48-lecture-explanation-tables-stable` at commit `f3b2bc9` on branch `phase11-fastfacts-stability`.

Most recent local stable tags (newest first):
v4.48-lecture-explanation-tables-stable
v4.47-emma-pdf-batch-import-stable
v4.46-fastfacts-reviewed-import-after-auto-import-stable
v4.45-fastfacts-review-only-completion-stable
v4.44-fastfacts-generation-completion-stable
v4.44-phase11-observability-stable
v4.43-fastfacts-limit-removal-stable
v4.42-fastfacts-packaged-path-hotfix-stable
v4.42-source-type-switching
v4.41-phase11-generation-correctness-stable
v4.41-per-question-review-draft-stable
v4.40-phase10c-survivability-stable

Reading order on first start:

1. `PROJECT_CONTEXT.md`
2. `PROJECT_STATUS_2026-05-23.md`
3. `ARCHITECTURE.md`
4. `BATCH_IMPORT_ARCHITECTURE.md`
5. `KNOWN_LIMITATIONS.md`
6. `NEXT_STEPS_PRIORITY.md`
7. `MIGRATION_HANDOFF.md`
8. `docs/DOCUMENTATION_INDEX.md`

Critical current state:

- v4.48 added structured table rendering in the lecture-slide explanation panel (`renderExplanationTablesInto` in `index.html`; generator no longer emits the `"Table used for explanation only: <tableId>"` placeholder).
- Phase 10C survivability layer is intact in `electron/main.js`: single-instance lock, `process_registry.json`, filesystem-first queue/history reconciliation, completed-job protection, guarded process-group cleanup, startup cleanup for stale tracked runner PIDs, packaged app parity.
- UOGA core package under `core/uoga/` is graph-native only for `fast_facts_pptx`. Other organic sources fail fast with "not graph-native, cannot run in hybrid mode." Domain boundaries are enforced by `scripts/uoga_dependency_graph_validator.py`.

Open issue (new in v4.48 diagnosis):

- Lecture-slide chunk-planning silently drops Gemini short returns. Same input produced 16 questions and then 7 on consecutive BIC runs. A naive strict-count fix triggered budget runaway through recursive sub-chunking and ended with 0 questions when Gemini quota depleted. Reverted in HEAD. See `NEXT_STEPS_PRIORITY.md` item 0 for the quota-aware design options.

Working tree:

- Working tree carries untracked generated artifacts under `tools/lecture-slide-question-generator/output_assets/` and `tools/shared-ingestion/output/`. These are workflow/validation artifacts. Do not stage or delete unless explicitly requested.
- Documentation hygiene pass on 2026-05-23 removed the stale `PHASE_10A_UNCOMMITTED_CHECKPOINT.patch` / `.stat.txt` snapshots (work captured there was already committed across v4.41–v4.47), archived `PROJECT_STATUS_2026-05-21.md` and `docs/RUNTIME_ARCHITECTURE_AUDIT_2026-05-21.md` to `docs/archive/`, and brought every tracked doc's `Last updated` line to 2026-05-23.
