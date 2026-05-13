# BUGS AND NEXT STEPS

**Last updated:** 2026-05-12 (BUG-001 resolved)  
**Purpose:** Active bug tracker and prioritized work queue for handoff to Codex. Contains all unresolved issues, failed diagnoses, and explicit debugging instructions. This file must be updated as bugs are resolved.

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

### [VAL-001] Explanation rendering end-to-end test

**What to test:**
1. `npm run electron:dev`
2. Delete any previously imported Psych_Shelf_8 test (it predates the fix)
3. Import `test-data:/Psych_Shelf_8_full_app_ready.json` fresh
4. Start a quiz, answer Q1, click "Correct Answer" or view explanation
5. Verify: blue "Educational Objective" box appears with plain text
6. Verify: structured explanation block appears below with the "Correct Answer" section content
7. Verify: per-choice explanations appear for each incorrect choice

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

## PRIORITIZED NEXT STEPS

**P1 — Run VAL-001 (explanation rendering).** Delete old imported test, reimport, answer Q1, confirm explanation panel works.

**P2 — Run VAL-002 (figure rendering).** Answer Q25/Q34/Q48, confirm placeholder appears. Then test figure upload workflow end-to-end.

**P3 — Complete VAL-003 (save valid only).** Read the `saveValidNbmeGeminiJsonQuestionsOnly` function body. If it's stubbed, implement it following the pattern of `createTestFromNbmeGeminiJsonImport` but filtering to `validation.questionResults.filter(r => r.status === 'ok')`.

**P4 — Broader JSON import validation.** Test with a JSON file that has mixed valid/invalid questions to confirm the validation summary, warning counts, and save options all behave correctly.
