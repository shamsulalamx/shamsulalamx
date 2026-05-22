#!/usr/bin/env python3
"""
Mehlman Medical Mastery PDF → Step 2 Question Generator
Milestone 1: Deterministic extraction + chunking + dry-run output
Live Gemini generation: Milestone 2 (infrastructure wired, not yet validated)

Usage:
  python3 generate_mehlman_questions.py --dry-run
  python3 generate_mehlman_questions.py --extract-only
  python3 generate_mehlman_questions.py --extract-only --extract-assets
  python3 generate_mehlman_questions.py --chunk-only
  python3 generate_mehlman_questions.py --dry-run --extract-assets
  python3 generate_mehlman_questions.py --dry-run --max-chunks 2
  python3 generate_mehlman_questions.py --generate --questions-per-chunk 5
"""

import argparse
import hashlib
import json
import os
import re
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Infrastructure reuse ──────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "uworld-notes-question-generator"))
import generate_uworld_questions as _uw

# ── Optional imports (graceful degradation) ───────────────────────────────────
try:
    import pdfplumber as _pdfplumber
    _PDFPLUMBER = True
except ImportError:
    _PDFPLUMBER = False

try:
    import fitz as _fitz
    _FITZ = True
except ImportError:
    _FITZ = False

# ── Paths ─────────────────────────────────────────────────────────────────────
_BASE       = Path(__file__).parent
INPUT_DIR   = _BASE / "input_pdfs"
TEXT_DIR    = _BASE / "extracted_text"
FIG_DIR     = _BASE / "extracted_figures"
TABLE_DIR   = _BASE / "extracted_tables"
CHUNK_DIR   = _BASE / "output_json" / "chunks"
GEN_DIR     = _BASE / "output_json" / "generated"
DEBUG_DIR   = _BASE / "output_json" / "generated" / "debug"
APP_DIR     = _BASE / "output_json" / "app_ready"
REPORT_DIR  = _BASE / "reports"
PROMPTS_DIR = _BASE / "prompts"

# ── Patch UWorld module globals (resolved at call time) ───────────────────────
_uw.DEBUG_DIR   = DEBUG_DIR
_uw.PROMPT_FILE = PROMPTS_DIR / "mehlman_pdf_to_questions_prompt.txt"
_uw.REPORT_DIR  = REPORT_DIR

# ── sourceFormat patch ────────────────────────────────────────────────────────
_orig_build_app_ready = _uw.build_app_ready_json

def _mehlman_build_app_ready_json(
    source_stem: str,
    questions: List[Dict],
    warnings: List[str],
) -> Dict:
    result = _orig_build_app_ready(source_stem, questions, warnings)
    result["sourceFormat"] = "mehlman-pdf"
    return result

_uw.build_app_ready_json = _mehlman_build_app_ready_json

# ── Constants ─────────────────────────────────────────────────────────────────
_MIN_CHUNK = 8_000
_MAX_CHUNK = 12_000
_MIN_FIG_PX   = 80
_MAX_ASPECT   = 8.0
_HIGH_CONF_PX = 200


def _apply_output_dir(raw_path: str) -> Path:
    global TEXT_DIR, FIG_DIR, TABLE_DIR, CHUNK_DIR, GEN_DIR, DEBUG_DIR, APP_DIR, REPORT_DIR

    output_root = Path(raw_path).expanduser()
    if not output_root.is_absolute():
        output_root = (Path.cwd() / output_root).resolve()
    else:
        output_root = output_root.resolve()
    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"--output-dir must be a directory path: {output_root}")
    TEXT_DIR = output_root / "extracted_text"
    FIG_DIR = output_root / "extracted_figures"
    TABLE_DIR = output_root / "extracted_tables"
    CHUNK_DIR = output_root / "output_json" / "chunks"
    GEN_DIR = output_root / "output_json" / "generated"
    DEBUG_DIR = output_root / "output_json" / "generated" / "debug"
    APP_DIR = output_root / "output_json" / "app_ready"
    REPORT_DIR = output_root / "reports"
    _uw.DEBUG_DIR = DEBUG_DIR
    _uw.REPORT_DIR = REPORT_DIR
    return output_root


# ── Asset helpers ─────────────────────────────────────────────────────────────

def _figure_disposition(w: int, h: int) -> str:
    """Returns 'ignore', 'low', or 'high' confidence for a figure."""
    if w < _MIN_FIG_PX or h < _MIN_FIG_PX:
        return "ignore"
    aspect = max(w, h) / max(min(w, h), 1)
    if aspect > _MAX_ASPECT:
        return "ignore"
    if w >= _HIGH_CONF_PX and h >= _HIGH_CONF_PX:
        return "high"
    return "low"


def _table_to_markdown(table: List[List]) -> str:
    if not table:
        return ""
    rows = []
    for i, row in enumerate(table):
        cells = [str(c or "").replace("\n", " ").strip() for c in row]
        rows.append("| " + " | ".join(cells) + " |")
        if i == 0:
            rows.append("| " + " | ".join(["---"] * len(cells)) + " |")
    return "\n".join(rows)


# ── Per-page extraction ───────────────────────────────────────────────────────

def _crop_body(page) -> object:
    """Crop pdfplumber page to body zone, stripping top 8% and bottom 8%."""
    h = float(page.height)
    w = float(page.width)
    return page.crop((0, h * 0.08, w, h * 0.92))


def extract_pdf_pages(
    filepath: Path,
    extract_assets: bool,
    stats: Dict,
    max_pages: Optional[int] = None,
) -> List[Dict]:
    """
    Extract text per page with pdfplumber (body crop strips header/footer zones).
    Optionally extract figures via PyMuPDF and tables via pdfplumber.

    Returns list of page dicts: {pageNum, text, figures, tables, warnings}
    """
    if not _PDFPLUMBER:
        raise ImportError("pdfplumber is required: pip install pdfplumber")

    pages_data: List[Dict] = []
    seen_fig_hashes: set = set()

    fitz_doc = None
    if extract_assets:
        if _FITZ:
            fitz_doc = _fitz.open(str(filepath))
        else:
            _uw.warn("PyMuPDF not installed — figure extraction skipped. pip install pymupdf")

    with _pdfplumber.open(str(filepath)) as pdf:
        total_pages = len(pdf.pages)
        pages_to_process = pdf.pages[:max_pages] if max_pages else pdf.pages
        stats["totalSourcePages"] = total_pages
        stats["totalPages"] = len(pages_to_process)
        if max_pages:
            _uw.log(f"    {total_pages} pages detected; processing first {len(pages_to_process)} page(s)")
        else:
            _uw.log(f"    {total_pages} pages detected")

        for i, page in enumerate(pages_to_process):
            page_num = i + 1
            pg: Dict = {
                "pageNum": page_num,
                "text": "",
                "figures": [],
                "tables": [],
                "warnings": [],
            }

            # Text: body-crop to strip header/footer zones
            body = _crop_body(page)
            pg["text"] = body.extract_text(x_tolerance=2, y_tolerance=2) or ""

            if extract_assets:
                # ── Table extraction (lattice/lines only — avoids false positives) ──
                try:
                    tbls = body.extract_tables(
                        {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
                    )
                    for ti, tbl in enumerate(tbls or []):
                        if not tbl or len(tbl) < 2:
                            continue
                        md = _table_to_markdown(tbl)
                        nrows = len(tbl)
                        ncols = max(len(r) for r in tbl) if tbl else 0
                        tbl_name = f"{filepath.stem}_p{page_num}_t{ti + 1}.json"
                        tbl_path = TABLE_DIR / tbl_name
                        tbl_path.write_text(
                            json.dumps({"rows": tbl}, indent=2), encoding="utf-8"
                        )
                        pg["tables"].append(
                            {
                                "filename": tbl_name,
                                "rows": nrows,
                                "cols": ncols,
                                "markdown": md,
                            }
                        )
                        stats["tablesDetected"] = stats.get("tablesDetected", 0) + 1
                        stats["tablesExtracted"] = stats.get("tablesExtracted", 0) + 1
                except Exception as exc:
                    pg["warnings"].append(f"table p{page_num}: {exc}")

                # ── Figure extraction via PyMuPDF ─────────────────────────────
                if fitz_doc is not None:
                    try:
                        fitz_page = fitz_doc[i]
                        for img_info in fitz_page.get_images(full=True):
                            xref = img_info[0]
                            pix = _fitz.Pixmap(fitz_doc, xref)
                            w, h = pix.width, pix.height
                            disp = _figure_disposition(w, h)
                            stats["figuresDetected"] = stats.get("figuresDetected", 0) + 1
                            if disp == "ignore":
                                stats["figuresIgnored"] = stats.get("figuresIgnored", 0) + 1
                                pix = None
                                continue
                            if pix.n - pix.alpha > 3:
                                pix = _fitz.Pixmap(_fitz.csRGB, pix)
                            img_bytes = pix.tobytes("png")
                            img_hash = hashlib.md5(img_bytes).hexdigest()[:8]
                            if img_hash in seen_fig_hashes:
                                stats["figuresIgnored"] = (
                                    stats.get("figuresIgnored", 0) + 1
                                )
                                pix = None
                                continue
                            seen_fig_hashes.add(img_hash)
                            fig_name = f"{filepath.stem}_p{page_num}_{img_hash}.png"
                            (FIG_DIR / fig_name).write_bytes(img_bytes)
                            pg["figures"].append(
                                {
                                    "filename": fig_name,
                                    "width": w,
                                    "height": h,
                                    "confidence": disp,
                                }
                            )
                            stats["figuresKept"] = stats.get("figuresKept", 0) + 1
                            pix = None
                    except Exception as exc:
                        pg["warnings"].append(f"figure p{page_num}: {exc}")

            pages_data.append(pg)

    if fitz_doc is not None:
        fitz_doc.close()

    return pages_data


# ── Long-PDF chunking ─────────────────────────────────────────────────────────

def split_pages_into_chunks(
    pages_data: List[Dict],
    min_chars: int = _MIN_CHUNK,
    max_chars: int = _MAX_CHUNK,
) -> List[Dict]:
    """
    Merge per-page text into chunks of min_chars–max_chars.
    Splits at page boundaries when possible; falls back to paragraph splits
    when a single page exceeds max_chars. Preserves pageStart/pageEnd metadata.
    """
    chunks: List[Dict] = []
    chunk_id = 0

    buf_text  = ""
    buf_start: Optional[int] = None
    buf_end:   Optional[int] = None
    buf_figs:  List[Dict] = []
    buf_tbls:  List[Dict] = []
    buf_warns: List[str]  = []

    def _emit() -> None:
        nonlocal buf_text, buf_start, buf_end, buf_figs, buf_tbls, buf_warns, chunk_id
        if not buf_text.strip():
            return
        chunk_id += 1
        chunks.append(
            {
                "chunkId":    chunk_id,
                "sourceFile": "",   # filled by caller
                "pageStart":  buf_start,
                "pageEnd":    buf_end,
                "charCount":  len(buf_text),
                "text":       buf_text,
                "figures":    list(buf_figs),
                "tables":     list(buf_tbls),
                "warnings":   list(buf_warns),
            }
        )
        buf_text  = ""
        buf_start = None
        buf_end   = None
        buf_figs  = []
        buf_tbls  = []
        buf_warns = []

    def _emit_para_chunk(text: str, pn: int, figs, tbls, warns) -> None:
        """Emit a single paragraph-split chunk (single-page overflow)."""
        nonlocal chunk_id
        chunk_id += 1
        chunks.append(
            {
                "chunkId":    chunk_id,
                "sourceFile": "",
                "pageStart":  pn,
                "pageEnd":    pn,
                "charCount":  len(text),
                "text":       text,
                "figures":    list(figs),
                "tables":     list(tbls),
                "warnings":   list(warns),
            }
        )

    for pg in pages_data:
        pn   = pg["pageNum"]
        pt   = pg["text"].strip()
        figs = pg.get("figures", [])
        tbls = pg.get("tables", [])
        warns = pg.get("warnings", [])

        if not pt:
            continue

        if buf_start is None:
            buf_start = pn

        candidate = (buf_text + "\n\n" + pt).strip() if buf_text else pt

        if len(candidate) > max_chars and buf_text:
            # Current buffer full — emit before adding this page
            _emit()
            buf_text  = pt
            buf_start = pn
            buf_end   = pn
            buf_figs  = list(figs)
            buf_tbls  = list(tbls)
            buf_warns = list(warns)
        else:
            buf_text = candidate
            buf_end  = pn
            buf_figs.extend(figs)
            buf_tbls.extend(tbls)
            buf_warns.extend(warns)

        # Single-page text exceeds max — split at paragraphs within the page
        if len(buf_text) > max_chars and buf_start == buf_end == pn:
            paras = [p.strip() for p in re.split(r"\n{2,}", buf_text) if p.strip()]
            sub_buf  = ""
            sub_figs: List[Dict] = list(figs)
            sub_tbls: List[Dict] = list(tbls)
            for para in paras:
                if len(sub_buf) + len(para) + 2 <= max_chars:
                    sub_buf = (sub_buf + "\n\n" + para).strip() if sub_buf else para
                else:
                    if sub_buf:
                        _emit_para_chunk(sub_buf, pn, sub_figs, sub_tbls, warns)
                        sub_figs = []
                        sub_tbls = []
                    sub_buf = para
            buf_text  = sub_buf
            buf_start = pn
            buf_end   = pn
            buf_figs  = sub_figs
            buf_tbls  = sub_tbls

    _emit()
    return chunks


# ── Asset markers ─────────────────────────────────────────────────────────────

def _inject_asset_markers(chunk: Dict) -> str:
    """Prepend [DETECTED FIGURE/TABLE] markers to chunk text for Gemini prompts."""
    markers: List[str] = []
    for fig in chunk.get("figures", []):
        markers.append(
            f"[DETECTED FIGURE: {fig['filename']} | "
            f"{fig['width']}×{fig['height']} px | confidence: {fig['confidence']}]"
        )
    for tbl in chunk.get("tables", []):
        markers.append(
            f"[DETECTED TABLE: {tbl['filename']} | "
            f"{tbl['rows']} rows × {tbl['cols']} cols]"
        )
        markers.append(tbl.get("markdown", ""))

    if not markers:
        return chunk["text"]
    return "\n".join(markers) + "\n\n" + chunk["text"]


# ── Stats skeleton ────────────────────────────────────────────────────────────

def _empty_stats() -> Dict:
    return {
        "totalPages":         0,
        "totalTextChars":     0,
        "chunksCreated":      0,
        "chunksProcessed":    0,
        "figuresDetected":    0,
        "figuresKept":        0,
        "figuresIgnored":     0,
        "tablesDetected":     0,
        "tablesExtracted":    0,
        "questionsGenerated": 0,
        "validationFailures": 0,
        "repairsSucceeded":   0,
        "repairFailures":     0,
        "warnings":           [],
        "chunkStats":         [],
    }


# ── Core processor ────────────────────────────────────────────────────────────

def process_pdf(
    filepath: Path,
    *,
    mode: str,                     # "extract_only" | "chunk_only" | "dry_run" | "generate"
    extract_assets: bool,
    max_pages: Optional[int],
    max_chunks: Optional[int],
    questions_per_chunk: int,
    resume: bool,
    report_data: Dict,
) -> None:
    t_start = time.time()
    stem    = filepath.stem
    artifact_stem = f"{stem}_p001_p{max_pages:03d}" if max_pages else stem
    _uw.log(f"Processing: {filepath.name}  [mode={mode}]")
    stats   = _empty_stats()

    text_path  = TEXT_DIR  / f"{artifact_stem}_text.json"
    chunk_path = CHUNK_DIR / f"{artifact_stem}_chunks.json"

    # ── Stage 1: Per-page text (and asset) extraction ─────────────────────────
    if mode == "chunk_only":
        if not text_path.exists():
            _uw.warn(
                f"  {text_path.name} not found — run --extract-only first. Skipping."
            )
            report_data["files"][filepath.name] = {
                "status": "skipped",
                "reason": "missing_extracted_text",
            }
            return
        _uw.log(f"  Stage 1: Loading existing text → {text_path.name}")
        pages_data = json.loads(text_path.read_text(encoding="utf-8"))
        stats["totalPages"] = len(pages_data)
    else:
        if resume and text_path.exists():
            _uw.log(f"  Stage 1: [RESUME] Reusing {text_path.name}")
            pages_data = json.loads(text_path.read_text(encoding="utf-8"))
            stats["totalPages"] = len(pages_data)
        else:
            _uw.log(f"  Stage 1: Extracting pages from {filepath.name}…")
            pages_data = extract_pdf_pages(filepath, extract_assets, stats, max_pages=max_pages)
            text_path.write_text(
                json.dumps(pages_data, indent=2), encoding="utf-8"
            )
            _uw.log(f"    → {text_path.name} ({stats['totalPages']} pages)")

    total_chars = sum(len(pg["text"]) for pg in pages_data)
    stats["totalTextChars"] = total_chars
    _uw.log(f"    Total body chars: {total_chars:,}")

    if total_chars < 100:
        msg = "very_low_text: <100 chars extracted — PDF may be image-only or encrypted"
        _uw.warn(f"  {msg}")
        stats["warnings"].append(msg)

    if mode == "extract_only":
        elapsed = round(time.time() - t_start, 1)
        report_data["files"][filepath.name] = {
            "status":          "extracted",
            "totalPages":      stats["totalPages"],
            "totalTextChars":  total_chars,
            "figuresDetected": stats.get("figuresDetected", 0),
            "figuresKept":     stats.get("figuresKept", 0),
            "figuresIgnored":  stats.get("figuresIgnored", 0),
            "tablesDetected":  stats.get("tablesDetected", 0),
            "tablesExtracted": stats.get("tablesExtracted", 0),
            "warnings":        stats["warnings"],
            "elapsedSeconds":  elapsed,
            "outputPaths":     {"extractedText": str(text_path)},
        }
        return

    # ── Stage 2: Chunking ─────────────────────────────────────────────────────
    if resume and chunk_path.exists():
        _uw.log(f"  Stage 2: [RESUME] Reusing {chunk_path.name}")
        manifest   = json.loads(chunk_path.read_text(encoding="utf-8"))
        all_chunks = manifest["chunks"]
        stats["chunksCreated"] = len(all_chunks)
    else:
        _uw.log(f"  Stage 2: Chunking ({_MIN_CHUNK:,}–{_MAX_CHUNK:,} chars/chunk)…")
        all_chunks = split_pages_into_chunks(pages_data)
        for c in all_chunks:
            c["sourceFile"] = filepath.name
        stats["chunksCreated"] = len(all_chunks)
        manifest = {
            "sourceFile":  filepath.name,
            "totalPages":  stats["totalPages"],
            "totalChars":  total_chars,
            "chunkCount":  len(all_chunks),
            "minChunkTarget": _MIN_CHUNK,
            "maxChunkTarget": _MAX_CHUNK,
            "chunks":      all_chunks,
        }
        chunk_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        _uw.log(f"    {len(all_chunks)} chunk(s) → {chunk_path.name}")

    if mode == "chunk_only":
        elapsed = round(time.time() - t_start, 1)
        report_data["files"][filepath.name] = {
            "status":         "chunked",
            "totalPages":     stats["totalPages"],
            "totalTextChars": total_chars,
            "chunksCreated":  stats["chunksCreated"],
            "warnings":       stats["warnings"],
            "elapsedSeconds": elapsed,
            "outputPaths":    {
                "extractedText": str(text_path),
                "chunks":        str(chunk_path),
            },
        }
        return

    # ── Stage 3: Question generation ──────────────────────────────────────────
    chunks_to_process = all_chunks[:max_chunks] if max_chunks else all_chunks
    stats["chunksProcessed"] = len(chunks_to_process)
    _uw.log(
        f"  Stage 3: {'[DRY-RUN]' if mode == 'dry_run' else '[GENERATE]'} "
        f"{len(chunks_to_process)} chunk(s), {questions_per_chunk} q/chunk"
    )

    all_questions: List[Dict] = []
    gen_stats = {
        "validationFailures": 0,
        "retries":            0,
        "repairsSucceeded":   0,
        "repairFailures":     0,
    }

    for ci, chunk in enumerate(chunks_to_process):
        c_stat: Dict = {
            "chunkId":    chunk["chunkId"],
            "pageStart":  chunk["pageStart"],
            "pageEnd":    chunk["pageEnd"],
            "charCount":  chunk["charCount"],
        }

        if mode == "dry_run":
            placeholder_qs = [
                _uw._placeholder_question(len(all_questions) + i + 1)
                for i in range(questions_per_chunk)
            ]
            all_questions.extend(placeholder_qs)
            c_stat["status"]             = "dry-run"
            c_stat["questionsGenerated"] = questions_per_chunk
        else:
            chunk_text = _inject_asset_markers(chunk)
            try:
                qs, chunk_warns = _uw.call_gemini_with_retry(
                    chunk_text, questions_per_chunk, chunk["chunkId"], gen_stats
                )
                qs = _uw.renumber_questions(qs, len(all_questions))
                all_questions.extend(qs)
                stats["warnings"].extend(chunk_warns)
                c_stat["status"]             = "ok"
                c_stat["questionsGenerated"] = len(qs)
                _uw.log(f"    Chunk {chunk['chunkId']}: {len(qs)} question(s) generated")
                time.sleep(1)
            except json.JSONDecodeError as exc:
                msg = f"chunk {chunk['chunkId']} JSON parse error: {exc}"
                _uw.warn(msg)
                stats["warnings"].append(msg)
                c_stat["status"] = "json_error"
                c_stat["error"]  = str(exc)
            except Exception as exc:
                msg = f"chunk {chunk['chunkId']} failed: {exc}"
                _uw.warn(msg)
                stats["warnings"].append(msg)
                c_stat["status"] = "error"
                c_stat["error"]  = str(exc)

        stats["chunkStats"].append(c_stat)

    if mode == "dry_run":
        stats["warnings"].append(
            "dry-run: questions are placeholders, not Gemini-generated"
        )

    stats["questionsGenerated"] = len(all_questions)
    stats["validationFailures"] = gen_stats["validationFailures"]
    stats["repairsSucceeded"]   = gen_stats["repairsSucceeded"]
    stats["repairFailures"]     = gen_stats["repairFailures"]

    dup_warns = _uw.check_duplicate_stems(all_questions)
    if dup_warns:
        stats["warnings"].extend(dup_warns)

    # ── Stage 4: Write app-ready JSON ─────────────────────────────────────────
    app_json = _uw.build_app_ready_json(artifact_stem, all_questions, stats["warnings"])
    app_json["sourceFile"] = filepath.name
    app_json["metadata"] = {
        **(app_json.get("metadata") if isinstance(app_json.get("metadata"), dict) else {}),
        "sourceFile": filepath.name,
        "sourceStem": stem,
        "artifactStem": artifact_stem,
        "pageLimit": max_pages,
    }
    app_path = APP_DIR / f"{artifact_stem}_app_ready.json"
    app_path.write_text(json.dumps(app_json, indent=2), encoding="utf-8")
    _uw.log(f"  App-ready → {app_path.name} ({len(all_questions)} questions)")

    if mode != "dry_run":
        gen_path = GEN_DIR / f"{artifact_stem}_generated.json"
        gen_path.write_text(json.dumps(all_questions, indent=2), encoding="utf-8")

    elapsed = round(time.time() - t_start, 1)
    report_data["files"][filepath.name] = {
        "status":             "ok",
        "totalPages":         stats["totalPages"],
        "totalSourcePages":   stats.get("totalSourcePages", stats["totalPages"]),
        "totalTextChars":     stats["totalTextChars"],
        "chunksCreated":      stats["chunksCreated"],
        "chunksProcessed":    stats["chunksProcessed"],
        "figuresDetected":    stats.get("figuresDetected", 0),
        "figuresKept":        stats.get("figuresKept", 0),
        "figuresIgnored":     stats.get("figuresIgnored", 0),
        "tablesDetected":     stats.get("tablesDetected", 0),
        "tablesExtracted":    stats.get("tablesExtracted", 0),
        "questionsGenerated": stats["questionsGenerated"],
        "validationFailures": stats["validationFailures"],
        "repairsSucceeded":   stats["repairsSucceeded"],
        "repairFailures":     stats["repairFailures"],
        "warnings":           stats["warnings"],
        "chunkStats":         stats["chunkStats"],
        "elapsedSeconds":     elapsed,
        "dryRun":             (mode == "dry_run"),
        "outputPaths": {
            "appReady":      str(app_path),
            "chunks":        str(chunk_path),
            "extractedText": str(text_path),
        },
    }


# ── Discover helpers ──────────────────────────────────────────────────────────

def _discover_pdfs() -> List[Path]:
    if not INPUT_DIR.exists():
        return []
    return sorted(
        f for f in INPUT_DIR.iterdir()
        if f.is_file() and f.suffix.lower() == ".pdf"
    )


def _discover_extracted_texts() -> List[Path]:
    if not TEXT_DIR.exists():
        return []
    return sorted(f for f in TEXT_DIR.iterdir() if f.name.endswith("_text.json"))


def _stem_from_text_path(p: Path) -> str:
    return p.stem.removesuffix("_text")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mehlman Medical Mastery PDF → Step 2 Question Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Modes (mutually exclusive):
              --extract-only     Extract text (and optionally assets) per page; no questions.
              --chunk-only       Build chunk manifests from existing extracted text; no questions.
              --dry-run          Full pipeline with placeholder questions (no Gemini).
              --generate         Full pipeline with live Gemini generation (Milestone 2).

            Examples:
              python3 generate_mehlman_questions.py --dry-run
              python3 generate_mehlman_questions.py --extract-only --extract-assets
              python3 generate_mehlman_questions.py --chunk-only
              python3 generate_mehlman_questions.py --dry-run --extract-assets --max-chunks 2
              python3 generate_mehlman_questions.py --generate --questions-per-chunk 5
              python3 generate_mehlman_questions.py --dry-run --resume
              python3 generate_mehlman_questions.py --dry-run --force
            """
        ),
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--extract-only",
        action="store_true",
        help="Extract text per page and save to extracted_text/; stop before chunking.",
    )
    mode_group.add_argument(
        "--chunk-only",
        action="store_true",
        help="Build chunk manifests from existing extracted_text/ files; no questions.",
    )
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Full pipeline with placeholder questions; no Gemini API calls.",
    )
    mode_group.add_argument(
        "--generate",
        action="store_true",
        help="Full pipeline with live Gemini generation. Requires GEMINI_API_KEY.",
    )

    parser.add_argument(
        "--extract-assets",
        action="store_true",
        help="Also extract figures (PyMuPDF) and tables (pdfplumber) alongside text.",
    )
    parser.add_argument(
        "--input-file",
        default="",
        help="Process one selected PDF instead of every PDF in input_pdfs/.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Optional output root. Writes extracted assets, app-ready JSON, generated files, and reports under this directory.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        metavar="N",
        help="Limit processing to the first N pages of each PDF.",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=None,
        metavar="N",
        help="Limit the number of chunks processed per file (useful for testing).",
    )
    parser.add_argument(
        "--questions-per-chunk",
        type=int,
        default=5,
        metavar="N",
        help="Questions to generate per chunk (default: 5).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing extracted_text/ and chunks/ files when present.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore existing files and reprocess from scratch.",
    )

    args = parser.parse_args()

    if args.resume and args.force:
        parser.error("--resume and --force are mutually exclusive.")
    try:
        output_root = _apply_output_dir(args.output_dir) if args.output_dir else None
    except ValueError as exc:
        parser.error(str(exc))

    # Default mode when none specified
    if not any([args.extract_only, args.chunk_only, args.dry_run, args.generate]):
        args.dry_run = True

    if args.generate and not os.environ.get("GEMINI_API_KEY", "").strip():
        parser.error(
            "--generate requires GEMINI_API_KEY to be set.\n"
            "  export GEMINI_API_KEY=your_key_here"
        )

    if args.generate and not (PROMPTS_DIR / "mehlman_pdf_to_questions_prompt.txt").exists():
        parser.error(
            f"Prompt file not found: {PROMPTS_DIR / 'mehlman_pdf_to_questions_prompt.txt'}"
        )

    # Determine mode string
    if args.extract_only:
        mode = "extract_only"
    elif args.chunk_only:
        mode = "chunk_only"
    elif args.generate:
        mode = "generate"
    else:
        mode = "dry_run"

    _uw.log("=" * 64)
    _uw.log("Mehlman PDF → Question Generator")
    _uw.log(f"  Mode:                 {mode}")
    _uw.log(f"  Extract assets:       {args.extract_assets}")
    _uw.log(f"  Input file:           {args.input_file or 'input_pdfs/*.pdf'}")
    if output_root:
        _uw.log(f"  Output root:          {output_root}")
    _uw.log(f"  Max pages:            {args.max_pages or 'unlimited'}")
    _uw.log(f"  Max chunks:           {args.max_chunks or 'unlimited'}")
    _uw.log(f"  Questions per chunk:  {args.questions_per_chunk}")
    _uw.log(f"  Resume:               {args.resume}")
    _uw.log(f"  Force:                {args.force}")
    _uw.log("=" * 64)

    # Create output dirs
    for d in (
        TEXT_DIR, FIG_DIR, TABLE_DIR,
        CHUNK_DIR, GEN_DIR, DEBUG_DIR, APP_DIR, REPORT_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)

    # Determine input files based on mode
    if mode == "chunk_only":
        text_files = _discover_extracted_texts()
        if not text_files:
            _uw.log(
                "No extracted text files found in extracted_text/. "
                "Run --extract-only first."
            )
            _uw.write_report(
                {"status": "no_input_files", "mode": mode, "files": {}},
                prefix="mehlman_generation_report",
            )
            return
        # Build fake filepath objects pointing to input_pdfs/ for report keys
        input_files = [INPUT_DIR / (_stem_from_text_path(t) + ".pdf") for t in text_files]
        _uw.log(
            f"Found {len(text_files)} extracted text file(s): "
            f"{[t.name for t in text_files]}"
        )
    else:
        input_files = [Path(args.input_file).expanduser().resolve()] if args.input_file else _discover_pdfs()
        if not input_files:
            _uw.log(
                f"No PDF files found in {INPUT_DIR}. "
                "Drop Mehlman PDFs into input_pdfs/ and re-run."
            )
            _uw.write_report(
                {"status": "no_input_files", "mode": mode, "files": {}},
                prefix="mehlman_generation_report",
            )
            return
        _uw.log(
            f"Found {len(input_files)} PDF(s): {[f.name for f in input_files]}"
        )

    report_data: Dict = {
        "runTimestamp":      datetime.now().isoformat(),
        "model":             _uw.GEMINI_MODEL,
        "mode":              mode,
        "extractAssets":     args.extract_assets,
        "maxChunks":         args.max_chunks,
        "questionsPerChunk": args.questions_per_chunk,
        "resume":            args.resume,
        "inputFiles":        [f.name for f in input_files],
        "files":             {},
    }

    t_total = time.time()
    for filepath in input_files:
        try:
            process_pdf(
                filepath,
                mode=mode,
                extract_assets=args.extract_assets,
                max_pages=args.max_pages,
                max_chunks=args.max_chunks,
                questions_per_chunk=args.questions_per_chunk,
                resume=args.resume,
                report_data=report_data,
            )
        except Exception as exc:
            _uw.warn(f"Fatal error on {filepath.name}: {exc}")
            report_data["files"][filepath.name] = {
                "status": "error",
                "error":  str(exc),
            }

    report_data["totalElapsedSeconds"] = round(time.time() - t_total, 1)
    _uw.write_report(report_data, prefix="mehlman_generation_report")
    _uw.log("Done.")


if __name__ == "__main__":
    main()
