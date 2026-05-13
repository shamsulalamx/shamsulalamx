# BUGS AND NEXT STEPS

**Last updated:** 2026-05-13 (Phase 1 retrieval tag + review pearl complete)  
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

## PRIORITIZED NEXT STEPS

**P1 — Run VAL-002 (figure rendering).** Import `test-data/Psych_Shelf_8_full_app_ready.json`, navigate to Q25, Q34, Q48, confirm lab-values table renders inline where the `[FIGURE: ...]` marker was. Then test the figure-upload workflow: attach a test image for one figureId before saving, confirm it renders as `<img>` in quiz view.

**P2 — Complete VAL-003 (save valid only).** Read the `saveValidNbmeGeminiJsonQuestionsOnly` function body. If it's stubbed, implement it following the pattern of `createTestFromNbmeGeminiJsonImport` but filtering `normalizedItems` to only questions whose `validation.questionResults` entry has `status === 'ok'`. Test with a JSON file that has at least one invalid question.

**P3 — Repeat extraction workflow for other NBME folders.** The Psych Shelf (3–8) is fully validated. Next: run the Gemini extraction prompt on the remaining NBME subject folders (Medicine, Surgery, Family Medicine, Pediatrics, OB/GYN, Neurology, etc.), produce `*_app_ready.json` files, import and validate each one, add to `test-data/`, commit. Each new folder may expose new sanitizer edge cases.

**P4 — Shared-group rendering validation.** Psych_Shelf_3 Q33–Q36 and Psych_Shelf_4 have `sharedGroup.sharedStem`. After importing these files, navigate to those questions in quiz mode and confirm the shared vignette renders above the per-question stem via `buildSharedGroupHTML`. Verify linked question range is shown correctly.

**P5 (post-exam) — Phase 2 pearl generation.** Add `ipcMain.handle('nbme:ai:generate-pearls', ...)` to `electron/main.js`. Expose via `preload.js`. Add "Generate Missing Tags & Pearls" button in score summary, guarded by `window.nbmeDesktop?.ai?.generatePearls` so it only appears in Electron. No Netlify involvement.
