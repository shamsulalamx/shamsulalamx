# Electron Migration Prompt

Use this prompt for Electron migration planning and implementation continuity.

Do not commit, push, deploy, package, or remove Netlify/web support unless explicitly approved.

Ownership: this prompt is operational guidance for Electron work. Durable rules belong in `PROJECT_CONTEXT.md`; current status belongs in `PROJECT_STATUS_2026-05-08.md`; the staged roadmap belongs in `ELECTRON_MIGRATION_PLAN.md`.

## Current Baseline

- Current stable checkpoint: `2ba4b1d Stabilize parser/render pipeline before Electron migration`.
- The browser app in `index.html` remains the stable baseline and fallback.
- Parser/render pipeline is stable locally.
- Electron dev scaffolding and planning have started.
- Netlify deploy credits are limited; avoid Netlify deploys during local Electron iteration.
- The app is currently private/personal use only.

## Migration Strategy

- Wrap the current stable app first.
- Preserve browser compatibility initially.
- Avoid rewrites during the first migration step.
- Keep the current web/Netlify version working.
- Preserve parser/debug tooling and local-only debug safeguards.
- Preserve current Google Drive behavior initially.
- Preserve current Gemini behavior initially.
- Use staged migration with small verifiable steps.

## Electron Architecture Direction

- Add Electron-specific scaffolding without treating that as a split of the current browser app.
- Keep renderer, main process, and preload responsibilities separated.
- Prefer a local-first app-data strategy.
- Preserve IndexedDB/FigureStore behavior initially unless a later migration explicitly replaces it.
- Do not expose API keys in renderer/frontend code.

## Future Importer/Render Direction

- Support per-question text, image, and hybrid render modes.
- Preserve both parsed text and stem/image crops when available.
- Move toward a canonical intermediate question schema before quiz generation.
- The schema should separate OCR repair, normalization, semantic parsing, rendering, and persistence.
- Render selection should be driven by metadata, confidence, and content type, not historical question numbers.
- Render mode should be reviewable/editable by the user.

## Gemini Strategy

- Keep Netlify Functions initially.
- Later consider Electron main-process Gemini calls with a user-provided local key, or a hybrid mode.
- Do not decide this prematurely.
- Keep the Gemini model string exactly `gemini-2.5-flash`.

## Requested Output

Before implementation, produce:

- staged migration plan
- exact files to add/modify
- renderer/main/preload responsibility split
- storage strategy
- Gemini strategy
- Google Drive strategy
- render-mode strategy
- verification checklist
- regression-risk analysis
