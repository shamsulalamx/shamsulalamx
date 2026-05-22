#!/usr/bin/env python3
"""
Run transcript-only Divine text inputs through shared normalized chunks.

By default this runner stops at transcript normalization. With
--emit-app-ready-dry-run it invokes the existing Divine generator in dry-run
mode with one selected transcript and a controlled output directory.
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
DIVINE_GENERATOR = PROJECT_ROOT / "tools" / "divine-audio-question-generator" / "generate_divine_questions.py"
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


def parse_app_ready_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"App-ready output must be a JSON object: {path}")
    if not isinstance(payload.get("questions"), list):
        raise ValueError(f"App-ready output missing questions array: {path}")
    return payload


def run_divine_generator_dry_run(input_path: Path) -> dict[str, Any]:
    output_root = OUTPUT_DIR / "divine_app_ready_dry_run" / input_path.stem.replace(" ", "_")
    command = [
        sys.executable,
        str(DIVINE_GENERATOR),
        "--input-file",
        str(input_path),
        "--dry-run",
        "--output-dir",
        str(output_root),
    ]
    emit("divine_downstream_start", command=command, outputRoot=str(output_root))
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
        emit("divine_downstream_stdout", message=proc.stdout.strip()[-4000:])
    if proc.stderr.strip():
        emit("divine_downstream_stderr", message=proc.stderr.strip()[-4000:])
    if proc.returncode != 0:
        raise RuntimeError(f"Divine generator dry-run exited with code {proc.returncode}.")

    app_ready_path = output_root / "app_ready" / f"{input_path.stem}_app_ready.json"
    if not app_ready_path.exists():
        discovered = sorted((output_root / "app_ready").glob("*_app_ready.json")) if (output_root / "app_ready").exists() else []
        if len(discovered) == 1:
            app_ready_path = discovered[0]
        else:
            raise FileNotFoundError(f"Divine generator dry-run did not produce expected app-ready JSON: {app_ready_path}")
    payload = parse_app_ready_json(app_ready_path)
    report = {
        "schemaVersion": "divine-downstream-dry-run-report-v1",
        "outputRoot": str(output_root),
        "appReadyOutputPath": str(app_ready_path),
        "observedSchemaVersion": payload.get("schemaVersion"),
        "observedSourceFormat": payload.get("sourceFormat"),
        "observedQuestionCount": len(payload["questions"]),
        "runtimeSeconds": runtime,
        "exitCode": proc.returncode,
    }
    emit("divine_downstream_complete", ok=True, report=report, outputs=[str(app_ready_path)])
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit transcript-only Divine normalized chunks through shared ingestion.")
    parser.add_argument("--input-file", required=True, help="Divine transcript text file. Supported: .txt, .md.")
    parser.add_argument("--limit", type=int, default=0, help="Optional transcript block limit. 0 emits all blocks.")
    parser.add_argument("--chunk-output", default="")
    parser.add_argument("--emit-app-ready-dry-run", action="store_true", help="After normalized chunk validation, invoke the existing Divine generator in dry-run mode for app-ready output.")
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
    downstream_report: dict[str, Any] | None = None
    if ok and args.emit_app_ready_dry_run:
        try:
            downstream_report = run_divine_generator_dry_run(input_path)
        except Exception as exc:
            errors.append(str(exc))
            ok = False
    final_report = {
        "schemaVersion": "divine-transcript-profile-runner-report-v1",
        "sourceType": SOURCE_TYPE,
        "inputPath": str(input_path),
        "normalizedChunkPath": str(chunk_output),
        "normalizedChunkCount": report.get("chunkCount", 0),
        "chunkTypes": chunk_types,
        "sharedStageTimings": report.get("stageTimings", {}),
        "scope": "transcript-first normalized chunks only",
        "downstreamStatus": (
            "dry-run-completed" if downstream_report else
            "failed" if args.emit_app_ready_dry_run and not ok else
            "not-requested"
        ),
        "downstreamReport": downstream_report,
        "appReadyOutputPath": downstream_report["appReadyOutputPath"] if downstream_report else None,
        "observedSchemaVersion": downstream_report["observedSchemaVersion"] if downstream_report else None,
        "observedSourceFormat": downstream_report["observedSourceFormat"] if downstream_report else None,
        "observedQuestionCount": downstream_report["observedQuestionCount"] if downstream_report else None,
        "warnings": report.get("warnings", []),
        "errors": errors,
        "totalRuntimeSeconds": round(time.time() - started_at, 3),
    }
    emit("divine_transcript_normalized_chunks", outputPath=str(chunk_output), report=final_report)
    outputs = [str(chunk_output)]
    if downstream_report:
        outputs.append(downstream_report["appReadyOutputPath"])
    emit("divine_transcript_profile_complete", ok=ok, report=final_report, outputs=outputs)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
