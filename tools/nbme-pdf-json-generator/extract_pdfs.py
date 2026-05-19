#!/usr/bin/env python3
"""
NBME PDF → JSON Generator — Milestone 1: Deterministic Extraction Skeleton

Scans input_pdfs/, extracts raw text from every .pdf, writes one .txt file
per PDF to output_json/raw_text/, and writes a structured JSON report to
reports/extraction_report_<timestamp>.json.

Does NOT call Gemini. Does NOT write any app-ready JSON yet.
"""

import json
import os
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
# Paths (relative to this script's location)
# ---------------------------------------------------------------------------

SCRIPT_DIR   = Path(__file__).parent.resolve()
INPUT_DIR    = SCRIPT_DIR / "input_pdfs"
OUTPUT_DIR   = SCRIPT_DIR / "output_json"
RAW_TEXT_DIR = OUTPUT_DIR / "raw_text"
REPORTS_DIR  = SCRIPT_DIR / "reports"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ensure_dirs():
    for d in (INPUT_DIR, OUTPUT_DIR, RAW_TEXT_DIR, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def extract_pdf(pdf_path: Path) -> dict:
    """
    Attempt to extract text from every page of pdf_path using pdfplumber.
    Returns a result dict with keys:
      filename, page_count, status, warnings, pages (list of str), output_path
    """
    result = {
        "filename":     pdf_path.name,
        "filepath":     str(pdf_path),
        "page_count":   0,
        "status":       "ok",
        "warnings":     [],
        "pages":        [],
        "output_path":  None,
        "char_count":   0,
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            result["page_count"] = len(pdf.pages)
            if result["page_count"] == 0:
                result["status"] = "warning"
                result["warnings"].append("PDF has 0 pages")
                return result

            for i, page in enumerate(pdf.pages, start=1):
                try:
                    text = page.extract_text() or ""
                    result["pages"].append(text)
                    if not text.strip():
                        result["warnings"].append(f"Page {i}: no extractable text (may be image-only)")
                except Exception as page_err:
                    result["warnings"].append(f"Page {i}: extraction error — {page_err}")
                    result["pages"].append("")

    except Exception as err:
        result["status"] = "error"
        result["warnings"].append(f"Could not open PDF: {err}")
        result["warnings"].append(traceback.format_exc())
        return result

    # Combine pages into a markdown-style document
    sections = []
    for i, text in enumerate(result["pages"], start=1):
        sections.append(f"## Page {i}\n\n{text.strip()}")
    full_text = "\n\n---\n\n".join(sections)
    result["char_count"] = len(full_text)

    if result["char_count"] == 0:
        result["status"] = "warning"
        result["warnings"].append("Total extracted text is empty — PDF may be fully image-based")

    # Write raw text file
    stem = pdf_path.stem
    out_path = RAW_TEXT_DIR / f"{stem}_raw.txt"
    try:
        out_path.write_text(full_text, encoding="utf-8")
        result["output_path"] = str(out_path.relative_to(SCRIPT_DIR))
    except Exception as write_err:
        result["status"] = "warning"
        result["warnings"].append(f"Could not write output file: {write_err}")

    # Downgrade status if there are warnings but extraction succeeded
    if result["status"] == "ok" and result["warnings"]:
        result["status"] = "warning"

    return result


def build_report(results: list, elapsed_sec: float) -> dict:
    total   = len(results)
    ok      = sum(1 for r in results if r["status"] == "ok")
    warning = sum(1 for r in results if r["status"] == "warning")
    error   = sum(1 for r in results if r["status"] == "error")

    return {
        "schemaVersion":   "nbme-pdf-extractor-report-v1",
        "generatedAt":     datetime.utcnow().isoformat() + "Z",
        "elapsedSeconds":  round(elapsed_sec, 2),
        "inputDirectory":  str(INPUT_DIR.relative_to(SCRIPT_DIR)),
        "outputDirectory": str(RAW_TEXT_DIR.relative_to(SCRIPT_DIR)),
        "summary": {
            "total":    total,
            "ok":       ok,
            "warning":  warning,
            "error":    error,
        },
        "files": [
            {
                "filename":    r["filename"],
                "pageCount":   r["page_count"],
                "status":      r["status"],
                "charCount":   r["char_count"],
                "warnings":    r["warnings"],
                "outputPath":  r["output_path"],
            }
            for r in results
        ],
    }


def print_summary(report: dict):
    s = report["summary"]
    print(f"\n{'='*60}")
    print(f"  NBME PDF Extractor — Milestone 1")
    print(f"{'='*60}")
    print(f"  PDFs processed : {s['total']}")
    print(f"  OK             : {s['ok']}")
    print(f"  Warnings       : {s['warning']}")
    print(f"  Errors         : {s['error']}")
    print(f"  Elapsed        : {report['elapsedSeconds']}s")
    print(f"{'='*60}")
    for f in report["files"]:
        icon = {"ok": "✅", "warning": "⚠️ ", "error": "❌"}.get(f["status"], "?")
        chars = f"{f['charCount']:,}" if f["charCount"] else "0"
        print(f"  {icon} {f['filename']}  [{f['pageCount']} pages, {chars} chars]")
        for w in f["warnings"]:
            print(f"       ⚠  {w}")
        if f["outputPath"]:
            print(f"       → {f['outputPath']}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import time
    start = time.time()

    ensure_dirs()

    pdf_files = sorted(INPUT_DIR.glob("*.pdf"))

    if not pdf_files:
        print(f"\nNo PDFs found in {INPUT_DIR}")
        print("Place your NBME PDF files inside:")
        print(f"  {INPUT_DIR}")
        print("Then re-run this script.\n")
        # Still write an empty report so the reports/ dir is populated
        report = build_report([], elapsed_sec=0.0)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_path = REPORTS_DIR / f"extraction_report_{ts}.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Empty report written to: {report_path.relative_to(SCRIPT_DIR)}\n")
        return

    print(f"\nFound {len(pdf_files)} PDF(s) in {INPUT_DIR.relative_to(SCRIPT_DIR)}/")
    results = []
    for pdf_path in pdf_files:
        print(f"  Processing: {pdf_path.name} ...", end=" ", flush=True)
        r = extract_pdf(pdf_path)
        results.append(r)
        icon = {"ok": "OK", "warning": "WARN", "error": "ERROR"}.get(r["status"], "?")
        print(f"[{icon}]")

    elapsed = time.time() - start
    report = build_report(results, elapsed)
    print_summary(report)

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"extraction_report_{ts}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report saved to: {report_path.relative_to(SCRIPT_DIR)}\n")


if __name__ == "__main__":
    main()
