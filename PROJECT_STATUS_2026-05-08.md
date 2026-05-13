# NBME Self-Assessment Suite Project Status

Last updated: 2026-05-11

This file captures the current working state after the landing-page library rehaul, PDF report naming update, and local grouped-question parser/render stabilization. It supersedes older status files where they conflict.

Ownership: this file is the current runtime/status snapshot. Durable rules belong in `PROJECT_CONTEXT.md`; staged Electron roadmap details belong in `ELECTRON_MIGRATION_PLAN.md`; prompt files are operational guidance only.

## Core Rules

- `index.html` is the authoritative working app.
- Keep active app edits inside `index.html`.
- Do not split the current browser app into external CSS or JS files.
- Long-term platform direction: Electron desktop is now the intended primary platform. Browser mode and Netlify remain transitional compatibility layers during migration.
- The Electron migration may add Electron-specific scaffolding such as `package.json`, `electron/main.js`, and `electron/preload.js`. That does not change `index.html` being the current authoritative app during the transition.
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
- Google Drive OAuth currently requires opening the app from an approved HTTP/HTTPS origin, not `file://`, when connecting or syncing Drive. Primary local origin: `http://localhost:8888`; secondary/fallback local origin: `http://localhost:8080`.
- The app is currently private/personal use only. Future Electron security decisions, including local user-provided API key storage or OAuth token storage, should be evaluated in that context and revisited if public distribution is ever planned.

## Current File State

- Active app: `index.html`
- Informational snapshot at time of this update: `index.html` is about 9812 lines and 455 KB. Treat this as a timestamped reference, not a required invariant.
- Previous handoffs:
  - `PROJECT_STATUS_2026-05-06.md`
  - `PROJECT_STATUS_2026-05-07.md`
- Current handoff: `PROJECT_STATUS_2026-05-08.md`
- Stable local checkpoint commit: `2ba4b1d Stabilize parser/render pipeline before Electron migration`
- Local branch status at documentation update: `main` is ahead of `origin/main` by one commit.
- Current uncommitted working tree at time of this documentation update:
  - Documentation/prompt files are being synchronized with the current Electron and UWorld pipeline state.
  - `deno.lock` is untracked and should not be touched unless explicitly requested.
- `.DS_Store` is unrelated and should not be touched unless explicitly requested.
- No push or Netlify deploy has been performed after checkpoint `2ba4b1d` from this checkout.
- Source-level validation across NBME, UWorld, Anki, and OME passed without modifying files during validation.
- Runtime and live fixture validation remain pending.
- Gemini validation remains intentionally deferred to conserve API credits.

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
- Anki text-import pipeline: plain-text `.txt` import only, normalized card preview, cloze/basic concept extraction, tag-first clustering, deterministic variant draft preview, review controls, approved-variant JSON export, quiz-object preview, and controlled save into real tests.
- OME PDF pipeline: short high-quality PDF import only, PDF.js text-layer extraction only, structure/block preview, concept extraction, concept clustering, selected clusters, deterministic draft preview, review controls, approved-draft JSON export, quiz-object preview, and controlled save into real tests.

## Current Stable Parser And Rendering State

The grouped-question pipeline is currently stable and locally verified.

Confirmed behavior:

- OCR, normalization, parsing, answer/explanation merge, final quiz construction, and rendering preserve the expected source question count.
- Parser/render counts match expected source question counts.
- No unintended question loss is currently observed across OCR, normalization, parsing, merge, final quiz construction, and rendering.
- Source-number recovery is functioning when an OCR page has no parsed header item number but the normalized paragraph text contains a recoverable item number.
- Source-question numbering is preserved separately from generated quiz display order.
- Source-number audits and final-count integrity checks are functioning.
- Quoted answer-choice parsing is functioning.
- Grouped-question carry-forward logic is functioning.
- Grouped shared instructions and shared stems render correctly.
- Grouped answer banks render once, use `sharedGroup.sharedChoices` as the authoritative choice source, and remain independently selectable and independently scored for each linked question.
- Grouped rendering order is stable: shared instruction, shared stem, individual parsed stem, then one selectable answer-choice section.
- Grouped rendering prioritizes structured parsed text over cropped stem-image layout when stem crops would duplicate or misorder grouped content.
- Duplicate lab/table fragments are suppressed in grouped rendering when they are already present in the parsed individual stem.
- OCR normalization fixes for damaged screenshot-based text are functioning and should remain conservative.
- Temporary question-specific debugging instrumentation has been removed.

General parser/debug infrastructure preserved:

- Local-only parser debug export buttons.
- Raw OCR and normalized OCR export data.
- Focused debug exports.
- Source-number recovery audits.
- Grouped range audits.
- Final rendered question array audits.
- `parseSkippedItems` diagnostics for parser misses.
- Parser fixtures and grouped-question fixtures.
- Quoted-choice parser checks.
- Local-only debug tooling should stay hidden or disabled in production unless intentionally exposed.
- Parser debug artifacts may contain copyrighted or private exam content and should remain local/private.

Operational status:

- This stabilized state is local only.
- Stable local checkpoint commit exists: `2ba4b1d`.
- Electron Stage 1 dev scaffolding has been added and Stage 2 local HTTP loading has been verified.
- Browser app remains the stable baseline and fallback.
- No push, pull request, or Netlify deployment has been performed after checkpoint `2ba4b1d` from this checkout.
- Documentation and reusable prompt files are being organized for continuity across ChatGPT/Codex accounts.
- Netlify Functions and deployment settings remain transitional/rollback layers. Electron-local UWorld Gemini refinement now uses Electron main/preload and reads `GEMINI_API_KEY` from `process.env` only.
- Saved/generated quizzes created before parser or render fixes may be stale. Do not silently mutate existing saved quizzes; regenerate or explicitly reparse them.

## Future Importer And Render Architecture

Electron migration is in early staged development and planning. The long-term target is a desktop-only Electron app, with browser/Netlify support retained only as transitional compatibility until desktop-native replacements are verified.

Electron should continue wrapping the current stable app without changing app behavior. Avoid rewrites during initial migration.

Electron work should begin locally and should not trigger Netlify deployments initially.

Future architecture should preserve the current working behavior during transition while separating importer, parser, review, renderer, storage, and desktop-native service responsibilities more clearly.

Planned direction:

- All source types should normalize into a common intermediate format before quiz generation.
- Do not overfit importers to NBME. Use source adapters for multiple modalities, including PDFs, DOCX, pasted text, Anki, audio/podcast transcripts, video transcripts, and lecture notes.
- The common intermediate format should preserve raw OCR, normalized text, parsed structured question data, source numbering metadata, answer/explanation mappings, confidence, warnings, and available stem/image crops.
- Future render architecture should support per-question text, image, and hybrid render modes.
- Render mode should be reviewable and editable by the user before final quiz generation when confidence is low or content type is ambiguous.
- Render behavior should be driven by metadata, parse confidence, available structured content, and content type, not by historical question numbers.
- The importer should preserve both parsed text and stem/image crops when available so the app can choose the safest render mode without losing source evidence.
- Future architecture is moving toward a canonical intermediate question schema that separates OCR repair, normalization, semantic parsing, rendering, and persistence.
- Future architecture may further separate OCR cleanup, semantic parsing, and render adaptation to reduce coupling and regression risk.

Render-mode decision policy:

- Text mode for clean structured stems and grouped questions.
- Image mode for figure-heavy, layout-sensitive, or OCR-corrupted stems.
- Hybrid mode for usable text plus figures, tables, or images.
- User review and override per question.

Electron Gemini direction:

- Netlify Functions remain available as transitional/rollback support.
- Electron-local UWorld refinement now uses Electron main/preload.
- `GEMINI_API_KEY` is read from `process.env` only for Electron-local refinement.
- Do not remove Netlify Functions until desktop Gemini, storage, backup/restore, and rollback behavior are verified.
- Preserve `gemini-2.5-flash`.

Storage direction:

- Browser `localStorage` and IndexedDB/FigureStore remain active during transition.
- Long-term Electron storage should move quiz metadata, source artifacts, figures, backups, settings, parser runs, and debug exports into local app-data.
- Do not migrate or remove browser storage paths until app-data export/import, backup, restore, and rollback are verified.

## UWorld DOCX Pipeline Status

Status: UWorld v1 implementation complete. Electron Gemini JSON extraction hardened (tagged uworld-gemini-v1-stable). Pending real-world validation.

Implemented UWorld Notes flow:

```text
DOCX import
→ normalized blocks
→ concept extraction
→ deterministic clustering/deduplication
→ selected clusters
→ deterministic draft scaffolds
→ one-at-a-time Electron-local Gemini refinement
→ review controls
→ duplicate warnings and section/topic coverage summaries
→ approved draft JSON export
→ quiz-object preview
→ controlled save into real tests
```

Current safeguards:

- UWorld pipeline is separate from `OCR.processTestPDFs()` and the NBME PDF parser/render path.
- Concept clustering and selected-cluster controls are implemented.
- Draft previews are deterministic scaffolds until refined.
- Electron-local Gemini refinement is called through Electron main/preload only; renderer code does not receive API keys.
- `GEMINI_API_KEY` is read from `process.env` only and must not be stored in localStorage, frontend code, Drive backups, debug exports, or packaged assets.
- Live batch queue infrastructure is implemented for selected deterministic drafts. It processes one draft at a time through the existing Electron Gemini bridge, caches by draft hash, skips duplicate draft hashes, supports pause/cancel/retry, stops after consecutive failures, and requires a visible preflight confirmation before live runs.
- Duplicate refined-question warnings are implemented for similar stems, teaching points, source concepts, source blocks, and clusters. These warnings do not auto-reject, auto-remove, approve, or block saving.
- Section/topic coverage summaries are implemented from selected clusters, deterministic drafts, refined drafts, approved drafts, duplicate warnings, and coverage gaps. They are display-only and do not rebalance or filter generation.
- UWorld save into a real test requires approved refined drafts, valid quiz-object preview, explicit UWorld save target, nonempty inline test name, and inline review confirmation.
- Browser `prompt()`/`confirm()` are not part of the UWorld save flow.
- Live Gemini validation/testing is intentionally deferred to conserve API credits.

Bug fixed (2026-05-11, electron/main.js only):

- `extractGeminiJson()` previously stripped only simple leading/trailing markdown fences and called `JSON.parse()` once. Any prose before or after the JSON object caused `SyntaxError`, reported only as the generic "Gemini returned malformed JSON." message with no distinction from schema failures.
- Fixed with a two-attempt strategy: (1) strip fences and parse directly; (2) if that fails, scan for the first `{` and walk brace depth tracking string/escape state to extract the first complete top-level JSON object without `eval`. If both fail, throw `SyntaxError('no valid JSON object found in model response')`.
- Parse failures and schema validation failures now return separate `MODEL_RESPONSE_INVALID` messages with distinct `reason` fields. No API key, prompt text, or source content appears in any error message.
- `responseMimeType: 'application/json'` was already present in the request and was not changed.
- No auto-retry was added.

## Anki Notes Pipeline Status

Status: Anki v1 implementation complete. Approval-state and save-path bugs fixed (tagged anki-v1-stable). Pending real-world validation.

Current Anki flow:

```text
plain-text Anki export (.txt only)
→ normalized cards
→ cloze/basic concept extraction
→ tag-first clustering
→ deterministic variant draft preview
→ review controls
→ approved-variant JSON export
→ quiz-object preview
→ controlled save into real tests
```

Current Anki safeguards:

- `.apkg` is intentionally unsupported in Anki v1.
- Anki v1 does not use Gemini yet.
- Approved variants only are eligible for export, quiz-object preview, and controlled save.
- The Anki save path requires an explicit Anki subfolder target, a nonempty test name, and an inline review confirmation.
- Anki provenance stays separate from UWorld provenance and quiz-object review state.
- The Anki and UWorld pipelines remain isolated.

Bugs fixed (2026-05-11):

- `getApprovedAnkiVariantDrafts()` was going through an indirect path; now calls `getApprovedAnkiDraftsFromReviewSnapshot()` directly.
- `validateAnkiQuizObjectPreviewItem()` returns `{ ok, errors }`, not an array. Two call sites in `getApprovedAnkiQuizObjectPreviewValidation()` and `createTestFromApprovedAnkiVariants()` were calling `.map()` on the object, crashing the preview and save path. Fixed to `.errors.map()`.
- Temporary debug panels (Anki Review State Debug, Quiz Preview Debug) removed after fix confirmation.

Unresolved validation tasks:

- Validate the plain-text Anki import flow against several real `.txt` exports.
- Verify explicit target selection and new-folder creation in the Anki save path.
- Verify controlled save into a real test with approved variants only.
- Verify approved-variant JSON export and quiz-object preview with mixed note types and cloze groups.
- Confirm no cross-talk with the UWorld DOCX pipeline.

## OME Notes Pipeline Status

Status: OME v1 implementation complete. Cluster index provenance bug fixed (tagged ome-v1-stable). Pending real-world validation.

Current flow:

```text
short high-quality PDF
→ PDF.js text-layer extraction only
→ structure/block preview
→ concept extraction
→ concept clustering
→ selected clusters
→ deterministic draft preview
→ review controls
→ approved-draft JSON export
→ quiz-object preview
→ controlled save into real tests
```

Current safeguards:

- OME accepts short high-quality PDFs in v1.
- OME intentionally does not add OCR fallback in v1.
- OME preview uses PDF.js text-layer extraction only.
- OME structure, concept, cluster, draft, review, export, preview, and save logic stay isolated from the NBME PDF parser/OCR/render path, the UWorld DOCX path, and the Anki path.
- Approved OME drafts only are eligible for export, quiz-object preview, and controlled save.
- The OME save flow requires an explicit OME subfolder target, a nonempty test name, and an inline review confirmation.
- OME provenance stays separate from UWorld provenance and Anki provenance.
- No Gemini is used in OME v1 yet.
- OME v1 does not modify NBME parser/OCR/render behavior.

Bug fixed (2026-05-11):

- `createOmeCluster(members, index)` built the cluster `id` from `index` but never stored `clusterIndex: index` on the returned object. All downstream provenance reads got `undefined`, which propagated as `null` through quiz-object preview and failed `Number.isFinite(null)` validation, blocking save. Fixed by adding `clusterIndex: index` to the returned object.

Unresolved validation tasks:

- Verify real short OME PDFs import cleanly with PDF.js text-layer extraction only.
- Verify structure/block preview on PDFs with columns, tables, charts, algorithms, and diagrams.
- Verify concept extraction and clustering do not cross into UWorld or Anki paths.
- Verify selected-cluster draft previews, review controls, approved-draft JSON export, quiz-object preview, and controlled save into a real test.
- Confirm the no-OCR-fallback rule remains intact on real OME fixtures.

Current UWorld batch flow:

```text
selected clusters
→ deterministic drafts
→ one-at-a-time queue
→ cache by draft hash
→ pause/cancel/retry
→ preflight confirmation
→ review-gated save
```

`deno.lock` remains untracked and should not be touched unless explicitly requested.

## Historical Implementation And Debugging Notes

The following notes are historical debugging findings only. They should not be treated as active architectural logic, permanent assumptions, or source-question-specific behavior.

- Grouped-question rendering previously duplicated answer banks when cropped source-layout stems included the shared answer bank and the selectable choices rendered again below.
- Shared answer-bank ordering issues were caused by render/layout selection after parser grouping was already correct.
- Grouped carry-forward debugging showed that a shared group must remain active until the expected number of linked questions is assigned, even when later questions repeat only the shared stem or answer bank.
- Dropped-question recovery debugging showed that item pages should not be discarded solely because the OCR header item number is missing when paragraph-level item numbers are recoverable.
- OCR damage recovery examples included damaged age text, quoted answer choices, and duplicate lab/table fragments extracted from text already present in the stem.
- Historical source item numbers used during debugging are examples only and should not be encoded as future architectural rules.

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
- Local development should use `http://localhost:8888` as the primary origin, or `http://localhost:8080` as a secondary/fallback origin, only if those origins are added in Google Cloud Console.
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

Browser/Netlify Gemini calls still run through Netlify Functions. Electron-local UWorld refinement runs through Electron main/preload. `GEMINI_API_KEY` must not be stored in frontend JavaScript, renderer code, localStorage, Google Drive backups, debug exports, or packaged assets.

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

## Render Modes And Stem Assets

The current app supports image-based stems for ordinary non-grouped questions and structured parsed text for grouped questions when crops would duplicate or misorder grouped content. Future work should formalize this into text, image, and hybrid render modes.

Implemented:

- Cropped PDF stem images are generated from the original PDF page.
- The crop removes the NBME item number area on the left.
- Parsed text stems are hidden when a stem image exists for ordinary non-grouped questions.
- For grouped questions, structured parsed text is preferred when a stem crop would preserve the source-layout answer bank above the patient stem or otherwise duplicate grouped content.
- Stem images are rendered as the main question stem when the selected render mode is image-based.
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

Recent verification after the latest local parser/render stabilization:

- Inline JavaScript syntax check passed.
- Grouped parser fixtures passed.
- Quoted A-E answer-choice parsing check passed.
- Local debug exports confirmed stable parser/render counts in the affected workflow.
- Temporary question-specific debug instrumentation was removed after confirmation.
- Existing saved/generated quizzes may not automatically reflect parser or render fixes. Regenerate or explicitly reparse rather than silently mutating stored user data.
- Electron Stage 2 verification passed: the Electron dev wrapper loads the existing app over `http://localhost:8888`.
- Electron does not use `file://` for the app load path.
- Browser/Netlify mode still works and remains the stable fallback.
- Basic Electron interaction verification passed.
- Gemini live validation for UWorld v1 is intentionally deferred to conserve API credits.
- No parser, render, OCR, Gemini, or Google Drive logic was modified for Stage 2 verification.

Verification after 2026-05-11 bug fixes:

- `node -c electron/main.js` syntax check passed.
- `git diff --check` whitespace check passed on `electron/main.js`.
- No API key, prompt text, or source content exposed in any error path (confirmed by diff sweep).
- Only `electron/main.js` was modified; `index.html`, `electron/preload.js`, and `deno.lock` were not touched.
- Anki `.errors.map` fix: `node -c` syntax check on `index.html` passed; no NBME/UWorld/OME/Gemini logic modified.
- OME `clusterIndex` fix: single-line change to `createOmeCluster`; no NBME/UWorld/Anki/Gemini logic modified.

For deployment and sync testing, use the deployed HTTPS Netlify URL or Netlify local dev. Do not test Drive or Gemini from a `file://` URL.

## High-Risk Areas

Use extra caution around:

- `DB.save()` and `storagePayload()`, because they protect localStorage from large image payloads.
- `FigureStore`, because it owns large local images.
- Google Drive backup/restore, because it is the durable cross-device image path.
- OCR parsing and stem crop logic, because previous spacing fixes became unstable when handled with broad token surgery.
- Avoid broad OCR normalization rules. OCR fixes should be conservative, traceable, and covered by fixtures because broad spacing/token cleanup previously caused instability.
- PDF report generation, because jsPDF layout is sensitive to font state, page breaks, and text normalization.
- Landing/source-folder routing, because it now determines which subfolders are visible and where new tests are created.

## Recommended Next Steps

- Remaining work is real-world validation and eventual modularization, not new importers.
- Validate Anki v1 end-to-end against real `.txt` exports; confirm approval → preview → save path with mixed note types.
- Validate OME v1 end-to-end against real short high-quality PDFs; confirm cluster provenance, approved-draft export, quiz-object preview, and controlled save.
- Validate UWorld v1 Electron Gemini refinement with a small live batch using real imported notes before any large run.
- Continue Electron migration by adding desktop-native storage, backup/restore, and Gemini service boundaries as the next planned phase.
- During Electron migration, preserve the current local browser behavior before changing importer or renderer architecture.
- Design the future importer around a common intermediate format shared by PDFs, DOCX, pasted text, Anki, audio/podcast transcripts, video transcripts, lecture notes, screenshots, and future source types.
- Add a reviewable render-mode decision layer so each question can be displayed as text, image, or hybrid based on metadata, confidence, and content type.
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
