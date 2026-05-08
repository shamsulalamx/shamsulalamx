# NBME Self-Assessment Suite — Current Project Context

Last verified from `PROJECT_STATUS_2026-05-08.md`.

## Core Rules

- `index.html` is the authoritative working app.
- Keep active app edits inside `index.html`.
- Do not split the app into external CSS or JavaScript files.
- Old split files may exist, but they are not the active implementation.
- Keep the Gemini model string exactly `gemini-2.5-flash`.
- Gemini API calls must go through Netlify Functions. Do not put Gemini API keys in frontend JavaScript, localStorage, or Google Drive backups.
- Supabase is not active. Do not reintroduce Supabase unless explicitly requested.
- Keep full-quality question stems, figures, and exhibits in IndexedDB via `FigureStore` or in Google Drive. Do not store large image data in localStorage.
- Google Drive OAuth should use the deployed HTTPS Netlify origin. Local development may use `http://localhost:8888` or `http://localhost:8080` only if those origins are added in Google Cloud Console. `file://` is not supported for Drive or Gemini.

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
- PDF report generation, because jsPDF layout is sensitive to font state, page breaks, and text normalization.
- Landing/source-folder routing, because it determines which subfolders are visible and where new tests are created.

## Current Handoff

For detailed current status, use `PROJECT_STATUS_2026-05-08.md`. It supersedes older status files where they conflict.
