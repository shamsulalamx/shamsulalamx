#!/usr/bin/env python3
"""
Shared normalized chunk orchestration.

Stages are intentionally limited to shared ingestion concerns:
extraction, OCR, chunking, normalization, asset routing, validation.
Downstream app-ready generation remains in existing source pipelines.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from normalized_chunk_schema import validate_chunk_bundle
from pipeline_adapter import emit_normalized_chunks
from recovery_contract import recovery_metadata


STAGES = ("extraction", "OCR", "chunking", "normalization", "asset routing", "validation")


def run_shared_chunk_pipeline(
    *,
    source_type: str,
    input_path: Path,
    output_path: Path,
    limit: int,
    refresh: bool = False,
) -> dict[str, Any]:
    started_at = time.time()
    emit_started_at = time.time()
    bundle = emit_normalized_chunks(
        source_type=source_type,
        input_path=input_path,
        output_path=output_path,
        limit=limit,
        refresh=refresh,
    )
    emit_seconds = round(time.time() - emit_started_at, 3)
    validation_started_at = time.time()
    errors = validate_chunk_bundle(bundle)
    validation_seconds = round(time.time() - validation_started_at, 3)
    total_seconds = round(time.time() - started_at, 3)
    report = {
        "schemaVersion": "shared-normalized-chunk-report-v1",
        "sourceType": source_type,
        "inputPath": str(input_path),
        "outputPath": str(output_path),
        "stages": list(STAGES),
        "chunkCount": bundle.get("chunkCount", 0),
        "chunkTypes": sorted({chunk.get("chunkType") for chunk in bundle.get("chunks", []) if isinstance(chunk, dict)}),
        "imageRefCount": sum(len(chunk.get("imageRefs") or []) for chunk in bundle.get("chunks", []) if isinstance(chunk, dict)),
        "tableRefCount": sum(len(chunk.get("tableRefs") or []) for chunk in bundle.get("chunks", []) if isinstance(chunk, dict)),
        "assetCount": sum(len(chunk.get("imageRefs") or []) + len(chunk.get("tableRefs") or []) for chunk in bundle.get("chunks", []) if isinstance(chunk, dict)),
        "stageTimings": {
            "extraction_to_asset_routing_seconds": emit_seconds,
            "validation_seconds": validation_seconds,
            "total_seconds": total_seconds,
        },
        "warnings": bundle.get("warnings", []),
        "validationErrors": errors,
        "errors": errors,
        "ok": not errors,
    }
    report["recovery"] = recovery_metadata(
        source_type=source_type,
        outcome="completed" if not errors else "failed_fatal",
        warnings=report["warnings"],
        fatal_errors=errors,
        retry_from_scratch_required=bool(errors),
    )
    return {"bundle": bundle, "report": report}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit shared normalized chunks from an existing source pipeline.")
    parser.add_argument("--source-type", required=True, choices=["amboss_pdf", "nbme_pdf", "anki_notes", "uworld_notes", "fast_facts_pptx", "emma_holiday_pdf", "mehlman_pdf", "ome_pdf", "images_tables_source"])
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output-file", required=True)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--refresh", action="store_true", help="Refresh source extraction artifacts when the adapter supports it.")
    parser.add_argument("--report-file", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_shared_chunk_pipeline(
        source_type=args.source_type,
        input_path=Path(args.input_file).expanduser().resolve(),
        output_path=Path(args.output_file).expanduser().resolve(),
        limit=max(0, args.limit),
        refresh=bool(args.refresh),
    )
    if args.report_file:
        Path(args.report_file).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        Path(args.report_file).expanduser().resolve().write_text(
            json.dumps(result["report"], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(json.dumps(result["report"], indent=2, ensure_ascii=False))
    return 0 if result["report"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
