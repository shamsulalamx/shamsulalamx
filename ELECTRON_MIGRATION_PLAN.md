# Electron Migration Plan

## Purpose

This is the active Electron migration roadmap for the NBME Self-Assessment Suite.

It is different from:

- `PROJECT_CONTEXT.md`: durable architecture/context rules.
- `PROJECT_STATUS_2026-05-08.md`: current project status and handoff snapshot.

This file should track migration stages, decisions, risks, verification checkpoints, and future migration log entries.

## Current Baseline

- Stable checkpoint commit: `2ba4b1d Stabilize parser/render pipeline before Electron migration`.
- Current app is the stable browser/Netlify version.
- Electron work has not started yet.
- Browser app remains the fallback.
- Early Electron work should run locally and should not require push or Netlify deploys.

## Migration Principles

- Wrap the current app first.
- Preserve browser compatibility.
- Avoid rewrites initially.
- Avoid breaking the stable parser/render pipeline.
- Preserve parser/debug tooling.
- Preserve current Google Drive behavior initially.
- Preserve current Gemini behavior initially.
- Avoid Netlify deploys during local Electron iteration.
- Do not expose API keys client-side.
- Keep migration steps small and reversible.

## Planned Stages

### Stage 0: Confirm Stable Baseline

- Confirm working tree and checkpoint.
- Confirm browser app still runs locally.
- Confirm parser/render fixtures and debug exports still work.

### Stage 1: Add Minimal Electron Wrapper

- Add only the minimum Electron scaffolding needed for local dev mode.
- Keep existing browser app unchanged.
- Do not package yet.

### Stage 2: Load Existing `index.html` In Electron

- Load the current app as-is.
- Preserve browser/Netlify compatibility.
- Identify any assumptions that differ between browser and Electron.

### Stage 3: Add Preload/Main/Renderer Boundaries

- Define what belongs in Electron main process, preload, and renderer.
- Keep privileged APIs out of the renderer unless exposed through narrow preload bridges.

### Stage 4: Add Desktop-Mode Detection

- Add a minimal way for the app to detect Electron/desktop mode.
- Avoid changing normal browser behavior.

### Stage 5: Add Local Filesystem/Debug Helpers

- Add local-only helpers where Electron provides clear value.
- Keep parser/debug exports local and private.
- Avoid replacing existing browser debug tooling prematurely.
- Use narrow preload/main IPC only when a helper is implemented.
- Candidate future helpers: app-data path lookup, open debug folder, save debug export, and native file dialogs.
- Do not expose direct filesystem access, raw IPC wrappers, or broad Node APIs to the renderer.

### Stage 6: Preserve Netlify Gemini Initially

- Continue using current Netlify Functions path for Gemini during early Electron work.
- Keep `gemini-2.5-flash`.
- Revisit local Gemini strategy later.

### Stage 7: Preserve Or Adapt Drive Workflow

- Preserve current Google Drive backup/restore initially.
- Investigate Electron OAuth behavior before changing the flow.

### Stage 8: Add Local App-Data Structure

- Define app-data folder layout.
- Decide how local metadata, generated quizzes, parser debug artifacts, and image assets should be stored.
- Avoid destructive migration of existing browser data.
- Stage 8 is design-only until an explicit storage migration is approved.
- Proposed future layout under the Electron user data directory:
  - `quizzes/`: generated quiz metadata and question JSON.
  - `sources/`: original imported PDFs, documents, screenshots, transcripts, and other source files.
  - `ocr/raw/`: raw OCR and PDF text extraction output.
  - `ocr/normalized/`: normalized blocks before semantic parsing.
  - `parsed/questions/`: parsed question objects before quiz generation.
  - `debug/snapshots/`: focused parser/debug snapshots and export bundles.
  - `parser-runs/`: per-import run manifests, counts, warnings, and source-number audits.
  - `backups/`: local backup snapshots separate from Google Drive sync.
  - `settings/`: desktop-only settings that should not live in browser localStorage.
  - `logs/`: local application and import logs.
- Do not create these folders, move `FigureStore` images, migrate localStorage, or add filesystem IPC during Stage 8.

### Future Local Storage Migration Strategy

- Current browser storage remains authoritative until an explicit migration is approved.
- `localStorage` currently stores sanitized metadata under `nbme_app_v1`: settings, source folders, subfolders, tests, trash, flags, marks, notes, history, attempts, answers, explanations, tags, and image references.
- `FigureStore` currently stores large image data in IndexedDB database `nbme_figures_v1`, object store `figures`, keyed by figure keys referenced from question image metadata.
- Keep browser compatibility by leaving `DB.save()`, `storagePayload()`, and `FigureStore` behavior unchanged during early Electron work.
- Future Electron migration should be staged:
  - Add read-only export diagnostics from current browser storage.
  - Add explicit user-triggered export to local app-data JSON without changing the active save path.
  - Add explicit user-triggered import/restore from local app-data after validation and backup.
  - Move active Electron metadata writes to local JSON only after parity checks and rollback are available.
  - Migrate figure/image persistence separately from metadata, preserving `figureKey` references and Drive file IDs.
  - Keep Google Drive manifest compatibility so browser and Electron backups can coexist during transition.
- Do not silently mutate stored quizzes, localStorage, IndexedDB images, or Google Drive backups during any storage migration.

### Stage 9: Design Text/Image/Hybrid Render-Mode Layer

- Define per-question render mode metadata.
- Support text mode, image mode, and hybrid mode.
- Preserve both parsed text and stem/image crops when available.
- Make render mode reviewable/editable by the user.

### Stage 10: Package Later Only After Stable Dev Mode

- Package only after local Electron dev mode is stable.
- Confirm browser app remains functional before packaging.

## Architecture Decisions To Track

- Renderer/main/preload boundary.
- Local storage model.
- App-data folder structure.
- Gemini strategy.
- Google Drive strategy.
- Render-mode strategy.
- Importer/intermediate schema strategy.

## Open Decisions

- Whether Gemini stays through Netlify Functions or later moves to Electron main process with a user-provided local key or hybrid mode.
- Whether local storage remains JSON/local files or eventually uses SQLite.
- How Google Drive OAuth should work in Electron.
- How render-mode review UI should work.
- How future importers should plug into the canonical intermediate question format.

## Regression Risks

- Parser/render breakage.
- Grouped-question behavior regression.
- OCR normalization regression.
- Stale saved quizzes after parser/render changes.
- localStorage or app-data migration mistakes.
- Google Drive restore breakage.
- Gemini hints/tags breakage.
- Browser/Electron divergence.
- Messy Electron architecture from moving too much too early.

## Verification Checklist

For each stage, verify:

- Web version still works.
- Electron app opens.
- PDF upload still works.
- Parser counts match expected source count.
- Grouped questions still work.
- Debug exports still work.
- Google Drive backup/restore still works.
- Gemini hints/tags still work.
- No API keys are exposed client-side.

## Rollback Plan

- Stable checkpoint: `2ba4b1d`.
- Browser version is the fallback.
- Avoid destructive migration steps.
- Prefer branches or local checkpoints before major stages.
- If Electron changes destabilize the app, revert the Electron-specific layer first and preserve the browser app.

## Migration Log

Append future entries here.

### 2026-05-09

- Stage: 2, load existing `index.html` in Electron.
- Change: Documentation-only verification entry; no runtime or app-logic changes.
- Verification: Electron successfully loaded the existing app over `http://localhost:8888`; `file://` was not used; browser/Netlify mode still works; basic Electron interaction verification passed.
- Decision: Keep Gemini routed through Netlify Functions for now. Local Gemini verification remains intentionally skipped during early Electron migration.
- Rollback notes: No parser, render, OCR, Gemini, Drive, storage, packaging, or deployment changes were made for this verification.

### Entry Template

- Date:
- Stage:
- Change:
- Verification:
- Decision:
- Rollback notes:
