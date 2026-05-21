# Project Status 2026-05-21

Current stable tag: `v4.16-anki-dry-run-bic-stable`

Current branch observed during this update: `main`

## Completed Milestones

The v4 line moved the project from individual source pipelines toward profile-based ingestion.

Completed and tagged milestones:

- v4.4: Fast Facts cache foundation added.
- v4.5: AMBOSS extraction and variable-choice support.
- v4.6: Batch Import Center foundation and AMBOSS live import path.
- v4.7: Gemini environment propagation to batch jobs.
- v4.8: NBME PDF batch orchestration.
- v4.9: BIC orchestration hardening.
- v4.10: shared normalized chunk ingestion foundation.
- v4.11: Emma shared-ingestion profile.
- v4.12: Mehlman shared-ingestion live profile.
- v4.13: BIC existing-output validation mode.
- v4.14: Emma normalized-chunk downstream consumption.
- v4.15: Images & Tables shared-ingestion profile.
- v4.16: Anki dry-run BIC profile.

Earlier v4.0-v4.3 established Images/Tables generator stability and Emma Holiday lecture-slide generator stability.

## Validated Sources

| Source | Current status | Validation level |
|---|---|---|
| AMBOSS | BIC live path stable | Variable-choice support and BIC live import path tagged stable |
| Emma Holiday | Shared ingestion profile stable; normalized-chunk downstream stable | BIC existing-output import validated; live generation has separate semantic blocker risk |
| Mehlman | Shared-ingestion live profile stable | Tagged v4.12 |
| NBME | BIC orchestration stable | Tagged v4.8; legacy NBME import and image workflows have earlier validation |
| Images & Tables | Shared-ingestion profile stable | Packaged app import, FigureStore persistence, image/table rendering, score, reload validated |
| Anki | Shared-ingestion dry-run profile and BIC dry-run orchestration validated | Dev Electron visible UI auto-import, packaged visible UI auto-import, and score history persistence validated; live Gemini generation and semantic question quality are not validated |
| OME | Shared-ingestion dry-run profile and BIC dry-run orchestration validated | Normalized chunks, selected-input dry-run handoff, dev and packaged visible BIC auto-import, clean-profile import, quiz rendering, and score history persistence validated; live Gemini generation is not validated |
| Divine Transcript | Shared-ingestion transcript profile and BIC dry-run orchestration validated | Transcript normalized chunks, `.txt` and `.md` inputs, selected-input dry-run handoff, dev and packaged visible BIC auto-import, and score history persistence validated; live Gemini, audio, and transcription are not validated |
| Fast Facts | Cache foundation only | Explicitly not semantically stable |

## Validated Runtime Paths

Validated runtime paths as of v4.16:

- Electron packaged build through `npm run electron:build:mac`.
- Packaged app launch with remote debugging.
- BIC Python job execution from packaged app resources.
- BIC output discovery.
- Existing-output validation mode for BIC.
- Auto-import through the BIC import path.
- `DB.createTest` save path.
- `FigureStore` persistence for direct image arrays.
- Quiz image rendering from `FigureStore`.
- Score history persistence after reload.

Validated after v4.15 for the Anki dry-run BIC milestone:

- Shared-ingestion normalized Anki text chunks.
- Existing Anki wrapper selected-input dry-run handoff through the Anki profile runner.
- BIC dry-run registry execution.
- Dev Electron visible UI auto-import into the existing importer and DB save path.
- Optional BIC test-name input on the validated dry-run import path.
- Packaged app visible UI auto-import.
- Packaged auto-import, quiz rendering, reload persistence, and score history persistence.

This Anki milestone does not validate live Gemini Anki generation or real semantic Anki question quality.

Validated after v4.16 for the OME dry-run BIC milestone:

- Shared-ingestion normalized OME text chunks from the tracked synthetic OME PDF fixture.
- Selected-input dry-run handoff through the existing OME generator.
- Shared runner handoff through `--emit-app-ready-dry-run`.
- Active BIC dry-run registry orchestration and output discovery.
- Dev Electron visible UI auto-import and dry-run-only registry note display.
- Packaged app visible UI auto-import from a clean temporary profile.
- Quiz rendering, reload persistence, and score history persistence after reload.

This OME milestone validates placeholder dry-run output only. It does not validate live Gemini OME generation, a live OME BIC path, or real semantic OME question quality.

Validated after the OME dry-run BIC milestone for Divine Transcript:

- Shared-ingestion normalized Divine transcript chunks.
- Synthetic `.txt` and `.md` transcript inputs.
- Selected-input dry-run handoff through the existing Divine generator.
- Active BIC dry-run registry orchestration and output discovery.
- Dev Electron visible BIC auto-import.
- Packaged app visible BIC auto-import for `.txt` and `.md` inputs.
- Score history persistence after packaged validation.

This Divine Transcript milestone validates transcript-first dry-run output only. It does not validate live Gemini Divine generation, audio input, transcription, or real Divine podcast audio.

## Packaged App Status

Packaged app validation has been required for image and BIC claims. The v4.15 Images & Tables profile passed packaged validation:

- 5 app-ready cards generated from a small image folder.
- Imported into Images and Tables.
- All 5 images persisted in `FigureStore`.
- Inline `dataUrl` values were removed from saved questions.
- Ordinary image rendered.
- Table image rendered after reload.
- Score history persisted as `3/5`.

## Remaining Risks

- Fast Facts semantic generation remains unstable. Do not call it stable.
- Emma live generation can fail semantic validation even after normalized chunks are consumed.
- Semantic validators may reject legitimate source terms.
- Images & Tables classification is heuristic.
- OCR quality depends on local `tesseract` and image quality.
- Large multimodal folders are not validated.
- Shared downstream generation is not complete.
- Live Gemini Anki generation is not validated.
- Semantic Anki question quality is not validated.
- Live Gemini OME generation and live OME BIC execution are not validated.
- OME packaged output currently depends on a writable packaged resource tree; app-data output migration is future work.
- Live Gemini Divine generation, Divine audio input, and Divine transcription are not validated.

## Roadmap

Priority roadmap:

1. Controlled Divine audio and `.mp3` operationalization through the existing generator only if pursued next.
2. Fast Facts stabilization.
3. OME live-generation policy and semantic quality only if desired.
4. OME writable app-data output migration.
5. Anki live generation and semantic hardening only if desired.
6. Shared downstream reuse.
7. Semantic validator hardening.
8. Multimodal grounding improvements.
9. Scalable asset caching.
10. Deeper table parsing.
11. Full profile architecture convergence.

## Exact Current Git Tags

| Tag | Meaning |
|---|---|
| `v4.0-images-tables-generator-stable` | Initial Images/Tables generator stable point |
| `v4.1-images-tables-placement-stable` | Image placement refined |
| `v4.2-images-tables-schema-stable` | Canonical Images/Tables schema fixed |
| `v4.3-emma-holiday-pediatrics-stable` | Lecture-slide generator stabilized for Emma Holiday pediatrics |
| `v4.4-fast-facts-cache-foundation` | Fast Facts profile/cache foundation only |
| `v4.5-amboss-variable-choice-stable` | AMBOSS extraction plus variable-choice support |
| `v4.6-batch-import-amboss-live-stable` | BIC foundation plus AMBOSS live import path |
| `v4.7-batch-import-gemini-env-stable` | Gemini env propagation to BIC jobs |
| `v4.8-batch-import-nbme-stable` | NBME PDF batch orchestration |
| `v4.9-batch-import-orchestration-stable` | BIC orchestration hardening |
| `v4.10-shared-ingestion-foundation` | Shared normalized chunk ingestion foundation |
| `v4.11-emma-shared-ingestion-profile-stable` | Emma profile through shared ingestion |
| `v4.12-mehlman-shared-ingestion-live-stable` | Mehlman shared-ingestion live profile |
| `v4.13-bic-existing-output-import-stable` | Existing-output BIC validation mode |
| `v4.14-emma-normalized-chunk-downstream-stable` | Emma downstream consumes normalized chunks |
| `v4.15-images-tables-profile-stable` | Images & Tables shared-ingestion profile |
| `v4.16-anki-dry-run-bic-stable` | Anki dry-run BIC profile |

## Working Tree Notes At Handoff

During this documentation update, `.claude/settings.local.json` was already modified. Several generated/untracked assets and output JSON files were also present. They are not part of this documentation update unless explicitly staged by the user later.
