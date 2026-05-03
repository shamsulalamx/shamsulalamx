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
| PDF text extraction | PDF.js v3.11.174 — `getTextContent()` (NOT OCR) |
| OCR library | Tesseract.js v5 — loaded but NOT used (was replaced) |
| Storage primary | Browser localStorage |
| Session sync | Supabase — fully working |
| AI hints + tagging | Google Gemini API `gemini-2.5-flash` |
| PDF report download | jsPDF 2.5.1 |
| Hosting | GitHub Pages |

---

## File Structure

```
NBME Self-Assessment Suite/
  index.html          ← entire app, single self-contained file (4440 lines)
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
| OCR | 1761–2189 | PDF extraction engine v7 (see full details below) |
| Quiz | 2252–2790 | Test-taking engine: state, timers, navigation, modes |
| Results | 2936–3488 | Score report, analytics, review mode |
| App | 3499–4162 | Main controller, UI, routing, sidebar, modals |
| PIN | 4163–4305 | 4-digit passcode protection |
| Bootstrap | 4306+ | App initialization on DOMContentLoaded |

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
| Font size A+ A- buttons | Partially working |
| Calculator strip | Working |
| Lab Values panel | Working |
| PDF extraction (OCR v7) | Mostly working — see known issues below |
| Explanation display | Working |
| Navigation panel collapsible | Working |
| PDF report download | Working |
| AI Hints with Gemini | Working |
| AI auto-tagging | Working |
| Supabase session sync | Working |

---

## OCR Engine — Current Version: v7

### Architecture

The app uses **PDF.js `getTextContent()`** (native vector text extraction), NOT Tesseract image OCR. NBME PDFs contain selectable text — OCR was causing all original noise issues and was replaced in v3.

### PDF Structure (NBME format)

Each question PDF page has:
- **Top chrome** (y > 700pt): `Exam Section: Item X of N`, `National Board of Medical Examiners`, `Time Remaining:`
- **Bottom chrome** (y < 48pt): `Previous`, `Next`, `Lab Values`, `Calculator`, `Review`, `Help`, `Pause`, plus glyph noise (`~ ~ , r ,`)
- **Content band** (48pt < y < 700pt): question stem + answer choices
- **Radio buttons**: separate text items at x < 80, rendered as `0` or `O` — filtered out

Each answer PDF page has:
- Same chrome bands
- Question stem (repeated from question PDF)
- Answer choices (repeated)
- `Correct Answer: X.` line
- Full explanation paragraphs (17pt line spacing within, 33pt gap between)
- Each answer item spans **2 PDF pages** — page 2 contains a full repeat of the explanation

### Key Constants (in OCR module)

```javascript
PAGE_HEIGHT      = 752   // pt — consistent across all NBME pages
TOP_CHROME_Y     = 700   // filter rows above this
BOTTOM_CHROME_Y  = 48    // filter rows below this
PARA_GAP_PT      = 25    // Y gap (pt) → paragraph break
PHANTOM_GAP_MAX  = 3.0   // gap < 3pt AND both word chars → phantom space
```

### Critical Regex Fixes

```javascript
// CORRECT — requires colon + single letter grade
CA_RE = /correct\s+answer\s*[:\-.]\s*([A-Ha-h])(?:[.\s,]|$)/i

// WHY: "Incorrect Answers: A, B, D" was falsely matching /correct\s+answer/i
// because "In-CORRECT ANSWER-s" contains both substrings.
// The CA_RE fix requires a single letter after the colon, so "Incorrect Answers: A, B"
// never matches (it has "s: A, B" not ": A" alone).
```

### Key Pipeline Functions

```
extractPdfText(file)        → pages[]  {pageNum, paragraphs[], itemNum, totalItems}
groupPagesByItem(pages)     → itemMap  {itemNum → paragraphs[]}
parseQuestionBank(itemMap)  → questions[]
parseAnswerKey(itemMap)     → answers{}
matchAndMerge(questions, answers) → matched[]
aiTagQuestions(matched)     → tags added in-place
processTestPDFs(qFile, aFile, onProgress) → matched[]  ← main entry point
```

### Phantom Space Fix

**Problem:** PDF ligature encoding splits words across text items with tiny gaps.  
Example: `"Catatonia"` → PDF.js emits `"Cataton"` item (x1=141.98) then `"ia"` item (x0=143.49).  
Gap = 1.51pt. Real word-space minimum = 3.36pt (Helvetica-Bold).

**Fix:** `PHANTOM_GAP_MAX = 3.0pt` — if gap < 3pt AND both sides are word chars → merge without space.  
Previous approach (median-based 60% threshold) failed because kerning-after-space gaps (1.4–2.2pt) polluted the median.

### Duplicate Explanation Fix

**Problem:** Each answer item spans 2 PDF pages. Page 2 REPEATS the entire explanation from `"Correct Answer: X."` onward. Old code merged both pages → double explanations.  
**Fix:** Use `lastIdx = correctIndices[correctIndices.length - 1]` — always use the last true "Correct Answer: X" occurrence. Take only `paragraphs[lastIdx + 1:]`.

### Item 8 Boundary Fix

**Problem:** Item 7's last choice E was on the same page as item 8's question text. The parser appended `"8.  A 62-year-old..."` to item 7's choice E as "continuation text".  
**Fix:** `NEXT_Q_RE = /^(\d+)\.\s+\S/` — while in options mode, if a line matches a DIFFERENT question number → stop immediately.

---

## Known Remaining Issues (as of last session)

### OCR / Extraction Issues

1. **49 questions extracted instead of 50** — Item 8 still missing from Psych Shelf 4 PDF. The `NEXT_Q_RE` fix was applied but not yet verified with a re-extraction. Item 8 uses extended matching (two-column answer choices).

2. **Trailing digits after some answer choices** — Radio button glyphs not fully filtered in all PDF layouts. Filter threshold is x < 80, may need widening further.

3. **Some phantom spaces still persist** — `PHANTOM_GAP_MAX = 3.0pt` should catch all cases (confirmed max phantom gap = 2.62pt, min real space = 3.36pt) but not yet re-verified against full PDF.

4. **Two-column answer layout edge cases** — Items like 8, 13, 16 with extended matching (8+ choices, two columns) sometimes have choices rendered out of order or merged. `splitMergedOptions()` handles most cases.

5. **"No questions found" error on new PDFs** — New PDFs with different structure (different item header format, different fonts, different question numbering scheme) return zero questions. **THIS IS THE CURRENT BLOCKER for the next session.** New PDFs need to be uploaded and analyzed before the OCR pipeline can be extended.

### UI Issues (lower priority)

6. **Timer has a visual glitch** — Two timers visible; Fix 1 from PROJECT_CONTEXT describes the intended fix (not yet done).

7. **Font size A+/A- zooms whole page** — Fix 2 from PROJECT_CONTEXT describes the intended fix (not yet done).

8. **Lab values spacing** — Fix 3 from PROJECT_CONTEXT (not yet done).

9. **Navigation panel width** — Fix 4 from PROJECT_CONTEXT (not yet done).

10. **Search in navigation panel** — Fix 5 from PROJECT_CONTEXT (not yet done).

---

## PRIORITY FOR NEXT SESSION

**Goal: Fix "No questions found" error for new PDFs**

The user is trying to upload a different questions PDF and answers PDF. The error means `parseQuestionBank()` returned zero items.

**Steps needed:**
1. Upload the new questions PDF and answers PDF to the chat
2. Run `pdfminer` analysis to extract all text items with positions (same analysis done for Psych Shelf 4)
3. Identify:
   - Does the header say `"Exam Section: Item X of N"` or something different?
   - Are item numbers in the same format?
   - Are Y coordinates similar (page height 752pt)?
   - Are answer choices formatted the same way?
4. Modify `extractPdfText()` / `parseOneQuestion()` as needed to handle the new format
5. The fix may be as simple as a different item-header regex, or may require more structural changes

**Key diagnostic command for new PDFs:**
```python
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextBox, LTTextLine

for pg_idx, page in enumerate(extract_pages('new_questions.pdf')):
    elements = []
    for elem in page:
        if isinstance(elem, LTTextBox):
            for line in elem:
                if isinstance(line, LTTextLine):
                    t = line.get_text().strip()
                    if t: elements.append((line.y0, line.x0, t))
    elements.sort(key=lambda e: -e[0])
    print(f"\n=== PAGE {pg_idx+1} ===")
    for y, x, t in elements:
        print(f"  y={y:7.1f} x={x:6.1f} | {repr(t[:100])}")
    if pg_idx >= 2: break  # just first 3 pages
```

---

## How to Start a New Claude Chat Session

**Standard opening message:**
> "Read PROJECT_CONTEXT.md and index.html. Confirm you understand the project before I give you any tasks."

**For the new PDF session:**
> "Read PROJECT_CONTEXT.md. I'm uploading new question and answer PDFs that return 'No questions found'. Please analyze their structure and fix the OCR pipeline to support them."
> Then upload: new questions PDF, new answers PDF, and index.html

---

## Important Rules for Claude

- **NEVER split index.html** into separate files
- **NEVER link to css/ or js/ folders** — they exist but are unused
- All edits go directly into index.html
- Gemini model is `gemini-2.5-flash` (not gemini-2.0-flash)
- PDF.js version is 3.11.174
- After completing tasks: `git add . && git commit -m "description" && git push`
- Run one prompt at a time, test in Chrome after each one
- If a task runs longer than 5 minutes, press Ctrl+C and break into smaller steps

---

## Git History (recent)

```
b7bb556  Loads of edits done through Claude chat, particularly with PDF OCR v6, more edits needed
a960471  Hint Button Issue Fixed after Setting Gemini Cloud Billing with Prepaid 0 with no auto reload
77f5cca  Supabase Sync Error Fixed
```

---

## Appendix: OCR Module v7 Key Functions (condensed)

### `joinItems(items)` — phantom space fix
```javascript
// gap < 3.0pt AND both sides word chars → no space (phantom merge)
// gap >= 3.0pt OR either side non-word → real space
const phantom = gap < PHANTOM_GAP_MAX && prevWord && nextWord;
result += (phantom ? '' : ' ') + items[i].str;
```

### `parseOneQuestion(num, paragraphs)` — item boundary fix
```javascript
const NEXT_Q_RE = /^(\d+)\.\s+\S/;
// While in options mode, if we see a different question number → stop
if (inOptions) {
    const nqm = p.match(NEXT_Q_RE);
    if (nqm && parseInt(nqm[1]) !== num) break;
}
```

### `parseOneAnswer(num, paragraphs)` — duplicate explanation fix
```javascript
// CA_RE won't match "Incorrect Answers: A, B..." — requires single letter after colon
const CA_RE = /correct\s+answer\s*[:\-.]\s*([A-Ha-h])(?:[.\s,]|$)/i;
// Use LAST true "Correct Answer: X" — that's the complete explanation page
const lastIdx = correctIndices[correctIndices.length - 1];
const expParas = paragraphs.slice(lastIdx + 1);
```

### `normalizeChars(text)` — artifact cleanup
```javascript
// Age artifact: "4 ? 7-year" → "47-year"
text.replace(/(\d)\s*\?\s*(\d)/g, '$1$2');
// Greek: "~-Adrenergic" → "β-Adrenergic"
text.replace(/~\s*-\s*[Aa]drenergic/g, 'β-Adrenergic');
```
