# Migration Handoff

Last updated: 2026-05-23

Current stable tag: `v4.52-uworld-chunk-and-token-fix-stable`.
Current branch: `phase11-fastfacts-stability`.

This handoff was originally written when the project migrated to a new ChatGPT + Codex account on 2026-05-22. It is now valid for any subsequent account or agent continuing the project, including the current Claude (Anthropic) agent that took over on 2026-05-23 and produced the v4.48 milestone.

## How To Continue Safely

Start every session by confirming:

```bash
pwd
git status --short
git tag --list 'v4.*' --sort=version:refname
```

Read in this order:

1. `PROJECT_CONTEXT.md`
2. `PROJECT_STATUS_2026-05-21.md`
3. `ARCHITECTURE.md`
4. `VALIDATED_PIPELINES.md`
5. `KNOWN_LIMITATIONS.md`
6. The exact source files relevant to the task

Do not infer current behavior from old docs if current source or tags contradict them.

Current preferred user workflows:

1. Use `Batch Import` for registered ingestion and generation workflows.
2. Use `Import JSON` for manual app-ready JSON import.
3. Use `Utilities` for secondary NBME JSON Import and NBME Figure Review work.

## What Not To Destabilize

Do not casually change:

- `index.html` import behavior.
- `FigureStore` persistence.
- `DB.save()` and localStorage stripping behavior.
- BIC job manifest shape.
- BIC output discovery.
- Phase 10C queue survivability and `process_registry.json` cleanup.
- Existing source-specific generators.
- Fast Facts semantic generation quality.
- Gemini semantic validators.
- Electron preload security boundaries.

Do not convert this app to React, Next.js, or a different desktop architecture. The validated direction is a thin Electron wrapper around the existing HTTP-served app.

## Commit And Tag Discipline

Tags are used as recovery checkpoints after validated milestones. A tag name should mean a real validation bar was met, not merely that code was written.

Do not create a new stable tag until:

- source-level checks pass,
- JSON validation passes,
- BIC path passes if BIC is involved,
- auto-import works if import is claimed,
- packaged `.app` passes if runtime/packaging behavior is claimed,
- reload persistence is verified when storage is involved.

Use precise commit messages. Avoid broad commits that mix generated artifacts, runtime logic, docs, and unrelated local settings.

## Fragile Areas

Fast Facts remains a stabilization area. Current Fast Facts validation has diagnostic reporting, no-cache stabilization behavior, a 3-attempt cap, and one validated Turner screening ontology fix. It is not broad semantic stability.

Other fragile areas:

- semantic validator strictness,
- OCR quality and image classification,
- FigureStore/import preservation,
- packaged app resource paths,
- stale packaged bundles that do not match source,
- BIC output discovery across workspace vs packaged resources,
- large input folder scaling,
- variable-choice assumptions outside AMBOSS.
- limited Divine transcript/audio live semantic evidence outside transcript dry-run proof.

## Validated Architectural Claims

Validated:

- BIC can launch Python jobs and discover app-ready outputs.
- BIC can auto-import valid app-ready JSON.
- Existing-output validation mode can prove import wiring without rerunning live generation.
- Shared normalized chunks can feed Emma downstream.
- Mehlman can run through shared ingestion.
- Images & Tables can run as image/table shared profile and import attachment-first cards.
- `q.images[]` plus `FigureStore` is the stable image persistence/rendering route.
- Packaged app validation is necessary for image and BIC claims.
- Shared generation/import status UI exists for relevant BIC and JSON import surfaces.
- v4.23 keeps the normal import UI focused on Batch Import and Import JSON.
- v4.40 keeps the Batch Import queue system survivable through single-instance locking, filesystem-first reconciliation, queue corruption preservation, tracked process cleanup, and packaged app parity with source.

Not yet validated:

- True shared downstream generator for all profiles.
- Advanced semantic visual question generation.
- Deep table parsing.
- Large multimodal folder runs.
- Full shared downstream generation convergence for Anki, OME, Divine, and UWorld.
- Broad semantic validation for sources that currently have mostly dry-run or orchestration/import evidence.

## How To Validate Future Sources

Use a small sample first. Prefer 2-5 items unless the user requests scale testing.

Minimum validation:

1. Emit normalized chunks.
2. Validate `shared-normalized-chunk-bundle-v1`.
3. Produce app-ready JSON.
4. Run `python3 -m json.tool` on outputs.
5. Validate app-ready schema through the existing importer/generator validator.
6. Run BIC dry-run when registered.
7. Run BIC generate.
8. Run BIC generate + auto-import.
9. Confirm question count and destination folder.
10. Score a test.
11. Reload and confirm persistence.
12. Use packaged `.app` for final runtime proof when UI, persistence, Electron, assets, or BIC are involved.
13. For BIC queue survivability claims, confirm the rebuilt packaged app includes `requestSingleInstanceLock`, `process_registry.json`, and `reconcileQueueAndHistoryOnStartup`.

## Expected Workflow Discipline

When the user says documentation only, do documentation only. When the user says do not rerun live generation, do not rerun it. When a validation failure isolates generation quality from BIC wiring, validate the wiring separately using existing valid outputs.

Do not explain away failures. Capture the exact blocker, preserve the valid parts, and propose the next narrow diagnostic.

## Current Rollback And Dirty-Tree Notes

Current local rollback milestones (newest first):

- `v4.52-uworld-chunk-and-token-fix-stable` — current head tag
- `v4.51-stem-quality-and-ome-live-stable`
- `v4.50-fastfacts-review-merge-stable`
- `v4.49-lecture-chunk-recovery-stable`
- `v4.48-lecture-explanation-tables-stable`
- `v4.47-emma-pdf-batch-import-stable`
- `v4.46-fastfacts-reviewed-import-after-auto-import-stable`
- `v4.45-fastfacts-review-only-completion-stable`
- `v4.44-fastfacts-generation-completion-stable`
- `v4.44-phase11-observability-stable`
- `v4.43-fastfacts-limit-removal-stable`
- `v4.42-fastfacts-packaged-path-hotfix-stable`
- `v4.42-source-type-switching`
- `v4.41-phase11-generation-correctness-stable`
- `v4.41-per-question-review-draft-stable`
- `v4.40-phase10c-survivability-stable` — last "phase boundary" rollback point before Phase 11 work
- Older Phase 7–10 tags (`v4.19` through `v4.37`) remain in the tag list as historical rollback points; see `GIT_TAG_HISTORY.md` for the full record.

Do not assume the remote has every local tag or commit without checking before a push or migration claim.

The current worktree carries untracked generated artifacts under `tools/lecture-slide-question-generator/output_assets/` and `tools/shared-ingestion/output/`. These are workflow/validation artifacts, not source-controlled docs. Keep generated outputs and unrelated dirty runtime work excluded from narrow commits unless the user explicitly requests them.

## Open Follow-Ups Going Into The Next Session

The lecture-slide chunk-planning silent-loss issue diagnosed and partially attempted on 2026-05-23 morning was fully resolved that same day and tagged `v4.49-lecture-chunk-recovery-stable`. Field-validated on Test_Emma BIC live run: 18 allocated → 17 generated, recovery loop fired for 5 short-returning slides and recovered 4 of them.

Follow-ups (not blockers):

- The chunk-planning fix lives only in `generate_lecture_slide_questions.py`. OME, Mehlman, NBME, and Divine generators have separate code paths and may share the same silent-loss class. See `NEXT_STEPS_PRIORITY.md` item 0b.
- The OME live-generation registry/runner change made by the cowork agent is in the working tree as uncommitted dirty work (`tools/shared-ingestion/ome_profile_runner.py`, `tools/batch-import-center/pipeline_registry.json`). Validation pending — see the OME audit item in priorities. Also: that change flips `requiresGemini: false → true` for OME and crosses a previously documented "dry-run only" validation boundary, so several docs (`VALIDATED_PIPELINES.md`, `KNOWN_LIMITATIONS.md`, `BATCH_IMPORT_ARCHITECTURE.md`) will need updates after live OME validation.
