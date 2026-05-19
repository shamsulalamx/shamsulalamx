#!/usr/bin/env python3
"""
NBME PDF → JSON Generator

Milestone 1: PDF → raw text extraction (pdfplumber)
Milestone 2: raw text → question chunks (deterministic, no AI)
Milestone 3: chunks → normalized scaffold (dry-run placeholder, no LLM)

Usage:
  python3 extract_pdfs.py                  # full pipeline: extract + chunk
  python3 extract_pdfs.py --chunk-only     # re-chunk existing raw_text files
  python3 extract_pdfs.py --normalize-dry-run  # create placeholder normalized JSON (no LLM)
"""

import argparse
import json
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("ERROR: pdfplumber is not installed.")
    print("Run:  pip3 install pdfplumber")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR      = Path(__file__).parent.resolve()
INPUT_DIR       = SCRIPT_DIR / "input_pdfs"
OUTPUT_DIR      = SCRIPT_DIR / "output_json"
RAW_TEXT_DIR    = OUTPUT_DIR / "raw_text"
CHUNKS_DIR      = OUTPUT_DIR / "chunks"
NORMALIZED_DIR  = OUTPUT_DIR / "normalized"
REPORTS_DIR     = SCRIPT_DIR / "reports"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTAMINATION_PHRASES = [
    "Here are the extracted questions",
    "eftab720",
    "tightenfactor0",
]

MIN_CHUNK_CHARS = 80

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

# Question boundary detection (anchored to line start via MULTILINE):
#   "Question 1"  "Question 1."  "Question 1:"
#   "Item 1"      "Item 1."      "Item 1:"
#   "1. "         "1) "
_Q_BOUNDARY_RE = re.compile(
    r'^(?:'
    r'(?:Question|Item)\s+(\d+)[.):\s]'   # group 1 — "Question N" / "Item N"
    r'|(\d+)[.)]\s'                        # group 2 — "N. " or "N) "
    r')',
    re.MULTILINE | re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def ensure_dirs():
    for d in (INPUT_DIR, OUTPUT_DIR, RAW_TEXT_DIR, CHUNKS_DIR, NORMALIZED_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _save_report(report: dict):
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = REPORTS_DIR / f"extraction_report_{ts}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Report saved to: {path.relative_to(SCRIPT_DIR)}\n")


# ---------------------------------------------------------------------------
# Milestone 1: PDF → raw text
# ---------------------------------------------------------------------------

def extract_pdf(pdf_path: Path) -> dict:
    """Extract text from all pages of a PDF using pdfplumber."""
    result = {
        "filename":    pdf_path.name,
        "page_count":  0,
        "status":      "ok",
        "warnings":    [],
        "output_path": None,
        "char_count":  0,
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            result["page_count"] = len(pdf.pages)
            if result["page_count"] == 0:
                result["status"] = "warning"
                result["warnings"].append("PDF has 0 pages")
                return result

            pages_text = []
            for i, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text() or ""
                    pages_text.append(text)
                    if not text.strip():
                        result["warnings"].append(
                            f"Page {i}: no extractable text (may be image-only)"
                        )
                except Exception as e:
                    result["warnings"].append(f"Page {i}: extraction error — {e}")
                    pages_text.append("")

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
    """Remove the ## Page N headers and --- separators written by M1."""
    text = re.sub(r'^## Page \d+\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^---\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _parse_q_number(m: re.Match) -> int:
    return int(m.group(1) if m.group(1) else m.group(2))


def _confidence(raw_text: str) -> str:
    has_choices = bool(ANSWER_CHOICE_RE.search(raw_text))
    long_enough = len(raw_text.strip()) >= MIN_CHUNK_CHARS
    if has_choices and long_enough:
        return "high"
    if has_choices or long_enough:
        return "medium"
    return "low"


def chunk_raw_text(raw_path: Path) -> dict:
    """
    Split a _raw.txt file into per-question chunks.
    Returns a result dict; also writes the _chunks.json file as a side-effect.
    """
    stem = raw_path.stem
    if stem.endswith("_raw"):
        stem = stem[:-4]

    result = {
        "status":                 "ok",
        "warnings":               [],
        "chunkCount":             0,
        "char_count":             0,
        "_per_chunk_warn_total":  0,
        "output_path":            None,
    }

    try:
        raw = raw_path.read_text(encoding="utf-8")
    except Exception as e:
        result["status"] = "error"
        result["warnings"].append(f"Could not read file: {e}")
        return result

    result["char_count"] = len(raw)

    # Contamination scan on full text
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

    # Preamble check
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

        cw = []  # per-chunk warnings

        if q_num in seen_numbers:
            cw.append(f"Duplicate question number {q_num} (also at chunk index {seen_numbers[q_num]})")
        seen_numbers[q_num] = idx

        if len(raw_chunk) < MIN_CHUNK_CHARS:
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
            "confidence":     _confidence(raw_chunk),
            "warnings":       cw,
        })

    # Missing question numbers in sequence
    if chunks:
        nums     = [c["questionNumber"] for c in chunks]
        missing  = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
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
    """
    Read a _chunks.json file and write a placeholder _normalized.json file.
    Does NOT call Gemini or any LLM.  Every question gets an empty scaffold
    with a warning flagging it as a dry-run placeholder.
    """
    stem = chunk_path.stem
    if stem.endswith("_chunks"):
        stem = stem[:-7]

    result = {
        "status":           "ok",
        "warnings":         [],
        "normalizedCount":  0,
        "output_path":      None,
    }

    try:
        payload = json.loads(chunk_path.read_text(encoding="utf-8"))
    except Exception as e:
        result["status"] = "error"
        result["warnings"].append(f"Could not read chunk file: {e}")
        return result

    chunks = payload.get("chunks", [])
    source_file = payload.get("sourceFile", chunk_path.name)

    if not chunks:
        result["status"] = "warning"
        result["warnings"].append("Chunk file contains 0 chunks — nothing to normalize")

    # Check for contamination in fileWarnings from M2
    file_warnings = payload.get("fileWarnings", [])
    for w in file_warnings:
        if any(p.lower() in w.lower() for p in CONTAMINATION_PHRASES):
            result["warnings"].append(f"Contamination flagged by chunker: {w}")

    questions = []
    for chunk in chunks:
        q_num    = chunk.get("questionNumber", 0)
        chunk_id = chunk.get("chunkId", f"q{q_num:03d}")
        raw_text = chunk.get("rawText", "")

        # Inherit any per-chunk warnings from M2
        inherited = [f"[from chunker] {w}" for w in chunk.get("warnings", [])]

        # Detect contamination in this chunk's rawText
        chunk_contaminated = any(
            p.lower() in raw_text.lower() for p in CONTAMINATION_PHRASES
        )
        if chunk_contaminated:
            inherited.append("Contamination phrase detected in chunk rawText")

        questions.append({
            "schemaVersion":         "nbme-normalized-question-v1",
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
        "schemaVersion":    "nbme-normalized-file-v1",
        "sourceChunkFile":  chunk_path.name,
        "createdAt":        datetime.utcnow().isoformat() + "Z",
        "isDryRun":         True,
        "questionCount":    len(questions),
        "fileWarnings":     result["warnings"],
        "questions":        questions,
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
# Report
# ---------------------------------------------------------------------------

def build_report(records: list, elapsed: float, mode: str) -> dict:
    def cnt(field, val):
        return sum(1 for r in records if r.get(field) == val)

    return {
        "schemaVersion":       "nbme-pdf-extractor-report-v3",
        "generatedAt":         datetime.utcnow().isoformat() + "Z",
        "elapsedSeconds":      round(elapsed, 2),
        "mode":                mode,
        "inputDirectory":      str(INPUT_DIR.relative_to(SCRIPT_DIR)),
        "rawTextDirectory":    str(RAW_TEXT_DIR.relative_to(SCRIPT_DIR)),
        "chunksDirectory":     str(CHUNKS_DIR.relative_to(SCRIPT_DIR)),
        "normalizedDirectory": str(NORMALIZED_DIR.relative_to(SCRIPT_DIR)),
        "summary": {
            "total":                len(records),
            "extractionOk":         cnt("extraction_status", "ok"),
            "extractionWarning":    cnt("extraction_status", "warning"),
            "extractionError":      cnt("extraction_status", "error"),
            "extractionSkipped":    cnt("extraction_status", "skipped"),
            "chunkingOk":           cnt("chunking_status", "ok"),
            "chunkingWarning":      cnt("chunking_status", "warning"),
            "chunkingError":        cnt("chunking_status", "error"),
            "chunkingSkipped":      cnt("chunking_status", "skipped"),
            "totalChunks":          sum(r.get("chunk_count", 0) for r in records),
            "totalChunkWarnings":   sum(r.get("chunk_warning_count", 0) for r in records),
            "normalizationOk":      cnt("normalization_status", "ok"),
            "normalizationWarning": cnt("normalization_status", "warning"),
            "normalizationError":   cnt("normalization_status", "error"),
            "normalizationSkipped": cnt("normalization_status", "skipped"),
            "totalNormalized":      sum(r.get("normalized_count", 0) for r in records),
        },
        "files": [
            {
                "filename":             r["filename"],
                "pageCount":            r.get("page_count", 0),
                "extractionStatus":     r.get("extraction_status", "skipped"),
                "extractionWarnings":   r.get("extraction_warnings", []),
                "charCount":            r.get("char_count", 0),
                "rawTextPath":          r.get("raw_text_path"),
                "chunkingStatus":       r.get("chunking_status", "skipped"),
                "chunkCount":           r.get("chunk_count", 0),
                "chunkWarningCount":    r.get("chunk_warning_count", 0),
                "chunkPath":            r.get("chunk_path"),
                "normalizationStatus":  r.get("normalization_status", "skipped"),
                "normalizedCount":      r.get("normalized_count", 0),
                "normalizedOutputPath": r.get("normalized_output_path"),
            }
            for r in records
        ],
    }


def print_summary(report: dict):
    s    = report["summary"]
    mode = report.get("mode", "full")

    print(f"\n{'='*60}")
    print(f"  NBME PDF Extractor  [mode: {mode}]")
    print(f"{'='*60}")
    print(f"  Files processed      : {s['total']}")
    if mode not in ("chunk-only", "normalize-dry-run"):
        print(f"  Extraction  OK       : {s['extractionOk']}")
        print(f"  Extraction  WARN     : {s['extractionWarning']}")
        print(f"  Extraction  ERROR    : {s['extractionError']}")
    if mode != "normalize-dry-run":
        print(f"  Chunking    OK       : {s['chunkingOk']}")
        print(f"  Chunking    WARN     : {s['chunkingWarning']}")
        print(f"  Chunking    ERROR    : {s['chunkingError']}")
        print(f"  Total chunks         : {s['totalChunks']}")
        print(f"  Total chunk warns    : {s['totalChunkWarnings']}")
    if mode == "normalize-dry-run":
        print(f"  Normalization OK     : {s['normalizationOk']}")
        print(f"  Normalization WARN   : {s['normalizationWarning']}")
        print(f"  Normalization ERROR  : {s['normalizationError']}")
        print(f"  Total normalized     : {s['totalNormalized']}")
        print(f"  NOTE: dry run only — no LLM called")
    print(f"  Elapsed              : {report['elapsedSeconds']}s")
    print(f"{'='*60}")

    icons = {"ok": "✅", "warning": "⚠️ ", "error": "❌", "skipped": "⏭ "}

    for f in report["files"]:
        ei = icons.get(f["extractionStatus"], "?")
        ci = icons.get(f["chunkingStatus"], "?")
        ni = icons.get(f["normalizationStatus"], "?")
        print(f"\n  {f['filename']}")
        if mode not in ("chunk-only", "normalize-dry-run"):
            chars = f"{f['charCount']:,}" if f.get("charCount") else "0"
            print(f"    extract   {ei}  [{f['pageCount']} pages, {chars} chars]")
            for w in f.get("extractionWarnings", []):
                print(f"           ⚠  {w}")
            if f.get("rawTextPath"):
                print(f"           → {f['rawTextPath']}")
        if mode != "normalize-dry-run":
            print(f"    chunk     {ci}  [{f['chunkCount']} chunks, {f['chunkWarningCount']} warnings]")
            if f.get("chunkPath"):
                print(f"           → {f['chunkPath']}")
        if mode == "normalize-dry-run":
            print(f"    normalize {ni}  [{f['normalizedCount']} placeholders] (dry run)")
            if f.get("normalizedOutputPath"):
                print(f"           → {f['normalizedOutputPath']}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import time

    parser = argparse.ArgumentParser(
        description="NBME PDF → JSON Generator (Milestones 1+2+3)"
    )
    parser.add_argument(
        "--chunk-only",
        action="store_true",
        help="Skip PDF extraction; re-chunk existing raw_text files",
    )
    parser.add_argument(
        "--normalize-dry-run",
        action="store_true",
        help="Create placeholder normalized JSON from existing chunk files (no LLM called)",
    )
    args = parser.parse_args()

    start = time.time()
    ensure_dirs()

    if args.normalize_dry_run:
        mode = "normalize-dry-run"
    elif args.chunk_only:
        mode = "chunk-only"
    else:
        mode = "full"

    # ------------------------------------------------------------------
    # normalize-dry-run: create placeholder normalized JSON, no LLM
    # ------------------------------------------------------------------
    if args.normalize_dry_run:
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
                "normalized_output_path": nr.get("output_path"),
            })

        elapsed = time.time() - start
        report  = build_report(records, elapsed, mode)
        print_summary(report)
        _save_report(report)
        return

    # ------------------------------------------------------------------
    # chunk-only: re-chunk existing raw_text files, skip PDF scanning
    # ------------------------------------------------------------------
    if args.chunk_only:
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
                "normalized_output_path": None,
            })

        elapsed = time.time() - start
        report  = build_report(records, elapsed, mode)
        print_summary(report)
        _save_report(report)
        return

    # ------------------------------------------------------------------
    # Full mode: extract PDFs, then chunk each one
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
        ext = extract_pdf(pdf_path)
        print(f"[{ext['status'].upper()}]  {ext['page_count']} pages, {ext['char_count']:,} chars")

        cr = {"status": "skipped", "chunkCount": 0, "warnings": [],
              "_per_chunk_warn_total": 0, "output_path": None}

        if ext["status"] != "error" and ext.get("output_path"):
            raw_path = SCRIPT_DIR / ext["output_path"]
            print(f"    Chunking  ...", end=" ", flush=True)
            cr = chunk_raw_text(raw_path)
            print(f"[{cr['status'].upper()}]  {cr['chunkCount']} chunks")
        else:
            cr["warnings"].append("Skipped chunking: extraction failed")

        records.append({
            "filename":              ext["filename"],
            "page_count":            ext.get("page_count", 0),
            "extraction_status":     ext["status"],
            "extraction_warnings":   ext.get("warnings", []),
            "char_count":            ext.get("char_count", 0),
            "raw_text_path":         ext.get("output_path"),
            "chunking_status":       cr["status"],
            "chunk_count":           cr["chunkCount"],
            "chunk_warning_count":   _total_chunk_warnings(cr),
            "chunk_path":            cr.get("output_path"),
            "normalization_status":  "skipped",
            "normalized_count":      0,
            "normalized_output_path": None,
        })

    elapsed = time.time() - start
    report  = build_report(records, elapsed, mode)
    print_summary(report)
    _save_report(report)


if __name__ == "__main__":
    main()
