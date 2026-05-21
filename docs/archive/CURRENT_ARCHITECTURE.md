# NBME Self-Assessment Suite — Current Architecture

**Last updated:** 2026-05-18  
**Supersedes:** `ARCHITECTURE.md` (which was last updated 2026-05-11 and remains accurate for Electron IPC/Gemini internals, but does not reflect the 2026-05-18 changes)

> Superseded for current `shamsulalamx` state on 2026-05-21. Use `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `BATCH_IMPORT_ARCHITECTURE.md`, `SHARED_INGESTION_ARCHITECTURE.md`, `VALIDATED_PIPELINES.md`, and `PROJECT_STATUS_2026-05-21.md` for current workflow and validation claims. This file remains a historical description of the older inline-app architecture and should not override the current Batch Import, shared-ingestion, status UI, or import UI milestone docs.

---

## 1. Platform Overview

The app is a single-page application in plain HTML, CSS, and JavaScript inside one file:

```
/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html
```

All application code is inline. No external local CSS or JS files. No build system. No transpiler. ~21,700+ lines as of 2026-05-18.

CDN dependencies only (loaded at runtime):
- PDF.js 3.11.174
- Tesseract.js 5
- jsPDF 2.5.1
- html-docx-js
- Google GSI client (OAuth)

The app runs in three modes: Electron dev, packaged Electron, and GitHub Pages browser. See `DEPLOYMENT_AND_RUNTIME_MODES.md`.

---

## 2. Inline Module Layout

The file is organized as a sequence of self-contained IIFEs and global helpers:

| Module/Block | Role |
|---|---|
| `DB` IIFE | localStorage metadata: tests, folders, subfolders, marks, flags, notes, history, settings |
| `FigureStore` | IndexedDB (`FigureStore` db): stem/exhibit images from OCR pipeline and Drive restore |
| `MiscDocStore` | IndexedDB (`nbme_misc_docs_v1` db): Miscellaneous Documents file blobs + metadata |
| Stem rendering helpers | `window.buildStemHTML`, `window.buildQuestionStemHTML`, `window.buildSharedGroupHTML`, `window._ngjFigureToHTML`, `window._replaceFigureMarkersInStemHtml` |
| NBME JSON sanitizers | `window._ngjSanitizeUiArtifactsText`, `window._ngjSanitizeQuestion`, `window._isNbmeOcrJunkLine` |
| Export safety | `window.safeExportJson`, `_EXPORT_SENSITIVE_KEYS` |
| Gemini key helpers | `getLocalGeminiKey()`, `setLocalGeminiKey()`, `callGeminiDirect()` |
| Retrieval tag/pearl getters | `window.getRetrievalTag(q)`, `window.getReviewPearl(q)` |
| `Quiz` IIFE | Test-taking engine: state, navigation, timers, answer selection, explanation rendering, focus mode |
| `Results` IIFE | Score report, review mode, PDF report generation |
| `App` IIFE | Home screen, all import pipelines, modals, search, Drive sync, sidebar navigation |
| Flashcard system | Pearl flashcard generation, deduplication, Drive sync (inside `App`) |

---

## 3. Electron Shell Architecture

```
┌──────────────────────────────────────────────────────────┐
│ Electron Main Process  (electron/main.js)                │
│                                                          │
│  Embedded HTTP server: 127.0.0.1:8888 (fallback 8080)   │
│  Serves index.html and static assets                     │
│                                                          │
│  IPC handlers:                                           │
│    nbme:ai:get-status          → API key check           │
│    nbme:ai:refine-uworld-draft → UWorld Gemini           │
│    nbme:ai:refine-divine-draft → Divine Gemini           │
│                                                          │
│  Owns GEMINI_API_KEY (process.env only — never leaves)   │
└────────────────────────────┬─────────────────────────────┘
                             │ contextBridge
┌────────────────────────────▼─────────────────────────────┐
│ Preload  (electron/preload.js)                           │
│                                                          │
│  window.nbmeDesktop = Object.freeze({                    │
│    isElectron: true,                                     │
│    ai: { getStatus, refineUWorldDraft, refineDivineDraft}│
│  })                                                      │
│  contextIsolation: true | sandbox: true | webSecurity: true│
└────────────────────────────┬─────────────────────────────┘
                             │ HTTP (localhost)
┌────────────────────────────▼─────────────────────────────┐
│ Renderer  (index.html)                                   │
│                                                          │
│  All pipeline logic, UI, quiz engine, parsers, storage   │
│  Detects Electron: window.nbmeDesktop?.isElectron        │
│  AI calls: window.nbmeDesktop.ai.* (UWorld/Divine only)  │
│  Hints/tagging: callGeminiDirect() — direct fetch        │
│  No direct Node access, no API key, no raw IPC           │
└──────────────────────────────────────────────────────────┘
```

In browser (GitHub Pages) mode: `window.nbmeDesktop` is undefined. UWorld/Divine Gemini refinement is unavailable. All other features work.

---

## 4. Gemini Architecture (Current — as of 2026-05-18)

Two distinct Gemini call paths exist:

### Path 1: Hints and question tagging (browser + Electron)
- Function: `callGeminiDirect(contents, generationConfig)` in the renderer
- Transport: direct `fetch` from renderer to `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent`
- Auth: `x-goog-api-key: getLocalGeminiKey()` header
- Timeout: 30s via `AbortController`
- Works in: browser (GitHub Pages) AND Electron
- Key source: `db.settings.geminiApiKey` (canonical) + `localStorage('nbme_gemini_key_v1')` (fast-access mirror)

### Path 2: UWorld and Divine draft refinement (Electron only)
- Transport: Electron IPC → `window.nbmeDesktop.ai.refineUWorldDraft / refineDivineDraft`
- Main process sanitizes input, builds prompt, calls Gemini, validates output
- Key source: payload's `apiKey` field (renderer injects via `getLocalGeminiKey()`), fallback `process.env.GEMINI_API_KEY`
- Works in: Electron only (method undefined in browser)
- Anti-copy: 8-word overlap check against sourceContext
- Voice-marker rejection: podcast/coaching phrases rejected from stems
- Provenance: assembled server-side from sanitized input — never from Gemini output

**Netlify Functions:** Dead code. Remain in `netlify/` as rollback reference. Not called anywhere.

### Key management
- Stored: `db.settings.geminiApiKey` (canonical, persists in localStorage `nbme_app_v1`)
- Mirrored: `localStorage('nbme_gemini_key_v1')` (fast access)
- Drive sync: included in Drive manifest `settings` block — restoring Drive on new device auto-populates key
- Export safety: `safeExportJson()` strips `geminiApiKey` at any depth from all downloadable files
- Never: committed to repo, in exported JSON, in debug exports, in `process.env` reads from renderer

---

## 5. Local Persistence Architecture

```
localStorage (nbme_app_v1)
  Tests, folders, subfolders, marks, flags, notes, history
  Settings: geminiApiKey, hint usage counter, preferences
  NO large images (DB.save() guards against large payloads)

IndexedDB — FigureStore
  Cropped stem images, figures, exhibits from PDF OCR
  Restored Drive images (saved by Drive ID in q.images)

IndexedDB — MiscDocStore (nbme_misc_docs_v1)
  Miscellaneous Documents: { id, filename, mimeType, size, createdAt, dataUrl }
  Organized by subfolder (subfolders added 2026-05-18)
  Isolated from FigureStore and localStorage

Google Drive (durable cross-device backup)
  App folder: "NBME Self-Assessment Suite"
  Main manifest: nbme_manifest.json
    Full DB snapshot: tests, folders, history, settings (including geminiApiKey)
  Misc docs backup: NBME_MiscDocs_backup.json (separate file)
  Pearl flashcards: synced through Drive
  Restore: full data + images + Gemini key → local app
```

**Save invariants:**
- `DB.save()` is the sole Drive sync scheduler. Never call `scheduleGoogleDriveSave()` after `DB.save()` — double-scheduling extends the debounce delay unnecessarily.
- Post-restore guard: `restoreGoogleDriveNow()` writes `sessionStorage('nbme_post_restore_v1')` before `location.reload()`. `DOMContentLoaded` reads and clears it; `migrateGeminiKeyToDb` skips its `DB.save()` when the flag is set. This prevents a startup write from racing against a fresh restore.

---

## 6. Quiz Engine Architecture

Inside the `Quiz` IIFE. Key subsystems:

### State management
- `initState()` creates a fresh state object for each test. Module-level variables (`_totTimerRef`) are NOT inside the state object.
- State tracks: current question index, answers, time per question, marks, flags, hints used, tutor mode.

### Timer system
- **Per-question timer:** `state.qTimerRef` (interval inside state, cleared on question navigation). Displays in `#q-timer` / `.timer-val`. Warning CSS class added at ≤91 seconds elapsed (1:31 threshold — fires the visual warning).
- **Total timer:** `_totTimerRef` — **module-level, outside state object**. This is critical: if placed inside `initState()`, the old interval reference is lost when state is replaced, orphaning the previous interval. The orphaned interval continues writing to `state.totSecs` via the module-level `state` reference, causing elapsed time from old tests to leak into new tests.
  - Fires every 1000ms (not 500ms — prevents layout reflow from double-fires)
  - Displays in `#block-timer` / `.block-timer-display`
  - Bottom bar uses 3-column flex: `left: flex:1 (score/controls)`, `center: flex:1 (timer)`, `right: flex:1 (nav buttons)`
  - `font-variant-numeric: tabular-nums` on timer display prevents layout reflow when digit-count changes (e.g., `9:59` → `10:00`)

### Focus mode
- `toggleFocusMode()` toggles `body.quiz-fullscreen-mode`
- `#screen-quiz` has `position:fixed; z-index:9999` in focus mode (creates stacking context over viewport)
- All app chrome (sidebar, header, nav bars) hidden via CSS
- `.modal-overlay` z-index elevated to `10000` in focus mode — prevents modal dialogs from rendering behind the fullscreen screen. This rule is **essential** — without it, the Finish Exam modal is invisible.

### Explanation rendering
Both `buildExplanationHTML` copies (local in Quiz IIFE ~line 5640; global `window.buildExplanationHTML` ~line 5820) render in order:
1. `q.educationalObjective` → blue-bordered box, `textContent` (XSS-safe)
2. `q.correctBlurb` → `innerHTML` (pre-escaped HTML)
3. `q.explanation` → legacy plain text (PDF OCR imports)
4. `q.e` → per-choice explanations, one block per letter

---

## 7. Flashcard System Architecture

Auto-generates clinical pearl flashcards after each completed test.

**Trigger:** End of test / score report display  
**Source:** For each incorrectly answered question: `q.reviewPearl || q.explanation`  
**Deduplication:** Content hash (`btoa` or similar) — same pearl from different tests is stored once  
**Organization:** Source folder → test name hierarchy  
**Persistence:** Synced to Google Drive as part of Drive backup  
**Access:** Sidebar navigation → "Notes" section  

Key commits: `de50089` (initial), `d0e04a4` (fix extraction), `92d6d2b` (fix trigger)

---

## 8. Incorrects Test Generation Architecture

Allows users to create a focused practice test from their wrong answers after completing a test.

**Trigger:** Score report / review mode — "Generate Incorrects Test" button  
**Flow:**
1. Collect all incorrectly answered question objects from the current test
2. Optionally filter by review section (subsection incorrects)
3. Create a new test object with these questions
4. Route to "Incorrects" dedicated folder
5. User selects save destination and confirms test name
6. Test saved to DB — appears in library immediately

Key commits: `4e26061` (initial), `b769fc5` (subsection), `dfc80ee` (routing), `8685f5c` (destination), `be965b2` (naming fix)

---

## 9. Pipeline Separation

Each source pipeline is isolated — flat functional code, no shared base classes.

```
NBME PDF      → OCR/parser → stem crops → quiz objects
NBME JSON     → validateNbmeGeminiJsonImport → normalizeNbmeGeminiJsonImport → quiz objects
UWorld DOCX   → blocks → concepts → clusters → (Gemini IPC) → quiz objects
OME PDF       → PDF.js text-layer → concepts → clusters → quiz objects
Anki .txt     → normalized cards → concepts → clusters → quiz objects
Mehlman       → structured text → concepts → clusters → quiz objects
Divine        → transcript → clean → segment → cluster → (Gemini IPC) → quiz objects
```

All pipelines share:
- Save gate: approved → preview → explicit target → name → confirm
- Provenance namespaced per pipeline
- No shared parser/OCR code between pipelines
- `safeExportJson()` for all downloadable outputs

---

## 10. NBME Gemini JSON Pipeline (nbme-gemini-json)

**Status:** Stable. All bugs resolved. Psych Shelf 3–8 (300 questions) validated.

Key functions (approximate line numbers as of 2026-05-18):

| Function | Role |
|---|---|
| `openNbmeGeminiJsonImportModal` | Opens `#modal-nbme-gemini-json-import` |
| `validateNbmeGeminiJsonImport` | Full schema validation → counts/errors/warnings |
| `_ngjBuildCorrectBlurb` | Builds `correctBlurb` HTML from `explanationSections` |
| `_ngjBuildPerChoiceExplanations` | Parses "Incorrect Answers" → per-letter `q.e` |
| `normalizeNbmeGeminiJsonImport` | Maps JSON schema → internal quiz schema |
| `parseNbmeGeminiJson` | Parse + validate + normalize orchestrator |
| `renderNbmeGeminiJsonPreview` | Full-stem question preview table in modal |
| `renderNbmeGeminiJsonFigureAttachSection` | Figure upload UI |
| `createTestFromNbmeGeminiJsonImport` | DB save + figure attachment copy |

**`_isLabPara()` guards (critical — do not remove):**
```javascript
function _isLabPara(para) {
  if (para.length > 400) return false;  // BUG-001: clinical vignettes are long
  if (/\?/.test(para)) return false;    // BUG-005: question stems contain '?'
  _LAB_SCAN_RE.lastIndex = 0;
  let m;
  while ((m = _LAB_SCAN_RE.exec(para)) !== null) {
    const nameWords = m[1].trim().split(/\s+/);
    if (nameWords.length <= 4) return true;
  }
  return false;
}
```
Both guards prevent clinical vignettes from being misclassified as lab-value table blocks and silently truncated.

---

## 11. Key Architectural Invariants

1. **`index.html` is the authoritative source.** All edits go here.
2. **`_totTimerRef` is module-level in the Quiz IIFE.** Never move inside `initState()`.
3. **`.modal-overlay` z-index ≥ 10000 in `quiz-fullscreen-mode`.** Never reduce.
4. **`safeExportJson()` on all downloads.** Never use raw `JSON.stringify` for user-downloadable content.
5. **Gemini key never in renderer's `process.env`.** Only `electron/main.js` may read `process.env.GEMINI_API_KEY`.
6. **`DB.save()` is the sole Drive sync scheduler.** No redundant `scheduleGoogleDriveSave()` calls.
7. **`callGeminiDirect()` for hints/tagging.** Works browser + Electron. Do not route through Netlify.
8. **All provenance assembled server-side.** Never trust Gemini output for provenance fields.
9. **OCR fixes must be conservative.** Broad OCR normalization rules caused instability in the past.
10. **Each pipeline saves only approved drafts.** Unapproved AI output is never auto-saved.
