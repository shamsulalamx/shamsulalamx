# BATCH 4 HANDOFF — Session State as of 2026-05-26

Hand-off document for resuming work in a fresh Claude session. Read this AFTER
`CLAUDE.md` (which is the binding protocol — it ALWAYS takes precedence over
anything in this file).

---

## 1. Tag history (current state)

| Tag | Status | Branch | Commit |
|---|---|---|---|
| `v4.81-batch1-ui-polish-stable` | shipped + stable | `phase12-vertex-migration` | `a85e319` |
| `v4.82-batch2-stable` | shipped + stable | `phase12-vertex-migration` | `6f77188` |
| `v4.83-batch3-pending-validation` | shipped + pending | `phase12-vertex-migration` | `6c62e53` |

**Pending tag promotion before Batch 4 ships:**
- `v4.83-batch3-pending-validation` → `v4.83-batch3-stable`

User has lived with v4.83 long enough; promote on resume.

---

## 2. The original 33-item list — cumulative resolution

**Shipped (24 of 33):**

| Batch | Tag | Items resolved |
|---|---|---|
| 1 | v4.81 | #8, #18, #20, #22, #28 (UI polish: hint prompt, hint counter, hint label, ed objective dup, image CSS) |
| 1 | v4.81 | #16 (bottom panel gap — separate fix in batch 1) |
| 2 | v4.82 | #12b (single-click unhighlight), #17 (Q-number prefix dup) |
| 2 | v4.82 | #30 (clinical pearls + Gemini pearl gen for legacy NBMEs) |
| 3 | v4.83 | #1, #9, #10, #11, #13, #24, #26, #27 (rendering pipeline) |
| 3 | v4.83 | Plus 13 patches from NBME 4/5/6 fixture sweep (OCR fixes, β-thalassemia, etc.) |

**Remaining for Batch 4 (9 originally listed):**

🔴 Vertex/Gemini correctness: #23, #7, #29, #32
🔴 Persistence/Drive: #19, #33
🟡 Mode-specific: #3, #15, #21
🟡 Timer: #5, #6
🟢 Features: #2 (uWorld), #25 (lab search)
🟡 Highlight perf: #12a

---

## 3. Batch 4 plan — agreed scope

### Override accepted (user explicit):
**ALL Batch 4 work ships under a single `-stable` tag** (`v4.84-batch4-stable`),
overriding CLAUDE.md's default `-pending-validation` rule. User has accepted the
rollback-cost trade-off. This override is **session-specific** — future
batches go back to the default `-pending-validation` rule.

### Items to FULLY FIX (11):

| # | Description |
|---|---|
| #23 | FATAL: NBME 3 Item 26 wrong correct answer — currently `q.c="C"`, should be `H` (Gastric bezoar / trichobezoar). User confirmed correct answer = H. |
| #29 | Bromocriptine hint contradiction — NBME 3 Q46. Note: v4.81 already restricted hint prompt from naming specific choices, so MAY already be resolved — pending user verification (see Q5 in §5). |
| #7 | NBME 3 has Gemini-generated explanations — would need full re-extraction from PDF. Approach TBD by user (see Q1 in §5). |
| #32 | NBME 7/8 import failures. 8A.pdf already in `tools/nbme-pdf-json-generator/input_pdfs/`; latest extraction had 1 failure + 12 validation errors out of 50 questions. NBME 7 PDFs at `/Users/shamsulalam/Desktop/NBME 7Q.pdf` and `7A.pdf`. |
| #19 | Pause→resume loses answer selections (highlights persist correctly, answers don't). |
| #3 | Pause button doesn't work in focus mode. |
| #15 | Lab/Calc buttons don't work in focus mode. |
| #21 | Exam mode reveals right/wrong on click; should defer to end-of-test score report only. |
| #5 | Per-Q + total timer both pause when answer selected, both resume on Next click. |
| #2 | uWorld import is text-only, images NOT processed (user separates them and feeds into images-tables-question-generator pipeline). |
| #25 | Lab values modal: add search input that highlights matches as user types, with jump-to-match navigation. |

### Items to INSTRUMENT ONLY (3 — cannot be fixed without live testing):

| # | Description | Instrumentation |
|---|---|---|
| #33 | Drive backup→restore returns nothing despite success message | Add diagnostic logging to backup write path AND restore read path so next user attempt produces console output identifying where the mismatch occurs |
| #6 | Total timer stuck at 4:44 (intermittent) | Add timing instrumentation around timer tick + pause/resume events |
| #12a | Highlight lag on school computer (hardware-specific) | Add wall-clock perf timer around highlight save in `toggleSelectionHighlight` + range-walking code |

These are flagged as DEFERRED — the new session should add instrumentation
NOW but wait for user reproduction data before attempting actual fixes.

---

## 4. Permissions granted by user (blanket yes)

- Modify Python extraction pipeline (`tools/nbme-pdf-json-generator/*.py` + the prompt file `prompts/chunk_to_normalized_question_prompt.txt`)
- Spend money on Vertex/Gemini API calls for re-extractions (cents per question)
- Re-import affected NBMEs (wipes per-question state — highlights/notes/marks/answered status — on those specific tests; other NBMEs unaffected)
- Modify Drive sync + persistence code (CLAUDE.md high-trust area)
- Add diagnostic logging across Drive/timer/highlight code paths

---

## 5. OPEN CLARIFICATIONS — answer these in new session before coding

User said "ask clarifying questions, don't guess" and the following six are
still outstanding. New session must get answers before starting Batch 4 code
changes:

**Q1 (biggest one) — NBME 3 strategy:**
- A. Surgical: just patch `q.c` on Item 26 from C→H. Preserves existing NBME 3 state. Doesn't fix #7.
- B. Full re-extract from `/Users/shamsulalam/Desktop/NBME 3Q.pdf` and `NBME 3A.pdf`. Wipes existing NBME 3 state. Fixes both #23 and #7.
- DEFAULT IF SKIPPED: A (surgical).

**Q2 — #5 timer edge cases:**
- After answering Q5, then clicking Prev back to Q5 (already answered): timers stay paused OR resume?
- Changing answer on already-answered Q: timers stay paused OR restart?
- DEFAULT IF SKIPPED: stay paused on any revisit (answered = locked).

**Q3 — #25 lab search interaction:**
- A. Inline highlight + keyboard nav (Enter/arrows to jump to next/prev match, no popup)
- B. Dropdown popup of matches (click one to scroll to it)
- DEFAULT IF SKIPPED: A.

**Q4 — #2 uWorld current state:**
- Is there CURRENTLY code in uWorld import that tries to process images and breaks/warns? Or is the fix just confirming + documenting?
- DEFAULT IF SKIPPED: grep `tools/uworld-notes-question-generator/` — if image-handling code exists, remove. If absent, document and confirm.

**Q5 — #29 bromocriptine — has user re-tested since v4.81?**
- Yes & still contradicting → add stronger prompt guards
- Yes & now fine → mark resolved by v4.81, no further work
- Haven't tested → verify prompt change is intact and assume v4.81 fixed it
- DEFAULT IF SKIPPED: option 3 (verify and assume).

**Q6 — #32 NBME 8 — extraction or import?**
- Has user attempted to import `8A_app_ready.json` into the .app? Or did it fail at extraction?
- DEFAULT IF SKIPPED: investigate the 12 validation errors in `output_json/normalized/8A_normalized.json` first; that's most likely the upstream cause.

---

## 6. Behavior defaults user confirmed

| # | Behavior |
|---|---|
| #5 | When answer selected: BOTH per-Q timer AND total timer pause. When Next clicked: BOTH resume. |
| #21 | Right/wrong reveal only at end-of-test score report in exam mode. Mid-test review allowed without correctness reveal. |
| #25 | Search by lab name (not value/range). Highlights matches as user types. Then user selects which match to jump to (see Q3 above for exact interaction). |
| #2 | uWorld import is text-only. Images NOT included in uWorld parser. User manually separates images and feeds them into the images-tables-question-generator pipeline. |

---

## 7. Architecture summary — what's where (post-v4.83)

### Normalizer (added in v4.83, lines ~7408-7659 in index.html)

A top-level IIFE that exposes three globals:
- `window._normalizeDisplayText(text)` — render-time string repair. ~50 regex patterns.
- `window._normalizeChoices(choices)` — returns normalized copies of choice array.
- `window._tryRenderColumnedChoices(choices, container, onClick, options)` — table-style answer choices (#26).

Wired in three places:
- `window.buildStemHTML` (every stem render)
- `window.buildQuestionStemHTML` saved-highlight-HTML path (so old highlights also get normalized)
- `window.getQuestionChoices` (returns normalized copies — propagates to renderOptions AND both buildExplanationHTML variants)

### Lab block extractor (added in v4.83)

- `_extractEmbeddedLabBlock(paragraph)` — pulls contiguous lab-shaped lines out of long prose paragraphs into a `<table>`. The existing `_isLabPara` rejects paragraphs >400 chars so it never fired in practice.
- `_EMBED_LAB_LINE_RE` — widened to include qualitative results (negative/positive/trace), N+ charges, ranges (1-2/hpf), /hpf /lpf sec units.

### Hint system (touched in v4.81 batch 1)

- Hint prompt at `index.html:8258-8269` (numbers may shift — search for "Step 2 CK clinical reasoning coach")
- Hint label removed from `_renderHints` at `index.html:8196-8203` area
- Hint counter removed from quiz topbar
- Prompt now includes: "NEVER mention any specific answer choice — neither the correct one nor any wrong one"

### Clinical pearl generation (added in v4.82 batch 2)

- `window.generateClinicalPearl(q, test)` — calls Gemini, caches to `q.clinicalPearl`, persists via `DB.updateTest`
- `window._hasAnyClinicalPearl(q)` — true iff any of `reviewPearl/clinicalPearl/pearl/pearls/metadata.*` is set
- Wired into: quiz-interface pearl block (`q-pearl-block`), review-mode pearl block (`rev-pearl-block`), score-report Needs Review section (`res-weaknesses` via `buildTopicAnalysis`)

### App IIFE structure (CLAUDE.md scope-sensitivity)

- `const App = (() => { ... })()` starts at `index.html:9298-ish`
- App IIFE closes around line 30354
- Multiple OTHER IIFEs exist before App (closing at lines 3967, 4126, 4195, 4255, 5076, 6938, 7316, 7335 area, 8051, 9284)
- Two `buildExplanationHTML` exist: one inside App IIFE (~line 7832-7895) and one global override (~line 8051+, `window.buildExplanationHTML = function(...)`). Edits to either must verify they apply at intended scope.

### Existing `getReviewPearl` definitions (chained for pearl fallback)

- Inside Results IIFE at `index.html:8612+`
- Global at `index.html:9321+` (`window.getReviewPearl = ...`)

Both updated to chain: `reviewPearl → clinicalPearl → pearl → pearls[0] → metadata.*`

---

## 8. Source PDFs available

| File | Path |
|---|---|
| NBME 3 questions | `/Users/shamsulalam/Desktop/NBME 3Q.pdf` (18 MB) |
| NBME 3 answers | `/Users/shamsulalam/Desktop/NBME 3A.pdf` (39 MB) |
| NBME 7 questions | `/Users/shamsulalam/Desktop/NBME 7Q.pdf` (18 MB) |
| NBME 7 answers | `/Users/shamsulalam/Desktop/NBME 7A.pdf` (70 MB) |
| NBME 8 (already in pipeline) | `tools/nbme-pdf-json-generator/input_pdfs/8A.pdf` |

User has NOT provided NBME 5 PDFs (extraction-failed NBME 5 questions, if any, would need PDFs to fix).

---

## 9. Extraction pipeline locations (Python)

- `tools/nbme-pdf-json-generator/extract_pdfs.py` — text/figure extraction from PDFs (1386 lines)
- `tools/nbme-pdf-json-generator/normalized_to_app_json.py` — JSON → app-importable format (521 lines)
- `tools/nbme-pdf-json-generator/nbme_batch_wrapper.py` — orchestration (246 lines)
- `tools/nbme-pdf-json-generator/nbme_dual_pdf_runner.py` — main runner (2076 lines)
- `tools/nbme-pdf-json-generator/prompts/chunk_to_normalized_question_prompt.txt` — Gemini prompt (119 lines)
- `tools/nbme-pdf-json-generator/schema/normalized_question_schema.json` — output schema
- `tools/nbme-pdf-json-generator/reports/extraction_report_*.json` — per-run validation reports

Latest extraction (May 19, 17:14): 1 file (`8A.pdf`), 1 failure, 12 validation errors among 50 normalized items.

---

## 10. Test fixtures generated this session (Node.js, for normalizer testing)

- `/tmp/nbme3-test/nbme4.json` — NBME 4 fixture (50 questions)
- `/tmp/nbme3-test/nbme5.json` — NBME 5 fixture (50 questions)
- `/tmp/nbme3-test/nbme6.json` — NBME 6 fixture (49 questions)
- `/tmp/nbme3-test/full_test.js` — test runner template
- `/tmp/nbme3-test/diagnose_all.js` — issue-category diagnostic script
- `/tmp/nbme3-test/diagnose_v5.js` — latest with all v4.83 patches inline

These survive across sessions on this machine. Useful for regression testing
after Batch 4 changes — re-run `diagnose_v5.js` after editing normalizer to
confirm no regressions in 149 questions.

---

## 11. Known limitations carried forward from Batch 3

These are extraction-time corruption, NOT render-fixable:

- NBME 3 Q21 "99.?°F" — temperature digit lost in extraction
- NBME 4 Q4/Q10/Q12/Q26/Q27/Q29/Q46 — answer-choice letter gaps (e.g., A→D→E with B/C missing) and merged choice texts
- NBME 6 Q18 "Hemog~~n 13g~L" — fully garbled OCR
- NBME 6 Q20 — ECG ASCII art at top of stem
- NBME 6 Q40 "Ban~ 2%" — should be "Bands 2%" (single-instance OCR)
- Complex multi-token subscript jumbles: FEV₁:FVC, Hemoglobin A₁c, "(T concentration" with `4` and `)` separately exiled
- Question-number-prefix decorations: `~ 11.`, `)( 23.`, `■ ·•--■ 17.` — minor cosmetic

These would all be fixed by re-extraction with a corrected pipeline (Q1 above).

---

## 12. What new session should do on resume

1. **Read** `CLAUDE.md` first (binding protocol — ALWAYS).
2. **Read** this file second.
3. **Promote `v4.83-batch3-pending-validation` → `v4.83-batch3-stable`** (same flow as v4.81/v4.82):
   ```
   git tag v4.83-batch3-stable 6c62e53
   git tag -d v4.83-batch3-pending-validation
   git push origin :refs/tags/v4.83-batch3-pending-validation
   git push origin v4.83-batch3-stable
   ```
4. **Ask user** the six questions in §5 (Q1-Q6). Or if user is unavailable / wants defaults, use defaults documented per-question.
5. **Execute Batch 4** per the scope in §3.
6. **Ship as `v4.84-batch4-stable`** (single tag, override accepted in §3).
7. **Delete this file** when v4.84 ships and is verified, OR keep as reference if more batches follow.

---

## 13. Files modified in batches 1-3 (for context)

`index.html` only. Everything else (Python pipeline, css, electron files, other .js files in root and js/) was NOT touched.

Important: `js/quiz.js`, `app.js`, etc. are NOT loaded by `index.html` (no `<script src=>` references). They're dead code at runtime. Don't waste time editing them.

---

## 14. Commit message convention used

`vX.YY: Short title (N fixes)` on the title line, then detailed multi-paragraph
body listing each fix with its number, root cause, and resolution. Static
checks section at bottom. Co-Authored-By line.

Pattern: see commits `a85e319`, `6f77188`, `6c62e53`.

---

End of handoff. Good luck.
