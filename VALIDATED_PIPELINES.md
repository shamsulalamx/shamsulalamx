# Validated Pipelines

Last updated: 2026-05-24 (v4.59)

Current stable tag: `v4.59-uworld-live-stable`.

This file records what is validated, what is not validated, and the risk level for each source. Do not upgrade a source's status without evidence.

## Summary Table

| Source | Ingestion status | Live generation status | Normalized chunk support | Auto-import status | Packaged validation | Known blockers | Risk |
|---|---|---|---|---|---|---|---|
| AMBOSS PDF | Deterministic OCR-first pipeline rebuilt at v4.57 | Hybrid deterministic + per-question Gemini field-validated at v4.57 on a 39-page / 8-question QBank PDF: all 8 questions extracted with clean choices, correct answers, explanations, retrieval tags, review pearls | Stem fingerprinting + nav-pill union-find grouping + adjacent-merge | Live BIC end-to-end with packaged app | Packaged `.app` 8-question live BIC run validated (~$0.11 cost, ~2.5min runtime) | OCR variance can occasionally fragment 1 question into a duplicate (resolved post-extraction via stem dedupe) or land 1 question in the recovery fallback (resolved via 1 extra Gemini call); in-stem clinical images need NBME cropper UI integration (Phase 2) | Medium |
| Emma | Shared profile stable | Live generation can fail semantic validation | Validated through v4.14 downstream | Existing-output BIC import validated | BIC existing-output import path validated | Semantic validator rejected unsupported term `dystocia` in live run | Medium-high |
| Mehlman | Shared profile stable; v4.58 tight-focus chunking + deterministic page-proximity image attachment + full-PDF processing | Tagged live profile stable | Validated in v4.12; v4.58 retargets chunks to 1.5K chars with sentence-split fallback so each chunk maps to one Mehlman fact | Registered in BIC; v4.58 drops the prior 10-page validation cap so live runs cover every page of the uploaded PDF | Stable tag exists; revalidate packaged path before broad claims | Scaling and source variety not fully characterized; live v4.58 cost/quality on a full 300-page Mehlman PDF not field-validated yet | Medium |
| NBME | BIC orchestration stable | Existing NBME pipeline stable for known workflows | Adapter foundation exists | BIC orchestration tagged stable | Earlier figure/image workflows packaged-validated; recheck for new changes | OCR variability, figure linking, source-specific PDFs | Medium |
| Images & Tables | Shared image/table profile stable; v4.15 attachment-first cards superseded by v4.56 live Gemini generation | Live Gemini per-image classification + NBME-style question generation field-validated at v4.56 (5-image BIC run, 5 questions imported in one test, mixed diagnostic-stem / explanation-only / table placement) | Normalized image/table chunks validated for dry-run sanity stub | Live BIC auto-import validated end-to-end on the packaged `.app` | Packaged `.app` live multi-image BIC run validated: stable combined output filename + accumulating merge across BIC's per-input invocations + non-duplicate explanation rendering all confirmed | `sourceType` `images_tables_source`; visible source "Images & Tables"; supports `.png .jpg .jpeg .webp .bmp .tif .tiff`; tables/charts are forced to the explanation panel by both prompt + post-classification override | Medium |
| Anki | Shared profile + live BIC generation stable at v4.52 | Field-validated 2026-05-23 on 15-card .txt → 15 real questions with proper stems / choices / explanations | Normalized text chunks validated | Live BIC auto-import validated end-to-end | Packaged app live BIC generation + auto-import + quiz rendering verified on the same run | Broad Anki export variation (other languages, complex HTML, media references) not stressed | Medium |
| OME | Shared PDF profile stable | Live Gemini OME generation field-validated at v4.51 on small OME PDF | Normalized text chunks validated | Live BIC auto-import validated end-to-end | Packaged app live BIC generation, auto-import, and quiz rendering validated | Broad OME PDF variety not stressed; writable packaged output for live mode follows v4.51 registry change | Medium |
| Divine (Audio + Transcript) | Dry-run BIC handoff validated for text inputs | Live BIC audio → transcribe → clean → questions field-validated at v4.55 on a 17.2 MB MP3 (`Test Divine.mp3`, 131s, 7 valid questions, `sourceFormat: divine-audio`) | Normalized transcript chunks validated for text inputs; audio inputs skip the shared chunk pipeline (chunks emerge after transcription) | Live BIC end-to-end validated in dev Electron | Packaged `.txt` and `.md` dry-run auto-import previously validated; packaged live audio run via the same `.app` is the next field check | `sourceType` `divine_transcript`; visible source "Divine (Audio + Transcript)"; supports `.txt .md .mp3 .m4a .wav`; audio dry-run is rejected on purpose so transcription tokens are never wasted | Medium |
| Fast Facts | Cache foundation plus narrow screening stabilization | Dev Electron live BIC generation validated only through the capped 3-attempt stabilization path | Adapter foundation exists | Dev BIC app-ready discovery and auto-import validated on one small PPTX | Not run for this Fast Facts fix | Broad deck coverage, broad semantic stability, renderer Gemini-alert mismatch | High |
| UWorld Notes | v4.59 BIC profile registered (text-only, no images) | Live Gemini generation wired through `uworld_profile_runner.py`; downstream-runner dry-run path verified offline end-to-end on a 1.8K and a 4.1K UWorld fixture inside the packaged `.app` | Shared normalized text chunks emitted via the same UWorld heading-aware splitter the downstream generator uses | Live BIC path wired; auto-import target directory registered in registry | Packaged `.app` profile-runner dry-run validated; packaged live run on a real UWorld notes file is the next field check | Live Gemini run on a real UWorld notes file not yet validated; broad input-format variance (.docx with complex formatting, .rtf, very large notes) not stressed | Medium |

## AMBOSS PDF

Foundational validations (still in place):

- Variable-choice support tagged at v4.5.
- BIC live import path tagged at v4.6.
- Gemini environment propagation applies through v4.7.

Newly validated at v4.57 (deterministic OCR-first rebuild + per-question Gemini hybrid):

- `amboss_pdf` BIC source rewritten from per-page Gemini extraction (~$0.50 / ~9 min per PDF) to a deterministic-first pipeline with one Gemini call per question (~$0.11 / ~2.5 min per PDF).
- Stage 1 (deterministic, no Gemini): PyMuPDF page render → tesseract OCR → page classification (`qbank_screenshot` vs `blown_up_image`) → stem fingerprinting → nav-pill detection with majority-M validation.
- Stage 2 (deterministic grouping): union-find connects pages that share a nav-pill question number OR a stem fingerprint. Adjacent-component merge for pages whose nav numbers agree. Blown-up image pages route to the preceding question's `explanationImages[]` via adjacency.
- Stage 3a (hybrid Gemini): one multimodal call per question group (up to 4 page screenshots) extracts answer choices A–H (AMBOSS's styled choice circles defeat OCR), correct answer (identified by the green choice header bar on the explanation-reveal page), per-choice explanations, educational objective, retrieval tag, review pearl. Uses `responseMimeType: application/json` + `maxOutputTokens: 8192` to eliminate truncated-string and prose-instead-of-JSON failure modes.
- Stage 3b (Gemini recovery fallback): when a group's deterministic extraction returns None (every page misclassified due to OCR failure), one extra Gemini call asks "is there an AMBOSS question here? if yes, extract it; if no, return no_question". Recovers questions whose stem OCR catastrophically failed.
- Stage 3c (post-extraction dedupe): collapses questions whose normalized stems agree on the first 40 chars — handles OCR variance that fragments a single question into two components.
- Image routing: full-page blown-up clinical images (AMBOSS's "click to enlarge" view) routed to the preceding question's `explanationImages[]` deterministically.
- Field-validated on `Test Amboss.pdf` (8 QBank questions across 39 pages of browser screenshots + click-to-enlarge clinical images): all 8 questions extracted with clean choices, correct answers (varicella vaccine F, indinavir urolithiasis G, etc.), educational objectives, retrieval tags, review pearls. Clinical images attached to the correct explanation panels (shingles photo with Q1, esophagus endoscopy with Q2, etc.).

Intentionally not yet validated:

- In-stem clinical images on AMBOSS PDFs whose stems include embedded figures. These need NBME-style cropper UI integration — Phase 2.
- Broad real-world AMBOSS QBank export variation beyond the single 8-question Test PDF.
- AMBOSS PDFs with non-flattened text layers (rare — most exports are browser screenshots).
- Long QBank exports (50+ questions). The deterministic page-grouping pipeline scales linearly; Gemini cost scales linearly at ~$0.01 per question. No upper bound tested.

Not claimed:

- Universal AMBOSS source robustness across all QBank export variants.
- Shared normalized-chunk downstream convergence (AMBOSS uses its own page-classification + grouping pipeline, not the shared chunk infrastructure used by Emma / Mehlman / Anki / OME / Divine).

## Emma Holiday

Validated:

- Shared-ingestion profile at v4.11.
- BIC existing-output import mode at v4.13.
- Normalized-chunk downstream consumption at v4.14.
- Emma PDF batch import routing stabilization at v4.47.
- Lecture-slide explanation tables now render structured `q.tables` inline (v4.48). Validated on Test_Emma fixture in packaged app: 3-column / 3-row table renders correctly in the explanation panel.
- Existing valid Emma app-ready JSON can auto-import through BIC with expected count and folder.

Known blockers:

- Live generation reached downstream but failed Emma semantic validation on Q1 for unsupported term `dystocia`. This is generation/validator quality, not BIC wiring.

Resolved (previously a blocker):

- Lecture-slide chunk-planning silent-loss. Fixed and tagged `v4.49-lecture-chunk-recovery-stable` on 2026-05-23. Field-validated on Test_Emma BIC live run (job `batch-mpis1xxn-c0i3id`): 18 allocated → 17 generated, targeted recovery loop fired for 5 short-returning slides and recovered 4 of them; the 5th stopped cleanly on a Gemini network timeout. Quota-aware retry stop separately field-validated on the prior depleted-credits run: 1 HTTP 429 caught, no cascade, no further budget burn. Auto-import and explanation-panel table rendering verified in the same run (4 questions with inline tables).

## Mehlman

Validated:

- Shared-ingestion live profile at v4.12.
- Text-heavy normalized chunks with preserved figures/tables where available.

Newly validated at v4.58 (tight-focus chunking + deterministic page-proximity image attachment + full-PDF processing):

- `tools/mehlman-pdf-question-generator/generate_mehlman_questions.py` chunk window retargeted from 8,000–12,000 chars to 1,200–1,800 chars (~1.5K target). Each chunk is intended to cover one discrete Mehlman fact slice so one question per chunk has a single grounded topic to test.
- Per-page chunking now falls back to sentence splits when paragraph breaks are lost in PDF extraction (PyMuPDF/pdfplumber often strip `\n\n` markers on dense Mehlman pages). Verified on the 15-page `HY Internal Medicine (2).pdf` slice: 39,971 body chars → 33 chunks, avg 1,210 chars, max 1,796, 0 chunks over the 1,800 cap.
- Default `--questions-per-chunk` lowered from 5 to 1, paired with the tighter chunks for one-fact-per-question NBME stems. Override remains available for backward compatibility.
- Deterministic page-proximity image attachment: each chunk already tracks the figures extracted from its `pageStart-pageEnd` range, so the generator now attaches those figures to the first question produced for the chunk via `q.explanationImages[]` + `q.figureRefs[]` (`hasEmbeddedFigure: true`). No Gemini multimodal call required — pure file-system attachment, free.
- Attachment helper `_attach_chunk_figures_to_questions` is hardened against BIC's out-of-tree `--output-dir`: the prior `relative_to(_BASE)` ValueError silently killed every chunk that had figures during the first packaged live run (8 chunks dropped on the `Test Mehlman.pdf` field test, 0 images on 20 surviving questions). v4.58 catches the ValueError, records the per-figure failure in `extractionWarnings`, and keeps the question with its remaining figures.
- `tools/shared-ingestion/mehlman_profile_runner.py` no longer overrides `--questions-per-chunk` to 2 (pre-v4.58 contract from the 8-12K-chunk era). The runner now inherits the generator's v4.58 default of 1, so the BIC live path actually hits the tight-focus contract end-to-end.
- BIC + profile-runner page cap lifted: the dry-run and live registry entries no longer pass `--limit 10`, and the profile runner's `--limit` default is 0 (process every page). Field-verified on `Test Mehlman.pdf` (19 pages): full PDF processed → 36 chunks → 36 questions with 12 carrying 23 figures across pages 1, 2, 3, 4, 5, 8, 9, 10, 11, 16, 17, 19. Previously the 10-page cap dropped pages 11-19 and ~half the figures on every import.
- Cardiology test fixture (`test_mehlman_cardiology_fixture.pdf`, 13 pages → 20,849 chars) re-chunks to 15 chunks (avg 1,389, max 1,734); page-6 table propagates to its chunk and renders in the explanation panel via the existing table-markdown asset marker path.

Not claimed:

- Every Mehlman PDF variant.
- Full semantic stability across all Mehlman topics.
- Live Gemini cost/quality on a full 300-page Mehlman PDF at the v4.58 chunk size — only dry-run + chunk-manifest sanity checks have run on the small fixtures. The cost model projects ~$1.30 per 300-page import and ~600 questions per import, but a live run on a 300-page Mehlman has not been field-validated yet.
- Packaged `.app` live BIC run at the v4.58 chunk size on a large Mehlman PDF — packaged rebuild ships the v4.58 generator, runner, and BIC registry; the next field check is a live run on the 19-page `Test Mehlman.pdf` after the v4.58 rebuild.

## NBME

Validated:

- NBME batch orchestration at v4.8.
- BIC orchestration hardening at v4.9.
- Earlier NBME figure extraction and crop/manual-upload workflows have packaged validation history.

Not claimed:

- All NBME forms.
- Perfect OCR.
- Fully automatic figure attachment.

## Images & Tables

Validated at v4.15 (foundational attachment-first milestone):

- `images_tables_source` descriptor.
- image/table normalized chunk emission.
- OCR extraction with local `tesseract`.
- asset classification into ordinary image, algorithm, and table image on a small sample.
- lightweight app-ready cards.
- BIC generate + auto-import.
- packaged `.app` import.
- `FigureStore` persistence for all generated cards.
- ordinary image rendering.
- table image rendering after reload.
- score history persistence after reload.

Newly validated at v4.56 (live Gemini generation + multi-image accumulation + render fixes):

- `liveSteps` in BIC registry now invokes per-image Gemini classification and NBME-style question generation via `tools/images-tables-question-generator/generate_images_tables_questions.py` instead of the attachment-first stub. Live mode requires `GEMINI_API_KEY`. Dry-run still emits the attachment-first stub for sanity checks without API spend.
- Placement contract enforced by both prompt and post-classification override: diagnostic images that need interpretation land in `q.images[]` (stem); explanation-only images and **all** tables/charts land in `q.explanationImages[]` (explanation panel). Even if Gemini misclassifies a table as `diagnostic_stem_image`, `normalize_classification` re-routes it back to `explanation_only_table`.
- Multi-image jobs: BIC orchestration invokes the runner once per input file. Each runner invocation appends its fresh per-image output to the job's `*_per_image.json` set, then rewrites a single stable-named `images_tables_combined_app_ready.json` with every question gathered so far. By the time the last input completes, exactly one combined `*_app_ready.json` exists and contains every generated question. BIC's `discover_outputs` picks up only the combined file (per-image files use a non-matching `_per_image.json` suffix), and auto-import loads the full set in one shot.
- Renderer no longer double-renders explanations when both `correctBlurb` and `explanation` are populated. `correctBlurb` (HTML, used by the images-tables v2 schema) takes precedence; `explanation` (plain text, used by legacy PDF imports) is rendered only when `correctBlurb` is absent. Applies to both the in-quiz `buildExplanationHTML` and the review-mode `window.buildExplanationHTML` copies.
- Generator no longer emits the duplicate plain-text `explanation` field — only `correctBlurb` and `explanationSections`. Eliminates the duplicate-explanation bug at the source for any future renderers that also previously rendered both.
- Field-validated on the packaged `.app` with a 5-image multi-file BIC job (Abdominal CT, abetalipoproteinemia biopsy, alcoholic hepatic steatosis, aortic arch derivatives, Barrett's esophagus): 5 questions imported in a single test, no duplicate explanation blocks, correct stem/explanation placement per image type.
- A separate 4-image dev-Electron run (diagnostic dermatology, vesicoureteral process diagram, water-soluble vitamins table, Weber/Rinne tracing) confirmed correct classifier behavior across all four placement categories; the table was relegated to the explanation panel as required.

Not yet validated:

- Broad real-world Step 2 image variety beyond the validation fixtures.
- Recursive large-folder ingestion.
- Deep table parsing into rows and columns (out of scope — the table is preserved as an image attachment, not parsed).
- Behavior under Gemini rate-limit / quota exhaustion mid-run (the per-image generator does not yet share the UWorld-family quota-aware retry stop landed at v4.49/v4.54).

## Anki

Validated for the dry-run BIC milestone (earlier):

- `anki_notes` shared descriptor and normalized `text` chunk emission.
- Shared-ingestion dry-run profile runner handoff to the existing Anki wrapper with one selected input.
- BIC dry-run registry execution and output discovery.
- Renderer auto-import through the existing importer path.
- DB persistence, quiz rendering, reload persistence, and score history persistence.
- Visible BIC UI auto-import in dev Electron and packaged app.

Validated at v4.52 (live BIC milestone, 2026-05-23):

- `anki_profile_runner.py --mode generate` handoff (`--emit-app-ready-dry-run` kept as backward-compatible alias for `--mode dry-run`).
- BIC `anki_notes` registry entry now has `requiresGemini: true` and live steps that invoke `--mode generate --limit 0`.
- Live Gemini Anki generation produces app-ready JSON from a user-supplied 15-card .txt export.
- Generated questions carry explicit one-best-answer final-question sentences (via the v4.51 stem-quality validator in the shared UWorld machinery — Anki wraps it).
- Cross-generator chunking + token-cap fix in the UWorld machinery (force-slice in `split_into_chunks` plus `maxOutputTokens` raised 8192 → 16384) prevents the truncation that the 15-card test originally hit.
- Packaged app live BIC auto-import and quiz rendering verified on the same run.

Not validated (still):

- Broad real-world Anki export variation: other languages, complex HTML, media references, `.apkg` files, single-line monolithic exports of much larger decks.
- Per-question manual review/accept/reject for questions that fail validation now works for the UWorld-family wrappers (Anki, OME, Mehlman, Divine, UWorld) too, via the v4.53 port of the v4.50 review-survivor flow. When repair retry fails, the question is routed to `<jobOutputRoot>/review/uworld_family_review_draft.json` instead of being silently kept with `extractionWarnings`; the BIC review modal surfaces it for accept / edit / reject; accepted candidates merge into the same auto-imported test via the v4.50 append-to-existing-test path. Offline-validated. Field validation of the failure path is pending an organic partial-failure run.

## Fast Facts

Validated:

- Cache foundation was added at v4.4.
- Diagnostic reporting was added for Fast Facts generation and validation.
- `--fast-facts-question-limit` was added and the visible BIC live stabilization path was capped at 3 attempted questions.
- The screening-test ontology classifier was fixed for the observed Turner Syndrome screening failure.
- One visible Electron dev BIC live generation passed from a small Fast Facts PPTX through the capped stabilization registry path.
- The run emitted app-ready output with 1 final question, discovered that output in BIC, auto-imported it, rendered the first question, scored the imported test, and preserved score history after reload.
- The newest diagnostic and validation reports for that run did not show `mixed_answer_choice_ontology` or unsupported-term failures.
- Review-survivor import path fixed and field-validated at v4.50: reviewed-accepted questions now merge into the same auto-imported test for the BIC job, and survivor questions carry canonical `explanationSections[]` instead of the empty placeholder the prior buggy path wrote.

Explicitly not validated:

- broad semantic generation quality.
- all Fast Facts decks.
- packaged validation for this Fast Facts fix.
- uncapped live BIC validation outside the current stabilization registry path.

Treat Fast Facts as high-risk outside the narrow observed screening failure that was stabilized and validated.

## Divine (Audio + Transcript)

Validated for the dry-run BIC milestone (text inputs):

- `divine_transcript` descriptor for transcript text input.
- `.txt` and `.md` synthetic transcript fixtures.
- Transcript normalized chunks with source line-range grounding.
- Explicit timestamp preservation when transcript lines contain timestamps.
- Selected-input dry-run handoff through the existing Divine generator.
- Active BIC dry-run registry execution, output discovery, and visible auto-import in dev Electron.
- Packaged `.txt` and `.md` dry-run validation with visible auto-import and score history persistence.

Newly validated at v4.55 (audio + live):

- Visible BIC source label "Divine (Audio + Transcript)" with `.txt .md .mp3 .m4a .wav` extensions.
- Audio input picker accepts `.mp3 / .m4a / .wav` files; dry-run with audio is rejected with a clear error (exit 2) so transcription tokens are never wasted.
- Live mode (`--emit-app-ready-live`) routes audio inputs straight to `generate_divine_questions.py --generate --input-file <audio> --output-dir <durable>`, skipping the shared chunk pipeline (which needs text).
- Gemini File API upload, file-state polling, and audio-aware `generateContent` exercised end-to-end on `Test Divine.mp3` (17.2 MB, audio/mpeg).
- Transcription → cleaning → 2 chunks → 15 questions targeted → 7 questions valid in 131s wall-clock.
- Raw transcript written to `<jobOutputRoot>/transcripts/raw/<stem>_raw.txt`; cleaned transcript to `<jobOutputRoot>/transcripts/cleaned/<stem>_cleaned.txt` (redirected via `--output-dir`, not the packaged tree).
- App-ready output at `tools/shared-ingestion/output/divine_app_ready_live/<stem>/app_ready/<stem>_app_ready.json` with `schemaVersion: nbme-gemini-json-v3` and `sourceFormat: divine-audio`. Sample question has 4 answer choices, non-empty `retrievalTag` and `reviewPearl`.

Intentionally not yet validated:

- Packaged `.app` live audio run (the dev-Electron-equivalent live run via the v4.55 build was validated; the user is encouraged to repeat through the new packaged BIC dropdown).
- Long episodes (> ~90 min): the transcript-cleaning prompt caps at 120,000 chars and the transcription `maxOutputTokens` caps at 65,536 (~3 hours). Warnings fire when caps are hit.
- Real-world transcript variation beyond the single Divine Intervention test episode.
- Retrieval, clustering, multimodal grounding, images, or assets — out of scope for this pipeline.
- Robustness of the question-generation JSON parse on long Gemini responses. On the v4.55 test run, chunk 1 (8 questions requested) failed JSON parse after the generator's 3-stage repair, so 7 of 15 questions made it through; this is the pre-existing UWorld-family JSON-truncation class addressed at v4.52 / v4.54 and the chunk-planning recovery is expected to compensate on subsequent runs.

## OME

Validated for the dry-run BIC milestone (earlier):

- `ome_pdf` descriptor and normalized `text` chunks from the tracked synthetic fixture.
- Selected-input OME generator dry-run with controlled output.
- Active BIC dry-run orchestration, output discovery, registry note display, and visible auto-import in dev Electron and packaged app.
- Clean packaged temporary profile import, quiz rendering, reload persistence, and score history persistence after reload.

Validated at v4.51 (live BIC milestone, 2026-05-23):

- `ome_profile_runner.py --mode generate` handoff (the old `--emit-app-ready-dry-run` flag is kept as a backward-compatible alias for `--mode dry-run`).
- BIC `ome_pdf` registry entry now has `requiresGemini: true` and live steps that invoke `--mode generate --limit 0`.
- Live Gemini OME generation produces app-ready JSON from a small user-supplied OME PDF.
- Generated questions carry explicit one-best-answer final-question sentences ending in '?' (via the v4.51 stem-quality validator added to the shared UWorld machinery — OME wraps it).
- Packaged app live BIC auto-import, quiz rendering, and explanation panel verified on the same run.

Not validated (still):

- Broad OME PDF coverage beyond small user-supplied samples.
- Controlled asset extraction for OME.
- Non-writable packaged resource tree behavior (live OME output paths follow `BIC_JOB_OUTPUT_ROOT` redirection but signed/notarized distribution behavior was not stressed in this validation).

## UWorld Notes

Validated at v4.59 (text-only BIC enablement of the foundational UWorld generator):

- `tools/uworld-notes-question-generator/generate_uworld_questions.py` gained `--input-file` and `--output-dir` CLI flags so the existing generator can be driven from outside its source tree (BIC's job dir lives outside the `.app` bundle).
- `tools/shared-ingestion/uworld_profile_runner.py` (new) emits shared normalized text chunks via the UWorld text extractor + heading-aware splitter, then invokes the existing UWorld generator with the right `--input-file` / `--output-dir` / `--questions-per-file`. Skips all image/table machinery because the user confirmed UWorld notes are text-only.
- High-yield density: `--questions-per-file` auto-scales to ~1 question per 500 chars (roughly 3× Mehlman density) because the user specifically asked for higher question frequency on UWorld notes — they are "extremely high yield." Auto bound is `max(5, chars // 500)` clamped at 80 to avoid runaway cost on unexpectedly large files. Explicit `--questions-per-file N` override stays available.
- `tools/shared-ingestion/source_descriptor.py` gains a `uworld_notes` descriptor (modality: text, asset_policy: none).
- `tools/shared-ingestion/pipeline_adapter.py` gains a `uworld_notes_to_normalized_chunks` adapter that reuses the UWorld text extractor + chunker. Returns chunks with grounded `topicIndex` + `heading` provenance.
- `tools/shared-ingestion/chunk_pipeline.py` adds `uworld_notes` to the `--source-type` allowlist.
- `tools/batch-import-center/pipeline_registry.json` registers `uworld_notes` with dry-run + live steps (`requiresGemini: true`) and supports `.txt .md .rtf .docx` inputs.
- Offline-verified end-to-end on a 1.8K `test_cardiology.txt` (5 questions emitted — MIN clamp) and a 4.1K synthetic UWorld file (8 questions — auto-scaled). Verified through the packaged `.app` profile runner: `outcome: completed`, `candidateQuestionCount: 8`, `sourceFormat: uworld-notes`, `schemaVersion: nbme-gemini-json-v3` (the canonical app-ready shape).

Not yet validated:

- Live Gemini run on a real UWorld notes file — only the dry-run path through the packaged profile runner has been exercised so far. Live cost projection per UWorld file is ~$0.02-$0.16 (5-80 questions × ~$0.002/question) depending on file size.
- Broad input-format variance: `.docx` with complex formatting, `.rtf`, very large notes (>40K chars where the MAX_AUTO_QUESTIONS_PER_FILE clamp would kick in).
- Packaged `.app` live BIC run from the UI dropdown — the packaged generator + profile runner + registry all carry the v4.59 changes, but the end-to-end live BIC click-through hasn't been field-tested.
