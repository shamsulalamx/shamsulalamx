# BATCH 4 — Session Status (v4.86.1)

Final hand-off doc for Batch 4. Supersedes all prior v4.84.x / v4.85.x docs.

Branch: `phase12-vertex-migration`
Tag: `v4.86.1-batch4-stable` (latest); see version history below.
Override accepted: all items ship under a single `-stable` tag per your
session-specific override of CLAUDE.md §2.

## Version history (this session)

| Tag | What |
|---|---|
| `v4.83-batch3-stable` | Promoted from pending; baseline before this session |
| `v4.84-batch4-stable` | Initial Batch 4 ship (Submit button, lab search, focus mode, etc.) |
| `v4.84.1-batch4-stable` | Validator demotion + NBME 8 Q48 patch |
| `v4.84.2-batch4-stable` | VERBATIM A-PDF explanations (no more Gemini summaries) |
| `v4.85-batch4-stable` | Full NBME 3-8 re-extract, 300/300 audit-clean |
| **`v4.86-batch4-stable`** | Per-Q timer **DISPLAY** lock on submit (DOM + queued-tick race) |
| **`v4.86.1-batch4-stable`** | This doc updated to reflect v4.86 |

---

## TL;DR — what shipped

**All 6 NBMEs (3, 4, 5, 6, 7, 8) re-extracted from scratch from
`/Users/shamsulalam/Desktop/APP/IM/NBME/*.pdf`. 300 / 300 questions
pass the item-by-item content audit. Verbatim NBME PDF explanations on
298 questions; the 2 exceptions (NBME 4 Q50, NBME 6 Q30) are PDF-source
gaps where NBME literally prints "Answer - explanation not available on
NBME website" — those carry a Gemini-best-guess answer with a clear
`extractionWarning`.**

Plus all the original Batch 4 items (#5 Submit button, #25 Lab search,
#3 + #15 focus mode, #21 exam reveal, #19 persistence, #33/#6/#12a
instrumentation, #2 uWorld text-only confirmed) remain shipped as of
v4.84.x and survive into v4.85 unchanged.

---

## v4.85 fixes (this session, on top of v4.84.2)

### Extractor

**`nbme_dual_pdf_runner.py`** — five concrete bug classes fixed:

1. **Choice-A drop** — `_CHOICE_LINE_RE` and the multi-column rescue
   parser now accept `©` and `®` as bubble-glyph prefixes (Tesseract
   OCRs the empty NBME radio as one of `0`, `o`, `O`, `Q`, `©`, `®`,
   `■`, etc.). Previously, choice A silently disappeared on NBME 7
   Q1/Q9/Q10/Q21/Q23/Q27/Q44/Q45 and NBME 8 Q6/Q14/Q24/Q42/Q45.

2. **Stem-chrome leakage** — `_STEM_CHROME_PATTERNS` widened. New
   patterns scrub `@ Mark`, `National Board of Medical Examiners®`,
   truncated `Time Rema`/`Time Rem`, NBME 8's `Ce @ N` page-footer,
   standalone `Mark` lines, and the bottom-bar `Lab Values
   Calculator [Review] Help` chrome. Previously NBME 7 Q4/Q22/Q35/Q42
   and NBME 8 Q6/Q43/Q44/Q45/Q49 all leaked UI text into the question
   stem.

3. **Lab-table truncation** — new suspicion signal
   `lab_header_without_values` fires when the stem advertises a labs
   table ("Laboratory studies show:") but has fewer than 3 actual
   numeric measurements after the header. Triggers multimodal
   page-extract escalation to recover the full inline lab values.
   Previously NBME 8 Q6 was the canonical user-reported failure here;
   also helps NBME 7 Q7/Q10/Q23/Q24/Q37/Q39/Q42.

4. **PDF column-wrap line breaks** — new `_normalize_text_flow()` joins
   the single-`\n` breaks that NBME PDFs emit at every fixed-width
   column wrap, while preserving real paragraph breaks (`\n\n`).
   Applied inside both `_clean_stem_chrome()` and
   `_clean_explanation_chrome()` so every stem and every explanation
   reads as flowing prose. Before this every question carried mid-
   sentence `↵` characters; after, none do.

5. **Filename-pair role detection** — `detect_mode()` now short-circuits
   to dual when one input filename is unambiguously Q and the other
   unambiguously A (e.g. `NBME 6Q.pdf` + `NBME 6A.pdf`). The previous
   content-sniff path mis-classified NBME 6A as Q because the A-PDF
   contains the full question stems followed by the answer key, and the
   first 3 pages didn't include the "Correct Answer" phrase.

6. **OCR-misread question-number recovery** — `chunk_text()`
   post-processes each chunk: if the in-chunk stem-prefix number (e.g.
   `~ 10. A 23-year-old...`) disagrees with the header-derived
   `Item N of 50` number, the stem-prefix value wins. NBME 3 Q10 was
   silently disappearing because the OCR rendered "Item 10" as
   "Item 1" and the chunker dedup'd it with Q1.

7. **Verbatim explanations** — runner's orchestrate path builds
   `explanationSections` from the raw chrome-scrubbed A-PDF text via
   `_split_verbatim_explanation()`. The Gemini polish call is still
   made, but ONLY for the meta fields (reviewPearl, retrievalTag,
   educationalObjective). `polished.get("explanationSections")` is no
   longer consumed.

8. **`_CORRECT_ANSWER_RE`** — widened from `\s+` to `\s*` between
   "Correct" and "Answer" so NBME 3A's embedded `CorrectAnswer:` (no
   space) matches alongside the OCR'd `Correct Answer:` variant.

9. **`question_pages.json`** — runner now writes a `q_num → pdf_page`
   map alongside the app_ready JSON, so the targeted multimodal
   remediator can render the exact page for any post-extraction
   audit failure without brute-force scanning.

### Patcher pipeline

Three companion tools, run after each extraction:

- **`/tmp/verbatim_patcher.py`** — re-extracts verbatim explanations
  from the cached A-PDF raw text, replaces the runner's polish output,
  normalizes stem text flow. Handles standard NBME format (3, 4, 5, 7, 8).

- **`/tmp/nbme6_inline_parens_patcher.py`** — NBME 6 only. Older PDF
  format uses inline-parens references (`(C) For melanoma...`,
  `(B is correct)`, `(Fis correct)`, `F Insufficient inhibition...`)
  instead of the explicit `Correct Answer:` + `Incorrect Answers:`
  headers. Three pattern strategies + OCR-tolerance (handles
  `(Eis correct;` and `(Bis correct, E is incorrect)`).

- **`/tmp/targeted_remediator.py`** — for any question that fails the
  content audit, render the relevant cached page and run Gemini
  multimodal with a strict prompt. Recovers stems that lost text +
  choices that the chunker missed, including tabular layouts.

### Content audit

**`/tmp/content_audit.py`** — gates every ship. 14 distinct checks:

1. Chrome leakage in stem
2. Stem too short (<100 chars)
3. Phantom mid-sentence line break in stem
4. Stem ends mid-sentence (with tabular-choice exemption — `|`-separated
   OR same-token-count signature)
5. No choices · Missing choice A · Choice-label gap (A, B, D missing C)
6. Choice text too short (1-char, except graph-pointing labels-as-choices)
7. Choice starts lowercase (with biochem/gene-name/translocation exemptions)
8. Lab-header without values (multi-label-only-lines signature, with
   benign-ending exemptions like "show no abnormalities", "are within
   the reference range", "show a leukocyte count of…")
9. correctAnswer not in choice labels
10. Missing correctAnswer
11. Missing Correct Answer Explanation section
12. Correct explanation suspiciously short (<250 chars, likely Gemini summary)
13. Missing Incorrect Answer Explanation section (with NBME-6-combined
    + long-body-covers-inline + "is incorrect" inline exemptions)
14. Phantom mid-sentence breaks in Correct/Incorrect explanation bodies
15. Explanation references `(Choice X)` for a missing choice

---

## Final stats (300 / 300 clean)

| NBME | Q  | Choices avg | Correct expl avg (verbatim) | Incorrect expl avg | PDF-gap notes |
|------|----|-------------|------------------------------|--------------------|---------------|
| 3 | 50 | 5.9 | 1271 chars (50/50) | 1448 chars (39/50) | — |
| 4 | 50 | 5.9 | 1169 chars (50/50) | 1256 chars (36/50) | Q50 ¹ |
| 5 | 50 | 5.4 |  793 chars (50/50) | 1005 chars (50/50) | — |
| 6 | 50 | 5.3 |  955 chars (50/50²)| n/a (combined)     | Q30 ¹ |
| 7 | 50 | 5.3 | 1230 chars (50/50) | 1231 chars (47/50) | — |
| 8 | 50 | 5.4 | 1211 chars (50/50) | 1171 chars (50/50) | — |

¹ NBME source PDF has no answer key entry — Gemini-best-guess answer
with `extractionWarning` + footer note in the explanation body.

² NBME 6 uses an older single-block format that combines correct +
incorrect rationale. Patcher preserves the full block as one verbatim
Correct Answer Explanation section.

---

## Files staged at `/Users/shamsulalam/Desktop/v4.85-app-ready/`

```
NBME 3_app_ready.json
NBME 4_app_ready.json
NBME 5_app_ready.json
NBME 6_app_ready.json
NBME 7_app_ready.json
NBME 8_app_ready.json
```

The previous `v4.84-app-ready/` directory has been removed.

### Re-import instructions

Launch the rebuilt `.app` at `dist/mac-arm64/shamsulalamx.app`. In NBME
Gemini JSON Import, select each of the 6 files. Existing per-question
state on these tests (answers, marks, timers, notes, highlights) will
be replaced — that was OK'd in your batch-4 permissions.

---

## v4.86 fix — per-Q timer DISPLAY lock on submit

**User-reported regression on top of v4.85:** "PER QUESTION TIMER STILL
DOES NOT STOP IMMEDIATELY AFTER CLICKING SUBMIT. THE TOTAL TIMER STOPS
AFTER SUBMIT, BUT THE QUESTION SPECIFIC TIMER KEEPS GOING."

Real cause: in v4.84-v4.85, `submitAnswer` cleared the per-Q interval
correctly (`stopQTimer` → `clearInterval`), but two subtle paths made
the displayed value appear to keep advancing:

1. **Display lag** — submit captured `r.time` precisely but never
   pushed it to the DOM. The DOM still showed whatever value the most
   recent 500 ms tick had written to `state.qSecs`, which lagged
   `r.time` by up to half a second. Felt like an extra tick.

2. **Queued-tick race** — JS `setInterval` callbacks already scheduled
   before `clearInterval` still fire on the event loop. That
   post-clear tick re-wrote `state.qSecs` and re-rendered, making the
   display tick once past submit.

**Fix (v4.86, `index.html`):**

- `submitAnswer` now sets `state.qSecs = r.time`, nulls `state.qStart`,
  and explicitly calls `renderQTimer()` to lock the DOM to the exact
  frozen value before any other render.
- The setInterval callback bails defensively on any of: state
  destroyed, `qTimerRef` nulled, `qStart` nulled, or `r.answered ===
  true` — catches the queued-tick-after-clear edge case.

## Earlier Batch 4 items (unchanged from v4.84.x)

| # | Status |
|---|---|
| #5 Submit button (all sources, both timers freeze on submit) | shipped (display-lock hardened in v4.86) |
| #25 Lab search inline highlight + Enter cycle | shipped |
| #3 / #15 Focus-mode pause/lab/calc z-index fix | shipped |
| #21 Exam-mode reveal-at-end | shipped |
| #19 Pause/resume answer persistence | shipped |
| #33 Drive backup↔restore instrumentation only | shipped |
| #6 Timer freeze instrumentation only | shipped |
| #12a Highlight perf instrumentation only | shipped |
| #2 uWorld text-only (no code change needed) | shipped |
| #23 NBME 3 Q26 correctAnswer = H | shipped (verified via re-extract) |
| #7 NBME 3 PDF-verbatim explanations | shipped (verified via v4.85) |
| #32 NBME 7/8 import failure | shipped (validator + extractor fixes) |
| #29 bromocriptine hint | no-op (verified resolved in v4.81) |

---

## Static checks performed
- `python3 -m py_compile tools/nbme-pdf-json-generator/nbme_dual_pdf_runner.py` → clean
- `node --check` on 11 inline `<script>` blocks in `index.html` → 0 errors
- IIFE-boundary scope check (CLAUDE.md §4) for app-side edits → confirmed in-scope
- Item-by-item content audit on all 300 questions → 0 issues
- Bundle MD5 verification (source ↔ bundled) → matches

## CLAUDE.md compliance notes
- All-stable tag override accepted for this session (per your earlier
  explicit instruction).
- Drive code (#33) remains instrumentation-only (high-trust per
  CLAUDE.md).
- I cannot click-through test the Electron app. UI items (#5, #21,
  #3, #15, #25) are static-check-and-build-verified only; you are
  the runtime verification step.
- Audit is the new ship gate. Any future Batch must pass
  `/tmp/content_audit.py` at 0 issues before tagging.

## What you come back to
- Branch `phase12-vertex-migration`, HEAD pushed to origin
- Tag `v4.86.1-batch4-stable` (latest) pushed; earlier tags preserved
  for clean rollback points
- `dist/mac-arm64/shamsulalamx.app` rebuilt for v4.86 and bundle-MD5-
  verified (no rebuild needed for v4.86.1 — docs-only patch)
- `/Users/shamsulalam/Desktop/v4.85-app-ready/` containing 6 fresh
  app-ready JSONs (every question audited clean) — these are
  binary-stable since v4.85; v4.86 only touched index.html
- This document

## Re-launch the .app to pick up v4.86

You must **quit and relaunch** the .app to load the v4.86 bundle.
Verify the per-Q timer freeze: click any choice → click Submit. The
per-Q timer should freeze instantly, no half-second drift, no extra
tick. Clicking Next on a submitted question advances to the next Q and
both timers restart cleanly.
