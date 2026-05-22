#!/usr/bin/env python3
"""
Batch Import Center Python runner.

Accepts a job manifest, resolves the registered source pipeline, emits newline
delimited JSON progress events, and discovers *_app_ready.json outputs.
"""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

SHARED_INGESTION_DIR = Path(__file__).parent.parent / "shared-ingestion"
sys.path.insert(0, str(SHARED_INGESTION_DIR.resolve()))
from recovery_contract import recovery_metadata  # noqa: E402


RUNNER_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = RUNNER_DIR.parents[1]
REGISTRY_PATH = RUNNER_DIR / "pipeline_registry.json"
STANDARD_STAGES = {
    "preflight",
    "extraction",
    "OCR",
    "chunking",
    "normalization",
    "generation",
    "validation",
    "app-ready conversion",
    "import",
    "completed",
}
CURRENT_PROC: subprocess.Popen[str] | None = None
CANCEL_REQUESTED = False
PROGRESS_PREFIX = "BIC_PROGRESS "


def emit(event_type: str, **payload: Any) -> None:
    event = {
        "type": event_type,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **payload,
    }
    print(json.dumps(event, ensure_ascii=False), flush=True)


def parse_pipeline_progress(message: str) -> dict[str, Any] | None:
    if not message.startswith(PROGRESS_PREFIX):
        return None
    try:
        payload = json.loads(message[len(PROGRESS_PREFIX):])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def handle_cancel_signal(signum: int, _frame: Any) -> None:
    global CANCEL_REQUESTED
    CANCEL_REQUESTED = True
    emit("job_cancelled", message=f"Cancellation signal received: {signum}")
    if CURRENT_PROC and CURRENT_PROC.poll() is None:
        try:
            CURRENT_PROC.terminate()
        except Exception:
            pass


signal.signal(signal.SIGTERM, handle_cancel_signal)
signal.signal(signal.SIGINT, handle_cancel_signal)


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
    if "existingOutputValidation" in manifest and not isinstance(manifest["existingOutputValidation"], bool):
        raise ValueError("Manifest existingOutputValidation must be true or false")
    if "outputRoot" in manifest and not isinstance(manifest["outputRoot"], str):
        raise ValueError("Manifest outputRoot must be a string")


def get_source(registry: dict[str, Any], source_type: str) -> dict[str, Any]:
    source = registry.get("sources", {}).get(source_type)
    if not source:
        raise ValueError(f"Unregistered sourceType: {source_type}")
    if source.get("status") != "active":
        raise ValueError(f"Source type is not active: {source_type}")
    return source


def validate_inputs(manifest: dict[str, Any], source: dict[str, Any]) -> list[Path]:
    existing_output_validation = bool(manifest.get("existingOutputValidation"))
    allowed = {".json"} if existing_output_validation else {ext.lower() for ext in source.get("inputExtensions", [])}
    allow_directories = bool(source.get("allowDirectories")) and not existing_output_validation
    paths: list[Path] = []
    for item in manifest["inputs"]:
        raw_path = item.get("path") if isinstance(item, dict) else None
        if not raw_path:
            raise ValueError("Each input must include path")
        path = Path(raw_path).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"Input file does not exist: {path}")
        if path.is_dir():
            if not allow_directories:
                raise ValueError(f"Input directories are not supported for this source: {path}")
            paths.append(path)
            continue
        if not path.is_file():
            raise ValueError(f"Input path is not a file: {path}")
        if allowed and path.suffix.lower() not in allowed:
            raise ValueError(f"Unsupported input extension for {path.name}: {path.suffix}")
        if existing_output_validation and not path.name.endswith("_app_ready.json"):
            raise ValueError(f"Existing-output validation requires *_app_ready.json: {path.name}")
        paths.append(path)
    return paths


def job_output_root(manifest: dict[str, Any]) -> Path | None:
    raw_path = str(manifest.get("outputRoot") or "").strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser().resolve()


def output_dirs(source: dict[str, Any], manifest: dict[str, Any]) -> list[Path]:
    cwd = (PROJECT_ROOT / source["workingDirectory"]).resolve()
    dirs = [(cwd / rel).resolve() for rel in source.get("outputDirectories", [])]
    durable_root = job_output_root(manifest)
    if durable_root:
        dirs.insert(0, durable_root)
    return dirs


def discover_outputs(source: dict[str, Any], manifest: dict[str, Any]) -> dict[str, float]:
    found: dict[str, float] = {}
    for out_dir in output_dirs(source, manifest):
        if not out_dir.exists():
            continue
        for path in out_dir.rglob("*_app_ready.json"):
            if path.is_file():
                found[str(path.resolve())] = path.stat().st_mtime
    return found


def discover_review_draft(manifest: dict[str, Any], started_at: float) -> dict[str, Any] | None:
    durable_root = job_output_root(manifest)
    if not durable_root:
        return None
    path = durable_root / "review" / "lecture_slide_review_draft.json"
    if not path.is_file() or path.stat().st_mtime < started_at - 1:
        return None
    try:
        draft = load_json(path)
    except Exception as exc:
        emit("warning", message=f"Review draft could not be read: {exc}", draftPath=str(path))
        return None
    candidates = draft.get("candidateQuestions")
    survivors = draft.get("validQuestionIndexes")
    if (
        draft.get("draftVersion") != 1
        or draft.get("status") != "needs_review"
        or not isinstance(candidates, list)
        or not candidates
        or not isinstance(survivors, list)
        or not survivors
    ):
        return None
    return {"path": str(path.resolve()), "draft": draft}


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


def normalize_stage(step: dict[str, Any]) -> str:
    stage = str(step.get("stage") or step.get("stageLabel") or "generation").strip()
    aliases = {
        "ocr": "OCR",
        "app-ready": "app-ready conversion",
        "app_ready": "app-ready conversion",
        "app-ready conversion": "app-ready conversion",
        "complete": "completed",
    }
    stage = aliases.get(stage.lower(), stage)
    if stage not in STANDARD_STAGES:
        stage = "generation"
    return stage


def run_command(source: dict[str, Any], manifest: dict[str, Any], input_file: Path, step: dict[str, Any], step_index: int) -> int:
    global CURRENT_PROC
    dry_run = bool(manifest.get("dryRun"))
    cwd = (PROJECT_ROOT / source["workingDirectory"]).resolve()
    cmd = [source.get("pythonExecutable") or "python3", *expand_args(step["args"], input_file)]
    stage_label = str(step.get("stageLabel") or f"Pipeline step {step_index}")
    stage = normalize_stage(step)
    stage_started_at = time.time()
    emit(
        "stage_start",
        message=f"{stage_label} started for {input_file.name}",
        stage=stage,
        stageLabel=stage_label,
        inputFile=str(input_file),
        stepIndex=step_index,
    )
    emit("command_start", cwd=str(cwd), command=cmd, stepIndex=step_index, stageLabel=stage_label)
    env = os.environ.copy()
    durable_root = job_output_root(manifest)
    if durable_root:
        durable_root.mkdir(parents=True, exist_ok=True)
        env["BIC_JOB_OUTPUT_ROOT"] = str(durable_root)
        env["BIC_JOB_ID"] = str(manifest.get("jobId") or "")
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    CURRENT_PROC = proc
    assert proc.stdout is not None
    last_lines: list[str] = []
    lines: queue.Queue[str | None] = queue.Queue()

    def read_stdout() -> None:
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()
    stream_done = False
    heartbeat_seconds = float(step.get("heartbeatSeconds") or (20 if stage in {"OCR", "generation"} else 0))
    next_heartbeat = time.time() + heartbeat_seconds if heartbeat_seconds > 0 else 0
    while not stream_done:
        if CANCEL_REQUESTED:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except Exception:
                pass
        try:
            line = lines.get(timeout=1)
        except queue.Empty:
            if heartbeat_seconds > 0 and proc.poll() is None and time.time() >= next_heartbeat:
                duration = round(time.time() - stage_started_at, 2)
                emit(
                    "stage_heartbeat",
                    message=f"{stage_label} still running after {duration}s",
                    stage=stage,
                    stageLabel=stage_label,
                    durationSeconds=duration,
                    stepIndex=step_index,
                )
                next_heartbeat = time.time() + heartbeat_seconds
            continue
        if line is None:
            stream_done = True
            continue
        message = line.rstrip("\n")
        if message:
            last_lines.append(message)
            last_lines = last_lines[-12:]
        progress = parse_pipeline_progress(message)
        if progress is not None:
            emit(
                "pipeline_progress",
                **{key: value for key, value in progress.items() if key not in {"type", "timestamp", "stage", "stageLabel", "stepIndex"}},
                stage=progress.get("stage") or stage,
                stageLabel=progress.get("stageLabel") or stage_label,
                stepIndex=step_index,
            )
        emit("log", message=message, stageLabel=stage_label)
    code = proc.wait()
    CURRENT_PROC = None
    reader.join(timeout=1)
    duration = round(time.time() - stage_started_at, 2)
    if code == 0:
        emit(
            "stage_complete",
            message=f"{stage_label} completed in {duration}s",
            stage=stage,
            stageLabel=stage_label,
            durationSeconds=duration,
            stepIndex=step_index,
        )
    elif CANCEL_REQUESTED:
        emit(
            "stage_cancelled",
            message=f"{stage_label} cancelled after {duration}s",
            stage=stage,
            stageLabel=stage_label,
            durationSeconds=duration,
            exitCode=code,
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
            stage=stage,
            stageLabel=stage_label,
            durationSeconds=duration,
            exitCode=code,
            failureReason=reason,
            stepIndex=step_index,
        )
    return code


def output_metrics(output_path: Path) -> dict[str, Any]:
    metrics = {
        "questionCount": 0,
        "imageTableCount": 0,
        "figureRefs": [],
        "warnings": [],
        "errors": [],
    }
    try:
        data = load_json(output_path)
    except Exception as exc:
        metrics["errors"].append(f"{rel(output_path)} could not be read: {exc}")
        return metrics
    questions = data.get("questions") if isinstance(data.get("questions"), list) else []
    metrics["questionCount"] = len(questions)
    figure_refs: list[str] = []
    image_table_count = 0
    warnings: list[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        for key in ("figureRefs", "images", "explanationImages", "tables", "explanationTables"):
            value = question.get(key)
            if isinstance(value, list):
                image_table_count += len(value)
                if key == "figureRefs":
                    for item in value:
                        if isinstance(item, dict):
                            ref_id = item.get("id") or item.get("figureId") or item.get("placeholder")
                            if ref_id:
                                figure_refs.append(str(ref_id))
                        elif item:
                            figure_refs.append(str(item))
        extraction_warnings = question.get("extractionWarnings")
        if isinstance(extraction_warnings, list):
            warnings.extend(str(item) for item in extraction_warnings if item)
    metrics["imageTableCount"] = image_table_count
    metrics["figureRefs"] = sorted(set(figure_refs))
    metrics["warnings"] = warnings[:50]
    return metrics


def completion_report(
    manifest: dict[str, Any],
    source: dict[str, Any],
    run_started_at: float,
    outputs: list[str],
    source_summary: dict[str, Any] | None,
    review_draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    question_count = 0
    image_table_count = 0
    figure_refs: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    for output in outputs:
        metrics = output_metrics(Path(output))
        question_count += int(metrics["questionCount"])
        image_table_count += int(metrics["imageTableCount"])
        figure_refs.extend(metrics["figureRefs"])
        warnings.extend(metrics["warnings"])
        errors.extend(metrics["errors"])
    report = {
        "schemaVersion": "batch-import-completion-report-v1",
        "jobId": manifest.get("jobId"),
        "sourceType": manifest.get("sourceType"),
        "targetFolder": (manifest.get("destination") or {}).get("folderId") or "",
        "outputRoot": str(job_output_root(manifest) or ""),
        "runtimeSeconds": round(time.time() - run_started_at, 2),
        "questionCount": question_count,
        "imageTableCount": image_table_count,
        "figureRefs": sorted(set(figure_refs)),
        "cacheHits": (source_summary or {}).get("cacheHits"),
        "cacheMisses": (source_summary or {}).get("cacheMisses"),
        "warnings": warnings[:50],
        "errors": errors[:50],
        "outputJsonPath": outputs[0] if outputs else "",
        "outputPaths": outputs,
        "importedTestId": None,
        "importedTestName": None,
        "stage": "completed",
    }
    if isinstance(review_draft, dict) and isinstance(review_draft.get("draft"), dict):
        draft = review_draft["draft"]
        report.update({
            "status": "needs_review",
            "stage": "needs_review",
            "draftPath": str(review_draft.get("path") or ""),
            "questionCount": len(draft.get("candidateQuestions") or []),
            "warnings": [str(item) for item in draft.get("validationWarnings") or []][:50],
            "errors": [str(item) for item in draft.get("validationErrors") or []][:50],
        })
        report["recovery"] = recovery_metadata(
            source_type=str(manifest.get("sourceType") or ""),
            outcome="needs_review",
            candidate_question_count=len(draft.get("candidateQuestions") or []),
            surviving_question_count=len(draft.get("validQuestionIndexes") or []),
            warnings=report["warnings"],
            review_items=draft.get("reviewItems") or [],
            survivors_import_safe=True,
            retry_from_scratch_required=False,
            resume_checkpoint_safe_later=True,
        )
    else:
        completed_outcome = "failed_fatal" if report["errors"] else "completed"
        report["recovery"] = recovery_metadata(
            source_type=str(manifest.get("sourceType") or ""),
            outcome=completed_outcome,
            candidate_question_count=question_count,
            warnings=report["warnings"],
            fatal_errors=report["errors"],
            survivors_import_safe=bool(outputs and not report["errors"]),
            retry_from_scratch_required=False,
        )
    return report


def command_failure_report(
    manifest: dict[str, Any],
    run_started_at: float,
    step_index: int,
    exit_code: int,
) -> dict[str, Any]:
    error = f"Pipeline step {step_index} exited with code {exit_code}."
    report = {
        "schemaVersion": "batch-import-completion-report-v1",
        "jobId": manifest.get("jobId"),
        "sourceType": manifest.get("sourceType"),
        "targetFolder": (manifest.get("destination") or {}).get("folderId") or "",
        "outputRoot": str(job_output_root(manifest) or ""),
        "runtimeSeconds": round(time.time() - run_started_at, 2),
        "questionCount": 0,
        "imageTableCount": 0,
        "figureRefs": [],
        "warnings": [],
        "errors": [error],
        "outputJsonPath": "",
        "outputPaths": [],
        "importedTestId": None,
        "importedTestName": None,
        "stage": "failed",
        "status": "failed",
    }
    report["recovery"] = recovery_metadata(
        source_type=str(manifest.get("sourceType") or ""),
        outcome="failed_fatal",
        fatal_errors=report["errors"],
    )
    return report


def newest_json_report(source: dict[str, Any], manifest: dict[str, Any], pattern: str, started_at: float) -> Path | None:
    cwd = (PROJECT_ROOT / source["workingDirectory"]).resolve()
    reports_dirs = [cwd / "reports"]
    durable_root = job_output_root(manifest)
    if durable_root:
        reports_dirs.insert(0, durable_root / "lecture-slide-question-generator" / "reports")
    candidates = []
    for reports_dir in reports_dirs:
        if not reports_dir.exists():
            continue
        candidates.extend(
            path for path in reports_dir.glob(pattern)
            if path.is_file() and path.stat().st_mtime >= started_at - 1
        )
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def emit_source_summary(source_type: str, source: dict[str, Any], manifest: dict[str, Any], started_at: float) -> dict[str, Any]:
    if source_type != "fast_facts_pptx":
        return {}
    report_path = newest_json_report(source, manifest, "fast_facts_generation_validation_report_*.json", started_at)
    if not report_path:
        emit("cache_summary", message="Fast Facts cache summary unavailable; validation report not produced.")
        return {}
    try:
        report = load_json(report_path)
    except Exception as exc:
        emit("cache_summary", message=f"Fast Facts cache summary unavailable: {exc}")
        return {}
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
    return {"cacheHits": hits, "cacheMisses": misses}


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

        preflight_started_at = time.time()
        emit("stage_start", stage="preflight", stageLabel="preflight", message="preflight started")
        emit(
            "job_start",
            jobId=manifest["jobId"],
            sourceType=manifest["sourceType"],
            dryRun=bool(manifest.get("dryRun")),
            inputCount=len(inputs),
            outputRoot=str(job_output_root(manifest) or ""),
        )
        emit(
            "stage_complete",
            stage="preflight",
            stageLabel="preflight",
            message="preflight completed",
            durationSeconds=round(time.time() - preflight_started_at, 2),
        )

        run_started_at = time.time()
        before = discover_outputs(source, manifest)
        execute_pipeline = bool(manifest.get("executePipeline"))
        existing_output_validation = bool(manifest.get("existingOutputValidation"))
        if existing_output_validation:
            emit(
                "validation_mode",
                message="Existing app-ready output validation mode enabled; generation skipped.",
                outputs=[str(path) for path in inputs],
            )
        elif manifest.get("dryRun") and not execute_pipeline:
            emit("dry_run", message="Validated manifest and registry. Pipeline execution skipped by dry-run.")
        else:
            for input_file in inputs:
                for step_index, step in enumerate(command_steps(source, bool(manifest.get("dryRun"))), start=1):
                    if CANCEL_REQUESTED:
                        emit(
                            "job_complete",
                            jobId=manifest["jobId"],
                            ok=False,
                            cancelled=True,
                            dryRun=bool(manifest.get("dryRun")),
                            outputs=[],
                            error="Job cancelled.",
                        )
                        return 130
                    code = run_command(source, manifest, input_file, step, step_index)
                    if CANCEL_REQUESTED:
                        emit(
                            "job_complete",
                            jobId=manifest["jobId"],
                            ok=False,
                            cancelled=True,
                            dryRun=bool(manifest.get("dryRun")),
                            outputs=[],
                            error="Job cancelled.",
                        )
                        return 130
                    if code != 0:
                        failure_report = command_failure_report(manifest, run_started_at, step_index, code)
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
                            report=failure_report,
                            error=f"Pipeline step {step_index} exited with code {code}.",
                        )
                        return code

        source_summary = emit_source_summary(manifest["sourceType"], source, manifest, run_started_at)
        after = discover_outputs(source, manifest)
        if existing_output_validation:
            discovered = set(after)
            selected = [str(path.resolve()) for path in inputs]
            outputs = selected[:]
            external = [path for path in selected if path not in discovered]
            if external:
                emit(
                    "warning",
                    message="Selected app-ready output was not in the packaged registered output directories; using explicit existing-output selection after discovery.",
                    externalOutputs=external,
                )
        else:
            new_outputs = {path for path in after if path not in before}
            touched_outputs = {
                path for path, modified_at in after.items()
                if modified_at >= run_started_at - 1
            }
            outputs = sorted(new_outputs | touched_outputs)
        emit("outputs_discovered", outputs=outputs, count=len(outputs))
        review_draft = discover_review_draft(manifest, run_started_at)
        report = completion_report(manifest, source, run_started_at, outputs, source_summary, review_draft)
        emit(
            "stage_complete",
            stage="completed",
            stageLabel="completed",
            message="job completed",
            durationSeconds=report["runtimeSeconds"],
        )
        emit(
            "job_complete",
            jobId=manifest["jobId"],
            ok=True,
            dryRun=bool(manifest.get("dryRun")),
            outputs=outputs,
            report=report,
        )
        return 0
    except Exception as exc:
        emit("job_complete", ok=False, error=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
