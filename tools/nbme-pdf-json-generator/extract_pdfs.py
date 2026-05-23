#!/usr/bin/env python3
"""
NBME PDF → JSON Generator

Milestone 1: PDF → raw text extraction (pdfplumber)
Milestone 2: raw text → question chunks (deterministic, no AI)
Milestone 3: chunks → normalized scaffold (dry-run placeholder, no LLM)
Milestone 4: chunks → Gemini → validated normalized JSON
Milestone 4.5: OCR fallback for image-based / scanned PDFs

Usage:
  python3 extract_pdfs.py                      # full pipeline: extract + chunk
  python3 extract_pdfs.py --force-ocr          # force OCR on every page (requires pymupdf + tesseract)
  python3 extract_pdfs.py --chunk-only         # re-chunk existing raw_text files
  python3 extract_pdfs.py --normalize-dry-run  # placeholder normalized JSON (no LLM)
  python3 extract_pdfs.py --normalize-gemini   # Gemini-powered normalization
                                               # requires: export GEMINI_API_KEY=...

OCR dependencies (optional — needed for image-based PDFs):
  pip3 install pymupdf pytesseract
  brew install tesseract
"""

import argparse
import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber is not installed.")
    print("Run:  pip3 install pdfplumber")
    sys.exit(1)

# Optional OCR dependencies (M4.5) — graceful degradation if absent
try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    import pytesseract
    from PIL import Image as _PILImage
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR     = Path(__file__).parent.resolve()
INPUT_DIR      = SCRIPT_DIR / "input_pdfs"
OUTPUT_DIR     = SCRIPT_DIR / "output_json"
RAW_TEXT_DIR   = OUTPUT_DIR / "raw_text"
CHUNKS_DIR     = OUTPUT_DIR / "chunks"
NORMALIZED_DIR = OUTPUT_DIR / "normalized"
REPORTS_DIR    = SCRIPT_DIR / "reports"
PROMPTS_DIR    = SCRIPT_DIR / "prompts"
SCHEMA_DIR     = SCRIPT_DIR / "schema"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTAMINATION_PHRASES = [
    "Here are the extracted questions",
    "eftab720",
    "tightenfactor0",
]

# Additional phrases forbidden in LLM output fields
FORBIDDEN_OUTPUT_PHRASES = CONTAMINATION_PHRASES + [
    "Below is the JSON",
    "```json",
    "```",
]

MIN_SEGMENT_CHARS = 80

# OCR heuristics (M4.5)
OCR_MIN_USEFUL_CHARS = 50   # page text shorter than this → candidate for OCR
OCR_DPI              = 200  # render DPI for pytesseract

# Lines that look like watermarks, page numbers, or URL-only content
_OCR_NOISE_LINE_RE = re.compile(
    r'^[\s\d]+$'           # purely numeric / whitespace
    r'|https?://\S+'       # http/https URLs
    r'|t\.me/\S+'          # Telegram links
    r'|www\.\S+'           # www links
    r'|^\s*[-|]+\s*$',     # divider lines
    re.IGNORECASE,
)

GEMINI_MODEL    = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

INTER_CALL_DELAY = 0.5   # seconds between Gemini API calls
MAX_ATTEMPTS     = 2     # initial attempt + 1 repair

NORMALIZED_SCHEMA_VERSION = "nbme-normalized-question-v1"
REQUIRED_NORMALIZED_FIELDS = [
    "schemaVersion", "sourceFile", "sourceQuestionNumber", "questionId",
    "stem", "choices", "correctAnswer", "educationalObjective",
    "correctExplanation", "incorrectExplanations", "reviewPearl",
    "retrievalTag", "tags", "figures", "tables", "warnings", "confidence",
]

# Answer choice lines: "A. text", "A) text", "(A) text"  (A–F)
ANSWER_CHOICE_RE = re.compile(
    r'^\s*(?:\()?[A-Fa-f][.)]\s+\S',
    re.MULTILINE,
)

# Explanation-like content
EXPLANATION_RE = re.compile(
    r'\b(?:correct|incorrect|explanation|because|therefore|'
    r'this patient|the answer|educational objective)\b',
    re.IGNORECASE,
)

# Question boundary detection
_Q_BOUNDARY_RE = re.compile(
    r'^(?:'
    r'(?:Question|Item)\s+(\d+)[.):\s]'
    r'|\*\s*(\d+)[.)]\s'   # NBME interface prefix: "* 1. "
    r'|(\d+)[.)]\s'
    r')',
    re.MULTILINE | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def ensure_dirs():
    for d in (INPUT_DIR, OUTPUT_DIR, RAW_TEXT_DIR, CHUNKS_DIR,
              NORMALIZED_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _save_report(report: dict):
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"extraction_report_{ts}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report saved to: {path.relative_to(SCRIPT_DIR)}\n")


# ---------------------------------------------------------------------------
# Milestone 4.5: OCR helpers
# ---------------------------------------------------------------------------

def _page_needs_ocr(text: str) -> bool:
    """Return True if pdfplumber text looks like watermark/header only, not real content."""
    stripped = text.strip()
    if len(stripped) < OCR_MIN_USEFUL_CHARS:
        return True
    lines = [l.strip() for l in stripped.splitlines() if l.strip()]
    if not lines:
        return True
    noise = sum(1 for l in lines if _OCR_NOISE_LINE_RE.search(l))
    return (noise / len(lines)) > 0.6


def _ocr_pdf_page(pdf_path: Path, page_index: int, dpi: int = OCR_DPI) -> str:
    """Render one PDF page to a greyscale image and return OCR text."""
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_index]
        mat  = fitz.Matrix(dpi / 72, dpi / 72)
        pix  = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img  = _PILImage.frombytes("L", [pix.width, pix.height], pix.samples)
        return pytesseract.image_to_string(img)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Milestone 1: PDF → raw text
# ---------------------------------------------------------------------------

def extract_pdf(pdf_path: Path, force_ocr: bool = False) -> dict:
    result = {
        "filename":     pdf_path.name,
        "page_count":   0,
        "status":       "ok",
        "warnings":     [],
        "output_path":  None,
        "char_count":   0,
        "ocr_pages":    0,
        "failed_pages": 0,
        "page_methods": [],  # per-page: "text" | "ocr" | "text+ocr" | "failed"
    }

    if force_ocr and not (HAS_FITZ and HAS_TESSERACT):
        missing = []
        if not HAS_FITZ:
            missing.append("pymupdf  →  pip3 install pymupdf")
        if not HAS_TESSERACT:
            missing.append("pytesseract  →  pip3 install pytesseract  &&  brew install tesseract")
        result["status"] = "error"
        result["warnings"].append("--force-ocr requires: " + "  |  ".join(missing))
        return result

    _ocr_dep_warned = False

    try:
        with pdfplumber.open(pdf_path) as pdf:
            result["page_count"] = len(pdf.pages)
            if result["page_count"] == 0:
                result["status"] = "warning"
                result["warnings"].append("PDF has 0 pages")
                return result

            pages_text = []
            for i, page in enumerate(pdf.pages, start=1):
                page_idx = i - 1

                try:
                    plumber_text = page.extract_text() or ""
                except Exception as e:
                    result["warnings"].append(f"Page {i}: pdfplumber error — {e}")
                    plumber_text = ""

                should_ocr = force_ocr or _page_needs_ocr(plumber_text)

                if should_ocr and HAS_FITZ and HAS_TESSERACT:
                    try:
                        ocr_text = _ocr_pdf_page(pdf_path, page_idx)
                        result["ocr_pages"] += 1
                        # text+ocr: force_ocr AND pdfplumber had real content
                        if force_ocr and plumber_text.strip() and not _page_needs_ocr(plumber_text):
                            pages_text.append(plumber_text.rstrip() + "\n\n" + ocr_text.strip())
                            result["page_methods"].append("text+ocr")
                        else:
                            pages_text.append(ocr_text)
                            result["page_methods"].append("ocr")
                    except Exception as e:
                        result["warnings"].append(f"Page {i}: OCR failed — {e}")
                        pages_text.append(plumber_text)
                        if plumber_text.strip():
                            result["page_methods"].append("text")
                        else:
                            result["page_methods"].append("failed")
                            result["failed_pages"] += 1

                elif should_ocr and not (HAS_FITZ and HAS_TESSERACT):
                    if not _ocr_dep_warned:
                        _ocr_dep_warned = True
                        hints = []
                        if not HAS_FITZ:
                            hints.append("pymupdf  →  pip3 install pymupdf")
                        if not HAS_TESSERACT:
                            hints.append("pytesseract  →  pip3 install pytesseract  &&  brew install tesseract")
                        result["warnings"].append(
                            "Some pages need OCR but dependencies are missing — "
                            "watermark/image pages will be empty.  Install: " + "  |  ".join(hints)
                        )
                    pages_text.append(plumber_text)
                    if plumber_text.strip():
                        result["page_methods"].append("text")
                    else:
                        result["warnings"].append(
                            f"Page {i}: no extractable text (may be image-only)"
                        )
                        result["page_methods"].append("failed")
                        result["failed_pages"] += 1

                else:
                    pages_text.append(plumber_text)
                    if plumber_text.strip():
                        result["page_methods"].append("text")
                    else:
                        result["warnings"].append(
                            f"Page {i}: no extractable text (may be image-only)"
                        )
                        result["page_methods"].append("failed")
                        result["failed_pages"] += 1

    except Exception as e:
        result["status"] = "error"
        result["warnings"].append(f"Could not open PDF: {e}")
        result["warnings"].append(traceback.format_exc())
        return result

    sections = [f"## Page {i}\n\n{t.strip()}" for i, t in enumerate(pages_text, 1)]
    full_text = "\n\n---\n\n".join(sections)
    result["char_count"] = len(full_text)

    if result["char_count"] == 0:
        result["status"] = "warning"
        result["warnings"].append("Total extracted text is empty — PDF may be fully image-based")

    out_path = RAW_TEXT_DIR / f"{pdf_path.stem}_raw.txt"
    try:
        out_path.write_text(full_text, encoding="utf-8")
        result["output_path"] = str(out_path.relative_to(SCRIPT_DIR))
    except Exception as e:
        result["status"] = "warning"
        result["warnings"].append(f"Could not write raw text file: {e}")

    if result["status"] == "ok" and result["warnings"]:
        result["status"] = "warning"

    return result


# ---------------------------------------------------------------------------
# Milestone 2: raw text → question chunks
# ---------------------------------------------------------------------------

def _strip_page_markers(text: str) -> str:
    text = re.sub(r'^## Page \d+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^---\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _parse_q_number(m: re.Match) -> int:
    return int(next(g for g in m.groups() if g is not None))


def _chunk_confidence(raw_text: str) -> str:
    has_choices = bool(ANSWER_CHOICE_RE.search(raw_text))
    long_enough = len(raw_text.strip()) >= MIN_SEGMENT_CHARS
    if has_choices and long_enough:
        return "high"
    if has_choices or long_enough:
        return "medium"
    return "low"


def chunk_raw_text(raw_path: Path) -> dict:
    stem = raw_path.stem
    if stem.endswith("_raw"):
        stem = stem[:-4]

    result = {
        "status":                "ok",
        "warnings":              [],
        "chunkCount":            0,
        "char_count":            0,
        "_per_chunk_warn_total": 0,
        "output_path":           None,
    }

    try:
        raw = raw_path.read_text(encoding="utf-8")
    except Exception as e:
        result["status"] = "error"
        result["warnings"].append(f"Could not read file: {e}")
        return result

    result["char_count"] = len(raw)

    for phrase in CONTAMINATION_PHRASES:
        if phrase.lower() in raw.lower():
            result["warnings"].append(f"Contamination phrase detected in full text: '{phrase}'")

    text = _strip_page_markers(raw)
    matches = list(_Q_BOUNDARY_RE.finditer(text))

    if not matches:
        result["status"] = "warning"
        result["warnings"].append("No question boundaries found — cannot chunk")
        _write_chunks(stem, raw_path.name, [], result)
        return result

    preamble = text[: matches[0].start()].strip()
    if preamble:
        preview = preamble[:100].replace("\n", " ")
        result["warnings"].append(
            f"Skipped {len(preamble)} chars before first question: \"{preview}\""
        )

    chunks = []
    seen_numbers: dict[int, int] = {}

    for idx, m in enumerate(matches):
        q_num        = _parse_q_number(m)
        start_marker = m.group(0).rstrip()
        end_idx      = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        end_marker   = matches[idx + 1].group(0).rstrip() if idx + 1 < len(matches) else "EOF"
        raw_chunk    = text[m.start() : end_idx].strip()

        cw = []
        if q_num in seen_numbers:
            cw.append(f"Duplicate question number {q_num} (also at chunk index {seen_numbers[q_num]})")
        seen_numbers[q_num] = idx

        if len(raw_chunk) < MIN_SEGMENT_CHARS:
            cw.append(f"Unusually short chunk ({len(raw_chunk)} chars)")
        if not ANSWER_CHOICE_RE.search(raw_chunk):
            cw.append("No answer choices detected (A/B/C/D/E pattern absent)")
        if not EXPLANATION_RE.search(raw_chunk):
            cw.append("No explanation-like content detected")
        for phrase in CONTAMINATION_PHRASES:
            if phrase.lower() in raw_chunk.lower():
                cw.append(f"Contamination phrase in chunk: '{phrase}'")

        chunks.append({
            "chunkId":        f"q{q_num:03d}",
            "questionNumber": q_num,
            "rawText":        raw_chunk,
            "startMarker":    start_marker,
            "endMarker":      end_marker,
            "confidence":     _chunk_confidence(raw_chunk),
            "warnings":       cw,
        })

    if chunks:
        nums    = [c["questionNumber"] for c in chunks]
        missing = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
        if missing:
            result["warnings"].append(f"Missing question numbers in sequence: {missing}")

    result["chunkCount"]            = len(chunks)
    result["_per_chunk_warn_total"] = sum(len(c["warnings"]) for c in chunks)

    if result["status"] == "ok" and result["warnings"]:
        result["status"] = "warning"

    _write_chunks(stem, raw_path.name, chunks, result)
    return result


def _write_chunks(stem: str, source_name: str, chunks: list, result: dict):
    out_path = CHUNKS_DIR / f"{stem}_chunks.json"
    payload = {
        "schemaVersion": "nbme-chunk-v1",
        "sourceFile":    source_name,
        "createdAt":     datetime.utcnow().isoformat() + "Z",
        "chunkCount":    len(chunks),
        "fileWarnings":  result.get("warnings", []),
        "chunks":        chunks,
    }
    try:
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        result["output_path"] = str(out_path.relative_to(SCRIPT_DIR))
    except Exception as e:
        result["status"] = "warning"
        result["warnings"].append(f"Could not write chunk file: {e}")


def _total_chunk_warnings(cr: dict) -> int:
    return len(cr.get("warnings", [])) + cr.get("_per_chunk_warn_total", 0)


# ---------------------------------------------------------------------------
# Milestone 3: chunks → normalized scaffold (dry-run, no LLM)
# ---------------------------------------------------------------------------

_DRY_RUN_WARNING = "normalize dry run only; LLM not called"


def normalize_dry_run(chunk_path: Path) -> dict:
    stem = chunk_path.stem
    if stem.endswith("_chunks"):
        stem = stem[:-7]

    result = {
        "status":          "ok",
        "warnings":        [],
        "normalizedCount": 0,
        "failedCount":     0,
        "output_path":     None,
    }

    try:
        payload = json.loads(chunk_path.read_text(encoding="utf-8"))
    except Exception as e:
        result["status"] = "error"
        result["warnings"].append(f"Could not read chunk file: {e}")
        return result

    chunks      = payload.get("chunks", [])
    source_file = payload.get("sourceFile", chunk_path.name)

    if not chunks:
        result["status"] = "warning"
        result["warnings"].append("Chunk file contains 0 chunks — nothing to normalize")

    for w in payload.get("fileWarnings", []):
        if any(p.lower() in w.lower() for p in CONTAMINATION_PHRASES):
            result["warnings"].append(f"Contamination flagged by chunker: {w}")

    questions = []
    for chunk in chunks:
        q_num    = chunk.get("questionNumber", 0)
        chunk_id = chunk.get("chunkId", f"q{q_num:03d}")
        raw_text = chunk.get("rawText", "")

        inherited = [f"[from chunker] {w}" for w in chunk.get("warnings", [])]
        if any(p.lower() in raw_text.lower() for p in CONTAMINATION_PHRASES):
            inherited.append("Contamination phrase detected in chunk rawText")

        questions.append({
            "schemaVersion":         NORMALIZED_SCHEMA_VERSION,
            "sourceFile":            source_file,
            "sourceQuestionNumber":  q_num,
            "questionId":            chunk_id,
            "stem":                  "",
            "choices":               [],
            "correctAnswer":         "",
            "educationalObjective":  "",
            "correctExplanation":    "",
            "incorrectExplanations": [],
            "reviewPearl":           "",
            "retrievalTag":          "",
            "tags":                  [],
            "figures":               [],
            "tables":                [],
            "warnings":              [_DRY_RUN_WARNING] + inherited,
            "confidence":            "low",
        })

    result["normalizedCount"] = len(questions)
    if result["status"] == "ok" and result["warnings"]:
        result["status"] = "warning"

    out_path = NORMALIZED_DIR / f"{stem}_normalized.json"
    normalized_payload = {
        "schemaVersion":     "nbme-normalized-file-v1",
        "sourceChunkFile":   chunk_path.name,
        "createdAt":         datetime.utcnow().isoformat() + "Z",
        "isDryRun":          True,
        "normalizationMode": "dry-run",
        "questionCount":     len(questions),
        "failedCount":       0,
        "fileWarnings":      result["warnings"],
        "questions":         questions,
        "failures":          [],
    }
    try:
        out_path.write_text(
            json.dumps(normalized_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        result["output_path"] = str(out_path.relative_to(SCRIPT_DIR))
    except Exception as e:
        result["status"] = "warning"
        result["warnings"].append(f"Could not write normalized file: {e}")

    return result


# ---------------------------------------------------------------------------
# Milestone 4: chunks → Gemini → validated normalized JSON
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    """Read GEMINI_API_KEY from environment. Never prints or logs the key."""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("\nERROR: GEMINI_API_KEY environment variable is not set.")
        print("  export GEMINI_API_KEY='your-key-here'")
        print("  Then re-run:  python3 extract_pdfs.py --normalize-gemini\n")
        sys.exit(1)
    return key


def _load_prompt_template() -> str:
    path = PROMPTS_DIR / "chunk_to_normalized_question_prompt.txt"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Prompt template not found: {path}\n"
            "Expected at: prompts/chunk_to_normalized_question_prompt.txt"
        )


def _load_schema_text() -> str:
    path = SCHEMA_DIR / "normalized_question_schema.json"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Schema not found: {path}\n"
            "Expected at: schema/normalized_question_schema.json"
        )


def _build_gemini_prompt(
    template: str, schema_text: str, chunk: dict, source_file: str
) -> str:
    """Fill the prompt template with schema + chunk data."""
    # Inject the schema into the SCHEMA section of the prompt
    schema_block = (
        "\nThe JSON Schema for validation is:\n"
        + schema_text
        + "\n\nOutput exactly this shape:\n"
    )
    filled = template.replace("Output exactly this shape:\n", schema_block)

    filled = filled.replace("{{SOURCE_FILE}}", source_file)
    filled = filled.replace("{{QUESTION_NUMBER}}", str(chunk["questionNumber"]))
    filled = filled.replace("{{QUESTION_ID}}", chunk["chunkId"])
    filled = filled.replace("{{RAW_CHUNK_TEXT}}", chunk["rawText"])
    return filled


def _build_repair_prompt(
    schema_text: str, chunk: dict, source_file: str,
    errors: list[str], raw_preview: str
) -> str:
    """Build a repair prompt that includes validation errors from attempt 1."""
    errors_block = "\n".join(f"  - {e}" for e in errors)
    return (
        "The following normalized question JSON failed validation.\n\n"
        f"VALIDATION ERRORS:\n{errors_block}\n\n"
        f"PREVIOUS RESPONSE (first 400 chars):\n{raw_preview[:400]}\n\n"
        "Fix all validation errors. Output JSON only — no markdown, no commentary.\n\n"
        "The JSON Schema is:\n"
        + schema_text
        + "\n\n---CHUNK META---\n"
        f"sourceFile: {source_file}\n"
        f"sourceQuestionNumber: {chunk['questionNumber']}\n"
        f"questionId: {chunk['chunkId']}\n\n"
        "---CHUNK START---\n"
        + chunk["rawText"]
    )


def _call_gemini_api(api_key: str, prompt: str) -> str:
    """
    Call Gemini generateContent and return the raw text response.
    Uses urllib.request (stdlib). Never logs the API key.
    Raises urllib.error.HTTPError or ValueError on failure.
    """
    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={api_key}"
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 8192,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini HTTP {e.code}: {body_text[:300]}")

    candidates = raw.get("candidates", [])
    if not candidates:
        raise ValueError(f"Gemini returned no candidates. Response: {str(raw)[:300]}")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError("Gemini candidate has no content parts.")

    return parts[0].get("text", "")


def _strip_llm_fences(text: str) -> str:
    """Remove markdown code fences that the model may add despite instructions."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*```\s*$', '', text)
    return text.strip()


def _validate_normalized_question(q: dict) -> list[str]:
    """
    Validate one normalized question object.
    Returns a list of error strings (empty list = valid).
    """
    errors = []

    # Required fields present
    for field in REQUIRED_NORMALIZED_FIELDS:
        if field not in q:
            errors.append(f"Missing required field: '{field}'")

    if errors:
        return errors  # can't validate further without the fields

    # schemaVersion
    if q.get("schemaVersion") != NORMALIZED_SCHEMA_VERSION:
        errors.append(
            f"schemaVersion must be '{NORMALIZED_SCHEMA_VERSION}', "
            f"got '{q.get('schemaVersion')}'"
        )

    # sourceQuestionNumber
    if not isinstance(q.get("sourceQuestionNumber"), int):
        errors.append("sourceQuestionNumber must be an integer")

    # choices
    choices = q.get("choices", [])
    if not isinstance(choices, list):
        errors.append("choices must be an array")
    else:
        for i, c in enumerate(choices):
            if not isinstance(c, dict):
                errors.append(f"choices[{i}] must be an object")
                continue
            if "label" not in c:
                errors.append(f"choices[{i}] missing 'label'")
            if "text" not in c:
                errors.append(f"choices[{i}] missing 'text'")
            if "label" in c and not re.match(r'^[A-F]$', str(c["label"])):
                errors.append(f"choices[{i}].label must be A–F, got '{c['label']}'")

    # correctAnswer
    ca = q.get("correctAnswer", "")
    if not isinstance(ca, str):
        errors.append("correctAnswer must be a string")
    elif ca != "" and not re.match(r'^[A-F]$', ca):
        errors.append(f"correctAnswer must be a single letter A–F or empty, got '{ca}'")

    # confidence
    if q.get("confidence") not in ("high", "medium", "low"):
        errors.append(f"confidence must be high/medium/low, got '{q.get('confidence')}'")

    # Array fields
    for field in ("warnings", "tags", "figures", "tables", "incorrectExplanations"):
        if not isinstance(q.get(field), list):
            errors.append(f"'{field}' must be an array")

    # incorrectExplanations entries
    ie = q.get("incorrectExplanations", [])
    if isinstance(ie, list):
        for i, entry in enumerate(ie):
            if not isinstance(entry, dict):
                errors.append(f"incorrectExplanations[{i}] must be an object")
                continue
            if "label" not in entry:
                errors.append(f"incorrectExplanations[{i}] missing 'label'")
            if "explanation" not in entry:
                errors.append(f"incorrectExplanations[{i}] missing 'explanation'")

    # Forbidden output phrases in text fields
    text_fields = {
        "stem":                  q.get("stem", ""),
        "correctExplanation":    q.get("correctExplanation", ""),
        "educationalObjective":  q.get("educationalObjective", ""),
        "reviewPearl":           q.get("reviewPearl", ""),
        "retrievalTag":          q.get("retrievalTag", ""),
    }
    for tag_str in q.get("tags", []):
        text_fields[f"tags[{tag_str[:30]}]"] = str(tag_str)
    for ie_entry in (q.get("incorrectExplanations") or []):
        if isinstance(ie_entry, dict):
            lbl = ie_entry.get("label", "?")
            text_fields[f"incorrectExplanations[{lbl}].explanation"] = (
                ie_entry.get("explanation", "")
            )

    for fname, fval in text_fields.items():
        for phrase in FORBIDDEN_OUTPUT_PHRASES:
            if phrase.lower() in str(fval).lower():
                errors.append(
                    f"Forbidden phrase '{phrase}' found in field '{fname}'"
                )

    return errors


def normalize_gemini_chunk_file(chunk_path: Path, api_key: str) -> dict:
    """
    Process one _chunks.json file: call Gemini for each chunk,
    validate, retry once on failure, write _normalized.json.
    Returns a result dict summarising the outcome.
    """
    stem = chunk_path.stem
    if stem.endswith("_chunks"):
        stem = stem[:-7]

    result = {
        "status":               "ok",
        "warnings":             [],
        "normalizedCount":      0,
        "failedCount":          0,
        "validationErrorCount": 0,
        "output_path":          None,
    }

    try:
        payload  = json.loads(chunk_path.read_text(encoding="utf-8"))
    except Exception as e:
        result["status"] = "error"
        result["warnings"].append(f"Could not read chunk file: {e}")
        return result

    chunks      = payload.get("chunks", [])
    source_file = payload.get("sourceFile", chunk_path.name)

    if not chunks:
        result["status"] = "warning"
        result["warnings"].append("Chunk file contains 0 chunks — nothing to normalize")
        _write_normalized_gemini(stem, source_file, chunk_path.name, [], [], result)
        return result

    try:
        template    = _load_prompt_template()
        schema_text = _load_schema_text()
    except FileNotFoundError as e:
        result["status"] = "error"
        result["warnings"].append(str(e))
        return result

    items    = []
    failures = []
    total    = len(chunks)

    for i, chunk in enumerate(chunks, start=1):
        chunk_id = chunk.get("chunkId", "?")
        print(f"    [{i}/{total}] chunk {chunk_id} ...", end=" ", flush=True)

        last_error       = None
        last_raw_preview = ""
        success          = False

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                if attempt == 1:
                    prompt = _build_gemini_prompt(template, schema_text, chunk, source_file)
                else:
                    prompt = _build_repair_prompt(
                        schema_text, chunk, source_file,
                        last_error, last_raw_preview
                    )

                raw_text = _call_gemini_api(api_key, prompt)
                cleaned  = _strip_llm_fences(raw_text)

                try:
                    q_obj = json.loads(cleaned)
                except json.JSONDecodeError as je:
                    last_error       = [f"JSON parse error: {je}"]
                    last_raw_preview = raw_text[:400]
                    if attempt < MAX_ATTEMPTS:
                        time.sleep(INTER_CALL_DELAY)
                    continue

                val_errors = _validate_normalized_question(q_obj)
                if val_errors:
                    result["validationErrorCount"] += len(val_errors)
                    last_error       = val_errors
                    last_raw_preview = raw_text[:400]
                    if attempt < MAX_ATTEMPTS:
                        print(f"[RETRY] {len(val_errors)} validation errors ...", end=" ", flush=True)
                        time.sleep(INTER_CALL_DELAY)
                    continue

                # Valid
                items.append(q_obj)
                success = True
                print("[OK]")
                break

            except Exception as exc:
                last_error       = [f"API error on attempt {attempt}: {exc}"]
                last_raw_preview = ""
                if attempt < MAX_ATTEMPTS:
                    print(f"[RETRY] {exc} ...", end=" ", flush=True)
                    time.sleep(INTER_CALL_DELAY)

        if not success:
            error_msg = "; ".join(last_error) if isinstance(last_error, list) else str(last_error)
            print(f"[FAIL] {error_msg[:80]}")
            failures.append({
                "chunkId":          chunk_id,
                "questionNumber":   chunk.get("questionNumber", 0),
                "error":            error_msg,
                "rawResponsePreview": last_raw_preview[:300],
                "attempts":         MAX_ATTEMPTS,
            })

        time.sleep(INTER_CALL_DELAY)

    result["normalizedCount"] = len(items)
    result["failedCount"]     = len(failures)

    if failures:
        result["status"] = "warning"
        result["warnings"].append(
            f"{len(failures)} chunk(s) failed normalization after {MAX_ATTEMPTS} attempts"
        )
    elif result["status"] == "ok" and result["warnings"]:
        result["status"] = "warning"

    _write_normalized_gemini(stem, source_file, chunk_path.name, items, failures, result)
    return result


def _write_normalized_gemini(
    stem: str, source_file: str, chunk_file_name: str,
    items: list, failures: list, result: dict
):
    out_path = NORMALIZED_DIR / f"{stem}_normalized.json"
    payload  = {
        "schemaVersion":     "normalized-question-batch-v1",
        "sourceFile":        source_file,
        "sourceChunkFile":   chunk_file_name,
        "createdAt":         datetime.utcnow().isoformat() + "Z",
        "normalizationMode": "gemini",
        "normalizedCount":   len(items),
        "failedCount":       len(failures),
        "items":             items,
        "failures":          failures,
    }
    try:
        out_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        result["output_path"] = str(out_path.relative_to(SCRIPT_DIR))
    except Exception as e:
        result["status"] = "warning"
        result["warnings"].append(f"Could not write normalized file: {e}")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(records: list, elapsed: float, mode: str) -> dict:
    def cnt(field, val):
        return sum(1 for r in records if r.get(field) == val)

    return {
        "schemaVersion":       "nbme-pdf-extractor-report-v4",
        "generatedAt":         datetime.utcnow().isoformat() + "Z",
        "elapsedSeconds":      round(elapsed, 2),
        "mode":                mode,
        "inputDirectory":      str(INPUT_DIR.relative_to(SCRIPT_DIR)),
        "rawTextDirectory":    str(RAW_TEXT_DIR.relative_to(SCRIPT_DIR)),
        "chunksDirectory":     str(CHUNKS_DIR.relative_to(SCRIPT_DIR)),
        "normalizedDirectory": str(NORMALIZED_DIR.relative_to(SCRIPT_DIR)),
        "summary": {
            "total":                 len(records),
            "extractionOk":          cnt("extraction_status", "ok"),
            "extractionWarning":     cnt("extraction_status", "warning"),
            "extractionError":       cnt("extraction_status", "error"),
            "extractionSkipped":     cnt("extraction_status", "skipped"),
            "chunkingOk":            cnt("chunking_status", "ok"),
            "chunkingWarning":       cnt("chunking_status", "warning"),
            "chunkingError":         cnt("chunking_status", "error"),
            "chunkingSkipped":       cnt("chunking_status", "skipped"),
            "totalChunks":           sum(r.get("chunk_count", 0) for r in records),
            "totalChunkWarnings":    sum(r.get("chunk_warning_count", 0) for r in records),
            "normalizationOk":       cnt("normalization_status", "ok"),
            "normalizationWarning":  cnt("normalization_status", "warning"),
            "normalizationError":    cnt("normalization_status", "error"),
            "normalizationSkipped":  cnt("normalization_status", "skipped"),
            "totalNormalized":       sum(r.get("normalized_count", 0) for r in records),
            "totalFailed":           sum(r.get("failed_count", 0) for r in records),
            "totalValidationErrors": sum(r.get("validation_error_count", 0) for r in records),
            "totalOcrPages":         sum(r.get("ocr_pages", 0) for r in records),
            "totalFailedPages":      sum(r.get("failed_pages", 0) for r in records),
        },
        "files": [
            {
                "filename":              r["filename"],
                "pageCount":             r.get("page_count", 0),
                "extractionStatus":      r.get("extraction_status", "skipped"),
                "extractionWarnings":    r.get("extraction_warnings", []),
                "charCount":             r.get("char_count", 0),
                "ocrPages":              r.get("ocr_pages", 0),
                "failedPages":           r.get("failed_pages", 0),
                "pageMethodCounts":      r.get("page_method_counts", {}),
                "rawTextPath":           r.get("raw_text_path"),
                "chunkingStatus":        r.get("chunking_status", "skipped"),
                "chunkCount":            r.get("chunk_count", 0),
                "chunkWarningCount":     r.get("chunk_warning_count", 0),
                "chunkPath":             r.get("chunk_path"),
                "normalizationStatus":   r.get("normalization_status", "skipped"),
                "normalizedCount":       r.get("normalized_count", 0),
                "failedCount":           r.get("failed_count", 0),
                "validationErrorCount":  r.get("validation_error_count", 0),
                "normalizedOutputPath":  r.get("normalized_output_path"),
            }
            for r in records
        ],
    }


def print_summary(report: dict):
    s    = report["summary"]
    mode = report.get("mode", "full")

    is_normalize = mode in ("normalize-dry-run", "normalize-gemini")

    print(f"\n{'='*62}")
    print(f"  NBME PDF Extractor  [mode: {mode}]")
    print(f"{'='*62}")
    print(f"  Files processed        : {s['total']}")

    if not is_normalize and mode != "chunk-only":
        print(f"  Extraction  OK         : {s['extractionOk']}")
        print(f"  Extraction  WARN       : {s['extractionWarning']}")
        print(f"  Extraction  ERROR      : {s['extractionError']}")
        if s.get("totalOcrPages", 0) > 0:
            print(f"  Pages via OCR          : {s['totalOcrPages']}")
        if s.get("totalFailedPages", 0) > 0:
            print(f"  Pages failed (no text) : {s['totalFailedPages']}")

    if not is_normalize:
        print(f"  Chunking    OK         : {s['chunkingOk']}")
        print(f"  Chunking    WARN       : {s['chunkingWarning']}")
        print(f"  Chunking    ERROR      : {s['chunkingError']}")
        print(f"  Total chunks           : {s['totalChunks']}")
        print(f"  Total chunk warns      : {s['totalChunkWarnings']}")

    if is_normalize:
        print(f"  Normalization OK       : {s['normalizationOk']}")
        print(f"  Normalization WARN     : {s['normalizationWarning']}")
        print(f"  Normalization ERROR    : {s['normalizationError']}")
        print(f"  Total normalized       : {s['totalNormalized']}")
        if mode == "normalize-gemini":
            print(f"  Total failed           : {s['totalFailed']}")
            print(f"  Total validation errs  : {s['totalValidationErrors']}")
        else:
            print(f"  NOTE: dry run — no LLM called")

    print(f"  Elapsed                : {report['elapsedSeconds']}s")
    print(f"{'='*62}")

    icons = {"ok": "✅", "warning": "⚠️ ", "error": "❌", "skipped": "⏭ "}

    for f in report["files"]:
        ei = icons.get(f["extractionStatus"], "?")
        ci = icons.get(f["chunkingStatus"], "?")
        ni = icons.get(f["normalizationStatus"], "?")
        print(f"\n  {f['filename']}")

        if not is_normalize and mode != "chunk-only":
            chars = f"{f['charCount']:,}" if f.get("charCount") else "0"
            ocr_note = ""
            if f.get("ocrPages", 0) > 0:
                ocr_note = f", {f['ocrPages']} OCR'd"
            if f.get("failedPages", 0) > 0:
                ocr_note += f", {f['failedPages']} failed"
            print(f"    extract   {ei}  [{f['pageCount']} pages, {chars} chars{ocr_note}]")
            for w in f.get("extractionWarnings", []):
                print(f"           ⚠  {w}")
            if f.get("rawTextPath"):
                print(f"           → {f['rawTextPath']}")

        if not is_normalize:
            print(f"    chunk     {ci}  [{f['chunkCount']} chunks, {f['chunkWarningCount']} warnings]")
            if f.get("chunkPath"):
                print(f"           → {f['chunkPath']}")

        if is_normalize:
            if mode == "normalize-gemini":
                detail = (f"[{f['normalizedCount']} OK, {f['failedCount']} failed, "
                          f"{f['validationErrorCount']} val-errors]")
            else:
                detail = f"[{f['normalizedCount']} placeholders] (dry run)"
            print(f"    normalize {ni}  {detail}")
            if f.get("normalizedOutputPath"):
                print(f"           → {f['normalizedOutputPath']}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="NBME PDF → JSON Generator (Milestones 1–4.5)"
    )
    parser.add_argument(
        "--force-ocr", action="store_true",
        help=(
            "Force OCR on every PDF page regardless of extracted text content. "
            "Requires: pip3 install pymupdf pytesseract  &&  brew install tesseract"
        ),
    )
    parser.add_argument(
        "--chunk-only", action="store_true",
        help="Skip PDF extraction; re-chunk existing raw_text files",
    )
    parser.add_argument(
        "--normalize-dry-run", action="store_true",
        help="Create placeholder normalized JSON from chunk files (no LLM)",
    )
    parser.add_argument(
        "--normalize-gemini", action="store_true",
        help="Call Gemini to normalize chunk files (requires GEMINI_API_KEY env var)",
    )
    args = parser.parse_args()

    start = time.time()
    ensure_dirs()

    if args.normalize_gemini:
        mode = "normalize-gemini"
    elif args.normalize_dry_run:
        mode = "normalize-dry-run"
    elif args.chunk_only:
        mode = "chunk-only"
    else:
        mode = "full"

    # ------------------------------------------------------------------
    # normalize-gemini
    # ------------------------------------------------------------------
    if mode == "normalize-gemini":
        api_key     = _get_api_key()   # exits with message if missing
        chunk_files = sorted(CHUNKS_DIR.glob("*_chunks.json"))

        if not chunk_files:
            print(f"\nNo *_chunks.json files in {CHUNKS_DIR.relative_to(SCRIPT_DIR)}/")
            print("Run without --normalize-gemini first to generate chunk files.\n")
            report = build_report([], elapsed=0.0, mode=mode)
            _save_report(report)
            return

        print(f"\nFound {len(chunk_files)} chunk file(s) — Gemini normalization...")
        print(f"Model: {GEMINI_MODEL}\n")
        records = []
        total_f = len(chunk_files)

        for fi, chunk_path in enumerate(chunk_files, start=1):
            stem = chunk_path.stem
            if stem.endswith("_chunks"):
                stem = stem[:-7]
            print(f"\n  File {fi}/{total_f}: {chunk_path.name}")

            nr = normalize_gemini_chunk_file(chunk_path, api_key)
            icon = {"ok": "OK", "warning": "WARN", "error": "ERROR"}.get(nr["status"], "?")
            print(f"  → [{icon}]  {nr['normalizedCount']} normalized, "
                  f"{nr['failedCount']} failed")

            records.append({
                "filename":              f"{stem}.pdf",
                "page_count":            0,
                "extraction_status":     "skipped",
                "extraction_warnings":   [],
                "char_count":            0,
                "raw_text_path":         None,
                "chunking_status":       "skipped",
                "chunk_count":           0,
                "chunk_warning_count":   0,
                "chunk_path":            str(chunk_path.relative_to(SCRIPT_DIR)),
                "normalization_status":  nr["status"],
                "normalized_count":      nr["normalizedCount"],
                "failed_count":          nr["failedCount"],
                "validation_error_count": nr.get("validationErrorCount", 0),
                "normalized_output_path": nr.get("output_path"),
            })

        elapsed = time.time() - start
        report  = build_report(records, elapsed, mode)
        print_summary(report)
        _save_report(report)
        return

    # ------------------------------------------------------------------
    # normalize-dry-run
    # ------------------------------------------------------------------
    if mode == "normalize-dry-run":
        chunk_files = sorted(CHUNKS_DIR.glob("*_chunks.json"))
        if not chunk_files:
            print(f"\nNo *_chunks.json files in {CHUNKS_DIR.relative_to(SCRIPT_DIR)}/")
            print("Run without --normalize-dry-run first to generate chunk files.\n")
            report = build_report([], elapsed=0.0, mode=mode)
            _save_report(report)
            return

        print(f"\nFound {len(chunk_files)} chunk file(s) — normalize dry run (no LLM)...")
        records = []
        for chunk_path in chunk_files:
            print(f"  Normalizing: {chunk_path.name} ...", end=" ", flush=True)
            nr = normalize_dry_run(chunk_path)
            icon = {"ok": "OK", "warning": "WARN", "error": "ERROR"}.get(nr["status"], "?")
            print(f"[{icon}]  {nr['normalizedCount']} placeholders")

            stem = chunk_path.stem
            if stem.endswith("_chunks"):
                stem = stem[:-7]

            records.append({
                "filename":              f"{stem}.pdf",
                "page_count":            0,
                "extraction_status":     "skipped",
                "extraction_warnings":   [],
                "char_count":            0,
                "raw_text_path":         None,
                "chunking_status":       "skipped",
                "chunk_count":           0,
                "chunk_warning_count":   0,
                "chunk_path":            str(chunk_path.relative_to(SCRIPT_DIR)),
                "normalization_status":  nr["status"],
                "normalized_count":      nr["normalizedCount"],
                "failed_count":          0,
                "validation_error_count": 0,
                "normalized_output_path": nr.get("output_path"),
            })

        elapsed = time.time() - start
        report  = build_report(records, elapsed, mode)
        print_summary(report)
        _save_report(report)
        return

    # ------------------------------------------------------------------
    # chunk-only
    # ------------------------------------------------------------------
    if mode == "chunk-only":
        raw_files = sorted(RAW_TEXT_DIR.glob("*_raw.txt"))
        if not raw_files:
            print(f"\nNo *_raw.txt files in {RAW_TEXT_DIR.relative_to(SCRIPT_DIR)}/")
            print("Run without --chunk-only first to generate raw text files.\n")
            report = build_report([], elapsed=0.0, mode=mode)
            _save_report(report)
            return

        print(f"\nFound {len(raw_files)} raw text file(s) — chunking only...")
        records = []
        for raw_path in raw_files:
            print(f"  Chunking: {raw_path.name} ...", end=" ", flush=True)
            cr = chunk_raw_text(raw_path)
            icon = {"ok": "OK", "warning": "WARN", "error": "ERROR"}.get(cr["status"], "?")
            print(f"[{icon}]  {cr['chunkCount']} chunks")

            stem = raw_path.stem
            if stem.endswith("_raw"):
                stem = stem[:-4]

            records.append({
                "filename":              f"{stem}.pdf",
                "page_count":            0,
                "extraction_status":     "skipped",
                "extraction_warnings":   [],
                "char_count":            cr.get("char_count", 0),
                "raw_text_path":         str(raw_path.relative_to(SCRIPT_DIR)),
                "chunking_status":       cr["status"],
                "chunk_count":           cr["chunkCount"],
                "chunk_warning_count":   _total_chunk_warnings(cr),
                "chunk_path":            cr.get("output_path"),
                "normalization_status":  "skipped",
                "normalized_count":      0,
                "failed_count":          0,
                "validation_error_count": 0,
                "normalized_output_path": None,
            })

        elapsed = time.time() - start
        report  = build_report(records, elapsed, mode)
        print_summary(report)
        _save_report(report)
        return

    # ------------------------------------------------------------------
    # Full mode: extract PDFs + chunk
    # ------------------------------------------------------------------
    pdf_files = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"\nNo PDFs found in {INPUT_DIR.relative_to(SCRIPT_DIR)}/")
        print(f"Place NBME PDF files in:  {INPUT_DIR}\n")
        report = build_report([], elapsed=0.0, mode=mode)
        _save_report(report)
        return

    print(f"\nFound {len(pdf_files)} PDF(s) in {INPUT_DIR.relative_to(SCRIPT_DIR)}/")
    records = []

    for pdf_path in pdf_files:
        print(f"\n  [{pdf_path.name}]")
        print(f"    Extracting ...", end=" ", flush=True)
        ext = extract_pdf(pdf_path, force_ocr=args.force_ocr)
        ocr_note = f", {ext['ocr_pages']} OCR'd" if ext.get("ocr_pages") else ""
        print(f"[{ext['status'].upper()}]  {ext['page_count']} pages, "
              f"{ext['char_count']:,} chars{ocr_note}")

        cr = {"status": "skipped", "chunkCount": 0, "warnings": [],
              "_per_chunk_warn_total": 0, "output_path": None}

        if ext["status"] != "error" and ext.get("output_path"):
            raw_path = SCRIPT_DIR / ext["output_path"]
            print(f"    Chunking  ...", end=" ", flush=True)
            cr = chunk_raw_text(raw_path)
            print(f"[{cr['status'].upper()}]  {cr['chunkCount']} chunks")
        else:
            cr["warnings"].append("Skipped chunking: extraction failed")

        page_methods = ext.get("page_methods", [])
        method_counts = {
            m: page_methods.count(m) for m in ("text", "ocr", "text+ocr", "failed")
            if page_methods.count(m) > 0
        }
        records.append({
            "filename":              ext["filename"],
            "page_count":            ext.get("page_count", 0),
            "extraction_status":     ext["status"],
            "extraction_warnings":   ext.get("warnings", []),
            "char_count":            ext.get("char_count", 0),
            "ocr_pages":             ext.get("ocr_pages", 0),
            "failed_pages":          ext.get("failed_pages", 0),
            "page_method_counts":    method_counts,
            "raw_text_path":         ext.get("output_path"),
            "chunking_status":       cr["status"],
            "chunk_count":           cr["chunkCount"],
            "chunk_warning_count":   _total_chunk_warnings(cr),
            "chunk_path":            cr.get("output_path"),
            "normalization_status":  "skipped",
            "normalized_count":      0,
            "failed_count":          0,
            "validation_error_count": 0,
            "normalized_output_path": None,
        })

    elapsed = time.time() - start
    report  = build_report(records, elapsed, mode)
    print_summary(report)
    _save_report(report)


if __name__ == "__main__":
    main()
