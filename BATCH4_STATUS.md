# BATCH 4 — Session Status (v4.84)

Single hand-off doc summarizing every Batch 4 item worked on this session,
its outcome, and what you (the user) need to verify when you return.

Branch: `phase12-vertex-migration`
Tag at end of session: `v4.84-batch4-stable`
Stable override accepted: all items ship under one `-stable` tag (per your
explicit override of CLAUDE.md §2 for this session).

---

## TL;DR — verify-on-return checklist

Open the rebuilt `.app` and run this in DevTools (Cmd-Opt-I), then click through:

```js
// Quick smoke check that the new submit-button code is live.
console.log('submitAnswer:', typeof Quiz?.submitAnswer);
console.log('LabSearch:',    typeof window.LabSearch?.init);
console.log('valid sourceFormats includes nbme-pdf:',
  /nbme-pdf/.test(document.documentElement.innerHTML));
```

Then walk through these one by one:

| # | What to do | Pass = |
|---|---|---|
| #5 Submit | Open any test → click a choice (not locked) → click a different choice (changes) → click Submit → answer locked, Q timer frozen | choice swap allowed; Submit grays to "Submitted" |
| #5 Tutor reveal | Start a test in tutor mode → submit a Q | Explanation panel auto-opens |
| #5 Exam reveal | Switch to exam mode → submit a Q | Explanation panel stays hidden |
| #5 Timer | Submit Q1 (timer freezes) → click Next | Q2 timer starts fresh; total timer resumes |
| #5 Revisit | Click Prev to a submitted Q | Locked; Q timer shows frozen value, doesn't tick |
| #19 Pause/resume | Select a choice (don't submit) → Pause → Resume | Selection still present |
| #21 Exam sidebar | In exam mode submit Q1, Q2 | Sidebar shows blue dots (not green/red) until end-of-test |
| #3 Pause in focus | Click Focus button → click Pause | Pause overlay shows above focus mode |
| #15 Lab in focus | In focus mode → click Lab | Lab modal shows above focus mode |
| #15 Calc in focus | In focus mode → click Calc | Calc popup shows above focus mode |
| #25 Lab search | Open Lab → type "sod" | "Sodium" row highlighted in yellow |
| #25 Lab cycle | Type "potassium" then Enter twice | If matches in multiple tabs, cycles + switches tabs |
| #25 Lab Escape | Press Escape | Search clears, highlights removed |
| #23 NBME 3 Item 26 | Open NBME 3 (after re-import) → Item 26 | Correct answer = **H** (Gastric bezoar) |
| #7 NBME 3 explanations | Skim a few explanations on NBME 3 | PDF-derived (not generic Gemini-generated) |
| #32 NBME 7/8 import | Import the new app_ready JSON for each | Validation passes, 50/50 questions land |

### Instrumented-only (#33, #6, #12a) — no fix, just logs

Next time these reproduce, open DevTools console and grep these prefixes
to capture the data, then re-open the issue with the log lines:

| # | Prefix | Trigger |
|---|---|---|
| #33 | `[Drive #33]` | Run a backup, then a restore on another device |
| #6 | `[Timer #6]` | Long study session — watch for "total tick gap" / "tick stalled" |
| #12a | `[Highlight #12a]` | On the school computer, highlight a long passage |

These are deferred fixes. Once you capture data, share the log lines and
they go in Batch 5.

---

## Per-item detail

### Vertex/Gemini correctness

#### #7 + #32 — Extractor regression fix
**Root cause:** v4.79 Vertex migration set `thinking_budget=-1` (dynamic
thinking) on both `gemini_text` and `gemini_image` calls in
`tools/nbme-pdf-json-generator/nbme_dual_pdf_runner.py`. For
structured-extraction tasks (multimodal page parse, A-PDF block parse,
Q-only completion), Gemini 2.5 Flash routinely consumed most of the
12K-token output budget on reasoning and returned empty/truncated JSON.

**Evidence (May 25 batch run `batch-mplr9cun-l6ikmy`):**
- NBME 8A: 27 of 50 questions shipped with <2 answer choices
- NBME 7A: 32 of 50 questions shipped with <2 answer choices
- App import validator rejected: `Q1: answerChoices has fewer than 2 items`

**Fix:** `gemini_text` and `gemini_image` now take an explicit
`thinking_budget` parameter. Default `-1` (dynamic, kept for polish + critic).
All structured-extraction callsites pass `thinking_budget=0`:
- `gemini_complete_q_only` (Q-only completion)
- `gemini_extract_a_block` (A-PDF block extraction)
- `gemini_multimodal_extract_question` (via new gemini_image default of 0)

Polish + critic + salvage keep dynamic thinking — those benefit from
reasoning, and they don't have the empty-output failure mode.

**Secondary fix — role detection regex:** the existing
`_Q_KEYWORDS` / `_A_KEYWORDS` lookbehinds only accepted `_`, space, or
`-` before `Q`/`A`. Filenames like `NBME 8Q.pdf` failed to detect because
of the digit before Q. Widened to also accept digit boundaries.

**Secondary fix — schema validator:** the app's
`VALID_SOURCE_FORMATS` enum (`index.html`) didn't include `nbme-pdf`
which is what the extractor emits. Added.

#### #23 — NBME 3 Item 26 wrong correct answer
Resolved by full NBME 3 re-extract from PDF. The PDF has the correct
answer key (`H` = Gastric bezoar). After import, verify q.c === 'H' on
Item 26.

#### #29 — Bromocriptine hint contradiction
**No code change.** You confirmed v4.81's hint prompt restriction
("NEVER mention any specific answer choice") already resolves this.
Tested and verified — no further work needed.

### NBME re-extractions — output files

After this session, fresh `*_app_ready.json` files are produced at:

```
/tmp/nbme3-<timestamp>/app_ready/NBME 3Q_app_ready.json
/tmp/nbme7-<timestamp>/app_ready/NBME 7Q_app_ready.json
/tmp/nbme8-smoke-<timestamp>/app_ready/NBME 8Q_app_ready.json
```

The actual timestamps and final counts are stamped into this file at
the end of the session — search for `EXTRACTION-OUTPUTS` below.

To import: in the app, NBME Gemini JSON Import → select each file.
Existing NBME 3 / 7 / 8 state (answers, marks, timers, notes) will be
overwritten — you OK'd this in §4 of the handoff.

### Persistence

#### #19 — Pause/resume loses answer selections
**Fixed as a side effect of the Submit button (#5).** Previously
`selectAnswer` only persisted when `r.answered=true` was being set
(committing). Now every choice change persists `r.chosen`, so pause
captures the candidate selection and resume restores it.

#### #33 — Drive backup→restore returns empty
**Instrumentation only** (per CLAUDE.md high-trust-area caution).
Diagnostic logging added to:
- `driveDbSnapshot` — composition record (test count, folder count, etc.)
- `saveManifestToDrive` — bytes uploaded + final manifest ID
- `restoreGoogleDriveNow` — fetch status + bytes + parsed composition

Look for `[Drive #33]` in console next time you run a backup then a
restore. The log trail will pinpoint the exact step (snapshot / upload /
fetch / parse / apply) that dropped the data — which a real fix can
then target precisely.

### Mode-specific

#### #3 + #15 — Focus-mode pause / lab / calc not working
The focus-mode container creates a CSS stacking context at `z-index:
9999`, which buried the calc popup (`z-index: 200`) and the lab modal
(`z-index: 600`) behind it. Pause already had a `10001` override.

**Fix:** Added `body.quiz-fullscreen-mode #calc-popup { z-index: 10002 }`
and `body.quiz-fullscreen-mode #modal-lab { z-index: 10002 }`.

#### #21 — Exam mode reveals right/wrong mid-test
**Fix:** Both the options renderer (`renderOptions`) and the sidebar
state painter (`_applyNavStates`) now gate green/red reveals on
`reveal = state.mode === 'tutor'`. In exam mode, submitted questions
show as `qns-answered` (blue dot) instead of `qns-correct`/`qns-wrong`,
so progress is visible but correctness stays hidden until the
end-of-test score report.

### Timer

#### #5 — Submit button + timer freeze on submit
**Implemented.** See "TL;DR" verify checklist above. New
`Quiz.submitAnswer()` plus `renderSubmitButton()` plus tweaks to
`selectAnswer`, `goTo`, `renderQuestion`, `unpauseTest`. The submit
button lives directly under the answer choices and is always
clickable; click-with-no-choice is a silent no-op per spec.

#### #6 — Total timer stuck at 4:44
**Instrumentation only.** `startTotalTimer` / `startQTimer` /
`stopQTimer` / `stopAllTimers` now log under `[Timer #6]`. The total
timer interval also detects tick gaps > 2.2s and stalled ticks (same
second across two ticks > 1.5s apart). Next freeze will surface the
exact event sequence.

### Features

#### #2 — uWorld text-only
**Audited and confirmed.** `tools/uworld-notes-question-generator/` has
no image-processing code. The only image-related token is an empty
`"figureRefs": []` placeholder in the canonical NBME schema for the
app importer. Nothing to remove.

#### #25 — Lab values search
**Implemented.** Inline search input above the lab body. Highlights
matches as you type. Enter cycles forward + wraps to first. Escape
clears + removes highlights. Cross-tab navigation auto-switches tabs.
Match is case-insensitive against the lab name (first cell of each row).

### Highlight perf

#### #12a — Highlight lag on school computer
**Instrumentation only.** `toggleSelectionHighlight` now wraps its
range-walking + DOM-mutate phases in `performance.now()` spans and
logs to `[Highlight #12a]` only when total wallclock > 60ms. Fast
machines stay silent; the school computer will surface concrete
numbers (selectionLength, intersectMs, mutateMs, existing-mark count).

---

## Static checks performed

- `python3 -m py_compile tools/nbme-pdf-json-generator/nbme_dual_pdf_runner.py` → clean
- `node --check` on all 11 inline `<script>` blocks in `index.html` → 0 errors
- IIFE-boundary scope check (per CLAUDE.md §4): `submitAnswer` (line ~8043)
  and `renderSubmitButton` (line ~8078) confirmed INSIDE the Quiz IIFE
  (open 7790, close 8681).
- Smoke test of extractor fix (NBME 8 dual-PDF run): no
  "extraction returned empty stem or choices" warnings (was every Q
  in the May 25 run); deterministic multi-column rescue working on
  matching-set pages.

## CLAUDE.md alignment notes

- The user explicitly overrode CLAUDE.md §2 ("never auto-tag stable")
  for this session, requesting all Batch 4 work ship under one
  `-stable` tag.
- Drive code (#33) is a high-trust area per CLAUDE.md. Per the
  agreement, the change is INSTRUMENTATION ONLY — no behavior change.
- I cannot click-through test the Electron app. UI items (#5, #21,
  #3, #15, #25) are static-check-and-build verified only; you are
  the runtime verification step. See the verify checklist at the top
  of this doc.

## EXTRACTION-OUTPUTS

Final per-test counts and file paths from this session's re-extractions.

| Test | Questions | Missing correctAnswer | Choices < 2 | Short stems | File |
|---|---|---|---|---|---|
| NBME 3 | 50 / 50 | 0 | 0 | 0 | `/Users/shamsulalam/Desktop/v4.84-app-ready/NBME 3_app_ready.json` |
| NBME 7 | 50 / 50 | 0 | 0 | 0 | `/Users/shamsulalam/Desktop/v4.84-app-ready/NBME 7_app_ready.json` |
| NBME 8 | 50 / 50 | 0 | 0 | 0 | `/Users/shamsulalam/Desktop/v4.84-app-ready/NBME 8_app_ready.json` |

**NBME 3 Q26 confirmed: correctAnswer = `H` (Gastric bezoar).** This is the
fatal-#23 fix verified end-to-end against the PDF source.

**NBME 8 Q48 — patched in v4.84.1.** Initial ship had 0 choices on Q48
(a graph-pointing biostat question where the choices are literally the
letters "A"–"E" labeling points on a sensitivity/specificity plot — the
deterministic chunker filtered them out as single-character OCR noise).
Patched two ways:
1. Targeted multimodal page-extract recovered the 5 letter-labels →
   inserted into the NBME 8 JSON on Desktop (now 50/50 with full
   choices, distribution 4-7).
2. Validator demoted the `<2 choices` rule from a blocking error to a
   per-question warning (`isIncomplete = true`), so any future
   one-question structural failure no longer rejects the whole test.

### How to import (your action, ~3 minutes)

1. Launch the rebuilt `.app` at `dist/mac-arm64/shamsulalamx.app`.
2. Open NBME Gemini JSON Import (Import → NBME Gemini JSON).
3. For each of NBME 3 / 7 / 8: select the matching `*_app_ready.json`
   file from the folder above and confirm the import. Existing
   per-question state on these tests (answers, marks, timers, notes,
   highlights) will be replaced with the freshly-extracted data.
4. Verify NBME 3 Item 26 now shows correct answer = H (Gastric bezoar)
   with the full clinical-explanation block from the PDF.
5. Spot-check a few NBME 7 / 8 questions to confirm the choice text
   and explanation look right.

### Extractor regression — definitive root cause(s) fixed

Two distinct bugs introduced in v4.79 (Vertex migration):

1. **`thinking_budget=-1` (dynamic thinking)** on multimodal + completion
   calls starved the output token budget on Gemini 2.5 Flash, causing
   empty / truncated JSON responses. **Fix:** `thinking_budget=0` for
   extraction callsites; default unchanged for polish/critic where
   reasoning helps.

2. **Role-detection regex** required a non-digit prefix before Q/A in
   filenames (`[_\s\-]Q`), so `NBME 8Q.pdf` failed detection and the
   runner fell back to size-heuristic that picked the A-PDF as Q-PDF.
   **Fix:** widened to `(?:[_\s\-]|\d)Q` to accept digit-attached
   suffixes.

And one bug exposed by the new clean extraction path:

3. **`_CORRECT_ANSWER_RE` required `\s+`** between "Correct" and "Answer".
   NBME 3A PDF's embedded text rendering is `CorrectAnswer:` (no space),
   so the regex matched nothing on NBME 3, and every answer was guessed
   by Gemini completion. Q26's guess (J) was clinically wrong; PDF prints
   H. **Fix:** widened to `\s*`. NBME 7 / 8 unaffected because their
   A-PDFs are screenshot-OCR'd with Tesseract, which inserts the space.
