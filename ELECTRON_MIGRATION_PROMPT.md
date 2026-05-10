# Electron Migration Prompt

Use this prompt for Electron migration planning and implementation continuity.

Do not commit, push, deploy, package, or remove Netlify/web support unless explicitly approved.

Ownership: this prompt is operational guidance for Electron work. Durable rules belong in `PROJECT_CONTEXT.md`; current status belongs in `PROJECT_STATUS_2026-05-08.md`; the staged roadmap belongs in `ELECTRON_MIGRATION_PLAN.md`.

## Current Baseline

- Current stable checkpoint: `2ba4b1d Stabilize parser/render pipeline before Electron migration`.
- Long-term target is a desktop-only Electron app.
- The current browser/Netlify app in `index.html` remains the stable transitional baseline and rollback path.
- Parser/render pipeline is stable locally.
- Electron dev scaffolding and planning have started.
- UWorld DOCX pipeline is implemented end-to-end: DOCX import → normalized blocks → concept extraction → deterministic clustering/deduplication → selected clusters → deterministic draft scaffolds → one-at-a-time Electron-local Gemini refinement → live batch queue → review controls → duplicate warnings and coverage summaries → approved draft JSON export → quiz-object preview → controlled save into real tests.
- UWorld v1 implementation complete, pending real-world validation.
- Live Gemini validation/testing is intentionally deferred to conserve API credits.
- Netlify deploy credits are limited; avoid Netlify deploys during local Electron iteration.
- The app is currently private/personal use only.

## Migration Strategy

- Wrap the current stable app first.
- Preserve browser/Netlify compatibility initially, but treat it as transitional rather than the long-term platform.
- Avoid rewrites during the first migration step.
- Keep the current web/Netlify version working.
- Preserve parser/debug tooling and local-only debug safeguards.
- Preserve current Google Drive behavior initially.
- Preserve Netlify/browser fallback behavior while using Electron main/preload for Electron-local UWorld Gemini refinement.
- Use staged migration with small verifiable steps.
- Do not remove browser mode, Netlify Functions, Drive, localStorage, IndexedDB/FigureStore, or localhost dev loading until desktop-native replacements are implemented and verified.

## Electron Architecture Direction

- Add Electron-specific scaffolding without treating that as a split of the current browser app.
- Keep renderer, main process, and preload responsibilities separated.
- Prefer a local-first app-data strategy.
- Preserve IndexedDB/FigureStore behavior initially unless a later migration explicitly replaces it.
- Do not expose API keys in renderer/frontend code.
- Continue loading from localhost during development until packaged/local app loading is explicitly designed and verified.

## Future Importer/Render Direction

- Support per-question text, image, and hybrid render modes.
- Preserve both parsed text and stem/image crops when available.
- Move toward a canonical intermediate question schema before quiz generation.
- The schema should separate OCR repair, normalization, semantic parsing, rendering, and persistence.
- Render selection should be driven by metadata, confidence, and content type, not historical question numbers.
- Render mode should be reviewable/editable by the user.

## Gemini Strategy

- Keep Netlify Functions as transitional/rollback support.
- Electron-local UWorld refinement uses the Electron main process behind narrow preload APIs.
- Main process should own API key lookup, request construction, response validation, rate/error handling, and redaction.
- `GEMINI_API_KEY` must be read from `process.env` only.
- Do not store or expose API keys in renderer/frontend code, preload globals, localStorage, Google Drive backups, debug exports, or packaged assets.
- Do not remove Netlify Functions until desktop-native Gemini, storage, backup/restore, and rollback behavior are verified.
- Keep the Gemini model string exactly `gemini-2.5-flash`.

## UWorld Notes Guidance

- Keep UWorld DOCX import, clustering, selection, draft generation, refinement, review, export, and save isolated from the NBME PDF parser/OCR/render pipeline.
- Do not remove the existing single-draft refinement path.
- Live batch refinement is implemented through the existing Electron Gemini bridge and must remain one-at-a-time.
- Batch queue safeguards include draft-hash caching, duplicate skipping, explicit queue states, pause/cancel/retry, repeated-failure stop, preflight confirmation, and no automatic approval or save.
- Duplicate refined-question warnings, review filters/sorts, and section/topic coverage summaries are implemented as display aids only.
- Do not auto-refine all selected clusters blindly outside the controlled batch queue.
- Do not save pending or rejected drafts.
- UWorld saves require approved refined drafts, valid quiz-object preview, explicit save target, nonempty inline test name, and inline review confirmation.
- Current batch queue design is selected clusters → deterministic drafts → one-at-a-time queue → cache by draft hash → pause/cancel/retry → preflight confirmation → review-gated save.
- Real-world validation remains unresolved: test a small live Gemini batch with real imported notes before large runs.
- `deno.lock` remains untracked and should not be touched unless explicitly requested.

## Storage Strategy

- Browser `localStorage` and IndexedDB/FigureStore remain active during transition.
- Long-term desktop target: move metadata, figures, source artifacts, parser runs, backups, settings, and logs into Electron app-data.
- Do not silently migrate stored quizzes or image assets. Add explicit export/import, backup, verification, and rollback first.

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
