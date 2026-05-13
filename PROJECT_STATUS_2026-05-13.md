# NBME Self-Assessment Suite — Project Status

**Last updated:** 2026-05-13  
**Supersedes:** PROJECT_STATUS_2026-05-12.md  
**Purpose:** Master handoff snapshot. Zero-ambiguity current state.

---

## 1. How to Run the App

### Development (always use this)
```bash
cd "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite"
npm install          # first time only, or after dependency changes
npm run electron:dev
```
Electron starts, serves `index.html` from the project root via an embedded HTTP server at `127.0.0.1:8888` (fallback `8080`).

### Packaged App (do NOT use for development)
```
dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html
```
The bundle contains its own frozen copy of `index.html`. Edits to the project source are invisible when the `.app` is launched directly. A full rebuild is required: `npm run electron:build:mac`. See BUG-004 in `BUGS_AND_NEXT_STEPS.md` for the full history.

---

## 2. Architecture

Single-file SPA: **`index.html`** (~21,700+ lines). All HTML, CSS, and JS inline. No external local assets except `electron/main.js` and `electron/preload.js`.

### Inline module layout
| Module | Role |
|--------|------|
| `DB` IIFE | localStorage read/write: tests, folders, flags, marks, notes, history |
| `FigureStore` | IndexedDB: large stem/exhibit images (PDF OCR pipeline) |
| Stem rendering helpers | `window.buildStemHTML`, `window.buildQuestionStemHTML`, `window.buildSharedGroupHTML`, `window._ngjFigureToHTML`, `window._replaceFigureMarkersInStemHtml` |
| Sanitizers | `window._ngjSanitizeUiArtifactsText`, `window._ngjSanitizeQuestion`, `window._isNbmeOcrJunkLine` |
| `Quiz` IIFE | Test-taking engine: state, navigation, answer selection, explanation rendering |
| `Results` | Score report, review mode |
| `App` IIFE | Home screen, modals, all import pipelines, sidebar, search |

### Electron shell
- `electron/main.js` — embedded HTTP server, IPC handlers for Gemini
- `electron/preload.js` — exposes `window.nbmeDesktop` bridge
- `package.json` — `"main": "electron/main.js"`, scripts: `electron:dev`, `electron:build:mac`

---

## 3. Source Pipelines

| Pipeline | Status | Gemini |
|----------|--------|--------|
| NBME PDF OCR | Stable | No |
| NBME Gemini JSON Import | **Stable** — all bugs resolved, Psych Shelf 3–8 validated | No |
| UWorld DOCX | Stable (tagged `uworld-gemini-v1-stable`) | Yes (Electron IPC) |
| OME PDF | Stable (tagged `ome-v1-stable`) | No |
| Anki text | Stable (tagged `anki-v1-stable`) | No |
| Divine Podcasts | Stable (tagged `divine-gemini-v1-stable`) | Yes (Electron IPC) |
| Mehlman | Stable (tagged `mehlman-v1-stable`) | No |

---

## 4. NBME Gemini JSON Import — Current State

### Status
All blocking bugs resolved. Pipeline is stable. Psych Shelf 3–8 (300 questions total) imported and validated with 0 blocking errors. VAL-002 (figure rendering) and VAL-003 (save-valid-only) still pending end-to-end confirmation.

### Entry point
```html
<button onclick="App.openNbmeGeminiJsonImportModal()">↓ NBME JSON Import</button>
```
Opens `#modal-nbme-gemini-json-import`.

### Canonical JSON schema
```json
{
  "testTitle": "string",
  "expectedQuestionCount": number,
  "questions": [
    {
      "questionNumber": number,
      "stem": "string",
      "answerChoices": [{ "label": "A", "text": "string" }],
      "correctAnswer": "A",
      "educationalObjective": "string",
      "explanationSections": [{ "heading": "string", "body": ["string"] }],
      "figureRefs": [{ "figureId": "string", "location": "stem", "visibleText": ["string"] }],
      "tables": [{ "title": "string", "headers": ["string"], "rows": [["string"]] }],
      "sharedGroup": { "sharedStem": "string", "sharedChoices": [], "questionRange": {}, "linkedQuestionIds": [] },
      "retrievalTag": "string",
      "extractionWarnings": ["string"]
    }
  ]
}
```

### Internal quiz question schema (after normalization)
```javascript
{
  n: questionNumber,
  t: stem,                         // full string, no truncation
  o: [{ l: "A", t: "text" }],
  c: "E",
  e: { "A": "escaped html" },      // per-choice explanations
  tags: ["retrievalTag or empty"],  // retrievalTag promoted to tags[0], or []
  retrievalTag: "string",           // top-level; '' if not in input
  reviewPearl: "string",            // top-level; '' if not in input
  educationalObjective: "string",
  correctBlurb: "HTML string",      // pre-escaped HTML from explanationSections
  metadata: {
    sourceType: "nbme-gemini-json",
    retrievalTag: "string",         // mirrored from top-level
    reviewPearl: "string",          // mirrored from top-level
    figureRefs: [...],
    tables: [...],
    sharedGroup: { ... } | null,
    figureAttachments: {},          // { figureId: "data:image/png;base64,..." }
    extractionWarnings: [],
    schemaVersion: "nbme-gemini-json-v1"
  }
}
```

### Key functions (index.html, approximate line numbers as of 2026-05-13)
| Function | Line | Role |
|----------|------|------|
| `window._ngjSanitizeUiArtifactsText` | ~20870 | Phase A+B text sanitizer |
| `window._ngjSanitizeQuestion` | ~20930 | Applies sanitizer to all question fields |
| `window._isNbmeOcrJunkLine` | ~20905 | Junk-line heuristic (Phase B4) |
| `openNbmeGeminiJsonImportModal` | ~20579 | Opens modal |
| `validateNbmeGeminiJsonImport` | ~20685 | Full validation → counts, errors, warnings |
| `_ngjBuildCorrectBlurb` | ~20909 | Builds `correctBlurb` HTML from explanationSections |
| `_ngjBuildPerChoiceExplanations` | ~20923 | Parses "Incorrect Answers" → per-letter `q.e` |
| `normalizeNbmeGeminiJsonImport` | ~20952 | Maps JSON schema → internal quiz schema |
| `parseNbmeGeminiJson` | ~21006 | Parse + validate + normalize orchestrator |
| `renderNbmeGeminiJsonPreview` | ~21136 | Full-stem question preview table in modal |
| `renderNbmeGeminiJsonFigureAttachSection` | ~21284 | Figure upload UI |
| `createTestFromNbmeGeminiJsonImport` | ~21363 | DB save + figureAttachment copy |
| `saveValidNbmeGeminiJsonQuestionsOnly` | (in return object) | Partial save — stub or incomplete, verify |

---

## 5. Sanitizer Pipeline

Two sanitization phases run as the **first step** of `normalizeNbmeGeminiJsonImport`, before any field is extracted. All removals are logged to `q.metadata.extractionWarnings`.

### Phase A — UI footer clusters
Removes NBME navigation-bar text that leaks into extracted text via OCR:
- Multi-term clusters: `Previous Next Score Report Lab Values Calculator Help Pause` and any subset of ≥2 adjacent terms
- Single UI term alone on a line
- `Lab Values` / `Score Report` as terminal suffix after sentence punctuation

### Phase B — OCR separator / header artifacts
Removes OCR noise from explanation body text:
- Inline separator runs: 3+ space-separated groups of `-–—·•|\/\` chars (e.g., `- - - -- -`)
- `.... Mark` bookmarks (2+ dots followed by standalone `Mark`)
- Residual period-preceded `Mark` after run removal (e.g., `. Mark text`)
- Junk lines: `Please Walt`, `https://t.me/` URLs, lines that are ≥70% separator/punctuation chars after stripping spaces

### Validated results
| File | Fields cleaned | False positives |
|---|---|---|
| Psych_Shelf_5 (Phase A) | 50 | 0 |
| Psych_Shelf_3 (Phase B) | 49 | 0 |

---

## 6. Explanation Rendering

### Architecture
Both `buildExplanationHTML` copies (local in Quiz IIFE ~line 5640; global `window.buildExplanationHTML` ~line 5820) render in this order:
1. Educational Objective — blue-bordered box, `textContent`
2. Correct Blurb (`q.correctBlurb`) — `innerHTML`; pre-escaped HTML with `<div class="ngj-exp-section">` wrappers per section
3. Legacy explanation (`q.explanation`) — for PDF OCR imports only
4. Per-choice explanations (`q.e`) — one block per letter

### Spacing
`.ngj-exp-section` CSS class controls inter-section spacing (`margin-bottom: 10px`). Paragraphs within a section have minimal margin (`margin: 0 0 1px`). This creates visible grouping between sections without collapsing them into one block.

### Status
VAL-001 ✅ validated: Educational Objective, explanation sections, and per-choice rationales all render correctly.

---

## 7. Figure Rendering

### Architecture
`window._ngjFigureToHTML(figureId, q)` (line ~5183) — priority order:
1. `q.metadata.figureAttachments[figureId]` exists → `<img src="dataUrl">`
2. `figureRef.visibleText` non-empty → `<table class="lab-values-table">`
3. Else → placeholder div

`window._replaceFigureMarkersInStemHtml(html, q)` (line ~5221) — post-processes stem HTML after `buildStemHTML`, replaces all `[FIGURE: figureId]` patterns.

### Status
VAL-002 pending. Q25/Q34/Q48 of Psych_Shelf_8 have `figureRefs` with `visibleText` — these should auto-render as lab tables without any image upload.

---

## 8. Shared Groups

Questions with a shared patient vignette or shared answer choice list carry a `sharedGroup` object in `metadata.sharedGroup`.

- `sharedGroup.sharedStem` — shared vignette text; rendered by `window.buildSharedGroupHTML(q)` above the per-question stem in quiz view
- `sharedGroup.sharedChoices` — if non-empty (≥2 items), overrides `q.o` at render time
- `shouldUseStemCropForQuestion(q)` returns `false` for any question with a sharedGroup — ensures the shared group HTML is shown instead of a stem crop image

Psych_Shelf_3 Q33–Q36 and Psych_Shelf_4 contain shared-stem groups. Rendering validation (VAL-004) is pending.

---

## 9. Validated Fixture Set

All in `test-data/`, committed to the `electron-runtime-phase-1` branch.

| File | Qs | Shared groups | Tables | FigureRefs |
|------|-----|---------------|--------|------------|
| `Psych_Shelf_3_app_ready.json` | 50 | 4 (Q33–Q36) | 1 (Q10) | 0 |
| `Psych_Shelf_4_app_ready.json` | 50 | 4 | 0 | 0 |
| `Psych_Shelf_5_app_ready.json` | 50 | 0 | 2 | 0 |
| `Psych_Shelf_6_app_ready.json` | 50 | 0 | 1 | 0 |
| `Psych_Shelf_7_repaired_app_ready.json` | 50 | 0 | 1 | 0 |
| `Psych_Shelf_8_full_app_ready.json` | 50 | 0 | 0 | 3 (Q25/Q34/Q48) |

---

## 10. What Changed Since 2026-05-12

| Change | Status |
|--------|--------|
| BUG-001 fixed: `_isLabPara()` false-positive on `%` in clinical prose | ✅ |
| BUG-002 fixed: explanation panel empty for JSON questions | ✅ |
| BUG-003 fixed: import preview truncated at 240 chars | ✅ |
| BUG-004 identified: stale packaged app silently hiding fixes | ✅ documented |
| VAL-001 confirmed: explanation rendering works end-to-end | ✅ |
| Explanation spacing: `ngj-exp-section` CSS; semantic section wrappers in `_ngjBuildCorrectBlurb` | ✅ |
| Phase A sanitizer: UI footer cluster removal | ✅ validated on Psych_Shelf_5 |
| Phase B sanitizer: OCR separator/header artifact removal | ✅ validated on Psych_Shelf_3 |
| Psych_Shelf_3 fixture added to `test-data/` | ✅ committed `6fe7798` |
| Psych_Shelf_4–7 fixtures added | ✅ committed `3bd1621` |
| `test-data:/` path normalized to `test-data/` in all docs | ✅ |
| `.claude/` added to `.gitignore` | ✅ |

---

## 10b. What Changed 2026-05-13 (Phase 1: retrieval tag + review pearl)

| Change | Status |
|--------|--------|
| `getRetrievalTag(q)` / `getReviewPearl(q)` getter helpers added to `Results` IIFE; exposed globally | ✅ |
| NBME JSON normalizer: `reviewPearl` passthrough added (top-level + `metadata`) | ✅ |
| Score summary table: columns changed from `Question tag \| Time` to `Retrieval Tag \| Review Pearl` | ✅ |
| Review detail panel: amber `#rev-pearl-block` added below explanation; hidden when fields empty | ✅ |
| PDF report: `Tag:` + `Pearl:` lines added per question; `Avg / Q` stat removed from header | ✅ |
| `sourceFormat: "rtf"` added to `VALID_SOURCE_FORMATS` in NBME JSON validator | ✅ |
| PDF variable rename: `rpPdf` → `rtPdf` (retrieval tag variable) | ✅ |
| Validated in Electron dev mode: import, quiz, summary, review detail, PDF all correct | ✅ |
| Backward compatibility: existing tests without pearls unaffected | ✅ |

---

## 11. Immediate Next Priorities

**P1 — VAL-002: Figure rendering.** Import `test-data/Psych_Shelf_8_full_app_ready.json`, navigate to Q25/Q34/Q48, confirm lab-values table renders inline. Then test image upload workflow for one figureId.

**P2 — VAL-003: Save valid questions only.** Read `saveValidNbmeGeminiJsonQuestionsOnly` function body. If stubbed, implement it (filter `normalizedItems` to `status === 'ok'` entries, reuse `createTestFromNbmeGeminiJsonImport` save logic).

**P3 — Next NBME folder extraction.** Psych Shelf is done. Run the Gemini extraction prompt on Medicine Shelf (or whichever folder is next). Produce `*_app_ready.json`, import and validate, add to `test-data/`, commit.

**P4 — VAL-004: Shared group rendering.** Import Psych_Shelf_3 or Psych_Shelf_4, navigate to a shared-stem group, confirm `buildSharedGroupHTML` renders the shared vignette above the per-question stem in quiz mode.

**P5 (post-exam) — Phase 2: Gemini pearl generation via Electron IPC.** Add `nbme:ai:generate-pearls` IPC handler to `electron/main.js`. Expose via `preload.js`. Gate the "Generate Missing Tags & Pearls" button on `window.nbmeDesktop?.ai?.generatePearls`. No Netlify involvement.
