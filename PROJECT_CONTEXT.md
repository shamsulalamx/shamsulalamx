# NBME Self-Assessment Suite — Current Project Context

Last verified from `PROJECT_STATUS_2026-05-08.md`.

## Core Rules

- `index.html` is the authoritative working app.
- Keep active app edits inside `index.html`.
- Do not split the current browser app into external CSS or JavaScript files.
- The Electron migration may add Electron-specific scaffolding such as `package.json`, `electron/main.js`, and `electron/preload.js`. That does not change `index.html` being the current authoritative browser app.
- Old split files may exist, but they are not the active implementation.
- Keep the Gemini model string exactly `gemini-2.5-flash`.
- Current implementation: Gemini API calls go through Netlify Functions. Do not put Gemini API keys in frontend JavaScript, localStorage, or Google Drive backups.
- Supabase is not active. Do not reintroduce Supabase unless explicitly requested.
- Keep full-quality question stems, figures, and exhibits in IndexedDB via `FigureStore` or in Google Drive. Do not store large image data in localStorage.
- Google Drive OAuth should use the deployed HTTPS Netlify origin. Local development may use `http://localhost:8888` or `http://localhost:8080` only if those origins are added in Google Cloud Console. `file://` is not supported for Drive or Gemini.
- The app is currently private/personal use only. Electron security decisions, including local user-provided API keys or OAuth token storage, should be evaluated in that context and revisited if public distribution is ever planned.

## Active App

The project is a single-page browser app written in plain HTML, CSS, and JavaScript inside `index.html`.

Main inline modules:

- `DB`: localStorage metadata, source folders, subfolders, tests, marks, flags, notes, history, and settings.
- `FigureStore`: IndexedDB image storage for question stems, figures, exhibits, and restored Drive images.
- Google Drive backup: Drive folder, manifest, image upload, and restore.
- Netlify Functions: secure Gemini tagging, hint, and analysis requests.
- `OCR`: PDF extraction, OCR fallback, parsing, stem crop generation, and answer parsing.
- `Quiz`: test-taking engine, timers, answer selection, hints, stem-image rendering, highlighting, and navigation.
- `Results`: score report, review mode, analytics, and PDF report generation.
- `App`: study library landing page, source-folder routing, sidebar navigation, modals, search, notes, incorrect, marked, flagged, trash, and test generation.

## Current Stable Parser And Rendering State

The local grouped-question pipeline is stable and verified locally. The current confirmed behavior is:

- OCR, normalization, parsing, answer merge, final quiz construction, and rendering preserve the expected source question count.
- Source-number recovery is functioning, including fallback recovery when OCR page headers miss an item number but the item number appears in the normalized paragraph text.
- Source-number audits, final-count integrity checks, focused parser exports, grouped range audits, and `parseSkippedItems` diagnostics are available through local-only parser debug tooling.
- Local-only debug tooling should stay hidden or disabled in production unless intentionally exposed.
- Parser debug artifacts may contain copyrighted or private exam content and should remain local/private.
- Quoted answer-choice parsing is functioning.
- Grouped item carry-forward is functioning for shared instructions, shared stems, and shared answer banks.
- Grouped shared instructions and shared stems render correctly.
- Grouped answer banks render once, use `sharedGroup.sharedChoices` as the authoritative choice source, and remain independently selectable and independently scored for each linked question.
- Grouped rendering prioritizes structured parsed text over cropped stem-image layout when the crop would duplicate or misorder grouped content.
- Duplicate lab/table fragments that are already present in the parsed stem are suppressed in grouped rendering.
- OCR normalization fixes for damaged screenshot-based text are active and should remain conservative.
- Temporary question-specific debugging instrumentation has been removed.
- Saved/generated quizzes created before parser or render fixes may be stale. Do not silently mutate existing saved quizzes; regenerate or explicitly reparse them.

## Future Importer And Render Direction

The next planned phase is Electron migration. The first Electron step should wrap the current stable app without changing app behavior. Avoid rewrites during the initial migration.

Future importer and render work should preserve the current stable browser behavior while moving toward a clearer architecture:

- All source types should normalize into a common intermediate format before quiz generation.
- The intermediate format should preserve both parsed text and available stem/image crops.
- Do not overfit importers to NBME. Use adapters for multiple modalities, including PDFs, DOCX, pasted text, Anki, audio/podcast transcripts, video transcripts, and lecture notes.
- Rendering should support per-question text, image, and hybrid render modes.
- Render mode should be reviewable and editable by the user before final quiz save when confidence is low.
- Render behavior should be driven by metadata, confidence, and content type, not by historical question numbers.
- Future architecture is moving toward a canonical intermediate question schema that separates OCR repair, normalization, semantic parsing, rendering, and persistence.
- Future architecture may further separate OCR cleanup, semantic parsing, and render adaptation to reduce coupling and regression risk.
- Render-mode policy:
  - Text mode for clean structured stems and grouped questions.
  - Image mode for figure-heavy, layout-sensitive, or OCR-corrupted stems.
  - Hybrid mode for usable text plus figures, tables, or images.
  - User override per question.
- Gemini should continue through Netlify Functions initially. Later Electron work may consider Electron main-process Gemini calls with a user-provided local key or a hybrid mode, but that decision should not be made prematurely.

## Historical Debugging Notes

The following are historical implementation/debugging findings only. They should not be treated as permanent architecture assumptions or active question-number-specific logic:

- Grouped-question rendering previously duplicated shared answer banks when stem crops preserved the original source layout and selectable choices rendered again below.
- Shared answer-bank ordering issues were traced to downstream render/layout selection after parser grouping was already correct.
- Grouped carry-forward debugging showed that a shared group must remain active for the expected item count even if later items repeat only the shared stem or answer bank.
- Dropped-question recovery debugging showed that missing OCR header item numbers should not cause item loss when paragraph-level item numbers are available.
- OCR damage recovery examples included damaged age text, quoted answer choices, and duplicate lab/table fragments extracted from text already present in the patient stem.

## Current Project Direction

The app now has a top-level study library layer above the old subfolder system.

Default library folders:

- NBME
- UWorld
- Anki
- OME
- Divine Podcasts
- Mehlman
- Images and Tables
- Amboss

Existing old folders are migrated under NBME by default. Subfolders should appear only after entering a top-level library folder.

## High-Risk Areas

Use extra caution around:

- `DB.save()` and `storagePayload()`, because they protect localStorage from large image payloads.
- `FigureStore`, because it owns large local images.
- Google Drive backup and restore, because it is the durable cross-device image path.
- OCR parsing and stem crop logic, because previous broad spacing fixes became unstable.
- Avoid broad OCR normalization rules. OCR fixes should be conservative, traceable, and covered by fixtures because broad spacing/token cleanup previously caused instability.
- PDF report generation, because jsPDF layout is sensitive to font state, page breaks, and text normalization.
- Landing/source-folder routing, because it determines which subfolders are visible and where new tests are created.

## Current Handoff

For detailed current status, use `PROJECT_STATUS_2026-05-08.md`. It supersedes older status files where they conflict.
