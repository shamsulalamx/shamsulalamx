# BUGS AND NEXT STEPS

**Last updated:** 2026-05-18 (HEAD: `81e11f5` — editable notes, persistent highlights, review later, mark reasons, performance summaries, Electron close fix, expanded search, responsive resizing)
**Purpose:** Active bug tracker and prioritized work queue. Contains all unresolved issues and pending validations. Update this file as items are resolved.

---

## UNRESOLVED BUGS

*(none currently — see Resolved section below)*

---

## RESOLVED BUGS

### [BUG-001] Quiz stem truncation — RESOLVED 2026-05-12

**Status:** ✅ FIXED. Verified in running app: Q1, Q9, Q11, Q24 all render full stems. Q25, Q34, Q48 figure/lab tables still render correctly.

**Symptom:**  
Q1, Q9, Q11, and Q24 of `Psych_Shelf_8_full_app_ready.json` showed only 1–2 lines of text in quiz mode. Stems are 608, 828, 1160, and 1319 characters respectively. No scrollbar. Missing content inaccessible.

**Root cause:**  
`_isLabPara()` in `buildStemHTML()` (`index.html` ~line 5074) used `_LAB_SCAN_RE.test(para)` to decide whether a paragraph should render as a lab-values table. The regex includes `%` as a recognized unit. Clinical sentences like "80% intelligible" (Q1) and "14% of his total body surface area" (Q24) matched — causing `buildStemHTML` to treat the entire 1319-char clinical paragraph as a lab-value block. It extracted one table row ("he sustained second-degree burns to" | "14%") and silently discarded all remaining text. DOM inspection confirmed: `stemEl.innerText.length = 39`, `scrollHeight = clientHeight = 24px` — the text was never in the DOM at all.

**Fix applied (`index.html`, `_isLabPara()`, ~line 5074):**  
Added two guards before returning `true`:
1. **Length guard:** `if (para.length > 400) return false` — real NBME lab-value blocks are always short dedicated paragraphs, never 1000+ char clinical vignettes.
2. **Name word-count guard:** after each regex match, count words in the captured name field; if > 4 words, it's a sentence fragment (e.g., "he sustained second-degree burns to"), not a lab name — skip it.

```javascript
function _isLabPara(para) {
  if (para.length > 400) return false;
  _LAB_SCAN_RE.lastIndex = 0;
  let m;
  while ((m = _LAB_SCAN_RE.exec(para)) !== null) {
    const nameWords = m[1].trim().split(/\s+/);
    if (nameWords.length <= 4) return true;
  }
  return false;
}
```

**Caveat:** Lab detection must remain conservative. Do not loosen `_LAB_SCAN_RE` or remove the guards. If real lab-value paragraphs exceed 400 chars in future test files, raise the threshold carefully and re-verify Q1/Q24 still render as prose.

**See also:** BUG-005 below — a second `_isLabPara` false-positive affecting short stems was fixed separately.

---

### [BUG-005] `_isLabPara()` false-positive on short clinical stems with inline lab values — RESOLVED 2026-05-13

**Status:** ✅ FIXED. Verified in electron:dev: Q13, Q23, Q35 of `UWorld_Notes_Psych_Questions_enhanced_app_ready.json` now render full stems.

**Symptom:**
Short clinical vignettes (< 400 chars) containing inline lab values were misclassified as lab-value table blocks. The stem was truncated to a single-row table and the rest of the text silently discarded. Examples:
- Q13 (280 chars): "…Lithium level is 2.1 mEq/L. Which medication is most likely responsible?"
- Q23 (310 chars): "…Serum sodium is 128 mEq/L. Which substance did she most likely ingest?"
- Q35 (239 chars): "…Potassium is 2.8 mEq/L and bicarbonate is 32 mEq/L. Which diagnosis is most likely?"

**Root cause:**
The BUG-001 length guard (`para.length > 400`) did not protect short stems. The word-count guard (`nameWords.length <= 4`) also failed because "Lithium level is" is only 3 words — a valid regex match. Real question stems always end with a question mark; isolated lab-value table blocks never do.

**Fix applied (`index.html`, `_isLabPara()`, ~line 5086):**
Added a question-mark guard as the second check, immediately after the length guard:
```javascript
if (/\?/.test(para)) return false;
```
Current full function:
```javascript
function _isLabPara(para) {
  if (para.length > 400) return false;
  if (/\?/.test(para)) return false;
  _LAB_SCAN_RE.lastIndex = 0;
  let m;
  while ((m = _LAB_SCAN_RE.exec(para)) !== null) {
    const nameWords = m[1].trim().split(/\s+/);
    if (nameWords.length <= 4) return true;
  }
  return false;
}
```

**Caveat:** Do not remove this guard. Real NBME lab-value table blocks are isolated paragraphs with no question marks.

---

### [BUG-006] Retrieval tag and review pearl missing from quiz explanation area — RESOLVED 2026-05-13

**Status:** ✅ FIXED. Pearl block now appears immediately below the "Answer Explanation" header in tutor mode, above the explanation body.

**Symptom:**
After Phase 1 implementation, `retrievalTag` and `reviewPearl` appeared in the score summary table and review detail panel, but not in the tutor-mode quiz view after answering. Users saw no pearl at the moment of feedback.

**Fix applied (`index.html`):**
1. Added `#q-pearl-block` div inside `#exp-panel` (line ~1201), before `#exp-body`. Same amber styling as `#rev-pearl-block` (background `#fff8e1`, left border `#f59e0b`).
2. `renderExplanation()` (line ~5717) now populates `#q-retrieval-tag` and `#q-review-pearl` from `getRetrievalTag(q)` / `getReviewPearl(q)` and shows the block only when at least one field is non-empty.

**Backward compatibility:** Pearl block hidden (`display:none`) for questions without these fields. Existing UWorld/PDF/OCR imports unaffected.

---

### [BUG-007] PDF report missing all explanations for JSON-imported questions — RESOLVED 2026-05-13

**Status:** ✅ FIXED. PDF now includes Educational Objective, all explanation sections, and per-choice rationales for NBME JSON questions.

**Symptom:**
The PDF score report rendered answer choice pills for each question but showed no explanation text for NBME JSON-imported questions. Legacy PDF-OCR and UWorld imports were unaffected.

**Root cause:**
`explanationParts(q)` (PDF code, ~line 6544) only read `q.explanation` (the legacy field). NBME JSON questions store explanations in `q.educationalObjective` (plain text), `q.correctBlurb` (pre-escaped HTML), and `q.e` (per-choice rationale object). The rendering block was also gated on `if (q.explanation)`, so JSON questions were skipped entirely.

**Fix applied (`index.html`):**
1. `explanationParts(q)` now collects paragraphs from four sources in priority order:
   - `q.educationalObjective` → prefixed "Objective: …" (plain text)
   - `q.correctBlurb` → HTML stripped via `plainTextFromHTML()`, split on double-newlines
   - `q.explanation` → legacy plain text (unchanged; UWorld/OCR imports)
   - `q.e` entries → each letter's rationale rendered as "X) text"
2. Rendering gate changed from `if (q.explanation)` to `if (exp.correctLine || exp.paras.length > 0)`.

---

## RESOLVED BUGS (for reference)

### [BUG-002] Explanation panel shows nothing for nbme-gemini-json questions — RESOLVED

**Symptom:** After answering a question from the JSON importer, the explanation panel was empty.

**Root cause:** Both `buildExplanationHTML` functions (local Quiz IIFE ~line 5644, global `window.buildExplanationHTML` ~line 5819) only checked `q.explanation`. The JSON importer never sets `q.explanation` — it sets `q.correctBlurb` (pre-escaped HTML) and `q.educationalObjective` (plain text).

**Fix applied:** Both functions now render `q.educationalObjective` (blue bordered block, `textContent`) and `q.correctBlurb` (`innerHTML`) before the legacy `q.explanation` check.

**Caveat:** Tests imported BEFORE this fix was applied will not show explanations. Must delete and reimport the test. After reimport, Q1 of Psych_Shelf_8 should show: (1) a blue "Educational Objective" box, (2) a structured explanation block from the "Correct Answer" section.

**Validation status:** Code is correct. End-to-end validation (delete → reimport → answer Q1 → check explanation panel) has NOT been done as of 2026-05-12.

---

### [BUG-003] Import preview stems truncated at 240 characters — RESOLVED

**Symptom:** In the import preview modal (before saving), long stems appeared cut off with "…".

**Root cause:** `stemPreview = String(q.stem || '').slice(0, 240)` at ~line 21094 in the preview rendering function.

**Fix applied:** Removed `.slice(0, 240)`. Full stem now shown in preview.

**Note:** This fix is ONLY for the import preview modal. It is unrelated to quiz view truncation (BUG-001).

---

### [BUG-004] Stale packaged app silently hiding all fixes — RESOLVED

**Symptom:** Code fixes were verified in `index.html` but had no effect when running the app.

**Root cause:** User was opening the packaged `.app` at `dist/mac-arm64/NBME Self-Assessment Suite.app` directly. This bundle contains its own copy of `index.html` inside the bundle at `Contents/Resources/app/index.html`. That copy was from May 11 (1,018,924 bytes) and did not include any May 12 fixes.

**Fix applied:** On 2026-05-12 19:13:
```bash
cp "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html" \
   "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html"
```
Both files are now 1,073,458 bytes.

**Prevention:** Always use `npm run electron:dev` for development and testing. Never test against the packaged `.app` unless a new build has been produced with `npm run electron:build:mac`.

---

## PENDING VALIDATION (code written but not end-to-end tested)

### [VAL-001] Explanation rendering end-to-end test — ✅ VALIDATED (2026-05-13)

Confirmed working: blue "Educational Objective" box, structured explanation sections (with correct inter-section spacing), and per-choice rationales all render correctly for Psych_Shelf_8 Q1.

---

### [VAL-002] Figure rendering end-to-end test

**What to test:**
1. Import Psych_Shelf_8 fresh (as above)
2. Navigate to Q25, Q34, Q48 (questions with `[FIGURE: ...]` markers in stems)
3. Verify: a placeholder box appears where the figure marker was, showing the figureId and location hint
4. In the import modal, before saving, test figure attachment: use the figure attachment panel, upload a test image for a figureId, save, then view the question in quiz mode
5. Verify: the uploaded image appears inline where the marker was

---

### [VAL-003] "Save valid questions only" Phase 3

**Status:** ✅ IMPLEMENTED (`e29420c`). Needs runtime smoke test.

`saveValidNbmeGeminiJsonQuestionsOnly()` is fully implemented. It filters `_nbmeGeminiJsonImport.validation.questionResults` to `isValid === true`, builds question payloads with correct metadata, calls `DB.createTest()` + `DB.updateTest()`, and reports skipped count in toast. Figure-attachment size warning (3 MB threshold) also present.

**What to smoke test:**
1. Import a JSON file with at least one invalid question (e.g., missing choices)
2. In the import modal, confirm "Save valid questions only" button appears and is clickable
3. Verify: only valid questions saved; toast shows skipped count; test appears in library correctly

---

## COMPLETED — 2026-05-13: Phase 1 retrieval tag + review pearl

### [FEAT-001] retrievalTag + reviewPearl display support — ✅ COMPLETE

**Implemented:**
- `getRetrievalTag(q)` / `getReviewPearl(q)` getter helpers (read `q.retrievalTag` or `q.metadata.retrievalTag`, same for pearl). Exposed as `window.getRetrievalTag` / `window.getReviewPearl`.
- NBME JSON importer (`normalizeNbmeGeminiJsonImport`): reads `q.reviewPearl` from input, stores at `q.reviewPearl` (top-level) and `q.metadata.reviewPearl`. `retrievalTag` was already partially supported; now mirrored correctly at both levels.
- Score summary review table: columns changed from `Question tag | Time` to `Retrieval Tag | Review Pearl`. Retrieval Tag falls back to `q.tags[0]` for questions without `retrievalTag`.
- Review detail panel: amber box (`#rev-pearl-block`) shown below explanation when either field is non-empty. Hidden by `display:none` for older questions without pearls.
- PDF report: `Tag:` + `Pearl:` lines rendered below answer choice pills for each question. `Avg / Q` timing stat removed from header stats block.
- `sourceFormat: "rtf"` added to allowed values in NBME JSON validator — no longer generates spurious warnings.
- Variable rename in PDF code: `rpPdf` → `rtPdf` (retrieval tag, not review pearl).

**Validated in Electron dev mode (2026-05-13):**
- Import of 3-question JSON with full `retrievalTag` + `reviewPearl` fields: all rendering surfaces correct.
- Backward compatibility: existing tests without these fields render normally; pearl block hidden, table cells empty.
- No crashes, no rendering regressions.

**Phase 2 (generation) — POSTPONED:**
Gemini-powered "Generate Missing Tags & Pearls" is deferred until after the exam. The planned path is Electron IPC (`ipcMain.handle('nbme:ai:generate-pearls', ...)`) — same pattern as existing `refine-uworld-draft`. No Netlify dependency. Do not implement until Phase 1 has been used in real studying and the Electron IPC path is confirmed appropriate.

---

---

## COMPLETED — 2026-05-13: No-Netlify Gemini architecture

### [FEAT-003] Remove Netlify dependency from all Gemini code paths — ✅ COMPLETE

**Implemented:**
- `localStorage` key `nbme_gemini_key_v1` — sole storage for the Gemini API key. Never written to the app DB, never synced via Drive, never committed.
- `getLocalGeminiKey()` / `setLocalGeminiKey(key)` — helpers for all renderer Gemini callers.
- `callGeminiDirect(contents, generationConfig)` — direct `fetch` to `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent` with `x-goog-api-key` header, 30s timeout, `NO_KEY` error code when key absent.
- Settings modal: replaced Netlify description with local key input (password field, Save/Clear buttons, live status).
- `requestHint()` — Netlify call replaced with `callGeminiDirect()` using verbatim hint prompt from `netlify/functions/gemini-hint.js`.
- `aiTagQuestions()` — Netlify call replaced with `callGeminiDirect()` using verbatim tagging prompt from `netlify/functions/gemini-tagging.js`.
- `refineDivineDraft` payload — `apiKey: getLocalGeminiKey()` injected.
- `refineNotesDraft` / `processNextLiveBatchItem` (UWorld) — `apiKey: getLocalGeminiKey()` injected in both call sites.
- `electron/main.js` — both `nbme:ai:refine-uworld-draft` and `nbme:ai:refine-divine-draft` handlers now use `(payload?.apiKey || '').trim() || process.env.GEMINI_API_KEY || ''`.
- `refreshNotesAiStatus()` — status message now reads from `getLocalGeminiKey()` instead of IPC `hasApiKey`.

**Key invariants:**
- The key lives in `db.settings.geminiApiKey` (canonical) and is mirrored to `localStorage('nbme_gemini_key_v1')` for fast access. `setLocalGeminiKey()` writes both and calls `DB.save()` (which schedules Drive sync automatically — no second `scheduleGoogleDriveSave()` call needed).
- Drive snapshot includes the full `settings` block including `geminiApiKey`. Restoring from Drive on a new device syncs the key to localStorage and calls `checkGeminiApiKeyStatus()` to update the top-bar indicator.
- Startup migration: if `localStorage('nbme_gemini_key_v1')` has a key but `db.settings.geminiApiKey` is absent, the key is promoted to the DB on first load (one-time, handles existing installs). Skipped on first load after a Drive restore (see FEAT-005).
- The key never appears in downloadable files — all four JSON export call sites use `safeExportJson()`, a central serializer that strips every key in `_EXPORT_SENSITIVE_KEYS` (currently `{'geminiApiKey'}`) at any depth. Audit confirmed no current export path touches `db.settings` directly; the guard is defensive for future code.
- Netlify function files remain in the repo as dead code (reference/rollback). They are not called anywhere in the renderer or Electron main process.
- All AI output fields (`retrievalTag`, `reviewPearl`, `hints`, `generatedAt`, `model`) are stored with question/test data and sync through Drive normally.

---

## COMPLETED — 2026-05-13: Export safety — safeExportJson

### [FEAT-004] Prevent Gemini key leakage in downloadable exports — ✅ COMPLETE

**Audit result:** No current export path touches `db.settings`. All exports serialize individual draft/question/test objects. PDF report, notes PDF/DOCX, and all JSON exports were confirmed clean.

**Implemented:**
- `_EXPORT_SENSITIVE_KEYS = new Set(['geminiApiKey'])` — central list of keys to strip from all downloads
- `safeExportJson(payload, indent)` — wrapper around `JSON.stringify` with a replacer that strips every key in `_EXPORT_SENSITIVE_KEYS` at any depth. Exposed as `window.safeExportJson`.
- All four JSON export `Blob` call sites updated: OME approved drafts, Anki approved variants, UWorld approved drafts, parser debug export.
- Drive manifest path (`saveManifestToDrive`) intentionally left on raw `JSON.stringify` — Drive backup is the correct sync destination for the key.

**Smoke tested (Node.js):**
1. Root-level `geminiApiKey` stripped; other fields preserved.
2. Nested `geminiApiKey` stripped; sibling settings fields preserved.
3. Clean OME payload with no sensitive keys — output byte-identical.

**Syntax check:** 9 inline script blocks — 0 errors.

---

## COMPLETED — 2026-05-13: New study folders and Miscellaneous Documents storage

### [FEAT-002] Emma Holiday, Fast Facts, Miscellaneous Documents — ✅ COMPLETE

**Implemented:**

- **Emma Holiday** (`src-emma-holiday`) and **Fast Facts** (`src-fast-facts`) added to `DEFAULT_SOURCE_FOLDERS` in the `DB` layer. Both use `sourceType: 'nbme'` and `workflows: ['pdf-test-import']`, giving them the full NBME JSON import workflow (upload JSON, save tests, run quizzes, score reports, `retrievalTag`/`reviewPearl` support). `ensureSourceFolders()` appends them to any existing install automatically on next load — no manual migration required.

- **Miscellaneous Documents** card added to the landing grid (purple left-border, 📄 icon). This is a document-only storage folder — **not a quiz source**. No question generation, parsing, quiz mode, or score reports. Existing quiz/report/review workflows are completely untouched.
  - `MiscDocStore` — new IndexedDB module (`nbme_misc_docs_v1`), isolated from `FigureStore` and `localStorage`. Stores `{ id, filename, mimeType, size, createdAt, dataUrl }` per file.
  - Supported types: PDF, DOCX, TXT, RTF, MD, PNG, JPG, JPEG
  - Open: PDFs and images open in a new tab; DOCX/TXT/RTF/MD trigger a browser download
  - Delete: per-file with confirmation

**Validated in `electron:dev` (smoke test 2026-05-13):**
- All 3 cards visible on landing page
- Emma Holiday and Fast Facts open the standard source folder page
- Miscellaneous Documents opens the doc manager panel
- File upload, open, and delete all functional
- Existing NBME/UWorld/Anki folders unaffected

---

---

## COMPLETED — 2026-05-13: Drive autosave hardening

### [FEAT-005] Drive autosave hardening: remove redundant schedule + post-restore guard — ✅ COMPLETE

**Implemented:**

**Fix 1 — Remove redundant `scheduleGoogleDriveSave()` call from `setLocalGeminiKey`:**
- `setLocalGeminiKey()` previously called `DB.save()` (which schedules Drive sync internally) and then explicitly called `scheduleGoogleDriveSave()` a second time.
- The second call was a no-op that reset the 1200ms debounce timer, extending the sync delay unnecessarily.
- Removed the explicit call. `DB.save()` remains the sole scheduler.

**Fix 2 — Post-restore startup autosave guard:**
- `restoreGoogleDriveNow()` now writes `sessionStorage('nbme_post_restore_v1', '1')` immediately before `location.reload()`.
- On the next page load, `DOMContentLoaded` reads and clears the flag.
- If the flag was present, `migrateGeminiKeyToDb()` returns early — skipping its conditional `DB.save()` call, which would otherwise trigger `scheduleGoogleDriveSave()` and potentially overwrite the just-restored Drive manifest with stale local state.
- This closes the narrow window where a startup key-migration write could race against a fresh restore.

**Commit:** `4101bfc`

---

## COMPLETED — 2026-05-13: GitHub Pages static hosting

### [FEAT-006] GitHub Pages browser deployment — ✅ COMPLETE

**Implemented:**
- `.nojekyll` added at repo root — prevents Jekyll from mangling underscore-prefixed identifiers.
- `electron-runtime-phase-1` merged into `main` (`f282bb1`) — all app work that had accumulated on the feature branch is now on `main` and served by GitHub Pages.
- Live URL: **https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/**

**Google OAuth / Drive setup:**
- OAuth Client ID in use: `274374578651-5edirahp87c5hpv69donfpvcr81tmidk.apps.googleusercontent.com`
- Required Authorized JavaScript Origins in Google Cloud Console (credential must be type **Web application**):
  - `https://shamsulalamx.github.io` — GitHub Pages
  - `http://localhost:8080` — Electron dev (fallback port)
  - `http://localhost:8888` — Electron dev (primary port)
- No Redirect URIs are required — the app uses the GIS token flow, not the redirect-based OAuth flow.

**Confirmed working:**
- GitHub Pages app loads correctly
- Gemini key entry in Settings works
- Gemini key persists after page reload
- Gemini key syncs through Google Drive manifest
- Incognito browser restore auto-populated Gemini key after Drive sync
- `safeExportJson` prevents `geminiApiKey` leakage into downloadable JSON exports
- Miscellaneous Documents open via blob URLs (not blocked by popup blockers)

**Pending validation (next session):**
- Drive OAuth `origin_mismatch` on school browser — likely Google Cloud Console cache delay or wrong credential type; origin `https://shamsulalamx.github.io` added to `274374578651-` credential
- Full Drive Backup Now → Restore cycle on fresh browser profile
- Miscellaneous Documents restore on a fresh profile
- School Windows computer retest

**Commits:** `37d6d4c` (.nojekyll), `f282bb1` (merge to main)

---

## COMPLETED — 2026-05-18: Focus mode, timer system, flashcards, incorrects generation

### [FEAT-007] Quiz focus mode (fullscreen) — ✅ COMPLETE

**Implemented:**
- `toggleFocusMode()` exported from Quiz module
- `body.quiz-fullscreen-mode` class controls fullscreen state
- `#screen-quiz`: `position:fixed; z-index:9999` in focus mode — covers full viewport
- App chrome (sidebar, header, nav bars) hidden via CSS
- All `.modal-overlay` elements elevated to `z-index:10000` in focus mode — prevents modals from rendering invisibly behind the fullscreen screen

**Commits:** `b1d1c09` (export), `678b97b` (hide chrome), `3cf94eb` (modal z-index fix)

---

### [BUG-008] Modal dialogs hidden behind focus-mode screen — ✅ FIXED

**Status:** ✅ FIXED. Confirmed: clicking Finish in focus mode now shows the confirmation modal correctly.

**Root cause:** `body.quiz-fullscreen-mode` sets `#screen-quiz` to `position:fixed; z-index:9999`, creating a stacking context covering the full viewport. `.modal-overlay` had `z-index:1000` and rendered behind the screen. Clicking Finish appeared to do nothing.

**Fix:** CSS-only: `body.quiz-fullscreen-mode .modal-overlay { z-index: 10000; }` — elevates all modal overlays above the fullscreen screen.

**Commit:** `3cf94eb`

---

### [FEAT-008] Pearl flashcard system — ✅ COMPLETE

**Implemented:**
- Auto-generates clinical pearl flashcards after each test from incorrectly answered questions
- Source: `q.reviewPearl || q.explanation` for each incorrect answer
- Deduplicated by content hash
- Organized: source folder → test name hierarchy
- Synced to Google Drive
- Sidebar nav item added under "Notes"

**Bug fixes same day:**
- `d0e04a4`: Fixed extraction (was pulling from wrong field)
- `92d6d2b`: Fixed trigger (was not firing reliably after test completion)

**Commits:** `de50089`, `d0e04a4`, `92d6d2b`

---

### [FEAT-009] Incorrects test generation — ✅ COMPLETE

**Implemented:**
- "Generate Incorrects Test" button in score report / review mode
- Creates focused practice test from all incorrect answers (or a review subsection)
- Routes to dedicated "Incorrects" folder
- Save destination selection UI
- Test name input and naming fixed in `be965b2`

**Commits:** `4e26061` (initial), `b769fc5` (subsection), `dfc80ee` (routing), `8685f5c` (destination), `be965b2` (naming fix)

---

### [BUG-009] Total timer cross-test leakage — ✅ FIXED

**Status:** ✅ FIXED. Confirmed: starting a second test no longer inherits elapsed time from the first.

**Root cause:** `_totTimerRef` was inside `initState()`. When a new test started, `initState()` replaced the state object with `totTimerRef: null`. The old interval reference was lost and never cleared. The orphaned interval continued writing to `state.totSecs` via the module-level `state` reference.

**Fix:** Hoisted `_totTimerRef` to module level (outside `initState()`). Always cleared before any new interval is created.

**Commit:** `b45b5ca`

---

### [BUG-010] Total timer visual jumping — ✅ FIXED

**Root cause:** Interval fired at 500ms (twice per second). `textContent` changes on variable-width strings (e.g., `09:59` → `10:00`) caused layout reflow and visible jumping/seizing.

**Fix:** Interval changed to 1000ms. `.block-timer-display` given `min-width`, `text-align:center`, `font-variant-numeric:tabular-nums`.

**Commit:** `b45b5ca`

---

### [BUG-011] Total timer not centered — ✅ FIXED

**Root cause:** Timer was in the left group of the bottom bar.

**Fix:** Bottom bar restructured to 3-column flex: `left:flex:1 (score/controls)`, `center:flex:1 (timer)`, `right:flex:1 (nav buttons)`. Typography updated: font-size 13→17px, color white, min-width 52→70px.

**Commits:** `b45b5ca` (layout), `1149aa1` (typography)

---

### [FEAT-010] Per-question timer warning — ✅ COMPLETE

**Implemented:**
- Warning state (amber color) fires when per-question elapsed time reaches ≤91 seconds (90-second mark)
- Warning CSS class added to timer display
- Warning clears on navigation to next question

**Commits:** `94f1905` (initial), `09b49e2` (refinement), `b5aaf03` (color adjustment)

---

### [FEAT-011] Miscellaneous document subfolders — ✅ COMPLETE

- Subfolder organization added to Miscellaneous Documents panel
- `MiscDocStore` schema updated to include subfolder metadata
- Files can be organized into user-created subfolders

**Commit:** `8e01c5a`

---

### [FEAT-012] Stem + choice font-size synchronization — ✅ COMPLETE

- `_applyQuestionFontSize()` synchronizes stem and choice font sizes together
- `compareStemChoiceFont` fixed to use `#options-list` as canonical choice reference

**Commits:** `dab7678`, `ab9c060`, `d11b66e`

---

---

## COMPLETED — 2026-05-18: Second session (e29420c → 81e11f5)

### [FEAT-013] Block validate save — ✅ COMPLETE (`e29420c`)

`saveValidNbmeGeminiJsonQuestionsOnly()` implemented. Filters normalized items to `isValid === true`, persists with full metadata, reports skipped count. Resolves VAL-003 (implementation complete; runtime smoke test pending).

---

### [FEAT-014] Editable saved notes — ✅ COMPLETE (`686e75c`)

- `DB.updateNote(id, newText)` added to DB layer and exposed in public API
- Notes panel: each note shows Edit button; click enters inline textarea with Save/Cancel
- `App.startNoteEdit / saveNoteEdit / cancelNoteEdit` exposed on `window.App`
- Auto-focuses textarea at end of content on edit entry

---

### [FEAT-015] Persistent stem highlights — ✅ COMPLETE (`985cfd0`)

- `DB.getStemHighlights / setStemHighlight / clearStemHighlights` added to DB layer
- Stored `db.stemHighlights[testId][String(qIdx)]`, separate from attempt results
- `saveHighlight()` and `saveHighlightPart()` in Quiz module now call `DB.setStemHighlight()` on every write
- Highlights loaded from DB on both `startTest()` and `resumeTest()`
- `stemHighlights` included in Drive backup manifest and restore path

**Key distinction:** The Drive manifest serializer excludes a key named `highlights` — this refers to IndexedDB figure/image blob data, NOT to `db.stemHighlights`. Stem highlights are stored at the top level of `db` and are correctly included.

---

### [FEAT-016] Review Later quick notes — ✅ COMPLETE (`e0bb2e8`)

- `🗒️ Review Later` button in quiz top bar → `#modal-review-later` modal
- Notes stored as `type:'reviewLater'` in `db.notes[]` via `DB.addNote()`
- Normal Notes view (`showNotes()`) filters these OUT
- `showReviewLater()` sidebar panel filters to only `type:'reviewLater'`
- `#nav-review-later` sidebar nav item between Notes and Flashcards
- Context shows test name + question number in modal header

---

### [FEAT-017] Mark reasons — ✅ COMPLETE (`608a1c7`)

- `#modal-mark-reason` modal: optional reason textarea; Cancel/Unmark, Skip, Save
- `DB.getMarkReason / setMarkReason / clearMarkReason` added — `db.markReasons[testId][String(qIdx)]` with `createdAt`/`updatedAt`
- `markReasons` included in Drive backup manifest and restore path
- `Quiz.toggleMark()` updated: mark → persist first → open reason modal; unmark → silent (no modal)
- `.marked-item-reason` CSS class renders reason with amber left-border in marked items list

**Critical invariant:** `db.markReasons` is stored separately from `db.marks` because `syncMarks()` rebuilds `db.marks` wholesale on test finish. Do not merge these.

---

### [FEAT-018] Lightweight performance summaries — ✅ COMPLETE (`130f531`)

- `getPerformanceStatsForScope(tests)` — computes testsCreated, completed, in-progress, questionsGenerated/answered, avgScore from DB history
- `renderPerformanceSummary(stats)` — flex row of stat cards; returns `''` when no tests exist
- Injected above test grid in: subfolder view, source landing, source folder page
- CSS: `.perf-summary`, `.perf-stat`, `.perf-stat-value`, `.perf-stat.accent`

---

### [FEAT-019] Electron app close and reload — ✅ COMPLETE (`60cc867`)

**Changes to `electron/main.js` only:**
- `buildAppMenu(win)` — full macOS `Menu.buildFromTemplate`: Cmd+R (reload), Cmd+Shift+R (hard reload), standard Edit/View/Window roles
- `will-prevent-unload` override — prevents Drive's `beforeunload` handler from silently swallowing window close
- Two-pass `win.on('close')` handler: defers close, flushes `saveGoogleDriveNow()` + `DB.save()` via `executeJavaScript` (3s timeout), then closes

---

### [FEAT-020] Expanded search indexing with highlighted snippets — ✅ COMPLETE (`415fa79`)

- `_stripSearchHtml(s)` — strips HTML tags/entities before indexing/display
- `buildQuestionSearchFields(q)` — priority-ordered `{label, text}` pairs: stem → tags (all variants) → pearls → choices → explanations (all format-specific fields)
- `buildHighlightedSnippet(text, query)` — 300-char context window with `<mark class="search-hl">` on all case-insensitive matches; regex-injection safe
- Search deduplicates by `testId__idx`; first-priority-matching field wins
- `.search-hl { background: #fff176 }` for yellow in-card highlighting

---

### [FEAT-021] Responsive app resizing — ✅ COMPLETE (`81e11f5`)

CSS-only changes:
- `@media (max-width: 1280px)` breakpoint narrows sidebar to 160px
- `body { overflow-x: hidden }` prevents horizontal scrollbar
- `clamp()`/`min()` values throughout: topbar padding, topbar-right gap, home padding, search width, grid minmax, perf-stat sizing, quiz topbar padding
- No functional changes; no transform:scale hacks

---

## CROSS-DEVICE RESTORE — KNOWN DEFERRED RISKS

The following risks were audited but not fixed (deferred for post-exam stability):

| Risk | Severity | Deferred reason |
|---|---|---|
| Concurrent session overwrite (two tabs, no ETag check) | Medium | Single-user app; low real-world probability |
| `saveAttempt` scheduling mid-quiz (~50 Drive calls collapsed to 1–2) | Very low | Debounce collapses correctly; not a quota risk |
| `confirm()` dialog holding `_busy` open during large MiscDoc upload | Low (UX) | Non-blocking; 50MB gate is functional |

Implement ETag/modifiedTime concurrency protection only after cross-device restore is validated end-to-end and stable.

---

## PRIORITIZED NEXT STEPS (as of 2026-05-18)

### Immediate — validate cross-device restore before studying

**Step 1 — Run a clean full Drive backup from the Mac app:**
Open Electron app or GitHub Pages in Chrome → Settings → **Backup Now** → wait until status shows "Drive backup complete". Do not close or navigate away mid-backup.

**Step 2 — Confirm backup completed cleanly:**
Re-open Settings → Drive status shows "Drive ready" (green). No error banner.

**Step 3 — Open GitHub Pages in a fresh browser / incognito tab:**
Go to https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/

**Step 4 — Connect Drive and restore:**
Settings → Connect Drive → (OAuth popup) → authorize → Restore Drive. Wait for "Drive restore complete. Reloading…" and automatic page reload.

**Step 5 — Confirm all data restored:**
- [ ] Tests and folders visible in library
- [ ] Gemini key populated (Settings → Gemini status shows "Key saved")
- [ ] Hints work on a question
- [ ] Misc docs visible in Miscellaneous Documents panel
- [ ] Score history visible for a previously completed test

**Step 6 — Retest on school Windows computer:**
Open GitHub Pages in Chrome/Edge with popups allowed. Repeat Step 3–5. If Drive OAuth fails with `origin_mismatch`, verify the `274374578651-` credential in Google Cloud Console has `https://shamsulalamx.github.io` listed and is type **Web application** (not Desktop).

### After restore is stable

**Step 7 — Add unsynced-changes warning (optional):**
Consider a `beforeunload` warning or Drive dirty-state indicator so the user knows when Drive is not yet synced. Implement only after restore is working end-to-end.

**Step 8 — Consider Windows Electron build (optional):**
If the GitHub Pages browser mode is sufficient for school use, skip the Windows build. Only build if popup restrictions or browser limitations make the hosted app impractical.

### Content work (when study time permits)

**P0 — Backfill `retrievalTag` + `reviewPearl` for Psych Shelf 3–8.** Run `node backfill-pearls.js` (requires `GEMINI_API_KEY`). Updates all 300 questions in `test-data/Psych_Shelf_*_app_ready.json` in-place. Validate, then commit. Deferred until exam prep permits.

**P1 — Run VAL-002 (figure rendering).** Import `test-data/Psych_Shelf_8_full_app_ready.json`, navigate to Q25, Q34, Q48, confirm lab-values table renders inline where the `[FIGURE: ...]` marker was. Then test the figure-upload workflow: attach a test image for one figureId before saving, confirm it renders as `<img>` in quiz view.

**P2 — Complete VAL-003 (save valid only).** Read the `saveValidNbmeGeminiJsonQuestionsOnly` function body. If it's stubbed, implement it following the pattern of `createTestFromNbmeGeminiJsonImport` but filtering `normalizedItems` to only questions whose `validation.questionResults` entry has `status === 'ok'`. Test with a JSON file that has at least one invalid question.

**P3 — Repeat extraction workflow for other NBME folders.** The Psych Shelf (3–8) is fully validated. Next: run the Gemini extraction prompt on the remaining NBME subject folders (Medicine, Surgery, Family Medicine, Pediatrics, OB/GYN, Neurology, etc.), produce `*_app_ready.json` files, import and validate each one, add to `test-data/`, commit. Each new folder may expose new sanitizer edge cases.

**P4 — Shared-group rendering validation.** Psych_Shelf_3 Q33–Q36 and Psych_Shelf_4 have `sharedGroup.sharedStem`. After importing these files, navigate to those questions in quiz mode and confirm the shared vignette renders above the per-question stem via `buildSharedGroupHTML`. Verify linked question range is shown correctly.

**P5 (post-exam) — Phase 2 pearl generation.** Add `ipcMain.handle('nbme:ai:generate-pearls', ...)` to `electron/main.js`. Expose via `preload.js`. Add "Generate Missing Tags & Pearls" button in score summary, guarded by `window.nbmeDesktop?.ai?.generatePearls` so it only appears in Electron. No Netlify involvement.

---

## DO NOT

- Reintroduce Netlify functions or any server-side backend.
- Hardcode the Gemini API key anywhere in the source.
- Put the Gemini API key into exported test JSON files (all downloads must use `safeExportJson()`).
- Perform major storage migrations (FigureStore, IndexedDB rewrite, localStorage restructure) before the exam.
- Implement Supabase, Firebase, or any external database.
- Refactor into React or add a build system without a clear need.
- Move `_totTimerRef` inside `initState()` — causes cross-test timer leakage (BUG-009).
- Reduce `.modal-overlay` z-index below 10000 when `body.quiz-fullscreen-mode` is active (BUG-008).
- Call `scheduleGoogleDriveSave()` after `DB.save()` — `DB.save()` already schedules it (causes double-debounce delay).
