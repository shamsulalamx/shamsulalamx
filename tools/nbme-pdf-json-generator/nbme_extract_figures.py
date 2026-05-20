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
import csv
import hashlib
import html
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
    visual_score: float = 0.0
    text_like_score: float = 0.0
    rejection_reasons: list[str] = field(default_factory=list)
    kept: bool = True
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
    small_textish = 0
    line_like = 0
    large_visual = 0
    for idx in range(1, count):
        area = float(stats[idx, cv2.CC_STAT_AREA])
        if area < 3:
            continue
        w = float(stats[idx, cv2.CC_STAT_WIDTH])
        h = float(stats[idx, cv2.CC_STAT_HEIGHT])
        areas.append(area)
        widths.append(w)
        heights.append(h)
        if 3 <= h <= 26 and 2 <= w <= 220 and area <= 1300:
            small_textish += 1
        if w >= 90 and h <= 12:
            line_like += 1
        if area >= 2200 or (w >= 90 and h >= 70):
            large_visual += 1
    if not areas:
        return {
            "count": 0.0,
            "max_area": 0.0,
            "median_height": 0.0,
            "median_width": 0.0,
            "small_textish": 0.0,
            "line_like": 0.0,
            "large_visual": 0.0,
        }
    return {
        "count": float(len(areas)),
        "max_area": float(max(areas)),
        "median_height": float(np.median(heights)),
        "median_width": float(np.median(widths)),
        "small_textish": float(small_textish),
        "line_like": float(line_like),
        "large_visual": float(large_visual),
    }


def _box_features(rgb: np.ndarray, mask: np.ndarray, box: tuple[int, int, int, int]) -> dict[str, float]:
    x0, y0, x1, y1 = box
    crop = rgb[y0:y1, x0:x1]
    crop_mask = mask[y0:y1, x0:x1]
    area = max(1, crop_mask.shape[0] * crop_mask.shape[1])
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    edges = cv2.Canny(gray, 80, 180)
    stats = _component_stats(crop_mask)
    dark = gray < 160
    white = gray > 245
    colored = saturation > 40
    row_counts = (crop_mask > 0).sum(axis=1)
    active_rows = np.where(row_counts > max(12, crop_mask.shape[1] * 0.015))[0]
    row_runs = 0
    if active_rows.size:
        gaps = np.diff(active_rows)
        row_runs = int(np.count_nonzero(gaps > 2) + 1)
    return {
        "ink_density": float(np.count_nonzero(crop_mask) / area),
        "edge_density": float(np.count_nonzero(edges) / area),
        "white_ratio": float(np.count_nonzero(white) / area),
        "dark_ratio": float(np.count_nonzero(dark) / area),
        "color_ratio": float(np.count_nonzero(colored) / area),
        "gray_std": float(np.std(gray)),
        "sat_std": float(np.std(saturation)),
        "row_runs": float(row_runs),
        "component_count": stats["count"],
        "component_max_area_ratio": float(stats["max_area"] / area),
        "component_median_height": stats["median_height"],
        "component_median_width": stats["median_width"],
        "small_textish_components": stats["small_textish"],
        "line_like_components": stats["line_like"],
        "large_visual_components": stats["large_visual"],
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


def _line_density_score(features: dict[str, float], w: int, h: int) -> float:
    row_run_density = features["row_runs"] / max(1.0, h / 22.0)
    small_component_density = features["small_textish_components"] / max(1.0, features["component_count"])
    return min(1.0, 0.55 * row_run_density + 0.45 * small_component_density)


def _visual_text_scores(features: dict[str, float], w: int, h: int, area_ratio: float) -> tuple[float, float]:
    line_density = _line_density_score(features, w, h)
    color_score = min(1.0, features["color_ratio"] / 0.035)
    tonal_score = min(1.0, features["gray_std"] / 55.0)
    edge_score = min(1.0, features["edge_density"] / 0.08)
    large_component_score = min(1.0, features["component_max_area_ratio"] / 0.11)
    size_score = min(1.0, area_ratio / 0.045)

    visual_score = (
        0.22 * color_score
        + 0.22 * tonal_score
        + 0.20 * edge_score
        + 0.24 * large_component_score
        + 0.12 * size_score
    )

    white_text_score = 1.0 if features["white_ratio"] > 0.70 and features["color_ratio"] < 0.025 else 0.0
    small_text_score = min(1.0, features["small_textish_components"] / 60.0)
    paragraph_score = min(1.0, line_density)
    low_photo_variance = 1.0 if features["gray_std"] < 44 and features["color_ratio"] < 0.018 else 0.0
    line_table_score = min(1.0, features["line_like_components"] / 8.0)

    text_like_score = (
        0.28 * white_text_score
        + 0.28 * small_text_score
        + 0.24 * paragraph_score
        + 0.12 * low_photo_variance
        + 0.08 * line_table_score
    )

    # Visually dense or photo-like crops should not be rejected simply because
    # they contain small labels, grid ticks, or ECG axis text.
    if visual_score >= 0.68 and features["component_max_area_ratio"] >= 0.07:
        text_like_score *= 0.65
    if features["color_ratio"] >= 0.08 or features["gray_std"] >= 70:
        text_like_score *= 0.75

    return round(float(visual_score), 4), round(float(text_like_score), 4)


def _answer_choice_overlap_reasons(
    box: tuple[int, int, int, int],
    page_h: int,
    text_hint: PageTextHints,
) -> list[str]:
    if not text_hint.answer_choice_y:
        return []
    x0, y0, x1, y1 = box
    scale_y = page_h / 792.0
    answer_ys = [y * scale_y for y in text_hint.answer_choice_y if y > 0]
    if not answer_ys:
        return []
    inside = [y for y in answer_ys if y0 <= y <= y1]
    if len(inside) >= 3:
        return ["overlaps multiple native answer-choice labels"]
    first_choice = min(answer_ys)
    if y0 >= first_choice - 12 and len(inside) >= 2:
        return ["starts in answer-choice region"]
    return []


def _second_pass_decision(
    features: dict[str, float],
    box: tuple[int, int, int, int],
    page_w: int,
    page_h: int,
    dpi: int,
    text_hint: PageTextHints,
    min_visual_score: float,
    strict_text_filter: bool,
) -> tuple[bool, float, float, list[str]]:
    x0, y0, x1, y1 = box
    w = x1 - x0
    h = y1 - y0
    area_ratio = (w * h) / max(1, page_w * page_h)
    aspect = w / max(1, h)
    visual_score, text_like_score = _visual_text_scores(features, w, h, area_ratio)
    rejection_reasons = []
    component_count = max(1.0, features["component_count"])
    small_text_ratio = features["small_textish_components"] / component_count
    text_dominated_layout = (
        small_text_ratio >= 0.72
        and features["component_count"] >= 35
        and features["row_runs"] >= 5
    )
    likely_graph_or_diagram = (
        features["large_visual_components"] >= 2
        and features["component_count"] < 90
        and features["component_max_area_ratio"] >= 0.018
    )
    highlighted_answer_layout = (
        features["white_ratio"] > 0.55
        and features["color_ratio"] > 0.08
        and features["small_textish_components"] >= 35
        and features["row_runs"] >= 5
        and features["component_max_area_ratio"] < 0.28
    )
    compact_text_list = (
        h < 260 * (dpi / DEFAULT_DPI)
        and small_text_ratio >= 0.72
        and features["row_runs"] >= 3
        and features["large_visual_components"] <= 1
    )
    compact_highlight_list = (
        features["white_ratio"] > 0.75
        and features["color_ratio"] > 0.07
        and features["gray_std"] < 52
        and features["row_runs"] >= 6
        and features["component_count"] >= 15
        and features["component_max_area_ratio"] < 0.075
    )
    plain_text_table = (
        features["color_ratio"] < 0.025
        and small_text_ratio >= 0.60
        and features["row_runs"] >= 4
        and features["large_visual_components"] == 0
    )

    if visual_score < min_visual_score:
        rejection_reasons.append("visual score below threshold")
    if (
        features["white_ratio"] > 0.78
        and features["dark_ratio"] < 0.18
        and features["color_ratio"] < 0.018
        and not likely_graph_or_diagram
    ):
        rejection_reasons.append("mostly black text on white background")
    if highlighted_answer_layout:
        rejection_reasons.append("highlighted answer-choice/list layout")
    if compact_text_list:
        rejection_reasons.append("compact answer-choice/list crop")
    if compact_highlight_list:
        rejection_reasons.append("compact highlighted answer-choice crop")
    if plain_text_table and not likely_graph_or_diagram:
        rejection_reasons.append("plain text table crop")
    if (
        features["small_textish_components"] >= 55
        and (features["large_visual_components"] <= 1 or text_dominated_layout)
        and not likely_graph_or_diagram
    ):
        rejection_reasons.append("dense small text components")
    if (
        features["row_runs"] >= 8
        and features["component_max_area_ratio"] < 0.045
        and features["component_count"] >= 45
        and not likely_graph_or_diagram
    ):
        rejection_reasons.append("paragraph or answer-list row layout")
    if features["line_like_components"] >= 5 and visual_score < 0.62 and features["color_ratio"] < 0.035:
        rejection_reasons.append("plain line/table artifact without visual signal")
    if aspect > 7.5 and features["gray_std"] < 58:
        rejection_reasons.append("decorative horizontal line")

    rejection_reasons.extend(_answer_choice_overlap_reasons(box, page_h, text_hint))

    has_medical_visual_signal = (
        visual_score >= max(min_visual_score, 0.48)
        and not text_dominated_layout
        and (
            features["component_max_area_ratio"] >= 0.06
            or features["gray_std"] >= 62
            or features["color_ratio"] >= 0.04
            or likely_graph_or_diagram
        )
    )
    text_cutoff = 0.64 if strict_text_filter else 0.72
    if text_like_score >= text_cutoff and not has_medical_visual_signal:
        rejection_reasons.append("text-like score above threshold")

    # Keep uncertain medical-looking crops, but reject obvious text/list/table
    # blocks when at least two independent text signals agree.
    hard_reasons = [
        r for r in rejection_reasons
        if r in {
            "visual score below threshold",
            "mostly black text on white background",
            "highlighted answer-choice/list layout",
            "compact answer-choice/list crop",
            "compact highlighted answer-choice crop",
            "plain text table crop",
            "dense small text components",
            "paragraph or answer-list row layout",
            "plain line/table artifact without visual signal",
            "decorative horizontal line",
            "overlaps multiple native answer-choice labels",
            "starts in answer-choice region",
            "text-like score above threshold",
        }
    ]
    keep = True
    if "visual score below threshold" in hard_reasons:
        keep = False
    elif "highlighted answer-choice/list layout" in hard_reasons:
        keep = False
    elif "compact answer-choice/list crop" in hard_reasons:
        keep = False
    elif "compact highlighted answer-choice crop" in hard_reasons:
        keep = False
    elif "plain text table crop" in hard_reasons:
        keep = False
    elif "overlaps multiple native answer-choice labels" in hard_reasons:
        keep = False
    elif "starts in answer-choice region" in hard_reasons:
        keep = False
    elif "paragraph or answer-list row layout" in hard_reasons:
        keep = False
    elif "mostly black text on white background" in hard_reasons:
        keep = False
    elif "decorative horizontal line" in hard_reasons and text_dominated_layout:
        keep = False
    elif len(hard_reasons) >= (1 if strict_text_filter else 2) and not has_medical_visual_signal:
        keep = False

    return keep, visual_score, text_like_score, sorted(set(rejection_reasons))


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
    min_visual_score: float,
    strict_text_filter: bool,
    debug_rejected: bool,
) -> tuple[list[Candidate], int, list[Candidate]]:
    page_h, page_w = rgb.shape[:2]
    mask = _non_background_mask(rgb)
    kept: list[Candidate] = []
    ignored = 0
    scale = dpi / DEFAULT_DPI
    min_w = int((150 if conservative else 110) * scale)
    min_h = int((80 if conservative else 60) * scale)
    min_score = 0.44 if conservative else 0.34
    rejected_candidates: list[Candidate] = []

    def reject_candidate(
        reject_box: tuple[int, int, int, int],
        reject_reasons: list[str],
        reject_features: Optional[dict[str, float]] = None,
        reject_score: float = 0.0,
    ) -> None:
        if not debug_rejected:
            return
        rx0, ry0, rx1, ry1 = reject_box
        if reject_features is not None:
            visual_score, text_like_score = _visual_text_scores(
                reject_features,
                rx1 - rx0,
                ry1 - ry0,
                ((rx1 - rx0) * (ry1 - ry0)) / max(1, page_w * page_h),
            )
        else:
            visual_score, text_like_score = 0.0, 0.0
        rejected_candidates.append(
            Candidate(
                page=page_num,
                bbox=reject_box,
                score=round(float(reject_score), 4),
                reasons=[],
                suggested_question=None,
                confidence="unknown",
                needs_review=True,
                width=rx1 - rx0,
                height=ry1 - ry0,
                visual_score=visual_score,
                text_like_score=text_like_score,
                rejection_reasons=sorted(set(reject_reasons)),
                kept=False,
            )
        )

    for box in boxes:
        x0, y0, x1, y1 = box
        w = x1 - x0
        h = y1 - y0
        area_ratio = (w * h) / max(1, page_w * page_h)
        aspect = w / max(1, h)

        if w < min_w or h < min_h:
            ignored += 1
            reject_candidate(box, ["below minimum size threshold"])
            continue
        if y0 < page_h * 0.10 and h < page_h * 0.08:
            ignored += 1
            reject_candidate(box, ["top header or UI bar"])
            continue
        if y1 > page_h * 0.90 and h < page_h * 0.08:
            ignored += 1
            reject_candidate(box, ["bottom footer or UI bar"])
            continue
        if h < 34 * scale or (aspect > 13 and h < 110 * scale):
            ignored += 1
            reject_candidate(box, ["decorative horizontal line or tiny strip"])
            continue
        if area_ratio > 0.70:
            ignored += 1
            reject_candidate(box, ["full-page background screenshot"])
            continue

        features = _box_features(rgb, mask, box)
        if _is_text_only(features, w, h, dpi):
            ignored += 1
            reject_candidate(box, ["first-pass text-only component pattern"], features)
            continue

        score, reasons = _score_candidate(page_w, page_h, box, features)
        if score < min_score:
            ignored += 1
            reject_candidate(box, ["first-pass score below threshold"], features, score)
            continue

        keep, visual_score, text_like_score, rejection_reasons = _second_pass_decision(
            features,
            box,
            page_w,
            page_h,
            dpi,
            text_hint,
            min_visual_score,
            strict_text_filter,
        )
        if not keep:
            ignored += 1
            reject_candidate(box, rejection_reasons, features, score)
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
                visual_score=visual_score,
                text_like_score=text_like_score,
                rejection_reasons=rejection_reasons,
                kept=True,
            )
        )

    return kept, ignored, rejected_candidates


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
        "visualScore": c.visual_score,
        "textLikeScore": c.text_like_score,
        "reasons": c.reasons,
        "rejectionReasons": c.rejection_reasons,
        "kept": c.kept,
        "needsReview": c.needs_review,
    }


def _make_contact_sheet(figures: list[dict[str, Any]], out_path: Path) -> None:
    thumb_w = 320
    thumb_h = 220
    label_h = 108
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
            f"page {fig['page']}  suggested Q {fig['suggestedQuestionNumber'] or 'unknown'}",
            f"confidence {fig['confidence']}  score {fig['score']}",
            f"bbox {fig['bbox']}",
        ]
        for line in label_lines:
            draw.text((x, label_y), line, fill=(0, 0, 0))
            label_y += 18

    sheet.save(out_path)


def _write_review_csv(figures: list[dict[str, Any]], out_path: Path) -> None:
    columns = [
        "figureId",
        "page",
        "filePath",
        "confidence",
        "score",
        "suggestedQuestionNumber",
        "needsReview",
        "width",
        "height",
        "bbox",
        "visualScore",
        "textLikeScore",
        "rejectionReasons",
        "notes",
        "userDecision",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for fig in figures:
            writer.writerow({
                "figureId": fig.get("figureId", ""),
                "page": fig.get("page", ""),
                "filePath": fig.get("filePath", ""),
                "confidence": fig.get("confidence", ""),
                "score": fig.get("score", ""),
                "suggestedQuestionNumber": fig.get("suggestedQuestionNumber") or "",
                "needsReview": fig.get("needsReview", ""),
                "width": fig.get("width", ""),
                "height": fig.get("height", ""),
                "bbox": json.dumps(fig.get("bbox", []), separators=(",", ":")),
                "visualScore": fig.get("visualScore", ""),
                "textLikeScore": fig.get("textLikeScore", ""),
                "rejectionReasons": "; ".join(fig.get("rejectionReasons") or []),
                "notes": "",
                "userDecision": "",
            })


def _html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _write_review_html(
    figures: list[dict[str, Any]],
    out_path: Path,
    manifest_path: Path,
    csv_path: Path,
    contact_path: Path,
    summary: dict[str, Any],
) -> None:
    rows = []
    for fig in figures:
        image_src = "../" + fig["filePath"]
        suggested = fig.get("suggestedQuestionNumber") or "unknown"
        reasons = fig.get("reasons") or []
        rejection_reasons = fig.get("rejectionReasons") or []
        rows.append(f"""
        <article class="figure-card" id="{_html_escape(fig.get('figureId'))}">
          <div class="figure-image-wrap">
            <img src="{_html_escape(image_src)}" alt="{_html_escape(fig.get('figureId'))}">
          </div>
          <div class="figure-meta">
            <h2>{_html_escape(fig.get('figureId'))}</h2>
            <dl>
              <div><dt>Page</dt><dd>{_html_escape(fig.get('page'))}</dd></div>
              <div><dt>Suggested Q</dt><dd>{_html_escape(suggested)}</dd></div>
              <div><dt>Confidence</dt><dd>{_html_escape(fig.get('confidence'))}</dd></div>
              <div><dt>Score</dt><dd>{_html_escape(fig.get('score'))}</dd></div>
              <div><dt>Visual Score</dt><dd>{_html_escape(fig.get('visualScore'))}</dd></div>
              <div><dt>Text-Like Score</dt><dd>{_html_escape(fig.get('textLikeScore'))}</dd></div>
              <div><dt>Needs Review</dt><dd>{_html_escape(fig.get('needsReview'))}</dd></div>
              <div><dt>Size</dt><dd>{_html_escape(fig.get('width'))} x {_html_escape(fig.get('height'))}</dd></div>
              <div><dt>BBox</dt><dd>{_html_escape(fig.get('bbox'))}</dd></div>
              <div><dt>File</dt><dd><code>{_html_escape(fig.get('filePath'))}</code></dd></div>
            </dl>
            <fieldset>
              <legend>Review decision</legend>
              <label><input type="checkbox"> accept</label>
              <label><input type="checkbox"> reject</label>
              <label><input type="checkbox"> wrong question</label>
              <label><input type="checkbox"> needs crop</label>
            </fieldset>
            <div class="notes">
              <label>Notes</label>
              <textarea aria-label="Review notes for {_html_escape(fig.get('figureId'))}"></textarea>
            </div>
            <details>
              <summary>Detection reasons</summary>
              <p><strong>Reasons:</strong> {_html_escape('; '.join(reasons) or 'none')}</p>
              <p><strong>Rejection flags:</strong> {_html_escape('; '.join(rejection_reasons) or 'none')}</p>
            </details>
          </div>
        </article>
        """)

    if not rows:
        rows.append("""
        <article class="empty">
          <h2>No kept candidates</h2>
          <p>The extractor did not keep any figure candidates for this run.</p>
        </article>
        """)

    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NBME Figure Review</title>
  <style>
    :root {{
      color-scheme: light;
      --border: #d7dde5;
      --muted: #5f6b7a;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --ink: #17202a;
      --accent: #1f5f99;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 2;
      padding: 18px 24px;
      background: var(--panel);
      border-bottom: 1px solid var(--border);
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 22px;
      letter-spacing: 0;
    }}
    .summary {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      color: var(--muted);
      font-size: 14px;
    }}
    .links {{
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid currentColor;
    }}
    main {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 20px;
    }}
    .figure-card {{
      display: grid;
      grid-template-columns: minmax(280px, 46%) minmax(320px, 1fr);
      gap: 18px;
      padding: 16px;
      margin-bottom: 18px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    .figure-image-wrap {{
      display: flex;
      align-items: flex-start;
      justify-content: center;
      overflow: auto;
      max-height: 620px;
      border: 1px solid var(--border);
      background: #fff;
    }}
    img {{
      max-width: 100%;
      height: auto;
      display: block;
    }}
    h2 {{
      margin: 0 0 12px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    dl {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 14px;
      margin: 0 0 14px;
    }}
    dt {{
      color: var(--muted);
      font-size: 12px;
    }}
    dd {{
      margin: 2px 0 0;
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    fieldset {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin: 0 0 14px;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: 6px;
    }}
    legend {{
      color: var(--muted);
      font-size: 13px;
      padding: 0 4px;
    }}
    label {{
      font-size: 14px;
    }}
    input {{
      margin-right: 6px;
    }}
    textarea {{
      width: 100%;
      min-height: 72px;
      margin-top: 6px;
      padding: 8px;
      border: 1px solid var(--border);
      border-radius: 6px;
      font: inherit;
      resize: vertical;
    }}
    details {{
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }}
    code {{
      font-size: 13px;
      white-space: normal;
    }}
    .empty {{
      padding: 20px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    @media (max-width: 860px) {{
      .figure-card {{
        grid-template-columns: 1fr;
      }}
      dl {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>NBME Figure Review</h1>
    <div class="summary">
      <span>Kept: {_html_escape(summary.get('figuresKept'))}</span>
      <span>Ignored: {_html_escape(summary.get('figuresIgnored'))}</span>
      <span>Needs review: {_html_escape(summary.get('needsReview'))}</span>
      <span>Text-like kept: {_html_escape(summary.get('textLikeKept'))}</span>
    </div>
    <div class="links">
      <a href="{_html_escape(manifest_path.name)}">Manifest JSON</a>
      <a href="{_html_escape(csv_path.name)}">Review CSV</a>
      <a href="{_html_escape(contact_path.name)}">Contact Sheet</a>
    </div>
  </header>
  <main>
    {''.join(rows)}
  </main>
</body>
</html>
"""
    out_path.write_text(html_text, encoding="utf-8")


def extract_figures(
    pdf_path: Path,
    dpi: int = DEFAULT_DPI,
    max_pages: Optional[int] = None,
    conservative: bool = True,
    contact_sheet: bool = True,
    review_html: bool = True,
    strict_text_filter: bool = False,
    min_visual_score: float = 0.42,
    debug_rejected: bool = False,
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
    rejected_debug: list[dict[str, Any]] = []

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
            candidates, ignored, rejected_candidates = _filter_and_score_boxes(
                rgb,
                boxes,
                page_num,
                dpi,
                conservative,
                page_hint,
                len(boxes),
                min_visual_score,
                strict_text_filter,
                debug_rejected,
            )
            figures_ignored += ignored

            if debug_rejected:
                for rejected in rejected_candidates:
                    rejected_debug.append({
                        "page": rejected.page,
                        "bbox": list(rejected.bbox),
                        "width": rejected.width,
                        "height": rejected.height,
                        "score": rejected.score,
                        "visualScore": rejected.visual_score,
                        "textLikeScore": rejected.text_like_score,
                        "rejectionReasons": rejected.rejection_reasons,
                        "kept": False,
                    })

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
        "textLikeKept": sum(1 for f in figures if f["textLikeScore"] >= 0.72),
        "rejectedDebugCount": len(rejected_debug),
    }
    manifest = {
        "sourcePdf": source_display,
        "dpi": dpi,
        "settings": {
            "conservative": conservative,
            "strictTextFilter": strict_text_filter,
            "minVisualScore": min_visual_score,
            "debugRejected": debug_rejected,
        },
        "figures": figures,
        "summary": summary,
        "warnings": warnings,
    }
    if debug_rejected:
        manifest["rejectedCandidates"] = rejected_debug

    manifest_path = MANIFEST_DIR / f"{pdf_stem}_figure_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    contact_path = MANIFEST_DIR / f"{pdf_stem}_contact_sheet.png"
    if contact_sheet:
        _make_contact_sheet(figures, contact_path)

    review_csv_path = MANIFEST_DIR / f"{pdf_stem}_figure_review.csv"
    _write_review_csv(figures, review_csv_path)

    review_html_path = MANIFEST_DIR / f"{pdf_stem}_figure_review.html"
    if review_html:
        _write_review_html(
            figures,
            review_html_path,
            manifest_path,
            review_csv_path,
            contact_path,
            summary,
        )

    print(f"Manifest: {_rel(manifest_path)}")
    if contact_sheet:
        print(f"Contact sheet: {_rel(contact_path)}")
    print(f"Review CSV: {_rel(review_csv_path)}")
    if review_html:
        print(f"Review HTML: {_rel(review_html_path)}")
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
        "--review-html",
        dest="review_html",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a static HTML review page. Default: true",
    )
    parser.add_argument(
        "--conservative",
        dest="conservative",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Prefer fewer false positives. Default: true",
    )
    parser.add_argument(
        "--strict-text-filter",
        action="store_true",
        help="Use stricter rejection for text-like crops.",
    )
    parser.add_argument(
        "--min-visual-score",
        type=float,
        default=0.42,
        help="Minimum second-pass visual score. Default: 0.42",
    )
    parser.add_argument(
        "--debug-rejected",
        action="store_true",
        help="Include rejected candidate diagnostics in the manifest.",
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
    if args.min_visual_score < 0 or args.min_visual_score > 1:
        print("ERROR: --min-visual-score must be between 0 and 1", file=sys.stderr)
        return 2

    try:
        extract_figures(
            _resolve_pdf(args.pdf),
            dpi=args.dpi,
            max_pages=args.max_pages,
            conservative=args.conservative,
            contact_sheet=args.contact_sheet,
            review_html=args.review_html,
            strict_text_filter=args.strict_text_filter,
            min_visual_score=args.min_visual_score,
            debug_rejected=args.debug_rejected,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
