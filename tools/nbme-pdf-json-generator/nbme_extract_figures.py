#!/usr/bin/env python3
"""
NBME rendered-page figure candidate extractor.

Milestone 1 utility only:
  - crops likely visual candidates from rendered PDF pages
  - writes a review manifest
  - writes a contact sheet

This script does not modify raw text, chunks, normalized JSON, app-ready JSON,
index.html, or importer behavior. Candidate-to-question association is only a
weak review hint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

try:
    import fitz  # PyMuPDF
except Exception as exc:
    print(
        "ERROR: PyMuPDF is required for PDF rendering.\n"
        "Install with: python3 -m pip install pymupdf",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

try:
    import cv2
    import numpy as np
except Exception as exc:
    print(
        "ERROR: OpenCV is required for rendered-page figure detection.\n"
        "Install with: python3 -m pip install opencv-python",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

try:
    from PIL import Image, ImageDraw
except Exception as exc:
    print(
        "ERROR: Pillow is required for crop/contact-sheet writing.\n"
        "Install with: python3 -m pip install pillow",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
EXTRACTED_DIR = SCRIPT_DIR / "extracted_figures"
MANIFEST_DIR = SCRIPT_DIR / "figure_manifests"
DEFAULT_DPI = 200

QUESTION_LINE_RE = re.compile(r"(?m)^\s*\*?\s*(\d{1,3})\.\s+")
ITEM_RE = re.compile(r"\bItem\s+(\d{1,3})\s+of\s+\d{1,3}\b", re.IGNORECASE)
IMAGE_PHRASE_RE = re.compile(
    r"\b("
    r"figure|photograph|photo|image|shown|pictured|radiograph|x-?ray|"
    r"chest x-?ray|ecg|ekg|electrocardiogram|ct|mri|ultrasound|"
    r"graph|curve|plot|histology|biopsy|fundoscopic"
    r")\b",
    re.IGNORECASE,
)
ANSWER_CHOICE_WORD_RE = re.compile(r"^[A-F][\.\)]?$")


@dataclass
class PageTextHints:
    text: str = ""
    question_numbers: list[int] = field(default_factory=list)
    chunk_question_numbers: list[int] = field(default_factory=list)
    image_phrase: bool = False
    answer_choice_y: list[float] = field(default_factory=list)
    source: str = "none"


@dataclass
class Candidate:
    page: int
    bbox: tuple[int, int, int, int]
    score: float
    reasons: list[str]
    suggested_question: Optional[int]
    confidence: str
    needs_review: bool
    width: int
    height: int
    crop_hash: str = ""
    file_path: str = ""
    figure_id: str = ""


def ensure_dirs() -> None:
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)


def _rel(path: Path) -> str:
    return str(path.relative_to(SCRIPT_DIR))


def _resolve_pdf(path_text: str) -> Path:
    pdf_path = Path(path_text)
    if not pdf_path.is_absolute():
        pdf_path = SCRIPT_DIR / pdf_path
    return pdf_path.resolve()


def _render_page(page: fitz.Page, dpi: int) -> np.ndarray:
    zoom = dpi / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    return arr.copy()


def _extract_page_text_hints(pdf_path: Path, max_pages: Optional[int], warnings: list[str]) -> dict[int, PageTextHints]:
    hints: dict[int, PageTextHints] = {}
    try:
        import pdfplumber
    except Exception:
        warnings.append(
            "pdfplumber unavailable; text-based question hints disabled. "
            "Install with: python3 -m pip install pdfplumber"
        )
        return hints

    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = pdf.pages[:max_pages] if max_pages else pdf.pages
            for idx, page in enumerate(pages, start=1):
                text = page.extract_text() or ""
                qnums = [int(m.group(1)) for m in QUESTION_LINE_RE.finditer(text)]
                item_nums = [int(m.group(1)) for m in ITEM_RE.finditer(text)]
                for n in item_nums:
                    if n not in qnums:
                        qnums.append(n)
                answer_y: list[float] = []
                try:
                    for word in page.extract_words() or []:
                        token = str(word.get("text", "")).strip()
                        if ANSWER_CHOICE_WORD_RE.match(token):
                            answer_y.append(float(word.get("top", 0.0)))
                except Exception:
                    answer_y = []
                hints[idx] = PageTextHints(
                    text=text,
                    question_numbers=sorted(set(qnums)),
                    image_phrase=bool(IMAGE_PHRASE_RE.search(text)),
                    answer_choice_y=answer_y,
                    source="native-pdf-text" if text.strip() else "none",
                )
    except Exception as exc:
        warnings.append(f"Could not read native PDF text hints: {exc}")

    return hints


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _merge_chunk_page_hints(pdf_stem: str, hints: dict[int, PageTextHints], warnings: list[str]) -> None:
    """Weakly map existing chunk raw text back to raw page sections, if available."""
    raw_path = SCRIPT_DIR / "output_json" / "raw_text" / f"{pdf_stem}_raw.txt"
    chunk_path = SCRIPT_DIR / "output_json" / "chunks" / f"{pdf_stem}_chunks.json"
    if not raw_path.exists() or not chunk_path.exists():
        return

    try:
        raw = raw_path.read_text(encoding="utf-8")
        chunk_payload = json.loads(chunk_path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"Could not read existing chunk/raw-text hints: {exc}")
        return

    page_texts: dict[int, str] = {}
    parts = re.split(r"(?m)^## Page (\d+)\s*$", raw)
    for i in range(1, len(parts), 2):
        try:
            page_num = int(parts[i])
        except ValueError:
            continue
        if i + 1 < len(parts):
            page_texts[page_num] = _norm_text(parts[i + 1])

    for chunk in chunk_payload.get("chunks", []):
        q_num = chunk.get("questionNumber")
        raw_text = _norm_text(chunk.get("rawText", ""))
        if not isinstance(q_num, int) or not raw_text:
            continue
        snippet = raw_text[:220]
        if len(snippet) < 60:
            continue
        for page_num, page_text in page_texts.items():
            if snippet in page_text or raw_text[:90] in page_text:
                hint = hints.setdefault(page_num, PageTextHints())
                if q_num not in hint.chunk_question_numbers:
                    hint.chunk_question_numbers.append(q_num)
                if hint.source == "none":
                    hint.source = "existing-raw-text"
                break

    for hint in hints.values():
        hint.chunk_question_numbers.sort()


def _non_background_mask(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    dark = gray < 236
    colored = (saturation > 32) & (value < 252)
    mask = np.where(dark | colored, 255, 0).astype(np.uint8)
    return mask


def _expanded(box: tuple[int, int, int, int], margin: int, width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (
        max(0, x0 - margin),
        max(0, y0 - margin),
        min(width, x1 + margin),
        min(height, y1 + margin),
    )


def _intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _merge_boxes(
    boxes: list[tuple[int, int, int, int]],
    page_w: int,
    page_h: int,
    margin: int,
) -> list[tuple[int, int, int, int]]:
    merged = list(boxes)
    changed = True
    while changed:
        changed = False
        next_boxes: list[tuple[int, int, int, int]] = []
        used = [False] * len(merged)
        for i, box in enumerate(merged):
            if used[i]:
                continue
            current = box
            used[i] = True
            did_merge = True
            while did_merge:
                did_merge = False
                current_expanded = _expanded(current, margin, page_w, page_h)
                for j, other in enumerate(merged):
                    if used[j]:
                        continue
                    if _intersects(current_expanded, other):
                        current = (
                            min(current[0], other[0]),
                            min(current[1], other[1]),
                            max(current[2], other[2]),
                            max(current[3], other[3]),
                        )
                        used[j] = True
                        did_merge = True
                        changed = True
            next_boxes.append(current)
        merged = next_boxes
    return merged


def _component_stats(mask: np.ndarray) -> dict[str, float]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    areas = []
    heights = []
    widths = []
    for idx in range(1, count):
        area = float(stats[idx, cv2.CC_STAT_AREA])
        if area < 3:
            continue
        areas.append(area)
        widths.append(float(stats[idx, cv2.CC_STAT_WIDTH]))
        heights.append(float(stats[idx, cv2.CC_STAT_HEIGHT]))
    if not areas:
        return {
            "count": 0.0,
            "max_area": 0.0,
            "median_height": 0.0,
            "median_width": 0.0,
        }
    return {
        "count": float(len(areas)),
        "max_area": float(max(areas)),
        "median_height": float(np.median(heights)),
        "median_width": float(np.median(widths)),
    }


def _box_features(rgb: np.ndarray, mask: np.ndarray, box: tuple[int, int, int, int]) -> dict[str, float]:
    x0, y0, x1, y1 = box
    crop = rgb[y0:y1, x0:x1]
    crop_mask = mask[y0:y1, x0:x1]
    area = max(1, crop_mask.shape[0] * crop_mask.shape[1])
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 80, 180)
    stats = _component_stats(crop_mask)
    return {
        "ink_density": float(np.count_nonzero(crop_mask) / area),
        "edge_density": float(np.count_nonzero(edges) / area),
        "component_count": stats["count"],
        "component_max_area_ratio": float(stats["max_area"] / area),
        "component_median_height": stats["median_height"],
        "component_median_width": stats["median_width"],
    }


def _is_text_only(features: dict[str, float], w: int, h: int, dpi: int) -> bool:
    scale = dpi / DEFAULT_DPI
    many_small_components = (
        features["component_count"] >= 45
        and features["component_median_height"] <= 18 * scale
        and features["component_max_area_ratio"] < 0.035
    )
    sparse_large_text_block = (
        features["ink_density"] < 0.09
        and features["component_max_area_ratio"] < 0.025
        and h < 360 * scale
        and w > 260 * scale
    )
    return many_small_components or sparse_large_text_block


def _score_candidate(
    page_w: int,
    page_h: int,
    box: tuple[int, int, int, int],
    features: dict[str, float],
) -> tuple[float, list[str]]:
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    area_ratio = (w * h) / max(1, page_w * page_h)
    aspect = w / max(1, h)

    size_score = min(1.0, area_ratio / 0.055)
    density = features["ink_density"]
    if density < 0.015:
        density_score = 0.0
    elif density > 0.85:
        density_score = 0.25
    else:
        density_score = min(1.0, density / 0.18)
    edge_score = min(1.0, features["edge_density"] / 0.09)
    component_score = min(1.0, features["component_max_area_ratio"] / 0.12)
    aspect_penalty = 0.0 if aspect > 9.0 or aspect < 0.08 else 1.0

    score = (
        0.35 * size_score
        + 0.25 * density_score
        + 0.20 * edge_score
        + 0.20 * component_score
    ) * aspect_penalty

    reasons = []
    if area_ratio >= 0.008:
        reasons.append("major non-text visual region")
    if features["component_max_area_ratio"] >= 0.05:
        reasons.append("contains large connected visual component")
    if features["edge_density"] >= 0.025:
        reasons.append("contains dense visual edges")
    if density >= 0.12:
        reasons.append("visually dense crop")
    return round(float(score), 4), reasons


def _detect_boxes(rgb: np.ndarray, dpi: int, conservative: bool) -> tuple[list[tuple[int, int, int, int]], int]:
    page_h, page_w = rgb.shape[:2]
    mask = _non_background_mask(rgb)

    top_cut = int(page_h * 0.075)
    bottom_cut = int(page_h * 0.925)
    mask[:top_cut, :] = 0
    mask[bottom_cut:, :] = 0

    close_scale = dpi / DEFAULT_DPI
    close_size = int(19 * close_scale if conservative else 15 * close_scale)
    close_size = max(9, close_size | 1)
    open_size = max(3, int(3 * close_scale) | 1)

    closed = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (close_size, close_size)),
        iterations=2 if conservative else 1,
    )
    opened = cv2.morphologyEx(
        closed,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (open_size, open_size)),
        iterations=1,
    )

    contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    raw_boxes = []
    min_area = page_w * page_h * (0.0018 if conservative else 0.0012)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h < min_area:
            continue
        raw_boxes.append((x, y, x + w, y + h))

    merged = _merge_boxes(
        raw_boxes,
        page_w,
        page_h,
        margin=max(18, int(24 * dpi / DEFAULT_DPI)),
    )
    return merged, len(raw_boxes)


def _filter_and_score_boxes(
    rgb: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    page_num: int,
    dpi: int,
    conservative: bool,
    text_hint: PageTextHints,
    page_candidate_count: int,
) -> tuple[list[Candidate], int]:
    page_h, page_w = rgb.shape[:2]
    mask = _non_background_mask(rgb)
    kept: list[Candidate] = []
    ignored = 0
    scale = dpi / DEFAULT_DPI
    min_w = int((150 if conservative else 110) * scale)
    min_h = int((80 if conservative else 60) * scale)
    min_score = 0.44 if conservative else 0.34

    for box in boxes:
        x0, y0, x1, y1 = box
        w = x1 - x0
        h = y1 - y0
        area_ratio = (w * h) / max(1, page_w * page_h)
        aspect = w / max(1, h)

        if w < min_w or h < min_h:
            ignored += 1
            continue
        if y0 < page_h * 0.10 and h < page_h * 0.08:
            ignored += 1
            continue
        if y1 > page_h * 0.90 and h < page_h * 0.08:
            ignored += 1
            continue
        if h < 34 * scale or (aspect > 13 and h < 110 * scale):
            ignored += 1
            continue
        if area_ratio > 0.70:
            ignored += 1
            continue

        features = _box_features(rgb, mask, box)
        if _is_text_only(features, w, h, dpi):
            ignored += 1
            continue

        score, reasons = _score_candidate(page_w, page_h, box, features)
        if score < min_score:
            ignored += 1
            continue

        suggested, confidence, association_reasons = _associate_candidate(
            box, page_h, text_hint, page_candidate_count
        )
        reasons.extend(association_reasons)
        if not reasons:
            reasons.append("passed conservative visual filters")

        kept.append(
            Candidate(
                page=page_num,
                bbox=box,
                score=score,
                reasons=sorted(set(reasons)),
                suggested_question=suggested,
                confidence=confidence,
                needs_review=confidence != "high",
                width=w,
                height=h,
            )
        )

    return kept, ignored


def _associate_candidate(
    box: tuple[int, int, int, int],
    page_h: int,
    text_hint: PageTextHints,
    page_candidate_count: int,
) -> tuple[Optional[int], str, list[str]]:
    reasons: list[str] = []
    suggested: Optional[int] = None

    if text_hint.source != "none":
        reasons.append("native page text available")
    else:
        return None, "unknown", ["native text unavailable; association unknown"]

    qnums = text_hint.question_numbers
    chunk_qnums = text_hint.chunk_question_numbers
    if len(chunk_qnums) == 1:
        suggested = chunk_qnums[0]
        reasons.append("same page as existing chunk text")
    elif len(chunk_qnums) > 1:
        reasons.append("same page as multiple existing chunks")

    if len(qnums) == 1:
        if suggested is None:
            suggested = qnums[0]
        reasons.append("same page as one extracted question number")
    elif len(qnums) > 1:
        reasons.append("same page as multiple extracted question numbers")

    if text_hint.image_phrase:
        reasons.append("same page as image-reference phrase")

    x0, y0, x1, y1 = box
    crop_mid_y = (y0 + y1) / 2
    answer_choice_y = [y for y in text_hint.answer_choice_y if y > 0]
    if answer_choice_y:
        first_choice_y = min(answer_choice_y) * (page_h / 792.0)
        if crop_mid_y < first_choice_y:
            reasons.append("above native answer-choice text")
        else:
            reasons.append("near or below native answer-choice text")

    if page_candidate_count == 1:
        reasons.append("only major visual candidate on page")

    strong_reason_count = sum(
        1
        for reason in reasons
        if reason
        in {
            "same page as one extracted question number",
            "same page as existing chunk text",
            "same page as image-reference phrase",
            "above native answer-choice text",
            "only major visual candidate on page",
        }
    )

    if suggested is not None and strong_reason_count >= 4:
        confidence = "high"
    elif suggested is not None and strong_reason_count >= 2:
        confidence = "medium"
    elif suggested is not None:
        confidence = "low"
    else:
        confidence = "unknown"

    return suggested, confidence, reasons


def _png_bytes(rgb: np.ndarray) -> bytes:
    image = Image.fromarray(rgb)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _write_crop(pdf_stem: str, candidate: Candidate, crop_rgb: np.ndarray, ordinal: int) -> Candidate:
    figure_id = f"{pdf_stem}_p{candidate.page:03d}_fig{ordinal:03d}"
    out_path = EXTRACTED_DIR / f"{figure_id}.png"
    png = _png_bytes(crop_rgb)
    candidate.crop_hash = hashlib.sha256(png).hexdigest()
    candidate.figure_id = figure_id
    candidate.file_path = _rel(out_path)
    out_path.write_bytes(png)
    return candidate


def _candidate_to_manifest(c: Candidate) -> dict[str, Any]:
    return {
        "figureId": c.figure_id,
        "filePath": c.file_path,
        "page": c.page,
        "bbox": list(c.bbox),
        "width": c.width,
        "height": c.height,
        "cropHash": c.crop_hash,
        "suggestedQuestionNumber": c.suggested_question,
        "confidence": c.confidence,
        "score": c.score,
        "reasons": c.reasons,
        "needsReview": c.needs_review,
    }


def _make_contact_sheet(figures: list[dict[str, Any]], out_path: Path) -> None:
    thumb_w = 320
    thumb_h = 210
    label_h = 92
    pad = 18
    cols = 3 if len(figures) >= 3 else max(1, len(figures))
    if not figures:
        sheet = Image.new("RGB", (900, 260), "white")
        draw = ImageDraw.Draw(sheet)
        draw.text((24, 24), "No candidates kept", fill=(0, 0, 0))
        draw.text((24, 58), "Review manifest summary and warnings for ignored counts.", fill=(0, 0, 0))
        sheet.save(out_path)
        return

    rows = math.ceil(len(figures) / cols)
    cell_w = thumb_w + pad * 2
    cell_h = thumb_h + label_h + pad * 2
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), "white")
    draw = ImageDraw.Draw(sheet)

    for idx, fig in enumerate(figures):
        row = idx // cols
        col = idx % cols
        x = col * cell_w + pad
        y = row * cell_h + pad
        crop_path = SCRIPT_DIR / fig["filePath"]
        try:
            crop = Image.open(crop_path).convert("RGB")
        except Exception:
            crop = Image.new("RGB", (thumb_w, thumb_h), (240, 240, 240))
        crop.thumbnail((thumb_w, thumb_h), Image.LANCZOS)
        sheet.paste(crop, (x, y))

        label_y = y + thumb_h + 8
        label_lines = [
            fig["figureId"],
            f"page {fig['page']}  bbox {fig['bbox']}",
            f"confidence {fig['confidence']}  score {fig['score']}",
            f"question {fig['suggestedQuestionNumber'] or 'unknown'}",
        ]
        for line in label_lines:
            draw.text((x, label_y), line, fill=(0, 0, 0))
            label_y += 18

    sheet.save(out_path)


def extract_figures(
    pdf_path: Path,
    dpi: int = DEFAULT_DPI,
    max_pages: Optional[int] = None,
    conservative: bool = True,
    contact_sheet: bool = True,
) -> dict[str, Any]:
    ensure_dirs()
    warnings: list[str] = []
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF not found: {pdf_path}\n"
            "Pass a valid path, for example: python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf"
        )
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file, got: {pdf_path}")

    text_hints = _extract_page_text_hints(pdf_path, max_pages, warnings)
    source_display = str(pdf_path.relative_to(SCRIPT_DIR)) if pdf_path.is_relative_to(SCRIPT_DIR) else str(pdf_path)
    pdf_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", pdf_path.stem).strip("_") or "pdf"
    _merge_chunk_page_hints(pdf_stem, text_hints, warnings)

    figures: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    duplicates_removed = 0
    figures_detected = 0
    figures_ignored = 0
    pages_processed = 0
    per_page_ordinals: dict[int, int] = {}

    with fitz.open(pdf_path) as doc:
        page_total = doc.page_count
        page_limit = min(page_total, max_pages) if max_pages else page_total
        for page_index in range(page_limit):
            page_num = page_index + 1
            pages_processed += 1
            rgb = _render_page(doc[page_index], dpi)
            boxes, raw_box_count = _detect_boxes(rgb, dpi, conservative)
            figures_detected += raw_box_count
            page_hint = text_hints.get(page_num, PageTextHints())
            candidates, ignored = _filter_and_score_boxes(
                rgb, boxes, page_num, dpi, conservative, page_hint, len(boxes)
            )
            figures_ignored += ignored

            for candidate in candidates:
                x0, y0, x1, y1 = candidate.bbox
                pad = max(8, int(10 * dpi / DEFAULT_DPI))
                x0p = max(0, x0 - pad)
                y0p = max(0, y0 - pad)
                x1p = min(rgb.shape[1], x1 + pad)
                y1p = min(rgb.shape[0], y1 + pad)
                crop = rgb[y0p:y1p, x0p:x1p]
                crop_hash = hashlib.sha256(_png_bytes(crop)).hexdigest()
                if crop_hash in seen_hashes:
                    duplicates_removed += 1
                    continue
                seen_hashes.add(crop_hash)
                per_page_ordinals[page_num] = per_page_ordinals.get(page_num, 0) + 1
                candidate.bbox = (x0p, y0p, x1p, y1p)
                candidate.width = x1p - x0p
                candidate.height = y1p - y0p
                candidate = _write_crop(pdf_stem, candidate, crop, per_page_ordinals[page_num])
                figures.append(_candidate_to_manifest(candidate))

    summary = {
        "pagesProcessed": pages_processed,
        "figuresDetected": figures_detected,
        "figuresKept": len(figures),
        "figuresIgnored": figures_ignored,
        "duplicatesRemoved": duplicates_removed,
        "highConfidence": sum(1 for f in figures if f["confidence"] == "high"),
        "mediumConfidence": sum(1 for f in figures if f["confidence"] == "medium"),
        "lowConfidence": sum(1 for f in figures if f["confidence"] == "low"),
        "unknownConfidence": sum(1 for f in figures if f["confidence"] == "unknown"),
        "needsReview": sum(1 for f in figures if f["needsReview"]),
    }
    manifest = {
        "sourcePdf": source_display,
        "dpi": dpi,
        "figures": figures,
        "summary": summary,
        "warnings": warnings,
    }

    manifest_path = MANIFEST_DIR / f"{pdf_stem}_figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    contact_path = MANIFEST_DIR / f"{pdf_stem}_contact_sheet.png"
    if contact_sheet:
        _make_contact_sheet(figures, contact_path)

    print(f"Manifest: {_rel(manifest_path)}")
    if contact_sheet:
        print(f"Contact sheet: {_rel(contact_path)}")
    print(
        "Summary: "
        f"{summary['pagesProcessed']} pages, "
        f"{summary['figuresKept']} kept, "
        f"{summary['figuresIgnored']} ignored, "
        f"{summary['duplicatesRemoved']} duplicates removed, "
        f"{summary['needsReview']} need review"
    )
    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract likely NBME figure/image crop candidates from rendered PDF pages."
    )
    parser.add_argument("--pdf", required=True, help="PDF path, absolute or relative to this tool directory")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="Render DPI. Default: 200")
    parser.add_argument("--max-pages", type=int, default=None, help="Optional maximum pages to process")
    parser.add_argument(
        "--contact-sheet",
        dest="contact_sheet",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a PNG contact sheet. Default: true",
    )
    parser.add_argument(
        "--conservative",
        dest="conservative",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Prefer fewer false positives. Default: true",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.dpi < 100 or args.dpi > 400:
        print("ERROR: --dpi must be between 100 and 400", file=sys.stderr)
        return 2
    if args.max_pages is not None and args.max_pages < 1:
        print("ERROR: --max-pages must be >= 1", file=sys.stderr)
        return 2

    try:
        extract_figures(
            _resolve_pdf(args.pdf),
            dpi=args.dpi,
            max_pages=args.max_pages,
            conservative=args.conservative,
            contact_sheet=args.contact_sheet,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
