#!/usr/bin/env python3
"""
Unified intermediate schema for shared ingestion chunks.

Schema name: shared-normalized-chunk-bundle-v1

Top-level bundle:
- schemaVersion: "shared-normalized-chunk-bundle-v1"
- sourceDescriptor: SourceDescriptor dictionary
- sourceFile: original file or artifact name
- sourcePath: source path used by the adapter
- createdAt: UTC ISO timestamp
- chunkCount: number of chunks
- chunks: list[NormalizedChunk]
- warnings: bundle-level warnings

NormalizedChunk:
- schemaVersion: "shared-normalized-chunk-v1"
- chunkId: stable source-derived id
- chunkType: one of text, slide, question, transcript, image, table
- sourceType: registered source type
- sourceFile: original file or artifact name
- sourceGrounding: page/slide/question/audio grounding metadata
- text: source text preserved for normalization or generation
- textBlocks: optional structured text blocks
- imageRefs: normalized image references
- tableRefs: normalized table references
- confidence: numeric 0.0-1.0 plus label in metadata when available
- metadata: source-specific metadata that should survive adapter conversion
- warnings: chunk-level warnings

AssetRef:
- refId: stable id
- kind: image, table, stem_image, explanation_image, table_image, algorithm, chart, unknown
- role: stem, explanation, context, review, unknown
- path: file path when available
- text: OCR/native visible text when available
- grounding: source page/slide/question coordinates or ids
- confidence: 0.0-1.0
- metadata: source-specific extra fields
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


BUNDLE_SCHEMA_VERSION = "shared-normalized-chunk-bundle-v1"
CHUNK_SCHEMA_VERSION = "shared-normalized-chunk-v1"

ChunkType = Literal["text", "slide", "question", "transcript", "image", "table"]
AssetKind = Literal["image", "table", "stem_image", "explanation_image", "algorithm", "table_image", "chart", "unknown"]
AssetRole = Literal["stem", "explanation", "context", "review", "unknown"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AssetRef:
    refId: str
    kind: AssetKind
    role: AssetRole = "unknown"
    path: str = ""
    text: str = ""
    grounding: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["confidence"] = clamp_confidence(data["confidence"])
        return data


@dataclass
class NormalizedChunk:
    chunkId: str
    chunkType: ChunkType
    sourceType: str
    sourceFile: str
    sourceGrounding: dict[str, Any]
    text: str = ""
    textBlocks: list[dict[str, Any]] = field(default_factory=list)
    imageRefs: list[dict[str, Any]] = field(default_factory=list)
    tableRefs: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    schemaVersion: str = CHUNK_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["confidence"] = clamp_confidence(data["confidence"])
        return data


def clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.5
    return max(0.0, min(1.0, number))


def build_chunk_bundle(
    *,
    source_descriptor: dict[str, Any],
    source_file: str,
    source_path: str,
    chunks: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": BUNDLE_SCHEMA_VERSION,
        "sourceDescriptor": source_descriptor,
        "sourceFile": source_file,
        "sourcePath": source_path,
        "createdAt": utc_now_iso(),
        "chunkCount": len(chunks),
        "chunks": chunks,
        "warnings": warnings or [],
    }


def validate_chunk_bundle(bundle: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if bundle.get("schemaVersion") != BUNDLE_SCHEMA_VERSION:
        errors.append("schemaVersion must be shared-normalized-chunk-bundle-v1.")
    chunks = bundle.get("chunks")
    if not isinstance(chunks, list):
        errors.append("chunks must be an array.")
        return errors
    seen: set[str] = set()
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            errors.append(f"chunk {index} is not an object.")
            continue
        chunk_id = str(chunk.get("chunkId") or "")
        if not chunk_id:
            errors.append(f"chunk {index} missing chunkId.")
        elif chunk_id in seen:
            errors.append(f"duplicate chunkId: {chunk_id}")
        seen.add(chunk_id)
        if chunk.get("schemaVersion") != CHUNK_SCHEMA_VERSION:
            errors.append(f"{chunk_id or index}: invalid chunk schemaVersion.")
        if chunk.get("chunkType") not in {"text", "slide", "question", "transcript", "image", "table"}:
            errors.append(f"{chunk_id or index}: invalid chunkType.")
        if not isinstance(chunk.get("sourceGrounding"), dict):
            errors.append(f"{chunk_id or index}: sourceGrounding must be an object.")
        for key in ("imageRefs", "tableRefs", "warnings", "textBlocks"):
            if not isinstance(chunk.get(key), list):
                errors.append(f"{chunk_id or index}: {key} must be an array.")
    if bundle.get("chunkCount") != len(chunks):
        errors.append("chunkCount does not match chunks length.")
    return errors
