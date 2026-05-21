#!/usr/bin/env python3
"""
Emma Holiday profile runner.

This proves the profile flow:
shared-ingestion -> normalized chunks -> existing Emma downstream generator.

The downstream generator and prompts are not modified. This runner only adds
the shared chunk preflight and telemetry around the existing command.
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
LECTURE_DIR = PROJECT_ROOT / "tools" / "lecture-slide-question-generator"
APP_READY_DIR = LECTURE_DIR / "output_json" / "app_ready"
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


def run_existing_emma_generator(input_file: Path, mode: str, limit: int) -> tuple[int, float, list[str]]:
    started_at = time.time()
    command = [
        sys.executable,
        "generate_lecture_slide_questions.py",
        "--generate" if mode == "generate" else "--dry-run",
        "--input-file",
        str(input_file),
        "--limit",
        str(limit),
    ]
    emit("emma_downstream_start", command=command, cwd=str(LECTURE_DIR))
    proc = subprocess.Popen(
        command,
        cwd=str(LECTURE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        message = line.rstrip("\n")
        if message:
            emit("emma_downstream_log", message=message)
    code = proc.wait()
    runtime = round(time.time() - started_at, 3)
    return code, runtime, newest_app_ready_since(started_at)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Emma Holiday through shared ingestion before existing generation.")
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--mode", choices=["dry-run", "generate"], default="dry-run")
    parser.add_argument("--limit", type=int, default=0, help="Limit normalized chunks only. 0 means all chunks.")
    parser.add_argument("--chunk-output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_file = Path(args.input_file).expanduser().resolve()
    limit = max(0, int(args.limit or 0))
    chunk_output = Path(args.chunk_output).expanduser().resolve() if args.chunk_output else (
        CHUNK_OUTPUT_DIR / f"{input_file.stem.replace(' ', '_')}_emma_normalized_chunks.json"
    )
    started_at = time.time()

    emit("emma_profile_start", inputFile=str(input_file), mode=args.mode, limit=limit)
    shared = run_shared_chunk_pipeline(
        source_type="emma_holiday_pdf",
        input_path=input_file,
        output_path=chunk_output,
        limit=limit,
    )
    report = shared["report"]
    emit(
        "emma_normalized_chunks",
        outputPath=str(chunk_output),
        chunkCount=report.get("chunkCount", 0),
        assetCount=report.get("assetCount", 0),
        stageTimings=report.get("stageTimings", {}),
        warnings=report.get("warnings", []),
        errors=report.get("errors", []),
    )
    if not report.get("ok"):
        emit("emma_profile_complete", ok=False, error="Shared normalized chunk validation failed.", report=report)
        return 1

    code, downstream_runtime, outputs = run_existing_emma_generator(input_file, args.mode, limit)
    total_runtime = round(time.time() - started_at, 3)
    final_report = {
        "schemaVersion": "emma-profile-runner-report-v1",
        "sourceType": "emma_holiday_pdf",
        "mode": args.mode,
        "normalizedChunkPath": str(chunk_output),
        "normalizedChunkCount": report.get("chunkCount", 0),
        "assetCount": report.get("assetCount", 0),
        "sharedStageTimings": report.get("stageTimings", {}),
        "downstreamRuntimeSeconds": downstream_runtime,
        "totalRuntimeSeconds": total_runtime,
        "outputPaths": outputs,
        "warnings": report.get("warnings", []),
        "errors": report.get("errors", []) if code == 0 else [f"Existing Emma generator exited with code {code}"],
    }
    emit("emma_profile_complete", ok=code == 0, report=final_report, outputs=outputs)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
