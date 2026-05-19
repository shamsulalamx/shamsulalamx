#!/usr/bin/env python3
"""
UWorld Notes → Step 2 Question Generator
Pipeline: notes file → raw text → topic chunks → Gemini questions → canonical v3 JSON

Usage:
  python3 generate_uworld_questions.py [--dry-run] [--questions-per-file N]
"""

import argparse
import json
import os
import re
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# ── Optional imports (graceful degradation) ──────────────────────────────────
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    import striprtf.striprtf as _striprtf
    RTF_AVAILABLE = True
except ImportError:
    try:
        from striprtf.striprtf import rtf_to_text as _rtf_to_text
        RTF_AVAILABLE = True
    except ImportError:
        RTF_AVAILABLE = False

try:
    import docx as _docx
    DOCX_AVAILABLE = True
except ImportError:
    try:
        import docx2txt as _docx2txt
        DOCX_AVAILABLE = "docx2txt"
    except ImportError:
        DOCX_AVAILABLE = False

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
INPUT_DIR  = BASE_DIR / "input_notes"
RAW_DIR    = BASE_DIR / "output_json" / "raw_text"
CHUNK_DIR  = BASE_DIR / "output_json" / "chunks"
GEN_DIR    = BASE_DIR / "output_json" / "generated"
APP_DIR    = BASE_DIR / "output_json" / "app_ready"
REPORT_DIR = BASE_DIR / "reports"
PROMPT_FILE = BASE_DIR / "prompts" / "notes_to_questions_prompt.txt"
SCHEMA_FILE = BASE_DIR / "schema" / "uworld_generated_question_schema.json"

SUPPORTED_EXTENSIONS = {".txt", ".md", ".rtf", ".docx"}

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def warn(msg: str):
    print(f"[WARN] {msg}", file=sys.stderr)


# ── Text extraction ───────────────────────────────────────────────────────────
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
            from striprtf.striprtf import rtf_to_text
            return rtf_to_text(raw)
        except Exception as exc:
            warn(f"RTF extraction failed for {filepath.name}: {exc}")
            return ""

    if ext == ".docx":
        if not DOCX_AVAILABLE:
            warn(f"python-docx / docx2txt not installed; skipping {filepath.name}. Run: pip install python-docx")
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


# ── Chunking ──────────────────────────────────────────────────────────────────
_HEADING_RE = re.compile(
    r"^(?:#+ .+|[A-Z][A-Z\s\-/&]{4,}:|={3,}|-{3,}|\*{3,})\s*$",
    re.MULTILINE,
)

def split_into_chunks(text: str, max_chars: int = 3000) -> List[Dict]:
    """
    Split notes into topic chunks.
    Strategy:
      1. Try splitting on heading patterns (markdown # or ALL-CAPS labels).
      2. Fall back to paragraph-boundary splits.
      3. Hard-cap each chunk at max_chars characters (split on paragraph boundary).
    """
    # Pass 1: heading-based splits
    boundaries = [m.start() for m in _HEADING_RE.finditer(text)]
    if len(boundaries) >= 2:
        segments = []
        for i, start in enumerate(boundaries):
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
            segments.append(text[start:end].strip())
    else:
        # Fall back: split on blank lines
        segments = [s.strip() for s in re.split(r"\n{2,}", text) if s.strip()]

    # Pass 2: merge tiny segments and hard-cap large ones
    chunks = []
    buffer = ""
    for seg in segments:
        if len(buffer) + len(seg) + 2 <= max_chars:
            buffer = (buffer + "\n\n" + seg).strip() if buffer else seg
        else:
            if buffer:
                chunks.append(buffer)
            # seg itself may be huge — split it
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


# ── Dry-run placeholder generation ───────────────────────────────────────────
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
            {"heading": "Educational Objective", "body": ["[DRY-RUN placeholder]"]},
        ],
        "tables": [],
        "sharedGroup": None,
        "extractionWarnings": ["dry-run: question not generated"],
    }


def build_app_ready_json(
    source_stem: str,
    questions: List[Dict],
    warnings: List[str],
    dry_run: bool,
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


# ── Gemini generation ─────────────────────────────────────────────────────────
def load_prompt_template() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")
    return PROMPT_FILE.read_text(encoding="utf-8")


def call_gemini(chunk_text: str, num_questions: int, model_name: str = "gemini-1.5-flash") -> List[Dict]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY environment variable is not set.")
    if not GEMINI_AVAILABLE:
        raise ImportError("google-generativeai not installed. Run: pip install google-generativeai")

    genai.configure(api_key=api_key)
    template = load_prompt_template()
    prompt = template.replace("{{NOTES_CHUNK}}", chunk_text).replace(
        "{{NUM_QUESTIONS}}", str(num_questions)
    )

    model = genai.GenerativeModel(model_name)
    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.4,
            max_output_tokens=8192,
        ),
    )

    raw = response.text.strip()
    # Strip markdown fences if Gemini adds them despite instructions
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


def renumber_questions(questions: List[Dict], offset: int) -> List[Dict]:
    for i, q in enumerate(questions):
        n = offset + i + 1
        q["id"] = f"q{str(n).zfill(3)}"
        q["questionNumber"] = n
        q["sourceQuestionNumber"] = n
    return questions


# ── Report ────────────────────────────────────────────────────────────────────
def write_report(data: dict):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"generation_report_{ts}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    log(f"Report written → {path.name}")
    return path


# ── Main pipeline ─────────────────────────────────────────────────────────────
def process_file(
    filepath: Path,
    questions_per_file: int,
    dry_run: bool,
    report_data: Dict,
) -> Optional[Dict]:
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
    chunk_path.write_text(json.dumps({"sourceFile": filepath.name, "chunks": chunks}, indent=2), encoding="utf-8")
    log(f"  {len(chunks)} chunks saved → {chunk_path.name}")

    # 3. Generate (or placeholder)
    warnings: List[str] = []
    all_questions: List[Dict] = []

    if dry_run:
        log(f"  [DRY-RUN] Generating {questions_per_file} placeholder questions.")
        all_questions = [_placeholder_question(i + 1) for i in range(questions_per_file)]
        warnings.append("dry-run: questions are placeholders, not Gemini-generated")
    else:
        questions_per_chunk = max(1, questions_per_file // max(len(chunks), 1))
        remainder = questions_per_file - questions_per_chunk * len(chunks)
        q_offset = 0
        raw_generated: List[Dict] = []

        for ci, chunk in enumerate(chunks):
            n = questions_per_chunk + (1 if ci < remainder else 0)
            if n == 0:
                continue
            log(f"  Chunk {ci+1}/{len(chunks)} → requesting {n} questions from Gemini…")
            try:
                qs = call_gemini(chunk["chunkText"], n)
                qs = renumber_questions(qs, q_offset)
                raw_generated.extend(qs)
                all_questions.extend(qs)
                q_offset += len(qs)
                time.sleep(1)  # rate-limit courtesy pause
            except Exception as exc:
                msg = f"Gemini error on chunk {ci+1}: {exc}"
                warn(msg)
                warnings.append(msg)
                placeholders = renumber_questions(
                    [_placeholder_question(q_offset + i + 1) for i in range(n)], q_offset
                )
                all_questions.extend(placeholders)
                q_offset += n

        # Save raw generated JSON
        gen_path = GEN_DIR / f"{stem}_generated.json"
        gen_path.write_text(json.dumps(raw_generated, indent=2), encoding="utf-8")
        log(f"  Raw generated JSON → {gen_path.name}")

    # 4. Build app-ready JSON
    app_json = build_app_ready_json(stem, all_questions, warnings, dry_run)
    app_path = APP_DIR / f"{stem}_app_ready.json"
    app_path.write_text(json.dumps(app_json, indent=2), encoding="utf-8")
    log(f"  App-ready JSON → {app_path.name} ({len(all_questions)} questions)")

    report_data["files"][filepath.name] = {
        "status": "ok",
        "rawChars": len(raw_text),
        "chunks": len(chunks),
        "questionsGenerated": len(all_questions),
        "warnings": warnings,
        "dryRun": dry_run,
    }
    return app_json


def discover_input_files() -> List[Path]:
    if not INPUT_DIR.exists():
        return []
    files = sorted(
        f for f in INPUT_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    return files


def main():
    parser = argparse.ArgumentParser(
        description="UWorld Notes → Step 2 Question Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python3 generate_uworld_questions.py --dry-run
              python3 generate_uworld_questions.py --questions-per-file 10
              python3 generate_uworld_questions.py --questions-per-file 15
        """),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Gemini calls; produce placeholder app-ready JSON only.",
    )
    parser.add_argument(
        "--questions-per-file",
        type=int,
        default=15,
        metavar="N",
        help="Target number of questions to generate per input file (default: 15).",
    )
    args = parser.parse_args()

    log("=" * 60)
    log("UWorld Notes → Question Generator")
    log(f"  Dry-run: {args.dry_run}")
    log(f"  Questions per file: {args.questions_per_file}")
    log("=" * 60)

    # Ensure output dirs exist
    for d in (RAW_DIR, CHUNK_DIR, GEN_DIR, APP_DIR, REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    files = discover_input_files()
    if not files:
        log("No supported input files found in input_notes/")
        log(f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        write_report({"status": "no_input_files", "files": {}})
        return

    log(f"Found {len(files)} input file(s): {[f.name for f in files]}")

    if not args.dry_run:
        if not GEMINI_AVAILABLE:
            warn("google-generativeai is not installed. Run: pip install google-generativeai")
            warn("Falling back to --dry-run mode.")
            args.dry_run = True
        elif not os.environ.get("GEMINI_API_KEY", "").strip():
            warn("GEMINI_API_KEY is not set. Falling back to --dry-run mode.")
            args.dry_run = True

    report_data: Dict = {
        "runTimestamp": datetime.now().isoformat(),
        "dryRun": args.dry_run,
        "questionsPerFile": args.questions_per_file,
        "inputFiles": [f.name for f in files],
        "files": {},
    }

    for filepath in files:
        try:
            process_file(filepath, args.questions_per_file, args.dry_run, report_data)
        except Exception as exc:
            warn(f"Fatal error processing {filepath.name}: {exc}")
            report_data["files"][filepath.name] = {"status": "error", "error": str(exc)}

    write_report(report_data)
    log("Done.")


if __name__ == "__main__":
    main()
