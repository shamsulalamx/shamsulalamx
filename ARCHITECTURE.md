# Architecture

Last updated: 2026-05-21

This document describes the current v4.16 architecture plus the validated OME and Divine Transcript dry-run BIC milestones after that tag. It distinguishes validated behavior from intended convergence.

## System Overview

The app is a vanilla `index.html` application served through Electron over local HTTP. The app imports app-ready JSON into a local quiz database, persists metadata in localStorage, stores image data in IndexedDB `FigureStore`, and can be packaged as a Mac app.

The newer ingestion architecture adds a profile layer:

```text
source input
  -> source descriptor
  -> shared normalized chunk adapter
  -> source-specific downstream or attachment-first runner
  -> *_app_ready.json
  -> Batch Import Center output discovery
  -> existing JSON validation/import
  -> DB.createTest
  -> FigureStore image persistence
  -> quiz/review/scoring
```

## Shared Ingestion Layer

`tools/shared-ingestion/` contains the shared profile infrastructure:

- `source_descriptor.py`: declares source metadata.
- `normalized_chunk_schema.py`: defines `shared-normalized-chunk-bundle-v1`.
- `pipeline_adapter.py`: converts source artifacts into normalized chunks.
- `asset_router.py`: classifies and routes image/table references.
- `chunk_pipeline.py`: runs adapter emission and validation.
- Source runners such as `emma_profile_runner.py`, `mehlman_profile_runner.py`, `images_tables_profile_runner.py`, `anki_profile_runner.py`, and `ome_profile_runner.py`.

The layer is intentionally thin. It does not replace working generators unless a real abstraction gap has been proven.

## Source Descriptors

A descriptor records:

- `source_type`
- `modality`
- `extraction_style`
- `generation_style`
- `asset_policy`
- `cache_policy`
- notes and source-specific metadata

Current shared profile descriptors include:

- `emma_holiday_pdf`
- `mehlman_pdf`
- `images_tables_source`
- `anki_notes`
- `ome_pdf`
- `divine_transcript`

The descriptor is metadata plus routing intent. It is not a runtime schema fork.

## Normalized Chunks

The normalized bundle schema is `shared-normalized-chunk-bundle-v1`.

Top-level bundle fields:

- `schemaVersion`
- `sourceDescriptor`
- `sourceFile`
- `sourcePath`
- `createdAt`
- `chunkCount`
- `chunks`
- `warnings`

Chunk fields:

- `schemaVersion`
- `chunkId`
- `chunkType`
- `sourceType`
- `sourceFile`
- `sourceGrounding`
- `text`
- `textBlocks`
- `imageRefs`
- `tableRefs`
- `confidence`
- `metadata`
- `warnings`

Validated chunk types now include `text`, `slide`, `question`, `transcript`, `image`, and `table`.

## Downstream Reuse

Shared ingestion currently feeds existing downstream generators:

- Emma normalized chunks feed the lecture-slide generator.
- Mehlman normalized chunks feed the Mehlman generator.
- Images & Tables normalized chunks feed a deterministic attachment-first runner.
- Anki normalized text chunks hand off to the existing Anki wrapper only in selected-input dry-run mode.
- OME normalized text chunks hand off to the existing OME generator only in selected-input dry-run mode.
- Divine Transcript normalized transcript chunks hand off to the existing Divine generator only in selected-input dry-run mode.

NBME, AMBOSS, and Fast Facts still use existing source-specific downstream code. Do not rewrite those generators as part of profile onboarding unless the user explicitly requests it and validation supports the change.

## Anki Dry-Run Profile

Anki is a text/card-style shared profile. The current descriptor and thin adapter emit normalized `text` chunks from plain-text Anki exports while preserving card fields and source grounding. This profile does not assume MCQ structure at ingestion time.

The downstream milestone is intentionally dry-run only:

1. Shared ingestion emits normalized Anki text chunks.
2. `anki_profile_runner.py` invokes the existing Anki wrapper with one selected input in dry-run mode.
3. The wrapper emits app-ready JSON.
4. BIC discovers that output and the renderer accepts it through the existing NBME Gemini-style importer path.

The accepted app-ready JSON proves orchestration and import compatibility for placeholder dry-run output. It is not a live semantic generator milestone and does not validate live Gemini Anki generation or question quality.

## OME Dry-Run Profile

OME is a text-first PDF source. Its shared adapter reuses native text extraction through `pdfplumber`, emits normalized text chunks, and keeps the existing OME generator as the downstream boundary.

The validated BIC route is intentionally dry-run only:

1. Shared ingestion emits normalized OME text chunks.
2. `ome_profile_runner.py` calls the existing OME generator with one selected PDF, `--dry-run`, and a controlled output directory.
3. The generator emits app-ready JSON through the existing OME formatting path.
4. BIC discovers that JSON and the renderer imports it through the existing NBME Gemini-style importer path.

That path proves selected-input orchestration, import compatibility, quiz rendering, and persistence for placeholder dry-run output. It does not validate live Gemini OME generation or real OME question quality.

## Divine Transcript Dry-Run Profile

Divine Transcript is transcript-first. Its active shared profile accepts `.txt` and `.md` transcript inputs, emits normalized chunks with `chunkType: transcript`, and keeps the existing Divine generator as the app-ready output boundary.

The validated BIC route is dry-run only:

1. Shared ingestion emits normalized Divine transcript chunks.
2. `divine_transcript_profile_runner.py` calls the existing Divine generator with one selected transcript, `--dry-run`, and a controlled output directory.
3. The existing Divine generator emits app-ready JSON from that dry-run handoff.
4. BIC discovers that JSON and the renderer imports it through the existing importer path.

That path proves transcript-first dry-run orchestration, importer compatibility, packaged auto-import, and score history persistence for `.txt` and `.md` inputs. It does not add audio support or validate live Gemini Divine generation or transcription.

## Batch Import Center

BIC lives in:

- `tools/batch-import-center/pipeline_registry.json`
- `tools/batch-import-center/run_pipeline_job.py`
- Electron IPC handlers in `electron/main.js`
- Renderer UI in `index.html`

BIC responsibilities:

- Read the source registry.
- Select files or folders through Electron native dialogs.
- Write a job manifest.
- Spawn Python jobs.
- Stream progress events.
- Discover `*_app_ready.json` outputs.
- Read output JSON for import.
- Update job history.

BIC does not judge semantic quality. It proves orchestration, discovery, validation, and import wiring.

## App-Ready JSON Flow

The app imports app-ready JSON through existing JSON import helpers in `index.html`.

Two broad JSON shapes are used:

- NBME-style `testTitle` plus `questions`.
- Internal app-ready `questions[]` with compact fields such as `t`, `o`, `c`.

Images & Tables uses internal app-ready cards with canonical fields plus compact quiz fields. This path is validated because it preserves direct `q.images[]` and persists image data into `FigureStore`.

## Validation And Import Path

The validated import path is:

1. BIC discovers output.
2. Electron reads output JSON.
3. Renderer validates the JSON.
4. Renderer imports through `importValidatedBatchOutputJsonText`.
5. `DB.createTest` saves the test.
6. `_persistLandingJsonInlineImages` writes image `dataUrl` values into `FigureStore` and removes inline image data from saved questions.

This path is validated for Images & Tables profile in packaged app at v4.15.

## FigureStore And Persistence

`FigureStore` is IndexedDB storage for large image payloads. App question metadata keeps `figureKey`, not permanent base64 blobs. The stable image rendering path is:

```text
q.images[] or q.explanationImages[]
  -> figureKey
  -> FigureStore.get(figureKey)
  -> renderStoredImagesInto()
```

Do not reintroduce large `dataUrl` storage into localStorage.

## Electron And Python Orchestration

Electron main process owns native capabilities:

- Native file/folder picker.
- Python job spawning.
- Gemini environment propagation for sources that require Gemini.
- Packaged app serving.

Python runners own source extraction/generation. Renderer code owns import and quiz state. Keep this boundary.

## Cache Layers

Cache layers are source-specific:

- Fast Facts has an incremental generation cache foundation but semantic quality remains unstable.
- Shared descriptors expose `cache_policy`, but not every profile has a fully implemented cache.
- Images & Tables currently uses source asset hashes for deterministic asset naming, not a large scalable cache index.

## Provenance Metadata

Provenance is carried in:

- normalized chunk `sourceGrounding`
- normalized chunk `metadata`
- app-ready question `metadata`
- BIC completion reports

Emma normalized-chunk downstream carries chunk bundle hash/id/count into app-ready metadata. Images & Tables carries source path, chunk id, asset kind, classification reason, OCR availability, and attachment confidence.

## Variable-Choice Support

AMBOSS introduced variable-choice support in v4.5. This is a validated AMBOSS-specific behavior. Do not assume all sources use the same number of answer choices unless the target importer/generator has been verified for that source.

## Multimodal Ingestion Architecture

Images & Tables is the first validated image-first/table-first shared profile. It validates:

- image and table chunk emission
- OCR text preservation
- asset classification
- attachment-first app-ready JSON
- BIC auto-import
- FigureStore persistence
- image/table rendering after reload
- packaged `.app` behavior

It does not validate advanced semantic visual question generation, deep table parsing, or large-folder scaling.
