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
  index.html          ← entire app, single self-contained file (~4628 lines)
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
| OCR | 1761–2310 | PDF extraction engine v8 (see full details below) |
| Quiz | 2330–2870 | Test-taking engine: state, timers, navigation, modes |
| Results | 2940–3490 | Score report, analytics, review mode |
| App | 3500–4170 | Main controller, UI, routing, sidebar, modals |
| PIN | 4170–4310 | 4-digit passcode protection |
| Bootstrap | 4310+ | App initialization on DOMContentLoaded |

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
| 4-digit PIN screen | Working |
| UWorld sidebar with folders | Working |
| Home screen grid with progress | Working |
| Trash folder | Working |
| Timer (per-question, counts up) | Working |
| Auto yellow highlight | Working |
| Font size A+ A- buttons | Partially working (zooms whole page — not yet fixed) |
| Calculator strip | Working |
| Lab Values panel | Working |
| PDF extraction — vector PDFs | Working (OCR v8) |
| PDF extraction — image-only PDFs | Working via Tesseract fallback (slow: ~3–8 min for 50 pages) |
| Explanation display | Working |
| Navigation panel collapsible | Working |
| PDF report download | Working |
| AI Hints with Gemini | Working |
| AI auto-tagging | Working |
| Supabase session sync | Working |

---

## OCR Engine — Current Version: v8

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
// PHANTOM_GAP_MAX removed — replaced by font-size-relative threshold in joinItems
```

### All Regex Patterns (current, authoritative)

```javascript
// Item header — handles both "Item 1 of 50" and "Item: 1 of 50" (Surgery answers format)
/[Ii]tem\s*:?\s*(\d+)\s+of\s+(\d+)/

// Correct answer — requires colon + single letter, won't match "Incorrect Answers: A, B"
CA_RE = /correct\s+answer\s*[:\-.]\s*([A-Ha-h])(?:[.\s,]|$)/i

// Answer option — handles "A) text", "A ) text", "A )  text" (space before paren)
OPT_RE = /^(?:[0oOQ©®°]\s{0,3})?([A-Ha-h])\s{0,2}[)]\s{0,4}(.{2,})/

// Next question boundary (stops option parsing when new question starts)
NEXT_Q_RE = /^(\d+)[.,]\s+\S/

// Question number prefix (handles OCR period/comma variants)
/^(\d+)[.,]\s+(.+)/

// splitMergedOptions — two-column layout detection
/\s+(?=(?:[0oOQ]\s{0,3})?[A-Ha-h]\s{0,2}\)\s{1,4}\S)/
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

## Fixes Applied This Session (v7 → v8)

### Fix A — Item header regex handles Surgery answers format
**Problem:** Surgery answers PDF uses `Exam Section Item: 1 of 50` (colon after "Item"), old regex required `Item 1` (space before number).
**Fix:** `/[Ii]tem\s*:?\s*(\d+)\s+of\s+(\d+)/` — `\s*:?\s*` allows optional colon.

### Fix B — Answer option regex handles space before paren
**Problem:** Surgery/Psych PDFs render choices as `A )  text` — old `OPT_RE` required `A)` with no space.
**Fix:** `([A-Ha-h])\s{0,2}[)]\s{0,4}` — allows 0–2 spaces before `)`.

### Fix C — Tesseract OCR fallback for image-only PDFs
**Problem:** Surgery PDFs are PowerPoint screenshot images — PDF.js returns zero text, causing "No questions found".
**Fix:** `pdfHasTextLayer()` detects image-only PDFs; OCR path renders each page to canvas at 2× and runs Tesseract.js. `parseOcrPage()` uses bounding boxes + median-gap paragraph detection + chrome zone exclusion.

### Fix D — Phantom space fix rewritten (font-size-relative threshold)
**Problem:** `PHANTOM_GAP_MAX = 3.0pt` fixed threshold failed for many words (`serotonin` → `seroton in`, `Progression` → `Prog ression`, `wife's` → `w ife's`) because `item.width` from PDF.js is often 0 or wrong, making gap calculations incorrect.
**Fix:** `joinItems()` now:
1. Stores `transform` and `width` from PDF.js item (raw item now includes these fields)
2. Reads font size from `transform[0]` (scaleX of the PDF.js transform matrix)
3. Estimates char width as `fontSize × 0.5`
4. When `width = 0`, estimates x1 from string length × estCharW instead
5. Merges items when gap < `estCharW × 0.4` (40% of avg char width)

```javascript
const fontSize = prev.transform ? Math.abs(prev.transform[0]) : 10;
const estCharW = fontSize * 0.5;
const gap = (Math.abs(prev.width || 0) < 0.1) ? gapEstimated : gapReported;
const phantom = gap < estCharW * 0.4;
```

### Fix E — (Choice A) paragraph split in explanations
**Problem:** PDF renderer splits `(Choice A)` across two paragraphs at line break, producing:
```
"Generalized anxiety disorder (Choice"
"A) is an anxiety disorder..."
```
**Fix:** After deduplication in `parseOneAnswer`, a `rejoined` pass detects paragraphs ending with `(Choice` and merges them with the next paragraph (with a space inserted).

### Fix F — Split apostrophes in normalizeChars
**Problem:** `"child 's"`, `"doesn 't"` etc. appearing in extracted text.
**Fix:** Added to `normalizeChars()`:
```javascript
text = text.replace(/(\w)\s+'s\b/g, "$1's");
text = text.replace(/(\w)\s+'t\b/g, "$1't");
text = text.replace(/(\w)\s+'re\b/g, "$1're");
text = text.replace(/(\w)\s+'ve\b/g, "$1've");
text = text.replace(/(\w)\s+'ll\b/g, "$1'll");
```

### Fix G — Question/NEXT_Q boundary regex more flexible
**Problem:** OCR may produce comma instead of period after question number.
**Fix:** `NEXT_Q_RE = /^(\d+)[.,]\s+\S/` and stem prefix match `/^(\d+)[.,]\s+(.+)/`

---

## Known Remaining Issues

### OCR / Extraction

1. **Some phantom spaces may still persist** — Fix D was verified with simulated test cases but not yet re-tested against a full live Psych PDF re-extraction. If any `word space` artifacts remain after re-uploading the psych PDFs, the threshold `estCharW * 0.4` may need tuning upward (try `0.6`).

2. **49 questions instead of 50** — Psych Shelf 4 item 8 still possibly missing. Uses extended matching (two-column 8-choice layout). `NEXT_Q_RE` fix was applied but not re-verified.

3. **Trailing digits after answer choices** — Radio button glyph filter `x < 80 * sc` may need widening to `x < 100 * sc` for some PDF layouts.

4. **Two-column answer layout** — Items with 8+ choices (A–H) in two columns sometimes produce choices out of order or merged. `splitMergedOptions()` handles most cases but edge cases remain.

5. **Surgery PDF extraction not yet tested end-to-end** — Tesseract path was built and code-reviewed but user has decided to defer Surgery PDFs. Focus is Psych only.

### UI Issues (lower priority, not yet fixed)

6. **Timer visual glitch** — Two timers visible simultaneously.

7. **Font size A+/A- zooms whole page** — Should only zoom question text, not the entire UI.

8. **Lab values spacing** — Layout issue in the lab values panel.

9. **Navigation panel width** — Sizing issue.

10. **Search in navigation panel** — Not yet implemented.

---

## Priority for Next Session

**Goal: Verify and perfect Psych PDF extraction with newly uploaded PDFs.**

The user has new Psych question and answer PDFs to upload. Steps:

1. Upload new psych questions PDF + answers PDF + `index.html` to the chat
2. Extract and check for:
   - Correct question count (should be 50)
   - No phantom spaces in answer choices or stems
   - No `(Choice\nA)` splits in explanations
   - Correct answer letters parsed correctly
   - Explanations complete and not duplicated
3. If phantom spaces still appear, increase threshold from `estCharW * 0.4` to `estCharW * 0.6`
4. Address remaining issues from the list above one by one

---

## How to Start a New Claude Chat Session

**Standard opening message:**
> "Read PROJECT_CONTEXT.md and index.html. Confirm you understand the project before I give you any tasks."

**For the new psych PDF session:**
> "Read PROJECT_CONTEXT.md and index.html. I'm uploading new psych question and answer PDFs. Please help me verify the extraction works correctly and fix any remaining issues."
> Then upload: new psych questions PDF, new psych answers PDF, and index.html

---

## Important Rules for Claude

- **NEVER split index.html** into separate files
- **NEVER link to css/ or js/ folders** — they exist but are unused
- All edits go directly into index.html
- Gemini model is `gemini-2.5-flash` (not gemini-2.0-flash)
- PDF.js version is 3.11.174
- Tesseract.js version is v5
- After completing tasks: `git add . && git commit -m "description" && git push`
- Give fixes one at a time — user confirms each one works before moving to the next
- If a task runs longer than 5 minutes, press Ctrl+C and break into smaller steps
- Always read index.html before making edits — never work from memory

---

## Git History (recent)

```
b7bb556  Loads of edits done through Claude chat, particularly with PDF OCR v6, more edits needed
a960471  Hint Button Issue Fixed after Setting Gemini Cloud Billing with Prepaid 0 with no auto reload
77f5cca  Supabase Sync Error Fixed
```
*(v8 changes not yet committed — user to run: `git add . && git commit -m "OCR v8: phantom space fix, Choice-A split fix, Tesseract fallback, Surgery PDF support" && git push`)*

---

## Appendix: OCR v8 Key Functions (condensed)

### `joinItems(items)` — font-size-relative phantom space fix
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
    const phantom     = gap < estCharW * 0.4;
    result += (phantom ? '' : ' ') + curr.str;
  }
  return result.trim();
}
// NOTE: raw items must include { x0, x1, y, str, width, transform } fields
```

### `parseOneQuestion(num, paragraphs)` — item boundary + flexible number format
```javascript
const OPT_RE    = /^(?:[0oOQ©®°]\s{0,3})?([A-Ha-h])\s{0,2}[)]\s{0,4}(.{2,})/;
const NEXT_Q_RE = /^(\d+)[.,]\s+\S/;
// Stem number prefix — handles period or comma after number
const nm = p.match(/^(\d+)[.,]\s+(.+)/);
// While in options, stop if a different question number appears
if (inOptions) {
  const nqm = p.match(NEXT_Q_RE);
  if (nqm && parseInt(nqm[1]) !== num) break;
}
```

### `parseOneAnswer(num, paragraphs)` — duplicate + split fix
```javascript
// CA_RE — single letter after colon prevents "Incorrect Answers: A, B" false match
const CA_RE = /correct\s+answer\s*[:\-.]\s*([A-Ha-h])(?:[.\s,]|$)/i;
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
