# NBME Self-Assessment Suite — Project Status

**Last updated:** 2026-05-12  
**Supersedes:** PROJECT_STATUS_2026-05-08.md  
**Purpose:** Master handoff document for migration from Claude Code → Codex. Zero-ambiguity snapshot.

---

## 1. How to Run the App

### Development (use this — edits to index.html are immediately reflected)
```bash
cd "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite"
npm install          # only needed first time or after dependency changes
npm run electron:dev
```
Electron starts, embeds an HTTP server at `http://localhost:8888` (fallback `8080`), and loads `index.html` from the project root.

### Packaged App (DO NOT USE FOR DEVELOPMENT)
The built `.app` lives at:
```
dist/mac-arm64/NBME Self-Assessment Suite.app
```
**Critical caveat:** This bundle contains its own copy of `index.html` inside:
```
dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html
```
The packaged app reads from the bundle, NOT from the project root. Edits to the project's `index.html` are invisible when the `.app` is opened directly. This caused multiple diagnosis failures during May 12 debugging because the running app was always stale.

To sync the built app with current source manually:
```bash
cp "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html" \
   "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html"
```
This was done on 2026-05-12 19:13. The dist and source are currently in sync (both 1,073,458 bytes).

**For all future development: use `npm run electron:dev` only.**

---

## 2. Architecture Overview

The app is a single-file SPA: **`index.html`** (21,727 lines as of 2026-05-12).

All application code is inline — HTML, CSS, and JavaScript in one file. No external local JS or CSS files are loaded. CDN scripts only:
- PDF.js (3.11.174)
- Tesseract.js (5)
- jsPDF (2.5.1)
- html-docx-js
- Google GSI client

### Inline module layout (inside index.html)
| Module | Role |
|--------|------|
| `DB` IIFE | localStorage read/write; tests, folders, flags, marks, notes, history |
| `FigureStore` | IndexedDB large image storage |
| Stem rendering helpers | `window.buildStemHTML`, `window.buildQuestionStemHTML`, `window.buildSharedGroupHTML`, `window._ngjFigureToHTML`, `window._replaceFigureMarkersInStemHtml` |
| `Quiz` IIFE | Test-taking engine: state, navigation, answer selection, explanation rendering |
| `Results` | Score report, review mode |
| `App` IIFE | Everything else: home screen, modals, all importer pipelines, sidebar, search |

### Electron shell
- `electron/main.js` — embedded HTTP server (127.0.0.1:8888), IPC handlers for Gemini
- `electron/preload.js` — exposes `window.nbmeDesktop` bridge only (no broad Node access)
- `package.json` — `"main": "electron/main.js"`, scripts: `electron:dev`, `electron:build:mac`

---

## 3. Storage Architecture

### localStorage (`DB`)
Key: `nbme_app_v1`

Structure:
```javascript
{
  version: 1,
  settings: {},
  sourceFolders: [...],  // NBME, UWorld, Anki, OME, Divine, Mehlman, Images, Amboss
  folders: [],           // user-created subfolders
  tests: [],             // all saved tests with questions embedded
  trash: [],
  flags: [],
  marks: [],
  notes: [],
  history: []
}
```

`DB.createTest(folderId, name, questions)` → creates test, pushes to `db.tests`, saves.  
`DB.updateTest(id, updates)` → `Object.assign(db.tests[idx], updates)`, saves.  
Both use full `JSON.stringify` — all question fields (including `correctBlurb`, `educationalObjective`, `metadata`) are persisted.

**~5 MB localStorage limit.** Figure images stored in IndexedDB via `FigureStore`, not localStorage. Exception: `q.metadata.figureAttachments[figureId]` (base64 dataUrls for uploaded figures) IS in localStorage via test questions — warn if total images exceed ~3 MB.

### IndexedDB (`FigureStore`)
Large stem/exhibit images from the PDF OCR pipeline. Not used by the NBME JSON importer (which stores small attached images directly in localStorage).

---

## 4. Source Pipelines (Status Summary)

| Pipeline | Status | Gemini |
|----------|--------|--------|
| NBME PDF OCR | Stable (pre-May-12) | No |
| NBME ChatGPT/Gemini JSON Import | **Partially working — see §7** | No (import only) |
| UWorld DOCX | Stable (tagged uworld-gemini-v1-stable) | Yes (Electron IPC) |
| OME PDF | Stable (tagged ome-v1-stable) | No |
| Anki text | Stable (tagged anki-v1-stable) | No |
| Divine Podcasts | Stable (tagged divine-gemini-v1-stable) | Yes (Electron IPC) |
| Mehlman | Stable (tagged mehlman-v1-stable) | No |

---

## 5. NBME ChatGPT/Gemini JSON Import — Detailed Status

### What it is
A new import workflow added in May 2026. Accepts structured JSON extracted by ChatGPT Pro (or Gemini) from NBME self-assessment PDFs. Parallel to (not replacing) the existing OCR PDF importer.

### Entry point
Button in home header (line ~1115):
```html
<button onclick="App.openNbmeGeminiJsonImportModal()" style="background:#0d5c2b;">
  ↓ NBME JSON Import
</button>
```
Opens `#modal-nbme-gemini-json`.

### sourceType
All questions saved via this importer have `q.metadata.sourceType = 'nbme-gemini-json'`.

### Canonical JSON schema expected
```json
{
  "testTitle": "string",
  "sourceFormat": "string",
  "expectedQuestionCount": number,
  "actualExtractedQuestionCount": number,
  "extractionWarnings": ["string"],
  "questions": [
    {
      "questionNumber": number,
      "sourceQuestionNumber": number | null,
      "id": "string | null",
      "retrievalTag": "string",
      "stem": "string",
      "hasEmbeddedFigure": boolean,
      "figureRefs": [
        {
          "figureId": "string",
          "placeholder": "[FIGURE: figureId]",
          "sourceLocation": "stem | explanation",
          "description": "string",
          "visibleText": ["string"]
        }
      ],
      "answerChoices": [
        { "label": "A", "text": "string" }
      ],
      "correctAnswer": "A",
      "educationalObjective": "string",
      "explanationSections": [
        {
          "heading": "string",
          "body": ["string"]
        }
      ],
      "tables": [],
      "sharedGroup": null,
      "extractionWarnings": ["string"]
    }
  ]
}
```

### Internal quiz question schema (after normalization)
```javascript
{
  n: questionNumber,          // integer
  t: stem,                    // full string, NO truncation
  o: [{ l: "A", t: "text" }], // answer choices
  c: "E",                     // correctAnswer letter
  e: { "A": "escaped html", "B": "..." }, // per-choice explanations (from "Incorrect Answers" section)
  tags: ["retrievalTag"],
  educationalObjective: "string",
  correctBlurb: "HTML string", // pre-escaped HTML from all explanationSections
  metadata: {
    sourceType: "nbme-gemini-json",
    sourceQuestionNumber: number | null,
    sourceId: "string | null",
    retrievalTag: "string",
    hasEmbeddedFigure: boolean,
    figureRefs: [...],
    figureAttachments: {},    // { figureId: "data:image/png;base64,..." }
    tables: [],
    sharedGroup: null,
    extractionWarnings: [],
    explanationSections: [...],
    schemaVersion: "nbme-gemini-json-v1"
  }
}
```

### Import workflow
1. User clicks "NBME JSON Import" button → modal opens
2. User uploads `.json` file or pastes JSON text
3. User clicks "Validate JSON"
4. `parseNbmeGeminiJson()` runs:
   - RTF detection (`_ngjDetectRtfOrBinary`)
   - JSON.parse
   - Unescaped quote detection (`_ngjDetectUnescapedQuotes`)
   - `validateNbmeGeminiJsonImport(payload)` → `{isValid, blockingErrors[], warnings[], questionResults[], counts{}}`
   - If valid: `normalizeNbmeGeminiJsonImport(payload)` → stored in `_nbmeGeminiJsonImport.normalizedItems`
   - `renderNbmeGeminiJsonValidationSummary()`
   - `renderNbmeGeminiJsonPreview()` (shows all questions with full stems — no truncation)
   - `renderNbmeGeminiJsonFigureAttachSection()` (shows figure upload panel if any figureRefs)
   - `updateNbmeGeminiJsonSaveReadiness()`
5. User enters test name, selects target folder, checks confirmation checkbox
6. User clicks "Save Test"
7. `createTestFromNbmeGeminiJsonImport()`:
   - Copies `figureAttachments` from state into each question's `metadata.figureAttachments`
   - `DB.createTest(folderId, testName, questions)`
   - `DB.updateTest(test.id, { sourceType, importMetadata: { ... } })`
   - Closes modal, refreshes sidebar

### Validation rules
**Blocking (prevents save):**
- `questions` array missing or empty
- Any question: `stem` empty
- Any question: `answerChoices` not array or < 2 items
- Any question: `correctAnswer` missing
- Any question: `correctAnswer` not present in answer choice labels
- Any question: any answer choice missing `label` or `text`

**Warnings (non-blocking):**
- `educationalObjective` missing/empty
- `explanationSections` missing or empty
- `figureRefs` present (unresolved figures)
- Unknown top-level fields
- Top-level `extractionWarnings` present
- `expectedQuestionCount`/`actualExtractedQuestionCount` present

### Key functions and line ranges (index.html, 2026-05-12)
| Function | Line | Role |
|----------|------|------|
| `openNbmeGeminiJsonImportModal` | ~20579 | Opens modal, initializes state |
| `closeNbmeGeminiJsonImportModal` | ~20615 | Hides modal |
| `clearNbmeGeminiJsonImportState` | ~20619 | Resets `_nbmeGeminiJsonImport` including `figureAttachments: {}` |
| `handleNbmeGeminiJsonFileUpload` | ~20638 | FileReader → textarea |
| `_ngjDetectRtfOrBinary` | ~20660 | RTF/binary detection |
| `_ngjDetectUnescapedQuotes` | ~20666 | Malformed JSON hint |
| `validateNbmeGeminiJsonImport` | ~20685 | Full validation |
| `_ngjZeroCounts` | ~20905 | Validation counter init |
| `_ngjBuildCorrectBlurb` | ~20909 | Builds `correctBlurb` HTML from explanationSections |
| `_ngjBuildPerChoiceExplanations` | ~20923 | Parses "Incorrect Answers" section into `q.e` |
| `normalizeNbmeGeminiJsonImport` | ~20952 | Maps JSON schema → internal quiz schema |
| `parseNbmeGeminiJson` | ~21006 | Full parse+validate+normalize orchestrator |
| `renderNbmeGeminiJsonValidationSummary` | ~21077 | Validation result UI |
| `renderNbmeGeminiJsonPreview` | ~21136 | Question list preview |
| `updateNbmeGeminiJsonSaveReadiness` | ~21199 | Controls Save/Save-valid buttons |
| `renderNbmeGeminiJsonFigureAttachSection` | ~21284 | Figure upload UI |
| `ngjHandleFigureUpload` | ~21340 | FileReader for image, stores dataUrl |
| `ngjRemoveFigureAttachment` | ~21359 | Removes stored image |
| `createTestFromNbmeGeminiJsonImport` | ~21363 | DB save + metadata |
| `saveValidNbmeGeminiJsonQuestionsOnly` | (in return object) | Partial save (stub exposed, body may be incomplete — verify) |

### State variable
```javascript
let _nbmeGeminiJsonImport = {
  rawText: '',
  parsed: null,
  validation: null,
  normalizedItems: [],
  fileName: '',
  testName: '',
  targetFolder: '',
  confirmed: false,
  figureAttachments: {},     // { figureId: base64DataUrl }
  lastSaveResult: null,
  lastSaveError: null
};
```

---

## 6. Explanation Rendering

### Status: Code correct — end-to-end validation PENDING

Both `buildExplanationHTML` functions were updated on 2026-05-12 to render `q.correctBlurb` and `q.educationalObjective`. Previously they only rendered `q.explanation` (the PDF OCR field), which was never populated by the JSON importer.

### Render order (after fix)
1. **Correct answer header block** — always shown
2. **Educational Objective** (blue bordered box) — if `q.educationalObjective` non-empty
3. **Correct Blurb** (`q.correctBlurb` as `innerHTML`) — if non-empty; contains all explanationSections as pre-escaped HTML with `<strong>` headings and `<br><br>` separators
4. **Legacy explanation** (`q.explanation`) — for PDF OCR imports only

### Two copies of buildExplanationHTML
1. **Local** inside `Quiz` IIFE (~line 5640): used by `renderExplanation()` during quiz play
2. **Global** `window.buildExplanationHTML` (~line 5820): used by Results review screen

Both were patched identically.

### q.correctBlurb format
Pre-escaped HTML string built by `_ngjBuildCorrectBlurb(sections, educationalObjective)`:
```html
<strong>Evaluation</strong><br><br>text...<br><br><strong>Prevention</strong><br><br>text...
```
Rendered as `.innerHTML` into `.exp-blurb` div. Safe: all text is `_ngjEsc()`-escaped.

### q.e format
Object keyed by answer choice letter:
```javascript
{ "A": "escaped html text", "B": "escaped html text" }
```
Populated from "Incorrect Answers" section using single (`Choice B: ...`) and multi-letter (`Choices A, C, and D: ...`) patterns. **NOTE:** `q.e` is populated but not yet rendered in the explanation panel. The "Incorrect Answers" content is captured in `correctBlurb` under the "Incorrect Answers" heading, so it does appear — but `q.e` per-choice inline rendering is not implemented in the renderer.

### Caveat
Tests imported BEFORE 2026-05-12 will not have `q.correctBlurb` populated (the old importer did not build it; this was a renderer-only fix). Those tests must be **deleted and re-imported** to get explanations.

---

## 7. UNRESOLVED BUG: Stem Truncation in Quiz View

**Status: UNRESOLVED. Do not mark fixed.**

### Observed behavior
When taking a quiz with questions from `Psych_Shelf_8_full_app_ready.json`:
- Q1 (608 chars), Q9 (828 chars), Q11 (1160 chars), Q24 (1319 chars) display only ~1–2 visible lines of stem text
- The remaining stem text is inaccessible — no scrollbar reveals it
- Answer choices ARE visible
- No ellipsis (`…`) appears in the stem display

### Source data confirmed complete
```
Q1:  stem length = 608 chars, no newlines
Q9:  stem length = 828 chars, no newlines
Q11: stem length = 1160 chars, no newlines
Q24: stem length = 1319 chars, no newlines
```
All four are single-paragraph stems (no `\n\n`). `buildStemHTML` renders them as `<p>full text</p>`.

### Attempted fixes (all UNVERIFIED or FAILED)

**Fix 1: Import preview truncation** (confirmed fixed, NOT the quiz bug)
- Removed `.slice(0, 240)` from `stemPreview` at line ~21080
- Was causing import PREVIEW modal to show truncated stems
- Did NOT fix the quiz view — different code path entirely

**Fix 2: CSS flexbox overflow** (theoretically sound, empirically UNCONFIRMED)
- Added `overflow-y: auto; overflow-x: hidden; min-height: 0` to `.quiz-content-area` (line 546)
- Rationale: `.quiz-content-area { flex: 1 }` inside `#quiz-main { overflow-y: auto }` — flex layout reports total child height = container height, so `#quiz-main`'s scroll never triggers; `#screen-quiz { overflow: hidden }` clips the overflow
- The CSS change is in the source `index.html` and in the dist bundle
- User confirmed the issue STILL PERSISTS after this fix
- Therefore the root cause is NOT (or not only) this flexbox behavior

**Fix 3: Stale packaged build sync** (done, NOT sufficient)
- Discovered the built `.app` had a May 11 copy of `index.html` (missing all May 12 fixes)
- Synced source → dist on 2026-05-12 19:13
- User confirmed the issue STILL PERSISTS after sync
- Therefore stale build was a contributing factor but not the sole root cause

### What is NOT yet investigated
- Whether `shouldUseStemCropForQuestion(q)` returns `true` for these questions (if it does, the stem is replaced with `buildSharedGroupHTML(q)` which returns `''` for null sharedGroup → blank stem)
- Whether `r.highlights && r.highlights.html` is set (would use the highlights path instead of full stem)
- Actual DOM inspection of `#q-stem` element: `element.innerText.length`, `scrollHeight`, `clientHeight`, computed CSS
- Whether `-webkit-line-clamp` is applied via a rule not caught by static grep
- Whether there's a media query for small Electron window width that triggers a different layout
- Whether the quiz is rendering into a different element than `#q-stem`
- Whether `getQuestionChoices(q)` or any shared-group processing incorrectly transforms `q.t`

### Required next step for Codex
Add a visible debug box to the quiz view and use DevTools console to inspect the live DOM:

```javascript
// Run in DevTools console while Q1 is displayed in quiz mode:
var stemEl = document.getElementById('q-stem');
console.log('innerText length:', stemEl.innerText.length);
console.log('innerHTML length:', stemEl.innerHTML.length);
console.log('scrollHeight:', stemEl.scrollHeight);
console.log('clientHeight:', stemEl.clientHeight);
console.log('computed overflow:', getComputedStyle(stemEl).overflow);
console.log('computed max-height:', getComputedStyle(stemEl).maxHeight);
console.log('computed -webkit-line-clamp:', getComputedStyle(stemEl).webkitLineClamp);
console.log('computed display:', getComputedStyle(stemEl).display);
console.log('computed height:', getComputedStyle(stemEl).height);

// Also check parent containers:
var parent = stemEl.parentElement;
while (parent) {
  var cs = getComputedStyle(parent);
  if (cs.overflow !== 'visible' || cs.maxHeight !== 'none' || cs.height !== 'auto') {
    console.log('CLIPPING PARENT:', parent.id || parent.className, {
      overflow: cs.overflow, maxHeight: cs.maxHeight, height: cs.height
    });
  }
  parent = parent.parentElement;
}
```

Also check whether the CURRENT state object has the full stem:
```javascript
var state = Quiz.getState();
var q = state && state.testId && DB.get().tests.find(t => t.id === state.testId)?.questions[state.qIdx];
console.log('q.t length:', q && q.t.length);
console.log('q.t first 120:', q && q.t.slice(0, 120));
```

---

## 8. Figure Rendering System

### Status: Implemented, NOT end-to-end validated

### Architecture

**`window._ngjFigureToHTML(figureId, q)`** (line ~5183)
Priority order:
1. If `q.metadata.figureAttachments[figureId]` exists → `<img src="dataUrl">`
2. Else if `figureRef.visibleText` is non-empty → render as `<table class="lab-values-table">`
3. Else → `<div class="nbme-figure-placeholder">Figure not attached: [figureId]</div>`

**`window._replaceFigureMarkersInStemHtml(html, q)`** (line ~5221)
Post-processes stem HTML after `buildStemHTML`/`buildQuestionStemHTML`. Replaces `[FIGURE: figId]` patterns using regex. Safe because `[`, `]`, `:` are not HTML-escaped.

**`window.buildQuestionStemHTML(q, highlightedStemHtml)`** (line ~5168)
Modified to call `_replaceFigureMarkersInStemHtml(html, q)` on all returned HTML. This affects:
- Quiz play (`renderQuestion`, line ~5563)
- Results review screen (line ~6309)

### Questions with figures in test file
| Question | figureId | visibleText? | Description |
|----------|----------|--------------|-------------|
| Q25 | q25_fig1 | Yes (8 lab values) | Lab studies table |
| Q34 | q34_fig1 | Yes (10 lab values) | Lab studies table |
| Q48 | q48_fig1 | Yes (6 lab values) | Lab studies table |

All three will render as lab tables automatically without image upload (visibleText present).

### Figure attachment UI (import modal)
- Section `#ngj-figure-attach-section` shown after validation when figureRefs exist
- Per-figure: shows figureId, description, sourceLocation, visibleText, upload button
- Figures with visibleText labeled "Will render as lab table automatically"
- Upload stores dataUrl in `_nbmeGeminiJsonImport.figureAttachments[figureId]`
- Max image size: 2.5 MB per file
- Total image quota warning at 3 MB before save

### Figure persistence
`createTestFromNbmeGeminiJsonImport` copies attachments per-question:
```javascript
q.metadata.figureAttachments[figureId] = _nbmeGeminiJsonImport.figureAttachments[figureId]
```
Persisted via `DB.createTest` → `JSON.stringify`.

---

## 9. Test Files

| File | Path | Purpose |
|------|------|---------|
| 5-question chunk | `test-data:/Psych_SELF_5_question_test_chunk.json` | Small validation sample |
| Full 50-question | `test-data:/Psych_Shelf_8_full_app_ready.json` | Full test validation |

Note: The directory is named `test-data:` (with a literal colon) due to filesystem quirk.

The full file has:
- 50 questions, 0 blocking validation errors
- Q25, Q34, Q48 have figureRefs with visibleText
- Q1, Q9, Q11, Q24 have long single-paragraph stems showing truncation bug

---

## 10. Recent Change Log (May 12, 2026)

All changes to `index.html` only. No other files modified.

| Change | Location | Status |
|--------|----------|--------|
| Both `buildExplanationHTML` functions: added `q.educationalObjective` and `q.correctBlurb` rendering | Lines ~5640–5683 (local), ~5820–5870 (global) | Code correct; requires reimport to validate |
| `window.buildQuestionStemHTML`: calls `_replaceFigureMarkersInStemHtml` | Line ~5168 | Implemented |
| `window._ngjFigureToHTML`: figure → img/table/placeholder | Line ~5183 | Implemented |
| `window._replaceFigureMarkersInStemHtml`: regex post-processor | Line ~5221 | Implemented |
| `.quiz-content-area`: added `overflow-y: auto; min-height: 0` | Line 546 | In code, NOT confirmed fixing stem bug |
| `normalizeNbmeGeminiJsonImport`: `figureAttachments: {}` in metadata | Line ~20997 | Implemented |
| `clearNbmeGeminiJsonImportState`: `figureAttachments: {}` in initial state | Line ~20624 | Implemented |
| `renderNbmeGeminiJsonFigureAttachSection`: figure attachment UI | Line ~21284 | Implemented |
| `ngjHandleFigureUpload`, `ngjRemoveFigureAttachment` | Lines ~21340, ~21359 | Implemented |
| `createTestFromNbmeGeminiJsonImport`: copies figureAttachments, quota warning | Line ~21363 | Implemented |
| Import preview stem: removed `.slice(0, 240)` truncation | Line ~21094 | Confirmed fixed (preview only) |
| Figure attachment panel HTML + CSS | Lines ~1746, ~1700 | Implemented |
| Dist bundle synced with source | `dist/mac-arm64/.../index.html` | Done 19:13 May 12 |

---

## 11. Immediate Next Priorities for Codex

1. **[P0] Diagnose and fix stem truncation bug** — use DevTools console inspection (see §7). Do NOT retry CSS fixes blindly. Prove the active DOM path first.
2. **[P1] Validate explanation rendering end-to-end** — delete old imported test, reimport `Psych_Shelf_8_full_app_ready.json`, answer Q1, confirm Educational Objective and explanationSections appear.
3. **[P1] Validate figure auto-table rendering** — answer Q25, Q34, Q48, confirm lab table appears in stem.
4. **[P2] Complete `saveValidNbmeGeminiJsonQuestionsOnly`** — check whether the function body is fully implemented (Phase 3 was in progress at context limit).
5. **[P3] Add a `sync-dist.sh` script** or document the copy command clearly so future developers don't get caught by the stale-build trap.
