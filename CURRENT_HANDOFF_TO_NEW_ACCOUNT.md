Current project: shamsulalamx
Local repo path: /Users/shamsulalam/Desktop/shamsulalamx
GitHub repo: https://github.com/shamsulalamx/shamsulalamx

Current local stable baseline:
`v4.54-uworld-chunk-planning-recovery-stable` (covers commit `0c3e389` + doc commit) on branch `phase11-fastfacts-stability`.

Most recent local stable tags (newest first):
v4.54-uworld-chunk-planning-recovery-stable
v4.53-uworld-family-review-survivor-stable
v4.52-uworld-chunk-and-token-fix-stable
v4.51-stem-quality-and-ome-live-stable
v4.50-fastfacts-review-merge-stable
v4.49-lecture-chunk-recovery-stable
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

- v4.54 ported the v4.49 chunk-planning quota-aware retry stop + per-chunk shortfall recovery to the shared UWorld machinery. Closes the silent-loss class for all five UWorld-wrapping generators (Anki, OME, Mehlman, Divine, UWorld) in one source change. Single source change in `tools/uworld-notes-question-generator/generate_uworld_questions.py`. Offline-validated; recovery-path field validation deferred to organic short-return.
- v4.53 ported the v4.50 review-survivor flow to the UWorld-family wrappers (Anki, OME, Mehlman, Divine, UWorld). Questions that fail both initial validation AND repair retry are now surfaced for human review through the existing BIC review modal instead of being silently kept with `extractionWarnings`. Single source change in `tools/uworld-notes-question-generator/generate_uworld_questions.py`. Offline-validated; failure-path field validation deferred to organic occurrence.
- v4.52 enabled live Anki generation through BIC and fixed two long-standing bugs in the shared UWorld machinery (`split_into_chunks` not honoring its max_chars cap, `_raw_gemini_call` maxOutputTokens too tight). Field-validated 2026-05-23 on user's 15-card Anki .txt: 15 real questions generated cleanly. Both fixes apply automatically to OME, Mehlman, Divine, Anki, and UWorld.
- v4.51 enforced an explicit-final-question stem-quality contract across all 6 organic generators (lecture-slide + 5 UWorld-wrapping generators) and enabled OME live generation through BIC. Field-validated 2026-05-23 on user's small OME PDF: questions end with proper one-best-answer question sentences, packaged auto-import succeeded.
- v4.50 fixed two Fast Facts review-survivor bugs: reviewed-accepted questions now merge into the same auto-imported test for the BIC job (instead of creating a parallel duplicate test) and carry the canonical `explanationSections[]` shape (instead of empty placeholders that lost the wrong-answer explanations). Field-validated 2026-05-23 on a small Fast Facts PPTX: 1 validated + 2 reviewed-accepted = one 3-question test with full explanations on all three.
- v4.49 added quota-aware retry stop + targeted missing-slide recovery to the lecture-slide generator. Field-validated 2026-05-23 on Test_Emma BIC live run (18 allocated → 17 generated, recovery loop fired for 5 slides and recovered 4 of them).
- v4.48 added structured table rendering in the lecture-slide explanation panel (`renderExplanationTablesInto` in `index.html`; generator no longer emits the `"Table used for explanation only: <tableId>"` placeholder).
- Phase 10C survivability layer is intact in `electron/main.js`: single-instance lock, `process_registry.json`, filesystem-first queue/history reconciliation, completed-job protection, guarded process-group cleanup, startup cleanup for stale tracked runner PIDs, packaged app parity.
- UOGA core package under `core/uoga/` is graph-native only for `fast_facts_pptx`. Other organic sources fail fast with "not graph-native, cannot run in hybrid mode." Domain boundaries are enforced by `scripts/uoga_dependency_graph_validator.py`.

Open follow-ups (not blockers, see `NEXT_STEPS_PRIORITY.md`):

- The v4.49 chunk-planning fix lives in `generate_lecture_slide_questions.py` only. Other source-specific generators (OME, Mehlman, NBME, Divine, UWorld, Anki) have separate code paths and have NOT been audited for the same silent-loss class at the chunk boundary. The v4.51 stem-quality validator is a DIFFERENT concern (catches well-formed questions missing the final question sentence); it does not catch silent under-delivery at the chunk boundary. Worth a quick allocated-vs-generated check on first live run of each remaining source.
- OME live generation is field-validated on one small user-supplied OME PDF only. Broader OME variety, asset extraction quality, and signed/notarized distribution have not been stressed.

Working tree:

- Working tree carries untracked generated artifacts under `tools/lecture-slide-question-generator/output_assets/` and `tools/shared-ingestion/output/`. These are workflow/validation artifacts. Do not stage or delete unless explicitly requested.
- Documentation hygiene pass on 2026-05-23 removed the stale `PHASE_10A_UNCOMMITTED_CHECKPOINT.patch` / `.stat.txt` snapshots (work captured there was already committed across v4.41–v4.47), archived `PROJECT_STATUS_2026-05-21.md` and `docs/RUNTIME_ARCHITECTURE_AUDIT_2026-05-21.md` to `docs/archive/`, and brought every tracked doc's `Last updated` line to 2026-05-23.
