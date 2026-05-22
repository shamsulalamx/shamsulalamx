#!/usr/bin/env python3
"""
Run Anki plain-text exports through shared normalized chunk emission.

By default this runner stops after normalized chunks. With
--emit-app-ready-dry-run it invokes the existing Anki wrapper in dry-run mode
with an explicit selected input file and a controlled output directory.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
JOB_OUTPUT_ROOT = Path(os.environ["BIC_JOB_OUTPUT_ROOT"]).expanduser().resolve() if os.environ.get("BIC_JOB_OUTPUT_ROOT") else None
OUTPUT_DIR = JOB_OUTPUT_ROOT / "shared-ingestion" if JOB_OUTPUT_ROOT else SCRIPT_DIR / "output"
ANKI_WRAPPER = PROJECT_ROOT / "tools" / "anki-question-generator" / "generate_anki_questions.py"

sys.path.insert(0, str(SCRIPT_DIR))
from chunk_pipeline import run_shared_chunk_pipeline  # noqa: E402


SOURCE_TYPE = "anki_notes"


def emit(event_type: str, **payload: Any) -> None:
    payload = {"type": event_type, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), **payload}
    print(json.dumps(payload), flush=True)


def parse_app_ready_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"App-ready output must be a JSON object: {path}")
    if not isinstance(payload.get("questions"), list):
        raise ValueError(f"App-ready output missing questions array: {path}")
    return payload


def run_anki_wrapper_dry_run(input_path: Path) -> dict[str, Any]:
    output_root = OUTPUT_DIR / "anki_app_ready_dry_run" / input_path.stem.replace(" ", "_")
    command = [
        sys.executable,
        str(ANKI_WRAPPER),
        "--input-file",
        str(input_path),
        "--dry-run",
        "--output-dir",
        str(output_root),
    ]
    emit("anki_downstream_start", command=command, outputRoot=str(output_root))
    started_at = time.time()
    proc = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    runtime = round(time.time() - started_at, 3)
    if proc.stdout.strip():
        emit("anki_downstream_stdout", message=proc.stdout.strip()[-4000:])
    if proc.stderr.strip():
        emit("anki_downstream_stderr", message=proc.stderr.strip()[-4000:])
    if proc.returncode != 0:
        raise RuntimeError(f"Anki wrapper dry-run exited with code {proc.returncode}.")

    app_ready_path = output_root / "app_ready" / f"{input_path.stem}_app_ready.json"
    if not app_ready_path.exists():
        discovered = sorted((output_root / "app_ready").glob("*_app_ready.json")) if (output_root / "app_ready").exists() else []
        if len(discovered) == 1:
            app_ready_path = discovered[0]
        else:
            raise FileNotFoundError(f"Anki wrapper dry-run did not produce expected app-ready JSON: {app_ready_path}")
    payload = parse_app_ready_json(app_ready_path)
    report = {
        "schemaVersion": "anki-downstream-dry-run-report-v1",
        "outputRoot": str(output_root),
        "appReadyPath": str(app_ready_path),
        "schemaVersionObserved": payload.get("schemaVersion"),
        "sourceFormat": payload.get("sourceFormat"),
        "questionCount": len(payload.get("questions") or []),
        "runtimeSeconds": runtime,
        "exitCode": proc.returncode,
    }
    emit("anki_downstream_complete", ok=True, report=report, outputs=[str(app_ready_path)])
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Anki notes through shared-ingestion normalization.")
    parser.add_argument("--mode", choices=["dry-run", "generate"], default="dry-run")
    parser.add_argument("--input-file", required=True, help="Anki plain-text export file.")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--chunk-output", default="")
    parser.add_argument("--emit-app-ready-dry-run", action="store_true", help="After normalized chunk validation, invoke the existing Anki wrapper in dry-run mode for app-ready output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_file).expanduser().resolve()
    limit = max(0, int(args.limit or 0))
    chunk_output = Path(args.chunk_output).expanduser().resolve() if args.chunk_output else (
        OUTPUT_DIR / f"{input_path.stem.replace(' ', '_')}_anki_normalized_chunks.json"
    )
    started_at = time.time()
    emit("anki_profile_start", inputPath=str(input_path), mode=args.mode, limit=limit)
    shared = run_shared_chunk_pipeline(
        source_type=SOURCE_TYPE,
        input_path=input_path,
        output_path=chunk_output,
        limit=limit,
    )
    report = shared["report"]
    emit(
        "anki_normalized_chunks",
        outputPath=str(chunk_output),
        chunkCount=report.get("chunkCount", 0),
        stageTimings=report.get("stageTimings", {}),
        warnings=report.get("warnings", []),
        errors=report.get("errors", []),
    )
    if not report.get("ok"):
        emit("anki_profile_complete", ok=False, error="Shared normalized chunk validation failed.", report=report)
        return 1
    downstream_report: dict[str, Any] | None = None
    try:
        if args.emit_app_ready_dry_run:
            downstream_report = run_anki_wrapper_dry_run(input_path)
    except Exception as exc:
        final_report = {
            "schemaVersion": "anki-profile-runner-report-v1",
            "sourceType": SOURCE_TYPE,
            "mode": args.mode,
            "inputPath": str(input_path),
            "normalizedChunkPath": str(chunk_output),
            "normalizedChunkCount": report.get("chunkCount", 0),
            "sharedStageTimings": report.get("stageTimings", {}),
            "downstreamStatus": "failed",
            "downstreamError": str(exc),
            "outputPaths": [],
            "warnings": report.get("warnings", []),
            "errors": [str(exc)],
            "totalRuntimeSeconds": round(time.time() - started_at, 3),
        }
        emit("anki_profile_complete", ok=False, error=str(exc), report=final_report, outputs=[])
        return 1

    final_report = {
        "schemaVersion": "anki-profile-runner-report-v1",
        "sourceType": SOURCE_TYPE,
        "mode": args.mode,
        "inputPath": str(input_path),
        "normalizedChunkPath": str(chunk_output),
        "normalizedChunkCount": report.get("chunkCount", 0),
        "sharedStageTimings": report.get("stageTimings", {}),
        "downstreamStatus": "dry-run-completed" if downstream_report else "not-requested",
        "downstreamReport": downstream_report,
        "outputPaths": [downstream_report["appReadyPath"]] if downstream_report else [],
        "warnings": report.get("warnings", []),
        "errors": [],
        "totalRuntimeSeconds": round(time.time() - started_at, 3),
    }
    emit("anki_profile_complete", ok=True, report=final_report, outputs=final_report["outputPaths"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
