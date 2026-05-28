# BATCH 5 — Organic generator quality overhaul (v5)

Branch: `phase12-vertex-migration`
Tag: `v5.0-batch5-stable` (when committed)

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
