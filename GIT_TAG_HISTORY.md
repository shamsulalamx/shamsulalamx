# Git Tag History

Last updated: 2026-05-23

This file documents stable v4 tags from v4.0 through the current head tag `v4.53-uworld-family-review-survivor-stable`. Each entry records the commit, what was added or stabilized, what evidence supports it, and what architectural significance it carries.

## v4.0-images-tables-generator-stable

Commit: `4d96496`

Meaning: Added the initial Images/Tables question generator.

Validated: Images/Tables generator output and packaged import/render/persistence path according to prior handoff evidence.

Architecture significance: Established `q.images[]` plus `FigureStore` as the stable image attachment route.

## v4.1-images-tables-placement-stable

Commit: `dc45b5b`

Meaning: Refined Images/Tables stimulus placement.

Validated: Placement behavior for stem images versus explanation images.

Architecture significance: Clarified direct image routing and avoided competing `metadata.figureAttachments` routes.

## v4.2-images-tables-schema-stable

Commit: `6fb7973`

Meaning: Fixed canonical Images/Tables question schema.

Validated: Canonical fields required by the app importer, including `questionNumber`, `stem`, and `answerChoices`.

Architecture significance: Proved that schema validity and persistence validity are separate checks.

## v4.3-emma-holiday-pediatrics-stable

Commit: `6dbb5d0`

Meaning: Stabilized lecture-slide question generator for Emma Holiday pediatrics.

Validated: Emma Holiday lecture-slide workflow at that milestone.

Architecture significance: Established lecture-slide generator as downstream infrastructure later reused by Emma shared ingestion.

## v4.4-fast-facts-cache-foundation

Commit: `1376d21`

Meaning: Added Fast Facts profile extraction and incremental cache foundation.

Validated: Cache foundation, not semantic generation quality.

Architecture significance: Introduced cache-oriented profile work. Explicit limitation: Fast Facts semantic stability remains unresolved.

## v4.5-amboss-variable-choice-stable

Commit: `8e2eb94`

Meaning: Added AMBOSS extraction and variable-choice support.

Validated: AMBOSS variable-choice behavior.

Architecture significance: Proved that app-ready import/generation must not assume fixed 4-choice questions for all sources.

## v4.6-batch-import-amboss-live-stable

Commit: `ba1ddcb`

Meaning: Added Batch Import Center foundation and AMBOSS live import path.

Validated: BIC foundation with AMBOSS live path.

Architecture significance: Introduced registry-driven Electron/Python batch orchestration.

## v4.7-batch-import-gemini-env-stable

Commit: `cbccb67`

Meaning: Propagated Gemini environment to batch import jobs.

Validated: Batch jobs can access required Gemini environment when launched by Electron.

Architecture significance: Kept Gemini key handling in Electron/Python runtime boundaries rather than renderer storage.

## v4.8-batch-import-nbme-stable

Commit: `49809fc`

Meaning: Added NBME PDF batch import orchestration.

Validated: NBME BIC orchestration path.

Architecture significance: Extended BIC beyond AMBOSS and proved multi-stage source orchestration.

## v4.9-batch-import-orchestration-stable

Commit: `90b8b69`

Meaning: Hardened Batch Import Center orchestration.

Validated: More reliable job orchestration and reporting.

Architecture significance: BIC became a reusable orchestration surface rather than a single-source wrapper.

## v4.10-shared-ingestion-foundation

Commit: `ed5281b`

Meaning: Added shared normalized chunk ingestion layer.

Validated: Shared schema and adapter foundation.

Architecture significance: Started the profiles-not-pipelines transition.

## v4.11-emma-shared-ingestion-profile-stable

Commit: `838feea`

Meaning: Routed Emma Holiday through shared ingestion profile.

Validated: Emma shared profile entry through normalized chunks.

Architecture significance: First profile-style source using shared ingestion before existing downstream generation.

## v4.12-mehlman-shared-ingestion-live-stable

Commit: `4c6874e`

Meaning: Added Mehlman shared-ingestion batch import profile.

Validated: Mehlman shared-ingestion live profile.

Architecture significance: Extended profile architecture to text-heavy PDF sources with figures/tables.

## v4.13-bic-existing-output-import-stable

Commit: `5735e33`

Meaning: Added BIC existing-output validation mode.

Validated: BIC can skip generation, use an existing valid app-ready JSON, validate/import it, score, and persist after reload.

Architecture significance: Separated BIC wiring proof from source generation quality.

## v4.14-emma-normalized-chunk-downstream-stable

Commit: `03bc095`

Meaning: Added Emma normalized-chunk downstream consumption.

Validated: Emma downstream can consume normalized chunk bundles and preserve provenance.

Architecture significance: Completed the Emma shared-ingestion downstream handoff while leaving live semantic validation as a separate concern.

## v4.15-images-tables-profile-stable

Commit: `f79e3b9`

Meaning: Added Images and Tables shared-ingestion profile.

Validated: Image/table normalized chunks, OCR extraction, asset classification, attachment-first app-ready cards, BIC auto-import, packaged image/table rendering, `FigureStore` persistence, scoring, and reload persistence.

Architecture significance: First validated multimodal profile-style source.

## v4.16-anki-dry-run-bic-stable

Commit: `7e67a08`

Meaning: Added the validated Anki dry-run BIC profile milestone.

Validated: Shared-ingestion normalized Anki text chunks, selected-input dry-run handoff, active BIC dry-run orchestration, visible dev and packaged auto-import, quiz rendering, reload persistence, and score history persistence.

Architecture significance: Proved a dry-run-only BIC profile can reuse an existing wrapper without claiming live Gemini semantic quality.

## v4.19 → v4.30 (Intervening milestones)

The Anki, OME, and Divine Transcript dry-run BIC milestones plus assorted source-specific stabilizations were tagged in the v4.17–v4.30 range during Phase 7–10 work. Run `git tag --list 'v4.*' --sort=version:refname` for the exact set on this clone; some intermediate tags may only exist locally and are documented in their individual commit messages.

## v4.31 → v4.37 (BIC durability hardening)

| Tag | Meaning |
|---|---|
| `v4.31-bic-durable-output-root-stable` | Each BIC job gets a durable per-job output root under app userData. |
| `v4.32-bic-durable-generation-queue-stable` | Generation queue persists across Electron restarts. |
| `v4.33-bic-queue-visibility-stable` | Queue UI surfaces job state, retries, and pending work. |
| `v4.34-organic-lecture-review-drafts-stable` | Organic lecture-slide review draft writer landed. |
| `v4.35-review-draft-survivor-import-stable` | Reviewed survivors can be imported after manual approval. |
| `v4.36-unified-recovery-contract-stable` | `organic-generator-recovery-v1` metadata contract added. |
| `v4.37-mehlman-durable-output-stable` | Mehlman outputs route to the durable job output root. |

## v4.40-phase10c-survivability-stable

Commit: `5f1cffc`

Meaning: Phase 10C survivability layer for the Batch Import queue system.

Validated:

- single-instance Electron lock,
- queue corruption preservation,
- filesystem-first queue/history reconciliation,
- completed-job protection from filesystem artifacts,
- durable `<outputRoot>/process_registry.json`,
- guarded process-group cleanup,
- startup cleanup for stale tracked runner PIDs,
- rebuilt packaged app parity with current `electron/main.js`.

Architecture significance: Established the surviving-queue baseline that all later v4.41+ work builds on.

## v4.41 → v4.47 (Phase 11 Fast Facts stabilization)

| Tag | Meaning |
|---|---|
| `v4.41-per-question-review-draft-stable` | Per-question review draft wiring with manual approve / reject / import flow. |
| `v4.41-phase11-generation-correctness-stable` | Phase 11 generation correctness hardening. |
| `v4.42-fastfacts-packaged-path-hotfix-stable` | Packaged Fast Facts path crash hotfix. |
| `v4.42-source-type-switching` | Allow source type switching with queued files. |
| `v4.43-fastfacts-limit-removal-stable` | Removed unintended Fast Facts generation caps. |
| `v4.44-fastfacts-generation-completion-stable` | Fast Facts generation completion stabilized. |
| `v4.44-phase11-observability-stable` | Phase 11.7 observability plus unified chunk contract system. |
| `v4.45-fastfacts-review-only-completion-stable` | Fast Facts review-only completion handling. |
| `v4.46-fastfacts-reviewed-import-after-auto-import-stable` | Reviewed Fast Facts import allowed after auto-import. |
| `v4.47-emma-pdf-batch-import-stable` | Emma PDF batch import routing stabilization. |

Some adjacent tags share the same major version (e.g. two `v4.41-*` and two `v4.44-*`) because related but separately validated work was tagged independently rather than collapsed. The HEAD tag of each major number is the safest rollback point unless a specific entry above is required.

## v4.48-lecture-explanation-tables-stable

Commit: `f3b2bc9`

Meaning: Lecture-slide explanation panel now renders structured tables (`q.tables` / `q.metadata.tables`) inline instead of the placeholder line `"Table used for explanation only: <tableId>"`.

Validated:

- table extracted into `q.tables` / `q.metadata.tables` via the existing import path,
- packaged `shamsulalamx.app` renders a 3-column / 3-row HTML table in the explanation block for the Test_Emma fixture,
- placeholder line no longer emitted by `build_explanation_sections`,
- section heading renamed `"Slide Figures and Tables"` → `"Slide Figures"`,
- `renderExplanationTablesInto` wired into both Quiz IIFE and `window.buildExplanationHTML`.

Not validated by this milestone:

- per-question table render across all Emma decks (one Test_Emma fixture was tested at this tag; broader Emma deck coverage came in the v4.49 run which produced 4 questions with inline tables on a separate live run).
- the lecture-slide chunk-planning silent-loss issue diagnosed alongside this milestone was resolved separately at v4.49.

Architecture significance: Removes a long-standing renderer gap where extracted table content was discarded in favor of a textual reference. Establishes `q.tables` as a first-class renderer input alongside `q.images` and `q.explanationImages`.

## v4.49-lecture-chunk-recovery-stable

Commits: `1c1f744` + `6c0ce4f`.

Meaning: Two complementary fixes to the lecture-slide generator that close the chunk-planning silent-loss bug diagnosed on 2026-05-23, without re-introducing the budget-runaway risk of a naive strict-count flip.

Validated (field, BIC live run on Test_Emma, job `batch-mpis1xxn-c0i3id`):

- 18 allocated → 17 generated (94.4%) in a single live BIC run.
- Targeted recovery loop fired for each of 5 short-returning slides (s0001, s0002, s0004, s0007, s0008).
- 4 of the 5 recovered to allocated count.
- The 5th (s0008) stopped cleanly on a Gemini network timeout at attempt 1/2 via the existing `is_network_failure` check — no pointless retries.
- Total runtime 369.8s for the full 13-slide deck (vs the prior naive-fix run that ended with 0 questions in 148s).
- BIC auto-imported the result as "Test Emma Lecture Questions" with no errors.
- 4 imported questions carry inline `q.tables` content, exercising the v4.48 table renderer end-to-end in the same run.

Validated (field, earlier depleted-credits run, job `batch-mpirtu3n-1cfsur`):

- Single HTTP 429 caught on chunk1 attempt0.
- `is_quota_failure` predicate fired, `_QUOTA_EXHAUSTED` latch set.
- All subsequent retries and chunks skipped immediately.
- Runtime 10.5s vs the prior naive-cascade's 148s on the same input.
- No retry cascade, no budget runaway.

Validated (offline):

- `is_quota_failure` correctly classifies HTTP 429 / `RESOURCE_EXHAUSTED` / "prepayment credits are depleted" as quota failures and rejects normal validation/network errors.
- `mark_quota_exhausted` / `reset_quota_state` flip the latch idempotently.
- `MAX_RECOVERY_ATTEMPTS_PER_SLIDE` = 2.

Architecture significance: Establishes a bounded, quota-aware, source-aware retry/recovery pattern for organic generation. Worst-case extra API cost is `len(allocations_with_questions) * MAX_RECOVERY_ATTEMPTS_PER_SLIDE` — predictable and small. The same pattern (predicate + latch + targeted per-unit recovery instead of recursive sub-chunking) is portable to other source-specific generators that may share the silent-loss class of bug.

Not validated by this milestone:

- OME, Mehlman, NBME, and Divine generators have separate code paths and have NOT been audited for the same silent-loss class. See `NEXT_STEPS_PRIORITY.md` item 0b.
- The 2-attempt recovery cap is tuned for a small deck like Test_Emma. Heavier decks may benefit from a higher cap; default should hold for most cases.

## v4.50-fastfacts-review-merge-stable

Commit: `64a8e14`

Meaning: Two fixes to the Fast Facts review-survivor import path that close UX bug #1 (separate parallel test for reviewed-accepted questions) and schema bug #2 (missing explanations for wrong answer choices in reviewed survivors). Together these make the reviewed-accepted questions land where the user expects (the same auto-imported test) and render the full explanation panel the canonical schema promises.

Validated (field, user-reported small Fast Facts PPTX BIC live run after applying the fix):

- 1 validated question auto-imported as a new test.
- 2 reviewed questions appended to that same test on accept.
- All 3 questions visible together in one library test.
- Reviewed-accepted questions render full Correct Answer Explanation + Incorrect Answer Explanation + Educational Objective sections.

Implementation:

- `electron/main.js`: new `assembleReviewedQuestionExplanationSections(question)` and `canonicalizeReviewedSurvivorQuestion(question, offset)` helpers. The `write-accepted-review-survivors` IPC handler maps each accepted question through the canonicalizer before serializing the survivor JSON. Output now carries assembled `explanationSections[]` plus empty `figureRefs` / `images` / `explanationImages` / `tables` arrays.
- `index.html`: `importValidatedBatchOutputJsonText()` accepts a new `appendToTestId` destination option. When set and the test exists, the new questions are renumbered to continue from the existing question count and merged via `DB.updateTest()` instead of `DB.createTest()`. `_persistLandingJsonInlineImages` then runs against the merged test so `FigureStore` keys stay unique per `(testId, questionNumber)`. Falls back to creating a new test (with a status warning) if the referenced test was deleted between auto-import and review-import.
- `index.html`: `importAcceptedBatchReviewQuestions()` passes `appendToTestId = job.importedTestId || job.report.importedTestId || job.report.acceptedSurvivorsImportedTestId` so the reviewed survivors merge into the existing per-job test.

Architecture significance: Establishes the survivor write path as a canonical-schema producer, not a raw-Gemini passthrough. Same pattern applies to any future review path for OME, Mehlman, NBME, Divine — if their survivors carry raw fields they will need an analogous canonicalizer.

Not validated by this milestone:

- The migration path for tests already imported via the buggy pre-v4.50 review-survivor path is forward-only. Those orphan tests still have empty `explanationSections[]` and live in their own library entry. Recovery requires either re-running the source through BIC with the new build or running a one-shot recovery script over the existing `accepted_survivors_app_ready.json` files in the affected BIC job dirs.
- Append behavior was tested with 1 + 2 = 3 questions. Larger appends (10+ reviewed questions into a 20+ question existing test) have not been stressed.

## v4.51-stem-quality-and-ome-live-stable

Commits: `4b2d847` (stem-quality fix) + `cc290d9` (OME live enablement) + doc commit.

Meaning: Two related fixes landed and field-validated in the same session.

**Stem-quality across organic generators.** The user's first live OME BIC run produced 7 questions whose stems all ended mid-narrative without a one-best-answer question — same class of bug Fast Facts hit previously. The previous fix had landed only in the lecture-slide generator (Fast Facts, Emma, AMBOSS); OME, UWorld, Mehlman, Divine, and Anki had neither the prompt rule nor a stem-quality validator. This tag adds:

- `stem_has_explicit_final_question(stem)` plus helpers in `tools/uworld-notes-question-generator/generate_uworld_questions.py`, wired into the shared `validate_question(q)`. Because OME, Mehlman, Divine, and Anki all `import generate_uworld_questions as _uw` and reuse this validator, all 5 generators are fixed in one place. Failing stems route into the existing repair-retry path; if repair still fails, questions are kept with `extractionWarnings` rather than silently dropped.
- A `STEM FORMAT RULES` block added to all 5 prompt files (`notes_to_questions_prompt.txt`, `ome_to_questions_prompt.txt`, `mehlman_pdf_to_questions_prompt.txt`, `divine_audio_to_questions_prompt.txt`, `anki_notes_to_questions_prompt.txt`). Same wording as the lecture-slide prompt: every stem must end with a clear final question sentence ending in `?`, with acceptable wording examples.

**OME live generation through BIC.** The `ome_pdf` BIC registry entry was previously dry-run only by design. This tag enables live Gemini OME generation:

- `tools/shared-ingestion/ome_profile_runner.py` gained `--mode {dry-run, generate}` following the Emma runner pattern. Old `--emit-app-ready-dry-run` kept as backward-compatible alias. Default `--limit` changed 5 → 0 so live runs process the full PDF. Dry-run and live outputs land in separate subdirs.
- `tools/batch-import-center/pipeline_registry.json` `ome_pdf` entry: `requiresGemini: true`, `liveSteps` invoking `--mode generate --limit 0` with heartbeat 60s, `outputDirectories` covers both subdirs.

Validated (field, user's OME PDF live BIC run, 2026-05-23):

- OME live generation produced app-ready JSON from a small user-supplied OME PDF.
- Every generated question's stem ends with an explicit one-best-answer question sentence ending in `?`.
- Packaged app live BIC auto-import, quiz rendering, and explanation panel all verified in the same run.

Validated (offline):

- `stem_has_explicit_final_question` passes 3 well-formed stems and rejects 4 mid-narrative ones plus a no-question fragment.
- End-to-end `validate_question(bad_q)` returns the expected stem-quality error string.

Architecture significance: Establishes a single shared stem-quality contract across all 6 organic generation paths (lecture-slide + 5 UWorld-wrapping generators). Removes the OME `dry-run only` boundary that had stood since the OME profile shipped. The OME enablement plumbing was authored in a prior cowork session; today's run was the first end-to-end live validation.

Not validated by this milestone:

- Broad OME PDF coverage (only one small user-supplied PDF tested).
- Asset extraction quality for OME PDFs with figures/tables.
- Allocated-vs-generated parity audit for OME (the v4.49 chunk-planning fix has NOT been ported to `generate_ome_questions.py`; see `NEXT_STEPS_PRIORITY.md` item 0b).
- Signed or notarized distribution behavior of the live OME output paths.
- Migration of tests already imported via the buggy pre-v4.51 path is forward-only. Re-run the source through BIC with the new build to get the correct shape; the missing final sentence cannot be inferred from what was emitted.

## v4.52-uworld-chunk-and-token-fix-stable

Commits: `f99ded6` (Anki BIC enablement) + `3772d7a` (UWorld chunking + token fix) + doc commit.

Meaning: Two related fixes that together enable live Anki generation through BIC.

**Anki BIC enablement** — Same OME-pattern fix from v4.51. `tools/shared-ingestion/anki_profile_runner.py` gained `--mode {dry-run, generate}` replacing the implicit gate on `--emit-app-ready-dry-run`. The runner now always invokes the downstream wrapper with the selected mode. `tools/batch-import-center/pipeline_registry.json` `anki_notes` entry now has `requiresGemini: true` and `liveSteps` invoking `--mode generate --limit 0` with 60s heartbeat. Distinct output subdirs for live and dry-run modes.

**UWorld machinery fix** — Two compounding bugs in `tools/uworld-notes-question-generator/generate_uworld_questions.py` that the shared UWorld machinery (used by OME, Mehlman, Divine, Anki, UWorld) carried since the initial implementation:

1. `split_into_chunks()` silently bypassed its own `max_chars=3000` cap. The "paragraph-boundary fallback" re-splits on `\n{2,}` — the same boundary that already produced the segment list. Inputs without double-newlines (Anki .txt exports where each card is one tab-separated line) collapsed to one giant chunk. Now adds a force-slice pass after heading and paragraph splits that slices any remaining oversized chunk at the nearest single-newline boundary, falling back to whitespace, then a hard byte boundary.

2. `_raw_gemini_call()` set `maxOutputTokens=8192`, too tight for chunks that ask Gemini for 15+ questions of full JSON. Raised to 16384 for ~2x headroom. The lecture-slide generator already uses 12000 for comparison and was unaffected.

Field-validated (2026-05-23 user live BIC run on 15-card Anki .txt):

- Pre-fix: 0 questions generated, single chunk of 32,803 chars sent to Gemini which truncated the response at 23 KB.
- Post-fix: 15 questions generated cleanly with proper stems, choices, and explanations.

Offline-validated:

- `split_into_chunks()` on a 281 K synthetic Anki-shaped input with no double-newlines now produces 94 properly-sized chunks (all ≤ 3000 chars). Small inputs still produce 1 chunk.

Architecture significance: The shared UWorld machinery now actually honors its documented `max_chars` contract, removing a class of silent truncation that affected any UWorld-family generator on inputs without double-newline boundaries. The token-cap bump is defensive headroom for cases the chunking can't fully smooth out.

Not validated by this milestone:

- Broad Anki export variation (other languages, complex HTML, media references, `.apkg` files, very large decks).
- The v4.50 review-survivor flow is still lecture-slide-only — UWorld-wrapping generators (Anki, OME, Mehlman, Divine, UWorld) fall back to in-band repair retry; if repair still fails, the question is kept with `extractionWarnings` rather than surfaced for human review. See `NEXT_STEPS_PRIORITY.md` item 0c-anki.
- Allocated-vs-generated parity audit for non-lecture generators is still open (separate concern from this milestone; see `NEXT_STEPS_PRIORITY.md` item 0b).

## v4.53-uworld-family-review-survivor-stable

Commit: `8f213d5` plus the doc commit.

Meaning: Ports the v4.50 review-survivor flow to all five UWorld-wrapping generators (Anki, OME, Mehlman, Divine, UWorld) so that when a question fails BOTH initial validation AND the repair retry, it gets surfaced for human review through the existing BIC review modal instead of being silently included in the app-ready output with `extractionWarnings`.

Implementation (single source change in `tools/uworld-notes-question-generator/generate_uworld_questions.py`):

- New `write_uworld_family_review_draft()` helper writes a `uworld_family_review_draft.json` matching the same schema BIC's `discover_review_draft()` and the renderer's `read-review-draft` IPC handler already expect for the lecture-slide generator (`draftVersion: 1`, `status: "needs_review"`, populated `candidateQuestions[]`, empty `validQuestionIndexes[]`, `reviewItems[]` with per-question error messages and `chunkIndex`).
- New `_resolve_review_dir()` helper picks `BIC_JOB_OUTPUT_ROOT/review` when BIC sets that env var, falls back to `BASE_DIR/review` for standalone CLI. Computed at call time so per-wrapper `BASE_DIR` monkey-patching is honored.
- `call_gemini_with_retry()` gained an optional `needs_review_collector: Optional[List[Dict]] = None` parameter. When set, questions that fail BOTH initial validation AND repair are appended to it (each entry: `{question, errors, chunkIndex}`) instead of being added to the returned `questions` list with `extractionWarnings`. When None, behavior is backward-compatible.
- `process_file()` initializes `needs_review_entries: List[Dict] = []` at the top, always passes it to `call_gemini_with_retry`, and after the chunk loop calls `write_uworld_family_review_draft()` when the list is non-empty. Per-file report gains `reviewDraftPath` and `needsReviewCount` fields.

End-to-end flow when N − K questions pass and K fail repair on a live run:

- N − K go to the app-ready output as before; BIC auto-imports them as a new test.
- K go into the review draft.
- BIC's `discover_review_draft()` picks it up unchanged (it scans `<jobOutputRoot>/review/*_review_draft.json` per its existing logic).
- The renderer's existing BIC review modal surfaces the K candidates.
- User accepts/edits/rejects through the v4.50 review-survivor flow.
- Accepted candidates merge into the same auto-imported test via the v4.50 `appendToTestId` path; the v4.50 `canonicalizeReviewedSurvivorQuestion()` is a pass-through because UWorld-family questions are already in the canonical schema.

No regression for the clean case: if all questions pass, the collector stays empty, no review draft is written, and BIC behaves exactly as at v4.52. Dry-run mode is unaffected (the live branch is the only path that appends to the collector).

Validated (offline):

- `write_uworld_family_review_draft()` with empty input returns None; with 2 entries it writes a valid `uworld_family_review_draft.json` matching the BIC schema (draftVersion, status, jobId, sourceType, candidateQuestions, reviewItems all populated correctly).
- `_resolve_review_dir()` routes to `BIC_JOB_OUTPUT_ROOT/review` when BIC sets that env var, falls back to `BASE_DIR/review` otherwise.
- Syntax check passes.

Architecture significance: Closes the parity gap between the lecture-slide generator and the UWorld-family generators for the review-survivor flow. Both code paths now produce review drafts in the same format, the same location pattern, and the same renderer flow consumes them generically. Future UWorld-family wrappers (a hypothetical new source that uses the same machinery) inherit the review-survivor capability automatically.

Not validated by this milestone:

- The failure path itself. Requires Gemini to fail both initial validation and the repair retry on a live run. The user chose to wait for that to happen organically rather than synthesizing now.
- Per-wrapper coverage: the implementation lives in the shared UWorld machinery, but each wrapping generator (Anki, OME, Mehlman, Divine, UWorld) hasn't been individually exercised with a partial-failure case.
- The renderer/Electron side already handled `*_review_draft.json` files generically (via lecture-slide); no renderer changes were needed. If a UWorld-family-specific renderer affordance is desired later (e.g. a distinct badge), that's a separate enhancement.
