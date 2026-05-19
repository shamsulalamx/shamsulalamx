#!/usr/bin/env python3
"""
OME PDF → Step 2 Question Generator (v1 — text extraction only)

Thin wrapper around the stable UWorld notes pipeline.

Reuses from tools/uworld-notes-question-generator/generate_uworld_questions.py:
  - Gemini HTTP client          - JSON cleaning         - retry/repair flow
  - validate_question           - call_gemini_with_retry - split_into_chunks
  - build_app_ready_json        - write_report           - dry-run placeholders
  - check_duplicate_stems       - renumber_questions     - _parse_gemini_json

OME-specific additions:
  - extract_pdf_text(): pdfplumber-based PDF extraction (replaces extract_text)
  - SUPPORTED_EXTENSIONS patched to {".pdf"}
  - sourceFormat set to "ome-pdf"
  - Per-file report fields: pagesProcessed, charsExtracted, figuresDetected, tablesDetected

v1 scope: native text layer extraction only.
Figure/table-aware multimodal generation is planned but not active in v1.

Usage:
  python3 generate_ome_questions.py --dry-run
  python3 generate_ome_questions.py --generate
  python3 generate_ome_questions.py --generate --questions-per-file 15
"""

import argparse
import os
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

# ── Import the stable UWorld generator ────────────────────────────────────────
_UW_DIR = Path(__file__).parent.parent / "uworld-notes-question-generator"
if not _UW_DIR.is_dir():
    sys.exit(f"ERROR: UWorld generator not found at expected path: {_UW_DIR}")
sys.path.insert(0, str(_UW_DIR))
import generate_uworld_questions as _uw  # noqa: E402

# ── Patch all path globals to point at OME workspace ──────────────────────────
_BASE = Path(__file__).parent

_uw.BASE_DIR    = _BASE
_uw.INPUT_DIR   = _BASE / "input_pdfs"
_uw.RAW_DIR     = _BASE / "output_json" / "raw_text"
_uw.CHUNK_DIR   = _BASE / "output_json" / "chunks"
_uw.GEN_DIR     = _BASE / "output_json" / "generated"
_uw.DEBUG_DIR   = _BASE / "output_json" / "generated" / "debug"
_uw.APP_DIR     = _BASE / "output_json" / "app_ready"
_uw.REPORT_DIR  = _BASE / "reports"
_uw.PROMPT_FILE = _BASE / "prompts" / "ome_to_questions_prompt.txt"

# ── PDF extraction (replaces text-file extract_text) ──────────────────────────
# Populated by extract_pdf_text(); read back into report_data after process_file().
_pdf_extraction_stats: Dict[str, Dict] = {}


def extract_pdf_text(filepath: Path) -> str:
    """
    Extract native text from an OME vector-based PDF using pdfplumber.

    v1: text layer only. No OCR. No figure/table extraction.
    Side-effect: populates _pdf_extraction_stats[str(filepath)].
    """
    try:
        import pdfplumber
    except ImportError:
        _uw.warn(
            "pdfplumber is not installed. "
            "Run: pip3 install pdfplumber"
        )
        _pdf_extraction_stats[str(filepath)] = {
            "pagesProcessed": 0,
            "totalPages": 0,
            "charsExtracted": 0,
            "figuresDetected": 0,
            "tablesDetected": 0,
            "extractionWarnings": ["pdfplumber not installed — no text extracted"],
        }
        return ""

    pages_text = []
    pages_processed = 0
    total_pages = 0
    extraction_warnings = []

    try:
        with pdfplumber.open(str(filepath)) as pdf:
            total_pages = len(pdf.pages)
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages_text.append(f"## Page {i + 1}\n\n{text.strip()}")
                    pages_processed += 1
                else:
                    extraction_warnings.append(
                        f"Page {i + 1}: no extractable text (may be image-only or blank)"
                    )
    except Exception as exc:
        extraction_warnings.append(f"pdfplumber error: {exc}")
        _uw.warn(f"PDF extraction failed for {filepath.name}: {exc}")

    full_text = "\n\n".join(pages_text)

    _pdf_extraction_stats[str(filepath)] = {
        "pagesProcessed": pages_processed,
        "totalPages": total_pages,
        "charsExtracted": len(full_text),
        "figuresDetected": 0,   # v1: not implemented
        "tablesDetected": 0,    # v1: not implemented
        "extractionWarnings": extraction_warnings,
    }

    return full_text


# ── Patch extract_text and SUPPORTED_EXTENSIONS in the UWorld module ──────────
_uw.extract_text = extract_pdf_text
_uw.SUPPORTED_EXTENSIONS = {".pdf"}

# ── Patch sourceFormat in app-ready output ────────────────────────────────────
_orig_build_app_ready = _uw.build_app_ready_json


def _ome_build_app_ready_json(source_stem, questions, warnings):
    result = _orig_build_app_ready(source_stem, questions, warnings)
    result["sourceFormat"] = "ome-pdf"
    return result


_uw.build_app_ready_json = _ome_build_app_ready_json


# ── CLI entry point ────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="OME PDF → Step 2 Question Generator (v1 — text extraction only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python3 generate_ome_questions.py --dry-run
              python3 generate_ome_questions.py --generate
              python3 generate_ome_questions.py --generate --questions-per-file 15
              python3 generate_ome_questions.py --generate --questions-per-file 8
              python3 generate_ome_questions.py --generate --questions-per-file 20
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
        help="Target number of questions to generate per input PDF (default: 15).",
    )
    args = parser.parse_args()

    if args.dry_run and args.generate:
        parser.error("--dry-run and --generate are mutually exclusive.")

    _uw.log("=" * 60)
    _uw.log("OME PDF → Question Generator (v1 — text extraction only)")
    _uw.log(f"  Model:              {_uw.GEMINI_MODEL}")
    _uw.log(f"  Dry-run:            {args.dry_run}")
    _uw.log(f"  Generate:           {args.generate}")
    _uw.log(f"  Questions per file: {args.questions_per_file}")
    _uw.log("=" * 60)

    for d in (_uw.INPUT_DIR, _uw.RAW_DIR, _uw.CHUNK_DIR, _uw.GEN_DIR,
              _uw.DEBUG_DIR, _uw.APP_DIR, _uw.REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    files = _uw.discover_input_files()
    if not files:
        _uw.log("No PDF files found in input_pdfs/")
        _uw.log("Drop OME lesson PDF files into input_pdfs/ and re-run.")
        _uw.write_report(
            {"status": "no_input_files", "files": {}},
            prefix="ome_generation_report",
        )
        return

    _uw.log(f"Found {len(files)} input PDF(s): {[f.name for f in files]}")

    # ── Resolve generation mode ──────────────────────────────────────────────
    dry_run = args.dry_run

    if args.generate:
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            _uw.log("ERROR: --generate requires GEMINI_API_KEY to be set.")
            _uw.log("Set it with: export GEMINI_API_KEY=your_key_here")
            sys.exit(1)
        dry_run = False
    elif not dry_run:
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            _uw.warn("GEMINI_API_KEY is not set — falling back to --dry-run mode.")
            _uw.warn("Pass --generate to treat a missing key as a hard error.")
            dry_run = True

    report_data: Dict = {
        "runTimestamp":     datetime.now().isoformat(),
        "model":            _uw.GEMINI_MODEL,
        "dryRun":           dry_run,
        "questionsPerFile": args.questions_per_file,
        "inputFiles":       [f.name for f in files],
        "files":            {},
    }
    t_total = time.time()

    for filepath in files:
        try:
            _uw.process_file(filepath, args.questions_per_file, dry_run, report_data)
            # Inject OME-specific PDF extraction stats into the per-file report entry.
            pdf_stats = _pdf_extraction_stats.get(str(filepath), {})
            if filepath.name in report_data["files"] and pdf_stats:
                report_data["files"][filepath.name].update({
                    "pagesProcessed":        pdf_stats.get("pagesProcessed", 0),
                    "charsExtracted":        pdf_stats.get("charsExtracted", 0),
                    "figuresDetected":       pdf_stats.get("figuresDetected", 0),
                    "tablesDetected":        pdf_stats.get("tablesDetected", 0),
                    "pdfExtractionWarnings": pdf_stats.get("extractionWarnings", []),
                })
        except Exception as exc:
            _uw.warn(f"Fatal error processing {filepath.name}: {exc}")
            report_data["files"][filepath.name] = {"status": "error", "error": str(exc)}

    report_data["totalElapsedSeconds"] = round(time.time() - t_total, 1)
    _uw.write_report(report_data, prefix="ome_generation_report")
    _uw.log("Done.")


if __name__ == "__main__":
    main()
