# BUGS AND NEXT STEPS

**Last updated:** 2026-05-13 (renderer/report bug fixes complete)  
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

### [VAL-001] Explanation rendering end-to-end test — ✅ VALIDATED

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

**Status:** Partially implemented. Verify whether `saveValidNbmeGeminiJsonQuestionsOnly` has a complete function body or is just a stub.

**What to test:**
1. Import a JSON file with some invalid questions (e.g., missing choices)
2. In the import modal, check whether a "Save valid questions only" button appears
3. Verify it saves only questions that passed validation, skipping errored ones

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

## PRIORITIZED NEXT STEPS

**P0 — Backfill `retrievalTag` + `reviewPearl` for Psych Shelf 3–8.** Run `node backfill-pearls.js` (requires `GEMINI_API_KEY`). Updates all 300 questions in `test-data/Psych_Shelf_*_app_ready.json` in-place. Validate, then commit. Deferred until exam prep permits.

**P1 — Run VAL-002 (figure rendering).** Import `test-data/Psych_Shelf_8_full_app_ready.json`, navigate to Q25, Q34, Q48, confirm lab-values table renders inline where the `[FIGURE: ...]` marker was. Then test the figure-upload workflow: attach a test image for one figureId before saving, confirm it renders as `<img>` in quiz view.

**P2 — Complete VAL-003 (save valid only).** Read the `saveValidNbmeGeminiJsonQuestionsOnly` function body. If it's stubbed, implement it following the pattern of `createTestFromNbmeGeminiJsonImport` but filtering `normalizedItems` to only questions whose `validation.questionResults` entry has `status === 'ok'`. Test with a JSON file that has at least one invalid question.

**P3 — Repeat extraction workflow for other NBME folders.** The Psych Shelf (3–8) is fully validated. Next: run the Gemini extraction prompt on the remaining NBME subject folders (Medicine, Surgery, Family Medicine, Pediatrics, OB/GYN, Neurology, etc.), produce `*_app_ready.json` files, import and validate each one, add to `test-data/`, commit. Each new folder may expose new sanitizer edge cases.

**P4 — Shared-group rendering validation.** Psych_Shelf_3 Q33–Q36 and Psych_Shelf_4 have `sharedGroup.sharedStem`. After importing these files, navigate to those questions in quiz mode and confirm the shared vignette renders above the per-question stem via `buildSharedGroupHTML`. Verify linked question range is shown correctly.

**P5 (post-exam) — Phase 2 pearl generation.** Add `ipcMain.handle('nbme:ai:generate-pearls', ...)` to `electron/main.js`. Expose via `preload.js`. Add "Generate Missing Tags & Pearls" button in score summary, guarded by `window.nbmeDesktop?.ai?.generatePearls` so it only appears in Electron. No Netlify involvement.
