# BUGS AND NEXT STEPS

**Last updated:** 2026-05-12  
**Purpose:** Active bug tracker and prioritized work queue for handoff to Codex. Contains all unresolved issues, failed diagnoses, and explicit debugging instructions. This file must be updated as bugs are resolved.

---

## UNRESOLVED BUGS

### [BUG-001] Quiz stem truncation — CRITICAL, UNRESOLVED

**Status:** ❌ NOT FIXED. Do not mark this fixed without confirmed DOM evidence.

**Symptom:**  
When a question from the `nbme-gemini-json` importer is displayed in quiz mode, Q1, Q9, Q11, and Q24 of `Psych_Shelf_8_full_app_ready.json` show only 1–2 lines of text. The stems for these questions are 608, 828, 1160, and 1319 characters respectively. No scrollbar appears. The missing content is not accessible to the user.

**Scope:** This affects quiz view only (the screen shown when actively answering a question). The import preview modal and explanation review panel are separate and have their own known-fixed issues.

**What has been verified:**
- The raw JSON file contains the full stem text for all questions.
- The `normalizeNbmeGeminiJsonImport` function copies `q.t` from the JSON without truncation.
- The 240-character truncation that was in the import preview (`stemPreview = String(q.stem || '').slice(0, 240)`) was removed — but this only affected the import preview modal, NOT quiz view. This removal did not fix the quiz stem display.
- The dist bundle (`dist/mac-arm64/.../index.html`) was synced with the source on 2026-05-12 19:13. After the sync, the bug still persisted. Therefore the stale build was not the sole cause.
- A CSS fix was applied to `.quiz-content-area` (added `min-height: 0; overflow-y: auto; overflow-x: hidden`). The bug still persisted after this fix.

**Three failed diagnosis attempts:**
1. **240-char slice hypothesis** — Removed `slice(0,240)` from import preview. Did not affect quiz view. Wrong location.
2. **Stale dist build hypothesis** — Synced dist bundle. Bug persisted. Not the sole root cause.
3. **Flexbox overflow CSS hypothesis** — Added `min-height:0; overflow-y:auto` to `.quiz-content-area`. Bug persisted. CSS change may not have taken effect, or root cause is elsewhere.

**What has NOT been investigated (must be checked):**

1. **`shouldUseStemCropForQuestion(q)` returning true** — Search for this function in `index.html`. If it returns true for a question, the quiz renderer switches to image-crop mode, which shows `buildSharedGroupHTML(q)` instead of text. Questions from `nbme-gemini-json` have no crop image, so this would show nothing or 1–2 lines from a mismatched path.

2. **`r.highlights` being set unexpectedly** — Inside `renderQuestion()` (the main quiz question renderer), if `r.highlights` is set, a different stem rendering path may be taken. Check what `r` is for these questions.

3. **`-webkit-line-clamp` from an undetected CSS rule** — Search entire `index.html` for `-webkit-line-clamp` and `line-clamp`. If any ancestor of `#q-stem` has this property set, it will cap displayed lines regardless of content or overflow.

4. **`max-height` on an ancestor element** — Search for `max-height` on `#q-stem`, `.quiz-content-area`, `.question-stem-container`, `.stem-text-container`, `#quiz-main`, `#screen-quiz`. Any pixel-value `max-height` combined with `overflow: hidden` would clip the content invisibly.

5. **Wrong renderer being called** — There may be a separate renderer for questions with `sourceType: 'nbme-gemini-json'`. Confirm which code path actually executes for these questions by adding a temporary `console.log` at the top of each candidate render function.

6. **Electron window width triggering a media query** — The Electron window may be narrower than 768px or another breakpoint. Search for media queries in the CSS that affect `.quiz-content-area` or `#q-stem`.

**How to debug correctly (step-by-step):**

```
STEP 1: Run the app in dev mode only.
  cd "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite"
  npm run electron:dev

STEP 2: Import Psych_Shelf_8_full_app_ready.json via the NBME JSON importer.
  File is at: /Users/shamsulalam/Desktop/NBME Self-Assessment Suite/test-data:/Psych_Shelf_8_full_app_ready.json
  (Note: "test-data:" is the literal directory name with a colon)

STEP 3: Start a quiz with Q1.

STEP 4: Open Electron DevTools: View > Toggle Developer Tools (or Cmd+Option+I).

STEP 5: In Console, run:
  const stem = document.getElementById('q-stem');
  console.log('element:', stem);
  console.log('innerText length:', stem?.innerText?.length);
  console.log('scrollHeight:', stem?.scrollHeight);
  console.log('clientHeight:', stem?.clientHeight);
  console.log('full text:', stem?.innerText);

  Expected if full stem is in DOM: innerText.length ≈ 600, scrollHeight > clientHeight
  Expected if stem is truncated in DOM: innerText.length ≈ 60–120

STEP 6: If DOM contains full text but content is clipped (scrollHeight > clientHeight):
  Root cause is CSS. Use DevTools Elements panel to inspect #q-stem and every ancestor:
  - Look for: overflow:hidden, max-height, -webkit-line-clamp, height (fixed px)
  - Toggle them off one-by-one until content appears

STEP 7: If DOM contains only 1–2 lines (innerText.length is short):
  Root cause is the renderer. Add console.log at the START of these functions:
  - renderQuestion() (Quiz IIFE, ~line 5644 area)
  - window.buildStemHTML()
  - window.buildQuestionStemHTML()
  Check which one runs for Q1 and what text it receives.

STEP 8: If none of the above reveals the issue:
  Search index.html for: shouldUseStemCropForQuestion
  If found, check what it returns for a q with sourceType='nbme-gemini-json' and no metadata.cropRect.
```

**Key function locations:**
- `renderQuestion()` — Quiz IIFE, look for the function that calls `buildQuestionStemHTML` or sets `#q-stem` innerHTML
- `window.buildQuestionStemHTML` — ~line 5168
- `window.buildStemHTML` — ~line 5140 area
- `window._replaceFigureMarkersInStemHtml` — ~line 5228
- CSS for `.quiz-content-area` — ~line 546

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

**P0 — Fix BUG-001 (stem truncation).** Follow the debugging instructions above. Do not skip Step 5 (DOM inspection). Do not apply another CSS fix without first confirming via `scrollHeight` vs `clientHeight` whether the text is in the DOM or not.

**P1 — Run VAL-001 (explanation rendering).** Delete old imported test, reimport, answer Q1, confirm explanation panel works.

**P2 — Run VAL-002 (figure rendering).** Answer Q25/Q34/Q48, confirm placeholder appears. Then test figure upload workflow end-to-end.

**P3 — Complete VAL-003 (save valid only).** Read the `saveValidNbmeGeminiJsonQuestionsOnly` function body. If it's stubbed, implement it following the pattern of `createTestFromNbmeGeminiJsonImport` but filtering to `validation.questionResults.filter(r => r.status === 'ok')`.

**P4 — Broader JSON import validation.** Test with a JSON file that has mixed valid/invalid questions to confirm the validation summary, warning counts, and save options all behave correctly.
