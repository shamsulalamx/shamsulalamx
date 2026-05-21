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
| `MiscDocStore` | IndexedDB (`nbme_misc_docs_v1`): Miscellaneous Documents file blobs + metadata |
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

All in `test-data/`, committed to `main` (merged from `electron-runtime-phase-1` on 2026-05-13, commit `f282bb1`).

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

## 10c. What Changed 2026-05-13 (renderer/report bug fixes)

| Change | Status |
|--------|--------|
| BUG-005 fixed: `_isLabPara()` question-mark guard — short stems with inline lab values no longer truncated (Q13/Q23/Q35 UWorld Notes) | ✅ |
| BUG-006 fixed: `#q-pearl-block` added to `#exp-panel`; retrieval tag + pearl visible immediately after answering in tutor mode | ✅ |
| BUG-007 fixed: `explanationParts(q)` reads `educationalObjective`, `correctBlurb`, `q.e` in addition to legacy `q.explanation`; PDF gate broadened to `exp.correctLine || exp.paras.length > 0` | ✅ |
| All fixes validated in electron:dev | ✅ |
| Packaged app rebuilt: `npm run electron:build:mac` | ✅ |

---

## 10d. What Changed 2026-05-13 (landing page — new study folders)

| Change | Status |
|--------|--------|
| **Emma Holiday** added as top-level source folder (`src-emma-holiday`, order 8, `sourceType: 'nbme'`, `workflows: ['pdf-test-import']`) | ✅ |
| **Fast Facts** added as top-level source folder (`src-fast-facts`, order 9, same schema as Emma Holiday) | ✅ |
| Both folders reuse existing NBME JSON import workflow — no new parsing logic | ✅ |
| `ensureSourceFolders()` migration: both folders appended automatically to existing installs on next load | ✅ |
| **Miscellaneous Documents** card added to landing grid (purple left-border, document icon) | ✅ |
| `MiscDocStore` IndexedDB module added (`nbme_misc_docs_v1`), isolated from `FigureStore` and `localStorage` | ✅ |
| Misc docs panel: upload, list (filename/size/date), open (PDF/image → new tab; DOCX/TXT/MD → download), delete | ✅ |
| No quiz engine, report engine, review engine, or retrievalTag/reviewPearl logic touched | ✅ |
| Validated in `electron:dev` (smoke test passed) | ✅ |
| Packaged app rebuilt: `npm run electron:build:mac` | ✅ |

---

## 10e. What Changed 2026-05-13 (Gemini key Drive sync + export safety)

| Change | Status |
|--------|--------|
| **Gemini key now syncs through Drive** — stored in `db.settings.geminiApiKey` (canonical); mirrored to `localStorage('nbme_gemini_key_v1')` for fast access | ✅ |
| `isUnsafeStorageValue()` — `geminiApiKey` exclusion removed; key now saved in `nbme_app_v1` and Drive manifest | ✅ |
| `driveDbSnapshot()` — full `settings` block included; `geminiApiKey` no longer stripped | ✅ |
| `restoreGoogleDriveNow()` — after settings restore, syncs key to localStorage mirror; calls `checkGeminiApiKeyStatus()` to update top bar | ✅ |
| `setLocalGeminiKey()` — writes DB + localStorage, calls `DB.save()` and `scheduleGoogleDriveSave()` | ✅ |
| `getLocalGeminiKey()` — reads `db.settings.geminiApiKey` first, falls back to localStorage | ✅ |
| `clearLegacyGeminiKey()` — no longer deletes canonical DB key; removes only old `localStorage('gemini_api_key')` | ✅ |
| Startup one-time migration — if key in localStorage but absent from DB, promoted to `db.settings.geminiApiKey` on load | ✅ |
| **Export safety** — `safeExportJson(payload, indent)` added; strips `_EXPORT_SENSITIVE_KEYS` at any depth | ✅ |
| All 4 JSON export call sites updated to use `safeExportJson()` | ✅ |
| Audit confirmed: no current export path touches `db.settings` directly | ✅ |
| Syntax check: 9 script blocks, 0 errors | ✅ |
| Node.js smoke tests: 3 tests (root strip, nested strip, clean payload) — all pass | ✅ |

---

## 10f. What Changed 2026-05-13 (Drive autosave hardening + GitHub Pages deployment)

| Change | Status |
|--------|--------|
| `setLocalGeminiKey()` — removed redundant `scheduleGoogleDriveSave()` call; `DB.save()` is the sole scheduler | ✅ |
| `restoreGoogleDriveNow()` — writes `sessionStorage('nbme_post_restore_v1')` before `location.reload()` | ✅ |
| `DOMContentLoaded` — reads/clears post-restore flag; `migrateGeminiKeyToDb` skips its `DB.save()` when flag present | ✅ |
| `.nojekyll` added at repo root (commit `37d6d4c`) | ✅ |
| `electron-runtime-phase-1` merged into `main` — all session work now on `main` (commit `f282bb1`) | ✅ |
| GitHub Pages live at https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/ | ✅ |
| Gemini key entry, persistence, Drive sync, and incognito restore all confirmed working | ✅ |
| Drive OAuth `origin_mismatch` on school browser — `https://shamsulalamx.github.io` added to `274374578651-` Web credential | ⏳ pending cache propagation / school browser retest |
| Packaged Electron app rebuilt and verified (`dist/` index.html matches source) | ✅ |
| Syntax check: 9 script blocks, 0 errors | ✅ |

---

## 11. Current Branch State (as of end of 2026-05-13)

| Branch | HEAD | Notes |
|--------|------|-------|
| `main` | `f282bb1` | GitHub Pages source; contains all app work |
| `electron-runtime-phase-1` | `4101bfc` | Feature branch; all commits merged into main |
| `origin/main` | `f282bb1` | In sync with local main |

**Key commits (most recent first):**

| Hash | Description |
|------|-------------|
| `f282bb1` | Merge electron-runtime-phase-1 into main for GitHub Pages |
| `37d6d4c` | Add .nojekyll for GitHub Pages static hosting |
| `4101bfc` | Harden Drive autosave: remove redundant schedule, post-restore guard |
| `3f29d7b` | Cross-device hardening: MiscDocs Drive sync, blob URL open, origin config |
| `4bf15eb` | Prevent Gemini key leakage in downloadable exports |
| `335d665` | Add safeExportJson() to guard all downloadable file exports |
| `f0cdc16` | Sync Gemini API key through Google Drive |
| `68bc136` | Remove Netlify dependency: implement no-Netlify Gemini architecture |

---

## 12. Immediate Next Priorities (next session)

### Must-do before studying — cross-device restore validation

1. **Full Drive backup from Mac** — Settings → Backup Now → wait for green completion status
2. **Open GitHub Pages in incognito** → Connect Drive → Restore Drive → confirm all data present
3. **Confirm Gemini key restored** — Settings → Gemini shows "Key saved"; test a hint
4. **Confirm Misc docs restored** — Miscellaneous Documents panel shows uploaded files
5. **School Windows retest** — open GitHub Pages in Chrome/Edge; if Drive OAuth still fails, verify `274374578651-` credential type is "Web application" (not Desktop) in Google Cloud Console

### After restore is stable

6. **Add close-tab warning / dirty-state indicator** (optional) — only after restore works end-to-end
7. **Consider Windows Electron build** — only if browser mode is insufficient for school use

### Content work

- **P0** — Backfill retrievalTag + reviewPearl: `node backfill-pearls.js` for Psych Shelf 3–8
- **P1** — VAL-002: Figure rendering (Psych_Shelf_8 Q25/Q34/Q48)
- **P2** — VAL-003: Save-valid-only button
- **P3** — Next NBME shelf extraction (Medicine, Surgery, etc.)
- **P4** — VAL-004: Shared-group rendering (Psych_Shelf_3 Q33–Q36)
- **P5 (post-exam)** — Phase 2 pearl generation via Electron IPC
