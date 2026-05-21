# Git Tag History

Last updated: 2026-05-21

This file documents stable v4 tags from v4.4 through v4.16, plus immediate v4.0-v4.3 context because v4.4 builds on those milestones.

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

## Pending Milestone Candidate

The OME dry-run BIC milestone has validation evidence after v4.16, but no stable tag exists yet. Do not add a tag-history entry until the commit and tag decision is made.
