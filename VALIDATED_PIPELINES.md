# Validated Pipelines

Last updated: 2026-05-23

Current stable tag: `v4.48-lecture-explanation-tables-stable`.

This file records what is validated, what is not validated, and the risk level for each source. Do not upgrade a source's status without evidence.

## Summary Table

| Source | Ingestion status | Live generation status | Normalized chunk support | Auto-import status | Packaged validation | Known blockers | Risk |
|---|---|---|---|---|---|---|---|
| AMBOSS | Registered in BIC | Validated through v4.6 live path | Adapter foundation exists | Validated for BIC live import path | Stable tag exists; exact packaged details should be rechecked before new claims | Source-specific extraction assumptions | Medium |
| Emma | Shared profile stable | Live generation can fail semantic validation | Validated through v4.14 downstream | Existing-output BIC import validated | BIC existing-output import path validated | Semantic validator rejected unsupported term `dystocia` in live run | Medium-high |
| Mehlman | Shared profile stable | Tagged live profile stable | Validated in v4.12 | Registered in BIC | Stable tag exists; revalidate packaged path before broad claims | Scaling and source variety not fully characterized | Medium |
| NBME | BIC orchestration stable | Existing NBME pipeline stable for known workflows | Adapter foundation exists | BIC orchestration tagged stable | Earlier figure/image workflows packaged-validated; recheck for new changes | OCR variability, figure linking, source-specific PDFs | Medium |
| Images & Tables | Shared image/table profile stable | Attachment-first only, no semantic generator | Validated in v4.15 | BIC generate + auto-import validated | Packaged app validated end to end | Heuristic classification, no deep table parsing | Medium |
| Anki | Shared profile + live BIC generation stable at v4.52 | Field-validated 2026-05-23 on 15-card .txt → 15 real questions with proper stems / choices / explanations | Normalized text chunks validated | Live BIC auto-import validated end-to-end | Packaged app live BIC generation + auto-import + quiz rendering verified on the same run | Broad Anki export variation (other languages, complex HTML, media references) not stressed | Medium |
| OME | Shared PDF profile stable | Live Gemini OME generation field-validated at v4.51 on small OME PDF | Normalized text chunks validated | Live BIC auto-import validated end-to-end | Packaged app live BIC generation, auto-import, and quiz rendering validated | Broad OME PDF variety not stressed; writable packaged output for live mode follows v4.51 registry change | Medium |
| Divine Transcript | Dry-run BIC handoff validated | Not validated; BIC live steps intentionally reuse dry-run handoff | Normalized transcript chunks validated | Dry-run BIC auto-import validated in dev and packaged app | Packaged `.txt` and `.md` dry-run auto-import and score history persistence validated | `sourceType` `divine_transcript`; visible source `Divine Transcript`; `sourceFormat` remains `divine-audio`; live generation and audio are unvalidated | Medium-high |
| Fast Facts | Cache foundation plus narrow screening stabilization | Dev Electron live BIC generation validated only through the capped 3-attempt stabilization path | Adapter foundation exists | Dev BIC app-ready discovery and auto-import validated on one small PPTX | Not run for this Fast Facts fix | Broad deck coverage, broad semantic stability, renderer Gemini-alert mismatch | High |

## AMBOSS

Validated:

- Variable-choice support tagged at v4.5.
- BIC live import path tagged at v4.6.
- Gemini environment propagation applies through v4.7.

Not claimed:

- Universal AMBOSS source robustness.
- Shared normalized-chunk downstream convergence.

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

Not claimed:

- Every Mehlman PDF variant.
- Full semantic stability across all Mehlman topics.

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

Validated at v4.15:

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

Not claimed:

- Advanced semantic medical question generation.
- Recursive large-folder ingestion.
- deep table parsing.

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

## Divine Transcript

Validated for the dry-run BIC milestone:

- `divine_transcript` descriptor for transcript text input.
- Visible BIC source label `Divine Transcript`.
- `.txt` and `.md` synthetic transcript fixtures.
- Transcript normalized chunks with source line-range grounding.
- Explicit timestamp preservation when transcript lines contain timestamps.
- Selected-input dry-run handoff through the existing Divine generator.
- Active BIC dry-run registry execution, output discovery, and visible auto-import in dev Electron.
- Packaged `.txt` and `.md` dry-run validation with visible auto-import and score history persistence.
- App-ready dry-run output currently keeps `sourceFormat: divine-audio`.

Intentionally not validated:

- Live Gemini invocation or semantic question generation.
- Audio input, `.mp3`, `.wav`, `.m4a`, or transcription.
- Real Divine podcast audio.
- Installed or signed app write constraints.
- Real-world transcript variation.
- Retrieval, clustering, multimodal grounding, images, or assets.

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
