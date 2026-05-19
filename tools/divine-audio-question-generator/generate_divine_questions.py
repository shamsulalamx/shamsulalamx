#!/usr/bin/env python3
"""
Divine Intervention Podcast Audio → Step 2 Question Generator

Pipeline stages:
  1. Audio ingestion      input_audio/*.{mp3,m4a,wav}
  2. Gemini transcription → transcripts/raw/<stem>_raw.txt
  3. Transcript cleanup  → transcripts/cleaned/<stem>_cleaned.txt
  4. Chunking            → output_json/chunks/<stem>_chunks.json
  5. Question generation → output_json/app_ready/<stem>_app_ready.json

Usage:
  python3 generate_divine_questions.py --dry-run
  python3 generate_divine_questions.py --transcribe-only
  python3 generate_divine_questions.py --clean-only
  python3 generate_divine_questions.py --chunk-only
  python3 generate_divine_questions.py --generate
  python3 generate_divine_questions.py --generate --questions-per-file 15

For --dry-run: place cleaned transcripts in transcripts/cleaned/ (test fixture included).
For --generate: place audio files in input_audio/. Existing transcripts are reused
  automatically — delete them to force re-transcription or re-cleaning.

Reuses from tools/uworld-notes-question-generator/generate_uworld_questions.py:
  Gemini HTTP client, JSON cleaning, 3-stage JSON parse, validation, retry/repair,
  split_into_chunks, build_app_ready_json, write_report, dry-run placeholders,
  duplicate stem detection, question renumbering.

New infrastructure in this script:
  Gemini File API upload (multipart/related), file state polling,
  audio-aware generateContent call, transcript cleaning (large output),
  incremental stage resumption.

Security:
  GEMINI_API_KEY read only from os.environ. Never logged, never stored.
  safeExportJson() is applied by the app at import time — no extra action here.
"""

import argparse
import json
import os
import sys
import textwrap
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Import stable UWorld infrastructure ───────────────────────────────────────
_UW_DIR = Path(__file__).parent.parent / "uworld-notes-question-generator"
if not _UW_DIR.is_dir():
    sys.exit(f"ERROR: UWorld generator not found at: {_UW_DIR}")
sys.path.insert(0, str(_UW_DIR))
import generate_uworld_questions as _uw  # noqa: E402

# ── Paths ──────────────────────────────────────────────────────────────────────
_BASE      = Path(__file__).parent
AUDIO_DIR  = _BASE / "input_audio"
RAW_DIR    = _BASE / "transcripts" / "raw"
CLEANED_DIR = _BASE / "transcripts" / "cleaned"
CHUNK_DIR  = _BASE / "output_json" / "chunks"
GEN_DIR    = _BASE / "output_json" / "generated"
DEBUG_DIR  = _BASE / "output_json" / "generated" / "debug"
APP_DIR    = _BASE / "output_json" / "app_ready"
REPORT_DIR = _BASE / "reports"
PROMPTS_DIR = _BASE / "prompts"

SUPPORTED_AUDIO = {".mp3", ".m4a", ".wav"}

# Gemini File API base (separate from the generateContent endpoint)
_GEMINI_FILES_BASE = "https://generativelanguage.googleapis.com"

# ── Patch UWorld globals to point at Divine workspace ─────────────────────────
_uw.DEBUG_DIR  = DEBUG_DIR
_uw.PROMPT_FILE = PROMPTS_DIR / "divine_audio_to_questions_prompt.txt"
_uw.REPORT_DIR = REPORT_DIR

# ── Patch sourceFormat to "divine-audio" ──────────────────────────────────────
_orig_build_app_ready = _uw.build_app_ready_json


def _divine_build_app_ready_json(source_stem, questions, warnings):
    result = _orig_build_app_ready(source_stem, questions, warnings)
    result["sourceFormat"] = "divine-audio"
    return result


_uw.build_app_ready_json = _divine_build_app_ready_json


# ── Audio helpers ──────────────────────────────────────────────────────────────

_MIME_MAP = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}


def _detect_mime_type(filepath: Path) -> str:
    return _MIME_MAP.get(filepath.suffix.lower(), "audio/mpeg")


def _stem_from_raw(path: Path) -> str:
    """Strip '_raw' suffix from raw transcript filename stem."""
    return path.stem.removesuffix("_raw")


def _stem_from_cleaned(path: Path) -> str:
    """Strip '_cleaned' suffix from cleaned transcript filename stem."""
    return path.stem.removesuffix("_cleaned")


# ── Gemini File API: upload ────────────────────────────────────────────────────

def _upload_audio_file(filepath: Path, api_key: str) -> Dict:
    """
    Upload audio to Gemini File API via multipart/related POST.
    Returns the file metadata dict from the API response.

    Timeout: 600 seconds (large MP3s can take minutes to upload).
    Raises: ValueError on HTTP error, RuntimeError on malformed response.
    """
    mime_type = _detect_mime_type(filepath)
    boundary = uuid.uuid4().hex
    metadata_json = json.dumps({"file": {"display_name": filepath.name}}).encode("utf-8")
    file_bytes = filepath.read_bytes()

    body = (
        f"--{boundary}\r\nContent-Type: application/json\r\n\r\n".encode("utf-8")
        + metadata_json
        + f"\r\n--{boundary}\r\nContent-Type: {mime_type}\r\n\r\n".encode("utf-8")
        + file_bytes
        + f"\r\n--{boundary}--\r\n".encode("utf-8")
    )

    upload_url = f"{_GEMINI_FILES_BASE}/upload/v1beta/files?key={api_key}"
    req = urllib.request.Request(
        upload_url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/related; boundary={boundary}"},
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise ValueError(f"File API upload HTTP {e.code}: {body_text[:400]}")

    file_meta = data.get("file", {})
    if not file_meta.get("name"):
        raise RuntimeError(
            f"File API returned unexpected response (missing 'name'): {str(data)[:300]}"
        )
    return file_meta


# ── Gemini File API: poll ──────────────────────────────────────────────────────

def _poll_file_active(file_name: str, api_key: str, max_wait: int = 300) -> Dict:
    """
    Poll Gemini File API until file state transitions to ACTIVE.
    file_name: e.g. "files/abc123" (from upload response).
    Uses exponential backoff: 5s, 10s, 15s, ... up to 30s.
    Raises: TimeoutError if max_wait exceeded, RuntimeError on FAILED state.
    """
    poll_url = f"{_GEMINI_FILES_BASE}/v1beta/{file_name}?key={api_key}"
    deadline = time.time() + max_wait
    attempt = 0

    while time.time() < deadline:
        attempt += 1
        try:
            req = urllib.request.Request(poll_url, method="GET")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise ValueError(f"File API poll HTTP {e.code}: {body_text[:300]}")

        state = data.get("state", "PROCESSING")
        if state == "ACTIVE":
            return data
        if state == "FAILED":
            raise RuntimeError(f"Gemini File API: processing FAILED for {file_name}")

        wait_s = min(5 * attempt, 30)
        _uw.log(f"    {file_name}: state={state}, waiting {wait_s}s...")
        time.sleep(wait_s)

    raise TimeoutError(
        f"File {file_name} did not become ACTIVE within {max_wait}s"
    )


# ── Gemini generateContent: audio multimodal ───────────────────────────────────

def _transcribe_with_gemini(file_uri: str, mime_type: str, api_key: str) -> str:
    """
    Call Gemini generateContent with an audio file reference (multimodal).
    Uses 65536 max output tokens (maximum for gemini-2.5-flash) and 300s timeout.
    Warns if output is truncated at MAX_TOKENS.
    Returns the transcription text.
    """
    prompt_path = PROMPTS_DIR / "transcribe_audio_prompt.txt"
    if prompt_path.exists():
        prompt = prompt_path.read_text(encoding="utf-8").strip()
    else:
        prompt = (
            "Transcribe this medical podcast completely and verbatim. "
            "Output only the spoken content as plain text paragraphs."
        )

    url = f"{_uw.GEMINI_API_BASE}/{_uw.GEMINI_MODEL}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{
            "role": "user",
            "parts": [
                {"fileData": {"mimeType": mime_type, "fileUri": file_uri}},
                {"text": prompt},
            ],
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 65536,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini transcription HTTP {e.code}: {body_text[:400]}")

    candidates = raw.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini transcription: no candidates returned")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError("Gemini transcription: empty parts in candidate")

    finish = candidates[0].get("finishReason", "")
    if finish == "MAX_TOKENS":
        _uw.warn(
            "Transcription output was truncated (MAX_TOKENS). "
            "Episode may be > ~3 hours. Transcript is incomplete."
        )

    return parts[0].get("text", "")


def transcribe_audio(filepath: Path) -> str:
    """
    Full audio transcription pipeline: upload → poll → generateContent.
    Returns raw transcription text.
    Does NOT save to disk — caller saves the returned text.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set")

    mime_type = _detect_mime_type(filepath)
    size_mb = filepath.stat().st_size / (1024 * 1024)
    _uw.log(f"  Uploading {filepath.name} ({size_mb:.1f} MB, {mime_type})...")

    file_meta = _upload_audio_file(filepath, api_key)
    file_name = file_meta["name"]
    file_uri = file_meta.get("uri", f"{_GEMINI_FILES_BASE}/v1beta/{file_name}")
    _uw.log(f"  Upload complete: {file_name}")

    if file_meta.get("state") != "ACTIVE":
        _uw.log("  Waiting for file processing...")
        file_meta = _poll_file_active(file_name, api_key)

    _uw.log("  Transcribing with Gemini...")
    transcript = _transcribe_with_gemini(file_uri, mime_type, api_key)
    _uw.log(f"  Transcription done: {len(transcript):,} chars")
    return transcript


# ── Transcript cleaning ────────────────────────────────────────────────────────

def _gemini_text_call(
    api_key: str,
    prompt: str,
    max_output: int = 32768,
    timeout: int = 180,
) -> str:
    """
    Gemini text generation with configurable output token limit.
    Used for transcript cleaning — podcast transcripts require higher maxOutputTokens
    than the UWorld generator's default of 8192 (which would truncate long transcripts).
    Never logs the API key.
    """
    url = f"{_uw.GEMINI_API_BASE}/{_uw.GEMINI_MODEL}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": max_output,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini HTTP {e.code}: {body_text[:400]}")

    candidates = raw.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini returned no candidates")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError("Gemini returned empty parts")

    finish = candidates[0].get("finishReason", "")
    if finish == "MAX_TOKENS":
        _uw.warn(
            "Cleaning output truncated (MAX_TOKENS). "
            "Transcript may be too long for a single cleaning call."
        )

    return parts[0].get("text", "")


def clean_transcript(raw_text: str, api_key: str) -> str:
    """
    Clean raw podcast transcript using Gemini.
    Removes ads, intros, housekeeping; preserves clinical teaching content.
    Returns cleaned plain text.
    Falls back to raw_text if Gemini returns empty output (defensive).

    Input is capped at 120,000 chars (~30,000 tokens) for the cleaning call.
    Episodes longer than ~90 minutes may exceed this cap.
    """
    template_path = PROMPTS_DIR / "clean_transcript_prompt.txt"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8").strip()
        # Cap raw input to avoid exceeding Gemini context limits
        transcript_input = raw_text[:120000]
        prompt = template.replace("{{TRANSCRIPT}}", transcript_input)
        if len(raw_text) > 120000:
            _uw.warn(
                f"Raw transcript ({len(raw_text):,} chars) exceeds 120,000-char cleaning cap "
                f"— only the first 120,000 chars will be cleaned."
            )
    else:
        prompt = (
            "Clean this medical podcast transcript. Remove ads, intros, housekeeping. "
            f"Preserve all clinical teaching content. Return plain text only.\n\n{raw_text[:120000]}"
        )

    _uw.log(f"  Cleaning transcript ({len(raw_text):,} chars)...")
    cleaned = _gemini_text_call(api_key, prompt, max_output=32768, timeout=180)
    _uw.log(f"  Cleaned: {len(cleaned):,} chars")

    if not cleaned.strip():
        _uw.warn("Transcript cleaning returned empty output — using raw transcript")
        return raw_text

    return cleaned


# ── Stages 4-5: chunking and question generation ───────────────────────────────

def _process_cleaned_transcript(
    stem: str,
    cleaned_text: str,
    questions_per_file: int,
    dry_run: bool,
    report_data: Dict,
) -> None:
    """
    Stages 4-5 of the Divine pipeline.
    Input: stem (base name) + cleaned transcript text (already extracted).
    Outputs: chunks JSON + app-ready JSON.
    Reuses UWorld chunker, Gemini caller, validator, and app-ready builder.
    """
    t_start = time.time()
    _uw.log(f"Generating questions: {stem}")

    if not cleaned_text.strip():
        _uw.warn(f"Empty cleaned transcript for {stem} — skipping question generation")
        report_data["files"][stem] = {
            "status": "skipped",
            "reason": "empty_transcript",
        }
        return

    # Stage 4: Chunk
    chunks = _uw.split_into_chunks(cleaned_text, max_chars=3000)
    chunk_path = CHUNK_DIR / f"{stem}_chunks.json"
    chunk_path.write_text(
        json.dumps(
            {"sourceFile": f"{stem}_cleaned.txt", "chunks": chunks},
            indent=2,
        ),
        encoding="utf-8",
    )
    _uw.log(f"  {len(chunks)} chunk(s) → {chunk_path.name}")

    all_questions: List[Dict] = []
    file_warnings: List[str] = []
    chunk_stats: List[Dict] = []
    gen_stats: Dict = {
        "validationFailures": 0,
        "retries": 0,
        "repairsSucceeded": 0,
        "repairFailures": 0,
    }

    # Stage 5: Generate (or placeholders in dry-run)
    if dry_run:
        _uw.log(f"  [DRY-RUN] Generating {questions_per_file} placeholder questions.")
        all_questions = [_uw._placeholder_question(i + 1) for i in range(questions_per_file)]
        file_warnings.append("dry-run: questions are placeholders, not Gemini-generated")
        chunk_stats = [{"chunk": 1, "status": "dry-run", "questions": questions_per_file}]

    else:
        qpc = max(1, questions_per_file // max(len(chunks), 1))
        remainder = questions_per_file - qpc * len(chunks)
        q_offset = 0
        raw_generated: List[Dict] = []

        for ci, chunk in enumerate(chunks):
            n = qpc + (1 if ci < remainder else 0)
            if n == 0:
                chunk_stats.append({"chunk": ci + 1, "status": "skipped", "requested": 0})
                continue

            _uw.log(f"  Chunk {ci+1}/{len(chunks)} → {n} question(s) from Gemini...")
            c_stat: Dict = {"chunk": ci + 1, "requested": n}

            try:
                qs, chunk_warnings = _uw.call_gemini_with_retry(
                    chunk["chunkText"], n, ci + 1, gen_stats
                )
                qs = _uw.renumber_questions(qs, q_offset)
                raw_generated.extend(qs)
                all_questions.extend(qs)
                file_warnings.extend(chunk_warnings)
                q_offset += len(qs)
                c_stat["status"] = "ok"
                c_stat["generated"] = len(qs)
                _uw.log(f"    ✓ {len(qs)} question(s)")
                time.sleep(1)

            except json.JSONDecodeError as exc:
                msg = f"Chunk {ci+1} JSON parse error: {exc}"
                _uw.warn(msg)
                file_warnings.append(msg)
                c_stat["status"] = "json_error"
                c_stat["error"] = str(exc)

            except Exception as exc:
                msg = f"Chunk {ci+1} failed: {exc}"
                _uw.warn(msg)
                file_warnings.append(msg)
                c_stat["status"] = "error"
                c_stat["error"] = str(exc)

            chunk_stats.append(c_stat)

        dup_warnings = _uw.check_duplicate_stems(all_questions)
        if dup_warnings:
            file_warnings.extend(dup_warnings)
            for w in dup_warnings:
                _uw.warn(w)

        gen_path = GEN_DIR / f"{stem}_generated.json"
        gen_path.write_text(json.dumps(raw_generated, indent=2), encoding="utf-8")
        _uw.log(f"  Generated JSON → {gen_path.name} ({len(raw_generated)} questions)")

    # Build and write app-ready JSON
    app_json = _uw.build_app_ready_json(stem, all_questions, file_warnings)
    app_path = APP_DIR / f"{stem}_app_ready.json"
    app_path.write_text(json.dumps(app_json, indent=2), encoding="utf-8")
    _uw.log(f"  App-ready JSON → {app_path.name} ({len(all_questions)} questions)")

    elapsed = round(time.time() - t_start, 1)
    report_data["files"][stem] = {
        "status": "ok",
        "cleanedChars": len(cleaned_text),
        "chunksProcessed": len(chunks),
        "questionsGenerated": len(all_questions),
        "validationFailures": gen_stats["validationFailures"],
        "retries": gen_stats["retries"],
        "repairsSucceeded": gen_stats["repairsSucceeded"],
        "repairFailures": gen_stats["repairFailures"],
        "warnings": file_warnings,
        "chunkStats": chunk_stats,
        "outputPaths": {
            "appReady": str(app_path),
            "chunks": str(chunk_path),
            "generated": str(GEN_DIR / f"{stem}_generated.json") if not dry_run else None,
        },
        "elapsedSeconds": elapsed,
        "dryRun": dry_run,
    }


# ── Discovery ──────────────────────────────────────────────────────────────────

def discover_audio_files() -> List[Path]:
    if not AUDIO_DIR.exists():
        return []
    return sorted(
        f for f in AUDIO_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_AUDIO
    )


def discover_raw_transcripts() -> List[Path]:
    if not RAW_DIR.exists():
        return []
    return sorted(
        f for f in RAW_DIR.iterdir()
        if f.is_file() and f.name.endswith("_raw.txt")
    )


def discover_cleaned_transcripts() -> List[Path]:
    if not CLEANED_DIR.exists():
        return []
    return sorted(
        f for f in CLEANED_DIR.iterdir()
        if f.is_file() and f.name.endswith("_cleaned.txt")
    )


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Divine Intervention Podcast Audio → Step 2 Question Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            MODES (mutually exclusive):

              --dry-run          Chunk existing cleaned transcripts → placeholder app-ready JSON.
                                 No API key required. Uses transcripts/cleaned/*.txt.
                                 Test fixture: transcripts/cleaned/test_divine_heart_failure_cleaned.txt

              --transcribe-only  Audio files → raw transcripts.
                                 Input: input_audio/. Output: transcripts/raw/.
                                 Skips files that already have a raw transcript.

              --clean-only       Raw transcripts → cleaned transcripts.
                                 Input: transcripts/raw/. Output: transcripts/cleaned/.
                                 Skips files that already have a cleaned transcript.

              --chunk-only       Cleaned transcripts → chunk JSON. No API key required.
                                 Input: transcripts/cleaned/. Output: output_json/chunks/.

              --generate         Full pipeline (all stages). Reuses existing transcripts
                                 if present — delete them to force re-transcription.
                                 Also processes standalone cleaned transcripts without
                                 corresponding audio files.

            AUDIO FORMATS:  .mp3  .m4a  .wav

            INCREMENTAL RUNS:
              --generate checks for existing transcripts/raw/<stem>_raw.txt and
              transcripts/cleaned/<stem>_cleaned.txt before invoking Gemini for those
              stages. Safe to re-run without re-billing for completed stages.

            EXAMPLES:
              python3 generate_divine_questions.py --dry-run
              python3 generate_divine_questions.py --dry-run --questions-per-file 10
              python3 generate_divine_questions.py --transcribe-only
              python3 generate_divine_questions.py --clean-only
              python3 generate_divine_questions.py --chunk-only
              python3 generate_divine_questions.py --generate
              python3 generate_divine_questions.py --generate --questions-per-file 15
        """),
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--dry-run", action="store_true",
        help="No API calls. Chunk cleaned transcripts, write placeholder questions.",
    )
    mode_group.add_argument(
        "--transcribe-only", action="store_true",
        help="Stage 2 only: upload audio to Gemini and save raw transcripts.",
    )
    mode_group.add_argument(
        "--clean-only", action="store_true",
        help="Stage 3 only: clean existing raw transcripts with Gemini.",
    )
    mode_group.add_argument(
        "--chunk-only", action="store_true",
        help="Stage 4 only: chunk cleaned transcripts. No API call.",
    )
    mode_group.add_argument(
        "--generate", action="store_true",
        help="Full pipeline. Reuses existing transcripts when present.",
    )
    parser.add_argument(
        "--questions-per-file", type=int, default=15, metavar="N",
        help="Target questions per audio file or cleaned transcript (default: 15).",
    )
    args = parser.parse_args()

    # ── Startup log ────────────────────────────────────────────────────────────
    mode_label = (
        "dry-run" if args.dry_run
        else "transcribe-only" if args.transcribe_only
        else "clean-only" if args.clean_only
        else "chunk-only" if args.chunk_only
        else "generate (full pipeline)"
    )
    _uw.log("=" * 60)
    _uw.log("Divine Intervention Audio → Question Generator")
    _uw.log(f"  Model:              {_uw.GEMINI_MODEL}")
    _uw.log(f"  Mode:               {mode_label}")
    _uw.log(f"  Questions per file: {args.questions_per_file}")
    _uw.log("=" * 60)

    # ── Create all directories ─────────────────────────────────────────────────
    for d in (
        AUDIO_DIR, RAW_DIR, CLEANED_DIR,
        CHUNK_DIR, GEN_DIR, DEBUG_DIR, APP_DIR, REPORT_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)

    # ── API key check ──────────────────────────────────────────────────────────
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    needs_api = not (args.dry_run or args.chunk_only)
    if needs_api and not api_key:
        _uw.log("ERROR: GEMINI_API_KEY is required for this mode.")
        _uw.log("Set with: export GEMINI_API_KEY=your_key_here")
        sys.exit(1)

    report_data: Dict = {
        "runTimestamp": datetime.now().isoformat(),
        "model": _uw.GEMINI_MODEL,
        "mode": mode_label,
        "questionsPerFile": args.questions_per_file,
        "files": {},
    }
    t_total = time.time()

    # ══════════════════════════════════════════════════════════════════════════
    # Mode: --dry-run
    # ══════════════════════════════════════════════════════════════════════════
    if args.dry_run:
        cleaned_files = discover_cleaned_transcripts()
        if not cleaned_files:
            _uw.log("No cleaned transcripts found in transcripts/cleaned/")
            _uw.log(
                "For --dry-run, place cleaned transcripts in transcripts/cleaned/ "
                "(file must end in _cleaned.txt)"
            )
            _uw.log(
                "A test fixture is committed: "
                "transcripts/cleaned/test_divine_heart_failure_cleaned.txt"
            )
            _uw.write_report(
                {"status": "no_input", "mode": mode_label, "files": {}},
                prefix="divine_generation_report",
            )
            return

        _uw.log(f"Found {len(cleaned_files)} cleaned transcript(s): "
                f"{[f.name for f in cleaned_files]}")
        for cf in cleaned_files:
            stem = _stem_from_cleaned(cf)
            try:
                cleaned_text = cf.read_text(encoding="utf-8")
                _process_cleaned_transcript(
                    stem, cleaned_text, args.questions_per_file, True, report_data
                )
            except Exception as exc:
                _uw.warn(f"Error processing {cf.name}: {exc}")
                report_data["files"][stem] = {"status": "error", "error": str(exc)}

    # ══════════════════════════════════════════════════════════════════════════
    # Mode: --transcribe-only
    # ══════════════════════════════════════════════════════════════════════════
    elif args.transcribe_only:
        audio_files = discover_audio_files()
        if not audio_files:
            _uw.log("No audio files found in input_audio/")
            _uw.log(
                f"Supported formats: {', '.join(sorted(SUPPORTED_AUDIO))}. "
                "Drop files into input_audio/ and re-run."
            )
            _uw.write_report(
                {"status": "no_input", "mode": mode_label, "files": {}},
                prefix="divine_generation_report",
            )
            return

        _uw.log(f"Found {len(audio_files)} audio file(s): {[f.name for f in audio_files]}")
        for af in audio_files:
            raw_path = RAW_DIR / f"{af.stem}_raw.txt"
            if raw_path.exists():
                _uw.log(f"  Skipping {af.name} — raw transcript already exists: {raw_path.name}")
                report_data["files"][af.name] = {"status": "skipped", "reason": "raw_exists"}
                continue
            try:
                transcript = transcribe_audio(af)
                if not transcript.strip():
                    _uw.warn(f"Empty transcription for {af.name} — skipping save")
                    report_data["files"][af.name] = {
                        "status": "error",
                        "error": "empty transcription output",
                    }
                    continue
                raw_path.write_text(transcript, encoding="utf-8")
                _uw.log(f"  Saved → {raw_path.name} ({len(transcript):,} chars)")
                report_data["files"][af.name] = {
                    "status": "ok",
                    "rawChars": len(transcript),
                    "outputPath": str(raw_path),
                }
            except Exception as exc:
                _uw.warn(f"Error transcribing {af.name}: {exc}")
                report_data["files"][af.name] = {"status": "error", "error": str(exc)}

    # ══════════════════════════════════════════════════════════════════════════
    # Mode: --clean-only
    # ══════════════════════════════════════════════════════════════════════════
    elif args.clean_only:
        raw_files = discover_raw_transcripts()
        if not raw_files:
            _uw.log("No raw transcripts found in transcripts/raw/")
            _uw.log(
                "Run --transcribe-only first to generate raw transcripts, "
                "or place _raw.txt files manually in transcripts/raw/"
            )
            _uw.write_report(
                {"status": "no_input", "mode": mode_label, "files": {}},
                prefix="divine_generation_report",
            )
            return

        _uw.log(f"Found {len(raw_files)} raw transcript(s): {[f.name for f in raw_files]}")
        for rf in raw_files:
            stem = _stem_from_raw(rf)
            cleaned_path = CLEANED_DIR / f"{stem}_cleaned.txt"
            if cleaned_path.exists():
                _uw.log(
                    f"  Skipping {rf.name} — cleaned transcript already exists: {cleaned_path.name}"
                )
                report_data["files"][rf.name] = {
                    "status": "skipped",
                    "reason": "cleaned_exists",
                }
                continue
            try:
                raw_text = rf.read_text(encoding="utf-8")
                if not raw_text.strip():
                    _uw.warn(f"Empty raw transcript: {rf.name} — skipping")
                    report_data["files"][rf.name] = {
                        "status": "skipped",
                        "reason": "empty_raw_transcript",
                    }
                    continue
                cleaned_text = clean_transcript(raw_text, api_key)
                cleaned_path.write_text(cleaned_text, encoding="utf-8")
                _uw.log(f"  Saved → {cleaned_path.name} ({len(cleaned_text):,} chars)")
                report_data["files"][rf.name] = {
                    "status": "ok",
                    "rawChars": len(raw_text),
                    "cleanedChars": len(cleaned_text),
                    "outputPath": str(cleaned_path),
                }
            except Exception as exc:
                _uw.warn(f"Error cleaning {rf.name}: {exc}")
                report_data["files"][rf.name] = {"status": "error", "error": str(exc)}

    # ══════════════════════════════════════════════════════════════════════════
    # Mode: --chunk-only
    # ══════════════════════════════════════════════════════════════════════════
    elif args.chunk_only:
        cleaned_files = discover_cleaned_transcripts()
        if not cleaned_files:
            _uw.log("No cleaned transcripts found in transcripts/cleaned/")
            _uw.log("Run --clean-only first, or place _cleaned.txt files manually.")
            _uw.write_report(
                {"status": "no_input", "mode": mode_label, "files": {}},
                prefix="divine_generation_report",
            )
            return

        _uw.log(f"Found {len(cleaned_files)} cleaned transcript(s): "
                f"{[f.name for f in cleaned_files]}")
        for cf in cleaned_files:
            stem = _stem_from_cleaned(cf)
            try:
                cleaned_text = cf.read_text(encoding="utf-8")
                chunks = _uw.split_into_chunks(cleaned_text, max_chars=3000)
                chunk_path = CHUNK_DIR / f"{stem}_chunks.json"
                chunk_path.write_text(
                    json.dumps(
                        {"sourceFile": cf.name, "chunks": chunks},
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                _uw.log(f"  {cf.name} → {len(chunks)} chunk(s) → {chunk_path.name}")
                report_data["files"][cf.name] = {
                    "status": "ok",
                    "chunks": len(chunks),
                    "outputPath": str(chunk_path),
                }
            except Exception as exc:
                _uw.warn(f"Error chunking {cf.name}: {exc}")
                report_data["files"][cf.name] = {"status": "error", "error": str(exc)}

    # ══════════════════════════════════════════════════════════════════════════
    # Mode: --generate (full pipeline)
    # ══════════════════════════════════════════════════════════════════════════
    elif args.generate:
        audio_files = discover_audio_files()
        processed_stems: set = set()

        if audio_files:
            _uw.log(
                f"Found {len(audio_files)} audio file(s): {[f.name for f in audio_files]}"
            )

        for af in audio_files:
            stem = af.stem
            processed_stems.add(stem)
            _uw.log(f"\nProcessing audio: {af.name}")

            try:
                # Stage 2: Transcribe (skip if exists)
                raw_path = RAW_DIR / f"{stem}_raw.txt"
                if raw_path.exists():
                    _uw.log(f"  Reusing raw transcript: {raw_path.name}")
                    raw_text = raw_path.read_text(encoding="utf-8")
                else:
                    raw_text = transcribe_audio(af)
                    if not raw_text.strip():
                        _uw.warn(f"Empty transcription for {af.name} — skipping")
                        report_data["files"][stem] = {
                            "status": "error",
                            "error": "empty transcription output",
                        }
                        continue
                    raw_path.write_text(raw_text, encoding="utf-8")
                    _uw.log(f"  Raw transcript → {raw_path.name} ({len(raw_text):,} chars)")

                # Stage 3: Clean (skip if exists)
                cleaned_path = CLEANED_DIR / f"{stem}_cleaned.txt"
                if cleaned_path.exists():
                    _uw.log(f"  Reusing cleaned transcript: {cleaned_path.name}")
                    cleaned_text = cleaned_path.read_text(encoding="utf-8")
                else:
                    cleaned_text = clean_transcript(raw_text, api_key)
                    cleaned_path.write_text(cleaned_text, encoding="utf-8")
                    _uw.log(
                        f"  Cleaned transcript → {cleaned_path.name} ({len(cleaned_text):,} chars)"
                    )

                # Stages 4-5: Chunk + Generate
                _process_cleaned_transcript(
                    stem, cleaned_text, args.questions_per_file, False, report_data
                )

            except Exception as exc:
                _uw.warn(f"Error processing {af.name}: {exc}")
                report_data["files"][stem] = {"status": "error", "error": str(exc)}

        # Also process standalone cleaned transcripts (no corresponding audio file)
        standalone_cleaned = [
            f for f in discover_cleaned_transcripts()
            if _stem_from_cleaned(f) not in processed_stems
        ]
        if standalone_cleaned:
            _uw.log(
                f"\nProcessing {len(standalone_cleaned)} standalone cleaned transcript(s): "
                f"{[f.name for f in standalone_cleaned]}"
            )
            for cf in standalone_cleaned:
                stem = _stem_from_cleaned(cf)
                try:
                    cleaned_text = cf.read_text(encoding="utf-8")
                    _process_cleaned_transcript(
                        stem, cleaned_text, args.questions_per_file, False, report_data
                    )
                except Exception as exc:
                    _uw.warn(f"Error processing {cf.name}: {exc}")
                    report_data["files"][stem] = {"status": "error", "error": str(exc)}

        if not audio_files and not discover_cleaned_transcripts():
            _uw.log("No audio files found in input_audio/")
            _uw.log("No cleaned transcripts found in transcripts/cleaned/")
            _uw.log(
                "For --generate: drop audio files (.mp3/.m4a/.wav) into input_audio/ "
                "or place cleaned transcripts in transcripts/cleaned/."
            )
            _uw.write_report(
                {"status": "no_input", "mode": mode_label, "files": {}},
                prefix="divine_generation_report",
            )
            return

    # ── Write report ───────────────────────────────────────────────────────────
    report_data["totalElapsedSeconds"] = round(time.time() - t_total, 1)
    _uw.write_report(report_data, prefix="divine_generation_report")
    _uw.log("Done.")


if __name__ == "__main__":
    main()
