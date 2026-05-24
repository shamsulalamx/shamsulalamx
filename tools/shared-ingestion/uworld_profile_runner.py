#!/usr/bin/env python3
"""
Run UWorld notes (txt / md / rtf / docx) through shared normalized chunk
emission, then invoke the existing UWorld generator unchanged.

v4.59 — first BIC integration of the foundational UWorld generator. UWorld
notes are pure text (the user confirmed: "absolutely no images, just text")
so this runner skips any image/table machinery and goes straight to the
shared text-chunk emitter + downstream Gemini generation.

High-yield default: UWorld notes are the densest content the user has, so
questions-per-file is auto-scaled to 1 question per ~500 chars (roughly 3×
Mehlman's 1 question per 1,500 chars). The auto-scale can be overridden by
passing --questions-per-file explicitly.

Supports two modes:
  --mode dry-run   (default) Invoke the existing UWorld generator in
                   dry-run mode, producing placeholder app-ready JSON
                   without calling Gemini.
  --mode generate  Invoke the existing UWorld generator in live mode,
                   calling Gemini to produce real questions from the
                   note content. Requires GEMINI_API_KEY.
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
JOB_OUTPUT_ROOT = (
    Path(os.environ["BIC_JOB_OUTPUT_ROOT"]).expanduser().resolve()
    if os.environ.get("BIC_JOB_OUTPUT_ROOT")
    else None
)
OUTPUT_DIR = JOB_OUTPUT_ROOT / "shared-ingestion" if JOB_OUTPUT_ROOT else SCRIPT_DIR / "output"
UWORLD_GENERATOR = (
    PROJECT_ROOT / "tools" / "uworld-notes-question-generator" / "generate_uworld_questions.py"
)

sys.path.insert(0, str(SCRIPT_DIR))
from chunk_pipeline import run_shared_chunk_pipeline  # noqa: E402
from recovery_contract import recovery_metadata  # noqa: E402

SOURCE_TYPE = "uworld_notes"

# v4.59 high-yield density. The user explicitly asked for higher question
# frequency per content unit than other sources because UWorld notes are
# "extremely high yield." 500 chars per question is roughly 1 question per
# 1-2 dense bullet points or 2-3 sentences — about 3× Mehlman density and
# 6× the prior pre-v4.58 5-questions-per-12K-char Mehlman density.
DEFAULT_CHARS_PER_QUESTION = 500
MIN_AUTO_QUESTIONS_PER_FILE = 5
MAX_AUTO_QUESTIONS_PER_FILE = 80


def emit(event_type: str, **payload: Any) -> None:
    print(
        json.dumps(
            {"type": event_type, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), **payload},
            ensure_ascii=False,
        ),
        flush=True,
    )


def parse_app_ready_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"App-ready output must be a JSON object: {path}")
    if not isinstance(payload.get("questions"), list):
        raise ValueError(f"App-ready output missing questions array: {path}")
    return payload


def extract_text_for_density(input_path: Path) -> tuple[str, str]:
    """Return (extracted_text, dependency_error).

    Uses the same UWorld text extractor the downstream generator uses so
    the char count reflects actual textual content, not byte size of a
    compressed container. .docx files in particular are zipped XML where
    raw byte count can be 40× larger than the real text content — the
    old auto-density math saw a 57 KB .docx file as "80 questions worth"
    when the actual text was 1.4 KB.

    If python-docx / docx2txt / striprtf are missing, extract_text returns
    empty silently. Surface that as a dependency_error string so the
    runner can emit a precise failure instead of treating it as
    legitimately-empty content.
    """
    uworld_dir = Path(__file__).resolve().parent.parent / "uworld-notes-question-generator"
    sys.path.insert(0, str(uworld_dir))
    try:
        import generate_uworld_questions as _uw  # type: ignore
    finally:
        if sys.path and sys.path[0] == str(uworld_dir):
            sys.path.pop(0)

    suffix = input_path.suffix.lower()
    if suffix == ".docx" and not getattr(_uw, "DOCX_AVAILABLE", False):
        return "", "python-docx (or docx2txt) is required for .docx input. Install with: pip install --user python-docx"
    if suffix == ".rtf" and not getattr(_uw, "RTF_AVAILABLE", False):
        return "", "striprtf is required for .rtf input. Install with: pip install --user striprtf"

    try:
        text = _uw.extract_text(input_path)
    except Exception as exc:
        return "", f"text extraction raised: {exc}"
    return text or "", ""


def auto_questions_per_file(text_chars: int) -> int:
    """Convert a known char count to a question target.

    text_chars is the count of actual extracted text, NOT raw file bytes.
    Caller is responsible for the extraction so we don't repeat the
    parse twice.
    """
    target = max(MIN_AUTO_QUESTIONS_PER_FILE, text_chars // DEFAULT_CHARS_PER_QUESTION)
    return min(MAX_AUTO_QUESTIONS_PER_FILE, target)


def run_uworld_generator(input_path: Path, mode: str, questions_per_file: int) -> dict[str, Any]:
    """Invoke generate_uworld_questions.py in either dry-run or live mode."""
    label = "dry-run" if mode == "dry-run" else "live"
    output_root = OUTPUT_DIR / f"uworld_app_ready_{label}" / input_path.stem.replace(" ", "_")
    generator_flag = "--dry-run" if mode == "dry-run" else "--generate"
    command = [
        sys.executable,
        str(UWORLD_GENERATOR),
        "--input-file",
        str(input_path),
        generator_flag,
        "--questions-per-file",
        str(questions_per_file),
        "--output-dir",
        str(output_root),
    ]
    emit(
        "uworld_downstream_start",
        mode=mode,
        questionsPerFile=questions_per_file,
        command=command,
        outputRoot=str(output_root),
    )
    started_at = time.time()
    proc = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ},
    )
    runtime = round(time.time() - started_at, 3)
    if proc.stdout.strip():
        emit("uworld_downstream_stdout", message=proc.stdout.strip()[-4000:])
    if proc.stderr.strip():
        emit("uworld_downstream_stderr", message=proc.stderr.strip()[-4000:])
    if proc.returncode != 0:
        raise RuntimeError(f"UWorld generator ({label}) exited with code {proc.returncode}.")

    app_ready_dir = output_root / "app_ready"
    app_ready_path = app_ready_dir / f"{input_path.stem}_app_ready.json"
    if not app_ready_path.exists():
        discovered = sorted(app_ready_dir.glob("*_app_ready.json")) if app_ready_dir.exists() else []
        if len(discovered) == 1:
            app_ready_path = discovered[0]
        else:
            raise FileNotFoundError(
                f"UWorld generator ({label}) did not produce expected app-ready JSON: {app_ready_path}"
            )
    payload = parse_app_ready_json(app_ready_path)
    schema_label = f"uworld-downstream-{label}-report-v1"
    report = {
        "schemaVersion": schema_label,
        "mode": mode,
        "outputRoot": str(output_root),
        "appReadyPath": str(app_ready_path),
        "schemaVersionObserved": payload.get("schemaVersion"),
        "sourceFormat": payload.get("sourceFormat"),
        "questionCount": len(payload.get("questions") or []),
        "questionsPerFile": questions_per_file,
        "runtimeSeconds": runtime,
        "exitCode": proc.returncode,
    }
    emit("uworld_downstream_complete", ok=True, report=report, outputs=[str(app_ready_path)])
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit normalized UWorld notes text chunks through shared ingestion."
    )
    parser.add_argument("--input-file", required=True, help="UWorld notes file (.txt, .md, .rtf, .docx).")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Chunk limit for the normalization run. 0 (default, v4.59) = no cap.",
    )
    parser.add_argument("--chunk-output", default="")
    parser.add_argument(
        "--mode",
        choices=["dry-run", "generate"],
        default="dry-run",
        help=(
            "dry-run: produce placeholder app-ready JSON without calling Gemini. "
            "generate: call Gemini to produce real questions (requires GEMINI_API_KEY)."
        ),
    )
    parser.add_argument(
        "--questions-per-file",
        type=int,
        default=0,
        help=(
            "Target questions per file. 0 (default) = auto-scale to ~1 question per "
            f"{DEFAULT_CHARS_PER_QUESTION} chars for high-yield UWorld density."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = args.mode
    input_path = Path(args.input_file).expanduser().resolve()
    if not input_path.exists():
        emit("uworld_profile_complete", ok=False, error=f"Input file not found: {input_path}")
        return 1

    # v4.59 follow-up: extract text once up front so the density calc uses
    # actual text chars (not .docx byte count, which overcounts ~40×) AND
    # so we can fail fast with an actionable error if extraction returned
    # empty because of a missing dependency (python-docx / striprtf).
    extracted_text, dep_error = extract_text_for_density(input_path)
    if dep_error:
        emit(
            "uworld_profile_complete",
            ok=False,
            error=dep_error,
            inputPath=str(input_path),
            hint="Missing Python dependency. Install it on the Python interpreter the .app subprocesses use (system python3 on macOS).",
        )
        return 1
    extracted_chars = len(extracted_text)
    if extracted_chars == 0 and input_path.stat().st_size > 100:
        emit(
            "uworld_profile_complete",
            ok=False,
            error=f"Extracted 0 chars of text from a non-empty {input_path.suffix} file. The file may be image-only, password-protected, or use an unsupported encoding.",
            inputPath=str(input_path),
            fileBytes=input_path.stat().st_size,
        )
        return 1

    questions_per_file = (
        int(args.questions_per_file)
        if args.questions_per_file > 0
        else auto_questions_per_file(extracted_chars)
    )

    limit = max(0, int(args.limit or 0))
    chunk_output = (
        Path(args.chunk_output).expanduser().resolve()
        if args.chunk_output
        else (OUTPUT_DIR / f"{input_path.stem.replace(' ', '_')}_uworld_normalized_chunks.json")
    )
    started_at = time.time()
    emit(
        "uworld_profile_start",
        inputPath=str(input_path),
        mode=mode,
        limit=limit,
        extractedChars=extracted_chars,
        questionsPerFile=questions_per_file,
        densityMode="auto" if args.questions_per_file == 0 else "explicit",
    )
    shared = run_shared_chunk_pipeline(
        source_type=SOURCE_TYPE,
        input_path=input_path,
        output_path=chunk_output,
        limit=limit,
    )
    report = shared["report"]
    emit(
        "uworld_normalized_chunks",
        outputPath=str(chunk_output),
        chunkCount=report.get("chunkCount", 0),
        stageTimings=report.get("stageTimings", {}),
        warnings=report.get("warnings", []),
        errors=report.get("errors", []),
    )
    if not report.get("ok"):
        emit(
            "uworld_profile_complete",
            ok=False,
            error="Shared normalized chunk validation failed.",
            report=report,
        )
        return 1

    downstream_report: dict[str, Any] | None = None
    try:
        downstream_report = run_uworld_generator(input_path, mode, questions_per_file)
    except Exception as exc:
        final_report = {
            "schemaVersion": "uworld-profile-runner-report-v1",
            "sourceType": SOURCE_TYPE,
            "mode": mode,
            "inputPath": str(input_path),
            "normalizedChunkPath": str(chunk_output),
            "normalizedChunkCount": report.get("chunkCount", 0),
            "sharedStageTimings": report.get("stageTimings", {}),
            "questionsPerFile": questions_per_file,
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
        emit("uworld_profile_complete", ok=False, error=str(exc), report=final_report, outputs=[])
        return 1

    downstream_status = f"{mode}-completed"
    final_report = {
        "schemaVersion": "uworld-profile-runner-report-v1",
        "sourceType": SOURCE_TYPE,
        "mode": mode,
        "inputPath": str(input_path),
        "normalizedChunkPath": str(chunk_output),
        "normalizedChunkCount": report.get("chunkCount", 0),
        "sharedStageTimings": report.get("stageTimings", {}),
        "questionsPerFile": questions_per_file,
        "downstreamStatus": downstream_status,
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
    emit(
        "uworld_profile_complete",
        ok=True,
        report=final_report,
        outputs=final_report["outputPaths"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
