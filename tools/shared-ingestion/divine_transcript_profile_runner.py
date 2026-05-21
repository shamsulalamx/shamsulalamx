#!/usr/bin/env python3
"""
Run transcript-only Divine text inputs through shared normalized chunks.

This runner stops at transcript normalization. It does not call Gemini,
generate app-ready JSON, register with Batch Import Center, or persist data.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "output"
SUPPORTED_EXTENSIONS = {".txt", ".md"}

sys.path.insert(0, str(SCRIPT_DIR))
from chunk_pipeline import run_shared_chunk_pipeline  # noqa: E402


SOURCE_TYPE = "divine_transcript"


def emit(event_type: str, **payload: Any) -> None:
    print(json.dumps({"type": event_type, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), **payload}, ensure_ascii=False), flush=True)


def selected_transcript(raw_path: str) -> Path:
    input_path = Path(raw_path).expanduser().resolve()
    if not input_path.exists():
        raise ValueError(f"--input-file does not exist: {input_path}")
    if not input_path.is_file():
        raise ValueError(f"--input-file must be a file: {input_path}")
    if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"--input-file has unsupported extension '{input_path.suffix}'. Supported: {supported}")
    return input_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit transcript-only Divine normalized chunks through shared ingestion.")
    parser.add_argument("--input-file", required=True, help="Divine transcript text file. Supported: .txt, .md.")
    parser.add_argument("--limit", type=int, default=0, help="Optional transcript block limit. 0 emits all blocks.")
    parser.add_argument("--chunk-output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        input_path = selected_transcript(args.input_file)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 2

    limit = max(0, int(args.limit or 0))
    chunk_output = Path(args.chunk_output).expanduser().resolve() if args.chunk_output else (
        OUTPUT_DIR / f"{input_path.stem.replace(' ', '_')}_divine_transcript_normalized_chunks.json"
    )
    started_at = time.time()
    emit("divine_transcript_profile_start", inputFile=str(input_path), limit=limit)
    shared = run_shared_chunk_pipeline(
        source_type=SOURCE_TYPE,
        input_path=input_path,
        output_path=chunk_output,
        limit=limit,
    )
    report = shared["report"]
    chunk_types = report.get("chunkTypes", [])
    transcript_only = chunk_types == ["transcript"] or (not chunk_types and report.get("chunkCount") == 0)
    errors = list(report.get("errors", []))
    if not transcript_only:
        errors.append(f"Divine transcript runner emitted non-transcript chunk types: {chunk_types}")
    ok = bool(report.get("ok")) and not errors
    final_report = {
        "schemaVersion": "divine-transcript-profile-runner-report-v1",
        "sourceType": SOURCE_TYPE,
        "inputPath": str(input_path),
        "normalizedChunkPath": str(chunk_output),
        "normalizedChunkCount": report.get("chunkCount", 0),
        "chunkTypes": chunk_types,
        "sharedStageTimings": report.get("stageTimings", {}),
        "scope": "transcript-first normalized chunks only",
        "warnings": report.get("warnings", []),
        "errors": errors,
        "totalRuntimeSeconds": round(time.time() - started_at, 3),
    }
    emit("divine_transcript_normalized_chunks", outputPath=str(chunk_output), report=final_report)
    emit("divine_transcript_profile_complete", ok=ok, report=final_report, outputs=[str(chunk_output)])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
