#!/usr/bin/env python3
"""
OME PDF → Step 2 Question Generator

v1 (default / no flag): native text extraction via pdfplumber. No asset processing.
v2 (--extract-assets):  hybrid text + deterministic figure/table extraction.
    - PyMuPDF extracts embedded raster images; filtered by size + deduplication.
    - pdfplumber detects lattice/bordered tables.
    - Asset metadata injected as context markers in chunk text (no image bytes to Gemini).
    - Assets saved to extracted_figures/ and extracted_tables/.
    - No OCR. No schema changes. No app/importer changes.

Reuses from tools/uworld-notes-question-generator/generate_uworld_questions.py:
  Gemini HTTP client, JSON cleaning, 3-stage parse, validation, retry/repair,
  split_into_chunks, build_app_ready_json, write_report, dry-run placeholders.

OME-specific:
  extract_pdf_text() — pdfplumber text + optional PyMuPDF figures + pdfplumber tables
  SUPPORTED_EXTENSIONS — {".pdf"}
  sourceFormat — "ome-pdf"
  Report fields — pagesProcessed, charsExtracted, figuresDetected, figuresKept,
                  figuresIgnored, tablesDetected, tablesExtracted, assetOutputPaths,
                  pdfExtractionWarnings

Usage:
  python3 generate_ome_questions.py --dry-run
  python3 generate_ome_questions.py --dry-run --extract-assets
  python3 generate_ome_questions.py --generate
  python3 generate_ome_questions.py --generate --extract-assets
  python3 generate_ome_questions.py --generate --extract-assets --questions-per-file 15
"""

import argparse
import hashlib
import json
import os
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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

# ── OME-specific asset output directories ─────────────────────────────────────
_FIGURES_DIR = _BASE / "extracted_figures"
_TABLES_DIR  = _BASE / "extracted_tables"

# ── v2 feature flag — set to True by main() when --extract-assets is given ────
# extract_pdf_text() reads this global; set before process_file() is called.
_extract_assets: bool = False

# ── Figure filtering thresholds ───────────────────────────────────────────────
_MIN_FIG_DIM   = 80    # px — skip images smaller than this in either dimension
_MAX_FIG_RATIO = 8.0   # skip if max(w,h)/min(w,h) exceeds this (banner/divider)
_HIGH_CONF_DIM = 200   # px — both dims >= this → "high" confidence educational

# ── Per-file extraction stats — populated by extract_pdf_text() ───────────────
_pdf_extraction_stats: Dict[str, Dict] = {}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _figure_disposition(width: int, height: int) -> Optional[str]:
    """
    Determine whether to keep an extracted image and at what confidence.
    Returns "high", "medium", or None (skip/ignore).
    Conservative: prefer false-negatives over false-positives on decoratives.
    """
    if width < _MIN_FIG_DIM or height < _MIN_FIG_DIM:
        return None  # too small — icon, bullet, logo, watermark
    long, short = max(width, height), max(min(width, height), 1)
    if long / short > _MAX_FIG_RATIO:
        return None  # extreme ratio — banner, horizontal rule, divider line
    if width >= _HIGH_CONF_DIM and height >= _HIGH_CONF_DIM:
        return "high"
    return "medium"


def _table_to_markdown(table: List[List]) -> str:
    """Convert a pdfplumber table (list of lists) to GitHub-flavored markdown."""
    if not table:
        return ""
    lines: List[str] = []
    for i, row in enumerate(table):
        cells = [str(c or "").replace("\n", " ").strip() for c in row]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("|" + "|".join([" --- " for _ in cells]) + "|")
    return "\n".join(lines)


def _empty_stats(warning: str) -> Dict:
    return {
        "pagesProcessed": 0, "totalPages": 0, "charsExtracted": 0,
        "figuresDetected": 0, "figuresKept": 0, "figuresIgnored": 0,
        "tablesDetected": 0, "tablesExtracted": 0,
        "assetOutputPaths": [], "extractionWarnings": [warning],
    }


# ── PDF extraction ─────────────────────────────────────────────────────────────

def extract_pdf_text(filepath: Path) -> str:
    """
    Extract text from an OME vector-based PDF.

    v1 (always): pdfplumber text extraction per page.
    v2 (when _extract_assets is True):
      - Also runs pdfplumber table extraction per page.
      - Also runs PyMuPDF figure extraction per page.
      - Saves assets to extracted_figures/ and extracted_tables/.
      - Injects asset metadata markers into the returned text so that
        split_into_chunks() and Gemini receive them as context.
      No OCR. No image bytes sent to Gemini.

    Side-effect: populates _pdf_extraction_stats[str(filepath)].
    """
    try:
        import pdfplumber
    except ImportError:
        _uw.warn("pdfplumber not installed. Run: pip3 install pdfplumber")
        _pdf_extraction_stats[str(filepath)] = _empty_stats("pdfplumber not installed")
        return ""

    fitz_available = False
    if _extract_assets:
        try:
            import fitz  # noqa: F401
            fitz_available = True
        except ImportError:
            _uw.warn(
                "--extract-assets: PyMuPDF (fitz) not installed; "
                "figure extraction disabled. Run: pip3 install pymupdf"
            )

    stem = filepath.stem
    pages_text: List[str] = []
    pages_processed = 0
    total_pages = 0
    extraction_warnings: List[str] = []

    figures_detected = 0
    figures_kept = 0
    figures_ignored = 0
    tables_detected = 0
    tables_extracted = 0
    asset_output_paths: List[str] = []

    try:
        with pdfplumber.open(str(filepath)) as pdf:
            total_pages = len(pdf.pages)

            fitz_doc = None
            if _extract_assets and fitz_available:
                import fitz
                fitz_doc = fitz.open(str(filepath))

            seen_hashes: set = set()

            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                text = page.extract_text() or ""
                page_markers: List[str] = []

                if _extract_assets:

                    # ── Figures (PyMuPDF) ──────────────────────────────────
                    if fitz_doc is not None:
                        import fitz
                        fitz_page = fitz_doc[i]
                        for img_idx, img_info in enumerate(
                            fitz_page.get_images(full=True)
                        ):
                            xref = img_info[0]
                            try:
                                pix = fitz.Pixmap(fitz_doc, xref)
                                # Normalise CMYK or multi-channel to RGB
                                if pix.n - pix.alpha > 3:
                                    pix = fitz.Pixmap(fitz.csRGB, pix)
                                w, h = pix.width, pix.height
                                figures_detected += 1

                                confidence = _figure_disposition(w, h)
                                if confidence is None:
                                    figures_ignored += 1
                                    continue

                                # Hash-based deduplication (repeated header/footer graphics)
                                img_hash = hashlib.md5(pix.samples).hexdigest()
                                if img_hash in seen_hashes:
                                    figures_ignored += 1
                                    continue
                                seen_hashes.add(img_hash)

                                fname = f"{stem}_p{page_num}_fig{img_idx + 1}.png"
                                fpath = _FIGURES_DIR / fname
                                fpath.write_bytes(pix.tobytes("png"))
                                figures_kept += 1
                                asset_output_paths.append(str(fpath))

                                page_markers.append(
                                    f"[DETECTED FIGURE: {fname}"
                                    f" | {w}×{h} px"
                                    f" | confidence: {confidence}]\n"
                                    f"An educational image was detected here."
                                    f" If it appears to be a chart, diagram,"
                                    f" algorithm, or clinical image, incorporate"
                                    f" its likely topic into a question.\n"
                                )
                            except Exception as exc:
                                msg = f"Page {page_num} fig {img_idx + 1}: {exc}"
                                extraction_warnings.append(msg)
                                _uw.warn(f"Figure extraction error — {msg}")

                    # ── Tables (pdfplumber) ────────────────────────────────
                    try:
                        raw_tables = page.extract_tables() or []
                        for tbl_idx, tbl in enumerate(raw_tables):
                            if not tbl:
                                continue
                            n_rows = len(tbl)
                            n_cols = len(tbl[0]) if tbl else 0
                            # Skip trivial single-row or single-column extractions
                            if n_rows < 2 or n_cols < 2:
                                continue
                            tables_detected += 1

                            tname = f"{stem}_p{page_num}_table{tbl_idx + 1}.json"
                            tpath = _TABLES_DIR / tname
                            tpath.write_text(
                                json.dumps(
                                    {"page": page_num, "rows": n_rows,
                                     "cols": n_cols, "data": tbl},
                                    ensure_ascii=False, indent=2,
                                ),
                                encoding="utf-8",
                            )
                            tables_extracted += 1
                            asset_output_paths.append(str(tpath))

                            md = _table_to_markdown(tbl)
                            page_markers.append(
                                f"[DETECTED TABLE: {tname}"
                                f" | {n_rows} rows × {n_cols} cols]\n"
                                f"{md}\n"
                            )
                    except Exception as exc:
                        msg = f"Page {page_num} table extraction: {exc}"
                        extraction_warnings.append(msg)
                        _uw.warn(f"Table extraction error — {msg}")

                # Build page block: header, then any asset markers, then native text
                block_parts: List[str] = [f"## Page {page_num}"]
                if page_markers:
                    block_parts.extend(page_markers)
                if text.strip():
                    block_parts.append(text.strip())
                    pages_processed += 1
                else:
                    if not page_markers:
                        # Only warn when the page has neither text nor assets
                        extraction_warnings.append(
                            f"Page {page_num}: no extractable text"
                        )

                # Include page block if it has content beyond the bare header
                if len(block_parts) > 1:
                    pages_text.append("\n\n".join(block_parts))

            if fitz_doc is not None:
                fitz_doc.close()

    except Exception as exc:
        extraction_warnings.append(f"pdfplumber error: {exc}")
        _uw.warn(f"PDF extraction failed for {filepath.name}: {exc}")

    full_text = "\n\n".join(pages_text)

    _pdf_extraction_stats[str(filepath)] = {
        "pagesProcessed": pages_processed,
        "totalPages": total_pages,
        "charsExtracted": len(full_text),
        "figuresDetected": figures_detected,
        "figuresKept": figures_kept,
        "figuresIgnored": figures_ignored,
        "tablesDetected": tables_detected,
        "tablesExtracted": tables_extracted,
        "assetOutputPaths": asset_output_paths,
        "extractionWarnings": extraction_warnings,
    }

    return full_text


# ── Patch extract_text and SUPPORTED_EXTENSIONS in the UWorld module ──────────
_uw.extract_text = extract_pdf_text
_uw.SUPPORTED_EXTENSIONS = {".pdf"}

# ── Patch sourceFormat ─────────────────────────────────────────────────────────
_orig_build_app_ready = _uw.build_app_ready_json


def _ome_build_app_ready_json(source_stem, questions, warnings):
    result = _orig_build_app_ready(source_stem, questions, warnings)
    result["sourceFormat"] = "ome-pdf"
    return result


_uw.build_app_ready_json = _ome_build_app_ready_json


# ── CLI entry point ────────────────────────────────────────────────────────────

def main() -> None:
    global _extract_assets

    parser = argparse.ArgumentParser(
        description="OME PDF → Step 2 Question Generator (v1/v2)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            v1 — text only (default):
              python3 generate_ome_questions.py --dry-run
              python3 generate_ome_questions.py --generate

            v2 — hybrid text + asset extraction:
              python3 generate_ome_questions.py --dry-run --extract-assets
              python3 generate_ome_questions.py --generate --extract-assets
              python3 generate_ome_questions.py --generate --extract-assets --questions-per-file 15

            v2 requires PyMuPDF for figure extraction: pip3 install pymupdf
        """),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Gemini calls; produce placeholder app-ready JSON only.",
    )
    parser.add_argument(
        "--generate", action="store_true",
        help="Run live Gemini generation. Exits if GEMINI_API_KEY is unset.",
    )
    parser.add_argument(
        "--questions-per-file", type=int, default=15, metavar="N",
        help="Target questions per input PDF (default: 15).",
    )
    parser.add_argument(
        "--extract-assets",
        action="store_true",
        help=(
            "Enable v2 hybrid extraction: detect embedded figures (PyMuPDF) and "
            "tables (pdfplumber). Assets saved to extracted_figures/ and "
            "extracted_tables/. Asset metadata injected as text context into "
            "Gemini prompts. No OCR. No image bytes sent to Gemini. "
            "Requires: pip3 install pymupdf"
        ),
    )
    args = parser.parse_args()

    if args.dry_run and args.generate:
        parser.error("--dry-run and --generate are mutually exclusive.")

    _extract_assets = args.extract_assets
    mode_label = "v2 (text + asset extraction)" if _extract_assets else "v1 (text only)"

    _uw.log("=" * 60)
    _uw.log(f"OME PDF → Question Generator [{mode_label}]")
    _uw.log(f"  Model:              {_uw.GEMINI_MODEL}")
    _uw.log(f"  Dry-run:            {args.dry_run}")
    _uw.log(f"  Generate:           {args.generate}")
    _uw.log(f"  Extract assets:     {_extract_assets}")
    _uw.log(f"  Questions per file: {args.questions_per_file}")
    _uw.log("=" * 60)

    # Always create asset dirs so their presence is discoverable
    for d in (
        _uw.INPUT_DIR, _uw.RAW_DIR, _uw.CHUNK_DIR, _uw.GEN_DIR,
        _uw.DEBUG_DIR, _uw.APP_DIR, _uw.REPORT_DIR,
        _FIGURES_DIR, _TABLES_DIR,
    ):
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

    dry_run = args.dry_run
    if args.generate:
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            _uw.log("ERROR: --generate requires GEMINI_API_KEY to be set.")
            _uw.log("Set it with: export GEMINI_API_KEY=your_key_here")
            sys.exit(1)
        dry_run = False
    elif not dry_run:
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            _uw.warn("GEMINI_API_KEY not set — falling back to --dry-run mode.")
            _uw.warn("Pass --generate to treat a missing key as a hard error.")
            dry_run = True

    report_data: Dict = {
        "runTimestamp":     datetime.now().isoformat(),
        "model":            _uw.GEMINI_MODEL,
        "dryRun":           dry_run,
        "extractAssets":    _extract_assets,
        "questionsPerFile": args.questions_per_file,
        "inputFiles":       [f.name for f in files],
        "files":            {},
    }
    t_total = time.time()

    for filepath in files:
        try:
            _uw.process_file(filepath, args.questions_per_file, dry_run, report_data)
            pdf_stats = _pdf_extraction_stats.get(str(filepath), {})
            if filepath.name in report_data["files"] and pdf_stats:
                report_data["files"][filepath.name].update({
                    "pagesProcessed":        pdf_stats.get("pagesProcessed", 0),
                    "charsExtracted":        pdf_stats.get("charsExtracted", 0),
                    "figuresDetected":       pdf_stats.get("figuresDetected", 0),
                    "figuresKept":           pdf_stats.get("figuresKept", 0),
                    "figuresIgnored":        pdf_stats.get("figuresIgnored", 0),
                    "tablesDetected":        pdf_stats.get("tablesDetected", 0),
                    "tablesExtracted":       pdf_stats.get("tablesExtracted", 0),
                    "assetOutputPaths":      pdf_stats.get("assetOutputPaths", []),
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
