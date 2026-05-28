# BATCH 5 — Organic generator quality overhaul (v5)

Branch: `phase12-vertex-migration`
Tag: `v5.3-batch5-pending-validation` (latest); see version history below.

## Scope (very important): organic-generation only

**v5 changes ONLY the lecture-slide "organic" Gemini-authorship path.
The legacy verbatim-extraction pipelines for NBME PDFs and AMBOSS are
untouched.**

| Path | Code | v5 touches it? |
|---|---|---|
| NBME PDF extraction (verbatim Q + A + explanation from the source PDF) | `tools/nbme-pdf-json-generator/nbme_dual_pdf_runner.py` + `verbatim_patcher.py` | **No.** Verbatim guarantees from Batch 4 (v4.85) remain. |
| AMBOSS extraction (`--amboss-profile`) | branches earlier inside `generate_lecture_slide_questions.py` | **No.** v5 dispatch is gated on `--v5`, which does not engage in amboss mode. |
| uWorld notes (text-only) | `tools/uworld-notes-question-generator/` | **No.** |
| Lecture-slide ORGANIC generation (Gemini authors the stem + distractors from grounded slide concepts) | `tools/lecture-slide-question-generator/` | **Yes.** This is the only path that activates v5 when `--v5` is set. |

How to be sure for any given run:
- Running NBME extraction (e.g. `nbme_dual_pdf_runner.py`): the `--v5`
  flag does not even exist in that script's argparse. Always verbatim.
- Running AMBOSS extraction (`--amboss-profile`): the amboss code path
  branches before the v5 dispatch point, so v5 never activates in that
  mode. Verbatim AMBOSS guarantees preserved.
- Running lecture / Fast Facts / "organic" Gemini generation: v5
  activates only when `--v5` is set; without that flag the legacy
  single-call generator runs.

The verbatim extraction guarantees you have for NBME (every stem,
choice, correctAnswer, and multi-paragraph explanation extracted
directly from the source PDF) and AMBOSS remain in force exactly as
shipped in `v4.85-batch4-stable`.

## Version history (this batch)

| Tag | What |
|---|---|
| `v5.0-batch5-stable` | Initial v5 multi-stage organic generator |
| `v5.0.1-batch5-stable` | Doc clarification: legacy NBME/AMBOSS verbatim paths untouched |
| `v5.2-batch5-stable` | Five distractor-quality upgrades (kernel-first, trap categories, adversarial verify, per-distractor scoring, length parity) |
| `v5.2.1-batch5-stable` | Docs-only handoff ship (BATCH5_OME_PORT_HANDOFF.md + v5.3 plan) |
| `v5.3-batch5-pending-validation` | **OME organic generator port to v5.2.** Adds `--v5` to both OME runners; legacy single-call generator stays as fallback. |

## v5.3 — OME organic generator port

Ports the v5.2 multi-stage pipeline (kernel-first design + 4 trap
categories + adversarial verification + per-distractor scoring + length
parity) to the OME-PDF organic generator. Both the direct CLI
(`tools/ome-pdf-question-generator/generate_ome_questions.py`) and the
BIC profile runner (`tools/shared-ingestion/ome_profile_runner.py`)
gain a `--v5` flag and the related mix/seed flags
(`--v5-order-mix`, `--v5-difficulty-mix`, `--v5-seed`).

Scope explicitly excluded from v5.3 (unchanged from v5.2.1 plan):
- NBME PDF verbatim extraction (unchanged since v4.85)
- AMBOSS verbatim extraction (the lecture-slide `--amboss-profile` path)
- uWorld notes / Mehlman / Anki / Divine audio / Images-tables (legacy
  single-call generators stay until a later ship)
- Multi-PDF combine-into-one-test (single PDF in → single test out)

### What v5.3 added

```
tools/ome-pdf-question-generator/
├── ome_v5_adapter.py                  # NEW — chunks→v5 allocations,
│                                       #       term/title/fact extraction,
│                                       #       v5→OME field decoration
└── generate_ome_questions.py           # MODIFIED — --v5 flag + dispatch +
                                        #            _process_file_v5() helper
tools/shared-ingestion/
└── ome_profile_runner.py               # MODIFIED — --v5 flag, forwards to
                                        #            downstream generator
```

The adapter does the OME-specific work the lecture-slide
`_enrich_allocations_for_v5()` does for slides: turns the raw chunk text
into the v5 allocation shape (`allowedMedicalTerms`,
`allowedDistractorPool`, `slideContext.{slideTitle, clinicalFacts,
primaryConcepts, secondaryConcepts, highYield, fullText}`,
`slideImages`). Chunks shorter than 200 chars (page headers, stray
fragments) are filtered out before question budget is distributed, so
all generated questions come from substantive content.

### Dispatch & fallback

When `--v5` is set on `generate_ome_questions.py`, the per-PDF loop
calls `_process_file_v5(filepath, questions_per_file, v5_cfg,
report_data)` instead of `_uw.process_file()`. The v5 helper:

1. Extracts raw text via the OME-patched extractor (pdfplumber).
2. Chunks via `_uw.split_into_chunks()` (same as legacy).
3. Builds v5 allocations via `build_v5_allocations()`.
4. Calls `v5_pipeline.generate_v5(...)` with the configured mixes/seed.
5. Decorates v5 questions with legacy OME fields (`id`,
   `sourceQuestionNumber`, `retrievalTag`, `reviewPearl`) so the
   resulting app-ready JSON matches the OME schema downstream
   consumers expect.
6. Wraps via the existing OME-patched `_uw.build_app_ready_json()`
   (which still sets `sourceFormat: "ome-pdf"`).
7. Writes the same `<stem>_app_ready.json` artifact at the canonical
   path. Adds `pipeline: "v5.2-organic"` so downstream consumers can
   distinguish v5 output from legacy.

If the v5 pipeline raises (no eligible chunks, Vertex transient
failure, kernel rejection cascade), the wrapper logs a warning and
falls through to the legacy `_uw.process_file()`. Default behavior
(no `--v5`) is unchanged from v5.2.1 — the legacy single-call path runs
exactly as it did before this ship.

The BIC profile runner appends `--v5 --v5-order-mix … --v5-difficulty-mix … --v5-seed …`
to the downstream `generate_ome_questions.py` subprocess command when
`--v5` is set on its own CLI. In `--mode dry-run` the v5 flag is a no-op
(no Gemini calls happen at all on the dry-run path).

### How to generate an OME test with v5

Direct CLI:
```
cd tools/ome-pdf-question-generator
GEMINI_BACKEND=vertex python3 generate_ome_questions.py \
  --input-file input_pdfs/Lesson.pdf \
  --generate --v5 \
  --questions-per-file 15 \
  --v5-order-mix 0.25,0.45,0.30 \
  --v5-difficulty-mix 0.30,0.45,0.25 \
  --v5-seed 0
```

BIC path (matches what the UI invokes):
```
GEMINI_BACKEND=vertex python3 tools/shared-ingestion/ome_profile_runner.py \
  --input-file tools/ome-pdf-question-generator/input_pdfs/Lesson.pdf \
  --mode generate --v5 --limit 0
```

Audit the result with the v5.2 gate (no OME-specific changes needed —
the audit reads `_v5_2` metadata directly from every question):
```
python3 tools/lecture-slide-question-generator/v5_audit.py \
  <output_root>/app_ready/Lesson_app_ready.json
```

### Cost & latency

Same as v5.2 lecture-slide: ~$0.18–0.22 per question, ~4–5 min
sequential. A 15-question OME test ≈ $2.70–3.30 and ~60–75 min wall
time. The legacy single-call OME path is ~10–20× cheaper but produces
NBME-quality output only intermittently — for any test the user plans
to keep, the v5 cost premium is justified.

### Smoke test (v5.3 ship)

Input: `tools/ome-pdf-question-generator/input_pdfs/test_ome_mood_disorders.pdf`
(1565 chars extracted, 1 chunk after the 200-char filter).
Command (direct CLI):
```
GEMINI_BACKEND=vertex python3 tools/ome-pdf-question-generator/generate_ome_questions.py \
  --input-file tools/ome-pdf-question-generator/input_pdfs/test_ome_mood_disorders.pdf \
  --generate --v5 --v5-seed 7 --questions-per-file 3 \
  --output-dir /tmp/ome_v5_smoke
```

Smoke results (3 questions produced in 376s — ~125 s/Q, well inside the
v5.2 envelope):

| Q | Answer | Target | Achieved | Stem | Verdict | All 4 traps | Distractor scores | Parity |
|---|---|---|---|---|---|---|---|---|
| 1 | B | third_order/difficult | third_order/difficult | 1248 chars | accept | yes | 3/3/3/3 WEAK_DEFENSE | 1.09 (ok) |
| 2 | E | first_order/easy | first_order/easy | 694 chars | accept | yes | 3/3/3/3 WEAK_DEFENSE | 1.32 (fails 1.30 cap by 0.02) |
| 3 | C | second_order/medium | second_order/medium | 876 chars | accept | yes | 3/3/3/3 WEAK_DEFENSE | 1.02 (ok) |

Answer positions B/E/C: no A-bias on this smoke. Order/difficulty
coverage: 1 question per bucket across all 3 order tiers and all 3
difficulty tiers — the v5 PLAN stage's largest-remainder allocation
worked exactly as designed.

`v5_audit.py` run on the smoke output:

- ✓ stem length: avg 939, median 876, all 3 questions ≥600 chars
- ✓ exactly 5 choices in all 3 questions
- ✓ critic verdict: 3/3 accept
- ✓ trap-category coverage: 4 categories per question (12 totals,
  0 incomplete)
- ✓ adversarial outcomes: 100% WEAK_DEFENSE (0 STRONG_DEFENSE,
  0 NO_DEFENSE — the target band)
- "FAIL" — order distribution (first_order 33% vs 25% target,
  second_order 33% vs 45% target): statistical artifact of n=3, not
  a pipeline bug. The PLAN stage produced 1 question per bucket and
  the orderAchieved field matched targetOrder for all 3 questions.
- "FAIL" — difficulty distribution (medium 33% vs 45% target): same
  n=3 artifact.
- "FAIL" — length parity 1/3 (Q2's correct-answer choice at length
  ratio 1.32 vs 1.30 cap, missed by 0.02). v5_pipeline's
  `length_parity_balance()` only trims parentheticals / comma-clauses;
  Q2's "Initiate a selective serotonin reuptake inhibitor (SSRI)"
  had no safe-trim site, and the pipeline left the text intact per
  its design ("quality > parity-by-fabrication" — see v5_pipeline.py).

Pre-existing audit bug found and fixed in v5_audit.py: the order and
difficulty gates (`[2]` and `[3]`) read `_v5` only, while the v5.2
pipeline writes the metadata under `_v5_2`. Without the fix, every
v5.2+ question silently buckets into "unknown" and the gates fail
trivially. The fix mirrors the same `_v5_2`-then-`_v5` fallback the
later gates (critic verdict, trap categories, adversarial outcomes)
already had. The fix would also apply retroactively to any audits
the prior session ran on v5.2-batch5-stable output.

BIC profile runner verification: structural only (arg-forwarding
chain confirmed by simulating argparse without invoking Gemini). A
live BIC smoke run was deferred to stay inside the v5.3 API budget —
the BIC path subprocesses into `generate_ome_questions.py` with the
same CLI flow that the direct smoke validated end-to-end.

### User verification before promoting to `-stable`

Per CLAUDE.md hard constraint #2 (no commit/tag/push without user
verification on the .app), the v5.3 tag remains
`v5.3-batch5-pending-validation` until the user runs an end-to-end OME
generation through the BIC UI and confirms the resulting questions
look correct in the renderer. The test plan:

1. Quit and relaunch the rebuilt .app.
2. From BIC, import an OME PDF (e.g. the same
   `test_ome_mood_disorders.pdf`) with `--v5` enabled.
3. Verify the generated questions render with 5 choices each, stems
   read like NBME vignettes (5–10+ sentences, NBME demographics
   opener), and the test pages through correctly.
4. Confirm a non-OME source type (any other generator) still works
   identically to v5.2.1 — `--v5` should only affect OME.
5. On ✅: tag `v5.3-batch5-stable` and push. On ❌: capture console
   output, diagnose, and reship.

## v5.2 — what changed for distractor quality

Real failure mode the user observed in v5.0: distractors were too weak
and the correct answer was identifiable without engaging the reasoning
task. Three root causes:

1. **Distractor pool was too loose.** `ALLOWED_DISTRACTOR_POOL` was just
   "other terms from the slide" — no curated set of strong competitors
   for the specific correct answer.
2. **Distractors written AFTER the stem.** Real NBME committees design
   the discriminating clue and the trap structure TOGETHER, then write
   a stem that contains exactly the clues needed. We were retrofitting
   distractors against a stem that already gave the game away.
3. **No adversarial pass.** Nothing ever tried to argue "this distractor
   could ALSO be correct, here's why." The critic scored distractor
   *quality* generically (0-3) but didn't stress-test each one.

v5.2 introduces five interlocking fixes:

### A. KERNEL-FIRST DESIGN (architectural)
New `stage_kernel()` runs BEFORE the stem. It outputs:

- `correctAnswerConcept`
- `discriminatingClueInStem` (the SPECIFIC clinical detail the stem must contain)
- 4 distractors, each with: `trapCategory`, `item`, `sharedFeatures[]`,
  `ruledOutBy`, `tempt`

The kernel is the contract for the rest of the pipeline. The stem author
is now *required* to include the discriminating clue and every
distractor's `sharedFeatures` in the prose. Designing the trap structure
upfront mirrors how NBME committees actually work — discriminator and
distractors are designed in lockstep.

### B. TRAP-CATEGORY ENFORCEMENT (4 distinct categories per question)

The kernel must produce 4 distractors from 4 DIFFERENT trap categories:

1. `COMPETING_DIAGNOSIS` — shares chief complaint and 2-3 stem features,
   ruled out by ONE specific clue.
2. `RIGHT_IDEA_WRONG_TARGET` — same management/mechanism class but wrong
   specific drug / test / structure.
3. `NEXT_STEP_WRONG_PHASE` — appropriate action at the wrong point in the
   workup (premature or jumping ahead).
4. `CONTRAINDICATED_OR_COMORBID_TRAP` — textbook first-line that's ruled
   out by an explicit contraindication / comorbidity in the stem.

Hard-rejected if two distractors share a category. This forces structural
diversity rather than 4 vaguely-plausible same-kind items.

### C. STEM-DISTRACTOR CO-DESIGN (stem must satisfy the kernel contract)

The stem prompt now requires:

- The kernel's `discriminatingClueInStem` is literally in the prose.
- Every distractor's `sharedFeatures[]` is literally in the prose
  (otherwise the distractor isn't really tempting).
- No "decorative" data — no labs, imaging, exam findings, or
  comorbidities that aren't either the discriminator, a sharedFeature,
  or standard NBME demographic scaffolding.

The stem JSON output includes `containedDiscriminatingClue` and
`containedSharedFeatures.missing[]`. Any false / non-empty-missing is a
hard pipeline failure — the slot is rejected and a new question is
attempted.

### D. ADVERSARIAL VERIFICATION (embedded in critic)

The critic now performs, for EACH distractor independently, an attempt
to argue THIS distractor is the correct answer:

- `STRONG_DEFENSE` — a clinically valid argument exists. Two correct
  answers. **Critical failure**. Question rejected.
- `WEAK_DEFENSE` — sketchable argument but a specific stem clue rules
  it out. **Target zone**.
- `NO_DEFENSE` — too obviously wrong. **Too weak distractor**.
  Targeted regen.

This catches both failure modes the user noticed: the "obviously wrong"
distractor AND the multi-correct distractor.

### E. PER-DISTRACTOR CRITIC SCORING + LITERAL-CLUE VERIFICATION

The critic now scores each of 4 distractors individually (0-3), and
separately verifies that each `losingReason`'s claimed discriminating
clue is literally present in the stem text. Verdicts now include
`revise_weakest`: regen ONLY the lowest-scoring distractor (one focused
API call) rather than the whole set.

If verdict = `revise_weakest`, `stage_regen_distractor()` produces ONE
replacement distractor in the same `trapCategory` as the rejected one,
prompted with the critic's specific issue. The patched set is then
re-critiqued ONCE. If still failing, the question is rejected.

### F. LENGTH PARITY (deterministic post-process)

A documented test-taking heuristic: the longest answer is often correct.
NBME explicitly counters this. `length_parity_balance()` checks that no
answer choice's text length exceeds 1.30× the median. If the correct
answer or a distractor is too long, it attempts a safe trim (drop a
trailing parenthetical or comma-clause) without changing clinical
meaning. If trimming can't reach the band, the text is left alone and a
warning is recorded — quality > parity-by-fabrication.

## Updated stage flow (v5.2)

```
1.  PLAN         (deterministic)        — target (order, difficulty) per slot
2.  KERNEL       (Pro + thinking)       — correctAnswer + clue + 4 trap designs  [NEW]
3.  STEM         (Pro + thinking)       — write stem; verify clue+features in prose
4.  DISTRACTORS  (Pro + thinking)       — polish kernel items into answer-choice text
5.  CRITIC       (Pro + thinking)       — per-distractor scores + adversarial argue + clue-in-stem check  [NEW]
6.  TARGETED REGEN (Pro + thinking)     — replace ONLY the weakest distractor  [NEW]
7.  LENGTH PARITY (deterministic)       — balance answer-choice lengths to <=1.30x median  [NEW]
8.  IMAGE ROUTING (Flash)               — short-circuit when imageOpportunity=='none' OR no images
9.  ASSEMBLE     (deterministic)        — canonical shape, per-Q correctAnswer shuffle
10. GLOBAL GATE  (deterministic)        — batch-level A-E distribution gate (>=20 Qs)
```

## Files added in v5.2

```
tools/lecture-slide-question-generator/prompts/
├── v5_2_kernel_prompt.txt
├── v5_2_stem_prompt.txt
├── v5_2_distractors_prompt.txt
├── v5_2_critic_prompt.txt
└── v5_2_regen_distractor_prompt.txt
```

`v5_pipeline.py` rewritten to orchestrate the 10-stage flow. `v5_audit.py`
gained three new checks: trap-category coverage, adversarial outcome
distribution (too many STRONG_DEFENSE = multi-correct; too many
NO_DEFENSE = weak distractors), and length parity violation rate.

## Cost / latency

Per question, sequential:

| Stage | Model | Time | Cost (approx) |
|---|---|---|---|
| Kernel | Pro + thinking | ~50 sec | $0.05 |
| Stem | Pro + thinking | ~70 sec | $0.06 |
| Distractors | Pro + thinking | ~50 sec | $0.04 |
| Critic | Pro + thinking | ~60 sec | $0.05 |
| Targeted regen (sometimes) | Pro + thinking | ~30 sec | $0.03 |
| Image route | Flash | ~5 sec | $0.002 |
| **Per Q** | | **~4-5 min** | **~$0.18-0.22** |

50-Q test: ≈ $10 and ≈ 3.5-4 hr sequential. Higher cost than v5.0 but
the quality bump comes from kernel + adversarial; parallelism (the v5.1
cost/speed package we discussed) is the orthogonal lever to bring wall-
clock back down without sacrificing the v5.2 quality gains.

## Backward compatibility

- Files generated by v5.0 carry `_v5` metadata. The audit handles both
  `_v5` (legacy) and `_v5_2` (current) by falling back gracefully.
- The CLI flags (`--v5`, `--v5-order-mix`, `--v5-difficulty-mix`,
  `--v5-seed`) are unchanged. Existing scripts work without
  modification; they now get the v5.2 pipeline.
- The legacy single-call generator path is still intact for cache
  repairs and as a fallback. No code path for NBME/AMBOSS verbatim
  extraction was touched.

## Why this exists

User audit of recent lecture-slide-generator outputs:

- **135 of 136 generated questions (99.3%) had answer position `A` as the correct answer.**
- Stems were 4-5 sentences (NBME stems are 6-12).
- Questions were ~all first-order (recognize→name); no second-order
  (diagnose→manage) or third-order (multi-step layered) questions.
- No difficulty stratification.
- Distractors were weak and same-position-biased.

Root cause:
1. The prompt's JSON-schema example literally hardcodes
   `"correctAnswer": "A"` — the model copies that template at temperature
   ~0.4 for ~99% of outputs.
2. Schema example shows only 4 choices (A-D), no E.
3. Explicit rule: *"Stems must be 4 to 5 sentences."*
4. No question-order targeting in the prompt at all.
5. No difficulty stratification.
6. No critique or revision pass — single Gemini call.

## v5 multi-stage architecture

A new sibling module
`tools/lecture-slide-question-generator/v5_pipeline.py` runs ONE question
through 7 stages instead of one. The legacy single-call generator is
preserved for cache repairs but no new generation should use it.

```
┌─────────────────────────────────────────────────────────────────┐
│ Stage 1: PLAN                                                   │
│   For each allocation's N questions, pick a (order, difficulty) │
│   tuple per slot so the batch matches target mixes              │
│   (largest-remainder method).                                   │
│   Target order_mix:       25% first / 45% second / 30% third    │
│   Target difficulty_mix:  30% easy  / 45% medium / 25% difficult│
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 2: STEM    (gemini-2.5-pro, thinking_budget=-1)           │
│   Input:  ALLOWED_TERMS + slide_context + target_order +        │
│           target_difficulty + rolling memory                    │
│   Output: stem text (5-12 sentences per order spec) +           │
│           correctAnswerConcept (semantic, not a letter) +       │
│           rationale + imageOpportunity + orderAchieved +        │
│           difficultyAchieved (self-classification)              │
│   Prompt: prompts/v5_stem_prompt.txt                            │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 3: DISTRACTORS  (gemini-2.5-pro, thinking_budget=-1)      │
│   Input:  stem + correctAnswerConcept + ALLOWED_TERMS +         │
│           ALLOWED_DISTRACTOR_POOL                               │
│   Output: 4 distractors, each with `losingReason` (one specific │
│           sentence tied to a discriminating clue in the stem)   │
│           and `tempt` (why a less-prepared reader would pick it)│
│   Prompt: prompts/v5_distractors_prompt.txt                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 4: CRITIC  (gemini-2.5-pro, thinking_budget=-1)           │
│   Input:  stem + correct + distractors + target_order +         │
│           target_difficulty + allowed terms                     │
│   Output: 5-dimension rubric score (0-3 each) +                 │
│           anti-pattern list + verdict (accept/revise/reject)    │
│   Threshold: total >= 12 AND no dimension < 2 AND no            │
│              anti-pattern present                               │
│   Revise path: ONE distractor-regen pass with critic notes      │
│   Reject path: question slot returns None (skipped)             │
│   Prompt: prompts/v5_critic_prompt.txt                          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 5: IMAGE ROUTING  (gemini-2.5-flash, thinking_budget=0)   │
│   Input:  stem + imageOpportunity hint + AVAILABLE_IMAGES       │
│   Output: attach (bool) + imageId + placement (stem|explanation)│
│           + reason                                              │
│   Most questions are text-only by design — images only when     │
│   they MEANINGFULLY deepen the reasoning task (ECG, x-ray,      │
│   histology, etc.).                                             │
│   Prompt: prompts/v5_image_routing_prompt.txt                   │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 6: ASSEMBLE                                               │
│   Build canonical app-ready question shape with 5 choices       │
│   (A-E). Correct answer position is shuffled PER-QUESTION via   │
│   the per-Q RNG seed. Each distractor's losingReason and tempt  │
│   land in the Incorrect Answer Explanation body, labeled by     │
│   their final A-E position.                                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Stage 7: GLOBAL DISTRIBUTION GATE                               │
│   For batches of >= 20 questions: count correctAnswer per       │
│   position. If any position is > 26% or < 14% of the batch,     │
│   pick that position's questions and reshuffle until in band.   │
│   Up to 3 reshuffle attempts; logs any residual outliers.       │
└─────────────────────────────────────────────────────────────────┘
```

## CLI integration

The legacy entry point `tools/lecture-slide-question-generator/
generate_lecture_slide_questions.py` accepts new flags:

| Flag | Meaning |
|---|---|
| `--v5` | Use v5 multi-stage pipeline (default for all new generation) |
| `--v5-order-mix 0.25,0.45,0.30` | Override target order mix |
| `--v5-difficulty-mix 0.30,0.45,0.25` | Override target difficulty mix |
| `--v5-seed 0` | Reproducible RNG seed for position shuffling |

When `--v5` is set, the legacy `generate_questions()` function checks
`_V5_CONFIG` and dispatches to `v5_pipeline.generate_v5()` instead of
the single-Gemini-call legacy code path. If the v5 pipeline raises any
exception, the legacy path is used as a fallback (with a `warn()`).

Per-question debug artifacts land under
`output_json/v5_debug/Q####.json` capturing the stem_obj,
distractors_obj, critic_obj, image_route, and final assembled question
— so any post-hoc audit can trace exactly what each stage produced.

## Audit gate

`tools/lecture-slide-question-generator/v5_audit.py` runs after a v5
generation. Reports and gates on:

- **Answer position distribution** — each of A/B/C/D/E must be between
  14% and 26% of the batch when n >= 20.
- **Question order distribution** — each bucket within ±8 percentage
  points of the target mix.
- **Difficulty distribution** — each bucket within ±10 pp of target.
- **Stem length** — batch average >= 600 chars; <10% of stems may be
  shorter than 350 chars.
- **5 choices required** — at most 5% of questions may have fewer.
- **Critic verdict** — reports the accept/revise/reject distribution.

Audit exits 0 by default (informational); pass `--strict` to exit 2
on any failure.

## Cost & latency

Each v5 question makes ~4 API calls:

- Stem      — Pro, dynamic thinking (~$0.06)
- Distractors — Pro, dynamic thinking (~$0.05)
- Critic    — Pro, dynamic thinking (~$0.04)
- Image route — Flash, no thinking (~$0.002)

≈ $0.15 per question, ~2-4 minutes per question sequential. A 50-q
test = ~$7.50 and ~2-3 hours sequential. Parallelism is possible (the
NBME extractor already does it) but not implemented here to avoid
Vertex rate-limit pressure; if needed, run multiple v5 invocations on
different source files concurrently.

## What you come back to

- Branch `phase12-vertex-migration`, HEAD pushed.
- Tag `v5.0-batch5-stable`.
- New files:
  - `tools/lecture-slide-question-generator/v5_pipeline.py`
  - `tools/lecture-slide-question-generator/v5_audit.py`
  - `tools/lecture-slide-question-generator/prompts/v5_stem_prompt.txt`
  - `tools/lecture-slide-question-generator/prompts/v5_distractors_prompt.txt`
  - `tools/lecture-slide-question-generator/prompts/v5_critic_prompt.txt`
  - `tools/lecture-slide-question-generator/prompts/v5_image_routing_prompt.txt`
- Legacy `generate_lecture_slide_questions.py` gained `--v5` and three
  related flags. Default behavior unchanged unless you pass `--v5`.

## How to generate a new test with v5

```
cd tools/lecture-slide-question-generator
GEMINI_BACKEND=vertex python3 generate_lecture_slide_questions.py \
  --generate --v5 \
  --input-file /path/to/lecture.pdf \
  --v5-order-mix 0.25,0.45,0.30 \
  --v5-difficulty-mix 0.30,0.45,0.25 \
  --v5-seed 0
```

After it finishes, audit the output:

```
python3 v5_audit.py \
  output_json/app_ready/<test_name>_app_ready.json
```

Look for zero failures and a roughly-flat answer-position histogram.
