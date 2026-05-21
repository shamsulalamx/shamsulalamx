# Shared Ingestion Architecture

Last updated: 2026-05-21

Shared ingestion is the profile layer that normalizes source material before downstream generation or attachment-first app-ready output.

## Design Goal

The goal is convergence without breaking validated pipelines. Each source gets a descriptor and adapter. Existing downstream generation remains in place until a shared downstream can be proven source by source.

## Core Files

- `tools/shared-ingestion/source_descriptor.py`
- `tools/shared-ingestion/normalized_chunk_schema.py`
- `tools/shared-ingestion/pipeline_adapter.py`
- `tools/shared-ingestion/asset_router.py`
- `tools/shared-ingestion/chunk_pipeline.py`
- profile runners under `tools/shared-ingestion/`

## Descriptor Model

Each descriptor captures:

- `source_type`
- `modality`
- `extraction_style`
- `generation_style`
- `asset_policy`
- `cache_policy`
- notes
- source-specific metadata

This is a stable metadata contract, not a new app importer.

## Normalized Bundle

`shared-normalized-chunk-bundle-v1` is the shared intermediate.

Validated chunk types:

- `text`
- `slide`
- `question`
- `transcript`
- `image`
- `table`

Validated asset kinds:

- `image`
- `table`
- `stem_image`
- `explanation_image`
- `table_image`
- `algorithm`
- `chart`
- `unknown`

## Adapters

Adapters should be thin and source-aware. They can call existing extraction functions, but should not change downstream generator quality logic.

Current shared adapters include:

- AMBOSS adapter foundation,
- Emma adapter,
- NBME adapter foundation,
- Fast Facts adapter foundation,
- Mehlman adapter,
- Images & Tables adapter,
- Anki plain-text adapter.

Only the profiles listed in `VALIDATED_PIPELINES.md` should be treated as validated.

## Anki Descriptor And Adapter

Anki now has an `anki_notes` descriptor and a thin plain-text adapter. The adapter reads card-style text exports and emits normalized chunks with `chunkType: text`.

The Anki chunks preserve:

- front and back text when present,
- raw card fields,
- tags,
- cloze terms,
- source path and line/card grounding.

The adapter treats those inputs as card-style source text. It does not assume MCQ structure before the downstream Anki wrapper runs.

## Asset Routing

`asset_router.py` classifies and routes image/table references. It is conservative. For Images & Tables, classification is OCR/filename heuristic:

- algorithm/pathway language -> `algorithm`
- table/criteria/vitamin/lab language -> `table_image`
- chart/graph language -> `chart`
- OCR text without specific signal -> `stem_image`
- no signal -> `unknown`

This is not deep visual reasoning.

## Downstream Strategy

Current downstream approaches:

- Existing generator reuse: Emma, Mehlman.
- Attachment-first runner: Images & Tables.
- Existing generator dry-run handoff: Anki.
- Existing source-specific pipeline: AMBOSS, NBME, Fast Facts.

True shared downstream generation is a future milestone.

## Provenance

Every chunk should preserve:

- source file,
- source path,
- source grounding,
- asset path,
- OCR/native text,
- confidence,
- classification reason where applicable.

App-ready output should carry enough metadata to trace each question back to its normalized chunk.

## Validation

Shared ingestion validation checks:

- schema version,
- chunk array shape,
- chunk IDs,
- chunk types,
- source grounding,
- list fields,
- chunk count consistency.

Passing normalized chunk validation does not prove app-ready import or semantic quality.
