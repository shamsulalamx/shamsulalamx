# Known Limitations

Last updated: 2026-05-21

## Fast Facts Instability

Fast Facts is not semantically stable. v4.4 added profile extraction and an incremental cache foundation, but that does not prove generated question quality. Do not tune or claim Fast Facts quality without a separate validation pass.

## Semantic Validator Fragility

Semantic validators can reject legitimate medical vocabulary. The Emma live run reached downstream generation and consumed normalized chunks, but semantic validation rejected Q1 for unsupported term `dystocia`. This is an unresolved validator/generation quality issue.

## OCR Limitations

OCR depends on source quality and local tooling. Images & Tables uses local `tesseract` when available. Poor screenshots, unusual fonts, low contrast, and dense tables can reduce OCR quality. OCR success does not prove semantic understanding.

## Image Classification Heuristics

Images & Tables classification is currently heuristic. It uses filename and OCR text signals to classify assets as `stem_image`, `table_image`, `algorithm`, `chart`, or `unknown`. It does not perform deep visual reasoning.

## Source-Specific Assumptions

Each source still has source-specific assumptions:

- AMBOSS uses its existing extraction path.
- NBME depends on OCR/chunking behavior and figure conventions.
- Emma uses lecture-slide downstream semantics.
- Mehlman assumes text-heavy PDF structure.
- Images & Tables assumes small image sets.
- Fast Facts relies on its cache/profile foundation but remains semantically unstable.

## Unvalidated Scaling Behavior

Large source runs are not validated for every profile. The current Images & Tables validation used a small 5-image set. Large-folder behavior, memory pressure, and UI import performance are unresolved.

## Large-Folder Limitations

Images & Tables folder ingestion is shallow and intentionally limited. It does not recursively crawl nested folders. It should be validated with 2-5 assets first.

## Anki Dry-Run Limitations

The validated Anki BIC path is a dry-run handoff. Its current app-ready questions are placeholders.

- Live Gemini Anki generation is not enabled through BIC.
- Real-world Anki export variation is not broadly validated.
- `.apkg` imports are unsupported.
- Media references and HTML variation are not validated.
- The global `schemaVersion` and `questionCount` warning contract remains unresolved.

## OME Dry-Run Limitations

The validated OME BIC path is dry-run only. Its current app-ready questions are placeholders.

- Live Gemini OME generation is not enabled through BIC.
- Real semantic OME question quality is not validated.
- Real OME PDFs beyond the tracked synthetic fixture are not validated.
- OME asset extraction has not been validated with the controlled output path.
- Packaged OME output currently writes under packaged resources. Moving generated output to a writable app-data location is future work.
- Signed or notarized distribution behavior and non-writable packaged resource tree behavior are not validated.

## Divine Transcript First-Milestone Limitations

The current Divine shared-ingestion milestone is transcript normalization only.

- Only synthetic `.txt` and `.md` transcript fixtures are validated.
- Audio ingestion, transcription, Whisper, local speech models, and Gemini audio transcription are not supported.
- Transcript chunks preserve structure and provenance but do not prove semantic medical quality.
- BIC registration, app-ready generation, importer behavior, Electron UI, packaged orchestration, retrieval, clustering, images, and assets remain out of scope.

## Remaining Multimodal Gaps

Open multimodal gaps:

- deep table parsing into rows and columns,
- visual grounding beyond OCR/filename heuristics,
- multi-asset question grounding,
- confidence calibration,
- scalable asset cache indexing,
- semantic question generation from images/tables.

## Packaged Resource Path Differences

Packaged app jobs run from app resources. A workspace path and a packaged resource path are not always the same. Existing-output validation mode handles this for selected app-ready JSONs, but future source-specific file references should still be tested in the packaged app.

## Shared Architecture Incomplete

The shared profile architecture is active but incomplete. Anki and OME have validated dry-run shared profiles and BIC handoffs, while Divine and UWorld are not fully migrated into shared ingestion. Do not delete existing source-specific flows.
