# NBME Self-Assessment Suite — Project Context & Status

## Overview

A single-page HTML application for medical students to take NBME-style
practice tests. Runs entirely in the browser with no backend except
Supabase for session sync. Opens via index.html in Chrome.

**Live URL:** https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/
**GitHub Repo:** github.com/shamsulalamx/NBME-Self-Assessment-Suite (Public)
**User email:** shuvoli8@gmail.com

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Pure HTML, CSS, JavaScript (no frameworks) |
| OCR | Tesseract.js v5 (runs locally in browser) |
| PDF rendering | PDF.js v3.11.174 |
| Storage primary | Browser localStorage |
| Session sync | Supabase (replacing Google Drive) |
| AI hints and tagging | Google Gemini API gemini-2.0-flash |
| Hosting | GitHub Pages |

---

## File Structure

The app is a single self-contained file. Everything runs from index.html.

```
NBME Self-Assessment Suite/
  index.html          <- entire app, ~160KB, ~3613 lines
  css/                <- IGNORE, failed split attempt, not used
  js/                 <- IGNORE, failed split attempt, not used
  PROJECT_CONTEXT.md  <- this file
  README.md
```

CRITICAL: The css/ and js/ folders are not used. Never link to them.
Never attempt to split index.html into separate files. A previous
attempt broke the app completely and had to be reverted.

---

## JavaScript Modules (all inlined in index.html)

| Module | Approx Lines | Description |
|---|---|---|
| DB | 1031-1256 | Storage layer, localStorage plus Google Drive being replaced |
| OCR | 1257-1663 | NBME PDF extraction engine |
| Quiz | 1664-2218 | Test-taking engine, state, timers, navigation, modes |
| Results | 2219-2548 | Score report, analytics, review mode |
| App | 2549-3425 | Main controller, UI, routing, sidebar, modals |
| PIN | 3426-3572 | 4-digit passcode protection |
| Bootstrap | 3573+ | App initialization on DOMContentLoaded |

---

## Features Built and Working

### Authentication
- 4-digit PIN screen on every load
- Set on first launch, no recovery option
- Stored in localStorage

### Navigation and Structure
- UWorld-style sidebar with manually created folders
- Home screen grid with progress indicators showing Not Started,
  In Progress with question number, Completed with percentage
- Folders and test names are renameable
- Trash folder holds deleted tests indefinitely until manually emptied
- Multiple attempts saved separately in history

### Test Generation OCR Pipeline
- Generate Test button, upload Questions PDF and Answers PDF
- Tesseract.js OCR runs locally in browser, free, no API needed
- Uses "Exam Section: Item X of 50" NBME header as primary
  question number anchor
- Multi-page merging: pages with no item header are appended
  to the previous question's explanation block
- Noise filter strips NBME UI elements, URLs, navigation text
- Fuzzy matching pairs questions to answers even if order differs
- Auto-tags questions by topic using hardcoded keywords,
  being replaced with Gemini AI tagging in Prompt 14
- Edit Question available at all times: library, during test,
  during review

### Test Interface
- Tutor and Exam mode toggle available any time mid-test
- Switching Exam to Tutor: shows explanation for current question
- Switching Tutor to Exam: hides explanations on revisited questions
- 90-second informational timer, no auto-skip
- Answer selection: click the circle, dot, or letter only
- Strikethrough: click the answer text body, not the circle
- Text highlighting: yellow auto-applied on text selection,
  persists per question
- Mark and flag questions during test
- Pause always prompts Resume or Restart on reopen
- Question navigation grid showing right and wrong in real time
- Previous and Next buttons plus keyboard shortcuts

### Keyboard Shortcuts
| Key | Action |
|---|---|
| A B C D E | Select answer choice |
| Right arrow or Enter | Next question |
| Left arrow | Previous question |
| P | Pause test |
| F | Flag question |
| M | Mark question |

### After Test
- Score report with topic analytics and strengths and weaknesses
- Flagged Questions tab per folder showing question, last answer,
  full explanation, and which test it came from
- Full question-by-question review in order, both modes
- Post-test flagging available during review
- Multiple attempts saved separately in history

---

## Known Issues

| Issue | Status | Fix |
|---|---|---|
| Question ordering sometimes wrong | Partially fixed | Prompt 9 smart pixel detection |
| Explanation parsing incomplete | To be fixed | Prompt 8 single text block |
| NBME UI noise in extracted text | Partially fixed | Prompt 9 pixel detection and dedup |
| Multi-page overlap duplication | To be fixed | Prompt 9 deduplication |
| Google Drive sync | Being replaced | Prompt 15 Supabase |
| Hardcoded psychiatry tags only | To be fixed | Prompt 14 Gemini tagging |
| css/ and js/ folders unused | Known | Ignore entirely |

---

## Pending Prompts — Run in This Exact Order

Run one prompt at a time. Wait for Claude Code to finish.
Test in Chrome after each one before continuing.

---

## PROMPT 0 — Light Blue Color Theme

```
In index.html, update the color scheme from dark navy to a
lighter professional blue theme. Only change CSS color values.
Do not touch any JavaScript or HTML structure.

Replace these CSS variable values in the :root block:
--navy:     #1a3a5c  to  #1a6fba
--blue:     #1e5799  to  #2980d9
--ltblue:   #2980b9  to  #4da6e8
--teal:     #0077b6  to  #3399cc
--bg:       #f0f2f5  to  #f5f8fc
--border:   #c8d0da  to  #b8cfe8

Also find and replace these hardcoded hex colors wherever
they appear in the CSS only, not in JavaScript:
#1a3a5c  to  #1a6fba
#1e2d3d  to  #1a5a9e
#152f4d  to  #1a5090
#162333  to  #164080
#1e5799  to  #2980d9
#263238  to  #1a5a8a

For the sidebar background specifically change:
background: #1e2d3d  to  background: #1a5a9e

Elements using var(--navy) for their background will
automatically update and do not need separate changes.

The result should feel like a clean professional
light-to-medium blue, similar to a daytime exam interface,
not dark mode. Text on blue backgrounds must remain white
for readability. Do not change any text colors.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 1 — Remove Import and Export Buttons

```
In index.html, do the following:
1. Remove the Import button and its label from the top bar UI
2. Remove the Export button and its label from the top bar UI
3. Remove the exportBackup() function completely
4. Remove the importBackup() function completely
5. Remove any HTML elements referencing these functions
6. Make sure no broken references remain anywhere in the file

Do not change anything else. Confirm what you removed when done.
```

---

## PROMPT 2 — Return to Dashboard Button

```
In index.html, make these two changes:

1. On the PAUSE overlay: add a "Return to Dashboard" button
   that stops the current test, saves progress, and returns
   the user to the home screen

2. On the results screen after finishing a test: add a
   "Return to Dashboard" button that goes back to the home screen

Both buttons should call the existing showHome() function
or equivalent that displays the main dashboard.

Do not change any other functionality. Confirm changes when done.
```

---

## PROMPT 3 — Fix Timer to Count Up

```
In index.html, fix the per-question timer as follows:

1. The timer must COUNT UP from 0:00, not count down from 1:30
2. Display format is mm:ss, for example 0:00, 0:45, 1:30, 2:05
3. The timer turns yellow at 1:30 which is 90 seconds
4. The timer turns red and flashes at 2:00 which is 120 seconds
5. The timer never stops or locks the question. It is
   informational only and keeps counting indefinitely
6. The total elapsed test timer is not changed.
   Only fix the per-question timer behavior.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 4 — Auto Yellow Highlight

```
In index.html, simplify the highlighting system:

1. Remove the highlight color picker toolbar entirely,
   which is the floating div with yellow, blue, green,
   and pink color swatches
2. When the user selects any text in the question stem,
   automatically apply a yellow highlight immediately
   with no popup or toolbar appearing
3. To remove a highlight, the user selects already
   highlighted text and the highlight toggles off
4. Keep all highlight persistence logic unchanged.
   Highlights must still save per question.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 5 — Font Size Controls

```
In index.html, add font size controls:

1. Add two small buttons in the top bar labeled "A-" and "A+"
2. "A+" increases the base font size of the entire app
   by 1px per click up to a maximum of 20px
3. "A-" decreases the base font size by 1px per click
   down to a minimum of 12px
4. The default size is 14px
5. Apply the size change to document.body style fontSize
6. Save the preference to localStorage so it persists
   across sessions and reloads
7. The buttons are visible at all times in the top bar
   including during tests

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 6 — Calculator Strip

```
In index.html, add a basic calculator as a fixed strip
at the bottom of the screen during a test:

1. The calculator is only visible when the quiz screen
   is active
2. It is a fixed strip at the very bottom of the screen,
   always visible during the test, no toggle needed
3. Basic functionality only: digits 0 through 9,
   plus, minus, multiply, divide, decimal point,
   clear labeled C, and equals labeled =
4. A small display shows current input and result
5. Style it to match the existing blue color scheme
   of the app bottom bars
6. It must not overlap or hide the question navigation
   bottom bar. Place it cleanly below or integrate it
   into the bottom area without covering any other UI.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 7 — Lab Values Panel

```
In index.html, add a Lab Values reference panel:

1. Add a "Lab Values" button in the quiz top bar,
   visible on every question during a test
2. Clicking it opens a modal overlay panel
3. The panel has 4 tabs: Serum, CSF, Hematologic, Urine and BMI
4. Each tab shows a clean readable table of values
5. Use exactly this data for each tab:

SERUM TAB organized into sections:
Liver Enzymes: ALT 10-40 U/L, AST 12-38 U/L,
  Alkaline phosphatase 25-100 U/L
Pancreatic: Amylase 25-125 U/L
Bilirubin: Total 0.1-1.0 mg/dL, Direct 0.0-0.3 mg/dL
Electrolytes: Sodium 136-146 mEq/L, Potassium 3.5-5.0 mEq/L,
  Chloride 95-105 mEq/L, Bicarbonate 22-28 mEq/L,
  Magnesium 1.5-2.0 mEq/L
Renal: Creatinine 0.6-1.2 mg/dL, Urea nitrogen 7-18 mg/dL
Calcium and Phosphate: Calcium 8.4-10.2 mg/dL,
  Phosphorus 3.0-4.5 mg/dL, PTH 10-60 pg/mL
Lipids: Total cholesterol less than 200 mg/dL,
  HDL 40-60 mg/dL, LDL less than 160 mg/dL,
  Triglycerides less than 150 mg/dL
Endocrine: TSH 0.4-4.0 uU/mL, T4 5-12 ug/dL,
  Free T4 0.9-1.7 ng/dL, T3 100-200 ng/dL,
  Cortisol 0800h 5-23 ug/dL, Cortisol 1600h 3-15 ug/dL,
  FSH Male 4-25 mIU/mL, FSH Female 4-30 mIU/mL,
  LH Male 6-23 mIU/mL,
  Prolactin Male less than 17 ng/mL,
  Prolactin Female less than 25 ng/mL
Glucose: Fasting 70-110 mg/dL, HbA1c 6% or less
Muscle Enzymes: CK Male 25-90 U/L, CK Female 10-70 U/L,
  LDH 45-200 U/L
Iron Studies: Ferritin Male 20-250 ng/mL,
  Ferritin Female 10-120 ng/mL, Iron Male 65-175 ug/dL,
  TIBC 250-400 ug/dL
Proteins: Total protein 6.0-7.8 g/dL, Albumin 3.5-5.5 g/dL
Cardiac: Troponin I less than 0.04 ng/dL
Blood Gases: pH 7.35-7.45, PCO2 33-45 mm Hg,
  PO2 75-105 mm Hg
Miscellaneous: Uric acid 3.0-8.2 mg/dL,
  Osmolality 275-295 mOsmol/kg,
  IgA 76-390 mg/dL, IgG 650-1500 mg/dL, IgM 50-300 mg/dL

CSF TAB:
Cell count 0-5 per mm3, Chloride 118-132 mEq/L,
Gamma globulin 3-12% of total proteins,
Glucose 40-70 mg/dL, Pressure 70-180 mm H2O,
Total protein less than 40 mg/dL

HEMATOLOGIC TAB:
RBC Male 4.3-5.9 million per mm3,
RBC Female 3.5-5.5 million per mm3,
WBC 4500-11000 per mm3,
Hemoglobin Male 13.5-17.5 g/dL,
Hemoglobin Female 12.0-16.0 g/dL,
Hematocrit Male 41-53%, Hematocrit Female 36-46%,
MCV 80-100 um3, MCH 25-35 pg/cell, MCHC 31-36%,
Reticulocytes 0.5-1.5%,
Platelets 150000-400000 per mm3,
ESR Male 0-15 mm/h, ESR Female 0-20 mm/h,
Neutrophils 54-62%, Lymphocytes 25-33%,
Monocytes 3-7%, Eosinophils 1-3%, Basophils 0-0.75%,
PT 11-15 seconds, PTT 25-40 seconds,
D-dimer 250 ng/mL or less, CD4 500 per mm3 or more

URINE AND BMI TAB:
Calcium 100-300 mg/24h,
Creatinine clearance Male 97-137 mL/min,
Creatinine clearance Female 88-128 mL/min,
Osmolality 50-1200 mOsmol/kg,
Protein less than 150 mg/24h,
Oxalate 8-40 ug/mL,
17-hydroxycorticosteroids Male 3.0-10.0 mg/24h,
17-hydroxycorticosteroids Female 2.0-8.0 mg/24h,
17-ketosteroids Male 8-20 mg/24h,
17-ketosteroids Female 6-15 mg/24h,
BMI Adult 19-25 kg per m2

6. Close button in the top right corner of the panel
7. Style the panel to match the existing app design:
   white background, blue headers, clean table rows

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 8 — Simplified Explanation Display

```
In index.html, simplify the explanation display after
a user answers a question:

1. After the user selects an answer, show the correct
   answer highlighted in green as currently implemented
2. Below the answer choices, show ONE single block of text
   containing the full explanation exactly as extracted
   from the PDF. Do not parse, split, or organize it
   into per-choice sections.
3. The explanation block is a simple white card with
   a thin left border in navy blue
4. Remove all logic that separates correctBlurb,
   incorrectSummary, per-choice explanations, and
   educationalObjective into separate sections
5. Store the full explanation as a single string field
   called "explanation" on each question object
6. Update the OCR parser so that everything after
   "Correct Answer: X" on a page is stored as one
   single string in the explanation field.
   No parsing or splitting of explanation content.
7. The same single explanation block appears in the
   review screen after finishing the test

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 9 — Smart Blue Bar Detection and Overlap Deduplication

```
In index.html, replace all current OCR cropping logic with
a smart pixel-based system. This prompt has three parts.

PART A — SMART BLUE BAR DETECTION:

After rendering each PDF page to a canvas with PDF.js,
before passing the image to Tesseract, detect and remove
the NBME UI blue bars using pixel scanning.

TOP BAR DETECTION:
Scan pixel rows from the very top of the image downward.
A row is a blue bar row ONLY if ALL of these are true:
- The row spans the full width of the image
- The average pixel brightness of the row is below 80
  out of 255. This is intentionally strict to protect
  explanation text which sits on a light background.
- The blue channel value is significantly higher than
  both the red and green channels, meaning blue-dominant
- The row is contiguous with the top edge, meaning no
  non-bar row has been found yet between it and the top
Stop scanning downward the moment any row fails these
conditions. That is where the content begins.
Add a 3-pixel safety buffer: preserve 3 extra rows below
the detected bar boundary to ensure no text is clipped.
This is critical because some explanation text appears
very close to the blue bar in the screenshots.

BOTTOM BAR DETECTION:
Repeat the same logic scanning upward from the very bottom.
Same conditions: brightness below 80, blue-dominant,
contiguous with the bottom edge.
Add a 3-pixel safety buffer above the detected boundary.

CROP IMPLEMENTATION:
Create a second canvas.
Draw only the content between the detected top bar end
and the detected bottom bar start onto the new canvas.
Pass the cropped canvas to Tesseract for OCR.
If no blue bar is detected at the top or bottom,
use the full image without cropping.

IMPORTANT: Any blue color appearing in the middle of
the page such as charts, diagrams, or question images
is completely safe. It will not be affected because
it is not contiguous with the top or bottom edge.
Answer explanation text in the answers PDF sits on a
light or white background with brightness well above 80
and will never be touched by this detection.

PART B — OVERLAP DEDUPLICATION:

After merging multi-page text blocks, run overlap
detection at every seam between pages to prevent
duplicate text caused by screenshots that captured
the same line on two consecutive pages.

At each page seam do the following:
- Take the last 150 characters of the previous page text
- Search for that text at the start of the next page text
- Use fuzzy string matching with a 70% similarity threshold
  to handle slight OCR inconsistencies between two
  captures of the same text
- If a match is found, remove the duplicate portion from
  the beginning of the next page text before merging
- Only check for overlap at page seams, never mid-page

PART C — URL AND BOOKMARK REMOVAL:

After OCR text extraction, strip the following from every
page's text before any parsing occurs:
- Any URLs starting with https:// or http://
- Any Telegram links containing t.me/ or @username patterns
- Any social media handles starting with @
- Any watermark-style repeated short text strings
Use regex patterns to detect and remove all of these.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 9B — Extract Embedded Images From Question Stems

```
In index.html, add image extraction to the OCR pipeline
so that images embedded in question stems are captured
and displayed in the app:

IMAGE DETECTION:
After cropping the blue bars from the canvas, analyze the
remaining white content area to detect embedded image
regions. An image region is a rectangular area that
contains non-text visual content such as photos, ECGs,
X-rays, skin lesion photos, or lab result images shown
as pictures rather than typed text.
Detect image regions by looking for areas with high pixel
variance that are not consistent with black-on-white
text patterns.
Lab values presented as typed text line by line should
be extracted as text, not treated as images.

IMAGE EXTRACTION:
For each detected image region, crop that sub-region
from the canvas.
Convert it to a base64 PNG data URL.
Store it on the question object as an array called
"images" containing the base64 strings.

IMAGE DISPLAY:
If a question has images, display them ABOVE the question
text in the quiz interface.
Exception: if the image is detected as a lab value table,
meaning it contains mostly numbers and units in a grid
pattern, display it AFTER the question body text instead.
Images display at their natural size with max-width 100%
of the content area.
Images must persist through review mode and appear in
the same position during post-test review.

FALLBACK:
If no images are detected on a page, continue normally
with text-only extraction.
Never crash or block test generation due to image
extraction failure.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 10 — UWorld-Style Navigation Panel

```
In index.html, replace the current question navigation
panel with a UWorld-style collapsible sidebar:

1. Fixed left sidebar with independent vertical scroll
2. Collapsible: toggle between expanded showing full panel
   and collapsed showing only a thin strip with an icon
3. Save the collapsed or expanded state to localStorage
   and restore it on next session
4. Questions are numbered and clickable. Clicking a
   question navigates instantly to that question.
5. Each question dot shows one of these states:
   - Not attempted: empty circle, grey
   - Active and current: highlighted in blue
   - Correct: green check or green dot
   - Incorrect: red X or red dot
   - Flagged: small flag icon overlay
   - Marked: yellow outline
6. Questions are grouped into one section per test block
7. The sidebar scrolls independently of the main content
8. Dense spacing, minimal borders, clean UWorld aesthetic
9. Smooth collapse and expand transition animation
10. Must handle 50 or more questions without performance
    issues. No full re-renders on interaction.
11. Build entirely from the questions array.
    Do not hardcode any question elements.
12. When collapsed show only a thin strip with the
    question count and a toggle arrow.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 11 — Block Time Elapsed

```
In index.html, add a Block Time Elapsed timer to the
bottom control bar during a test:

1. Shows total time elapsed for the current test block
2. Starts when the test begins
3. Resets when the user starts a new test
4. Persists and continues running during question
   navigation within the same test
5. Always visible in the bottom bar during the test
6. Format: mm:ss when elapsed time is under 1 hour,
   hh:mm:ss when elapsed time is 1 hour or more
7. Updates every second using a lightweight setInterval.
   Do not trigger full UI re-renders on each tick.
8. Pauses when the test is paused.
   Resumes from the same time when the test resumes.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 12 — Downloadable PDF Report

```
In index.html, add a Download Test Report button on the
results screen that generates and downloads a PDF:

1. Add this CDN script tag to the head of the file:
   https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js

2. The button appears only on the results screen after
   a test is fully completed. Single click downloads
   the PDF immediately with no preview window.

3. The PDF must include these sections:

   HEADER:
   Test name, date completed, total time spent,
   mode which is Tutor or Exam

   PERFORMANCE SUMMARY:
   Total questions, correct count, incorrect count,
   skipped count, final score as fraction and percentage,
   strong topics scored 70% or above,
   weak topics scored below 70%

   QUESTION REVIEW for every single question:
   Question number, full question text,
   all answer choices listed,
   the user's selected answer marked clearly,
   the correct answer marked clearly,
   whether the result was correct, incorrect, or skipped,
   full explanation text,
   whether the question was flagged,
   any highlighted text noted as [highlighted text]

4. Clean readable layout in exam style.
   Not a raw data dump.

5. Filename format: TestName_YYYY-MM-DD.pdf

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 13 — AI Hints Using Gemini

```
In index.html, add a 3-layer AI hint system using the
Google Gemini API:

SETTINGS:
Add a Gemini API Key input field in the settings panel.
Store the key in localStorage under the key "gemini_api_key".
Also include it in Supabase session data so it syncs
across devices automatically.

HINT BUTTON:
Add a hint button labeled "💡 Hint" on every question,
positioned below the question stem and above the answer
choices. Visible in both Tutor and Exam mode. Remains
visible after the user has selected an answer.

HINT PANEL:
When a hint is requested, show a panel between the
question stem and answer choices. Style with light yellow
background #fffbeb, thin left border in amber #f59e0b,
and text color #92400e. All three hints stack vertically
in this panel as they are revealed.

THREE-LAYER HINT FLOW:
State 1: Button shows "💡 Hint"
Click calls Gemini and shows Hint 1.
Button changes to "💡 More Hint".

State 2: Button shows "💡 More Hint"
Click calls Gemini and shows Hint 2 below Hint 1.
Button changes to "💡 Final Hint".

State 3: Button shows "💡 Final Hint"
Click calls Gemini and shows Hint 3 below Hint 2.
Button becomes disabled after this.

All hints reset completely when navigating to a new question.

GEMINI API CALL:
Endpoint: https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=API_KEY
Method: POST
Header: Content-Type application/json
Get the API key from localStorage "gemini_api_key".

Use these exact prompts for each hint level.
Replace the bracketed placeholders with actual content.

HINT 1 PROMPT:
"You are a medical education tutor helping a student work
through a multiple choice question. Give a subtle hint
that points them in the right direction without revealing
the answer or naming the correct choice. Focus on the
key concept being tested.
Question: [FULL QUESTION TEXT]
Answer choices: [ALL ANSWER CHOICES LISTED]
Give only the hint, no preamble."

HINT 2 PROMPT:
"You are a medical education tutor. The student needs
more guidance. Give a stronger hint that narrows down
the reasoning significantly but still does not state
the answer or name the correct choice directly.
Question: [FULL QUESTION TEXT]
Answer choices: [ALL ANSWER CHOICES LISTED]
Give only the hint, no preamble."

HINT 3 PROMPT:
"You are a medical education tutor. Give a final hint
that leads the student directly to the answer through
reasoning, but do not explicitly state which answer
choice is correct. The student should be able to
identify the answer themselves after reading this hint.
Question: [FULL QUESTION TEXT]
Answer choices: [ALL ANSWER CHOICES LISTED]
Give only the hint, no preamble."

LOADING STATE:
While waiting for Gemini show "💡 Thinking..." on the
button and disable it until the response arrives.

ERROR HANDLING:
If no API key is set: show "Add your Gemini API key in
Settings to use hints" with a button that opens Settings.
If the API call fails: show "Hint unavailable. Check
your API key in Settings."
Never crash or break the question interface.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 14 — AI-Powered Auto-Tagging Using Gemini

```
In index.html, replace the hardcoded keyword-based
auto-tagging system with Gemini AI-powered tagging:

1. Remove the existing autoTag() function completely.
   Remove all hardcoded TAG_RULES keyword arrays completely.

2. After OCR extracts each question during test generation,
   send each question to Gemini to get its topic tags.

3. GEMINI API CALL:
   Use the same endpoint and API key as the hint system.
   Get the key from localStorage "gemini_api_key".
   If no API key is stored, assign ["Untagged"] to all
   questions silently and show this note in the OCR
   status bar: "Questions saved without tags. Add a
   Gemini API key in Settings to enable AI topic tagging."

4. PROMPT sent to Gemini for each question:
   "You are a medical education expert. Analyze this
   USMLE-style multiple choice question and return a JSON
   array of topic tags describing what this question tests.
   Include the medical subject such as Psychiatry, Surgery,
   Pediatrics, OB/GYN, Internal Medicine, Neurology,
   Cardiology, Pulmonology, Nephrology, Gastroenterology,
   Endocrinology, Hematology, Infectious Disease,
   Dermatology, Musculoskeletal, Rheumatology,
   Ophthalmology, ENT, Emergency Medicine, Radiology,
   Pathology, Pharmacology, Biochemistry, Genetics,
   Immunology, Ethics/Legal, Epidemiology/Biostatistics,
   AND the specific subtopic such as Mood Disorders,
   Appendicitis, Preeclampsia, Atrial Fibrillation,
   Mechanism of Action, and so on.
   Return ONLY a valid JSON array of strings.
   Maximum 4 tags. No explanation. No preamble.
   Example: [Psychiatry, Mood Disorders, Pharmacology, SSRIs]
   Question: [FULL QUESTION TEXT]
   Answer choices: [ALL ANSWER CHOICES LISTED]"

5. PARSING:
   Parse the JSON array from Gemini's response.
   If parsing fails for any question assign ["Untagged"].
   Never crash or block test generation due to tagging
   failure.

6. BATCHING:
   Process questions in batches of 5 at a time.
   Add a 500ms delay between batches to avoid rate limits.
   Show progress in the OCR status bar:
   "Tagging questions with AI... (10/50)"

7. No changes needed to the results analytics screen.
   It already reads from the tags array on each question
   so AI-generated tags will appear automatically.

Do not change anything else. Confirm changes when done.
```

---

## PROMPT 15 — Supabase Session Sync

```
In index.html, replace the entire Google Drive sync system
with Supabase-based automatic session persistence:

1. Add this CDN script tag to the head before all other
   script tags:
   https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2

2. Initialize the Supabase client with:
   URL: https://lmxdedepkwmilnvjcxil.supabase.co
   Key: sb_publishable_CVhmesK9VAUhAn-mMpQHYQ_yg2MMz9Q
   Make the client globally accessible as window.supabase

3. IDENTITY SYSTEM — NO LOGIN:
   On first use, generate a readable human code such as
   TIGER-4829 using a random common word plus a random
   4-digit number.
   Store it in localStorage as "user_code".
   This code is the only user identifier. No passwords.
   Show the code in the UI with a Copy Code button.
   Provide an Enter Code to Resume input field in the
   settings panel so the user can restore their session
   on any other device by typing their code.

4. DATABASE:
   Use the existing Supabase table called "sessions" with
   columns: user_id as text, data as jsonb, and
   updated_at as a timestamp.

5. SAVE SESSION function saveSession(state):
   Upsert into the sessions table using user_code as
   the user_id value.
   Store the full app state in the data column including
   folders, tests, history, flags, current question,
   answers, timer state, score, and Gemini API key.
   Update the updated_at timestamp.
   Use a 500ms debounce to prevent duplicate writes.

6. LOAD SESSION function loadSession(user_id):
   On app start, check localStorage for user_code.
   If found, fetch the session from Supabase and restore
   the full state including folders, tests, current
   question, answers, timer, score, and Gemini API key.
   If not found, prompt the user to generate a new code
   or enter an existing code.

7. SYNC TRIGGERS:
   Save immediately on: answer selection, question
   navigation, test start, test pause, test finish,
   and folder or test creation.
   Background sync every 15 seconds if state has changed
   since the last save.

8. REMOVE COMPLETELY — delete all of the following:
   Google Drive sync button and status indicator
   Google Drive setup wizard and all 5 wizard steps
   All Google OAuth functions and variables
   All Google Drive API calls and fetch requests
   Import button and Export button if not already removed

9. ADD TO UI:
   Show the user code visibly in the top bar or settings
   Copy Code button next to the displayed code
   Enter Code to Resume input field in settings
   A small sync status indicator showing Syncing,
   Synced, or Offline

10. SYNC RULES:
    Fully automatic, no manual save or load buttons.
    Must survive page refresh and tab close.
    Must not block the UI during save operations.
    Prevent duplicate writes using 500ms debounce.

Do not change anything else. Confirm changes when done.
```

---

## Data Model

Each question object:

```json
{
  "n": 1,
  "t": "Question stem text",
  "o": [
    {"l": "A", "t": "Option A text"},
    {"l": "B", "t": "Option B text"},
    {"l": "C", "t": "Option C text"},
    {"l": "D", "t": "Option D text"}
  ],
  "c": "D",
  "explanation": "Full explanation as single text block",
  "images": ["data:image/png;base64,..."],
  "tags": ["Psychiatry", "Mood Disorders"],
  "highlights": {},
  "strikethrough": []
}
```

---

## OCR Pipeline Target State After All Prompts

```
Upload Answers PDF
        ↓
PDF.js renders each page to canvas at scale 2.2
        ↓
Smart pixel scan detects dark blue rows at top and bottom
edges. Condition: brightness below 80, blue-dominant,
contiguous with edge.
        ↓
Crop precisely between detected bars plus 3px safety buffer
        ↓
Detect embedded image regions in white content area.
Extract as base64 PNG and store on question object.
        ↓
Tesseract.js OCR the cropped canvas
        ↓
Strip URLs, Telegram links, and watermarks via regex
        ↓
Detect "Exam Section: Item X of 50" as primary question anchor
        ↓
Pages with no item header merge into previous question.
Overlap deduplication at every page seam using 70% fuzzy match.
        ↓
Parse question stems and answer choices
        ↓
Parse correct answer and store everything after it
as a single explanation string
        ↓
Gemini API auto-tags each question in batches of 5
        ↓
Save test to localStorage and sync to Supabase
```

---

## Claude Code Session Rules

Every new Claude Code session must start with:

"Read PROJECT_CONTEXT.md and index.html.
Confirm you understand the project before I give you a task."

Then paste prompts one at a time from the list above.
Wait for Claude Code to finish and show the prompt symbol.
Test in Chrome after each prompt before continuing.
Never split index.html into separate files.
After finishing a session run:
git add . && git commit -m "description" && git push
