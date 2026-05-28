# BATCH 5 — OME organic generator port to v5.2 (v5.3 handoff)

Read this AFTER `CLAUDE.md` (binding protocol — ALWAYS takes precedence
over anything here) AND `BATCH5_STATUS.md` (architecture context).

This document is the self-contained brief for a fresh Claude session that
needs to port the v5.2 multi-stage organic generator pipeline from the
lecture-slide generator to the OME-PDF generator.

---

## 1. Task scope (very narrow on purpose)

Port the v5.2 multi-stage pipeline to the OME-PDF organic generator
ONLY. Do NOT port to any other generator in this ship.

In scope:
- `tools/ome-pdf-question-generator/generate_ome_questions.py` (direct CLI)
- `tools/shared-ingestion/ome_profile_runner.py` (the path BIC uses;
  this is the one the user's UI actually invokes)
- Both should gain a `--v5` flag and dispatch into the existing
  `tools/lecture-slide-question-generator/v5_pipeline.py`.

Explicitly out of scope (for this ship):
- NBME PDF extraction (verbatim, untouchable)
- AMBOSS extraction (verbatim, untouchable)
- uWorld notes / Mehlman / Anki / Divine audio / Images-tables (their
  legacy single-call generators stay)
- Multi-PDF combine-into-one-test (user explicitly scratched this for
  time; single PDF in → single test out is fine)
- Any refactor of v5_pipeline.py into a shared library (defer until at
  least one more generator gets ported)

---

## 2. What v5.2 actually is

The pipeline lives in
`tools/lecture-slide-question-generator/v5_pipeline.py` (~700 LOC).
It runs ONE question through 10 stages:

| # | Stage | Model | Why |
|---|---|---|---|
| 1 | PLAN | deterministic | largest-remainder allocation of (order, difficulty) slots per the target mixes |
| 2 | KERNEL | gemini-2.5-pro + thinking | designs correctAnswer + discriminatingClueInStem + 4 trap-category distractor designs BEFORE the prose |
| 3 | STEM | gemini-2.5-pro + thinking | writes vignette from the kernel; self-verifies discriminator + sharedFeatures are in the prose |
| 4 | DISTRACTORS | gemini-2.5-pro + thinking | polishes kernel items into clean answer-choice text |
| 5 | CRITIC | gemini-2.5-pro + thinking | per-distractor 0-3 score + adversarial argue-for-each + literal-clue verification |
| 6 | TARGETED REGEN | gemini-2.5-pro + thinking | replaces only the weak distractor(s); re-critics once |
| 7 | LENGTH PARITY | deterministic | keeps choices within 1.30x median length |
| 8 | IMAGE ROUTING | gemini-2.5-flash | short-circuited when imageOpportunity=='none' or no images |
| 9 | ASSEMBLE | deterministic | canonical app-ready shape with per-Q correct-position shuffle |
| 10 | GLOBAL GATE | deterministic | batch-level A-E distribution gate (≥20 questions) |

The 4 trap categories the kernel enforces:
- `COMPETING_DIAGNOSIS`
- `RIGHT_IDEA_WRONG_TARGET`
- `NEXT_STEP_WRONG_PHASE`
- `CONTRAINDICATED_OR_COMORBID_TRAP`

Hard-rejected if two distractors share a category.

Adversarial outcomes per distractor:
- `STRONG_DEFENSE` → competes too well → reject question
- `WEAK_DEFENSE` → target zone → accept
- `NO_DEFENSE` → too weak → regen this slot

Audit (`v5_audit.py`) fails if:
- >2% STRONG_DEFENSE (multi-correct risk)
- >10% NO_DEFENSE (too-weak distractors)
- >10% of questions miss one of the 4 trap categories
- >5% of questions violate length parity (max/median > 1.30)
- Plus the v5.0 gates: answer position 14-26% per A-E (n≥20),
  order mix within ±8pp, difficulty mix within ±10pp,
  stem avg ≥600 chars

Sample v5.2 smoke output (3 Turner-syndrome questions, in
`output_json/v5_debug/Q*.json`):
- 2/3 critic verdict = accept with all 4 distractors at score 3
- 1/3 surfaced a revise_full bug now fixed in the orchestrator
- Trap-category coverage 100% on all 3
- Answer positions: B, B, E (no A-bias on n=3)
- Stem avg 779 chars

---

## 3. What the OME generator currently does

### Direct path (`tools/ome-pdf-question-generator/generate_ome_questions.py`)

CLI:
```
python3 generate_ome_questions.py --input-file input_pdfs/lesson.pdf [--dry-run]
```

It:
1. Reads the PDF via `pdfplumber` (text), `PyMuPDF` (figures), `pdfplumber` tables.
2. Concatenates the text into a single big string per chunk.
3. Calls Gemini once with `prompts/ome_to_questions_prompt.txt` to author
   `--questions-per-file` questions in a single call.
4. Normalizes the response into app-ready JSON.

This is the LEGACY single-call generation pattern — same family of
problems as the lecture generator pre-v5.0 (A-bias, weak distractors,
short stems, no order/difficulty stratification).

### BIC path (`tools/shared-ingestion/ome_profile_runner.py`)

This is what the user's UI actually invokes. The BIC manifest dispatches
to this runner. CLI:
```
python3 ome_profile_runner.py --mode generate --input-file <pdf> --limit 0
```

It uses the same single-shot Gemini call pattern but produces output
under `tools/shared-ingestion/output/ome_app_ready_live/`.

### The prompt

`tools/ome-pdf-question-generator/prompts/ome_to_questions_prompt.txt`
starts with *"You are a Step 2 CK question writer. Your job is to convert
OME (Online MedEd) video lesson content into original NBME-style
multiple-choice questions."* — that confirms it's organic Gemini
authorship (not extraction), so v5 is the right fix.

Despite the prompt saying "video lesson content," the actual input is
**the PDF for each OME video lesson** — the user extracts the PDF from
OME and the tool processes that PDF. The video itself is never touched.

---

## 4. The port itself — step-by-step plan

### Stage A: Read the OME normalization code (45 min)

For each of the two runners:
- Find where the "allocation" equivalent is built.
- Find where Gemini gets called.
- Find what the source-specific context looks like (extracted text? chunked
  sections? slide headers? bullet points?).
- Identify what would map to the v5 `allocation` shape:
  - `slideId`            (probably a chunk ID or page number)
  - `questionCount`      (the per-allocation count)
  - `allowedMedicalTerms` (extracted concepts/keywords)
  - `allowedDistractorPool` (often the same as terms + related)
  - `slideContext`       (the relevant slide/chunk content)
  - `slideImages`        (any extracted figures with metadata)

### Stage B: Write the OME → v5 adapter (60-90 min)

Add a new function in EACH runner (or a shared helper):
```python
def build_v5_allocations(ome_normalized_chunks: list[dict]) -> list[dict]:
    ...
```

That converts OME's chunk format into the v5 allocation shape. Each
chunk becomes one allocation; the per-chunk question count comes from
the legacy allocation logic (or a simple division of total questions
across chunks).

### Stage C: Wire `--v5` flag and dispatch (15-20 min)

In both runners, add:
```python
parser.add_argument("--v5", action="store_true", help="Use v5.2 multi-stage organic pipeline.")
parser.add_argument("--v5-order-mix", default="0.25,0.45,0.30")
parser.add_argument("--v5-difficulty-mix", default="0.30,0.45,0.25")
parser.add_argument("--v5-seed", type=int, default=0)
```

When `--v5` is set:
```python
sys.path.insert(0, str(REPO / "tools" / "lecture-slide-question-generator"))
import v5_pipeline as v5
allocations = build_v5_allocations(...)
questions = v5.generate_v5(
    normalized_payload={"sourceFile": str(input_file)},
    allocations=allocations,
    memory={},
    target_order_mix=parse_mix(args.v5_order_mix, ["first_order","second_order","third_order"]),
    target_difficulty_mix=parse_mix(args.v5_difficulty_mix, ["easy","medium","difficult"]),
    seed=args.v5_seed,
)
# Then write out questions in the same canonical app-ready shape
# that the legacy path produces.
```

If v5 raises, log a warning and fall through to legacy.

### Stage D: Static check (10 min)

```
python3 -m py_compile tools/ome-pdf-question-generator/generate_ome_questions.py
python3 -m py_compile tools/shared-ingestion/ome_profile_runner.py
```

### Stage E: Smoke test (45 min)

Use a small OME PDF — there's `tools/ome-pdf-question-generator/input_pdfs/test_ome_mood_disorders.pdf` or `Test OME.pdf` already present. Run:

```
cd tools/ome-pdf-question-generator
GEMINI_BACKEND=vertex python3 generate_ome_questions.py \
  --input-file input_pdfs/Test\ OME.pdf \
  --v5 --v5-seed 7
```

Expected: 3-5 questions land in the output JSON. Run audit:

```
python3 ../lecture-slide-question-generator/v5_audit.py output_json/app_ready/<test>_app_ready.json
```

Verify:
- All audit gates pass
- v5_debug/Q*.json artifacts present per question
- Trap categories used = 4 distinct per Q
- Answer positions not 100% A

Repeat for the BIC runner:

```
GEMINI_BACKEND=vertex python3 tools/shared-ingestion/ome_profile_runner.py \
  --mode generate --input-file tools/ome-pdf-question-generator/input_pdfs/Test\ OME.pdf \
  --v5 --limit 0
```

### Stage F: BATCH5_STATUS.md update (15 min)

Add a v5.3 section documenting the OME port. Keep the trap-category +
adversarial architecture references; just note that OME is now covered.

### Stage G: .app rebuild + MD5 verify (10 min)

```
npm run electron:build:mac
md5 -q tools/ome-pdf-question-generator/generate_ome_questions.py \
       dist/mac-arm64/shamsulalamx.app/Contents/Resources/app/tools/ome-pdf-question-generator/generate_ome_questions.py
```

### Stage H: Commit + tag + push (10 min)

Commit message should reference:
- Why the port (user's request after seeing v5.2 land for lecture)
- What stages are covered (entire v5.2 pipeline)
- Scope explicitly excludes (NBME, AMBOSS, other organic gens)
- Smoke test result summary

Tag: `v5.3-batch5-stable`.

---

## 5. CLAUDE.md compliance notes

- The Drive/persistence/timer items from Batch 4 are NOT in scope here.
- I cannot click-through test the Electron app, but the user has already
  signed off on the per-session `-stable` override for Batch 5. The
  bundle MD5 source↔bundled match is the verification ritual.
- Per-Q debug artifacts under `output_json/v5_debug/` should be ignored
  by git (already in `.gitignore` as of v5.2).
- The legacy single-call path stays intact as a fallback if `--v5` is
  not passed.

---

## 6. Smoke test allocation reference (Turner-syndrome v5.2 sample)

For reference, the v5.2 smoke test used this allocation shape (from
`/tmp/v5_2_smoke_alloc.json` if it still exists on disk; otherwise
reconstruct from `BATCH5_STATUS.md`'s architecture section):

```json
[
  {
    "slideId": "smoke_turner",
    "questionCount": 3,
    "allowedMedicalTerms": ["Turner syndrome", "..."],
    "allowedDistractorPool": ["Klinefelter syndrome", "..."],
    "slideContext": {
      "slideTitle": "Comorbidity screening in Turner syndrome",
      "clinicalFacts": ["Congenital heart defects (bicuspid aortic valve, ...)"],
      "highYield": "Adult women with Turner syndrome require structured surveillance..."
    },
    "slideImages": []
  }
]
```

The OME adapter must produce one of these per chunk it wants to draw a
question from.

---

## 7. Sanity checklist before tagging

- [ ] `--v5` flag wired in BOTH OME runners
- [ ] Default behavior (no `--v5`) is unchanged — legacy single-call path
- [ ] When v5 raises, runner falls back to legacy with a warn()
- [ ] Smoke test produces ≥3 questions with all 4 trap categories
- [ ] v5_audit.py exits clean on the smoke output
- [ ] No A-bias on smoke output (verify Counter of correctAnswer)
- [ ] Bundle MD5 matches source after rebuild
- [ ] BATCH5_STATUS.md updated with v5.3 section
- [ ] Commit message + tag + push complete

---

## 8. If you get stuck

The v5.2 ship commit (`a39eadd`) is the reference implementation.
Lecture-slide generator's `--v5` integration in
`tools/lecture-slide-question-generator/generate_lecture_slide_questions.py`
(see `_V5ConfigSlot` + `_enrich_allocations_for_v5()` + the dispatch
inside `generate_questions()` at line ~1730) is the pattern to copy.

The OME port should be ~80% of the same plumbing with a different
allocation builder.
