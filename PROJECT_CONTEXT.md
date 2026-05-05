# NBME Self-Assessment Suite — Project Context & Status

## Overview

A single-page HTML application for medical students to take NBME-style practice tests. Runs entirely in the browser. Opens via `index.html` in Chrome (local file, not served).

**Live URL:** https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/
**GitHub Repo:** github.com/shamsulalamx/NBME-Self-Assessment-Suite (Public)
**User email:** shuvoli8@gmail.com

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Pure HTML, CSS, JavaScript — no frameworks |
| PDF text extraction | PDF.js v3.11.174 — `getTextContent()` for vector PDFs |
| OCR fallback | Tesseract.js v5 — used for image-only PDFs |
| Storage primary | Browser localStorage |
| Figure images | IndexedDB via `FigureStore` module (base64 PNGs, kept out of localStorage) |
| Session sync | Supabase — fully working |
| AI hints + tagging | Google Gemini API `gemini-2.5-flash` |
| PDF report download | jsPDF 2.5.1 |
| Hosting | GitHub Pages |

---

## File Structure

```
NBME Self-Assessment Suite/
  index.html          ← entire app (~5270+ lines), single self-contained file
  PROJECT_CONTEXT.md  ← this file
  README.md
  css/                ← IGNORE — failed split attempt, not used
  js/                 ← IGNORE — failed split attempt, not used
```

**CRITICAL: Never split index.html into separate files. Never link to css/ or js/ folders.**

---

## JavaScript Modules (all inlined in index.html)

| Module | Description |
|---|---|
| DB | Storage layer: localStorage + Supabase sync. Manages tests, folders, flags, marks, history |
| FigureStore | IndexedDB wrapper for figure images (keeps large base64 out of localStorage) |
| Supabase Sync | Session sync, user code generation (readable codes like TIGER-4829) |
| OCR | PDF extraction engine: vector path (PDF.js) + image fallback (Tesseract) |
| buildStemHTML | Renders question stem: detects lab value tables, figures, plain paragraphs |
| Quiz | Test-taking engine: state, timers, navigation, mode switching |
| Results | Score report, analytics, review mode |
| App | Main controller, UI routing, sidebar, modals, folder management |
| Bootstrap | App initialization on DOMContentLoaded |

> Line numbers shift constantly. Always search by function name, not line number.

---

## Supabase Configuration

```
URL: https://lmxdedepkwmilnvjcxil.supabase.co
Key: sb_publishable_CVhmesK9VAUhAn-mMpQHYQ_yg2MMz9Q
Table: sessions — columns: user_id text, data jsonb, updated_at timestamp
Status: Working.
```

---

## Gemini API Configuration

```
Model: gemini-2.5-flash  ← exact string, never change
Key stored in: localStorage under key "gemini_api_key" (also synced to Supabase)
User key: AIzaSyCkUV9ZeRZxHdTRtraAAbiTGbWKvmKay5E
Status: Working for hints and AI auto-tagging.
Note: Gemini key is re-entered manually after localStorage clears.
```

---

## Features Status

| Feature | Status |
|---|---|
| PDF import — vector PDFs (NBME standard) | ✅ Working |
| PDF import — image-only PDFs (Tesseract) | ✅ Working (slow: ~3–8 min/50 pages) |
| Folder system (Psychiatry, Surgery, etc.) | ✅ Working |
| Home screen grid with test cards | ✅ Working |
| Trash folder with 7-day auto-purge | ✅ Working |
| Marked questions panel (sidebar) | ✅ Working |
| Flagged questions panel (sidebar) | ✅ Working |
| Quiz engine — tutor mode | ✅ Working |
| Quiz engine — exam mode | ✅ Working |
| Timer — per-question (center of topbar, no label) | ✅ Working |
| Timer — block elapsed (bottom bar) | ✅ Working |
| Font size A+/A- (question, choices, explanation) | ✅ Working |
| AI tags — shown only after answering | ✅ Working |
| Navigation panel scroll to Q50 | ✅ Working |
| Navigation panel width | ✅ 96px expanded / 36px collapsed |
| Left sidebar width | ✅ 180px |
| PIN screen | ✅ Removed — app opens directly |
| Lab value tables in question stems | ✅ Working |
| Answer choice option parsing A–K | ✅ Working |
| Question number stripping (31., 39.) | ✅ Working |
| Option parsing — temperature splits (°F) | ✅ Working |
| Option parsing — lb) splits | ✅ Working |
| Option parsing — mm Hg) splits | ✅ Working |
| Option parsing — trailing option label (Q35 F/G) | ✅ Working |
| False figure detection (CT scan, X-ray refs) | ✅ Working |
| Figure rendering — content band crop | ✅ Working |
| Figure storage — IndexedDB (not localStorage) | ✅ Working |
| AI tagging on import | ✅ Working (requires Gemini key before import) |
| localStorage storage management | ✅ Working (history cap 3/test, auto-purge trash) |
| Marks persisted to DB | ✅ Working |
| Supabase sync includes marks | ✅ Working |
| Copy/paste from question text | ✅ Working |
| Review mode | ✅ Working |
| PDF report download | ✅ Working |
| AI Hints with Gemini | ✅ Working |
| Phantom spaces — within-item | ⚠️ Substantially improved, may still have edge cases |
| Missing spaces between words — cross-item | ⚠️ Substantially improved, may still have edge cases |
| Search in navigation panel | ❌ Not implemented |

---

## Known Issues — Remaining

### 1. Phantom Spaces & Missing Spaces — SUBSTANTIALLY REWORKED

**Status:** Multiple rounds of fixes applied this session. Architecture is now correct. Edge cases may remain depending on which specific NBME PDFs are imported.

**Root cause — two distinct bugs:**

**Bug A — Phantom spaces baked into `item.str`:** PDF.js returns individual text items with phantom spaces embedded inside them due to font ligature encoding artifacts in NBME PDFs (e.g. `"seroton in"` instead of `"serotonin"`, `"fat ig ue"` instead of `"fatigue"`). These spaces are not gaps between items — they are literally inside the string.

**Bug B — Missing spaces between words:** When `joinItems()` assembles items from a PDF line, gap geometry (`prev.width`) was used to decide whether to insert a space. NBME font advance widths are unreliable in PDF coordinate space, so real inter-word gaps were being measured as near-zero and eliminated (`"physicianby"`, `"Mostofthe"`).

**Current implementation — `fixLigatureSpaces()` and `joinItems()`:**

`joinItems()` now **always inserts a space** between items. All phantom space removal is delegated entirely to `fixLigatureSpaces()`.

`fixLigatureSpaces()` uses a **token-based dictionary approach**:
1. **Pass 1a/1b** — single-letter phantom fixes. Any lone letter (other than `a`, `i`, `I`, `B`/`T` before cell/lymph) before a lowercase word is merged: `"w ith"` → `"with"`, `"A lzheimer"` → `"Alzheimer"`.
2. **Pass 2 — token accumulator** — split the string on spaces into tokens. Accumulate tokens that are *not* in `_REAL_WORDS` (the dictionary) into a buffer. Flush the buffer as one merged word when a real dictionary word is hit. Bound suffixes (`ing`, `tion`, `ly`, `er`, etc.) always attach to whatever precedes them. Forward-merge check handles cases like `"seroton"` + `"in"` = `"serotonin"` (found in dictionary) vs `"malformations"` + `"in"` staying separate (not in dictionary as a compound).

**`_REAL_WORDS` dictionary** covers ~500+ English and medical terms. It is the single source of truth for what constitutes a real word boundary. To fix any new phantom space that slips through, add the correct merged form to `_REAL_WORDS` — no regex logic needs to change.

**`_BOUND_SUFFIXES`** regex covers: `ing`, `ings`, `ied`, `ies`, `tion`, `tions`, `sion`, `sions`, `ment`, `ments`, `ness`, `nesses`, `ful`, `less`, `ance`, `ances`, `ence`, `ences`, `ity`, `ities`, `ive`, `ives`, `ify`, `ic`, `ics`, `ize`, `ized`, `izes`, `ise`, `ised`, `ises`, `ly`, `er`, `ers`, `est`, `en`, `ens`.

**Confirmed fixed cases (this session):**
- `"Prog ression"` → `"Progression"`
- `"A lzheimer"` → `"Alzheimer"`
- `"Wh ich"` → `"Which"`
- `"cogn itive"` → `"cognitive"`
- `"Wern icke"` → `"Wernicke"`
- `"standard ized"` → `"standardized"`
- `"testi ng"` → `"testing"`
- `"letharg ic"` → `"lethargic"`
- `"paramed ics"` → `"paramedics"`
- `"admin istered"` → `"administered"`
- `"exam ination"` → `"examination"`
- `"reg ularly"` → `"regularly"`
- `"reg istered"` → `"registered"`
- `"fam ily"` → `"family"`
- `"seroton in"` → `"serotonin"`
- `"w ith"` → `"with"`, `"w ife"` → `"wife"`
- `"pu lse"` → `"pulse"`
- `"try ing"` → `"trying"`, `"work ing"` → `"working"`
- `"extrem ities"` → `"extremities"`
- `"independent ly"` → `"independently"`
- `"fat ig ue"` → `"fatigue"` (multi-fragment)
- `"U ri na ry"` → `"Urinary"` (multi-fragment)
- `"duri ng"` → `"during"`, `"the fi rst"` → `"the first"`
- `"3 ho u rs"` → `"3 hours"`
- `"week ly"` → `"weekly"`
- `"reg imen"` → `"regimen"`
- `"intersec ti ng"` → `"intersecting"`
- `"thoug hts"` → `"thoughts"`

**Confirmed false positives protected (real spaces preserved):**
- `"malformations in children"` — stays separate
- `"given to patients"` — stays separate
- `"found in the liver"` — stays separate
- `"known risk factors include"` — stays separate
- `"physician by his parents"` — stays separate
- `"incontinence secondary to"` — stays separate

**If new phantom cases are found:** Add the correctly-merged word to `_REAL_WORDS`. Search by function name `fixLigatureSpaces` to locate it.

---

### 2. Lab Table Rendering — Working

- **Q5 (Na+, Cl-, etc.):** ✅ Shows as 2-column table
- **Q5 (Ca2+, Urea nitrogen, Creatinine):** ✅ Handles multi-lab paragraphs and spaced units (`mg/ dL`)
- **Q28 (Leukocyte count):** ✅ "with a normal differential" appears in value cell
- **Q28 (Na+):** ✅ "Serum" prefix stripped
- **Remaining:** Some OCR artifacts may still produce incorrect lab names (e.g. `cI` for `Cl-`). The `_cleanLabName()` function handles `cI` → `Cl-` specifically.

---

### 3. Figure Rendering — Working

When a question references `"Figure 1"`, `"Fig. 2"`, or `"shown below"`, the page is rendered at 2× scale and cropped to the content band (strips top/bottom NBME chrome). The cropped image is stored in IndexedDB.

**Detection regex:**
```javascript
const _FIGURE_RE = /\b(figure|fig\.?)\s*\d+\b/i;
const _FIGURE_KW = /\bshown\s+(?:below|above|in\s+(?:the\s+)?(?:figure|image)\s*\d*)/i;
```

**Known limitation:** Q48 (intersecting pentagons) — vector drawings, not bitmap images. The operator-list approach was tried and reverted. Current behavior shows the full content band including question text alongside the figure, which is acceptable.

---

### 4. Search in Navigation Panel — Not Implemented

No search/filter within the quiz navigation panel. Low priority.

---

## OCR Engine — Architecture

### Two Paths

1. **Vector PDF path** (fast): PDF.js `getTextContent()` — used when PDF has a real text layer (>50 chars in first 3 pages). All standard NBME Shelf PDFs use this path.
2. **Image-only PDF path** (slow): Tesseract.js v5 — used when no text layer found. ~3–8 min for 50 pages.

### PDF Format — NBME Standard (vector)

Each question PDF page:
- **Top chrome** (y > TOP_CHROME_Y): exam header, item counter, timer
- **Bottom chrome** (y < BOTTOM_CHROME_Y): navigation buttons, URL watermark
- **Content band**: question stem + answer choices
- **Radio buttons**: `0`/`O` glyphs at x < 80pt — filtered out

### Key Constants

```javascript
PAGE_HEIGHT      = 752    // pt — NBME vector PDF standard page height
TOP_CHROME_Y     = 700    // filter items above this Y (pt)
BOTTOM_CHROME_Y  = 48     // filter items below this Y (pt)
PARA_GAP_PT      = 25     // Y gap (pt) → new paragraph
SNAP_THRESHOLD   = 12     // pt — snap-to-nearest-line for normal items
SNAP_SUPERSCRIPT = 18     // pt — snap threshold for superscript chars (°, ², ³)
```

### Key Pipeline Functions

```
extractPdfText(file)
  → for each page:
      collect raw items (filtered by Y, radio buttons filtered)
      apply fixLigatureSpaces() to each item.str        ← phantom space fix
      snap items to lines (snap-to-nearest, 12pt threshold)
      joinItems() per line                              ← always joins with space
      group lines into paragraphs (PARA_GAP_PT gap)
      splitMergedOptions() per paragraph (handles two-column layouts)
      splitLabValues() per paragraph (splits run-on lab value strings)
      normalizeChars() cleanup
      detect figure references → render content band → store in figureMap

groupPagesByItem(pages) → { merged, figureMap }

parseQuestionBank(itemMap) → questions[]
  → parseOneQuestion(num, paragraphs) per item:
      strip question number prefix (handles "31 ." with space before period)
      identify options via OPT_RE (A-K)
      stop at NEXT_Q_RE or hard stops
      fix trailing option label (Q35 two-column F/G issue)

parseAnswerKey(itemMap) → answerMap
  → parseOneAnswer(num, paragraphs) per item

matchAndMerge(questions, answerMap) → matched[]

processTestPDFs(qFile, aFile, onProgress)
  → attach figureMap to matched questions (figureKey stored, dataUrl → IndexedDB)
  → AI tag questions (or mark Untagged if no key)
```

### Critical Regex Patterns (authoritative)

```javascript
// Option detection — A through K, handles radio button prefix glyphs
// IMPORTANT: text after ) must start with [A-Za-z0-9] to prevent °F) false matches
OPT_RE = /^(?:[0oOQ©®°]\s{0,3})?([A-Ka-k])\s{0,2}[)]\s{0,4}([A-Za-z0-9].+)/

// Question number prefix — allows space before period/comma ("31 ." pattern)
/^(\d+)\s*[.,]\s*(.+)/

// Correct answer
CA_RE = /correct\s+answer\s*[:\-.]\s*([A-Ka-k])(?:[.\s,]|$)/i

// Next question boundary (stops option parsing)
NEXT_Q_RE = /^(\d+)[.,]\s+\S/

// Figure detection (conservative — avoids false positives on clinical procedure mentions)
_FIGURE_RE = /\b(figure|fig\.?)\s*\d+\b/i
_FIGURE_KW = /\bshown\s+(?:below|above|in\s+(?:the\s+)?(?:figure|image)\s*\d*)/i
```

### splitMergedOptions — Temperature/Unit Protection

Prevents splitting at medical unit patterns that end with option-like letters:
- `°F)` / `°C)` — temperature
- `lb)` — weight in pounds (`b)` looks like option B)
- `mm Hg)` — blood pressure (`g)` looks like option G)

Implemented via lookahead in zero-space insertion step + forward-merge loop in step 3.

---

## UI State (Current)

| Element | Current Value |
|---|---|
| Left sidebar width | 180px (via `--sidebar-w` CSS variable) |
| Quiz nav panel width | 96px (expanded) / 36px (collapsed) |
| Quiz content area max-width | 1000px, side padding 40px |
| Quiz topbar layout | 3-column: left (name/item/score), center (Q timer), right (buttons) |
| AI tags | Hidden until question answered, then revealed |
| Font size | User-adjustable via A+/A- (10–22px, stored in localStorage) |
| PIN screen | Removed — app opens directly |

---

## DB Schema (localStorage key: `nbme_app_v1`)

```javascript
{
  version: 1,
  settings: { geminiApiKey, googleClientId, googleAccessToken, ... },
  folders: [{ id, name, createdAt, order }],
  tests: [{
    id, folderId, name, status, attempts, currentAttempt,
    questions: [{
      n,           // question number
      t,           // stem text (paragraphs joined by \n\n)
      o,           // options array [{ l, t }]
      c,           // correct letter
      explanation,
      tags,
      images,      // [{ figureKey, isLabTable }] — figureKey references IndexedDB
      _figureData  // TRANSIENT only — stripped before localStorage save
    }]
  }],
  trash: [{ ...test, deletedAt }],
  flags: [{ id, testId, questionId, createdAt }],
  marks: [{ id, testId, questionIdx, questionNum, createdAt }],
  history: [{
    id, testId, attemptNum, date, mode, score, total, totSecs,
    results: [{ answered, correct, chosen, time, strikethrough }]
    // highlights stripped before save (too large)
  }]
}
```

### Storage Safety Rules
- History capped at **3 attempts per test** (older entries auto-dropped on save)
- Trash auto-purged after **7 days**
- Figure images stored in **IndexedDB** (not localStorage) — no size limit issues
- `highlights` (yellow highlight HTML) stored **in-memory only** — not persisted
- On `QuotaExceededError`: history cleared first, tests preserved; if still fails, clear toast shown

---

## Marked Questions Feature

Marks are separate from Flags:
- **Flags** (`🚩`): persistent across sessions, shown in "All Flagged" sidebar panel
- **Marks** (`📌`): persistent (stored in `db.marks[]`), shown in "Marked" sidebar panel (`🔖`)

**Marked panel behavior:**
- Groups marked questions by folder as collapsible accordion sections
- Shows question number, test name, first 220 chars of stem, "Remove Mark" button
- Marks sync to Supabase with the rest of the session data

**Mark persistence:**
- Toggled immediately to DB via `DB.addMark()` / `DB.removeMark()`
- Also synced via `DB.syncMarks(testId, marksSet)` when test finishes
- Restored from `currentAttempt.marks` when resuming in-progress test

---

## How to Start a New Claude Session

**Standard opening:**
> "Read PROJECT_CONTEXT.md and index.html. Confirm you understand the project before I give you any tasks."

Upload both files.

**For phantom space / OCR work:**
> "Read PROJECT_CONTEXT.md and index.html. The phantom space fix uses a token-based dictionary approach in `fixLigatureSpaces()`. The dictionary is `_REAL_WORDS`. `joinItems()` always inserts spaces — all phantom removal is done by `fixLigatureSpaces()`. If new phantom cases appear, add the correct merged word to `_REAL_WORDS`."

---

## Important Rules for Claude

- **NEVER split index.html** into separate files
- **NEVER link to css/ or js/ folders** — they exist but are unused
- All edits go directly into index.html
- Gemini model string is exactly `gemini-2.5-flash`
- PDF.js version is 3.11.174, Tesseract.js is v5
- Always read index.html before editing — never work from memory
- Fix one thing at a time, confirm it works before moving on
- When introducing a fix, test it doesn't break existing working behavior
- If a fix causes a regression, fix the regression before moving on
- The user is a medical student — changes to question parsing affect exam preparation directly
- To extend the phantom space fix: add words to `_REAL_WORDS` in `fixLigatureSpaces()` — do not touch the token logic

---

## Git History (recent)

```
[This session — unpublished]
  - Phantom space fix: replaced bigram approach with token-based dictionary (_REAL_WORDS)
  - Missing spaces fix: joinItems() now always inserts spaces; gap math removed
  - fixLigatureSpaces() handles all phantom removal via dictionary lookup
  - _BOUND_SUFFIXES handles ing/tion/ly/er etc. attaching to prior token
  - Forward-merge check: buf+tok lookup in _REAL_WORDS (handles seroton+in=serotonin)
  - 53 test cases passing (phantom merges + false positive protection)

[Previous session — unpublished]
  - Storage fixes, marked panel, OCR improvements, UI polish
  - Font size A+/A-, AI tags hidden until answered, nav panel scroll fix
  - Navigation panel width 96px, sidebar 180px, PIN screen removed
  - Lab value table rendering substantially fixed
  - Marks persisted to DB and synced to Supabase

[v9 commit] — 20 fixes: OCR A-K, phantom spaces 0.6, lab tables, figures, timers,
               sidebar collapse, font size, copy-paste, review mode, hint move,
               edit button removal
[v8] — OCR v8: phantom space fix, Choice-A split fix, Tesseract fallback, Surgery PDF
a960471  Hint Button Issue Fixed after Setting Gemini Cloud Billing
77f5cca  Supabase Sync Error Fixed
b7bb556  Loads of edits done through Claude chat, particularly with PDF OCR v6
```

**Recommended commit:**
```
git add . && git commit -m "Session: dictionary-based phantom space fix, joinItems always-space, 53 tests passing" && git push
```
