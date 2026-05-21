#!/usr/bin/env python3
"""
Batch Import Center Python runner.

Accepts a job manifest, resolves the registered source pipeline, emits newline
delimited JSON progress events, and discovers *_app_ready.json outputs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


RUNNER_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = RUNNER_DIR.parents[1]
REGISTRY_PATH = RUNNER_DIR / "pipeline_registry.json"


def emit(event_type: str, **payload: Any) -> None:
    event = {
        "type": event_type,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **payload,
    }
    print(json.dumps(event, ensure_ascii=False), flush=True)


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def validate_manifest(manifest: dict[str, Any]) -> None:
    required = ["manifestVersion", "jobId", "sourceType", "inputs", "dryRun", "destination"]
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ValueError(f"Manifest missing required field(s): {', '.join(missing)}")
    if manifest["manifestVersion"] != "batch-import-job-v1":
        raise ValueError("Unsupported manifestVersion")
    if not isinstance(manifest["inputs"], list) or not manifest["inputs"]:
        raise ValueError("Manifest inputs must be a non-empty array")
    if "requiresGemini" in manifest and not isinstance(manifest["requiresGemini"], bool):
        raise ValueError("Manifest requiresGemini must be true or false")


def get_source(registry: dict[str, Any], source_type: str) -> dict[str, Any]:
    source = registry.get("sources", {}).get(source_type)
    if not source:
        raise ValueError(f"Unregistered sourceType: {source_type}")
    if source.get("status") != "active":
        raise ValueError(f"Source type is not active: {source_type}")
    return source


def validate_inputs(manifest: dict[str, Any], source: dict[str, Any]) -> list[Path]:
    allowed = {ext.lower() for ext in source.get("inputExtensions", [])}
    paths: list[Path] = []
    for item in manifest["inputs"]:
        raw_path = item.get("path") if isinstance(item, dict) else None
        if not raw_path:
            raise ValueError("Each input must include path")
        path = Path(raw_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise ValueError(f"Input file does not exist: {path}")
        if allowed and path.suffix.lower() not in allowed:
            raise ValueError(f"Unsupported input extension for {path.name}: {path.suffix}")
        paths.append(path)
    return paths


def output_dirs(source: dict[str, Any]) -> list[Path]:
    cwd = (PROJECT_ROOT / source["workingDirectory"]).resolve()
    return [(cwd / rel).resolve() for rel in source.get("outputDirectories", [])]


def discover_outputs(source: dict[str, Any]) -> dict[str, float]:
    found: dict[str, float] = {}
    for out_dir in output_dirs(source):
        if not out_dir.exists():
            continue
        for path in out_dir.rglob("*_app_ready.json"):
            if path.is_file():
                found[str(path.resolve())] = path.stat().st_mtime
    return found


def expand_args(args: list[str], input_file: Path) -> list[str]:
    return [arg.replace("{inputFile}", str(input_file)) for arg in args]


def command_steps(source: dict[str, Any], dry_run: bool) -> list[dict[str, Any]]:
    steps_key = "dryRunSteps" if dry_run else "liveSteps"
    args_key = "dryRunArgs" if dry_run else "liveArgs"
    steps = source.get(steps_key)
    if isinstance(steps, list) and steps:
        return [step for step in steps if isinstance(step, dict) and isinstance(step.get("args"), list)]
    args = source.get(args_key)
    if isinstance(args, list) and args:
        return [{"args": args}]
    raise ValueError(f"Registry source has no {steps_key}")


def run_command(source: dict[str, Any], manifest: dict[str, Any], input_file: Path, step: dict[str, Any], step_index: int) -> int:
    dry_run = bool(manifest.get("dryRun"))
    cwd = (PROJECT_ROOT / source["workingDirectory"]).resolve()
    cmd = [source.get("pythonExecutable") or "python3", *expand_args(step["args"], input_file)]
    stage_label = str(step.get("stageLabel") or f"Pipeline step {step_index}")
    stage_started_at = time.time()
    emit(
        "stage_start",
        message=f"{stage_label} started for {input_file.name}",
        stageLabel=stage_label,
        inputFile=str(input_file),
        stepIndex=step_index,
    )
    emit("command_start", cwd=str(cwd), command=cmd, stepIndex=step_index, stageLabel=stage_label)
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=os.environ.copy(),
    )
    assert proc.stdout is not None
    last_lines: list[str] = []
    for line in proc.stdout:
        message = line.rstrip("\n")
        if message:
            last_lines.append(message)
            last_lines = last_lines[-12:]
        emit("log", message=message, stageLabel=stage_label)
    code = proc.wait()
    duration = round(time.time() - stage_started_at, 2)
    if code == 0:
        emit(
            "stage_complete",
            message=f"{stage_label} completed in {duration}s",
            stageLabel=stage_label,
            durationSeconds=duration,
            stepIndex=step_index,
        )
    else:
        reason = (
            next((line for line in reversed(last_lines) if line.strip().upper().startswith("ERROR:")), "")
            or next((line for line in reversed(last_lines) if line.strip()), f"Process exited with code {code}")
        )
        emit(
            "stage_failed",
            message=f"{stage_label} failed: {reason}",
            stageLabel=stage_label,
            durationSeconds=duration,
            exitCode=code,
            failureReason=reason,
            stepIndex=step_index,
        )
    return code


def newest_json_report(source: dict[str, Any], pattern: str, started_at: float) -> Path | None:
    cwd = (PROJECT_ROOT / source["workingDirectory"]).resolve()
    reports_dir = cwd / "reports"
    if not reports_dir.exists():
        return None
    candidates = [
        path for path in reports_dir.glob(pattern)
        if path.is_file() and path.stat().st_mtime >= started_at - 1
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def emit_source_summary(source_type: str, source: dict[str, Any], started_at: float) -> None:
    if source_type != "fast_facts_pptx":
        return
    report_path = newest_json_report(source, "fast_facts_generation_validation_report_*.json", started_at)
    if not report_path:
        emit("cache_summary", message="Fast Facts cache summary unavailable; validation report not produced.")
        return
    try:
        report = load_json(report_path)
    except Exception as exc:
        emit("cache_summary", message=f"Fast Facts cache summary unavailable: {exc}")
        return
    cache_report = report.get("cacheReport") if isinstance(report.get("cacheReport"), dict) else {}
    hits = int(cache_report.get("cacheHits") or 0)
    misses = int(cache_report.get("cacheMisses") or 0)
    regenerated = int(cache_report.get("regeneratedQuestions") or 0)
    dropped = int(cache_report.get("droppedQuestions") or 0)
    emit(
        "cache_summary",
        message=f"Fast Facts cache hits: {hits}; misses: {misses}; regenerated: {regenerated}; dropped: {dropped}.",
        reportPath=rel(report_path),
        cacheHits=hits,
        cacheMisses=misses,
        regeneratedQuestions=regenerated,
        droppedQuestions=dropped,
        runtimeDurationSeconds=cache_report.get("runtimeDurationSeconds"),
    )


def main() -> int:
    if len(sys.argv) != 2:
        emit("error", message="Usage: run_pipeline_job.py /path/to/manifest.json")
        return 2

    manifest_path = Path(sys.argv[1]).expanduser().resolve()
    try:
        manifest = load_json(manifest_path)
        registry = load_json(REGISTRY_PATH)
        validate_manifest(manifest)
        source = get_source(registry, manifest["sourceType"])
        inputs = validate_inputs(manifest, source)

        emit(
            "job_start",
            jobId=manifest["jobId"],
            sourceType=manifest["sourceType"],
            dryRun=bool(manifest.get("dryRun")),
            inputCount=len(inputs),
        )

        run_started_at = time.time()
        before = discover_outputs(source)
        execute_pipeline = bool(manifest.get("executePipeline"))
        if manifest.get("dryRun") and not execute_pipeline:
            emit("dry_run", message="Validated manifest and registry. Pipeline execution skipped by dry-run.")
        else:
            for input_file in inputs:
                for step_index, step in enumerate(command_steps(source, bool(manifest.get("dryRun"))), start=1):
                    code = run_command(source, manifest, input_file, step, step_index)
                    if code != 0:
                        emit(
                            "command_failed",
                            message=f"Pipeline step {step_index} exited with code {code}. See stage_failed for the explicit failure reason.",
                            exitCode=code,
                            stepIndex=step_index,
                        )
                        emit(
                            "job_complete",
                            jobId=manifest["jobId"],
                            ok=False,
                            dryRun=bool(manifest.get("dryRun")),
                            outputs=[],
                            error=f"Pipeline step {step_index} exited with code {code}.",
                        )
                        return code

        emit_source_summary(manifest["sourceType"], source, run_started_at)
        after = discover_outputs(source)
        new_outputs = {path for path in after if path not in before}
        touched_outputs = {
            path for path, modified_at in after.items()
            if modified_at >= run_started_at - 1
        }
        outputs = sorted(new_outputs | touched_outputs)
        emit("outputs_discovered", outputs=outputs, count=len(outputs))
        emit(
            "job_complete",
            jobId=manifest["jobId"],
            ok=True,
            dryRun=bool(manifest.get("dryRun")),
            outputs=outputs,
        )
        return 0
    except Exception as exc:
        emit("job_complete", ok=False, error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
