# NBME Self-Assessment Suite Project Status

Last updated: 2026-05-07 16:01 EDT

This file captures the current working state of the project after the May 7 updates. It supersedes older status notes where they conflict, especially anything that says Supabase is still active.

## Core Rules

- `index.html` is the authoritative working app.
- Keep active app edits inside `index.html`.
- Do not split the app into external CSS or JS files.
- The old `app.js`, `db.js`, `ocr.js`, `quiz.js`, `results.js`, `style.css`, `css/`, and `js/` files still exist, but they are not the active implementation.
- Keep the Gemini model string exactly `gemini-2.5-flash`.
- Do not reintroduce Supabase unless explicitly requested.
- Keep full-quality question and figure images in IndexedDB/Google Drive. Do not put image data back into localStorage.
- Google Drive OAuth requires the app to be opened from `http://localhost:8080`, not `file://`, when connecting or syncing Drive.

## Current File State

- Active app: `index.html`
- Current size: 6888 lines, about 312 KB.
- Existing older handoff: `PROJECT_STATUS_2026-05-06.md`
- Current handoff: `PROJECT_STATUS_2026-05-07.md`
- Current git working tree:
  - Modified: `index.html`
  - Modified: `.DS_Store`
- `.DS_Store` is unrelated and should not be touched unless requested.

## Current Architecture

The app is a single-page browser app written in plain HTML, CSS, and JavaScript inside `index.html`.

Main inlined modules:

- `DB`: localStorage database for metadata, folders, tests, marks, flags, notes, history, and settings.
- `FigureStore`: IndexedDB image storage for question stems, figures, exhibits, and restored Drive images.
- `Google Drive Backup`: Drive folder, manifest, and figure-file backup/restore.
- `OCR`: PDF text extraction, OCR fallback, parsing, stem crop generation, and answer parsing.
- `Quiz`: test-taking engine, timers, answer selection, hints, stem-image rendering, highlighting, and navigation.
- `Results`: post-submit score page, review mode, analytics, and PDF report generation.
- `App`: sidebar navigation, home/search/notes/incorrect/marked/flagged/trash views, folders, modals, and test generation.

## Storage And Sync

### Local Storage

localStorage stores app metadata only:

- folders
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

Google Drive is now the durable cross-device backup path.

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

- The app must be served from `http://localhost:8080` for Google Drive OAuth because the Google Cloud OAuth origin is configured for that origin.
- Opening `index.html` directly with `file://` still works for local use, but not for Drive connection.

### Supabase

Supabase has been removed from the active app.

Removed:

- Supabase CDN script.
- Session-code UI.
- Supabase sync functions.
- Startup restore from Supabase.
- Topbar sync indicator.
- Session-code copy/resume flow.

Current status:

- `index.html` has no active Supabase references.
- Do not bring Supabase back unless specifically requested.

## AI And Cost Controls

### Gemini

Gemini is still used for:

- one hyperspecific tag per question
- one hint per question

The model string remains:

```text
gemini-2.5-flash
```

### Tagging

Current tagging behavior:

- One batched Gemini request per generated test.
- One tag per question.
- Tags should be hyperspecific, not broad categories.
- Examples of desired style:
  - `Alzheimer treatment: cholinesterase inhibitor first line`
  - `Pramipexole adverse effect: impulse control behavior`
- Output is capped.
- Thinking is disabled for cost control.

### Hints

Current hint behavior:

- One cached hint per question.
- Stored permanently on the question as `q.hint`.
- If a cached hint exists, Gemini is not called again for that question.
- Hint should be one sentence when possible, maximum two sentences.
- Hint should guide reasoning without explicitly giving away the answer.
- Every question is now treated as image-based when available, so Gemini receives a temporary downscaled JPEG copy of the stem image for hint generation.
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

This helps monitor daily Gemini API use.

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

- Question numbers are no longer visible in the stem images based on the latest user feedback.
- The app intentionally avoids aggressive right-side cropping so figures such as question 48 are not cut off.
- Image framing has been adjusted toward a white, embedded UI look.

## Question Stem Image Highlighting

Implemented:

- Stem images can be highlighted directly.
- Highlight rectangles are stored as normalized image coordinates so they resize with the image.
- Stem image highlight color matches answer explanation highlight color.
- Current brush height setting is `0.16`.
- Continuous multi-line auto-highlighting was removed because it behaved unpredictably.
- Current behavior uses a single horizontal highlight stroke for each drag.

Known limitation:

- Image highlights are visual only. They are not extracted into Notes.

## Answer Explanation Highlighting And Notes

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

Not implemented by design:

- Answer choice highlighting is not needed.
- Question stem image highlight extraction into Notes is not needed.

## Search

Implemented:

- Home screen search box placeholder is simply `Search`.
- Searches answer choices and answer explanations.
- Results show:
  - test name
  - question number
  - question tag
  - source match location
  - preview
- Clicking a result opens that exact question through `Quiz.startTestAt(testId, qIdx)`.

## Sidebar Views

Current left panel items:

- Home
- All Flagged
- Incorrect
- Marked
- Notes
- Trash
- Folders

### Incorrect Tab

Implemented:

- Lists incorrect answered questions from the latest completed attempt.
- Skipped questions are excluded.
- Grouping order:
  1. folder name
  2. hyperspecific tag
- Each row shows:
  - question number
  - test name
  - hyperspecific tag
  - your answer
  - correct answer
- Clicking a row opens the question directly.

Latest edit:

- The row text that previously showed the question stem preview now shows the hyperspecific tag.

### Marked Tab

Implemented:

- Lists marked questions grouped by folder.
- Supports removing marks.

### Notes Tab

Implemented:

- Lists extracted answer-explanation highlights as bullet points.
- Groups notes by folder.
- Supports delete.
- Supports DOCX and PDF download.

## Score Page And Results

Latest score page changes:

- Removed `Your Answer` column.
- Removed `Correct Answer` column.
- Added `Question tag` column.
- Passing threshold is now 60%.
- `Strengths` section was removed entirely.
- `Needs Review` now lists only hyperspecific tags from incorrect answered questions.
- The PDF report topic analysis was also aligned to show `Needs Review` only, without Strengths.

Current result table columns:

- question number
- result
- question tag
- time
- flag
- review button

## Fonts And Text Styling

Current direction from user:

- Answer choices use Arial.
- General exam text has been adjusted toward NBME-like readability.
- Answer explanation line spacing and paragraph spacing were tuned over multiple rounds.

Important prior preference:

- Do not make global page-level zoom changes unless asked.
- Text selection and copy/paste must remain preserved.

## OCR And Parsing Direction

The old parser/OCR problems included:

- phantom spaces inside words
- missing spaces between words
- broken acronyms
- lab-heavy stems parsed as incomplete stems
- question stems being missing or unreliable

Current product direction:

- Do not keep escalating word-patch OCR fixes unless specifically requested.
- Use cropped original stem images as the source of truth for stems.
- Keep answer choices and explanations as parsed text.
- Keep OCR Review focused on real answer/explanation content issues.

OCR Review status:

- Parser diagnostic before saving a test has been removed from the user-facing save flow.
- OCR Review no longer treats `item` in an empty/no-stem state as a meaningful stem issue.

## Known Issues And Watch Items

### Google Drive

- Google Drive connection only works from `http://localhost:8080`.
- A different computer/browser needs Google sign-in and Drive restore.
- There is no separate sync code to paste between devices.

### Local Browser Data

- LocalStorage and IndexedDB are browser/device-specific.
- A generated test exists only on the current browser unless backed up/restored through Google Drive.

### Image Highlighting

- Current image highlight brush is visual and normalized.
- It may still need visual tuning if the user wants closer highlighter behavior.

### Score Page

- Latest score-page changes are implemented and syntax-checked.
- Browser visual verification was not repeated after the final score-page edits in this handoff.

### Responsive Sidebar

- On narrow browser widths, the left sidebar is hidden by responsive CSS.
- Browser smoke testing may not show the sidebar unless the viewport is wide enough.

## Commands Used For Verification

Recent checks passed:

```bash
awk 'BEGIN{in_script=0} /<script/{if ($0 !~ /src=/) in_script=1; next} /<\/script>/{in_script=0; next} in_script{print}' index.html > /private/tmp/nbme-inline.js && node --check /private/tmp/nbme-inline.js
git diff --check -- index.html
```

Recent browser check:

- The app loaded in the in-app browser.
- The browser viewport was narrow enough that the sidebar was hidden by responsive CSS.
- Earlier sidebar click verification could not proceed because the sidebar was not visible at that viewport width.

## Recommended Next Steps

1. Open the app from `http://localhost:8080/index.html` when testing Google Drive.
2. Run a generated test through submission and visually verify the updated score page.
3. Confirm the Incorrect tab grouping and direct question navigation with a completed test that has wrong answers.
4. If storage/sync is the next focus, test Drive backup and restore on a second browser/device before relying on it.
5. If visual polish is next, tune image-stem highlighting and score-page layout only after functionality is confirmed.

