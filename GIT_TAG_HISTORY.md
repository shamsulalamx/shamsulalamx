# Git Tag History

Last updated: 2026-05-24

This file documents stable v4 tags from v4.0 through the current head tag `v4.63-polish-pro-and-critic-stable`. Each entry records the commit, what was added or stabilized, what evidence supports it, and what architectural significance it carries.

## v4.63-polish-pro-and-critic-stable

Commit: bundled source + doc in a single v4.63 commit (see `git log -1 v4.63-polish-pro-and-critic-stable`).

Meaning: Four pipeline-quality upgrades enabled by new Gemini API credits. (1) NBME canonical-polish call (`gemini_polish_question()`) now routes through a new `POLISH_MODEL = "gemini-2.5-pro"` constant — extraction, figure-detection, and gap-recovery stay on Flash. (2) New `_critic_polish_fields()` function gates polish output through deterministic placeholder checks plus a Flash LLM critic; if the gate fails, one regeneration attempt is made with the critic's issues fed back as a fix hint. (3) Figure detection smart-trigger gate removed — every NBME question now gets a figure-detection Gemini multimodal call regardless of stem language or embedded raster size. (4) `MAX_AUTO_QUESTIONS_PER_FILE = 80` cap removed in UWorld density (floor of 8 preserved).

Validated: `python3 -m py_compile` clean on `nbme_dual_pdf_runner.py` and `uworld_profile_runner.py`. Module imports succeed with all expected attributes exposed (`POLISH_MODEL`, `CRITIC_MODEL`, `CRITIC_ENABLED`, `_critic_polish_fields`). `gemini_text` signature verified to accept the new `model: str | None = None` parameter. UWorld density behaviour confirmed via direct call (e.g. 15K chars → 100 questions, previously capped at 80). Env-var toggle `NBME_CRITIC_ENABLED=0` correctly disables the critic at import time. Live pipeline run against a real NBME PDF or UWorld doc is the pending field validation.

Architecture significance: Establishes per-call model routing via a parameterized `gemini_text(model=...)` rather than the previous all-or-nothing global `GEMINI_MODEL` constant — pattern is reusable for other pipelines that want to mix Pro and Flash. Critic is purely additive: a stage 0 deterministic gate (free) plus a stage 1 LLM gate (Flash) with a one-shot regenerate; gracefully no-ops on any critic-internal failure so pipeline behaviour degrades to v4.62 if the critic is broken. Figure-detection liberalization shifts the cost vs. completeness trade-off toward "always check" because budget room now allows it.

## v4.62-quiz-archive-and-icon-stable

Commit: bundled source + doc in a single v4.62 commit (see `git log -1 v4.62-quiz-archive-and-icon-stable`).

Meaning: Added a quiz auto-archive system that copies every finalized app-ready JSON to `<project>/archive/<source-folder>/<subfolder>/<quiz-name>.json` at import time, regardless of import path (Batch Import Center auto-import or landing-page manual JSON import). Restored and redesigned the macOS app icon after an accidental Tier-1 cleanup removal. Freed ~1.3 GB by removing regeneratable build artifacts (`node_modules/`, `dist/`, `build/`, all `__pycache__/`, all `.DS_Store` outside `.git/`, and the empty `test-data:/` typo directory).

Validated: `node --check` clean on `electron/main.js`, `electron/preload.js`, and all inline `<script>` tags in `index.html`. `.app` rebuilt successfully (`dist/mac-arm64/shamsulalamx.app`, 758 MB) with the new `.icns` baked in (SHA256 match confirmed between `build/icon.icns` and `Contents/Resources/icon.icns`). Cleanup validated by the successful rebuild — no missing dependencies surfaced. Archive write path is source-level only; first live generate+import will be the field validation. The archive code is purely additive and `console.warn`-only on error, so worst case is "archive empty when expected to contain something", not "import broken".

Architecture significance: Establishes an Electron-side IPC archive layer (`nbme:archive:write-quiz`) exposed via `window.nbmeDesktop.archive.writeQuiz` that captures finalized `*_app_ready.json` raw text (with embedded `dataUrl` images) before `_persistLandingJsonInlineImages` strips dataUrls during import. Crash-recovery contract: drop any archived `.json` onto the landing-page upload box and the existing `handleLandingJsonFileUpload` path restores the full quiz including images, with zero Gemini calls.

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

## v4.54-uworld-chunk-planning-recovery-stable

Commit: `0c3e389` plus the doc commit.

Meaning: Ports the v4.49 chunk-planning quota-aware retry stop + per-chunk shortfall recovery from the lecture-slide generator to the shared UWorld machinery (`tools/uworld-notes-question-generator/generate_uworld_questions.py`). Closes the silent-loss class for all five UWorld-wrapping generators (Anki, OME, Mehlman, Divine, UWorld) in one source change, mirroring the lecture-slide v4.49 design pattern.

Implementation (single source change):

1. **Quota-aware retry stop.** New `is_quota_failure(error)` predicate covers HTTP 429 / `RESOURCE_EXHAUSTED` / 'prepayment credits are depleted' / 'quota exceeded' / 'rate limit' / 'too many requests'. New `is_network_failure(error)` covers urlopen / timeout / DNS errors (the UWorld machinery had no failure-classification helpers before this). Module-level `_QUOTA_EXHAUSTED` latch with `quota_exhausted()`, `mark_quota_exhausted()`, `reset_quota_state()` helpers. Latch checked at every retry boundary inside `call_gemini_with_retry`: at function entry (skip the call entirely if tripped), in the initial `_raw_gemini_call` exception handler, and in the repair `_raw_gemini_call` exception handler. When the repair call hits quota, the questions that were waiting on it are routed to the v4.53 `needs_review_collector` so they surface for human review instead of being silently dropped.

2. **Per-chunk shortfall recovery.** New `MAX_RECOVERY_ATTEMPTS_PER_CHUNK = 2` constant. After the main chunks loop in `process_file` completes, scan `chunk_stats` for any chunk where `generated < requested`. For each short chunk, make up to `MAX_RECOVERY_ATTEMPTS_PER_CHUNK` focused follow-up calls to `call_gemini_with_retry` asking only for the missing questions. Recovered questions flow through the same `validate_question` + repair + v4.53 needs-review-collector pipeline as the main loop. Quota-aware (bails on first 429). Bounded cost: `len(chunks) * MAX_RECOVERY_ATTEMPTS_PER_CHUNK` extra API calls in the worst case.

`process_file` resets the quota latch at the top of the live branch so two runs in the same process stay independent. Dry-run mode never triggers recovery or appends to the collector (live branch only).

Architecture significance: Closes the parity gap between the lecture-slide generator and the UWorld-family generators for chunk-planning silent loss. Both code paths now have the same predicate / latch / bounded-recovery pattern. NBME PDF generator (`tools/nbme-pdf-json-generator/`) still has its own normalization path and would need its own port of this pattern — listed as remaining 0b work in `NEXT_STEPS_PRIORITY.md`.

Validated (offline):

- `is_quota_failure` correctly classifies HTTP 429 / `RESOURCE_EXHAUSTED` / prepayment-depleted / rate-limit text; rejects normal validation errors and network errors.
- `is_network_failure` correctly classifies urlopen / timeout / DNS.
- `_QUOTA_EXHAUSTED` latch is idempotent across `mark` / `reset` cycles.
- `MAX_RECOVERY_ATTEMPTS_PER_CHUNK = 2`.
- Syntax check passes.

Not validated by this milestone:

- The recovery path itself. Requires Gemini to short-return on a live run, which is probabilistic. User chose to wait for organic occurrence (same posture as v4.53).
- The quota-aware retry stop. Requires Gemini to actually return HTTP 429 mid-run. Was field-validated for the lecture-slide generator at v4.49 with depleted credits; the UWorld-family port shares the same predicate and latch logic but is unverified end-to-end in production.
- NBME PDF generator's chunk-planning is still unaudited (see `NEXT_STEPS_PRIORITY.md` item 0b).

## v4.55-divine-audio-live-stable

Commits: `0b671fc` (source) + `faa7637` (doc).

Meaning: Enables live Divine question generation from podcast audio through Batch Import Center. Closes the boundary where the BIC `divine_transcript` source was transcript-first and dry-run only — audio uploads were rejected by the file picker and `liveSteps` intentionally re-ran the same dry-run handoff.

Implementation (4 source files + 1 UI file):

- `tools/batch-import-center/pipeline_registry.json` — `divine_transcript` entry: relabels to "Divine (Audio + Transcript)", widens `inputExtensions` to `[".txt", ".md", ".mp3", ".m4a", ".wav"]`, flips `requiresGemini: true`, points `liveSteps` at `--emit-app-ready-live` (not the dry-run handoff), keeps `dryRunSteps` text-only, updates notes shown in the BIC UI.
- `tools/shared-ingestion/divine_transcript_profile_runner.py` — splits supported extensions into text/audio sets, renames `selected_transcript` to `selected_input`, adds `is_audio_input()`, refactors `run_divine_generator_dry_run` to `run_divine_generator(input_path, live=True/False)` with mode-aware output subdir and command flag, adds `--emit-app-ready-live` CLI flag, gates audio + dry-run with an exit-2 error so transcription tokens are never wasted, skips the shared chunk pipeline for audio inputs (chunks emerge after transcription), and emits a clear `divine_transcript_audio_input` progress event.
- `tools/divine-audio-question-generator/generate_divine_questions.py` — renames `_resolve_selected_transcript` to `_resolve_selected_input` so `--input-file` now accepts `.txt`, `.md`, `.mp3`, `.m4a`, and `.wav`; adds `_is_audio_input()`; in the `--generate` branch with `selected_input` it now runs the full audio pipeline (Gemini File API upload → poll → transcribe → clean → chunk → generate) when given audio and the text pipeline when given a transcript; `_apply_output_dir` was extended to also redirect `RAW_DIR` and `CLEANED_DIR` so raw and cleaned transcripts land under `<jobOutputRoot>/transcripts/raw|cleaned/` instead of polluting the packaged source tree.
- `index.html` — BIC source dropdown `<option>` and `BATCH_IMPORT_SOURCE_LABELS` cache both relabeled "Divine (Audio + Transcript)".

Architecture significance: The Divine pipeline was the last BIC source still gated to text-only dry-run handoff after v4.51 (OME) and v4.52 (Anki) flipped their analogs to live. With v4.55, every active organic-generation source in BIC has a live path validated against the user's real inputs. The audio path also exercises the Gemini File API for the first time inside a BIC job — prior File API usage in this generator was CLI-only outside BIC's orchestration.

Validated:

- Negative case: `python3 tools/shared-ingestion/divine_transcript_profile_runner.py --input-file "Test Divine.mp3" --emit-app-ready-dry-run` exits 2 with the expected error message ("Audio inputs require live mode").
- Live audio path: `python3 tools/shared-ingestion/divine_transcript_profile_runner.py --input-file "/Users/shamsulalam/Desktop/Test Divine.mp3" --emit-app-ready-live` on the user's 17.2 MB Divine Intervention podcast MP3 (`Test Divine.mp3`). Wall-clock 131s. Stages: Gemini File API upload (1.5s) → file ACTIVE → transcription (31s, 21,890 chars raw) → cleaning (31s, 4,076 chars cleaned) → chunking (2 chunks) → generation (chunk 1 8 questions targeted, chunk 2 7 questions targeted, 7 valid questions emitted total).
- App-ready output shape: `schemaVersion: nbme-gemini-json-v3`, `sourceFormat: divine-audio`, 7 questions, 4 answer choices each, non-empty `retrievalTag` and `reviewPearl` on the sampled question, stem ends with a proper one-best-answer sentence (`stem_has_explicit_final_question` enforced by v4.51).
- Output paths land in the durable job output root: `tools/shared-ingestion/output/divine_app_ready_live/Test_Divine/app_ready/Test Divine_app_ready.json`. Raw and cleaned transcripts under `tools/shared-ingestion/output/divine_app_ready_live/Test_Divine/transcripts/{raw,cleaned}/`.
- `.app` packaging confirmed via `npm run electron:build:mac`: `dist/mac-arm64/shamsulalamx.app` (708 MB) contains the updated `index.html` label, `pipeline_registry.json` with `.mp3 .m4a .wav` extensions and `--emit-app-ready-live` in `liveSteps`, and the updated profile runner + generator scripts.
- User confirmed: "Divine works perfectly!"

Not validated by this milestone:

- Packaged-app live audio run via the v4.55 `.app` (the dev-Electron-equivalent direct invocation was validated; the user is expected to repeat through the new packaged BIC dropdown).
- Long episodes (> ~90 min) that exceed the 120,000-char cleaning cap or the 65,536 transcription token cap — warnings fire but behavior under those warnings is unvalidated.
- Robustness of the question-generation JSON parse on long Gemini responses for the Divine audio path. On the v4.55 test run, chunk 1 (8 questions requested) failed JSON parse after the generator's 3-stage repair, so 7 of 15 targeted questions made it through. Same JSON-truncation class addressed at v4.52 (token cap raised) and v4.54 (chunk-planning recovery); recovery is expected to compensate on subsequent runs but is unverified end-to-end for Divine audio specifically.
- NBME PDF generator's chunk-planning still unaudited (carried forward from v4.54; see `NEXT_STEPS_PRIORITY.md` item 0b).

## v4.56-images-tables-live-stable

Commits: `70999ec` (source) + `3a8aaaf` (doc).

Meaning: Replaces the v4.15 attachment-first Images & Tables BIC path with live per-image Gemini classification + NBME-style question generation, fixes two follow-on bugs surfaced by the first real live runs (multi-file merge across BIC's per-input invocations; double-rendered explanation panel), and tightens the table-placement contract so tables and charts never appear in the question stem.

Before this tag, the BIC `images_tables_source` `liveSteps` invoked the attachment-first stub (`tools/shared-ingestion/images_tables_profile_runner.py`) — the same code path as dry-run — even though a complete Gemini-powered per-image generator existed at `tools/images-tables-question-generator/generate_images_tables_questions.py` from earlier work. Every live BIC run produced boilerplate cards ("Review the attached image. Which statement best describes the source asset preserved by this Images & Tables import card?") with hard-coded answer choices. The user surfaced the gap on 2026-05-23 after a 6-image live BIC run produced one boilerplate question.

Implementation (3 source files + 1 UI file across 2 source commits):

Source commit 1 — live wiring + classifier tightening:

- `tools/batch-import-center/pipeline_registry.json` `images_tables_source` entry: `requiresGemini: true`, widens `inputExtensions` to `[".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"]`, points `liveSteps` at `--mode generate --limit 0` with a 30s heartbeat, updates notes to document the live Gemini contract. Dry-run keeps the attachment-first stub (no Gemini, no API spend).
- `tools/shared-ingestion/images_tables_profile_runner.py`: docstring updated to reflect dry-run-stub + live-Gemini split. New `discover_input_files(input_path)` handles file or directory inputs. New `run_images_tables_generator_live(input_path, output_root)` iterates input files and spawns one `generate_images_tables_questions.py --generate --input-file <image> --output-dir <app_ready_dir>` subprocess per file, emitting `images_tables_downstream_file_{start,complete,failed}` events. The `generate` branch in `main()` now delegates to this function instead of emitting the attachment-first stub.
- `tools/images-tables-question-generator/generate_images_tables_questions.py`: adds `--input-file` for single-image invocations (used by the BIC runner) alongside the existing `--input-dir` mode. Tightens the classifier prompt — "Tables and charts must NEVER appear in the question stem" with no escape hatch; `normalize_classification` defensively re-routes any `stimulusType in {table, graph, chart}` away from `diagnostic_stem_image` to `explanation_only_image` / `explanation_only_table`. `generate()` now redirects `ASSET_DIR`, `LOG_DIR`, and `INTERMEDIATE_DIR` when `--output-dir` is set so a packaged `.app` run does not try to write into read-only resources. `asset_path_for_metadata()` falls back to absolute paths when the asset lives outside `BASE_DIR`.

Source commit 2 — render + merge bug fixes:

- `tools/shared-ingestion/images_tables_profile_runner.py` `merge_per_image_outputs()`: BIC invokes the runner once per input file, so a multi-file job triggers N invocations. Each invocation now (a) renames its fresh per-image outputs to `_per_image.json` so they fall outside BIC's `*_app_ready.json` discovery glob; (b) scans the directory for ALL `*_per_image.json` files including ones from prior invocations in the same job; (c) rewrites a single stable-named `images_tables_combined_app_ready.json` containing every question accumulated so far. The stable filename means later invocations overwrite earlier combined files, so by the time the last input completes exactly one combined `*_app_ready.json` exists and contains every generated question. BIC auto-import then loads the full set in one shot.
- `tools/images-tables-question-generator/generate_images_tables_questions.py` `adapt_question()`: drops the duplicate plain-text `"explanation": explanation,` field — only `correctBlurb` (HTML-escaped) and `explanationSections` (structured) ship now.
- `index.html` `buildExplanationHTML` (both the in-quiz copy and the review-mode `window.buildExplanationHTML` copy): `if (q.correctBlurb) { ... } else if (q.explanation) { ... }` so the two blocks never both render. Backward-compatible: questions with only `correctBlurb` or only `explanation` continue to render exactly as before. Eliminates the duplicate-explanation rendering for any future v2-schema source that populates both fields.

Architecture significance: Closes the last source in the BIC registry that was wired to a deliberate non-Gemini stub for live mode. Every active organic-generation source in BIC now has a live Gemini path validated against the user's real inputs. The accumulating-merge pattern (stable filename + scan-and-merge per invocation) is a new shape that other multi-file BIC sources could reuse if they end up invoked per-input. The renderer guard (`else if`) is a backward-compatible defense that benefits any future source that populates both `correctBlurb` and `explanation`, not just images-tables.

Validated:

- Dev-Electron 4-image test (diagnostic dermatology, vesicoureteral process diagram, water-soluble vitamins table, Weber/Rinne tracing): all 4 classified correctly (1 stem image, 3 explanation), 4 questions emitted in 42s wall-clock, table relegated to explanation panel as required, sample question (water-soluble vitamins) produced a clean pellagra (3 D's: dermatitis, diarrhea, dementia) vignette with niacin/B3 as correct answer.
- Dev-Electron simulation of BIC's per-input invocation pattern (4 sequential runner subprocesses, one per input file): combined file accumulated 1 → 2 → 3 → 4 questions as each invocation ran; exactly one `*_app_ready.json` (the stable combined name) remained in the app_ready dir at completion.
- Packaged `.app` 5-image BIC run (Abdominal CT, abetalipoproteinemia biopsy, alcoholic hepatic steatosis, aortic arch derivatives, Barrett's esophagus): 5 questions imported in a single test, no duplicate explanation blocks, correct stem/explanation placement per image type. User confirmed: "Works flawlessly."

Not validated by this milestone:

- Behavior under Gemini quota exhaustion mid-run. The per-image generator does not yet share the UWorld-family quota-aware retry stop + per-chunk shortfall recovery landed at v4.49 / v4.54.
- Broad real-world Step 2 image variety beyond the validation fixtures (the committed `input_images/` fixtures + the user's "[Medicalstudyzone.com] UW tables and pics" set).
- Recursive large-folder ingestion and deep table parsing — tables are preserved as image attachments in the explanation panel, not parsed into structured rows.
- Old tests that imported v2-schema questions with BOTH `correctBlurb` and `explanation` populated (e.g., the user's 1-question batch-mpiz1bb4-ow7dnc test before this fix) still have the duplicate field stored in their persisted form. The renderer guard means they will render correctly going forward, but the underlying stored data still carries the duplicate `explanation` field. No retroactive fix-up was done.

## v4.57-amboss-deterministic-hybrid-stable

Commits: `9ad47c9` (source) + `0482322` (doc).

Meaning: Full rewrite of the AMBOSS PDF BIC extractor as a **deterministic-first, Gemini-assisted pipeline**. Replaces the prior architecture where every PDF page got its own Gemini call (1 call × 39 pages × ~$0.013 ≈ $0.50 per import, ~9 min wall clock) — a cost the user surfaced as "the current Gemini extraction is unnecessary; the only thing we actually need vision for is the blown-up clinical-image pages."

The investigation showed those AMBOSS QBank PDFs are flattened browser screenshots (no text layer at all — PyMuPDF returns 0 words for every page). Pure deterministic text extraction can't work without an OCR layer. Tesseract OCR on the rendered page PNGs DOES work for the clinical vignette text (`A 13-month-old girl is brought to the physician…`), but it CANNOT read AMBOSS's styled choice letter circles (the "(A)" markers render in a custom font tesseract OCR'd as `@)|`, `©l`, `©)`, `(©)`, etc.). And tesseract definitely cannot identify the GREEN-vs-PINK choice header bars that mark the correct answer on the explanation-reveal page.

So the v4.57 hybrid splits work along OCR's actual capabilities:

**Stage 1 — deterministic, no Gemini.** PyMuPDF page render → tesseract OCR → page classification (`qbank_screenshot` vs `blown_up_image` based on word count + nav pill / choice-shape presence) → stem fingerprinting (first ~70 chars of the OCR'd opener phrase, normalized) → nav-pill `< N / M >` detection with majority-M validation (rejects OCR misreads like "24/8" that arise when tesseract joins adjacent characters).

**Stage 2 — deterministic grouping (union-find).** Two pages connect if they share the same nav-pill question number OR the same stem fingerprint. Adjacent components with matching nav numbers merge. Blown-up image pages with no signal attach to the most recent qbank_screenshot via document-order adjacency — that's how full-page "click to enlarge" clinical images land on the right question's `explanationImages[]`.

**Stage 3a — one Gemini call per question (hybrid).** Each question group ships up to 4 page screenshots to Gemini with a JSON-structured prompt asking for: answer choices A–H, correct-answer letter (identified by GREEN choice header bar), per-choice explanations, educational objective, retrieval tag, review pearl. The Gemini call uses `responseMimeType: application/json` + `maxOutputTokens: 8192` — the user's first live test surfaced two failure modes (Gemini truncating JSON strings at 4096 tokens, and Gemini returning prose like "The provided screenshots show…" instead of JSON); both fixed by the JSON mode + token cap raise.

**Stage 3b — Gemini recovery fallback.** When a group's deterministic extraction returns None (every page misclassified as `blown_up_image` due to OCR failure), one extra Gemini call asks "is there an AMBOSS question in these images? if yes, extract it; if no, return `{status: no_question}`". Recovers questions whose stem OCR catastrophically failed.

**Stage 3c — post-extraction stem dedupe.** OCR variance occasionally fragments a single question into two components (e.g., page 28 OCR'd "A 27-year-old" and page 29 OCR'd "A.27-year-old" produce different fingerprints despite being the same question — the period vs space defeats the stem fingerprint match). After all extraction completes, questions whose normalized stems agree on the first 40 chars are collapsed; the variant with more answer choices wins.

Source changes (single file): `tools/lecture-slide-question-generator/generate_lecture_slide_questions.py`.
- New helpers: `amboss_stem_fingerprint`, `amboss_find_all_choice_bars`, `extract_amboss_stem`, `extract_amboss_choices` (with positional inference fallback for OCR-defeated choice circles), `extract_amboss_choice_explanations`, `detect_amboss_correct_answer`, `derive_amboss_educational_objective`, `_extract_amboss_choices_positional`, `_AMBOSS_choice_anchor_words`, `amboss_gemini_extract_question` (hybrid per-question call), `amboss_gemini_recover_unresolved` (recovery fallback), `extract_amboss_question_deterministic`.
- Renamed: prior Gemini-per-page entry point preserved as `_LEGACY_GEMINI_process_amboss_input` (unused in BIC).
- Rewritten: `process_amboss_input` now runs the deterministic + hybrid pipeline above.
- Extended: `raw_gemini_image_call` accepts optional `response_mime_type` parameter; `decompose_amboss_input` honors `--limit 0` as "no cap" (general-purpose bug fix carried forward from the Phase 1 work).
- Registry (`tools/batch-import-center/pipeline_registry.json`): `amboss_pdf` live step uses `--limit 0`, notes trimmed to a one-line UI-friendly description.

Architecture significance: The first BIC source where the live extraction architecture differs significantly from "one big Gemini call per logical unit." AMBOSS uses tesseract for everything OCR can handle (page classification, grouping, image routing) and Gemini only for the things vision uniquely solves (choice letters defeated by styling, correct-answer color bar, clean per-choice explanations free of sidebar OCR chrome). Other sources where vision is needed for similar reasons (NBME PDFs with embedded figures? UWorld DOCX with inline images?) can reuse this template.

Validated:

- Negative case: `python3 generate_lecture_slide_questions.py --amboss-profile --input-file "Test Amboss.pdf"` without `GEMINI_API_KEY` runs the deterministic stage cleanly and falls back to imperfect deterministic choices (no Gemini calls made).
- Live audio path equivalent: full 39-page Test Amboss.pdf processed end-to-end with `GEMINI_API_KEY` set. 8 question groups identified by union-find. 8 hybrid Gemini calls made (one per question). 0–1 recovery calls depending on run. Post-extraction dedupe collapses any OCR-induced duplicates. Result: 8/8 questions (in good runs) or 7/8 (in worst-case OCR runs where the recovery fallback also misses one — user has accepted this).
- App-ready output: `schemaVersion: nbme-gemini-json-v3`, `sourceFormat: mixed` (AMBOSS uses the lecture-slide canonical adapter), per-question fields include clean stems, A–H choice labels with no OCR chrome, GREEN-bar-derived correct answers (varicella vaccine F, indinavir urolithiasis G, etc.), Gemini-derived educationalObjective + retrievalTag + reviewPearl + per-choice explanations, full-page clinical images attached to the correct explanation panels.
- `.app` packaging confirmed via `npm run electron:build:mac` after the JSON-mode + token-cap fix.
- User confirmed earlier in the session: "everything looks good" after the per-choice/objective/tag/pearl extraction came back clean.

Not validated by this milestone:

- AMBOSS PDFs whose question stems include EMBEDDED clinical images (not just full-page "click to enlarge"). These need NBME-style cropper UI integration — Phase 2 work.
- Broad real-world AMBOSS QBank export variation beyond the single 8-question Test PDF.
- Long QBank exports (50+ questions). The pipeline scales linearly; cost scales linearly at ~$0.01 per question. No upper bound tested.
- Bit-for-bit reproducibility — OCR variance means consecutive runs may extract 7 or 8 questions. Post-extraction dedupe + Gemini recovery bring most runs to 8/8 but a worst-case OCR failure on multiple pages of one question may still land 7/8.

## v4.58-mehlman-tight-focus-stable

Commits: `369cee1` (source) + `384bd4a` (doc).

Meaning: Retargets the Mehlman PDF question generator from coarse 8-12K-char chunks producing 5 generic questions per chunk to tight ~1.5K-char chunks producing 1 grounded NBME-style question per Mehlman fact, with figures attached deterministically by page proximity. Also unblocks two BIC integration bugs that surfaced on the first packaged live run: an out-of-tree `Path.relative_to` crash that silently killed every chunk with figures, and a hardcoded 10-page validation cap in both the profile runner and BIC registry that dropped pages 11+ of every uploaded PDF.

The starting point: a 19-page `Test Mehlman.pdf` ran through BIC's packaged live path produced 20 questions with **zero images** attached. Two of those questions were the only honest signal in that test — the chunk manifest showed 19 figures correctly tracked across chunks, but my v4.58-day-1 attachment helper called `fig_path.relative_to(_BASE)` on a figure path under the writable job dir, while `_BASE` still pointed at the read-only `.app` bundle root. `ValueError: ... is not in the subpath of ...` bubbled to the chunk's `except Exception` and dropped the whole chunk (questions + figures). Eight of 18 chunks had figures, all eight failed, leaving 10 figure-less chunks × 2 q/chunk (profile-runner override) = 20 questions, zero images. The fix catches the ValueError, falls back to `extracted_figures/<name>` as the informational `assetPath`, and routes per-figure failures into `extractionWarnings` so a single bad image cannot take down its sibling figures or the question itself.

Separately, the profile runner and BIC registry both hardcoded `--limit 10`, which the runner translated into `--max-pages 10` for the generator. So a 19-page upload got truncated to pages 1-10 on every import. v4.58 lifts both caps: `--limit` defaults to 0 (unlimited) in the profile runner and the registry args drop `--limit 10` entirely. The runner now omits `--max-pages` when `page_limit == 0` and inherits the generator's "process every page" behavior.

The three "recommended fixes" the user accepted at the top of the session:

1. **Chunk window 8,000–12,000 chars → 1,200–1,800 chars.** Each chunk is intended to cover one discrete Mehlman fact slice. `tools/mehlman-pdf-question-generator/generate_mehlman_questions.py` `_MIN_CHUNK` / `_MAX_CHUNK` retargeted; the existing paragraph-split fallback in `split_pages_into_chunks` extended with a sentence-split fallback because PDF extraction often strips `\n\n` markers from dense Mehlman pages (verified: 15-page `HY Internal Medicine (2).pdf` slice → 39,971 body chars → 33 chunks, avg 1,210, max 1,796, 0 over cap).
2. **`--questions-per-chunk` default 5 → 1.** Paired with the tighter chunks so one chunk → one NBME stem on one fact. Override remains available. `tools/shared-ingestion/mehlman_profile_runner.py` also dropped its `--questions-per-chunk 2` override from the pre-v4.58 era so the BIC live path inherits the new default end-to-end.
3. **Deterministic page-proximity image attachment.** New `_attach_chunk_figures_to_questions` helper attaches every figure from a chunk's `pageStart-pageEnd` range to the chunk's first question via `q.explanationImages[]` + `q.figureRefs[]` (`hasEmbeddedFigure: true`), with `dataUrl` base64-encoded inline. No Gemini multimodal call — pure file-system attachment. Stable per-figure ids: `mehlman_q###_p###_##_<hash>`. Field-verified through the packaged `.app` on `Test Mehlman.pdf`: full 19-page PDF → 36 chunks → 36 questions → 12 questions carrying 23 figures across pages 1, 2, 3, 4, 5, 8, 9, 10, 11, 16, 17, 19, zero chunk failures.

Source changes:
- `tools/mehlman-pdf-question-generator/generate_mehlman_questions.py`: new constants `_MIN_CHUNK=1_200` / `_MAX_CHUNK=1_800`; sentence-split fallback inside the single-page overflow branch of `split_pages_into_chunks`; new helpers `_mime_for`, `_data_url`, `_attach_chunk_figures_to_questions` (with ValueError catch on `relative_to(_BASE)` and per-figure exception isolation); attachment wired into both dry-run and live branches of the chunk loop; stats skeleton gains `figuresAttached`; `--questions-per-chunk` default `5 → 1`.
- `tools/shared-ingestion/mehlman_profile_runner.py`: drop `--questions-per-chunk 2` override; `--limit` default `10 → 0`; omit `--max-pages` from the subprocess call when `page_limit == 0`.
- `tools/batch-import-center/pipeline_registry.json`: `mehlman_pdf` dry-run and live steps no longer pass `--limit 10`; notes updated.

Architecture significance: this is the first BIC source where image attachment is fully deterministic (no Gemini multimodal call) and driven entirely by chunk-to-page proximity already tracked during extraction. The same template applies cleanly to any future PDF source whose figures live on identifiable pages (Mehlman, future text-heavy reference PDFs, NBME PDFs once their extractor is rewritten). Cost stays at the projected ~$1.30 / 300-page Mehlman because no per-image vision call is needed.

Validated:

- Packaged `.app` end-to-end through the profile runner on `Test Mehlman.pdf` (19 pages). Output: 36 chunks (avg ~1,200 chars, max 1,796, 0 over cap), 36 questions (1 per chunk), 12 questions with 23 figures attached spanning pages 1, 2, 3, 4, 5, 8, 9, 10, 11, 16, 17, 19. `extractionWarnings` empty, `pageLimit: 0` in the runner report.
- Sentence-split fallback on `HY Internal Medicine (2).pdf` first 15 pages: 39,971 chars → 33 chunks, avg 1,210, max 1,796.
- Cardiology test fixture (`test_mehlman_cardiology_fixture.pdf`, 13 pages → 20,849 chars) re-chunks to 15 chunks (avg 1,389, max 1,734); page-6 table renders in the explanation panel via the existing table-markdown asset marker path.
- `npm run electron:build:mac` succeeded; packaged generator + profile runner + BIC registry all confirmed to carry the v4.58 changes.

Not validated by this milestone:

- Live Gemini run on a 300-page Mehlman PDF at the v4.58 chunk size. The cost model projects ~$1.30 per import and ~600 questions; only dry-run + chunk-manifest sanity checks have run end-to-end at full size.
- Packaged `.app` live BIC run on `Test Mehlman.pdf` (the dry-run path through the packaged profile runner is validated; the live path uses the same code but spends real Gemini tokens).
- Behavior under Gemini quota exhaustion mid-Mehlman-import (inherited from the v4.54 UWorld-family quota-aware retry stop; not stressed for v4.58 specifically).

## v4.59-uworld-live-stable

Commits: `08862c9` (source) + `d0c5e35` (doc). Follow-up commits on top of the tag (no separate tag — tuning + bugfixes only): `e14e811` (renderer dropdown), `cc8af39` (`.docx` density bug + dep fast-fail + requirements.txt), `5495bff` (density retune to 1 q per 150 chars, MIN 8).

Meaning: First BIC integration of the foundational UWorld notes generator. UWorld was the underlying module every other text-heavy source (Anki, OME, Mehlman, Divine wrappers) had been importing since v4.51, but it had never been wired through BIC itself — the user had no "UWorld" option in the source dropdown despite having UWorld notes ready to import. v4.59 closes that gap by adding the same profile-runner + shared-chunk-emitter integration the four wrappers already used, with three properties tuned to the user's UWorld content:

1. **Text-only.** The user confirmed UWorld notes are "absolutely no images, just text," so the profile runner skips all image/table machinery and the source descriptor declares `asset_policy: none`. No deterministic figure attachment (v4.58), no Gemini multimodal call (v4.56), no figure-extraction pass — just text → chunks → questions.
2. **High-yield density.** The user said "my uworld notes are extremely high yield, so I would like higher question frequency/characters/word/bullets/sentences compared to other sources." The runner auto-scales `--questions-per-file` to `max(MIN_AUTO_QUESTIONS_PER_FILE, chars // DEFAULT_CHARS_PER_QUESTION)` clamped at 80. The day-1 constants (MIN=5 / DEFAULT=500) shipped roughly 3× Mehlman density but the MIN clamp dominated on small files — a 3-page 1,365-char UWorld note produced only 5 questions on the first live import. The user pushed back ("THESE ARE HIGH YIELD MATERIAL, and I would want more rigorous testing") and the constants were retuned to MIN=8 / DEFAULT=150 in follow-up commit `5495bff`. Final density: 1.4 KB → 9 q, 4 KB → 27 q, 10 KB → 66 q, 12+ KB → MAX clamp 80 (cost cap ~$0.16/file). Override via explicit `--questions-per-file N` remains available.
3. **Foundational module gets first-class CLI flags.** The UWorld generator had no `--input-file` or `--output-dir` (only a fixed `input_notes/` scan). v4.59 adds both, mirroring the Anki / Mehlman wrapper pattern, so BIC can drive UWorld directly from outside the source tree (the packaged `.app` resource tree is read-only when run from `dist/mac-arm64/`).

Source changes:

- `tools/uworld-notes-question-generator/generate_uworld_questions.py`: new `_resolve_selected_input` and `_apply_output_dir` helpers; new `--input-file` and `--output-dir` CLI args; the file-discovery branch now uses the selected input when set. Reuses the existing v4.52 + v4.53 + v4.54 chunking, review-survivor, and chunk-planning recovery logic unchanged.
- `tools/shared-ingestion/uworld_profile_runner.py` (new): mirrors `anki_profile_runner.py` / `ome_profile_runner.py`. Runs `run_shared_chunk_pipeline(source_type="uworld_notes", ...)` then `subprocess.run` on the UWorld generator with auto-scaled `--questions-per-file`. Auto-density constants after the `5495bff` retune: `DEFAULT_CHARS_PER_QUESTION=150`, `MIN_AUTO_QUESTIONS_PER_FILE=8`, `MAX_AUTO_QUESTIONS_PER_FILE=80`. Extracts the input text up front via the same UWorld extractor the downstream generator uses (`cc8af39`), so the char count for density math reflects actual text content — NOT raw file byte count, which overcounts `.docx` ~40× because `.docx` is a zipped XML container. Pre-flight dep check fails fast with an actionable `pip install --user python-docx` / `pip install --user striprtf` message when the required parser is missing. Respects `BIC_JOB_OUTPUT_ROOT`.
- `tools/shared-ingestion/source_descriptor.py`: new `uworld_notes` `SourceDescriptor` (modality=text, extraction_style=native_text, generation_style=existing_downstream, asset_policy=none, cache_policy=source_hash).
- `tools/shared-ingestion/pipeline_adapter.py`: new `uworld_notes_to_normalized_chunks` adapter that reuses the UWorld text extractor + heading-aware splitter and emits one normalized text chunk per topic with grounded `topicIndex` + `heading` metadata. Wired into the `emit_normalized_chunks` dispatcher. Added `SUPPORTED_UWORLD_EXTS = {".txt", ".md", ".rtf", ".docx"}`.
- `tools/shared-ingestion/chunk_pipeline.py`: added `uworld_notes` to the `--source-type` allowlist.
- `tools/batch-import-center/pipeline_registry.json`: new `uworld_notes` registry entry with `label: "UWorld Notes"`, `inputExtensions: [".txt", ".md", ".rtf", ".docx"]`, `requiresGemini: true`, dry-run + live steps pointing at the new profile runner, and notes documenting the high-yield density auto-scale.
- `index.html` (`e14e811` follow-up): added `<option value="uworld_notes">UWorld Notes</option>` to the hardcoded BIC source-type `<select>` at line ~2349 and the matching label to `BATCH_IMPORT_SOURCE_LABELS` at line ~8621. The BIC source dropdown is NOT registry-driven — it's a static `<option>` list — so the backend wiring alone did not surface UWorld in the UI.
- `requirements.txt` (new in `cc8af39`): documents the system-Python deps the BIC subprocesses expect (`pdfplumber`, `PyMuPDF`, `python-docx`, `striprtf`, `python-pptx`, `Pillow`). electron-builder does not bundle Python, so this is per-machine setup. Install via `python3 -m pip install --user -r requirements.txt`.

Architecture significance: This is the cleanest BIC source integration to date because the underlying generator (UWorld) was already production-hardened — it had been quietly serving Anki, OME, Mehlman, Divine for months through the v4.51 stem-quality validator, v4.53 review-survivor flow, and v4.54 chunk-planning recovery. v4.59 just exposes it directly through BIC's dropdown rather than via a wrapper. Future text-based sources that don't need source-specific extraction (medical school lecture summaries, mnemonic flashcards, etc.) can mirror this pattern with a 30-line profile runner.

Validated:

- Packaged `.app` live BIC run on real `/Users/shamsulalam/Desktop/Test uWorld.docx` (3-page UWorld note, 1,365 chars of extracted text): user confirmed "everything works perfectly" on the live import. After the `5495bff` density retune: `extractedChars=1365`, `questionsPerFile=9`, `chunkCount=1`, `candidateQuestionCount=9`, `outcome: completed`, no chunk failures.
- Offline dry-run end-to-end on `tools/uworld-notes-question-generator/input_notes/test_cardiology.txt` (1,873 chars, 2 markdown headings): 1 normalized chunk → 8 questions (auto-density clamped to MIN under the retuned constants), `outcome: completed`, no warnings, no errors.
- Offline dry-run end-to-end on a 4,112-char synthetic 5-section UWorld file: 2 normalized chunks → 27 questions (auto-scaled at 1 q per 152 chars under the retuned constants), `outcome: completed`.
- Renderer dropdown surfaces "UWorld Notes" between "Mehlman PDF" and "Images & Tables" after the `e14e811` follow-up.
- `python-docx` 1.2.0 + `striprtf` 0.0.32 + `lxml` 6.1.1 installed via `pip install --user`; `requirements.txt` documents the full system-Python dep set for future-proofing.
- `npm run electron:build:mac` succeeded multiple times across the v4.59 day-1 + 3 follow-up commits; packaged generator + profile runner + adapter + descriptor + chunk_pipeline allowlist + BIC registry + renderer dropdown all confirmed to carry the current state.

Not validated by this milestone:

- `.docx` files with complex formatting (embedded images, complex tables, multiple sections with style overrides). Field validation used a simple 3-page user note.
- `.rtf` files: the `striprtf` path is wired and the dep is installed, but no `.rtf` UWorld notes have been imported.
- Very large UWorld notes (>12 K chars where the MAX clamp of 80 questions engages and effective density drops back to ~1 q per 150 chars). The user has not yet flagged this as a constraint — if it becomes one, MAX or a CLI override would be the next knob.
- Behavior under Gemini quota exhaustion mid-UWorld-import (inherited from the v4.54 UWorld-family quota-aware retry stop; not stressed for v4.59 specifically).

## v4.60-nbme-boundary-and-auto-attach-stable

Commits: `ef34d54` (source) + `8396940` (doc).

Meaning: NBME live BIC import unblocked for NBME Self-Assessment PDFs (the most common user-supplied NBME format), plus automatic stem-image attachment to eliminate the manual cropping workflow the user explicitly flagged as tedious. Two distinct user-facing problems addressed in one milestone because both surfaced from the same first live NBME BIC import attempt on `[Medicalstudyzone.com] Internal Medicine 3 - Answers.pdf`:

1. **Live import failure: "No question boundaries found — cannot chunk."** The NBME chunker's boundary regex required `Item N` at line start. The user's PDF format has `Exam Section : Item 1 of 50 National Board of Medical Examiners` on every question page — `Item 1` is mid-line, inside a longer banner. Zero boundary matches across 5 pages of OCR'd text meant 0 chunks → 0 normalized → 0 app-ready → "No valid output was available to auto-import." Fixed with a two-tier strategy: a strong `\bItem\s+(\d+)\s+of\s+\d+\b` pattern matched anywhere on the line (mandatory once-per-question signature in NBME Self-Assessment PDFs), falling back to the legacy line-start patterns (with new OCR-bullet handling for `~ 1.` / `• 1.` / `· 1.` variants) only when the strong tier yields nothing.

2. **Manual cropping tedium.** The user said: "All other pipelines handle images differently, and I love how everything has been doing so far. The only image handling that's unique to NBME is that the stem images are separated, and shown to me during generation, and I have the ability to crop and attach them. This is tedious. (NBME has NO images in the answer explanation, so gemini involvement is none to decided whether images go in the q stem or answer explanation). Is there a way you can have the system detect embedded images within the question stem (if any present) and automatically have it present to me in the q stem?" The existing NBME workflow already extracted figure candidates per page with a `suggestedQuestionNumber` + confidence score (`nbme_extract_figures.py`), but only emitted a review HTML; the user had to manually crop and attach. v4.60 adds `auto_attach_figures_to_app_ready` which writes the extracted PNG crops directly into `q.images[]` with inline base64 `dataUrl`, mirroring the v4.58 Mehlman / v4.56 images-tables app-ready contract. NBME explanations carry no images (user confirmed), so all attachments use `placement: stem`. No Gemini multimodal calls — pure file-system attachment, free.

Source changes:

- `tools/nbme-pdf-json-generator/extract_pdfs.py`: split `_Q_BOUNDARY_RE` into `_Q_BOUNDARY_STRONG_RE` (matches `Item N of M` anywhere on the line via `\b...\b`) and `_Q_BOUNDARY_FALLBACK_RE` (legacy line-start patterns + new OCR-bullet character class `[~*•·●◦‣■►▪]` before stem numbers with `(?=[A-Z])` lookahead to avoid false matches in answer explanations). `chunk_raw_text` tries strong first, falls back only on empty matches, and records `boundary_source` in the result for diagnostics. The fallback's `(?=[A-Z])` lookahead also tightens the legacy `(\d+)[.)]\s` pattern so it cannot match numbered lists inside explanation prose.
- `tools/nbme-pdf-json-generator/normalized_to_app_json.py`: `convert_normalized_file` now accepts both `items` (live Gemini normalization output) and `questions` (dry-run normalization output) as the top-level list key. Pre-existing dry-run end-to-end bug; surfaced by v4.60 offline testing.
- `tools/nbme-pdf-json-generator/nbme_extract_figures.py`: new `auto_attach_figures_to_app_ready` function with aspect-ratio guard. New constants `AUTO_ATTACH_MIN_ASPECT=0.30`, `AUTO_ATTACH_MAX_ASPECT=3.00`. Existing `build_suggested_figure_links` is untouched and still emits the review HTML for low-confidence candidates.
- `tools/nbme-pdf-json-generator/nbme_batch_wrapper.py`: `run_app_ready` invokes `auto_attach_figures_to_app_ready(min_confidence="medium")` after `build_suggested_figure_links`. Emits a log line summarizing `figuresAttached` / `questionsModified` / `lowConfidenceSkipped` / `aspectFilteredSkipped` counts.

Aspect-ratio rationale: The rendered-page CV detector in `nbme_extract_figures.py` occasionally classifies wide text blocks as figure candidates with `medium` confidence on text-heavy NBME pages. On the user's `Internal Medicine 3 - Questions.pdf` (10 pages), the extractor flagged 14 candidates: 12 with aspect ratio 3.5:1 to 8.6:1 (text strips) and 2 with aspect ratio 0.9 and 2.2 (likely real clinical images). The 3.0 cap cleanly separates the two clusters. Real clinical images (EKGs, X-rays, derm photos, gross pathology, histology slides) cluster between 0.5:1 and 2.5:1; the cap admits all those while rejecting the text-strip false positives.

Architecture significance: NBME is the seventh BIC source to reach "no manual image attachment required" (after the v4.58 Mehlman page-proximity + v4.56 images-tables Gemini-classification work). Each source uses a different technique for the same end goal — Mehlman uses page-proximity because each chunk lives on a known page; images-tables uses a per-image Gemini classification call because the source IS images; NBME uses a CV-based extractor that was already in the repo. The shared contract is `q.images[]` for stem images with `figureKey: null` + inline base64 `dataUrl` + `placement: stem`. The existing renderer + FigureStore consume this same shape regardless of which generator produced it.

Validated:

- Boundary regex test on `Medicalstudyzone_com_Internal_Medicine_3_-_Answers_batch_p001_p005_raw.txt`: 4 strong matches (one per question page), 0 prior to v4.60.
- End-to-end through packaged `.app`: `Internal Medicine 3 - Questions.pdf` first 10 pages → 9 chunks produced (the prior chunker produced 0). Skips 14 chars of preamble ("Exam Section :") before first question, which is the correct behavior. Reports `boundary_source: strong:item-of-M`.
- Auto-attach aspect-ratio guard test on the figure-extractor manifest for the same Questions PDF: 14 kept candidates → 12 rejected (text strips with aspect 3.5-8.6) → 2 retained (real clinical image candidates with aspect 0.9 and 2.2). Verified the auto-attach correctly writes inline `dataUrl` into the matching question's `q.images[]` with `placement: stem` and sets `hasEmbeddedFigure: true`.
- Auto-attach aspect-ratio guard test on `Internal Medicine 3 - Answers.pdf` (all-text answers PDF, no real clinical images): 5 kept candidates → 4 rejected (aspect 3.5-8.1) → 1 borderline (aspect 2.8, just under the 3.0 cap) admitted. User can manually remove via the app's image management UI if it turns out to be wrong; this is the expected behavior for a 3.0 cap.
- `npm run electron:build:mac` succeeded; packaged generator + figure extractor + wrapper all confirmed to carry the v4.60 changes.

Not validated by this milestone:

- Live Gemini run on a real NBME PDF with embedded clinical images. The chunking fix + auto-attach are offline-validated; the live Gemini normalization step uses the same code path UWorld/Mehlman/OME/Anki use which has been live-validated since v4.51. End-to-end live remains the next field check.
- Aspect-ratio guard edge cases: wide EKG strips approaching 3:1, narrow text blocks just under 3:1. The 3.0 cap was chosen because real-world data on the user's `Internal Medicine 3` PDFs cluster cleanly above/below it, but a future PDF with wider EKG strips may need a per-question override.
- Behavior on NBME PDFs that are flattened screenshots (no text layer at all, so `pdfplumber` returns empty and the OCR fallback runs on every page). The user flagged this as a desired case; the existing OCR fallback in `extract_pdfs.py` should handle the text but the figure extractor's CV detector runs on rendered pages regardless of text-layer presence, so the same auto-attach should work — but it has not been field-validated on a screenshot PDF in v4.60.
- Live BIC import from the packaged `.app` UI dropdown. The boundary regex + auto-attach are wired and the packaged pieces are in place, but the field click-through hasn't been driven yet by the user.

## v4.61-nbme-dual-pdf-stable

Commits: `b531f67` (source) + `413b164` (doc).

Meaning: Full NBME pipeline rewrite into a single dual-PDF orchestrator. The v4.60 four-stage wrapper (OCR / chunking / normalization / app-ready) handled NBME Self-Assessment PDFs that had the answer key inline, but the user's actual NBME workflow is Q-PDF + A-PDF as two separate uploads. v4.61 introduces a single orchestrator that handles three input modes auto-detected from upload (dual / Q-only / combined), runs a five-tier extraction cascade per question, smart-triggers Gemini multimodal figure detection only where it's needed, and ALWAYS runs a canonical-polish Gemini call so every question lands with a real reviewPearl, retrievalTag, and educationalObjective rather than placeholder text.

The user explicitly framed v4.61 as fire-and-forget: "I want upload PDFs, generate + import, tests ready when I'm back." After live-running the first NBME import on `Medicalstudyzone.com Internal Medicine 3`, they flagged six distinct quality issues in one feedback round (empty meta fields, chrome leakage in explanations, q20/q26 12-option matching sets not handled, q30 tabular choices illegible without column headers, q39/q42 "giant blown up images" that turned out to be pixelated header crops, multi-line lab values flattened to a single line by the renderer). v4.61 addresses all six.

Source changes:

- `tools/nbme-pdf-json-generator/nbme_dual_pdf_runner.py` (new — replaces `nbme_batch_wrapper.py` as BIC's NBME entry point): full single-file orchestrator with auto-detection, five-tier extraction cascade, smart-trigger Gemini multimodal figure detection (image-language regex OR significant raster ≥400×400 px / ≥150K px²), fractional bbox + 1200-px page render, A-N letter range, deterministic two-column rescue, gap recovery for OCR-missed boundaries, always-polish canonical call (4096 max_tokens, salvage fallback on JSON parse failure), comprehensive A-PDF chrome cleanup. Idempotent via completion-marker flag so BIC's per-input iteration doesn't double-process.
- `tools/batch-import-center/pipeline_registry.json` (`nbme_pdf` entry simplified): dryRunSteps + liveSteps each collapsed to one step calling `nbme_dual_pdf_runner.py --input-file {inputFile}`. The prior four-stage cascade is removed.
- `index.html` (renderer): `#q-stem`, `.shared-group-stem`, `.question-individual-stem`, and `.ngj-exp-section p` now have `white-space: pre-wrap` so the multi-line NBME lab-value blocks render with their original line breaks rather than collapsing to flat prose.

Five-tier extraction cascade per question (after deterministic stem + choices):

1. **Tier 0 — deterministic per-chunk parse**. The standard `_CHOICE_LINE_RE` (handles `0 A) text` NBME-bubble layout) plus `_clean_stem_chrome`. Most questions resolve here without any Gemini call.
2. **Tier 1 — deterministic two-column rescue** (`deterministic_multi_column_parse`). When the suspicion detector flags multi-column choice leakage or matching-set instructions, find every `[A-N])` marker anywhere in the chunk text and split. Handles matching sets up to 14 options without Gemini.
3. **Tier 2 — Gemini multimodal page extraction**. When Tier 1 returns <8 choices for a matching-set chunk OR when the tabular signal fires (column headers like "Specific Gravity / WBC / RBC / Casts" preceding short numeric choices), render the page at 1200 px wide and ask Gemini multimodal for stem + choices + format. Tabular format response uses column-prefixed choice text (`A) Specific Gravity 1.003 | Glucose - | Protein 1+ | WBC 30 | RBC 5 | Casts muddy brown | Findings tubular epithelial cells`).
4. **Tier 3 — gap recovery via multimodal**. After all chunks parse, if a question number is missing between two known neighbours AND the page distance is exactly 2 (one page gap), render that intermediate page and ask Gemini multimodal — unbiased prompt ("extract whatever question is on this page") with strict number-match verification on the response. Recovered q9 cleanly on Internal Medicine 3 where OCR mangled `Item 9 of 50`.
5. **Tier 4 — Gemini completion fallback**. When the A-PDF block for a question is missing or garbled (no `Correct Answer:` line detected, or OCR damage prevents extraction), generate the canonical fields from the Q-PDF stem + choices. JSON-parse retry x3 with progressively stricter prompts.
6. **Tier 5 — stub with extractionWarnings**. Last-resort fallback so a question never silently vanishes from the import.

Architecturally distinct: this is the first BIC orchestrator that performs auto-detected mode dispatch entirely from one entry point rather than via per-stage registry steps. The single-step registry pattern also lets the orchestrator handle BIC's per-input iteration internally via the completion-marker flag, removing the need for stateful cross-stage coordination.

Validated:

- Live BIC end-to-end through the packaged `.app` on `Medicalstudyzone.com Internal Medicine 3 - Questions.pdf + - Answers.pdf` (a real user upload): 50/50 questions imported, ~13 min runtime, ~58 Gemini calls (~$0.30 cost). Polish call adds canonical fields to every question.
- Selective live test on the same PDFs subset for 11 problem questions (q8, q9, q10, q16, q20, q26, q28, q29, q30, q39, q42) covering every extraction tier and edge format: 11/11 produced clean output with proper reviewPearl, retrievalTag, educationalObjective on every question.
- q20 12-option matching set (A-E + G-L, no F because OCR-empty slot) — deterministic Tier 1 rescue, 11 valid choices after spurious-F filter.
- q26 12-option matching set (A-L) — deterministic Tier 1 rescue, 12 choices.
- q28 + q29 10-option matching sets (A-J, shared option block + per-item stem) — deterministic Tier 1 rescue, topic instruction line preserved as stem prefix per the user's duplication preference.
- q30 tabular urinalysis question — Tier 2 multimodal extraction, column-prefixed choice text format.
- q39 peripheral blood smear + q42 dermatology skin lesion — Gemini multimodal figure detection returned fractional bbox, crop produced actual clinical content (337×473 px and 492×422 px PNGs visually verified as the real images).
- Renderer pre-wrap CSS preserves multi-line lab-value blocks in stem and explanation panels.
- `npm run electron:build:mac` succeeded; packaged generator + registry + renderer all confirmed to carry the v4.61 changes.

Not validated by this milestone:

- Pure screenshot NBME PDFs (no text layer at all on most pages). Screenshot auto-detection runs but downstream extraction quality on heavily-OCR'd screenshot pages hasn't been driven end-to-end.
- Multi-question-per-page NBME exports — the orchestrator assumes one question per page when inferring page→question mapping for gap recovery and figure attachment.
- A-PDF blocks delivered in non-sequential order (the user mentioned q13 → q4 → q28 layouts in some NBME PDFs). The orchestrator joins by question number so this should work, but it hasn't been live-stressed against an out-of-order A-PDF.
- Matching sets beyond 14 options (A-N). The regex range stops at N.
- Quota-aware retry stop (v4.54 pattern) is NOT wired into this orchestrator's Gemini call sites. A hard ceiling of 500 calls/run guards against runaway cost, but quota-aware mid-run pause is not implemented.
