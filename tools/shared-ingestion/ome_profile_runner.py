#!/usr/bin/env python3
"""
Run OME PDFs through shared normalized chunk emission.

By default this runner stops after normalized chunks. With
--emit-app-ready-dry-run it invokes the existing OME generator in dry-run mode
with an explicit selected PDF and a controlled output directory.
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
OME_GENERATOR = PROJECT_ROOT / "tools" / "ome-pdf-question-generator" / "generate_ome_questions.py"

sys.path.insert(0, str(SCRIPT_DIR))
from chunk_pipeline import run_shared_chunk_pipeline  # noqa: E402
from recovery_contract import recovery_metadata  # noqa: E402

SOURCE_TYPE = "ome_pdf"


def emit(event_type: str, **payload: Any) -> None:
    print(json.dumps({"type": event_type, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), **payload}, ensure_ascii=False), flush=True)


def parse_app_ready_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"App-ready output must be a JSON object: {path}")
    if not isinstance(payload.get("questions"), list):
        raise ValueError(f"App-ready output missing questions array: {path}")
    return payload


def run_ome_generator_dry_run(input_path: Path) -> dict[str, Any]:
    output_root = OUTPUT_DIR / "ome_app_ready_dry_run" / input_path.stem.replace(" ", "_")
    command = [
        sys.executable,
        str(OME_GENERATOR),
        "--input-file",
        str(input_path),
        "--dry-run",
        "--output-dir",
        str(output_root),
    ]
    emit("ome_downstream_start", command=command, outputRoot=str(output_root))
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
        emit("ome_downstream_stdout", message=proc.stdout.strip()[-4000:])
    if proc.stderr.strip():
        emit("ome_downstream_stderr", message=proc.stderr.strip()[-4000:])
    if proc.returncode != 0:
        raise RuntimeError(f"OME generator dry-run exited with code {proc.returncode}.")

    app_ready_path = output_root / "app_ready" / f"{input_path.stem}_app_ready.json"
    if not app_ready_path.exists():
        discovered = sorted((output_root / "app_ready").glob("*_app_ready.json")) if (output_root / "app_ready").exists() else []
        if len(discovered) == 1:
            app_ready_path = discovered[0]
        else:
            raise FileNotFoundError(f"OME generator dry-run did not produce expected app-ready JSON: {app_ready_path}")
    payload = parse_app_ready_json(app_ready_path)
    report = {
        "schemaVersion": "ome-downstream-dry-run-report-v1",
        "outputRoot": str(output_root),
        "appReadyPath": str(app_ready_path),
        "schemaVersionObserved": payload.get("schemaVersion"),
        "sourceFormat": payload.get("sourceFormat"),
        "questionCount": len(payload.get("questions") or []),
        "runtimeSeconds": runtime,
        "exitCode": proc.returncode,
    }
    emit("ome_downstream_complete", ok=True, report=report, outputs=[str(app_ready_path)])
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit normalized OME PDF text chunks through shared ingestion.")
    parser.add_argument("--input-file", required=True, help="OME text-layer PDF.")
    parser.add_argument("--limit", type=int, default=5, help="Chunk limit for the normalization validation run.")
    parser.add_argument("--chunk-output", default="")
    parser.add_argument("--emit-app-ready-dry-run", action="store_true", help="After normalized chunk validation, invoke the existing OME generator in dry-run mode for app-ready output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_file = Path(args.input_file).expanduser().resolve()
    limit = max(0, int(args.limit or 0))
    chunk_output = Path(args.chunk_output).expanduser().resolve() if args.chunk_output else (
        OUTPUT_DIR / f"{input_file.stem.replace(' ', '_')}_ome_normalized_chunks.json"
    )
    started_at = time.time()
    emit("ome_profile_start", inputFile=str(input_file), limit=limit)
    shared = run_shared_chunk_pipeline(
        source_type=SOURCE_TYPE,
        input_path=input_file,
        output_path=chunk_output,
        limit=limit,
    )
    report = shared["report"]
    emit(
        "ome_normalized_chunks",
        outputPath=str(chunk_output),
        chunkCount=report.get("chunkCount", 0),
        stageTimings=report.get("stageTimings", {}),
        warnings=report.get("warnings", []),
        errors=report.get("errors", []),
    )
    if not report.get("ok"):
        emit("ome_profile_complete", ok=False, error="Shared normalized chunk validation failed.", report=report)
        return 1
    downstream_report: dict[str, Any] | None = None
    try:
        if args.emit_app_ready_dry_run:
            downstream_report = run_ome_generator_dry_run(input_file)
    except Exception as exc:
        final_report = {
            "schemaVersion": "ome-profile-runner-report-v1",
            "sourceType": SOURCE_TYPE,
            "inputPath": str(input_file),
            "normalizedChunkPath": str(chunk_output),
            "normalizedChunkCount": report.get("chunkCount", 0),
            "chunkTypes": report.get("chunkTypes", []),
            "sharedStageTimings": report.get("stageTimings", {}),
            "downstreamStatus": "failed",
            "downstreamError": str(exc),
            "outputPaths": [],
            "warnings": report.get("warnings", []),
            "errors": [str(exc)],
            "totalRuntimeSeconds": round(time.time() - started_at, 3),
        }
        final_report["recovery"] = recovery_metadata(
            source_type=SOURCE_TYPE,
            outcome="failed_fatal",
            warnings=final_report["warnings"],
            fatal_errors=final_report["errors"],
        )
        emit("ome_profile_complete", ok=False, error=str(exc), report=final_report, outputs=[])
        return 1

    final_report = {
        "schemaVersion": "ome-profile-runner-report-v1",
        "sourceType": SOURCE_TYPE,
        "inputPath": str(input_file),
        "normalizedChunkPath": str(chunk_output),
        "normalizedChunkCount": report.get("chunkCount", 0),
        "chunkTypes": report.get("chunkTypes", []),
        "sharedStageTimings": report.get("stageTimings", {}),
        "downstreamStatus": "dry-run-completed" if downstream_report else "not-requested",
        "downstreamReport": downstream_report,
        "outputPaths": [downstream_report["appReadyPath"]] if downstream_report else [],
        "warnings": report.get("warnings", []),
        "errors": [],
        "totalRuntimeSeconds": round(time.time() - started_at, 3),
    }
    candidate_count = int((downstream_report or {}).get("questionCount") or 0)
    final_report["recovery"] = recovery_metadata(
        source_type=SOURCE_TYPE,
        outcome="completed",
        candidate_question_count=candidate_count,
        warnings=final_report["warnings"],
        survivors_import_safe=bool(downstream_report),
        retry_from_scratch_required=False,
    )
    emit("ome_profile_complete", ok=True, report=final_report, outputs=final_report["outputPaths"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
