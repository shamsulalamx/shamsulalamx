# NBME Self-Assessment Suite Project Status

Last updated: 2026-05-08 00:45 EDT

This file captures the current working state after the landing-page library rehaul and PDF report naming update. It supersedes older status files where they conflict.

## Core Rules

- `index.html` is the authoritative working app.
- Keep active app edits inside `index.html`.
- Do not split the app into external CSS or JS files.
- The old split files still exist, but they are not the active implementation:
  - `app.js`
  - `db.js`
  - `ocr.js`
  - `quiz.js`
  - `results.js`
  - `style.css`
  - `css/`
  - `js/`
- Keep the Gemini model string exactly `gemini-2.5-flash`.
- Do not reintroduce Supabase unless explicitly requested.
- Keep full-quality question and figure images in IndexedDB or Google Drive. Do not put image data back into localStorage.
- Google Drive OAuth requires opening the app from `http://localhost:8080`, not `file://`, when connecting or syncing Drive.

## Current File State

- Active app: `index.html`
- Current size: 7359 lines, about 330 KB.
- Previous handoffs:
  - `PROJECT_STATUS_2026-05-06.md`
  - `PROJECT_STATUS_2026-05-07.md`
- Current handoff: `PROJECT_STATUS_2026-05-08.md`
- Latest visible git commit: `8bbc663 Complete landing page rehaul`
- Current uncommitted working tree at time of this file:
  - Modified: `.DS_Store`
- `.DS_Store` is unrelated and should not be touched unless explicitly requested.

## Current Architecture

The app is a single-page browser app written in plain HTML, CSS, and JavaScript inside `index.html`.

Main inlined modules:

- `DB`: localStorage database for metadata, source folders, subfolders, tests, marks, flags, notes, history, and settings.
- `FigureStore`: IndexedDB image storage for question stems, figures, exhibits, and restored Drive images.
- `Google Drive Backup`: Drive folder, manifest, and figure-file backup/restore.
- `OCR`: PDF text extraction, OCR fallback, parsing, stem crop generation, and answer parsing.
- `Quiz`: test-taking engine, timers, answer selection, hints, stem-image rendering, highlighting, and navigation.
- `Results`: post-submit score page, review mode, analytics, and PDF report generation.
- `App`: landing page, source-folder routing, sidebar navigation, home/search/notes/incorrect/marked/flagged/trash views, subfolders, modals, and test generation.

## Landing Page And Folder System

The app now has a top-level study library layer above the old folder system.

Default top-level library cards:

- NBME
- UWorld
- Anki
- OME
- Divine Podcasts
- Mehlman
- Images and Tables
- Amboss

Current behavior:

- The Home page shows large folder-style library cards.
- Each library card routes to its own library page.
- A `+ Add Folder` card creates new top-level library cards for future use.
- Top-level library cards are renamable.
- Existing old folders are migrated under NBME by default.
- Subfolders only appear after entering a top-level library folder.
- Example: a Psychiatry subfolder appears inside NBME, not on the global landing page.
- The left sidebar now scopes its folder list to the currently selected top-level library.
- The left sidebar hides the old folder list on the top-level landing page and prompts the user to open a library folder first.
- Creating a new subfolder requires being inside a top-level library folder.
- Generating a test from inside a library only shows subfolders from that selected library.

Important implementation details:

- `DB.defaultDB()` now includes `sourceFolders`.
- Existing folders are assigned `sourceId: 'src-nbme'` during the source-folder migration.
- `DB.getFolders(sourceId)` returns filtered subfolders when `sourceId` is provided and all subfolders when it is omitted.
- `DB.createFolder(name, sourceId)` creates a subfolder under the selected top-level library.
- `App.showHome()` with no folder returns to the top-level study library landing page.
- `App.showSourceHome(sourceId)` enters a top-level library page.
- `App.showFolderHome(folderId)` enters a specific subfolder and restores the correct top-level source from that subfolder.
- `App.closeReviewTest()` returns to the current subfolder or current source when possible, instead of always dropping back to the global landing page.

## PDF Report Status

Current PDF report behavior:

- The first page contains the summary report.
- The first-page title/header uses:

```text
StudyLibraryFolderName SubfolderName QuizName
```

- The downloaded file name also uses:

```text
StudyLibraryFolderName SubfolderName QuizName.pdf
```

- Example:

```text
NBME Psych Block 1.pdf
```

- If a subfolder or source folder cannot be found, the PDF falls back to:
  - top-level library: `Study Library`
  - subfolder: `Unfiled`

Current PDF layout behavior:

- Page 1 includes the score summary, attempt metadata, duration, and test analysis.
- Test analysis lists hyperspecific tags answered correctly and hyperspecific tags needing review.
- Page 2 onward renders the review content in the app’s review-test style.
- Each question starts on its own page.
- If a question or answer explanation exceeds one page, continuation text continues on a follow-up page for the same question.
- Continuation pages preserve normal font weight and color.
- The prior weird PDF spacing/font issue was addressed through text normalization before writing to jsPDF.

## Results And Review Flow

Current behavior:

- Completed test cards show a direct `Score Report` button.
- The older test-history button was replaced for completed tests.
- The score/results table now displays row data under the headers.
- The score report can open review mode.
- The separate all-question review surface remains available through `App.reviewTest(testId)`.
- Closing the review surface returns to the current subfolder or library context when possible.

## Storage And Sync

### localStorage

localStorage stores app metadata only:

- top-level source folders
- subfolders
- tests and parsed question metadata
- answer choices
- explanations
- tags
- history
- flags
- marks
- notes
- settings

Large image data is stripped before localStorage writes.

### IndexedDB

`FigureStore` stores large image data locally:

- cropped question stem images
- figures and exhibits
- restored Google Drive image files

### Google Drive

Google Drive remains the durable cross-device backup path.

Implemented behavior:

- Uses Google Identity Services.
- OAuth client ID is configured in `index.html`.
- Scope is Drive file access.
- Creates or uses an app folder named `NBME Self-Assessment Suite`.
- Stores a manifest named `nbme_manifest.json`.
- Uploads original image files from `FigureStore`.
- Saves Google Drive file IDs into `q.images`.
- Restores tests, notes, metadata, and images from Drive back into the local app.
- `DB.save()` schedules Google Drive backup when Drive is connected.
- If a local image is missing, rendering can fall back to loading it from Google Drive when connected.

Important operational note:

- For Netlify deployment, Google Drive OAuth should use the deployed HTTPS origin, for example `https://MY-NETLIFY-SITE.netlify.app`.
- Local development may use `http://localhost:8888` or `http://localhost:8080` only if those origins are added in Google Cloud Console.
- Opening `index.html` directly with `file://` is not supported for Drive or Gemini.

### Supabase

Supabase is not active in the app.

Removed from active implementation:

- Supabase CDN script.
- Session-code UI.
- Supabase sync functions.
- Startup restore from Supabase.
- Topbar sync indicator.
- Session-code copy/resume flow.

Do not bring Supabase back unless specifically requested.

## AI And Cost Controls

### Gemini

Gemini is still used for:

- one hyperspecific tag per question
- one hint per question

Gemini calls now run through Netlify Functions. The API key belongs only in the Netlify `GEMINI_API_KEY` environment variable and must not be stored in frontend JavaScript, localStorage, or Google Drive backups.

The model string must remain:

```text
gemini-2.5-flash
```

### Tagging

Current tagging behavior:

- One batched Gemini request per generated test.
- One tag per question.
- Tags should be hyperspecific, not broad categories.
- Output is capped.
- Thinking is disabled for cost control.

Desired tag style:

- `Alzheimer treatment: cholinesterase inhibitor first line`
- `Pramipexole adverse effect: impulse control behavior`

### Hints

Current hint behavior:

- One cached hint per question.
- Stored permanently on the question as `q.hint`.
- If a cached hint exists, Gemini is not called again for that question.
- Hint should be one sentence when possible, maximum two sentences.
- Hint should guide reasoning without explicitly giving away the answer.
- When a stem image is available, Gemini receives a temporary downscaled JPEG copy of the stem image for hint generation.
- Original question stem images are not compressed for storage or display.

### Hint Usage Counter

The quiz topbar shows:

```text
Gemini hints today: N
```

The counter is stored in localStorage under:

```text
gemini_hint_usage_v1
```

## Question Stem Images

The current app direction is image-first for question stems.

Implemented:

- Cropped PDF stem images are generated from the original PDF page.
- The crop removes the NBME item number area on the left.
- Parsed text stems are hidden when a stem image exists.
- Stem images are rendered as the main question stem.
- Figures and exhibits remain attached through `q.images`.
- Images use IndexedDB through `FigureStore`.
- Google Drive backup preserves question images for use across devices.

Current crop status:

- Question numbers are no longer visible in the stem images based on prior feedback.
- The app avoids aggressive right-side cropping so figures are not cut off.
- Image framing is tuned toward a white embedded UI look.

## Highlighting And Notes

### Question Stem Image Highlighting

Implemented:

- Stem images can be highlighted directly.
- Highlight rectangles are stored as normalized image coordinates so they resize with the image.
- Stem image highlight color matches answer explanation highlight color.
- Current brush height setting is `0.16`.
- Current behavior uses a single horizontal highlight stroke for each drag.

Known limitation:

- Image highlights are visual only. They are not extracted into Notes.

### Answer Explanation Highlighting And Notes

Implemented:

- Answer explanations are selectable and copyable.
- Highlighting answer explanation text adds the selection visually.
- A small `Add to Notes` toolbar appears after selection.
- Notes are grouped by folder.
- Each note is stored as a bullet point.
- Notes can be downloaded as:
  - `.docx`
  - `.pdf`

Important implementation detail:

- Explanation highlighting uses the CSS Highlight API rather than DOM mutation, which avoids random line breaks caused by wrapping selected text in inline elements.

## Current Verification

Recent verification after the latest PDF naming update:

- Inline JavaScript syntax check passed with `node --check`.
- `git diff --check` passed.

For deployment and sync testing, use the deployed HTTPS Netlify URL or Netlify local dev. Do not test Drive or Gemini from a `file://` URL.

## High-Risk Areas

Use extra caution around:

- `DB.save()` and `storagePayload()`, because they protect localStorage from large image payloads.
- `FigureStore`, because it owns large local images.
- Google Drive backup/restore, because it is the durable cross-device image path.
- OCR parsing and stem crop logic, because previous spacing fixes became unstable when handled with broad token surgery.
- PDF report generation, because jsPDF layout is sensitive to font state, page breaks, and text normalization.
- Landing/source-folder routing, because it now determines which subfolders are visible and where new tests are created.

## Recommended Next Steps

- Browser-check the landing page after refresh:
  - Home shows 8 top-level folder cards plus the add card.
  - Existing folders appear inside NBME.
  - The left sidebar shows subfolders only after entering a top-level library.
  - New subfolders are created inside the selected top-level library.
  - The Generate Test modal only lists subfolders from the selected top-level library.
- Generate or open a completed test and download the PDF:
  - Confirm filename format is `StudyLibraryFolderName SubfolderName QuizName.pdf`.
  - Confirm PDF header matches the same text.
  - Confirm page 2 onward still preserves the expected review-test layout.
- Do not edit `.DS_Store` unless specifically requested.
