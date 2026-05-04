# NBME Self-Assessment Suite — Project Context & Status

## Overview

A single-page HTML application for medical students to take NBME-style practice tests. Runs entirely in the browser. Opens via `index.html` in Chrome.

**Live URL:** https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/
**GitHub Repo:** github.com/shamsulalamx/NBME-Self-Assessment-Suite (Public)
**User email:** shuvoli8@gmail.com

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Pure HTML, CSS, JavaScript — no frameworks |
| PDF text extraction | PDF.js v3.11.174 — `getTextContent()` for vector PDFs |
| OCR fallback | Tesseract.js v5 — active, used for image-only PDFs |
| Storage primary | Browser localStorage |
| Session sync | Supabase — fully working |
| AI hints + tagging | Google Gemini API `gemini-2.5-flash` |
| PDF report download | jsPDF 2.5.1 |
| Hosting | GitHub Pages |

---

## File Structure

```
NBME Self-Assessment Suite/
  index.html          ← entire app, single self-contained file (~4800+ lines after v9 edits)
  test.html           ← browser-based test runner for verifying fixes (do not delete)
  css/                ← IGNORE — failed split attempt, not used
  js/                 ← IGNORE — failed split attempt, not used
  PROJECT_CONTEXT.md  ← this file
  README.md
```

**CRITICAL: Never split index.html into separate files. Never link to css/ or js/ folders.**

---

## JavaScript Modules (all inlined in index.html)

| Module | Approx Lines | Description |
|---|---|---|
| DB | 1494–1615 | Storage layer: localStorage + Supabase sync |
| Supabase | 1616–1760 | Session sync, user code generation |
| OCR | 1761–2310 | PDF extraction engine v9 (see full details below) |
| Quiz | 2330–2870 | Test-taking engine: state, timers, navigation, modes |
| Results | 2940–3490 | Score report, analytics, review mode |
| App | 3500–4170 | Main controller, UI, routing, sidebar, modals |
| PIN | 4170–4310 | 4-digit passcode protection |
| Bootstrap | 4310+ | App initialization on DOMContentLoaded |

> Note: Line numbers are approximate and will have shifted after v9 edits. Always search by function name, not line number.

---

## Supabase Configuration

```
URL: https://lmxdedepkwmilnvjcxil.supabase.co
Key: sb_publishable_CVhmesK9VAUhAn-mMpQHYQ_yg2MMz9Q
Table: sessions — columns: user_id text, data jsonb, updated_at timestamp
Status: Working. User sees readable code like TIGER-4829 in the UI.
```

---

## Gemini API Configuration

```
Model: gemini-2.5-flash
Key stored in: localStorage under key "gemini_api_key"
Also synced to Supabase session data
Billing: Active, $10 prepaid credits
Status: Working for hints. AI auto-tagging working.
```

---

## Features Status

| Feature | Status |
|---|---|
| 4-digit PIN screen | ✅ Working |
| UWorld sidebar with folders | ✅ Working |
| Sidebar collapsible | ⚠️ Attempted (v9) — passes test.html but may not work correctly in app |
| Home screen grid with progress | ✅ Working |
| Trash folder | ✅ Working |
| Timer — per-question (counts up) | ⚠️ Attempted fix (v9) — flickering partially improved, needs re-verification |
| Timer — block elapsed (bottom bar) | ✅ Working |
| Timer — redundant top bar total | ⚠️ Attempted removal (v9) — passes test.html but needs visual confirmation |
| Auto yellow highlight | ✅ Working |
| Font size A+ A- buttons | ⚠️ Attempted fix (v9) — passes test.html but zoom behavior may persist in app |
| Calculator strip | ✅ Working |
| Lab Values panel | ✅ Working |
| PDF extraction — vector PDFs | ✅ Working (OCR v9) |
| PDF extraction — image-only PDFs | ✅ Working via Tesseract fallback (slow: ~3–8 min for 50 pages) |
| Phantom spaces in extracted text | ⚠️ Threshold raised to 0.6 (v9) — passes test.html but real PDF re-verification needed |
| Answer choices A–K (11-choice questions) | ⚠️ Attempted fix (v9) — passes test.html but real PDF re-verification needed |
| Lab value tables in question stems | ⚠️ Attempted (v9) — passes test.html but real PDF re-verification needed |
| Embedded figures in questions | ⚠️ Attempted (v9) — figure detection logic added, not yet verified end-to-end |
| Explanation display | ✅ Working |
| AI tags position (after explanation) | ⚠️ Attempted (v9) — passes test.html but needs visual confirmation in app |
| Navigation panel scroll to Q50 | ⚠️ Attempted fix (v9) — needs visual confirmation |
| Navigation panel width | ⚠️ Attempted fix (v9, ~140px) — needs visual confirmation |
| Edit Question button | ⚠️ Attempted removal (v9) — passes test.html but needs visual confirmation |
| Hint button position (top bar) | ⚠️ Attempted move (v9) — passes test.html but needs visual confirmation |
| Review Test button | ⚠️ Attempted (v9) — passes test.html but full review view not verified end-to-end |
| Copy/paste from question text | ⚠️ Attempted (v9) — passes test.html but real app behavior not confirmed |
| PDF report download | ✅ Working |
| PDF report — per-question times | ⚠️ Attempted fix (v9) — wild time values (0s, 1292s) may still occur |
| AI Hints with Gemini | ✅ Working |
| AI auto-tagging | ✅ Working |
| Supabase session sync | ✅ Working |
| Search in navigation panel | ❌ Not yet implemented |
| Surgery PDF extraction | ⏸️ Deferred — Tesseract path built but not tested end-to-end |

---

## OCR Engine — Current Version: v9

### Architecture

The engine has two paths selected automatically:

1. **Vector PDF path** (fast): PDF.js `getTextContent()` — used when the PDF has a real text layer (>50 chars detected in first 3 pages). This is the path used for all standard NBME Psych/Medicine/Surgery Shelf PDFs downloaded from the NBME website.

2. **Image-only PDF path** (slow): Tesseract.js v5 OCR — used when PDF.js finds no text. Triggered for PDFs created from PowerPoint screenshots or scanned documents. Each page is rendered to canvas at 2× scale and OCR'd. Expect 3–8 minutes for 50 pages.

### PDF Format — NBME Standard (vector, used for Psych)

Each question PDF page:
- **Top chrome** (y > 700pt): `Exam Section : Item X of N`, `National Board of Medical Examiners`, `Time Remaining:`
- **Bottom chrome** (y < 48pt): `Previous`, `Next`, `Lab Values`, `Calculator`, `Review`, `Help`, `Pause`, glyph noise
- **Content band** (48pt < y < 700pt): question stem + answer choices
- **Radio buttons**: separate text items at x < 80, rendered as `0` or `O` — filtered out
- **Answer choices**: format `A )  text` (space before paren) or `A)  text`

Each answer PDF page:
- Same chrome bands
- `Correct Answer: X.` line
- Full explanation paragraphs
- Each answer item spans **2 PDF pages** — page 2 repeats full explanation (deduplication handles this)

### PDF Format — Surgery (image-only, PowerPoint screenshots)

- Page size: 959×523pt (widescreen 16:9)
- Created by: Microsoft PowerPoint → Export as PDF
- No text layer — Tesseract OCR path is used
- Top 15% of image = header chrome (item number extracted here)
- Bottom 12% = navigation buttons (excluded)
- Middle 73% = question content

### Key Constants (in OCR module)

```javascript
PAGE_HEIGHT      = 752    // pt — NBME vector PDF standard page height
TOP_CHROME_Y     = 700    // filter rows above this (vector path)
BOTTOM_CHROME_Y  = 48     // filter rows below this (vector path)
PARA_GAP_PT      = 25     // Y gap (pt) → paragraph break (vector path)
```

### All Regex Patterns (current, authoritative — v9)

```javascript
// Item header — handles both "Item 1 of 50" and "Item: 1 of 50" (Surgery answers format)
/[Ii]tem\s*:?\s*(\d+)\s+of\s+(\d+)/

// Correct answer — requires colon + single letter, won't match "Incorrect Answers: A, B"
// v9: expanded from A-H to A-K
CA_RE = /correct\s+answer\s*[:\-.]\s*([A-Ka-k])(?:[.\s,]|$)/i

// Answer option — handles "A) text", "A ) text", "A )  text" (space before paren)
// v9: expanded from A-H to A-K
OPT_RE = /^(?:[0oOQ©®°]\s{0,3})?([A-Ka-k])\s{0,2}[)]\s{0,4}(.{2,})/

// Next question boundary (stops option parsing when new question starts)
NEXT_Q_RE = /^(\d+)[.,]\s+\S/

// Question number prefix (handles OCR period/comma variants)
/^(\d+)[.,]\s+(.+)/

// splitMergedOptions — two-column layout detection
// v9: expanded from A-H to A-K
/\s+(?=(?:[0oOQ]\s{0,3})?[A-Ka-k]\s{0,2}\)\s{1,4}\S)/
```

### Key Pipeline Functions

```
extractPdfText(file)              → pages[]  {pageNum, paragraphs[], itemNum, totalItems}
  └─ pdfHasTextLayer(pdf)         → bool  (samples 3 pages, checks char count > 50)
  └─ [vector path] joinItems()    → merges PDF.js text items on same line
  └─ [image path] ocrPageImage()  → renders page to canvas, runs Tesseract
  └─ [image path] parseOcrPage()  → extracts item number + content from OCR lines
groupPagesByItem(pages)           → itemMap  {itemNum → paragraphs[]}
parseQuestionBank(itemMap)        → questions[]
parseAnswerKey(itemMap)           → answers{}
matchAndMerge(questions, answers) → matched[]
aiTagQuestions(matched)           → tags added in-place
processTestPDFs(qFile, aFile, onProgress) → matched[]  ← main entry point
```

---

## Full Fix History

### v7 → v8 Fixes

#### Fix A — Item header regex handles Surgery answers format
**Problem:** Surgery answers PDF uses `Exam Section Item: 1 of 50` (colon after "Item").
**Fix:** `/[Ii]tem\s*:?\s*(\d+)\s+of\s+(\d+)/` — `\s*:?\s*` allows optional colon.

#### Fix B — Answer option regex handles space before paren
**Problem:** Surgery/Psych PDFs render choices as `A )  text`.
**Fix:** `([A-Ha-h])\s{0,2}[)]\s{0,4}` — allows 0–2 spaces before `)`.

#### Fix C — Tesseract OCR fallback for image-only PDFs
**Problem:** Surgery PDFs are PowerPoint screenshot images — PDF.js returns zero text.
**Fix:** `pdfHasTextLayer()` detects image-only PDFs; OCR path renders each page to canvas at 2× and runs Tesseract.js.

#### Fix D — Phantom space fix (font-size-relative threshold)
**Problem:** Fixed threshold failed for many words (`serotonin` → `seroton in`).
**Fix:** `joinItems()` uses `fontSize × 0.5` as estimated char width; merges when gap < `estCharW × 0.4`.

#### Fix E — (Choice A) paragraph split in explanations
**Problem:** PDF renderer splits `(Choice A)` across two paragraphs.
**Fix:** Rejoin pass in `parseOneAnswer` detects paragraphs ending with `(Choice` and merges with next.

#### Fix F — Split apostrophes in normalizeChars
**Problem:** `"child 's"`, `"doesn 't"` in extracted text.
**Fix:** Regex replacements for `'s`, `'t`, `'re`, `'ve`, `'ll` contractions.

#### Fix G — Question/NEXT_Q boundary regex more flexible
**Problem:** OCR may produce comma instead of period after question number.
**Fix:** `NEXT_Q_RE = /^(\d+)[.,]\s+\S/`

---

### v8 → v9 Fixes (20 prompts — implemented via Claude Code)

> **Important:** All 20 fixes below were implemented and passed `test.html` automated tests. However, test.html uses source code analysis and iframe inspection — it cannot fully simulate real PDF upload and quiz interaction. Several fixes that passed test.html have been reported as still exhibiting issues in the running app. See "Known Remaining Issues" section for details.

#### Fix 1 — OPT_RE / CA_RE expanded to A–K
**Problem:** Questions with 11 choices (e.g. item 10, A–K two-column layout) had choices G–K silently dropped.
**Fix:** OPT_RE, CA_RE, splitMergedOptions, and NEXT_Q_RE all expanded from `[A-Ha-h]` to `[A-Ka-k]`.
**Status:** Passes test.html. Real PDF re-verification still needed.

#### Fix 2 — Phantom space threshold raised to 0.6
**Problem:** Words still showing phantom spaces after v8 fix (threshold 0.4 was too conservative).
**Fix:** `joinItems()` threshold changed from `estCharW * 0.4` to `estCharW * 0.6`.
**Status:** Passes test.html. Real PDF re-verification still needed.

#### Fix 3a — Lab value extraction splitting
**Problem:** Two-column lab value tables (Na+, Cl-, K+, etc.) collapsed into one run-on line during PDF extraction.
**Fix:** Paragraph splitter in OCR pipeline detects concatenated lab value pairs and splits them into individual lines.
**Status:** Passes test.html. Real PDF re-verification still needed.

#### Fix 3b — Lab value table rendering
**Problem:** Lab value lines displayed as plain unstyled text in question stems.
**Fix:** Quiz renderer detects consecutive lab value paragraphs and renders them as an HTML `<table class="lab-values-table">`.
**Status:** Passes test.html. Real PDF re-verification still needed.

#### Fix 4a — Embedded figure detection and display
**Problem:** Questions with embedded images (e.g. item 48, Figure 1 and Figure 2) lost all image content during extraction.
**Fix:** Vector PDF path detects figure references in text, renders the page to canvas at 1.5×, captures as base64 PNG, attaches as `__FIGURE__:` token in stem, rendered as `<img>` in quiz view.
**Status:** Logic implemented. End-to-end verification with item 48 still needed.

#### Fix 4b — AI tags moved to after explanation
**Problem:** AI topic tags appeared before explanation, potentially giving away the answer.
**Fix:** Tag rendering moved to after full explanation text in Results module.
**Status:** Passes test.html. Visual confirmation in app still needed.

#### Fix 5a — Navigation panel scroll to Q50
**Problem:** Navigation panel could not be scrolled to question 50.
**Fix:** Navigation question grid container given `overflow-y: auto` and `flex: 1` to fill available height.
**Status:** Passes test.html. Visual confirmation in app still needed.

#### Fix 5b — Navigation panel width reduced
**Problem:** Navigation panel too wide, taking excessive screen space.
**Fix:** Width reduced to ~140px; question buttons resized to 28×28px, font-size 11px.
**Status:** Passes test.html. Visual confirmation in app still needed.

#### Fix 6 — Left sidebar collapsible
**Problem:** Left sidebar (Home, Folders, Trash, etc.) could not be collapsed.
**Fix:** Toggle button added; `.sidebar-collapsed` class collapses sidebar to 36px; CSS transition 200ms; state persisted in localStorage.
**Status:** Passes test.html. Real app behavior (animation, persistence) needs confirmation.

#### Fix 7a — Redundant top bar total timer removed
**Problem:** Two total elapsed time displays visible simultaneously (top bar and bottom bar).
**Fix:** Top bar total elapsed timer element and its JS update logic removed.
**Status:** Passes test.html. Visual confirmation in app still needed.

#### Fix 7b — Timer flickering fixed
**Problem:** Per-question timer flickered due to multiple `setInterval()` calls accumulating.
**Fix:** Single named `questionTimerInterval` variable; always `clearInterval()` before starting new; `Date.now()` delta used instead of counter increment.
**Status:** Passes test.html. Real app timer behavior may still need verification.

#### Fix 7c — Per-question times in PDF report fixed
**Problem:** PDF report showed wildly wrong times (0s, 1292s, 93s randomly).
**Fix:** `timeSpent` saved on every question navigation; `questionStartTime = Date.now()` reset on each question load; values clamped to 0–3600s in PDF generation.
**Status:** Passes test.html. Needs real download and inspection to confirm.

#### Fix 8 — Font size A+/A- scoped to question content only
**Problem:** A+/A- buttons zoomed the entire page.
**Fix:** Removed `document.body.style.zoom`; `fontSize` variable (10–22px, step 2) now applied only to question stem, answer choices, and explanation containers; persisted in localStorage.
**Status:** Passes test.html. Real app behavior may still show full-page zoom.

#### Fix 9 — Edit Question button removed
**Problem:** Edit Question button was unused and cluttered the UI.
**Fix:** Button element, its event handler, its modal/form, and related CSS all removed.
**Status:** Passes test.html. Visual confirmation in app still needed.

#### Fix 10 — Hint button moved to top bar
**Problem:** Hint (AI/Gemini) button was in the question area.
**Fix:** Hint button moved to top bar adjacent to Pause button; all click handler functionality unchanged.
**Status:** Passes test.html. Visual confirmation in app still needed.

#### Fix 11a — Review Test button added to completed tests
**Problem:** No way to review a completed test from the home screen.
**Fix:** "Review Test" button added to each completed test card; calls `reviewTest(testId)`.
**Status:** Passes test.html. Visual confirmation in app still needed.

#### Fix 11b — Review Test full view implemented
**Problem:** `reviewTest()` had no rendering implementation.
**Fix:** Full-page scrollable review view renders all 50 questions with: user highlights, strikethroughs, selected answer marked, correct/incorrect indicators, full explanation, AI tags at end. Back button returns to home screen.
**Status:** Passes test.html. End-to-end review flow needs verification with a real completed test.

#### Fix 12a — Text selection CSS/JS unblocked
**Problem:** `user-select: none` and `selectstart` handlers prevented copying text.
**Fix:** `user-select: none` removed from question stem, answer choices, explanation containers; `selectstart` preventDefault removed from content areas.
**Status:** Passes test.html. Real copy behavior in app still needs confirmation.

#### Fix 12b — Answer choice click vs. drag conflict resolved
**Problem:** Dragging to select text on an answer choice triggered strikethrough or answer selection.
**Fix:** `window.getSelection().toString().length > 0` guard added to both answer selection and strikethrough handlers — if user has text selected, click action is suppressed.
**Status:** Passes test.html. Real app behavior needs confirmation.

---

## Known Remaining Issues

### Critical — Verified failing in app despite passing test.html

These passed automated tests but are reported as still broken when actually running the app. They should be the **first priority** in the next session.

| # | Issue | Notes |
|---|---|---|
| R1 | Phantom spaces still present in extracted text | test.html passes (threshold 0.6 confirmed in source) but real PDF extraction still shows spaces within words. May need threshold increase to 0.7–0.8, or the raw PDF.js items may not be passing `transform`/`width` fields correctly to joinItems(). |
| R2 | Font size A+/A- still zooms whole page | test.html passes (no body.style.zoom in source) but zoom behavior persists in app. The fix may have been applied to a copy of the handler while the original remained. |
| R3 | Timer flickering still visible | test.html passes (clearInterval pattern confirmed) but timer still flickers in app. Multiple intervals may still be created on question navigation. |
| R4 | Copy/paste still not working properly | test.html passes (user-select:none removed) but text selection still behaves incorrectly in app for some elements. |
| R5 | Navigation scroll still cuts off at Q50 | test.html passes but visual inspection shows issue persists. |

### OCR / Extraction

| # | Issue | Notes |
|---|---|---|
| O1 | Answer choices G–K on 11-choice questions | Fix 1 implemented and passes test.html but real PDF with item 10 (A–K) not yet re-uploaded to verify |
| O2 | Lab value table rendering | Fix 3a/3b passes test.html but real PDF item 5 not yet verified |
| O3 | Embedded figures (item 48) | Fix 4a implemented but item 48 figure display not verified end-to-end |
| O4 | Psych Shelf 4 item 8 possibly missing | 49 questions extracted instead of 50. Uses extended matching (two-column 8-choice layout). NEXT_Q_RE fix applied but not re-verified. |
| O5 | Trailing digits after answer choices | Radio button glyph filter `x < 80 * sc` may need widening to `x < 100 * sc` for some PDF layouts. |
| O6 | Surgery PDF extraction | Tesseract path built and code-reviewed but not tested end-to-end. Deferred — focus is Psych only. |

### UI Issues

| # | Issue | Notes |
|---|---|---|
| U1 | Sidebar collapse animation | May not animate smoothly or state may not persist on reload |
| U2 | Hint button position | May not appear correctly in top bar during quiz mode |
| U3 | Review Test view | Full review rendering not verified with real completed test data |
| U4 | PDF report times | Wild values (0s, 1292s) may still occur despite fix |
| U5 | AI tags before explanation | May still appear before explanation in some rendering paths |
| U6 | Search in navigation panel | Not yet implemented |
| U7 | Lab values panel layout | Separate from lab value table in question stem — the sidebar lab reference panel has a layout issue not yet addressed |

---

## test.html — Automated Test Runner

A `test.html` file exists in the project root alongside `index.html`. It runs automated pass/fail checks for all 20 v9 fixes. Open it in Chrome to see results.

**Important caveat:** test.html uses source code analysis (`fetch('index.html')`) and hidden iframe inspection. It cannot:
- Actually upload and process a PDF
- Simulate real user interactions in the quiz
- Detect issues that only appear during runtime state changes

**Therefore:** A PASS in test.html means the code change exists in the source. It does not guarantee the feature works correctly in the running app. Always verify visually in the app after test.html confirms PASS.

---

## How to Diagnose a Fix That Passes test.html But Fails in App

When a fix passes test.html but the problem persists in the app, run this diagnosis prompt in Claude Code:

```
Read index.html carefully.

The fix for [ISSUE NAME] passes test.html but the problem 
still occurs in the running app.

Do not fix anything yet. Search index.html for ALL locations 
where [the relevant code/element/handler] exists. List every 
occurrence with its line number and surrounding context. 

I need to know if:
1. The fix was applied in one place but the same logic 
   exists in another place that was missed
2. The fix overwrites a variable that gets reset elsewhere
3. The fix applies to a static element but the element 
   is actually created dynamically in JS
```

This diagnosis step prevents wasted re-fix attempts.

---

## Priority for Next Session

### Immediate Priority — Fix the "passes test.html but fails in app" issues

Work through R1–R5 from the Known Remaining Issues table above, one at a time:

1. **R1 — Phantom spaces:** Upload psych_shelf_5_questions.pdf and check extracted text for spaces within words. If still present, diagnose whether `joinItems()` is receiving correct `transform` and `width` fields from PDF.js items. May need threshold increase to 0.7 or 0.8.

2. **R2 — Font size zoom:** Inspect all A+/A- click handlers in index.html. The fix may have been applied to one handler while a second copy remained untouched.

3. **R3 — Timer flicker:** Open browser DevTools Performance tab while navigating between questions. Look for multiple intervals firing simultaneously.

4. **R4 — Copy/paste:** Test in app — try to select and copy a sentence from the question stem. If still blocked, inspect the element in DevTools for remaining `user-select` rules or event listeners.

5. **R5 — Navigation scroll:** Open the nav panel during a quiz, attempt to scroll to Q50. Inspect the container's CSS in DevTools.

### After R1–R5 — Verify v9 fixes visually

Work through all ⚠️ items in the Features Status table to confirm they work in the actual app, not just in test.html.

### After visual verification — New features

- Search in navigation panel
- Any additional PDF shelves (Medicine, Surgery) if needed

---

## Important Rules for Claude

- **NEVER split index.html** into separate files
- **NEVER link to css/ or js/ folders** — they exist but are unused
- All edits go directly into index.html
- Gemini model is `gemini-2.5-flash` (not gemini-2.0-flash or gemini-2.0)
- PDF.js version is 3.11.174
- Tesseract.js version is v5
- After completing tasks: `git add . && git commit -m "description" && git push`
- Give fixes one at a time — user confirms each one works before moving to the next
- If a task runs longer than 5 minutes, press Ctrl+C and break into smaller steps
- Always read index.html before making edits — never work from memory
- A PASS in test.html does not mean the fix works in the app — always verify visually
- When a fix passes test.html but fails in app: diagnose first, then fix — never guess

---

## How to Start a New Claude Chat Session

**Standard opening message:**
> "Read PROJECT_CONTEXT.md and index.html. Confirm you understand the project before I give you any tasks."

**For PDF verification sessions:**
> "Read PROJECT_CONTEXT.md and index.html. I'm uploading psych_shelf_5_questions.pdf and psych_shelf_5_answers.pdf. Please help me verify the extraction works correctly."
> Then upload: psych_shelf_5_questions.pdf, psych_shelf_5_answers.pdf, index.html

**For bug fix sessions:**
> "Read PROJECT_CONTEXT.md and index.html. I want to fix the issues listed under 'Known Remaining Issues — Critical' in PROJECT_CONTEXT.md. Start with R1."

---

## Git History (recent)

```
[v9 commit pending] — 20 fixes: OCR A-K, phantom spaces 0.6, lab tables, figures, 
                      timers, sidebar collapse, font size, copy-paste, review mode, 
                      hint move, edit button removal
[v8 commit pending] — OCR v8: phantom space fix, Choice-A split fix, Tesseract fallback, Surgery PDF support
a960471  Hint Button Issue Fixed after Setting Gemini Cloud Billing with Prepaid 0 with no auto reload
77f5cca  Supabase Sync Error Fixed
b7bb556  Loads of edits done through Claude chat, particularly with PDF OCR v6
```

**Recommended commit command after next successful session:**
```
git add . && git commit -m "v9: 20 fixes applied, test.html added, PROJECT_CONTEXT updated" && git push
```

---

## Appendix: OCR v9 Key Functions (authoritative)

### `joinItems(items)` — font-size-relative phantom space fix (v9: threshold 0.6)

```javascript
function joinItems(items) {
  if (!items.length) return '';
  let result = items[0].str;
  for (let i = 1; i < items.length; i++) {
    const prev = items[i - 1];
    const curr = items[i];
    const prevWord = /[A-Za-z0-9]$/.test(result);
    const nextWord = /^[A-Za-z0-9]/.test(curr.str);
    if (!prevWord || !nextWord) { result += ' ' + curr.str; continue; }
    const fontSize    = prev.transform ? Math.abs(prev.transform[0]) : 10;
    const estCharW    = fontSize * 0.5;
    const prevX1_rep  = prev.x0 + Math.abs(prev.width || 0);
    const prevX1_est  = prev.x0 + (prev.str.length * estCharW);
    const gapRep      = curr.x0 - prevX1_rep;
    const gapEst      = curr.x0 - prevX1_est;
    const gap         = (Math.abs(prev.width || 0) < 0.1) ? gapEst : gapRep;
    const phantom     = gap < estCharW * 0.6;  // v9: raised from 0.4
    result += (phantom ? '' : ' ') + curr.str;
  }
  return result.trim();
}
// NOTE: raw items must include { x0, x1, y, str, width, transform } fields
```

### `parseOneQuestion(num, paragraphs)` — item boundary + flexible number format (v9: A–K)

```javascript
const OPT_RE    = /^(?:[0oOQ©®°]\s{0,3})?([A-Ka-k])\s{0,2}[)]\s{0,4}(.{2,})/;  // v9: A-K
const NEXT_Q_RE = /^(\d+)[.,]\s+\S/;
// Stem number prefix — handles period or comma after number
const nm = p.match(/^(\d+)[.,]\s+(.+)/);
// While in options, stop if a different question number appears
if (inOptions) {
  const nqm = p.match(NEXT_Q_RE);
  if (nqm && parseInt(nqm[1]) !== num) break;
}
```

### `parseOneAnswer(num, paragraphs)` — duplicate + split fix (v9: CA_RE expanded to A–K)

```javascript
// CA_RE — v9: expanded from A-H to A-K
const CA_RE = /correct\s+answer\s*[:\-.]\s*([A-Ka-k])(?:[.\s,]|$)/i;
// Use LAST "Correct Answer" occurrence (page 2 repeat)
const lastIdx = correctIndices[correctIndices.length - 1];

// Rejoin "(Choice\nA)" splits
for (let i = 0; i < unique.length; i++) {
  const cur = unique[i].trim();
  const next = unique[i+1] ? unique[i+1].trim() : null;
  if (next && /\(Choice\s*$/i.test(cur)) {
    rejoined.push(cur + ' ' + next); i++;
  } else {
    rejoined.push(cur);
  }
}
```

### `pdfHasTextLayer(pdf)` — auto-detect image vs vector PDF

```javascript
async function pdfHasTextLayer(pdf) {
  const sample = Math.min(3, pdf.numPages);
  let total = 0;
  for (let p = 1; p <= sample; p++) {
    const page = await pdf.getPage(p);
    const tc   = await page.getTextContent({ includeMarkedContent: false });
    total += tc.items.reduce((n, i) => n + (i.str || '').trim().length, 0);
  }
  return total > 50;
}
```

### `normalizeChars(text)` — artifact cleanup

```javascript
text.replace(/(\d)\s*\?\s*(\d)/g, '$1$2');          // "4 ? 7" → "47"
text.replace(/~\s*-\s*[Aa]drenergic/g, 'β-Adrenergic');
text.replace(/(\w)\s+'s\b/g, "$1's");               // "child 's" → "child's"
text.replace(/(\w)\s+'t\b/g, "$1't");               // "doesn 't" → "doesn't"
// + 're, 've, 'll variants
```
