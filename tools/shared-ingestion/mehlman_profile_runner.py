#!/usr/bin/env python3
"""
Mehlman PDF profile runner.

This keeps Mehlman as a profile:
shared-ingestion -> normalized text chunks -> existing Mehlman downstream generator.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from chunk_pipeline import run_shared_chunk_pipeline


RUNNER_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = RUNNER_DIR.parents[1]
MEHLMAN_DIR = PROJECT_ROOT / "tools" / "mehlman-pdf-question-generator"
APP_READY_DIR = MEHLMAN_DIR / "output_json" / "app_ready"
CHUNK_OUTPUT_DIR = RUNNER_DIR / "output"


def emit(event_type: str, **payload: Any) -> None:
    print(json.dumps({"type": event_type, **payload}, ensure_ascii=False), flush=True)


def newest_app_ready_since(started_at: float) -> list[str]:
    if not APP_READY_DIR.exists():
        return []
    paths = [
        path for path in APP_READY_DIR.glob("*_app_ready.json")
        if path.is_file() and path.stat().st_mtime >= started_at - 1
    ]
    return [str(path.resolve()) for path in sorted(paths, key=lambda p: p.stat().st_mtime)]


def run_existing_mehlman_generator(input_file: Path, mode: str, page_limit: int) -> tuple[int, float, list[str]]:
    started_at = time.time()
    command = [
        sys.executable,
        "generate_mehlman_questions.py",
        "--generate" if mode == "generate" else "--dry-run",
        "--input-file",
        str(input_file),
        "--max-pages",
        str(page_limit),
        "--extract-assets",
        "--questions-per-chunk",
        "2",
    ]
    emit("mehlman_downstream_start", command=command, cwd=str(MEHLMAN_DIR))
    proc = subprocess.Popen(
        command,
        cwd=str(MEHLMAN_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        message = line.rstrip("\n")
        if message:
            emit("mehlman_downstream_log", message=message)
    code = proc.wait()
    runtime = round(time.time() - started_at, 3)
    return code, runtime, newest_app_ready_since(started_at)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Mehlman PDF through shared ingestion before existing generation.")
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--mode", choices=["dry-run", "generate"], default="dry-run")
    parser.add_argument("--limit", type=int, default=10, help="First-page limit for validation.")
    parser.add_argument("--chunk-output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_file = Path(args.input_file).expanduser().resolve()
    page_limit = max(1, int(args.limit or 10))
    chunk_output = Path(args.chunk_output).expanduser().resolve() if args.chunk_output else (
        CHUNK_OUTPUT_DIR / f"{input_file.stem.replace(' ', '_')}_mehlman_normalized_chunks.json"
    )
    started_at = time.time()

    emit("mehlman_profile_start", inputFile=str(input_file), mode=args.mode, pageLimit=page_limit)
    shared = run_shared_chunk_pipeline(
        source_type="mehlman_pdf",
        input_path=input_file,
        output_path=chunk_output,
        limit=page_limit,
    )
    report = shared["report"]
    emit(
        "mehlman_normalized_chunks",
        outputPath=str(chunk_output),
        chunkCount=report.get("chunkCount", 0),
        assetCount=report.get("assetCount", 0),
        imageRefCount=report.get("imageRefCount", 0),
        tableRefCount=report.get("tableRefCount", 0),
        stageTimings=report.get("stageTimings", {}),
        warnings=report.get("warnings", []),
        errors=report.get("errors", []),
    )
    if not report.get("ok"):
        emit("mehlman_profile_complete", ok=False, error="Shared normalized chunk validation failed.", report=report)
        return 1

    code, downstream_runtime, outputs = run_existing_mehlman_generator(input_file, args.mode, page_limit)
    final_report = {
        "schemaVersion": "mehlman-profile-runner-report-v1",
        "sourceType": "mehlman_pdf",
        "mode": args.mode,
        "pageLimit": page_limit,
        "normalizedChunkPath": str(chunk_output),
        "normalizedChunkCount": report.get("chunkCount", 0),
        "assetCount": report.get("assetCount", 0),
        "imageRefCount": report.get("imageRefCount", 0),
        "tableRefCount": report.get("tableRefCount", 0),
        "sharedStageTimings": report.get("stageTimings", {}),
        "downstreamRuntimeSeconds": downstream_runtime,
        "totalRuntimeSeconds": round(time.time() - started_at, 3),
        "outputPaths": outputs,
        "warnings": report.get("warnings", []),
        "errors": report.get("errors", []) if code == 0 else [f"Existing Mehlman generator exited with code {code}"],
    }
    emit("mehlman_profile_complete", ok=code == 0, report=final_report, outputs=outputs)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
