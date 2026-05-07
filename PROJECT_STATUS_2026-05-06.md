# NBME Self-Assessment Suite Project Status

Last updated: 2026-05-06 19:53 EDT

## Project Rules

- `index.html` is the authoritative working app.
- All active app edits must stay inside `index.html`.
- Do not split code into separate CSS or JS files.
- Do not use the existing `css/` or `js/` folders for active work.
- Gemini model string must remain exactly `gemini-2.5-flash`.
- Supabase sync is working and should not be changed unless specifically requested.
- Figure/exhibit images must stay in IndexedDB through `FigureStore`; do not move image data into localStorage.
- `joinItems()` should continue to always insert spaces.
- For phantom-space OCR issues, be careful not to rewrite token logic casually. Earlier guidance favored extending `_REAL_WORDS` inside `fixLigatureSpaces()`, but the current direction is to rely more on PDF stem image crops rather than endless word-level OCR repairs.

## Current Architecture

The app is a single-file browser app in `index.html`.

Major pieces inside `index.html`:

- Local database/session logic and Supabase sync.
- `FigureStore`, an IndexedDB store for question images/figures/exhibits.
- OCR/PDF extraction engine under `const OCR = (() => { ... })`.
- Quiz renderer under `const Quiz = (() => { ... })`.
- Results/review rendering.
- Generate Test modal, OCR review modal, and Parse Audit modal.

The old files `app.js`, `ocr.js`, `quiz.js`, `results.js`, and `style.css` exist in the folder, but the user has specified that the working app is `index.html` only.

## Current Git State

At the time this file was created:

- Modified: `.DS_Store`
- Modified: `index.html`
- No commit was made by Codex after the latest changes.

`.DS_Store` is unrelated and should not be touched unless the user asks.

## Main Problem History

The original problem was persistent OCR spacing corruption:

- “No spacing” examples: `Generalizedanxietydisorder`
- “Phantom spacing” examples: `fat ig ue`, `A l zheimer`, `w ife`, `in it i at i on`
- Broken explanations: paragraphs split inside words/acronyms.
- Parser failures: some items showed only lab values or partial stems.

Several rounds of dictionary-based repair improved some text, but did not reliably solve all cases. The current design direction is to stop depending on perfect OCR/parsing for question stems and instead preserve the original PDF stem visually.

## Current Direction

The best current strategy is:

1. Use cropped PDF images as the source of truth for question stems.
2. Keep parsed answer choices as text.
3. Keep parsed explanations as text, with cleanup/review.
4. Continue using `FigureStore`/IndexedDB for all images.
5. Later add image-based highlight rectangles so the user can highlight stem image crops.

This should largely bypass stem phantom-spacing issues and prevent missing stem text from breaking the quiz experience.

## Implemented Recently

### OCR Review

An OCR review modal exists before saving generated tests.

It detects curated spacing problems and learned corrections. It includes:

- Previous
- Undo
- Skip
- Apply All Same
- Apply Fix
- Manual edit
- Save Anyway

Manual fixes are learned in localStorage under `nbme_ocr_corrections_v1`.

### Parse Audit

A Parse Audit modal exists before saving generated tests.

It checks parsed questions for structural risk:

- Very short stems.
- Lab-heavy stems without clinical setup.
- Raw grouped text much longer than parsed stem.
- Low raw-vs-parsed keyword preservation.
- Missing question prompts.
- Broken explanation paragraph fragments.
- Too few answer choices.

It shows:

- Display item number.
- Source item number.
- Parsed stem length vs raw grouped question length.
- Parsed stem.
- Parsed options.
- Raw grouped question text.
- Raw answer text.
- Explanation preview.

This is diagnostic only. It does not fix parser failures automatically.

### Exhibit/Stem Crop Layer

Phase 1 of the image-stem direction has been implemented.

For vector/text-layer question PDFs:

- The app renders the original PDF page.
- It crops a stem image from below the NBME header to just above the first detected `A)` answer-choice row.
- It crops out part of the left margin to remove the PDF’s item-number area.
- It stores the crop as a `stem` exhibit in `q.images`.
- It saves the crop into IndexedDB through `FigureStore` when the test is saved.
- It displays stem crops after the stem location and before answer choices.
- If a stem crop exists, the parsed text stem is hidden in the quiz view.
- If a stem crop exists, duplicate full-page/lab/figure exhibit crops are filtered out from display.

The current crop is intentionally not perfect yet, but it is much better than relying on parsed/OCR text.

### Rendering Changes

When an image stem is present:

- The parsed text stem is hidden in the quiz view.
- The question image is displayed as the main stem.
- The quiz content area widens from `1000px` to `1280px` and side padding is reduced.
- Images are set to fill the available width.

Review mode also hides parsed text when a stem crop exists.

The all-question review page has not yet been fully adapted for image stems.

## Current Known Issues

### Stem Crop Cropping

The latest user feedback:

- The crop is much better after restoring the vertical top crop.
- Some cropping issues remain and will be discussed later.
- The earlier vertical crop that removed the item-number/header area cut off half of the first line. That has been corrected.
- The current crop removes left margin only, aiming to remove the PDF item number without cutting the first line vertically.

Likely next work:

- Fine-tune horizontal crop amount.
- Possibly detect actual first text x-position instead of using a fixed left crop.
- Possibly detect first answer-choice row more robustly.
- Support multi-page stems better if needed.

### Image Highlighting Not Yet Implemented

The user needs to be able to highlight parts of the question stem while taking a test.

Now that stems may be images, text selection highlighting will not work on the stem crop.

Recommended next phase:

- Add image-rectangle highlighting.
- Store highlights as normalized percentage coordinates:

```js
{
  imageIndex: 0,
  x: 0.21,
  y: 0.34,
  w: 0.18,
  h: 0.04,
  color: "yellow"
}
```

This preserves highlight alignment when images resize.

### Parser Still Imperfect

The parser still has known failures, especially for text stems with labs.

However, the current product direction is to reduce dependence on parsed stems by showing original PDF stem crops.

Do not spend more time on endless phantom-space word patches unless the user specifically redirects back to parsed text quality.

### Answer Explanations

Answer explanations are still parsed text, not images.

Known issues include:

- Phantom spacing in explanations.
- Broken paragraph fragments.
- Acronym splits, eg `M / O / D`.
- Repeated explanation fragments in some cases.

This remains a separate problem after stem images are stabilized.

## Important Files And Functions

All paths below are inside `index.html`.

- `FigureStore`: IndexedDB image storage.
- `fixLigatureSpaces(str)`: text-level phantom spacing repair.
- `_REAL_WORDS`: dictionary used by `fixLigatureSpaces()`.
- `joinItems(items)`: always joins PDF text items with spaces, then runs cleanup.
- `splitMergedOptions(line)`: splits merged answer choices.
- `splitLabValues(line)`: currently guarded to avoid destructive splitting of prose.
- `extractPdfText(file, onProgress)`: PDF extraction, page rendering, figure/lab/stem crop creation.
- `groupPagesByItem(pages)`: groups extracted page data and exhibits by item.
- `parseOneQuestion(num, paragraphs)`: converts grouped question paragraphs to stem/options.
- `parseOneAnswer(num, paragraphs)`: converts answer-key paragraphs to correct answer/explanation.
- `processTestPDFs(questionFile, answerFile, onProgress)`: main generate pipeline.
- `renderImages(q, topElId, bottomElId)`: loads images from `FigureStore` and renders them.
- `renderQuestion()`: quiz view rendering.
- `buildParseAudit(questions)`: structural parse diagnostics.
- `diagnoseGeneratedQuestions(questions)`: OCR issue diagnostics.
- `saveGeneratedTest(skipOcrReview, skipParseAudit)`: saves tests and writes exhibit data to `FigureStore`.

## Test PDFs Used

The current debugging set:

- `/Users/shamsulalam/Desktop/Psychiatry/5 questions.pdf`
- `/Users/shamsulalam/Desktop/Psychiatry/5 answers.pdf`

Problematic items discussed:

- Item 5: labs/stem issue, now using image crop as stem.
- Item 28: labs/stem issue, now using image crop as stem.
- Item 34: labs-only parsed stem issue, now using image crop as stem.
- Item 48: figure/image exhibit issue, should be preserved by image crop/exhibit approach.

## What To Do Next

When resuming:

1. Ask the user which cropping issue they want to address first.
2. Avoid changing OCR/token logic unless specifically needed.
3. Keep the next change focused on stem crop quality or image highlighting.
4. If adjusting crops:
   - Do not crop vertically into the first stem line.
   - Prefer horizontal cropping of the item-number margin.
   - Consider using detected text x-positions rather than a fixed left crop.
5. If adding highlighting:
   - Implement rectangle highlights on image stems.
   - Store normalized coordinates.
   - Preserve existing text highlighting behavior for non-image stems.

## Verification Already Run

After recent edits:

- Inline JavaScript syntax check passed.
- `git diff --check` passed.

The user still needs to verify visual crop quality by refreshing and regenerating a new test, since previously generated tests retain older crop images.
