# CLAUDE CODE HANDOFF — NBME Self-Assessment Suite

**Last updated:** 2026-05-18  
**Purpose:** Primary onboarding document for any new Claude Code session. Read this first. Then read `CURRENT_ARCHITECTURE.md`, `DEBUGGING_PITFALLS.md`, and `PROJECT_STATUS_2026-05-18.md`.

---

## 1. Source of Truth

There is exactly one authoritative source file:

```
/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html
```

All application code — HTML, CSS, and JavaScript — is inline in this single file (~21,700+ lines). No external local JS or CSS. No build system. No transpiler.

**Every edit must land in this file.** Verify with:
```bash
cd "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite"
git diff index.html | head -60
```

---

## 2. How to Run the App

### Development — ALWAYS use this
```bash
cd "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite"
npm run electron:dev
```
Electron starts and serves `index.html` from the project root via an embedded HTTP server at `127.0.0.1:8888` (fallback `8080`). Edits to `index.html` are reflected immediately on reload.

### GitHub Pages (browser)
```
https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/
```
Served from the `main` branch. Electron IPC features (UWorld/Divine Gemini refinement) are not available here, but all other features work — including Gemini hints/tagging (via `callGeminiDirect`), Drive backup/restore, and all quiz functionality.

### Packaged Electron App — DO NOT USE FOR DEVELOPMENT
```
dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html
```
This frozen bundle is NOT updated when you edit the project root. Edits are silently invisible. Multiple debugging sessions were lost this way. If you must sync the bundle without a full rebuild:
```bash
cp "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html" \
   "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html"
```
For full rebuild: `npm run electron:build:mac`

---

## 3. Triple Verification Protocol

Before reporting ANY fix as successful, you must verify ALL THREE:

1. **Was the edit applied to the right file?**
   ```bash
   grep -n "your_change_marker" "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html"
   ```

2. **Is the running app using this file?**
   - Confirm `npm run electron:dev` is running (not the packaged `.app`)
   - Check Electron's loaded URL: it must be `http://127.0.0.1:8888/` or `http://localhost:8888/`

3. **Does the fix work at runtime?**
   - Use the browser devtools inside Electron (`Cmd+Option+I`)
   - Use `getComputedStyle(element)` for CSS, not just grep
   - Use `element.style` for inline overrides
   - DOM inspection > grep every time

---

## 4. What This App Does

A personal study tool for NBME medical board exam preparation. It:
- Imports questions from multiple sources (NBME PDFs, pre-structured JSON, UWorld DOCX, OME PDFs, Anki exports, Divine podcast transcripts, Mehlman notes)
- Generates NBME-style question drafts using Gemini AI (all AI-assisted, all require human review)
- Runs timed or untimed self-assessments
- Generates score reports with explanations, retrieval tags, and review pearls
- Creates flashcards from incorrectly answered questions
- Generates targeted practice tests from incorrect answers
- Backs up and restores everything via Google Drive

---

## 5. Current Feature Inventory

### Quiz Engine
- Timed quiz mode with per-question timer and total test timer
- Focus mode (fullscreen) — hides all app chrome; `body.quiz-fullscreen-mode`
- Question navigation panel with active-question highlighting
- Tutor mode (immediate feedback) and block mode (deferred feedback)
- Answer highlighting, notes, marks, flags
- Gemini-powered hints (`callGeminiDirect` — works in browser and Electron)
- Lab values panel, calculator
- Zoom / font-size control; stem and choice font-size synchronized

### Timer System
- **Per-question timer:** `#q-timer` / `.timer-val`. Shows elapsed time per question. Warning state (amber/orange) fires at 90 seconds remaining (1:31 threshold). Warning clears on next question.
- **Total timer:** `#block-timer` / `.block-timer-display`. Shows total elapsed time for the entire test. Module-level `_totTimerRef` (NOT inside state object — was a bug) fires every 1000ms. 3-column flex bottom bar ensures geometric centering. `font-variant-numeric: tabular-nums` prevents layout reflow on digit changes.
- **Known timer pitfall:** `_totTimerRef` must be module-level (not inside `initState()`). Moving it back inside `state` will cause cross-test timer leakage.

### Focus Mode
- Triggered by a button in the quiz chrome
- Adds `body.quiz-fullscreen-mode`; `#screen-quiz` becomes `position:fixed; z-index:9999`
- App chrome (sidebar, nav bars, top header) hidden while in focus mode
- All `.modal-overlay` elements get `z-index:10000` in focus mode to stay above the fullscreen screen
- **Known focus-mode pitfall:** Without the modal z-index override, modal dialogs (e.g., Finish Exam confirmation) are invisible behind the fullscreen layer. Do not reduce `.modal-overlay` z-index while `quiz-fullscreen-mode` is active.

### Score Reports and Review
- Full score summary with per-question results table
- Review mode with pearl blocks (`#rev-pearl-block` — amber box)
- Retrieval Tag and Review Pearl columns in score summary table
- PDF report generation (jsPDF) — includes `retrievalTag`, `reviewPearl`, Educational Objective, per-choice rationales

### Flashcard System (Pearl Flashcards)
- Auto-generated after each test from incorrectly answered questions
- Source content: `q.reviewPearl || q.explanation`
- Deduplicated by content hash
- Organized: source folder → test name
- Synced to Google Drive
- Accessible from sidebar nav under "Notes"
- Functions: see `de50089`, `d0e04a4`, `92d6d2b` commits

### Incorrects Test Generation
- After a test, users can generate a new practice test from incorrect answers
- Review sections are grouped; "Generate Incorrects Test" button produces a new test object
- Saves to "Incorrects" folder (dedicated destination)
- Subsection incorrects test generation also supported
- Naming and destination selection was refined in `be965b2`

### Source Pipelines (all stable)
| Pipeline | Input | Gemini refinement |
|----------|-------|-------------------|
| NBME PDF OCR | PDF screenshot/scan | Hints + tagging (browser direct call) |
| NBME Gemini JSON | Pre-structured `.json` | None (external AI step) |
| UWorld DOCX | DOCX export | Electron IPC only |
| OME PDF | Short high-quality PDF | None in v1 |
| Anki | Plain-text `.txt` | None in v1 |
| Divine Podcasts | Transcript text | Electron IPC only |
| Mehlman | Structured text notes | None in v1 |

### Study Library
- Top-level folders: NBME, UWorld, Anki, OME, Divine Podcasts, Mehlman, Images and Tables, Amboss, Emma Holiday, Fast Facts, Miscellaneous Documents
- Folder → Subfolder → Tests hierarchy
- Incorrects folder for generated incorrects tests
- Miscellaneous Documents: file storage (PDF, DOCX, TXT, RTF, MD, PNG, JPG), now with subfolders

### Gemini Integration
- **Hints and tagging:** `callGeminiDirect()` — direct `fetch` to Gemini API from renderer. Works in browser and Electron. Key stored in `db.settings.geminiApiKey` + mirrored to `localStorage('nbme_gemini_key_v1')`.
- **UWorld and Divine refinement:** Electron IPC only via `window.nbmeDesktop.ai.*` — never in browser.
- **Key syncs through Drive:** Drive manifest includes full `settings` block with `geminiApiKey`. Restoring from Drive on a new device auto-populates the key.
- **Export safety:** All downloadable JSON exports use `safeExportJson()` which strips `geminiApiKey` at any depth. The key NEVER appears in downloads.
- **Model:** `gemini-2.5-flash` (hardcoded constant — do not change without a documented reason).

### Persistence
| Storage | Contents |
|---------|----------|
| `localStorage` (`nbme_app_v1`) | Test metadata, folders, marks, flags, notes, history, settings (including Gemini key) |
| IndexedDB (`FigureStore`) | Stem/exhibit images, figures |
| IndexedDB (`MiscDocStore`, `nbme_misc_docs_v1`) | Miscellaneous Documents file blobs + metadata |
| Google Drive — main manifest | Full DB snapshot: tests, folders, history, settings, Gemini key |
| Google Drive — `NBME_MiscDocs_backup.json` | Misc doc blobs (separate file) |

### Google Drive / OAuth
- OAuth Client ID: `274374578651-5edirahp87c5hpv69donfpvcr81tmidk.apps.googleusercontent.com`
- Credential type: **Web application** (not Desktop — Desktop type does not support Authorized JavaScript Origins)
- Required origins: `https://shamsulalamx.github.io`, `http://localhost:8888`, `http://localhost:8080`
- No redirect URIs needed (GIS token flow, not redirect-based)

---

## 6. Key File Map

| File/Path | Role |
|-----------|------|
| `index.html` | **THE ENTIRE APP** — all HTML, CSS, JS |
| `electron/main.js` | Electron main: HTTP server, IPC handlers, all Gemini API calls |
| `electron/preload.js` | `contextBridge`: exposes only `window.nbmeDesktop` to renderer |
| `package.json` | `"main": "electron/main.js"`, scripts: `electron:dev`, `electron:build:mac` |
| `netlify/` | Dead code — legacy Netlify Functions (kept as rollback reference only) |
| `test-data/` | Validated NBME JSON fixture files (Psych Shelf 3–8, UWorld Notes, etc.) |
| `backfill-pearls.js` | Utility: backfills `retrievalTag`/`reviewPearl` for existing test-data files |
| `dist/` | Packaged Electron app — NOT source of truth |

**Legacy split files** (`app.js`, `db.js`, `ocr.js`, `quiz.js`, `results.js`, `style.css`, `css/`, `js/`): not the active implementation. All active code is in `index.html`.

---

## 7. Critical Do-Nots

- **Do not test against `dist/mac-arm64/...app`** unless after a full rebuild. Edits to `index.html` are invisible to the packaged app.
- **Do not move `_totTimerRef` inside `initState()`** — it must be module-level to prevent cross-test timer leakage.
- **Do not reduce `.modal-overlay` z-index below 10000** when `body.quiz-fullscreen-mode` is present — modals will be hidden behind the fullscreen screen.
- **Do not put Gemini API key in downloaded files** — use `safeExportJson()` for all downloads.
- **Do not put Gemini API key in `process.env` reads inside the renderer** — key access is only in `electron/main.js`.
- **Do not reintroduce Netlify Functions** as active call sites — they are dead code/rollback.
- **Do not implement Supabase, Firebase, or any external database.**
- **Do not refactor into React or add a build system** without a documented and agreed reason.
- **Do not perform major storage migrations** (FigureStore, IndexedDB rewrite, localStorage restructure) before the exam.
- **Do not use `prompt()` or `confirm()`** in any Electron save flow — use inline modal UI instead.
- **Do not change the Gemini model string** from `gemini-2.5-flash` without a documented reason.
- **Do not commit `dist/` as source of truth** — it's generated.

---

## 8. Safe Debugging Workflow

1. **Identify the symptom** in the running `npm run electron:dev` app. Use devtools.
2. **Grep index.html** to find relevant code sections. Note line numbers.
3. **Read the actual code** with Read tool — do not assume grep results are complete.
4. **Inspect runtime state** with devtools: `getComputedStyle(el)`, `el.style`, `el.innerText`, `el.offsetHeight`, network tab.
5. **Make the minimal edit** to `index.html`. One change at a time.
6. **Reload** the Electron app (`Cmd+R`). Do NOT restart `electron:dev` between edits (it's a dev server, reload is enough).
7. **Verify at runtime** using devtools — do not trust grep alone.
8. **Check for CSS/inline-style conflicts** — inline styles on elements override CSS rules. Always check both.
9. **Git diff before reporting success:** `git diff index.html | head -60`

---

## 9. Architecture Summary

**Three-layer system:**

```
Electron Main (electron/main.js)
  → HTTP server (127.0.0.1:8888)
  → IPC handlers: nbme:ai:get-status, nbme:ai:refine-uworld-draft, nbme:ai:refine-divine-draft
  → Gemini API calls (owns GEMINI_API_KEY from process.env)
  → Input sanitization + output validation

Preload (electron/preload.js)
  → contextBridge → window.nbmeDesktop = { isElectron, ai: { getStatus, refineUWorldDraft, refineDivineDraft } }
  → contextIsolation: true, sandbox: true, webSecurity: true

Renderer (index.html)
  → All pipeline logic, UI, quiz engine, storage, Drive sync
  → Detects Electron via: window.nbmeDesktop?.isElectron
  → Gemini hints/tagging: callGeminiDirect() — direct fetch from renderer (browser + Electron)
  → UWorld/Divine Gemini: window.nbmeDesktop.ai.* (Electron only)
```

**Two-layer AI architecture:**
- **Deterministic layer:** Parses source content, builds clusters, produces draft scaffolds, sanitizes inputs, validates outputs, manages provenance. Works without Gemini.
- **Gemini layer:** Identifies testable medical fact (Divine), generates clinical vignettes (UWorld/Divine). Never manages provenance or save targets. Always validated by deterministic layer before use.

---

## 10. What to Read Next

| Doc | When to read it |
|-----|----------------|
| `CURRENT_ARCHITECTURE.md` | Need to understand internal module layout, storage, IPC flow |
| `DEBUGGING_PITFALLS.md` | Debugging a specific symptom or hit a confusing issue |
| `DEPLOYMENT_AND_RUNTIME_MODES.md` | Questions about GitHub Pages vs Electron vs packaged app |
| `CURRENT_FEATURES.md` | Need complete feature inventory |
| `RECENT_MAJOR_CHANGES.md` | What changed on 2026-05-18 (today's session) |
| `PROJECT_STATUS_2026-05-18.md` | Full current-state snapshot |
| `BUGS_AND_NEXT_STEPS.md` | Active bug tracker and prioritized work queue |
| `ARCHITECTURE.md` | Deep-dive IPC/Gemini architecture (still accurate for Electron IPC layer) |
| `NBME_JSON_IMPORT.md` | NBME Gemini JSON importer spec |
| `DIVINE_PIPELINE.md` | Divine podcast pipeline detail |
