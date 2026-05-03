# NBME Self-Assessment Suite — Project Context & Status

## Overview

A single-page HTML application for medical students to take NBME-style
practice tests. Runs entirely in the browser. Opens via index.html in Chrome.

**Live URL:** https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/
**GitHub Repo:** github.com/shamsulalamx/NBME-Self-Assessment-Suite (Public)
**User email:** shuvoli8@gmail.com

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Pure HTML, CSS, JavaScript, no frameworks |
| OCR | Tesseract.js v5, runs locally in browser |
| PDF rendering | PDF.js v3.11.174 |
| Storage primary | Browser localStorage |
| Session sync | Supabase, fully working |
| AI hints and tagging | Google Gemini API gemini-2.5-flash |
| Hosting | GitHub Pages |

---

## File Structure

```
NBME Self-Assessment Suite/
  index.html          <- entire app, single self-contained file
  css/                <- IGNORE, failed split attempt, not used
  js/                 <- IGNORE, failed split attempt, not used
  PROJECT_CONTEXT.md  <- this file
  README.md
```

CRITICAL: The entire app runs from index.html only.
Never split into separate files. A previous attempt broke the app.
Never link to the css/ or js/ folders.

---

## JavaScript Modules (all inlined in index.html)

| Module | Approx Lines | Description |
|---|---|---|
| DB | 1031-1256 | Storage layer, localStorage plus Supabase sync |
| OCR | 1257-1663 | NBME PDF extraction engine |
| Quiz | 1664-2218 | Test-taking engine, state, timers, navigation, modes |
| Results | 2219-2548 | Score report, analytics, review mode |
| App | 2549-3425 | Main controller, UI, routing, sidebar, modals |
| PIN | 3426-3572 | 4-digit passcode protection |
| Bootstrap | 3573+ | App initialization on DOMContentLoaded |

---

## Supabase Configuration

URL: https://lmxdedepkwmilnvjcxil.supabase.co
Key: sb_publishable_CVhmesK9VAUhAn-mMpQHYQ_yg2MMz9Q
Table: sessions with columns user_id text, data jsonb, updated_at timestamp
Status: Working. User sees a readable code like TIGER-4829 in the UI.

---

## Gemini API Configuration

Model: gemini-2.5-flash
Key stored in: localStorage under key "gemini_api_key"
Also synced to Supabase session data
Billing: Active, $10 prepaid credits loaded
Status: Working for hints. Auto-tagging unverified.

---

## Features Status Summary

| Feature | Status |
|---|---|
| 4-digit PIN screen | Working |
| UWorld sidebar with folders | Working |
| Home screen grid with progress | Working |
| Trash folder | Working |
| Import/Export buttons | Removed |
| Return to Dashboard button | Working |
| Timer counts up from 0 | Working but has glitch, needs fix |
| Auto yellow highlight | Working |
| Font size A+ A- buttons | Partially working, see issues |
| Calculator strip | Working |
| Lab Values panel | Working but has issues, see below |
| PDF extraction and OCR | MAJOR ISSUES, top priority |
| Explanation display | MAJOR ISSUES, top priority |
| Blue bar detection | Not working correctly |
| Image extraction from PDFs | Unverified |
| Navigation panel collapsible | Working but needs adjustments |
| Block time elapsed | Redundancy issue, needs fix |
| PDF report download | Working |
| AI Hints with Gemini | Working |
| AI auto-tagging | Unverified |
| Supabase session sync | Working |
| Google Drive sync | Removed and replaced by Supabase |

---

## PRIORITY 1 — MAJOR ISSUES (fix these first)

### Issue A: PDF Extraction is Severely Broken

The OCR pipeline has critical failures producing unusable question banks.
Observed problems:

- Only 4 questions extracted from a 50-question PDF
- Questions are in the wrong order
- Question text is garbled with heavy noise
- NBME UI elements appear inside question stems:
  time remaining, lab values, calculator, review, help, pause,
  previous, next, and other interface text
- Question stems contain answer circles and A) B) C) labels
  embedded within the stem text
- Some questions have only 1-2 sentences when the original
  has 8-9 sentences, meaning extraction is cutting off
- Answer choices are incomplete, sometimes only one choice shows
- Answer choices contain noise such as: ~=~ oOMm 0 ~~ previous
  next lab values calculator review help pause
- Some answer choices start at E) or F) instead of A)
- The app shows G) followed by G) instead of G) then H),
  indicating answer choices from the answer key section
  are being mixed with the original question choices
- The blue bar detection and cropping from Prompt 9 is
  not working correctly despite the blue bars being
  confirmed as identical shade across all pages

Root cause assessment:
The blue bar pixel detection is failing, meaning Tesseract
is OCR-ing the full page including all NBME UI chrome.
The noise filtering is insufficient because it runs after
OCR on text that was never cleanly extracted.

### Issue B: Explanation Display is Broken

After answering a question, the explanation section is
not displaying correctly. Needs investigation in new chat
session with PDF samples uploaded for visual inspection.

---

## PRIORITY 2 — FIXES NEEDED (after Priority 1 is resolved)

### Fix 1: Timer Glitch and Redundancy

Current state:
- There are two timers in the top panel
- One for current question, one for total test
- The question timer has a visual glitch where it jumps

Required changes:
- Keep only ONE timer in the top panel: the per-question timer
  counting up from 0:00, format mm:ss, turns yellow at 1:30,
  turns red and flashes at 2:00
- Remove the total test timer from the top panel entirely
- In the bottom control bar, show: Block Time Elapsed: mm:ss
  This is the total test elapsed time, renamed and relocated
- Fix the timer glitch so it increments smoothly every second

### Fix 2: Font Size Controls Not Working Correctly

Current state:
- The A+ and A- buttons zoom the entire page instead of
  changing only the font size

Required fix:
- A+ and A- must change ONLY the font size of:
  question stem text, answer choice text, explanation text
- Must NOT zoom or scale any other element on the page
- Must NOT affect: top bar, bottom bar, sidebar, buttons,
  navigation panel, or any UI chrome
- Target only the question content area font sizes
- Default 14px, range 12px to 20px, persists in localStorage

### Fix 3: Lab Values Spacing and Extra Data

Current state:
- Excessive vertical spacing between rows in the lab values panel
- App is showing extra lab values not in the provided data,
  meaning there are hallucinated or hardcoded extras

Required fix:
- Reduce vertical spacing between rows significantly so
  values appear compact and dense like a reference sheet
- Strictly use ONLY the lab values provided in the original
  Prompt 7 data. Remove any values not in that list.
- No additions, no extras, no hallucinations

### Fix 4: Navigation Panel Width and Sidebar Collapse

Current state:
- Navigation panel during test is too wide
- Left sidebar showing Home, All Flagged, Trash, Folders
  cannot be hidden or collapsed

Required fix:
- Reduce navigation panel width by approximately 30%
- Add a collapse/hide toggle for the main left sidebar
  so the user can hide it entirely during a test or
  when more screen space is needed
- The toggle should be a small arrow or button at the
  edge of the sidebar
- Collapsed state persists in localStorage

### Fix 5: Search Feature in Navigation Panel

Add a search box to the question navigation panel during a test.

Requirements:
- Search box appears at the top of the navigation panel
- User types a word or phrase
- App searches through: question stem text, answer choice
  text, and explanation text of all questions
- IMPORTANT: search results only show questions that have
  already been attempted and answered. Unanswered questions
  never appear in search results.
- Results show question number and a brief snippet
- Clicking a result navigates directly to that question
- Search is case-insensitive
- Clear button to reset the search

---

## How to Start a New Claude Code Session

1. Open Terminal: Cmd + Space, type Terminal, press Enter
2. Navigate to folder: type cd with a space, drag the
   NBME Self-Assessment Suite folder onto Terminal, press Enter
3. Start Claude Code: type claude and press Enter
4. First message every session:
   "Read PROJECT_CONTEXT.md and index.html.
   Confirm you understand the project before I give you any tasks."
5. Run one prompt at a time, test in Chrome after each one
6. After each working change:
   git add .
   git commit -m "describe what changed"
   git push

---

## How to Check Supabase is Working

Open the app in Chrome. Look in the top bar or settings panel
for a readable user code such as TIGER-4829. If you see it,
Supabase identity and sync are working. To verify cross-device
sync, open the app on a different device or browser, go to
settings, enter the same code, and your data should load.

---

## Important Notes for Claude Code

- Never split index.html into separate files
- Never attempt to move CSS or JS to external files
- The css/ and js/ folders exist but are not used, ignore them
- All edits go directly into index.html
- When asked to allow file access, always choose
  "Yes, allow all edits during this session"
- If a task runs longer than 5 minutes press Ctrl+C
  and break it into smaller steps
- Gemini model is gemini-2.5-flash, not gemini-2.0-flash
- After completing tasks run:
  git add . && git commit -m "description" && git push

---

## Next Steps

1. Start a new chat session and upload sample PDF pages
   and screenshots of broken extraction output so the
   OCR pipeline can be diagnosed visually and fixed properly

2. After OCR is fixed, verify explanation display

3. Then work through Priority 2 fixes one at a time
