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
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from chunk_pipeline import run_shared_chunk_pipeline
from normalized_chunk_schema import validate_chunk_bundle
from recovery_contract import recovery_metadata


RUNNER_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = RUNNER_DIR.parents[1]
LECTURE_DIR = PROJECT_ROOT / "tools" / "lecture-slide-question-generator"
JOB_OUTPUT_ROOT = Path(os.environ["BIC_JOB_OUTPUT_ROOT"]).expanduser().resolve() if os.environ.get("BIC_JOB_OUTPUT_ROOT") else None
APP_READY_DIR = (
    JOB_OUTPUT_ROOT / "lecture-slide-question-generator" / "output_json" / "app_ready"
    if JOB_OUTPUT_ROOT else LECTURE_DIR / "output_json" / "app_ready"
)
CHUNK_OUTPUT_DIR = JOB_OUTPUT_ROOT / "shared-ingestion" if JOB_OUTPUT_ROOT else RUNNER_DIR / "output"
REVIEW_DRAFT_PATH = JOB_OUTPUT_ROOT / "review" / "lecture_slide_review_draft.json" if JOB_OUTPUT_ROOT else None
CHECKPOINT_PATH = Path(os.environ["BIC_CHECKPOINT_PATH"]).expanduser().resolve() if os.environ.get("BIC_CHECKPOINT_PATH") else None
COMMAND_FINGERPRINT = str(os.environ.get("BIC_COMMAND_FINGERPRINT") or "")


def emit(event_type: str, **payload: Any) -> None:
    print(json.dumps({"type": event_type, **payload}, ensure_ascii=False), flush=True)


def emit_bic_progress(phase: str, message: str, **payload: Any) -> None:
    print(
        "BIC_PROGRESS " + json.dumps(
            {"phase": phase, "source": "emma_holiday_pdf", "message": message, **payload},
            ensure_ascii=False,
        ),
        flush=True,
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def path_lives_under(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def load_checkpoint() -> dict[str, Any]:
    if not CHECKPOINT_PATH or not CHECKPOINT_PATH.is_file():
        return {}
    try:
        payload = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def update_normalization_checkpoint(
    *,
    chunk_output: Path,
    report: dict[str, Any],
    reused: bool,
    restart_reasons: list[str],
) -> None:
    if not CHECKPOINT_PATH or not JOB_OUTPUT_ROOT or not path_lives_under(JOB_OUTPUT_ROOT, CHECKPOINT_PATH):
        return
    if not chunk_output.is_file() or not path_lives_under(JOB_OUTPUT_ROOT, chunk_output):
        return
    checkpoint = load_checkpoint()
    checkpoint.setdefault("stages", {})
    checkpoint["stages"]["normalization"] = {
        "status": "complete",
        "reused": reused,
        "chunkCount": report.get("chunkCount", 0),
        "artifacts": [{
            "kind": "normalized_chunk_bundle",
            "path": str(chunk_output.resolve()),
            "sha256": sha256_file(chunk_output),
        }],
    }
    checkpoint["lastSafeCheckpoint"] = "normalization"
    checkpoint["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    checkpoint["resume"] = {
        "eligible": True,
        "lastSafeStage": "normalization",
        "restartReasons": restart_reasons,
    }
    write_json(CHECKPOINT_PATH, checkpoint)


def normalization_report_from_bundle(bundle: dict[str, Any], chunk_output: Path) -> dict[str, Any]:
    errors = validate_chunk_bundle(bundle)
    chunks = [chunk for chunk in bundle.get("chunks") or [] if isinstance(chunk, dict)]
    return {
        "schemaVersion": "shared-normalized-chunk-report-v1",
        "sourceType": "emma_holiday_pdf",
        "inputPath": str(bundle.get("sourcePath") or ""),
        "outputPath": str(chunk_output),
        "chunkCount": int(bundle.get("chunkCount") or len(chunks)),
        "assetCount": sum(len(chunk.get("imageRefs") or []) + len(chunk.get("tableRefs") or []) for chunk in chunks),
        "imageRefCount": sum(len(chunk.get("imageRefs") or []) for chunk in chunks),
        "tableRefCount": sum(len(chunk.get("tableRefs") or []) for chunk in chunks),
        "stageTimings": {"checkpoint_reuse_seconds": 0},
        "warnings": list(bundle.get("warnings") or []),
        "validationErrors": errors,
        "errors": errors,
        "ok": not errors,
    }


def reusable_normalized_chunks(chunk_output: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not CHECKPOINT_PATH or not JOB_OUTPUT_ROOT:
        return None, ["checkpoint_context_unavailable"]
    checkpoint = load_checkpoint()
    prior_resume = checkpoint.get("resume") if isinstance(checkpoint.get("resume"), dict) else {}
    reasons = [str(item) for item in prior_resume.get("restartReasons") or [] if item]
    if checkpoint.get("sourceType") != "emma_holiday_pdf":
        reasons.append("checkpoint_source_type_mismatch")
    if not COMMAND_FINGERPRINT or (checkpoint.get("generator") or {}).get("commandFingerprint") != COMMAND_FINGERPRINT:
        reasons.append("command_config_fingerprint_mismatch")
    stage = (checkpoint.get("stages") or {}).get("normalization")
    if not isinstance(stage, dict):
        return None, reasons
    artifacts = stage.get("artifacts") if isinstance(stage, dict) else None
    artifact = artifacts[0] if isinstance(artifacts, list) and artifacts and isinstance(artifacts[0], dict) else {}
    artifact_path = Path(str(artifact.get("path") or "")).expanduser()
    if not artifact_path.is_absolute():
        reasons.append("normalized_artifact_path_missing")
    elif artifact_path.resolve() != chunk_output.resolve():
        reasons.append("normalized_artifact_path_changed")
    elif not path_lives_under(JOB_OUTPUT_ROOT, artifact_path):
        reasons.append("normalized_artifact_outside_job_root")
    elif not artifact_path.is_file():
        reasons.append("normalized_artifact_missing")
    elif artifact.get("sha256") != sha256_file(artifact_path):
        reasons.append("normalized_artifact_hash_mismatch")
    if reasons:
        return None, reasons
    try:
        bundle = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, ["normalized_artifact_unreadable"]
    if not isinstance(bundle, dict):
        return None, ["normalized_artifact_not_object"]
    report = normalization_report_from_bundle(bundle, artifact_path)
    if report["errors"]:
        return None, ["normalized_artifact_schema_invalid"]
    return report, []


def newest_app_ready_since(started_at: float) -> list[str]:
    if not APP_READY_DIR.exists():
        return []
    paths = [
        path for path in APP_READY_DIR.glob("*_app_ready.json")
        if path.is_file() and path.stat().st_mtime >= started_at - 1
    ]
    return [str(path.resolve()) for path in sorted(paths, key=lambda p: p.stat().st_mtime)]


def review_draft_since(started_at: float) -> str:
    if not REVIEW_DRAFT_PATH or not REVIEW_DRAFT_PATH.is_file():
        return ""
    if REVIEW_DRAFT_PATH.stat().st_mtime < started_at - 1:
        return ""
    try:
        payload = json.loads(REVIEW_DRAFT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict) or payload.get("draftVersion") != 1 or payload.get("status") != "needs_review":
        return ""
    if not isinstance(payload.get("candidateQuestions"), list) or not payload["candidateQuestions"]:
        return ""
    if not isinstance(payload.get("validQuestionIndexes"), list) or not payload["validQuestionIndexes"]:
        return ""
    return str(REVIEW_DRAFT_PATH.resolve())


def run_existing_emma_generator(input_file: Path, mode: str, limit: int, normalized_chunks: Path | None = None) -> tuple[int, float, list[str]]:
    started_at = time.time()
    command = [
        sys.executable,
        "generate_lecture_slide_questions.py",
        "--generate" if mode == "generate" else "--dry-run",
    ]
    if normalized_chunks:
        command.extend(["--normalized-chunks", str(normalized_chunks)])
    else:
        command.extend(["--input-file", str(input_file), "--limit", str(limit)])
    emit("emma_downstream_start", command=command, cwd=str(LECTURE_DIR))
    proc = subprocess.Popen(
        command,
        cwd=str(LECTURE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "BIC_PROGRESS_SOURCE": "emma_holiday_pdf"},
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        message = line.rstrip("\n")
        if message:
            if message.startswith("BIC_PROGRESS "):
                print(message, flush=True)
            else:
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
    parser.add_argument(
        "--downstream-input",
        choices=["raw-source", "normalized-chunks"],
        default="normalized-chunks",
        help="Choose whether the downstream Emma generator consumes the original PDF or the normalized chunk bundle.",
    )
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
    emit_bic_progress("extracting", f"Starting extraction for {input_file.name}", file=str(input_file))
    emit_bic_progress("chunking", "Preparing normalized chunks", file=str(input_file))
    report, checkpoint_restart_reasons = reusable_normalized_chunks(chunk_output)
    if report:
        emit(
            "emma_normalization_checkpoint_reused",
            outputPath=str(chunk_output),
            chunkCount=report.get("chunkCount", 0),
            checkpointPath=str(CHECKPOINT_PATH),
        )
        emit_bic_progress(
            "chunking",
            f"Reused {report.get('chunkCount', 0)} checkpointed normalized chunk(s)",
            file=str(input_file),
            chunk=report.get("chunkCount", 0),
            chunkTotal=report.get("chunkCount", 0),
        )
        update_normalization_checkpoint(
            chunk_output=chunk_output,
            report=report,
            reused=True,
            restart_reasons=[],
        )
    else:
        if checkpoint_restart_reasons:
            emit(
                "emma_normalization_checkpoint_rejected",
                outputPath=str(chunk_output),
                checkpointPath=str(CHECKPOINT_PATH or ""),
                restartReasons=checkpoint_restart_reasons,
            )
        shared = run_shared_chunk_pipeline(
            source_type="emma_holiday_pdf",
            input_path=input_file,
            output_path=chunk_output,
            limit=limit,
        )
        report = shared["report"]
        if report.get("ok"):
            update_normalization_checkpoint(
                chunk_output=chunk_output,
                report=report,
                reused=False,
                restart_reasons=checkpoint_restart_reasons,
            )
    emit_bic_progress(
        "validating",
        "Validating normalized chunks",
        file=str(input_file),
        chunkTotal=report.get("chunkCount", 0),
    )
    emit_bic_progress(
        "chunking",
        f"Built {report.get('chunkCount', 0)} normalized chunk(s)",
        file=str(input_file),
        chunk=report.get("chunkCount", 0),
        chunkTotal=report.get("chunkCount", 0),
    )
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

    normalized_input = chunk_output if args.downstream_input == "normalized-chunks" else None
    emit_bic_progress(
        "generating",
        "Starting downstream question generation" if args.mode == "generate" else "Starting dry-run question generation",
        file=str(input_file),
        chunkTotal=report.get("chunkCount", 0),
    )
    code, downstream_runtime, outputs = run_existing_emma_generator(input_file, args.mode, limit, normalized_chunks=normalized_input)
    total_runtime = round(time.time() - started_at, 3)
    draft_path = review_draft_since(started_at)
    needs_review = code != 0 and bool(draft_path)
    final_report = {
        "schemaVersion": "emma-profile-runner-report-v1",
        "sourceType": "emma_holiday_pdf",
        "status": "needs_review" if needs_review else ("completed" if code == 0 else "failed"),
        "mode": args.mode,
        "downstreamInput": args.downstream_input,
        "normalizedChunkPath": str(chunk_output),
        "normalizedChunkCount": report.get("chunkCount", 0),
        "assetCount": report.get("assetCount", 0),
        "sharedStageTimings": report.get("stageTimings", {}),
        "downstreamRuntimeSeconds": downstream_runtime,
        "totalRuntimeSeconds": total_runtime,
        "outputPaths": outputs,
        "draftPath": draft_path,
        "warnings": report.get("warnings", []),
        "errors": report.get("errors", []) if code == 0 else [f"Existing Emma generator exited with code {code}"],
    }
    draft: dict[str, Any] = {}
    if draft_path:
        try:
            draft = json.loads(Path(draft_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            draft = {}
    candidates = draft.get("candidateQuestions") if isinstance(draft.get("candidateQuestions"), list) else []
    survivors = draft.get("validQuestionIndexes") if isinstance(draft.get("validQuestionIndexes"), list) else []
    final_report["recovery"] = recovery_metadata(
        source_type="emma_holiday_pdf",
        outcome="needs_review" if needs_review else ("completed" if code == 0 else "failed_fatal"),
        candidate_question_count=len(candidates),
        surviving_question_count=len(survivors),
        warnings=final_report["warnings"] + list(draft.get("validationWarnings") or []),
        fatal_errors=[] if needs_review else final_report["errors"],
        review_items=draft.get("reviewItems") or [],
        survivors_import_safe=needs_review and bool(survivors),
        retry_from_scratch_required=not needs_review and code != 0,
        resume_checkpoint_safe_later=needs_review,
    )
    emit("emma_profile_complete", ok=code == 0 or needs_review, report=final_report, outputs=outputs)
    if needs_review:
        emit_bic_progress("needs_review", "Saved generated Emma questions as a durable review draft.", draftPath=draft_path)
        return 0
    return code


if __name__ == "__main__":
    raise SystemExit(main())
