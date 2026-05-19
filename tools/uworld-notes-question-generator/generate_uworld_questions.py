#!/usr/bin/env python3
"""
UWorld Notes → Step 2 Question Generator
Pipeline: notes file → raw text → topic chunks → Gemini questions → canonical v3 JSON

Usage:
  python3 generate_uworld_questions.py [--dry-run] [--generate] [--questions-per-file N]
"""

import argparse
import json
import os
import re
import sys
import textwrap
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Optional imports (graceful degradation) ───────────────────────────────────
try:
    from striprtf.striprtf import rtf_to_text as _rtf_to_text
    RTF_AVAILABLE = True
except ImportError:
    RTF_AVAILABLE = False

try:
    import docx as _docx
    DOCX_AVAILABLE: object = True
except ImportError:
    try:
        import docx2txt as _docx2txt
        DOCX_AVAILABLE = "docx2txt"
    except ImportError:
        DOCX_AVAILABLE = False

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
INPUT_DIR   = BASE_DIR / "input_notes"
RAW_DIR     = BASE_DIR / "output_json" / "raw_text"
CHUNK_DIR   = BASE_DIR / "output_json" / "chunks"
GEN_DIR     = BASE_DIR / "output_json" / "generated"
APP_DIR     = BASE_DIR / "output_json" / "app_ready"
REPORT_DIR  = BASE_DIR / "reports"
PROMPT_FILE = BASE_DIR / "prompts" / "notes_to_questions_prompt.txt"
SCHEMA_FILE = BASE_DIR / "schema" / "uworld_generated_question_schema.json"

SUPPORTED_EXTENSIONS = {".txt", ".md", ".rtf", ".docx"}

# Matches repo convention from tools/nbme-pdf-json-generator/extract_pdfs.py
GEMINI_MODEL    = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

FORBIDDEN_STRINGS = [
    "Here are the questions",
    "```json",
    "eftab720",
    "tightenfactor0",
]


# ── Logging ────────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", file=sys.stderr)


# ── Text extraction ────────────────────────────────────────────────────────────
def extract_text(filepath: Path) -> str:
    ext = filepath.suffix.lower()

    if ext in (".txt", ".md"):
        return filepath.read_text(encoding="utf-8", errors="replace")

    if ext == ".rtf":
        if not RTF_AVAILABLE:
            warn(f"striprtf not installed; skipping {filepath.name}. Run: pip install striprtf")
            return ""
        raw = filepath.read_text(encoding="utf-8", errors="replace")
        try:
            return _rtf_to_text(raw)
        except Exception as exc:
            warn(f"RTF extraction failed for {filepath.name}: {exc}")
            return ""

    if ext == ".docx":
        if not DOCX_AVAILABLE:
            warn(f"python-docx not installed; skipping {filepath.name}. Run: pip install python-docx")
            return ""
        try:
            if DOCX_AVAILABLE == "docx2txt":
                return _docx2txt.process(str(filepath))
            else:
                doc = _docx.Document(str(filepath))
                return "\n".join(para.text for para in doc.paragraphs)
        except Exception as exc:
            warn(f"DOCX extraction failed for {filepath.name}: {exc}")
            return ""

    warn(f"Unsupported extension: {ext}")
    return ""


# ── Chunking ───────────────────────────────────────────────────────────────────
_HEADING_RE = re.compile(
    r"^(?:#+ .+|[A-Z][A-Z\s\-/&]{4,}:|={3,}|-{3,}|\*{3,})\s*$",
    re.MULTILINE,
)


def split_into_chunks(text: str, max_chars: int = 3000) -> List[Dict]:
    """
    Split notes into topic chunks.
    Strategy:
      1. Heading-based splits (markdown # or ALL-CAPS section labels).
      2. Paragraph-boundary fallback.
      3. Hard-cap each chunk at max_chars, splitting on paragraph boundaries.
    """
    boundaries = [m.start() for m in _HEADING_RE.finditer(text)]
    if len(boundaries) >= 2:
        segments = []
        for i, start in enumerate(boundaries):
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
            segments.append(text[start:end].strip())
    else:
        segments = [s.strip() for s in re.split(r"\n{2,}", text) if s.strip()]

    chunks: List[str] = []
    buffer = ""
    for seg in segments:
        if len(buffer) + len(seg) + 2 <= max_chars:
            buffer = (buffer + "\n\n" + seg).strip() if buffer else seg
        else:
            if buffer:
                chunks.append(buffer)
            if len(seg) > max_chars:
                paras = re.split(r"\n{2,}", seg)
                sub_buf = ""
                for p in paras:
                    if len(sub_buf) + len(p) + 2 <= max_chars:
                        sub_buf = (sub_buf + "\n\n" + p).strip() if sub_buf else p
                    else:
                        if sub_buf:
                            chunks.append(sub_buf)
                        sub_buf = p
                if sub_buf:
                    chunks.append(sub_buf)
                buffer = ""
            else:
                buffer = seg

    if buffer:
        chunks.append(buffer)

    return [
        {"chunkIndex": i + 1, "chunkText": c, "charCount": len(c)}
        for i, c in enumerate(chunks)
        if c.strip()
    ]


# ── Validation ─────────────────────────────────────────────────────────────────
def validate_question(q: Dict) -> List[str]:
    """Returns a list of error strings. Empty = valid."""
    errors: List[str] = []

    if not q.get("questionNumber"):
        errors.append("missing questionNumber")

    stem = q.get("stem", "")
    if not stem or not stem.strip():
        errors.append("missing or empty stem")

    choices = q.get("answerChoices", [])
    if len(choices) != 4:
        errors.append(f"expected 4 answerChoices, got {len(choices)}")
    else:
        for c in choices:
            if not c.get("text", "").strip():
                errors.append(f"empty text for choice {c.get('label', '?')}")

    labels = {c.get("label") for c in choices}
    correct = q.get("correctAnswer", "")
    if not correct or correct not in labels:
        errors.append(f"correctAnswer '{correct}' not in choice labels {labels}")

    sections = q.get("explanationSections", [])
    if not sections:
        errors.append("missing explanationSections")
    else:
        for s in sections:
            body = s.get("body", [])
            if not body or all(not b.strip() for b in body):
                errors.append(f"empty body in explanationSection '{s.get('heading', '?')}'")

    if not q.get("retrievalTag", "").strip():
        errors.append("missing or empty retrievalTag")

    if not q.get("reviewPearl", "").strip():
        errors.append("missing or empty reviewPearl")

    blob = json.dumps(q)
    for forbidden in FORBIDDEN_STRINGS:
        if forbidden in blob:
            errors.append(f"forbidden string found: '{forbidden}'")

    return errors


def check_duplicate_stems(questions: List[Dict]) -> List[str]:
    """Returns duplicate-stem warning strings."""
    warnings: List[str] = []
    seen: Dict[str, int] = {}
    for q in questions:
        stem = q.get("stem", "").strip()
        if stem and stem in seen:
            warnings.append(
                f"Duplicate stem: q{str(q.get('questionNumber','?')).zfill(3)} "
                f"matches q{str(seen[stem]).zfill(3)}"
            )
        elif stem:
            seen[stem] = q.get("questionNumber", 0)
    return warnings


# ── Placeholder (dry-run) ──────────────────────────────────────────────────────
def _placeholder_question(n: int) -> Dict:
    idx = str(n).zfill(3)
    return {
        "id": f"q{idx}",
        "questionNumber": n,
        "sourceQuestionNumber": n,
        "retrievalTag": "[DRY-RUN placeholder — not generated]",
        "reviewPearl": "[DRY-RUN placeholder — not generated]",
        "clinicalPearl": None,
        "stem": "[DRY-RUN] This question was not generated. Run without --dry-run to call Gemini.",
        "hasEmbeddedFigure": False,
        "figureRefs": [],
        "answerChoices": [
            {"label": "A", "text": "Placeholder A"},
            {"label": "B", "text": "Placeholder B"},
            {"label": "C", "text": "Placeholder C"},
            {"label": "D", "text": "Placeholder D"},
        ],
        "correctAnswer": "A",
        "educationalObjective": "[DRY-RUN placeholder]",
        "explanationSections": [
            {"heading": "Correct Answer Explanation", "body": ["[DRY-RUN placeholder]"]},
            {"heading": "Incorrect Answer Explanation", "body": ["[DRY-RUN placeholder]"]},
            {"heading": "Educational Objective",        "body": ["[DRY-RUN placeholder]"]},
        ],
        "tables": [],
        "sharedGroup": None,
        "extractionWarnings": ["dry-run: question not generated"],
    }


# ── Gemini API (raw HTTP — no SDK dependency, matches repo convention) ─────────
def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def load_prompt_template() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")
    return PROMPT_FILE.read_text(encoding="utf-8")


def _raw_gemini_call(api_key: str, prompt: str) -> str:
    """Single raw HTTP POST to Gemini generateContent. Never logs the key."""
    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 8192,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini HTTP {e.code}: {body_text[:400]}")

    candidates = raw.get("candidates", [])
    if not candidates:
        raise ValueError(f"Gemini returned no candidates: {json.dumps(raw)[:300]}")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError("Gemini returned empty parts in candidate")

    return parts[0].get("text", "")


def _build_repair_prompt(
    chunk_text: str,
    failed_questions: List[Dict],
    errors_per_q: List[List[str]],
) -> str:
    error_block = ""
    for i, (q, errs) in enumerate(zip(failed_questions, errors_per_q)):
        error_block += f"\nQuestion {i+1} (id={q.get('id','?')}) errors:\n"
        for e in errs:
            error_block += f"  - {e}\n"
        error_block += f"  Stem preview: {q.get('stem','')[:120]}\n"

    forbidden_list = ", ".join(f'"{s}"' for s in FORBIDDEN_STRINGS)
    return (
        "You are fixing invalid NBME-style questions. Fix ONLY the listed validation errors.\n"
        "Keep all valid fields unchanged. Return a JSON array of the corrected questions only.\n"
        "Raw JSON — no markdown fences, no extra text.\n\n"
        f"VALIDATION ERRORS TO FIX:\n{error_block}\n"
        f"ORIGINAL QUESTIONS JSON:\n{json.dumps(failed_questions, indent=2)}\n\n"
        f"ORIGINAL NOTES CONTEXT (first 2000 chars):\n{chunk_text[:2000]}\n\n"
        "Rules reminder:\n"
        "- Exactly 4 answerChoices labeled A, B, C, D\n"
        "- correctAnswer must be one of A/B/C/D and match a choice label\n"
        "- retrievalTag: hyperspecific, under 12 words\n"
        "- reviewPearl: one high-yield sentence\n"
        f"- Forbidden strings (must not appear): {forbidden_list}\n\n"
        "Return the fixed questions as a JSON array only."
    )


def call_gemini_with_retry(
    chunk_text: str,
    num_questions: int,
    chunk_index: int,
    stats: Dict,
) -> Tuple[List[Dict], List[str]]:
    """
    Call Gemini for one chunk, validate all returned questions.
    Retry invalid questions once with a repair prompt.
    Returns (questions, warnings). Always continues — never raises on partial failure.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set")

    template = load_prompt_template()
    prompt = (
        template
        .replace("{{NOTES_CHUNK}}", chunk_text)
        .replace("{{NUM_QUESTIONS}}", str(num_questions))
    )

    warnings: List[str] = []

    # ── Attempt 1 ─────────────────────────────────────────────────────────────
    raw_text = _raw_gemini_call(api_key, prompt)
    cleaned  = _strip_fences(raw_text)
    questions = json.loads(cleaned)
    if not isinstance(questions, list):
        raise ValueError(f"Gemini returned non-list JSON ({type(questions).__name__})")

    # ── Validate each question ─────────────────────────────────────────────────
    valid:        List[Dict]       = []
    need_repair:  List[Dict]       = []
    repair_errors: List[List[str]] = []

    for q in questions:
        errs = validate_question(q)
        if errs:
            need_repair.append(q)
            repair_errors.append(errs)
            stats["validationFailures"] += 1
        else:
            valid.append(q)

    if not need_repair:
        return valid, warnings

    # ── Attempt 2 — repair ────────────────────────────────────────────────────
    stats["retries"] += 1
    msg = f"Chunk {chunk_index}: {len(need_repair)} question(s) failed validation — retrying"
    warn(msg)
    warnings.append(msg)

    try:
        repair_prompt   = _build_repair_prompt(chunk_text, need_repair, repair_errors)
        repair_raw      = _raw_gemini_call(api_key, repair_prompt)
        repair_cleaned  = _strip_fences(repair_raw)
        repaired        = json.loads(repair_cleaned)
        if not isinstance(repaired, list):
            raise ValueError("Repair response is not a JSON array")

        for q in repaired:
            errs = validate_question(q)
            if errs:
                fail_msg = f"Chunk {chunk_index}: repair still invalid — {errs[:2]}"
                warn(fail_msg)
                warnings.append(fail_msg)
                stats["repairFailures"] += 1
                q.setdefault("extractionWarnings", []).extend(errs)
                valid.append(q)  # include with warnings rather than silently drop
            else:
                valid.append(q)
                stats["repairsSucceeded"] += 1

    except Exception as exc:
        fail_msg = f"Chunk {chunk_index}: repair call failed ({exc}) — {len(need_repair)} question(s) dropped"
        warn(fail_msg)
        warnings.append(fail_msg)
        stats["repairFailures"] += len(need_repair)

    return valid, warnings


# ── App-ready wrapper ──────────────────────────────────────────────────────────
def build_app_ready_json(
    source_stem: str,
    questions: List[Dict],
    warnings: List[str],
) -> Dict:
    return {
        "schemaVersion": "nbme-gemini-json-v3",
        "testTitle": source_stem,
        "sourceFormat": "uworld-notes",
        "expectedQuestionCount": None,
        "actualExtractedQuestionCount": len(questions),
        "extractionWarnings": warnings,
        "questions": questions,
    }


def renumber_questions(questions: List[Dict], offset: int) -> List[Dict]:
    for i, q in enumerate(questions):
        n = offset + i + 1
        q["id"] = f"q{str(n).zfill(3)}"
        q["questionNumber"] = n
        q["sourceQuestionNumber"] = n
    return questions


# ── Report ─────────────────────────────────────────────────────────────────────
def write_report(data: Dict, prefix: str = "question_generation_report") -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"{prefix}_{ts}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log(f"Report → {path.name}")
    return path


# ── Main pipeline ──────────────────────────────────────────────────────────────
def process_file(
    filepath: Path,
    questions_per_file: int,
    dry_run: bool,
    report_data: Dict,
) -> Optional[Dict]:
    t_start = time.time()
    log(f"Processing: {filepath.name}")
    stem = filepath.stem

    # 1. Extract raw text
    raw_text = extract_text(filepath)
    if not raw_text.strip():
        warn(f"No text extracted from {filepath.name} — skipping.")
        report_data["files"][filepath.name] = {"status": "skipped", "reason": "empty_text"}
        return None

    raw_path = RAW_DIR / f"{stem}_raw.txt"
    raw_path.write_text(raw_text, encoding="utf-8")
    log(f"  Raw text saved → {raw_path.name} ({len(raw_text):,} chars)")

    # 2. Chunk
    chunks = split_into_chunks(raw_text)
    chunk_path = CHUNK_DIR / f"{stem}_chunks.json"
    chunk_path.write_text(
        json.dumps({"sourceFile": filepath.name, "chunks": chunks}, indent=2),
        encoding="utf-8",
    )
    log(f"  {len(chunks)} chunk(s) → {chunk_path.name}")

    file_warnings: List[str] = []
    all_questions: List[Dict] = []
    chunk_stats:   List[Dict] = []

    gen_stats: Dict = {
        "validationFailures": 0,
        "retries":            0,
        "repairsSucceeded":   0,
        "repairFailures":     0,
    }

    # 3. Generate questions
    if dry_run:
        log(f"  [DRY-RUN] Generating {questions_per_file} placeholder questions.")
        all_questions = [_placeholder_question(i + 1) for i in range(questions_per_file)]
        file_warnings.append("dry-run: questions are placeholders, not Gemini-generated")
        chunk_stats = [{"chunk": 1, "status": "dry-run", "questions": questions_per_file}]

    else:
        questions_per_chunk = max(1, questions_per_file // max(len(chunks), 1))
        remainder   = questions_per_file - questions_per_chunk * len(chunks)
        q_offset    = 0
        raw_generated: List[Dict] = []

        for ci, chunk in enumerate(chunks):
            n = questions_per_chunk + (1 if ci < remainder else 0)
            if n == 0:
                chunk_stats.append({"chunk": ci + 1, "status": "skipped", "requested": 0})
                continue

            log(f"  Chunk {ci+1}/{len(chunks)} → requesting {n} question(s) from Gemini…")
            c_stat: Dict = {"chunk": ci + 1, "requested": n}

            try:
                qs, chunk_warnings = call_gemini_with_retry(
                    chunk["chunkText"], n, ci + 1, gen_stats
                )
                qs = renumber_questions(qs, q_offset)
                raw_generated.extend(qs)
                all_questions.extend(qs)
                file_warnings.extend(chunk_warnings)
                q_offset += len(qs)
                c_stat["status"]    = "ok"
                c_stat["generated"] = len(qs)
                log(f"    ✓ {len(qs)} question(s) generated")
                time.sleep(1)  # courtesy pause between chunks

            except json.JSONDecodeError as exc:
                msg = f"Chunk {ci+1} JSON parse error: {exc}"
                warn(msg)
                file_warnings.append(msg)
                c_stat["status"] = "json_error"
                c_stat["error"]  = str(exc)

            except Exception as exc:
                msg = f"Chunk {ci+1} failed: {exc}"
                warn(msg)
                file_warnings.append(msg)
                c_stat["status"] = "error"
                c_stat["error"]  = str(exc)

            chunk_stats.append(c_stat)

        # Duplicate stem check across all collected questions
        dup_warnings = check_duplicate_stems(all_questions)
        if dup_warnings:
            file_warnings.extend(dup_warnings)
            for w in dup_warnings:
                warn(w)

        # Write raw generated JSON
        gen_path = GEN_DIR / f"{stem}_generated.json"
        gen_path.write_text(json.dumps(raw_generated, indent=2), encoding="utf-8")
        log(f"  Generated JSON → {gen_path.name} ({len(raw_generated)} questions)")

    # 4. Build and write app-ready JSON
    app_json = build_app_ready_json(stem, all_questions, file_warnings)
    app_path = APP_DIR / f"{stem}_app_ready.json"
    app_path.write_text(json.dumps(app_json, indent=2), encoding="utf-8")
    log(f"  App-ready JSON → {app_path.name} ({len(all_questions)} questions)")

    elapsed = round(time.time() - t_start, 1)
    report_data["files"][filepath.name] = {
        "status":             "ok",
        "rawChars":           len(raw_text),
        "chunksProcessed":    len(chunks),
        "questionsGenerated": len(all_questions),
        "validationFailures": gen_stats["validationFailures"],
        "retries":            gen_stats["retries"],
        "repairsSucceeded":   gen_stats["repairsSucceeded"],
        "repairFailures":     gen_stats["repairFailures"],
        "validationWarnings": [
            w for w in file_warnings
            if any(kw in w.lower() for kw in ("invalid", "failed", "duplicate", "repair", "forbidden"))
        ],
        "warnings":     file_warnings,
        "chunkStats":   chunk_stats,
        "outputPaths": {
            "appReady":  str(app_path),
            "generated": str(GEN_DIR / f"{stem}_generated.json") if not dry_run else None,
            "chunks":    str(chunk_path),
            "rawText":   str(raw_path),
        },
        "elapsedSeconds": elapsed,
        "dryRun":         dry_run,
    }
    return app_json


def discover_input_files() -> List[Path]:
    if not INPUT_DIR.exists():
        return []
    return sorted(
        f for f in INPUT_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="UWorld Notes → Step 2 Question Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python3 generate_uworld_questions.py --dry-run
              python3 generate_uworld_questions.py --generate
              python3 generate_uworld_questions.py --generate --questions-per-file 15
              python3 generate_uworld_questions.py --generate --questions-per-file 8
              python3 generate_uworld_questions.py --generate --questions-per-file 20
        """),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Gemini calls; produce placeholder app-ready JSON only.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help=(
            "Explicitly run live Gemini generation. "
            "Exits with error if GEMINI_API_KEY is unset (does not silently fall back)."
        ),
    )
    parser.add_argument(
        "--questions-per-file",
        type=int,
        default=15,
        metavar="N",
        help="Target number of questions to generate per input file (default: 15).",
    )
    args = parser.parse_args()

    if args.dry_run and args.generate:
        parser.error("--dry-run and --generate are mutually exclusive.")

    log("=" * 60)
    log("UWorld Notes → Question Generator")
    log(f"  Model:              {GEMINI_MODEL}")
    log(f"  Dry-run:            {args.dry_run}")
    log(f"  Generate:           {args.generate}")
    log(f"  Questions per file: {args.questions_per_file}")
    log("=" * 60)

    for d in (RAW_DIR, CHUNK_DIR, GEN_DIR, APP_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    files = discover_input_files()
    if not files:
        log("No supported input files found in input_notes/")
        log(f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        write_report({"status": "no_input_files", "files": {}})
        return

    log(f"Found {len(files)} input file(s): {[f.name for f in files]}")

    # ── Resolve generation mode ────────────────────────────────────────────────
    dry_run = args.dry_run

    if args.generate:
        # Hard fail if key is absent — do not silently degrade
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            log("ERROR: --generate requires GEMINI_API_KEY to be set.")
            log("Set it with: export GEMINI_API_KEY=your_key_here")
            sys.exit(1)
        dry_run = False

    elif not dry_run:
        # Auto mode: generate if key available, fall back gracefully otherwise
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            warn("GEMINI_API_KEY is not set — falling back to --dry-run mode.")
            warn("Pass --generate to treat a missing key as a hard error.")
            dry_run = True

    report_data: Dict = {
        "runTimestamp":     datetime.now().isoformat(),
        "model":            GEMINI_MODEL,
        "dryRun":           dry_run,
        "questionsPerFile": args.questions_per_file,
        "inputFiles":       [f.name for f in files],
        "files":            {},
    }
    t_total = time.time()

    for filepath in files:
        try:
            process_file(filepath, args.questions_per_file, dry_run, report_data)
        except Exception as exc:
            warn(f"Fatal error processing {filepath.name}: {exc}")
            report_data["files"][filepath.name] = {"status": "error", "error": str(exc)}

    report_data["totalElapsedSeconds"] = round(time.time() - t_total, 1)
    write_report(report_data)
    log("Done.")


if __name__ == "__main__":
    main()
