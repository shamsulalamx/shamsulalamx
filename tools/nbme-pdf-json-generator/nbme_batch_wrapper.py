#!/usr/bin/env python3
"""
Batch Import Center wrapper for the existing NBME PDF pipeline.

This file only orchestrates the current extractor, normalizer, app-ready
converter, and figure review utility for one selected PDF. It does not change
their internal behavior or schemas.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path

import extract_pdfs
import normalized_to_app_json
import nbme_extract_figures


SCRIPT_DIR = Path(__file__).parent.resolve()
INPUT_DIR = SCRIPT_DIR / "input_pdfs"
RAW_DIR = SCRIPT_DIR / "output_json" / "raw_text"
CHUNKS_DIR = SCRIPT_DIR / "output_json" / "chunks"
NORMALIZED_DIR = SCRIPT_DIR / "output_json" / "normalized"
APP_READY_DIR = SCRIPT_DIR / "output_json" / "app_ready"


def log(message: str) -> None:
    print(message, flush=True)


def safe_stem(path: Path, max_pages: int | None) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", path.stem).strip("_") or "nbme_pdf"
    if max_pages:
        return f"{stem}_batch_p001_p{max_pages:03d}"
    return f"{stem}_batch"


def limited_pdf_path(input_file: Path, max_pages: int | None) -> Path:
    return INPUT_DIR / f"{safe_stem(input_file, max_pages)}.pdf"


def create_limited_pdf(input_file: Path, max_pages: int | None) -> Path:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = limited_pdf_path(input_file, max_pages)
    if max_pages is None:
        shutil.copy2(input_file, target)
        return target

    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("PyMuPDF is required to create a page-limited NBME validation PDF") from exc

    with fitz.open(str(input_file)) as src:
        if src.page_count < 1:
            raise RuntimeError("Selected PDF has no pages")
        page_count = min(max_pages, src.page_count)
        with fitz.open() as out:
            out.insert_pdf(src, from_page=0, to_page=page_count - 1)
            out.save(str(target))
    return target


def artifact_paths(input_file: Path, max_pages: int | None) -> dict[str, Path]:
    stem = safe_stem(input_file, max_pages)
    return {
        "pdf": INPUT_DIR / f"{stem}.pdf",
        "raw": RAW_DIR / f"{stem}_raw.txt",
        "chunks": CHUNKS_DIR / f"{stem}_chunks.json",
        "normalized": NORMALIZED_DIR / f"{stem}_normalized.json",
        "app_ready": APP_READY_DIR / f"{stem}_app_ready.json",
    }


def require_artifact(path: Path, previous_stage: str) -> Path:
    if not path.exists():
        raise RuntimeError(f"Missing {path.relative_to(SCRIPT_DIR)}. Run {previous_stage} first.")
    return path


def run_ocr(args: argparse.Namespace) -> int:
    input_file = Path(args.input_file).expanduser().resolve()
    log(f"OCR: preparing first {args.max_pages} page(s) from {input_file.name}")
    pdf_path = create_limited_pdf(input_file, args.max_pages)
    log(f"OCR: selected batch PDF {pdf_path.relative_to(SCRIPT_DIR)}")
    extract_pdfs.ensure_dirs()
    started = time.time()
    result = extract_pdfs.extract_pdf(pdf_path, force_ocr=args.force_ocr)
    elapsed = round(time.time() - started, 2)
    log(
        "OCR: "
        f"{result.get('status')} in {elapsed}s; "
        f"{result.get('page_count', 0)} page(s), "
        f"{result.get('ocr_pages', 0)} OCR page(s), "
        f"{result.get('char_count', 0)} chars"
    )
    for warning in result.get("warnings", []) or []:
        log(f"WARN: {warning}")
    return 0 if result.get("status") != "error" else 1


def run_chunking(args: argparse.Namespace) -> int:
    paths = artifact_paths(Path(args.input_file).expanduser().resolve(), args.max_pages)
    raw_path = require_artifact(paths["raw"], "OCR")
    log(f"chunking: reading {raw_path.relative_to(SCRIPT_DIR)}")
    started = time.time()
    result = extract_pdfs.chunk_raw_text(raw_path)
    elapsed = round(time.time() - started, 2)
    log(f"chunking: {result.get('status')} in {elapsed}s; {result.get('chunkCount', 0)} chunk(s)")
    for warning in result.get("warnings", []) or []:
        if isinstance(warning, dict):
            log(f"WARN: chunk {warning.get('chunkNumber')}: {'; '.join(warning.get('warnings', []))}")
        else:
            log(f"WARN: {warning}")
    return 0 if result.get("status") != "error" else 1


def run_normalization(args: argparse.Namespace) -> int:
    paths = artifact_paths(Path(args.input_file).expanduser().resolve(), args.max_pages)
    chunk_path = require_artifact(paths["chunks"], "chunking")
    log(f"normalization: reading {chunk_path.relative_to(SCRIPT_DIR)}")
    started = time.time()
    if args.dry_run:
        result = extract_pdfs.normalize_dry_run(chunk_path)
    else:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not available to the NBME normalization stage")
        result = extract_pdfs.normalize_gemini_chunk_file(chunk_path, api_key)
    elapsed = round(time.time() - started, 2)
    log(
        "normalization: "
        f"{result.get('status')} in {elapsed}s; "
        f"{result.get('normalizedCount', 0)} normalized, "
        f"{result.get('failedCount', 0)} failed"
    )
    for warning in result.get("warnings", []) or []:
        log(f"WARN: {warning}")
    return 0 if result.get("status") != "error" else 1


def run_app_ready(args: argparse.Namespace) -> int:
    paths = artifact_paths(Path(args.input_file).expanduser().resolve(), args.max_pages)
    normalized_path = require_artifact(paths["normalized"], "normalization")
    log(f"app-ready conversion: reading {normalized_path.relative_to(SCRIPT_DIR)}")
    started = time.time()
    result = normalized_to_app_json.convert_normalized_file(normalized_path, dry_run=args.dry_run)
    elapsed = round(time.time() - started, 2)
    log(
        "app-ready conversion: "
        f"{result.get('status')} in {elapsed}s; "
        f"{result.get('question_count', 0)} question(s), "
        f"{result.get('skipped_count', 0)} skipped"
    )
    for warning in result.get("warnings", []) or []:
        log(f"WARN: {warning}")

    if args.dry_run or result.get("status") == "error":
        return 0 if result.get("status") != "error" else 1

    app_ready_path = paths["app_ready"]
    if app_ready_path.exists():
        pdf_path = require_artifact(paths["pdf"], "OCR")
        log("app-ready conversion: extracting figure/table review artifacts")
        manifest = nbme_extract_figures.extract_figures(
            pdf_path,
            max_pages=args.max_pages,
            contact_sheet=True,
            review_html=True,
        )
        manifest_path = SCRIPT_DIR / "figure_manifests" / f"{pdf_path.stem}_figure_manifest.json"
        nbme_extract_figures.build_suggested_figure_links(
            pdf_stem=pdf_path.stem,
            source_pdf=pdf_path.name,
            manifest_path=manifest_path,
            app_ready_path=app_ready_path,
            links_html=True,
        )
        summary = manifest.get("summary", {})
        log(
            "app-ready conversion: "
            f"{summary.get('figuresKept', 0)} figure candidate(s), "
            f"{summary.get('pagesProcessed', 0)} page(s) reviewed"
        )
        # v4.60: auto-attach high/medium-confidence stem images so the user
        # does not have to manually crop every figure through the cropper UI.
        # NBME PDFs put all images in question stems (user confirmed
        # explanations have no images), so we attach into q.images[] with
        # placement=stem and no Gemini routing call. Low-confidence
        # candidates still surface in the existing review HTML.
        attach_summary = nbme_extract_figures.auto_attach_figures_to_app_ready(
            pdf_stem=pdf_path.stem,
            manifest_path=manifest_path,
            app_ready_path=app_ready_path,
            min_confidence="medium",
        )
        log(
            "app-ready conversion: auto-attached "
            f"{attach_summary.get('figuresAttached', 0)} figure(s) to "
            f"{attach_summary.get('questionsModified', 0)} question(s); "
            f"{attach_summary.get('lowConfidenceSkipped', 0)} low-confidence skipped "
            f"(review HTML still available)"
        )
        for warn_msg in attach_summary.get("warnings", []) or []:
            log(f"WARN: {warn_msg}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch wrapper for existing NBME PDF pipeline")
    parser.add_argument("--stage", required=True, choices=["ocr", "chunking", "normalization", "app-ready"])
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-ocr", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.max_pages < 1:
        print("ERROR: --max-pages must be >= 1", file=sys.stderr, flush=True)
        return 2
    try:
        if args.stage == "ocr":
            return run_ocr(args)
        if args.stage == "chunking":
            return run_chunking(args)
        if args.stage == "normalization":
            return run_normalization(args)
        if args.stage == "app-ready":
            return run_app_ready(args)
        raise RuntimeError(f"Unsupported stage: {args.stage}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
