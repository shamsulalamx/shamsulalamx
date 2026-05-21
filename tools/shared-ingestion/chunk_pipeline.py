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
from pathlib import Path
from typing import Any

from normalized_chunk_schema import validate_chunk_bundle
from pipeline_adapter import emit_normalized_chunks


STAGES = ("extraction", "OCR", "chunking", "normalization", "asset routing", "validation")


def run_shared_chunk_pipeline(
    *,
    source_type: str,
    input_path: Path,
    output_path: Path,
    limit: int,
    refresh: bool = False,
) -> dict[str, Any]:
    bundle = emit_normalized_chunks(
        source_type=source_type,
        input_path=input_path,
        output_path=output_path,
        limit=limit,
        refresh=refresh,
    )
    errors = validate_chunk_bundle(bundle)
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
        "validationErrors": errors,
        "ok": not errors,
    }
    return {"bundle": bundle, "report": report}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit shared normalized chunks from an existing source pipeline.")
    parser.add_argument("--source-type", required=True, choices=["amboss_pdf", "nbme_pdf", "fast_facts_pptx"])
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
