#!/usr/bin/env python3
"""
Lecture slide PDF -> NBME-style question generator.

This is an isolated external tool. It does not modify the in-app raw NBME
importer. Output is canonical nbme-gemini-json-v3 accepted by the existing
NBME Gemini JSON importer in index.html.
"""

from __future__ import annotations

import argparse
import base64
import copy
import datetime as dt
import hashlib
import html.parser
import json
import mimetypes
import os
import re
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent.resolve()
INPUT_DIR = BASE_DIR / "input_pdfs"
OUTPUT_DIR = BASE_DIR / "output_json"
SLIDES_DIR = OUTPUT_DIR / "slides"
NORMALIZED_DIR = OUTPUT_DIR / "normalized"
MEMORY_DIR = OUTPUT_DIR / "memory"
GENERATED_DIR = OUTPUT_DIR / "generated"
APP_READY_DIR = OUTPUT_DIR / "app_ready"
DEBUG_DIR = OUTPUT_DIR / "debug"
ASSET_DIR = BASE_DIR / "output_assets"
REPORT_DIR = BASE_DIR / "reports"
LOG_DIR = BASE_DIR / "logs"
PROMPT_DIR = BASE_DIR / "prompts"
NORMALIZE_PROMPT = PROMPT_DIR / "normalize_slides_prompt.txt"
GENERATE_PROMPT = PROMPT_DIR / "generate_questions_prompt.txt"

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
OUTPUT_SCHEMA_VERSION = "nbme-gemini-json-v3"
SOURCE_FORMAT = "mixed"
LABELS = ["A", "B", "C", "D"]
MAX_SLIDES_PER_CHUNK = 3
MAX_GENERATION_ALLOCS_PER_CHUNK = 8
SMALL_NORMALIZATION_CHUNK_SIZE = 2
ISOLATED_NORMALIZATION_CHUNK_SIZE = 1
MAX_NORMALIZATION_ESTIMATED_JSON_CHARS = 6500
MAX_NORMALIZATION_OCR_CHARS = 3200

SLIDE_TYPES = {
    "HIGH_YIELD_CLINICAL",
    "MECHANISM",
    "RAPID_RECALL",
    "IMAGE_HEAVY",
    "TABLE_HEAVY",
    "LOW_INFORMATION",
    "ADMINISTRATIVE",
    "DUPLICATE_TOPIC",
    "TRANSITION_SLIDE",
}

FORBIDDEN_STRINGS = [
    "eftab720",
    "tightenfactor0",
    "Here are the questions",
    "```json",
    "```",
]

OCR_FRAGMENT_PATTERNS = [
    re.compile(r"\beftab720\b", re.I),
    re.compile(r"\btightenfactor0\b", re.I),
    re.compile(r"[\u2022]{2,}"),
    re.compile(r"[_=]{5,}"),
    re.compile(r"\bSlide\s+\d+\s+of\s+\d+\b", re.I),
]

COMMON_CLINICAL_WORDS = {
    "a", "an", "and", "are", "as", "at", "best", "by", "can", "does", "for",
    "from", "has", "have", "in", "is", "it", "may", "most", "of", "on", "or",
    "patient", "patients", "presents", "present", "with", "without", "the",
    "this", "to", "which", "will", "would", "following", "clinician", "child",
    "infant", "newborn", "boy", "girl", "man", "woman", "mother", "father",
    "old", "year", "years", "day", "days", "month", "months", "week", "weeks",
    "finding", "findings", "symptom", "symptoms", "sign", "signs", "diagnosis",
    "treatment", "management", "mechanism", "disease", "disorder", "syndrome",
    "condition", "answer", "choice", "slide", "supported", "concept",
    "examination", "exam", "reveals", "shows", "noted", "reported", "reports",
    "describes", "appears", "otherwise", "healthy", "feeding", "based",
    "identify", "diagnose", "differentiate", "determine", "suggests",
    "suggestive", "consistent", "characteristic", "classic", "key", "likely",
    "physical", "clinical", "history", "team", "concerned", "prepared",
    "preparing", "initial", "routine", "visit", "presentation", "case",
    "given", "while", "however", "typically", "often", "usually",
    "adequate", "critical", "difficult", "inappropriate", "intervention",
    "interventions", "mild", "moderate", "observation", "prompt", "specific",
    "severe", "significant", "suspicious", "transient",
}

MEDICAL_SUFFIXES = (
    "itis", "osis", "emia", "uria", "pathy", "plasia", "trophy", "penia",
    "cytosis", "blast", "mycin", "cillin", "azole", "pril", "sartan", "olol",
    "pine", "mab", "vir", "statin", "caine", "zine", "zepam", "xaban",
)

HIGH_RISK_MEDICAL_WORDS = {
    "agenesis", "akinesia", "alkalosis", "atresia", "biopsy", "ceftriaxone",
    "cerebritis", "corticosteroids", "cyanosis", "cyst", "dystocia",
    "encephalopathy", "enzyme", "fistula", "fracture", "gastroschisis",
    "hernia", "hydrocephalus", "hyperbilirubinemia", "hypoplasia",
    "hypothyroidism", "intussusception", "ischemia", "jaundice", "malrotation",
    "meconium", "omphalocele", "palsy", "phototherapy", "pneumonia",
    "reflux", "sepsis", "stenosis", "surgery", "syndrome", "volvulus",
    "acidosis", "appendicitis", "arthritis", "azithromycin", "ceftriaxone",
    "doxycycline", "hypocalcemia", "hypoglycemia", "hypokalemia", "leukemia",
    "lymphadenopathy", "lymphoma", "meningitis", "mononucleosis",
    "osteomyelitis", "pancreatitis", "thrombocytopenia", "thrombosis",
}

WORKUP_MANAGEMENT_WORDS = {
    "antibiotic", "antibiotics", "antibody", "audiometry", "biopsy", "ct",
    "culture", "dialysis", "ecg", "echo", "echocardiogram", "eeg", "ekg",
    "enzyme", "mri", "receptor", "steroid", "surgery", "surgical",
    "ultrasound", "vaccine", "ventilation", "x-ray", "xray",
}

TRIVIAL_RECALL_PATTERNS = [
    re.compile(r"\bwhich of the following is true\b", re.I),
    re.compile(r"\ball except\b", re.I),
    re.compile(r"\bexcept\b", re.I),
    re.compile(r"\bmost common cause\b", re.I),
    re.compile(r"\bwhat is the diagnosis\b", re.I),
    re.compile(r"\bwhat is the treatment\b", re.I),
]


class PipelineError(Exception):
    pass


class JsonParseFailure(PipelineError):
    def __init__(self, message: str, failure_type: str = "invalid_json") -> None:
        super().__init__(message)
        self.failure_type = failure_type


class StrictHTMLParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "hr", "img", "meta", "input"}:
            return
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"br", "hr", "img", "meta", "input"}:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected closing tag </{tag}>")
            return
        self.stack.pop()

    def close(self) -> None:
        super().close()
        if self.stack:
            self.errors.append(f"unclosed tags: {', '.join(self.stack)}")


def log(message: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}", file=sys.stderr)


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dirs() -> None:
    for path in [
        INPUT_DIR,
        SLIDES_DIR,
        NORMALIZED_DIR,
        MEMORY_DIR,
        GENERATED_DIR,
        APP_READY_DIR,
        DEBUG_DIR,
        ASSET_DIR,
        REPORT_DIR,
        LOG_DIR,
        PROMPT_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("._")
    return value or "lecture_slides"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def supported_pdfs(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    return [
        p for p in sorted(input_dir.iterdir())
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() == ".pdf"
    ]


def optional_import_pdfplumber() -> Any:
    try:
        import pdfplumber  # type: ignore
        return pdfplumber
    except Exception:
        return None


def optional_import_fitz() -> Any:
    try:
        import fitz  # type: ignore
        return fitz
    except Exception:
        return None


def mime_for(path: Path) -> str:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if path.suffix.lower() == ".png":
        return "image/png"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def data_url(path: Path, mime: str | None = None) -> str:
    actual_mime = mime or mime_for(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{actual_mime};base64,{encoded}"


def clean_slide_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_tables_from_page(page: Any) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    if not page:
        return tables
    try:
        raw_tables = page.extract_tables() or []
    except Exception:
        raw_tables = []
    for idx, table in enumerate(raw_tables, start=1):
        if not table or not any(any(str(cell or "").strip() for cell in row or []) for row in table):
            continue
        headers = [str(cell or "").strip() for cell in (table[0] or [])]
        rows = [
            [str(cell or "").strip() for cell in (row or [])]
            for row in table[1:]
            if any(str(cell or "").strip() for cell in (row or []))
        ]
        tables.append({
            "tableId": f"table_{idx:02d}",
            "title": "",
            "headers": headers,
            "rows": rows,
        })
    return tables


def render_slide_image(fitz_module: Any, fitz_doc: Any, page_index: int, pdf_stem: str, slide_id: str) -> dict[str, Any] | None:
    if not fitz_module or not fitz_doc:
        return None
    try:
        page = fitz_doc.load_page(page_index)
        pix = page.get_pixmap(matrix=fitz_module.Matrix(2, 2), alpha=False)
        asset_name = f"{slugify(pdf_stem)}_{slide_id}.png"
        asset_path = ASSET_DIR / asset_name
        pix.save(str(asset_path))
        return {
            "imageId": f"{slide_id}_slide_image",
            "kind": "slide_image",
            "assetPath": str(asset_path.relative_to(BASE_DIR)),
            "mimeType": "image/png",
            "width": int(pix.width),
            "height": int(pix.height),
            "sha256": file_sha(asset_path),
        }
    except Exception as exc:
        warn(f"Could not render slide image {slide_id}: {exc}")
        return None


def extract_embedded_images(fitz_doc: Any, page_index: int, pdf_stem: str, slide_id: str) -> list[dict[str, Any]]:
    if not fitz_doc:
        return []
    images: list[dict[str, Any]] = []
    try:
        page = fitz_doc.load_page(page_index)
        for img_index, img in enumerate(page.get_images(full=True), start=1):
            xref = img[0]
            extracted = fitz_doc.extract_image(xref)
            blob = extracted.get("image")
            ext = extracted.get("ext") or "png"
            if not blob:
                continue
            asset_name = f"{slugify(pdf_stem)}_{slide_id}_fig{img_index:02d}.{ext}"
            asset_path = ASSET_DIR / asset_name
            asset_path.write_bytes(blob)
            images.append({
                "imageId": f"{slide_id}_fig{img_index:02d}",
                "kind": "embedded_figure",
                "assetPath": str(asset_path.relative_to(BASE_DIR)),
                "mimeType": mime_for(asset_path),
                "width": int(extracted.get("width") or 0),
                "height": int(extracted.get("height") or 0),
                "sha256": file_sha(asset_path),
            })
    except Exception as exc:
        warn(f"Could not extract embedded images for {slide_id}: {exc}")
    return images


def decompose_pdf(pdf_path: Path) -> dict[str, Any]:
    ensure_dirs()
    pdfplumber = optional_import_pdfplumber()
    fitz = optional_import_fitz()
    if not pdfplumber and not fitz:
        raise PipelineError("Install pdfplumber or pymupdf to decompose PDFs.")

    pdf_hash = file_sha(pdf_path)
    pdf_stem = pdf_path.stem
    log(f"Decomposing {pdf_path.name}")

    pdf_doc = None
    plumber_pdf = None
    try:
        if fitz:
            pdf_doc = fitz.open(str(pdf_path))
        if pdfplumber:
            plumber_pdf = pdfplumber.open(str(pdf_path))
        page_count = len(pdf_doc) if pdf_doc else len(plumber_pdf.pages)
        slides: list[dict[str, Any]] = []
        metadata = {}
        if pdf_doc:
            metadata.update({k: v for k, v in (pdf_doc.metadata or {}).items() if v})
        if plumber_pdf and getattr(plumber_pdf, "metadata", None):
            metadata.update({k: v for k, v in plumber_pdf.metadata.items() if v})

        for page_index in range(page_count):
            slide_num = page_index + 1
            slide_id = f"{slugify(pdf_stem)}_s{slide_num:04d}_{pdf_hash[:8]}"
            plumber_page = plumber_pdf.pages[page_index] if plumber_pdf else None
            text = ""
            if plumber_page:
                try:
                    text = plumber_page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                except Exception:
                    text = ""
            if not text and pdf_doc:
                try:
                    text = pdf_doc.load_page(page_index).get_text("text") or ""
                except Exception:
                    text = ""
            tables = extract_tables_from_page(plumber_page)
            slide_image = render_slide_image(fitz, pdf_doc, page_index, pdf_stem, slide_id) if pdf_doc else None
            embedded_images = extract_embedded_images(pdf_doc, page_index, pdf_stem, slide_id) if pdf_doc else []
            images = ([slide_image] if slide_image else []) + embedded_images
            slides.append({
                "slideId": slide_id,
                "sourceFile": pdf_path.name,
                "pdfSha256": pdf_hash,
                "slideIndex": slide_num,
                "pageIndex": page_index,
                "ocrText": clean_slide_text(text),
                "images": images,
                "tables": [
                    {**table, "tableId": f"{slide_id}_{table['tableId']}"}
                    for table in tables
                ],
                "metadata": {
                    "pageWidth": float(getattr(plumber_page, "width", 0) or 0),
                    "pageHeight": float(getattr(plumber_page, "height", 0) or 0),
                },
            })
    finally:
        if plumber_pdf:
            plumber_pdf.close()
        if pdf_doc:
            pdf_doc.close()

    payload = {
        "schemaVersion": "lecture-slide-decomposition-v1",
        "sourceFile": pdf_path.name,
        "sourcePath": str(pdf_path.relative_to(BASE_DIR)) if pdf_path.is_relative_to(BASE_DIR) else str(pdf_path),
        "pdfSha256": pdf_hash,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pageCount": len(slides),
        "pdfMetadata": metadata,
        "slides": slides,
    }
    out_path = SLIDES_DIR / f"{slugify(pdf_stem)}_slides.json"
    write_json(out_path, payload)
    log(f"  Slides -> {out_path.relative_to(BASE_DIR)}")
    return payload


def load_or_decompose_pdf(pdf_path: Path) -> dict[str, Any]:
    pdf_hash = file_sha(pdf_path)
    existing_path = SLIDES_DIR / f"{slugify(pdf_path.stem)}_slides.json"
    if existing_path.exists():
        try:
            payload = read_json(existing_path)
            if payload.get("pdfSha256") == pdf_hash and isinstance(payload.get("slides"), list):
                log(f"Using existing decomposed slides -> {existing_path.relative_to(BASE_DIR)}")
                return payload
            warn(f"Existing slide decomposition ignored because input hash changed: {existing_path.name}")
        except Exception as exc:
            warn(f"Existing slide decomposition could not be read ({exc}); recomposing PDF.")
    return decompose_pdf(pdf_path)


def chunk_list(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def clean_llm_json(raw: str) -> str:
    text = raw.strip().lstrip("\ufeff")
    text = re.sub(r"^\s*```+(?:json|JSON)?\s*", "", text)
    text = re.sub(r"\s*```+\s*$", "", text)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    return text.strip()


def extract_json_payload(text: str) -> str:
    first = -1
    open_ch = close_ch = ""
    for i, ch in enumerate(text):
        if ch == "{":
            first, open_ch, close_ch = i, "{", "}"
            break
        if ch == "[":
            first, open_ch, close_ch = i, "[", "]"
            break
    if first < 0:
        return text
    depth = 0
    in_string = False
    escape_next = False
    for i in range(first, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[first:i + 1]
    return text[first:]


def iter_complete_json_payloads(text: str) -> list[str]:
    payloads: list[str] = []
    starts = [i for i, ch in enumerate(text) if ch in "[{"]
    for first in starts:
        open_ch = text[first]
        close_ch = "]" if open_ch == "[" else "}"
        depth = 0
        in_string = False
        escape_next = False
        for i in range(first, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    payloads.append(text[first:i + 1])
                    break
    return sorted(set(payloads), key=len, reverse=True)


def load_largest_valid_json(raw: str) -> Any:
    cleaned = clean_llm_json(raw)
    attempts = [
        raw.strip(),
        cleaned,
        extract_json_payload(cleaned),
        *iter_complete_json_payloads(cleaned),
    ]
    seen: set[str] = set()
    for text in attempts:
        text = text.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    failure_type = classify_json_failure(cleaned)
    raise JsonParseFailure(f"{failure_type}: no complete valid JSON object or array found", failure_type)


def classify_json_failure(text: str) -> str:
    stripped = clean_llm_json(text)
    if not stripped:
        return "empty_response"

    depth_curly = 0
    depth_square = 0
    in_string = False
    escape_next = False
    repeated_prefixes = 0
    slide_prefixes: dict[str, int] = {}

    for i, ch in enumerate(stripped):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth_curly += 1
        elif ch == "}":
            depth_curly -= 1
        elif ch == "[":
            depth_square += 1
        elif ch == "]":
            depth_square -= 1

    for match in re.finditer(r'"slideId"\s*:\s*"([^"]+)"', stripped):
        slide_id = match.group(1)
        slide_prefixes[slide_id] = slide_prefixes.get(slide_id, 0) + 1
    repeated_prefixes = sum(1 for count in slide_prefixes.values() if count > 1)

    if in_string:
        return "truncation_unterminated_string"
    if depth_curly > 0 or depth_square > 0:
        return "truncation_missing_closing_bracket"
    if repeated_prefixes:
        return "truncation_repeated_object_prefix"
    return "invalid_json"


def parse_llm_json(raw: str, debug_name: str) -> Any:
    try:
        return load_largest_valid_json(raw)
    except JsonParseFailure as exc:
        failure_type = exc.failure_type
    debug_path = DEBUG_DIR / f"{debug_name}_raw_response.txt"
    debug_path.write_text(raw, encoding="utf-8")
    raise JsonParseFailure(
        f"Gemini returned invalid JSON ({failure_type}). Raw response saved to {debug_path.relative_to(BASE_DIR)}",
        failure_type,
    )


def write_debug_raw(source_file: str, phase: str, chunk_label: str, retry_label: str, raw: str) -> Path:
    safe_source = slugify(Path(source_file).stem)
    safe_chunk = slugify(str(chunk_label))
    safe_retry = slugify(str(retry_label))
    path = DEBUG_DIR / f"{safe_source}_{phase}_{safe_chunk}_{safe_retry}_raw_response.txt"
    path.write_text(raw, encoding="utf-8")
    return path


def repair_json_prompt(raw: str, expected_schema: str, expected_ids: list[str], error_message: str) -> str:
    return "\n".join([
        "Return corrected valid JSON only. Do not include markdown fences, prose, comments, or explanations.",
        "The prior response was invalid or failed schema validation.",
        f"Error: {error_message}",
        "Required JSON shape:",
        expected_schema,
        "Required slide/question IDs that must be present exactly once:",
        json.dumps(expected_ids, ensure_ascii=False),
        "Prior invalid response:",
        raw[:12000],
    ])


def is_truncation_failure(error: Exception | str) -> bool:
    text = str(error)
    return (
        "truncation_unterminated_string" in text
        or "truncation_missing_closing_bracket" in text
        or "truncation_repeated_object_prefix" in text
    )


def raw_gemini_call(api_key: str, prompt: str, temperature: float, max_tokens: int = 8192, timeout_seconds: int = 120) -> str:
    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            response = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise PipelineError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise PipelineError("repair_timeout" if timeout_seconds <= 60 else "Gemini request timed out") from exc
    candidates = response.get("candidates") or []
    if not candidates:
        raise PipelineError(f"Gemini returned no candidates: {json.dumps(response)[:300]}")
    parts = candidates[0].get("content", {}).get("parts") or []
    if not parts or "text" not in parts[0]:
        raise PipelineError("Gemini candidate had no text part.")
    return str(parts[0].get("text") or "")


def deterministic_normalize_slide(slide: dict[str, Any]) -> dict[str, Any]:
    text = slide.get("ocrText") or ""
    lower = text.lower()
    word_count = len(re.findall(r"[A-Za-z0-9]+", text))
    tables = slide.get("tables") or []
    images = slide.get("images") or []
    slide_types: list[str] = []
    if word_count < 12 and not tables and len(images) <= 1:
        slide_types.append("LOW_INFORMATION")
    if re.search(r"\b(agenda|objectives|outline|references|thank you|questions)\b", lower):
        slide_types.append("ADMINISTRATIVE")
    if re.search(r"\b(pathophys|mechanism|pathway|receptor|enzyme|mutation|deficiency)\b", lower):
        slide_types.append("MECHANISM")
    if re.search(r"\b(diagnosis|treatment|management|screening|therapy|symptom|sign|patient|clinical)\b", lower):
        slide_types.append("HIGH_YIELD_CLINICAL")
    if len(images) > 1:
        slide_types.append("IMAGE_HEAVY")
    if tables:
        slide_types.append("TABLE_HEAVY")
    if not slide_types:
        slide_types.append("RAPID_RECALL" if word_count >= 12 else "LOW_INFORMATION")
    if "LOW_INFORMATION" in slide_types or "ADMINISTRATIVE" in slide_types:
        yield_score = min(35, word_count * 2 + len(tables) * 10)
    else:
        yield_score = min(95, 30 + word_count + len(tables) * 15 + min(20, len(images) * 5))
    concepts = extract_candidate_concepts(text)
    facts = extract_fact_lines(text)
    return {
        "slideId": slide["slideId"],
        "slideType": sorted(set(slide_types), key=slide_types.index),
        "yieldScore": int(yield_score),
        "primaryConcepts": concepts[:4],
        "secondaryConcepts": concepts[4:10],
        "clinicalFacts": facts[:8],
        "diagnosticFacts": [f for f in facts if re.search(r"\b(diagnos|test|lab|finding|x-ray|ct|mri|ecg|ultrasound)\b", f, re.I)][:8],
        "managementFacts": [f for f in facts if re.search(r"\b(treat|therapy|manage|screen|prevent|administer|surgery)\b", f, re.I)][:8],
        "mechanismFacts": [f for f in facts if re.search(r"\b(cause|pathophys|mechanism|inhibit|activate|mutation|deficiency)\b", f, re.I)][:8],
        "images": slide.get("images") or [],
        "tables": slide.get("tables") or [],
        "questionPotential": int(yield_score if "ADMINISTRATIVE" not in slide_types else min(20, yield_score)),
        "groundingNotes": facts[:12],
        "sourceTextHash": short_hash(text),
    }


def extract_candidate_concepts(text: str) -> list[str]:
    lines = extract_fact_lines(text)
    concepts: list[str] = []
    for line in lines:
        cleaned = re.sub(r"^[\-*\d.)\s]+", "", line).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if 3 <= len(cleaned) <= 100:
            concepts.append(cleaned)
    seen: set[str] = set()
    out: list[str] = []
    for concept in concepts:
        key = concept.lower()
        if key not in seen:
            seen.add(key)
            out.append(concept)
    return out


def extract_fact_lines(text: str) -> list[str]:
    parts = re.split(r"\n|(?:\s+[;\u2022]\s+)", text)
    facts: list[str] = []
    for part in parts:
        p = re.sub(r"^[\s\-*\u2022\d.)]+", "", part).strip()
        p = re.sub(r"\s+", " ", p)
        if len(p) < 4:
            continue
        if len(p) > 220:
            p = p[:220].rsplit(" ", 1)[0]
        facts.append(p)
    return facts[:40]


def normalize_slides(slide_payload: dict[str, Any], generate: bool) -> dict[str, Any]:
    slides = slide_payload.get("slides") or []
    if not slides:
        raise PipelineError("No slides found for normalization.")
    normalized: list[dict[str, Any]] = []
    warnings: list[str] = []
    existing_by_id: dict[str, dict[str, Any]] = {}
    if generate:
        existing_by_id, existing_warnings = load_existing_normalized_slide_map(slide_payload)
        warnings.extend(existing_warnings)
    if generate:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise PipelineError("GEMINI_API_KEY is not set.")
        template = NORMALIZE_PROMPT.read_text(encoding="utf-8")
        missing_slides = [s for s in slides if s["slideId"] not in existing_by_id]
        normalized.extend(existing_by_id[s["slideId"]] for s in slides if s["slideId"] in existing_by_id)
        if existing_by_id:
            warnings.append(f"Resumed normalization from existing file: reused {len(existing_by_id)} slide(s).")
        for chunk_index, chunk in enumerate(split_slides_for_normalization(missing_slides), start=1):
            items, chunk_warnings = normalize_chunk_with_retries(
                api_key=api_key,
                template=template,
                chunk=chunk,
                source_file=slide_payload["sourceFile"],
                chunk_label=f"chunk{chunk_index}",
            )
            normalized.extend(items)
            warnings.extend(chunk_warnings)
    else:
        normalized = [deterministic_normalize_slide(slide) for slide in slides]
        warnings.append("dry-run: semantic normalization used deterministic local heuristics, not Gemini.")

    slide_order = {s["slideId"]: i for i, s in enumerate(slides)}
    normalized = validate_normalized_slides(normalized, {s["slideId"] for s in slides}, allow_missing=True)
    normalized.sort(key=lambda s: slide_order.get(s["slideId"], 10**9))
    normalized_ids = {s["slideId"] for s in normalized}
    skipped_ids = sorted({s["slideId"] for s in slides} - normalized_ids)
    if skipped_ids:
        warnings.append(f"Skipped {len(skipped_ids)} slide(s) after normalization failures: {', '.join(skipped_ids)}")
    payload = {
        "schemaVersion": "lecture-slide-normalized-v1",
        "sourceFile": slide_payload["sourceFile"],
        "pdfSha256": slide_payload["pdfSha256"],
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "normalizationWarnings": warnings,
        "normalizationStats": {
            "expectedSlideCount": len(slides),
            "normalizedSlideCount": len(normalized),
            "skippedSlideCount": len(skipped_ids),
            "defaultChunkSize": MAX_SLIDES_PER_CHUNK,
            "estimatedJsonBudgetChars": MAX_NORMALIZATION_ESTIMATED_JSON_CHARS,
        },
        "slides": normalized,
    }
    out_path = normalized_output_path_for_source(slide_payload["sourceFile"])
    write_json(out_path, payload)
    log(f"  Normalized -> {out_path.relative_to(BASE_DIR)}")
    return payload


def normalized_output_path_for_source(source_file: str) -> Path:
    return NORMALIZED_DIR / f"{slugify(Path(source_file).stem)}_normalized_slides.json"


def load_existing_normalized_slide_map(slide_payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    path = normalized_output_path_for_source(slide_payload["sourceFile"])
    if not path.exists():
        return {}, []
    try:
        payload = read_json(path)
    except Exception as exc:
        return {}, [f"Existing normalized file could not be read; ignoring it: {exc}"]
    if payload.get("pdfSha256") != slide_payload.get("pdfSha256"):
        return {}, ["Existing normalized file ignored because pdfSha256 does not match current decomposition."]
    expected = {s["slideId"] for s in slide_payload.get("slides") or []}
    by_id: dict[str, dict[str, Any]] = {}
    for item in payload.get("slides") or []:
        if isinstance(item, dict) and item.get("slideId") in expected and item.get("sourceTextHash"):
            by_id[item["slideId"]] = item
    return by_id, []


def estimate_normalization_json_chars(slide: dict[str, Any]) -> int:
    ocr_len = len(slide.get("ocrText") or "")
    images = len(slide.get("images") or [])
    tables = len(slide.get("tables") or [])
    return int(900 + min(ocr_len, MAX_NORMALIZATION_OCR_CHARS) * 2.2 + images * 160 + tables * 700)


def split_slides_for_normalization(slides: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_estimate = 0
    for slide in slides:
        estimate = estimate_normalization_json_chars(slide)
        if current and (
            len(current) >= MAX_SLIDES_PER_CHUNK
            or current_estimate + estimate > MAX_NORMALIZATION_ESTIMATED_JSON_CHARS
        ):
            chunks.append(current)
            current = []
            current_estimate = 0
        current.append(slide)
        current_estimate += estimate
    if current:
        chunks.append(current)
    return chunks


def compact_slides_for_prompt(chunk: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "slideId": s["slideId"],
        "slideIndex": s["slideIndex"],
        "ocrText": s.get("ocrText", ""),
        "images": [{"imageId": img.get("imageId"), "kind": img.get("kind")} for img in s.get("images", [])],
        "tables": s.get("tables", []),
    } for s in chunk]


def normalized_schema_required_keys() -> str:
    return json.dumps({
        "slides": [{
            "slideId": "same input slideId",
            "slideType": ["HIGH_YIELD_CLINICAL"],
            "yieldScore": 0,
            "primaryConcepts": [],
            "secondaryConcepts": [],
            "clinicalFacts": [],
            "diagnosticFacts": [],
            "managementFacts": [],
            "mechanismFacts": [],
            "images": [],
            "tables": [],
            "questionPotential": 0,
            "groundingNotes": [],
        }]
    }, ensure_ascii=False)


def extract_normalized_items(parsed: Any, by_id: dict[str, dict[str, Any]], chunk_label: str) -> list[dict[str, Any]]:
    items = parsed.get("slides") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        raise PipelineError(f"Normalization {chunk_label} did not return a slides array.")

    expected_ids = set(by_id)
    seen_ids: set[str] = set()
    merged: list[dict[str, Any]] = []
    required = [
        "slideId", "slideType", "yieldScore", "primaryConcepts",
        "secondaryConcepts", "clinicalFacts", "diagnosticFacts",
        "managementFacts", "mechanismFacts", "images", "tables",
        "questionPotential", "groundingNotes",
    ]
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise PipelineError(f"Normalization {chunk_label} item {idx} is not an object.")
        slide_id = str(item.get("slideId") or "")
        if slide_id not in expected_ids:
            raise PipelineError(f"Normalization {chunk_label} returned unknown slideId: {slide_id or '(missing)'}")
        if slide_id in seen_ids:
            raise PipelineError(f"Normalization {chunk_label} returned duplicate slideId: {slide_id}")
        missing = [key for key in required if key not in item]
        if missing:
            raise PipelineError(f"Normalization {chunk_label} slide {slide_id} missing required keys: {', '.join(missing)}")
        seen_ids.add(slide_id)
        merged.append(merge_normalized_with_source(item, by_id[slide_id]))
    missing_ids = expected_ids - seen_ids
    if missing_ids:
        raise PipelineError(f"Normalization {chunk_label} omitted slideIds: {', '.join(sorted(missing_ids))}")
    return merged


def call_normalization_once(
    api_key: str,
    template: str,
    chunk: list[dict[str, Any]],
    source_file: str,
    chunk_label: str,
    retry_label: str,
    repair_raw: str | None = None,
    repair_error: str = "",
) -> list[dict[str, Any]]:
    by_id = {s["slideId"]: s for s in chunk}
    expected_ids = list(by_id)
    if repair_raw is None:
        prompt = template.replace("{{SLIDES_JSON}}", json.dumps(compact_slides_for_prompt(chunk), ensure_ascii=False))
    else:
        prompt = repair_json_prompt(
            raw=repair_raw,
            expected_schema=normalized_schema_required_keys(),
            expected_ids=expected_ids,
            error_message=repair_error,
        )
    raw = raw_gemini_call(api_key, prompt, temperature=0.0 if repair_raw else 0.15)
    write_debug_raw(source_file, "normalize", chunk_label, retry_label, raw)
    parsed = load_largest_valid_json(raw)
    return extract_normalized_items(parsed, by_id, chunk_label)


def normalize_chunk_with_retries(
    api_key: str,
    template: str,
    chunk: list[dict[str, Any]],
    source_file: str,
    chunk_label: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    last_raw = ""
    last_error = ""

    try:
        return call_normalization_once(api_key, template, chunk, source_file, chunk_label, "attempt0"), warnings
    except Exception as exc:
        last_error = str(exc)
        raw_path = DEBUG_DIR / f"{slugify(Path(source_file).stem)}_normalize_{slugify(chunk_label)}_attempt0_raw_response.txt"
        if raw_path.exists():
            last_raw = raw_path.read_text(encoding="utf-8", errors="replace")
        warnings.append(f"Normalization {chunk_label}: attempt0 failed: {last_error}")

    if not is_truncation_failure(last_error):
        try:
            return call_normalization_once(
                api_key, template, chunk, source_file, chunk_label, "retry1_repair",
                repair_raw=last_raw, repair_error=last_error,
            ), warnings
        except Exception as exc:
            last_error = str(exc)
            warnings.append(f"Normalization {chunk_label}: retry1 repair failed: {last_error}")
    else:
        warnings.append(f"Normalization {chunk_label}: truncation detected; splitting chunk without same-size repair.")

    if len(chunk) > SMALL_NORMALIZATION_CHUNK_SIZE:
        collected: list[dict[str, Any]] = []
        for sub_index, sub_chunk in enumerate(split_slides_for_normalization(chunk), start=1):
            if len(sub_chunk) == len(chunk):
                sub_chunk = chunk[:SMALL_NORMALIZATION_CHUNK_SIZE]
                remainder = chunk[SMALL_NORMALIZATION_CHUNK_SIZE:]
                split_chunks = [sub_chunk] + ([remainder] if remainder else [])
                remaining_collected: list[dict[str, Any]] = []
                for forced_index, forced_chunk in enumerate(split_chunks, start=1):
                    sub_items, sub_warnings = normalize_chunk_with_retries(
                        api_key, template, forced_chunk, source_file, f"{chunk_label}_retry2_forced{forced_index}"
                    )
                    remaining_collected.extend(sub_items)
                    warnings.extend(sub_warnings)
                return remaining_collected, warnings
            sub_items, sub_warnings = normalize_chunk_with_retries(
                api_key, template, sub_chunk, source_file, f"{chunk_label}_retry2_sub{sub_index}"
            )
            collected.extend(sub_items)
            warnings.extend(sub_warnings)
        return collected, warnings

    if len(chunk) > ISOLATED_NORMALIZATION_CHUNK_SIZE:
        collected = []
        for sub_index, slide in enumerate(chunk, start=1):
            sub_items, sub_warnings = normalize_chunk_with_retries(
                api_key, template, [slide], source_file, f"{chunk_label}_retry3_slide{sub_index}"
            )
            collected.extend(sub_items)
            warnings.extend(sub_warnings)
        return collected, warnings

    slide_id = chunk[0].get("slideId", "(unknown)") if chunk else "(empty)"
    warnings.append(f"Normalization {chunk_label}: skipped slide {slide_id} after repeated JSON/schema failures: {last_error}")
    return [], warnings


def merge_normalized_with_source(item: dict[str, Any], source_slide: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(item)
    merged["slideId"] = source_slide["slideId"]
    merged["images"] = source_slide.get("images") or []
    merged["tables"] = source_slide.get("tables") or []
    merged["sourceTextHash"] = short_hash(source_slide.get("ocrText") or "")
    return merged


def validate_normalized_slides(slides: list[dict[str, Any]], expected_ids: set[str], allow_missing: bool = False) -> list[dict[str, Any]]:
    seen: set[str] = set()
    clean: list[dict[str, Any]] = []
    for idx, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            raise PipelineError(f"Normalized slide {idx} is not an object.")
        slide_id = str(slide.get("slideId") or "")
        if not slide_id or slide_id not in expected_ids:
            raise PipelineError(f"Normalized slide {idx} has unknown slideId.")
        if slide_id in seen:
            raise PipelineError(f"Duplicate normalized slideId: {slide_id}")
        seen.add(slide_id)
        types = slide.get("slideType")
        if isinstance(types, str):
            types = [types]
        if not isinstance(types, list) or not types:
            types = ["LOW_INFORMATION"]
        types = [str(t).strip().upper() for t in types if str(t).strip()]
        bad = [t for t in types if t not in SLIDE_TYPES]
        if bad:
            raise PipelineError(f"{slide_id}: unknown slideType values: {bad}")
        slide["slideType"] = types
        for key in ["yieldScore", "questionPotential"]:
            try:
                slide[key] = max(0, min(100, int(slide.get(key) or 0)))
            except Exception:
                slide[key] = 0
        for key in [
            "primaryConcepts",
            "secondaryConcepts",
            "clinicalFacts",
            "diagnosticFacts",
            "managementFacts",
            "mechanismFacts",
            "images",
            "tables",
            "groundingNotes",
        ]:
            if not isinstance(slide.get(key), list):
                slide[key] = []
        clean.append(slide)
    missing = expected_ids - seen
    if missing and not allow_missing:
        raise PipelineError(f"Normalization omitted {len(missing)} slide(s).")
    return clean


def empty_memory() -> dict[str, Any]:
    return {
        "schemaVersion": "lecture-slide-rolling-memory-v1",
        "conceptFrequencyMap": {},
        "diagnosisUsageMap": {},
        "distractorUsageMap": {},
        "stemTemplateUsageMap": {},
        "imageUsageMap": {},
        "educationalObjectiveMap": {},
        "generatedQuestionFingerprints": {},
    }


def increment_map(mapping: dict[str, int], key: str, amount: int = 1) -> None:
    key = normalize_key(key)
    if not key:
        return
    mapping[key] = int(mapping.get(key, 0)) + amount


def normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def update_memory_from_slides(memory: dict[str, Any], slides: list[dict[str, Any]]) -> None:
    for slide in slides:
        for concept in (slide.get("primaryConcepts") or []) + (slide.get("secondaryConcepts") or []):
            increment_map(memory["conceptFrequencyMap"], str(concept))


def slide_redundancy(memory: dict[str, Any], slide: dict[str, Any]) -> float:
    concepts = [normalize_key(c) for c in slide.get("primaryConcepts", []) if normalize_key(c)]
    if not concepts:
        return 0.0
    hits = sum(1 for c in concepts if int(memory["conceptFrequencyMap"].get(c, 0)) > 1)
    return hits / max(1, len(concepts))


def allocate_questions(normalized_payload: dict[str, Any], memory: dict[str, Any]) -> list[dict[str, Any]]:
    update_memory_from_slides(memory, normalized_payload.get("slides") or [])
    allocations: list[dict[str, Any]] = []
    allocated_concepts: dict[str, int] = {}
    for slide in normalized_payload.get("slides") or []:
        types = set(slide.get("slideType") or [])
        redundancy = slide_redundancy(memory, slide)
        primary_keys = [normalize_key(c) for c in slide.get("primaryConcepts", []) if normalize_key(c)]
        prior_alloc_hits = sum(1 for key in primary_keys if allocated_concepts.get(key, 0) > 0)
        sequential_redundancy = prior_alloc_hits / max(1, len(primary_keys))
        effective_redundancy = max(redundancy, sequential_redundancy)
        richness = (
            len(slide.get("clinicalFacts") or [])
            + len(slide.get("diagnosticFacts") or [])
            + len(slide.get("managementFacts") or [])
            + len(slide.get("mechanismFacts") or [])
            + len(slide.get("tables") or []) * 2
            + len(slide.get("images") or [])
        )
        fact_categories = sum(
            1 for key in ["clinicalFacts", "diagnosticFacts", "managementFacts", "mechanismFacts"]
            if slide.get(key)
        )
        potential = int(slide.get("questionPotential") or 0)
        count = 0
        reason = "low information or administrative"
        if "ADMINISTRATIVE" in types or "TRANSITION_SLIDE" in types:
            count = 0
        elif (
            potential >= 85
            and richness >= 12
            and fact_categories >= 2
            and effective_redundancy < 0.35
            and ("HIGH_YIELD_CLINICAL" in types or "MECHANISM" in types)
        ):
            count = 2
            reason = "high yield, rich, low redundancy"
        elif potential >= 50 and richness >= 3 and effective_redundancy < 0.80:
            count = 1
            reason = "sufficient yield and distinct content"
        elif ("IMAGE_HEAVY" in types or "TABLE_HEAVY" in types) and potential >= 40 and effective_redundancy < 0.85:
            count = 1
            reason = "image or table has question value"
        else:
            count = 0
        for key in primary_keys:
            allocated_concepts[key] = allocated_concepts.get(key, 0) + count
        allocations.append({
            "slideId": slide["slideId"],
            "questionCount": count,
            "reason": reason,
            "yieldScore": slide.get("yieldScore", 0),
            "redundancyScore": round(effective_redundancy, 3),
            "contentRichness": richness,
            "slide": slide,
        })
    return allocations


def dry_run_question(allocation: dict[str, Any], number: int) -> dict[str, Any]:
    slide = allocation["slide"]
    concept = first_nonempty(slide.get("primaryConcepts")) or first_nonempty(slide.get("clinicalFacts")) or "slide-supported concept"
    facts = (slide.get("clinicalFacts") or slide.get("groundingNotes") or [concept])[:3]
    fact_sentence = " ".join(str(f).rstrip(".") + "." for f in facts if str(f).strip())
    if not fact_sentence:
        fact_sentence = f"The slide supports the concept: {concept}."
    stem = (
        f"A patient is evaluated for a finding related to {concept}. "
        f"The lecture slide emphasizes the following slide-supported information: {fact_sentence} "
        "The clinician wants to identify the best matching high-yield concept from the slide. "
        "Which of the following is the best answer?"
    )
    choices = [
        {"label": "A", "text": concept[:120]},
        {"label": "B", "text": "Closely related distractor from the same topic area"},
        {"label": "C", "text": "Alternative diagnosis or management step from the same system"},
        {"label": "D", "text": "Related mechanism or clinical mimic"},
    ]
    return {
        "slideId": slide["slideId"],
        "questionKind": "clinical_vignette",
        "stemTemplate": "dry_run_clinical_transform",
        "testedConcept": concept,
        "diagnosisOrTarget": concept,
        "distractorFamily": "same topic area",
        "stem": stem,
        "answerChoices": choices,
        "correctAnswer": "A",
        "correctExplanation": "This dry-run question preserves pipeline structure without calling Gemini.",
        "incorrectExplanations": [
            {"label": "B", "explanation": "Dry-run distractor placeholder."},
            {"label": "C", "explanation": "Dry-run distractor placeholder."},
            {"label": "D", "explanation": "Dry-run distractor placeholder."},
        ],
        "educationalObjective": f"Recognize the slide-supported concept: {concept}.",
        "retrievalTag": concept[:80],
        "reviewPearl": fact_sentence[:220],
        "imageRouting": dry_run_image_routing(slide, number),
        "tableUse": [{"tableId": t.get("tableId"), "placement": "explanation"} for t in slide.get("tables", [])],
        "sourceFactIds": [],
    }


def dry_run_image_routing(slide: dict[str, Any], number: int) -> list[dict[str, str]]:
    images = slide.get("images") or []
    if not images:
        return []
    if "IMAGE_HEAVY" in set(slide.get("slideType") or []) and number % 3 == 0:
        return [{"imageId": images[0].get("imageId", ""), "placement": "stem"}]
    return [{"imageId": images[0].get("imageId", ""), "placement": "explanation"}]


def first_nonempty(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def slide_allowed_grounding(slide: dict[str, Any]) -> dict[str, Any]:
    fact_text = normalized_slide_fact_text(slide)
    tokens = {
        tok.lower()
        for tok in re.findall(r"\b[A-Za-z][A-Za-z0-9+\-]{2,}\b", fact_text)
        if tok.lower() not in COMMON_CLINICAL_WORDS
    }
    grounding = build_grounding_index({"slides": [slide]}).get(slide["slideId"], {})
    tokens.update(grounding.get("tokens") or set())
    phrases: list[str] = []
    for key in [
        "primaryConcepts",
        "secondaryConcepts",
        "clinicalFacts",
        "diagnosticFacts",
        "managementFacts",
        "mechanismFacts",
        "groundingNotes",
    ]:
        values = slide.get(key) or []
        if isinstance(values, list):
            for value in values:
                text = clean_sentence(value)
                if text:
                    phrases.append(text)
    for table in slide.get("tables") or []:
        if isinstance(table, dict):
            title = clean_sentence(table.get("title") or "")
            if title:
                phrases.append(title)
            for header in table.get("headers") or []:
                text = clean_sentence(header)
                if text:
                    phrases.append(text)
    distractor_pool: list[str] = []
    for text in phrases:
        if len(distractor_pool) >= 30:
            break
        if text and text not in distractor_pool:
            distractor_pool.append(text[:180])
    return {
        "allowedMedicalTerms": sorted({t for t in tokens if t and len(t) >= 3})[:220],
        "allowedDistractorPool": distractor_pool,
        "groundingFacts": phrases[:40],
    }


def compact_generation_allocation(allocation: dict[str, Any]) -> dict[str, Any]:
    out = {key: value for key, value in allocation.items() if key != "slide"}
    slide = allocation.get("slide") or {}
    out["slide"] = slide
    allowed = slide_allowed_grounding(slide)
    out["ALLOWED_MEDICAL_TERMS"] = allowed["allowedMedicalTerms"]
    out["ALLOWED_DISTRACTOR_POOL"] = allowed["allowedDistractorPool"]
    out["GROUNDING_FACTS"] = allowed["groundingFacts"]
    return out


def generate_questions(normalized_payload: dict[str, Any], allocations: list[dict[str, Any]], memory: dict[str, Any], generate: bool) -> list[dict[str, Any]]:
    work = [a for a in allocations if int(a.get("questionCount") or 0) > 0]
    questions: list[dict[str, Any]] = []
    if not work:
        return questions
    if generate:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise PipelineError("GEMINI_API_KEY is not set.")
        template = GENERATE_PROMPT.read_text(encoding="utf-8")
        for chunk_index, chunk in enumerate(chunk_list(work, MAX_GENERATION_ALLOCS_PER_CHUNK), start=1):
            items, chunk_warnings = generate_question_chunk_with_retries(
                api_key=api_key,
                template=template,
                chunk=chunk,
                memory=memory,
                source_file=normalized_payload["sourceFile"],
                chunk_label=f"chunk{chunk_index}",
            )
            for warning in chunk_warnings:
                warn(warning)
            for item in items:
                questions.append(item)
                update_memory_from_question(memory, item)
    else:
        n = 1
        for allocation in work:
            for _ in range(int(allocation.get("questionCount") or 0)):
                q = dry_run_question(allocation, n)
                questions.append(q)
                update_memory_from_question(memory, q)
                n += 1
    gen_path = GENERATED_DIR / f"{slugify(Path(normalized_payload['sourceFile']).stem)}_generated_questions.json"
    write_json(gen_path, {"questions": questions})
    mem_path = MEMORY_DIR / f"{slugify(Path(normalized_payload['sourceFile']).stem)}_rolling_memory.json"
    write_json(mem_path, memory)
    log(f"  Generated -> {gen_path.relative_to(BASE_DIR)}")
    log(f"  Memory -> {mem_path.relative_to(BASE_DIR)}")
    return questions


def question_schema_required_keys() -> str:
    return json.dumps({
        "questions": [{
            "slideId": "",
            "questionKind": "clinical_vignette",
            "stemTemplate": "",
            "testedConcept": "",
            "diagnosisOrTarget": "",
            "distractorFamily": "",
            "stem": "",
            "answerChoices": [
                {"label": "A", "text": ""},
                {"label": "B", "text": ""},
                {"label": "C", "text": ""},
                {"label": "D", "text": ""},
            ],
            "correctAnswer": "A",
            "correctExplanation": "",
            "incorrectExplanations": [
                {"label": "B", "explanation": ""},
                {"label": "C", "explanation": ""},
                {"label": "D", "explanation": ""},
            ],
            "educationalObjective": "",
            "retrievalTag": "",
            "reviewPearl": "",
            "imageRouting": [],
            "tableUse": [],
            "sourceFactIds": [],
        }]
    }, ensure_ascii=False)


def extract_generated_question_items(parsed: Any, allocations: list[dict[str, Any]], chunk_label: str) -> list[dict[str, Any]]:
    items = parsed.get("questions") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list):
        raise PipelineError(f"Generation {chunk_label} did not return a questions array.")
    expected_count = sum(int(a.get("questionCount") or 0) for a in allocations)
    allowed_slide_ids = {a["slideId"] for a in allocations}
    if len(items) != expected_count:
        raise PipelineError(f"Generation {chunk_label} returned {len(items)} questions; expected {expected_count}.")
    required = [
        "slideId", "questionKind", "stemTemplate", "testedConcept",
        "diagnosisOrTarget", "distractorFamily", "stem", "answerChoices",
        "correctAnswer", "correctExplanation", "incorrectExplanations",
        "educationalObjective", "retrievalTag", "reviewPearl",
        "imageRouting", "tableUse", "sourceFactIds",
    ]
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise PipelineError(f"Generation {chunk_label} item {idx} is not an object.")
        missing = [key for key in required if key not in item]
        if missing:
            raise PipelineError(f"Generation {chunk_label} question {idx} missing required keys: {', '.join(missing)}")
        if item.get("slideId") not in allowed_slide_ids:
            raise PipelineError(f"Generation {chunk_label} question {idx} references unknown slideId: {item.get('slideId')}")
        choices = item.get("answerChoices")
        if not isinstance(choices, list) or len(choices) != 4:
            raise PipelineError(f"Generation {chunk_label} question {idx} does not have exactly 4 answerChoices.")
    return items


def call_generation_once(
    api_key: str,
    template: str,
    chunk: list[dict[str, Any]],
    memory: dict[str, Any],
    source_file: str,
    chunk_label: str,
    retry_label: str,
    repair_raw: str | None = None,
    repair_error: str = "",
) -> list[dict[str, Any]]:
    expected_ids = [a["slideId"] for a in chunk]
    if repair_raw is None:
        prompt_allocations = [compact_generation_allocation(a) for a in chunk]
        prompt = (
            template
            .replace("{{ALLOCATIONS_JSON}}", json.dumps(prompt_allocations, ensure_ascii=False))
            .replace("{{MEMORY_JSON}}", json.dumps(compact_memory(memory), ensure_ascii=False))
        )
    else:
        prompt = repair_json_prompt(
            raw=repair_raw,
            expected_schema=question_schema_required_keys(),
            expected_ids=expected_ids,
            error_message=repair_error,
        )
    raw = raw_gemini_call(api_key, prompt, temperature=0.0 if repair_raw else 0.35, max_tokens=12000)
    write_debug_raw(source_file, "generate", chunk_label, retry_label, raw)
    parsed = load_largest_valid_json(raw)
    return extract_generated_question_items(parsed, chunk, chunk_label)


def generate_question_chunk_with_retries(
    api_key: str,
    template: str,
    chunk: list[dict[str, Any]],
    memory: dict[str, Any],
    source_file: str,
    chunk_label: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    last_raw = ""
    last_error = ""

    try:
        return call_generation_once(api_key, template, chunk, memory, source_file, chunk_label, "attempt0"), warnings
    except Exception as exc:
        last_error = str(exc)
        raw_path = DEBUG_DIR / f"{slugify(Path(source_file).stem)}_generate_{slugify(chunk_label)}_attempt0_raw_response.txt"
        if raw_path.exists():
            last_raw = raw_path.read_text(encoding="utf-8", errors="replace")
        warnings.append(f"Generation {chunk_label}: attempt0 failed: {last_error}")

    if not is_truncation_failure(last_error):
        try:
            return call_generation_once(
                api_key, template, chunk, memory, source_file, chunk_label, "retry1_repair",
                repair_raw=last_raw, repair_error=last_error,
            ), warnings
        except Exception as exc:
            last_error = str(exc)
            warnings.append(f"Generation {chunk_label}: retry1 repair failed: {last_error}")
    else:
        warnings.append(f"Generation {chunk_label}: truncation detected; splitting chunk without same-size repair.")

    if len(chunk) > 2:
        collected: list[dict[str, Any]] = []
        for sub_index, sub_chunk in enumerate(chunk_list(chunk, max(1, len(chunk) // 2)), start=1):
            sub_items, sub_warnings = generate_question_chunk_with_retries(
                api_key, template, sub_chunk, memory, source_file, f"{chunk_label}_retry2_sub{sub_index}"
            )
            collected.extend(sub_items)
            warnings.extend(sub_warnings)
        return collected, warnings

    if len(chunk) > 1:
        collected = []
        for sub_index, allocation in enumerate(chunk, start=1):
            sub_items, sub_warnings = generate_question_chunk_with_retries(
                api_key, template, [allocation], memory, source_file, f"{chunk_label}_retry3_slide{sub_index}"
            )
            collected.extend(sub_items)
            warnings.extend(sub_warnings)
        return collected, warnings

    warnings.append(f"Generation {chunk_label}: skipped slide {chunk[0].get('slideId', '(unknown)')} after repeated JSON/schema failures: {last_error}")
    return [], warnings


def collect_generation_validation(
    normalized_payload: dict[str, Any],
    questions: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]], dict[str, Any]]:
    grounding_findings = semantic_grounding_findings(questions, normalized_payload)
    diversity_report = question_quality_and_diversity(questions)
    app_payload = build_app_ready_payload(normalized_payload, questions)
    errors = validate_app_ready_payload(app_payload)
    errors.extend(
        f"Semantic grounding Q{f.get('questionIndex', '?')}: {f.get('issue')} {f.get('detail')}"
        for f in grounding_findings
        if f.get("severity") == "error"
    )
    errors.extend(
        f"Question quality Q{f.get('questionIndex', '?')}: {f.get('issue')} {f.get('detail')}"
        for f in diversity_report.get("findings", [])
        if f.get("severity") == "error"
    )
    return app_payload, errors, grounding_findings, diversity_report


def repair_question_prompt(
    original_question: dict[str, Any],
    slide: dict[str, Any],
    unsupported_terms: list[str],
    attempt: int,
) -> str:
    allowed = slide_allowed_grounding(slide)
    return f"""
You are repairing one NBME-style question generated from one normalized lecture slide.

Return valid JSON only in this exact shape:
{question_schema_required_keys()}

Return exactly 1 question.
Use the same slideId.
Use exactly 4 answer choices labeled A, B, C, D.
Do not include these unsupported terms unless they are present in ALLOWED_MEDICAL_TERMS:
{json.dumps(unsupported_terms, ensure_ascii=False)}

STRICT GROUNDING RULES:
- Source of truth is the normalized slide JSON below.
- Every answer choice and every explanation claim must use only concepts from ALLOWED_MEDICAL_TERMS or generic nonmedical vignette wording.
- Distractors must come from ALLOWED_DISTRACTOR_POOL, same-slide normalized facts, signs, mechanisms, management choices, or abnormalities.
- Never invent outside diseases, drugs, tests, procedures, mechanisms, epidemiology, or risk factors.
- If the old question used unsupported distractors, replace them with grounded same-slide alternatives.
- Clinical prose may be natural, but medical content must remain slide-grounded.

Attempt: {attempt}

NORMALIZED_SLIDE_JSON:
{json.dumps(slide, ensure_ascii=False)}

ALLOWED_MEDICAL_TERMS:
{json.dumps(allowed["allowedMedicalTerms"], ensure_ascii=False)}

ALLOWED_DISTRACTOR_POOL:
{json.dumps(allowed["allowedDistractorPool"], ensure_ascii=False)}

GROUNDING_FACTS:
{json.dumps(allowed["groundingFacts"], ensure_ascii=False)}

ORIGINAL_QUESTION_TO_REPAIR:
{json.dumps(original_question, ensure_ascii=False)}
""".strip()


def call_question_repair_once(
    api_key: str,
    source_file: str,
    q_index: int,
    original_question: dict[str, Any],
    slide: dict[str, Any],
    unsupported_terms: list[str],
    attempt: int,
) -> dict[str, Any]:
    prompt = repair_question_prompt(original_question, slide, unsupported_terms, attempt)
    raw = raw_gemini_call(api_key, prompt, temperature=0.15, max_tokens=8192, timeout_seconds=45)
    write_debug_raw(source_file, "repair_question", f"q{q_index:03d}", f"attempt{attempt}", raw)
    parsed = load_largest_valid_json(raw)
    allocation = {
        "slideId": slide["slideId"],
        "questionCount": 1,
        "slide": slide,
    }
    items = extract_generated_question_items(parsed, [allocation], f"repair_q{q_index:03d}_attempt{attempt}")
    return items[0]


def repair_progress_path(stem: str) -> Path:
    return REPORT_DIR / f"{stem}_repair_progress.json"


def timestamp_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def empty_repair_progress(source_file: str, total_failed: int) -> dict[str, Any]:
    return {
        "sourceFile": source_file,
        "totalFailedQuestions": total_failed,
        "completedRepairs": 0,
        "droppedQuestions": 0,
        "currentQuestionId": None,
        "lastSuccessfulTimestamp": None,
        "lastError": "",
        "repairedQuestionsByIndex": {},
        "droppedByIndex": {},
    }


def write_repair_progress(path: Path, progress: dict[str, Any]) -> None:
    progress["completedRepairs"] = len(progress.get("repairedQuestionsByIndex") or {})
    progress["droppedQuestions"] = len(progress.get("droppedByIndex") or {})
    write_json(path, progress)


def validate_single_repair_candidate(
    normalized_payload: dict[str, Any],
    slide: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[bool, list[str], list[str]]:
    single_norm = dict(normalized_payload)
    single_norm["slides"] = [slide]
    _, single_errors, single_grounding, _ = collect_generation_validation(single_norm, [candidate])
    unsupported: list[str] = []
    for finding in single_grounding:
        if finding.get("severity") == "error":
            unsupported.extend(str(v) for v in finding.get("detail") or [])
    return not single_errors, single_errors, unsupported


def recover_repair_debug_artifacts(
    stem: str,
    normalized_payload: dict[str, Any],
    questions: list[dict[str, Any]],
    failed_by_index: dict[int, list[str]],
    slide_by_id: dict[str, dict[str, Any]],
    progress: dict[str, Any],
) -> None:
    repaired = progress.setdefault("repairedQuestionsByIndex", {})
    dropped = progress.setdefault("droppedByIndex", {})
    for idx in sorted(failed_by_index):
        key = str(idx)
        if key in repaired or key in dropped:
            continue
        question = questions[idx - 1]
        slide = slide_by_id.get(str(question.get("slideId") or ""))
        if not slide:
            continue
        for raw_path in sorted(DEBUG_DIR.glob(f"{stem}_repair_question_q{idx:03d}_attempt*_raw_response.txt")):
            try:
                parsed = load_largest_valid_json(raw_path.read_text(encoding="utf-8", errors="replace"))
                candidate = extract_generated_question_items(
                    parsed,
                    [{"slideId": slide["slideId"], "questionCount": 1, "slide": slide}],
                    f"recover_repair_q{idx:03d}",
                )[0]
                ok, errors, _ = validate_single_repair_candidate(normalized_payload, slide, candidate)
                if ok:
                    repaired[key] = candidate
                    progress["lastSuccessfulTimestamp"] = timestamp_iso()
                    progress["lastError"] = ""
                    break
                progress["lastError"] = "; ".join(errors[:4])
            except Exception as exc:
                progress["lastError"] = str(exc)


def repair_existing_questions(pdf_path: Path) -> Path:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise PipelineError("GEMINI_API_KEY is not set.")
    stem = slugify(pdf_path.stem)
    normalized_path = NORMALIZED_DIR / f"{stem}_normalized_slides.json"
    generated_path = GENERATED_DIR / f"{stem}_generated_questions.json"
    if not normalized_path.exists():
        raise PipelineError(f"Missing normalized slides file: {normalized_path.relative_to(BASE_DIR)}")
    if not generated_path.exists():
        raise PipelineError(f"Missing generated questions file: {generated_path.relative_to(BASE_DIR)}")
    normalized_payload = read_json(normalized_path)
    generated_payload = read_json(generated_path)
    questions = generated_payload.get("questions") if isinstance(generated_payload, dict) else generated_payload
    if not isinstance(questions, list):
        raise PipelineError("Existing generated questions file does not contain a questions array.")

    original_question_count = len(questions)
    _, before_errors, before_grounding, _ = collect_generation_validation(normalized_payload, questions)
    failed_by_index = {
        int(f["questionIndex"]): list(f.get("detail") or [])
        for f in before_grounding
        if f.get("severity") == "error" and f.get("issue") == "unsupported_medical_claim_terms"
    }
    slide_by_id = {s["slideId"]: s for s in normalized_payload.get("slides") or []}
    progress_path = repair_progress_path(stem)
    if progress_path.exists():
        progress = read_json(progress_path)
        if not isinstance(progress, dict):
            progress = empty_repair_progress(normalized_payload["sourceFile"], len(failed_by_index))
        progress["totalFailedQuestions"] = len(failed_by_index)
    else:
        progress = empty_repair_progress(normalized_payload["sourceFile"], len(failed_by_index))
    recover_repair_debug_artifacts(stem, normalized_payload, questions, failed_by_index, slide_by_id, progress)
    write_repair_progress(progress_path, progress)

    repair_log: list[dict[str, Any]] = []

    for idx, question in enumerate(questions, start=1):
        if idx not in failed_by_index:
            continue
        key = str(idx)
        if key in (progress.get("repairedQuestionsByIndex") or {}) or key in (progress.get("droppedByIndex") or {}):
            continue
        slide = slide_by_id.get(str(question.get("slideId") or ""))
        if not slide:
            progress.setdefault("droppedByIndex", {})[key] = {
                "questionIndex": idx,
                "reason": "unknown slideId",
                "slideId": question.get("slideId"),
            }
            write_repair_progress(progress_path, progress)
            continue
        candidate = question
        unsupported = failed_by_index[idx]
        accepted = False
        attempt_notes: list[str] = []
        progress["currentQuestionId"] = idx
        progress["lastError"] = ""
        write_repair_progress(progress_path, progress)
        for attempt in range(1, 3):
            try:
                candidate = call_question_repair_once(api_key, normalized_payload["sourceFile"], idx, candidate, slide, unsupported, attempt)
                ok, single_errors, next_unsupported = validate_single_repair_candidate(normalized_payload, slide, candidate)
                if ok:
                    progress.setdefault("repairedQuestionsByIndex", {})[key] = candidate
                    progress["lastSuccessfulTimestamp"] = timestamp_iso()
                    progress["lastError"] = ""
                    write_repair_progress(progress_path, progress)
                    accepted = True
                    break
                unsupported = next_unsupported
                attempt_notes.append("; ".join(single_errors[:6]))
            except Exception as exc:
                error_text = str(exc)
                attempt_notes.append(error_text)
                progress["lastError"] = error_text
                write_repair_progress(progress_path, progress)
                if "repair_timeout" in error_text:
                    progress.setdefault("droppedByIndex", {})[key] = {
                        "questionIndex": idx,
                        "slideId": question.get("slideId"),
                        "unsupportedTerms": failed_by_index[idx],
                        "reason": "repair_timeout",
                        "attemptNotes": attempt_notes,
                    }
                    write_repair_progress(progress_path, progress)
                    break
        if not accepted and key not in (progress.get("droppedByIndex") or {}):
            progress.setdefault("droppedByIndex", {})[key] = {
                "questionIndex": idx,
                "slideId": question.get("slideId"),
                "unsupportedTerms": failed_by_index[idx],
                "reason": "repair failed validation after 2 attempts",
                "attemptNotes": attempt_notes,
            }
            write_repair_progress(progress_path, progress)
        repair_log.append({
            "questionIndex": idx,
            "slideId": question.get("slideId"),
            "initialUnsupportedTerms": failed_by_index[idx],
            "accepted": accepted,
            "attemptNotes": attempt_notes,
        })

    progress["currentQuestionId"] = None
    write_repair_progress(progress_path, progress)
    repaired_map = progress.get("repairedQuestionsByIndex") or {}
    dropped_map = progress.get("droppedByIndex") or {}
    repaired_questions: list[dict[str, Any]] = []
    for idx, question in enumerate(questions, start=1):
        key = str(idx)
        if key in repaired_map:
            repaired_questions.append(repaired_map[key])
        elif key in dropped_map:
            continue
        else:
            repaired_questions.append(question)

    backup_path = GENERATED_DIR / f"{stem}_generated_questions_before_repair_{now_stamp()}.json"
    write_json(backup_path, generated_payload)
    write_json(generated_path, {"questions": repaired_questions})

    app_payload, after_errors, after_grounding, diversity_report = collect_generation_validation(normalized_payload, repaired_questions)
    report = {
        "sourceFile": pdf_path.name,
        "mode": "targeted-repair",
        "originalQuestionCount": original_question_count,
        "failedQuestionCountBeforeRepair": len(failed_by_index),
        "validationErrorCountBeforeRepair": len(before_errors),
        "repairedQuestionCount": len(repaired_map),
        "droppedQuestionCount": len(dropped_map),
        "finalQuestionCount": len(repaired_questions),
        "validationErrorCountAfterRepair": len(after_errors),
        "remainingValidationErrors": after_errors,
        "remainingSemanticGroundingFindings": after_grounding,
        "questionQualityFindings": diversity_report.get("findings", []),
        "droppedQuestions": list(dropped_map.values()),
        "repairLog": repair_log,
        "repairProgressPath": str(progress_path.relative_to(BASE_DIR)),
        "backupGeneratedQuestionsPath": str(backup_path.relative_to(BASE_DIR)),
    }
    write_report(report, "lecture_slide_repair_report")
    if after_errors:
        raise PipelineError("Targeted repair did not produce passing output:\n" + "\n".join(f"- {err}" for err in after_errors[:80]))
    out_path = APP_READY_DIR / f"{stem}_lecture_app_ready.json"
    write_json(out_path, app_payload)
    json.loads(out_path.read_text(encoding="utf-8"))
    log(f"App-ready -> {out_path.relative_to(BASE_DIR)}")
    return out_path


def compact_memory(memory: dict[str, Any]) -> dict[str, Any]:
    out = {"schemaVersion": memory.get("schemaVersion")}
    for key, value in memory.items():
        if not isinstance(value, dict):
            continue
        top = sorted(value.items(), key=lambda kv: int(kv[1]), reverse=True)[:80]
        out[key] = dict(top)
    return out


def update_memory_from_question(memory: dict[str, Any], q: dict[str, Any]) -> None:
    increment_map(memory["diagnosisUsageMap"], str(q.get("diagnosisOrTarget") or q.get("testedConcept") or ""))
    increment_map(memory["stemTemplateUsageMap"], str(q.get("stemTemplate") or ""))
    increment_map(memory["educationalObjectiveMap"], str(q.get("educationalObjective") or ""))
    for choice in q.get("answerChoices") or []:
        if isinstance(choice, dict) and choice.get("label") != q.get("correctAnswer"):
            increment_map(memory["distractorUsageMap"], str(choice.get("text") or ""))
    for route in q.get("imageRouting") or []:
        if isinstance(route, dict):
            increment_map(memory["imageUsageMap"], f"{route.get('imageId')}:{route.get('placement')}")
    fp = question_fingerprint(q.get("stem", ""), q.get("answerChoices") or [])
    increment_map(memory["generatedQuestionFingerprints"], fp)


def normalized_slide_fact_text(slide: dict[str, Any]) -> str:
    fields: list[str] = []
    for key in [
        "primaryConcepts",
        "secondaryConcepts",
        "clinicalFacts",
        "diagnosticFacts",
        "managementFacts",
        "mechanismFacts",
        "groundingNotes",
    ]:
        values = slide.get(key) or []
        if isinstance(values, list):
            fields.extend(str(v) for v in values)
    for table in slide.get("tables") or []:
        if not isinstance(table, dict):
            continue
        fields.append(str(table.get("title") or ""))
        fields.extend(str(h) for h in table.get("headers") or [])
        for row in table.get("rows") or []:
            if isinstance(row, list):
                fields.extend(str(cell) for cell in row)
            elif isinstance(row, dict):
                fields.extend(str(v) for v in row.values())
    return " ".join(fields)


def extract_medical_claim_terms(text: str) -> set[str]:
    """
    Conservative lexical claim extraction.
    This is not a medical ontology. It intentionally catches high-risk additions:
    named diagnoses, drugs, mechanisms, workups, epidemiology, and multiword terms.
    """
    text = re.sub(r"\[[A-Z]+:[^\]]+\]", " ", str(text or ""))
    terms: set[str] = set()

    for word in re.findall(r"\b[A-Za-z][A-Za-z0-9+\-]{3,}\b", text):
        w = word.lower().strip("-")
        if w in COMMON_CLINICAL_WORDS:
            continue
        if w.endswith(MEDICAL_SUFFIXES) or w in HIGH_RISK_MEDICAL_WORDS:
            terms.add(w)
        if w in WORKUP_MANAGEMENT_WORDS:
            terms.add(w)

    return {t for t in terms if len(t) >= 4}


def build_grounding_index(normalized_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for slide in normalized_payload.get("slides") or []:
        fact_text = normalized_slide_fact_text(slide)
        terms = extract_medical_claim_terms(fact_text)
        token_set = {
            tok.lower()
            for tok in re.findall(r"\b[A-Za-z][A-Za-z0-9+\-]{2,}\b", fact_text)
            if tok.lower() not in COMMON_CLINICAL_WORDS
        }
        if "surgery" in token_set or "surgical" in token_set or "myotomy" in token_set or "removed" in token_set or "removal" in token_set:
            token_set.update({"surgery", "surgical"})
        if "cyanotic" in token_set or "cyanosis" in token_set:
            token_set.update({"cyanotic", "cyanosis"})
        if "cxr" in token_set or "x-ray" in token_set or "xray" in token_set:
            token_set.update({"cxr", "x-ray", "xray"})
        if "echo" in token_set or "echocardiography" in token_set or "echocardiogram" in token_set:
            token_set.update({"echo", "echocardiography", "echocardiogram"})
        if "steroid" in token_set or "steroids" in token_set or "corticosteroids" in token_set or "betamethasone" in token_set:
            token_set.update({"steroid", "steroids", "corticosteroids"})
        if "antibiotic" in token_set or "antibiotics" in token_set:
            token_set.update({"antibiotic", "antibiotics"})
        if any(tok.endswith(MEDICAL_SUFFIXES) for tok in token_set):
            token_set.update({"antibiotic", "antibiotics"})
        if "culture" in token_set or "cultures" in token_set:
            token_set.update({"culture", "cultures"})
        if "bilirubin" in token_set or "hyperbilirubinemia" in token_set:
            token_set.update({"bilirubin", "hyperbilirubinemia"})
        if "kernicterus" in token_set:
            token_set.update({"encephalopathy"})
        if "deficient" in token_set or "deficiency" in token_set:
            token_set.update({"enzyme"})
        index[slide["slideId"]] = {
            "factText": fact_text,
            "claimTerms": terms,
            "tokens": token_set,
        }
    return index


def generated_question_claim_text(q: dict[str, Any]) -> str:
    parts = [str(q.get("stem") or "")]
    for choice in q.get("answerChoices") or []:
        if isinstance(choice, dict):
            parts.append(str(choice.get("text") or ""))
    parts.append(str(q.get("correctExplanation") or ""))
    for item in q.get("incorrectExplanations") or []:
        if isinstance(item, dict):
            parts.append(str(item.get("explanation") or ""))
    parts.append(str(q.get("educationalObjective") or ""))
    parts.append(str(q.get("reviewPearl") or ""))
    return " ".join(parts)


def semantic_grounding_findings(generated_questions: list[dict[str, Any]], normalized_payload: dict[str, Any]) -> list[dict[str, Any]]:
    grounding_index = build_grounding_index(normalized_payload)
    findings: list[dict[str, Any]] = []
    for idx, q in enumerate(generated_questions, start=1):
        slide_id = str(q.get("slideId") or "")
        grounding = grounding_index.get(slide_id)
        if not grounding:
            findings.append({
                "questionIndex": idx,
                "slideId": slide_id,
                "severity": "error",
                "issue": "unknown_slide_id",
                "detail": "Question references a slideId absent from normalized slide payload.",
            })
            continue
        q_terms = extract_medical_claim_terms(generated_question_claim_text(q))
        supported_terms = grounding["claimTerms"]
        supported_tokens = grounding["tokens"]
        unsupported: list[str] = []
        for term in sorted(q_terms):
            term_tokens = [t for t in re.findall(r"\b[A-Za-z][A-Za-z0-9+\-]{2,}\b", term.lower()) if t not in COMMON_CLINICAL_WORDS]
            if not term_tokens:
                continue
            token_hits = sum(1 for tok in term_tokens if tok in supported_tokens)
            if term in supported_terms or token_hits == len(term_tokens):
                continue
            if len(term_tokens) >= 2 and token_hits / len(term_tokens) >= 0.67:
                continue
            unsupported.append(term)
        if unsupported:
            findings.append({
                "questionIndex": idx,
                "slideId": slide_id,
                "severity": "error",
                "issue": "unsupported_medical_claim_terms",
                "detail": unsupported[:20],
            })
    return findings


def opening_phrase(stem: str) -> str:
    words = re.findall(r"\b[A-Za-z0-9'-]+\b", stem)
    return " ".join(words[:8]).lower()


def demographic_signature(stem: str) -> str:
    m = re.search(r"\b(\d{1,3})[- ]year[- ]old\s+(boy|girl|man|woman|male|female|child|infant|newborn)\b", stem, re.I)
    if m:
        age = int(m.group(1))
        bucket = "child" if age < 13 else "adolescent" if age < 18 else "adult" if age < 65 else "older adult"
        return f"{bucket} {m.group(2).lower()}"
    for label in ["newborn", "infant", "child", "adolescent", "boy", "girl", "man", "woman"]:
        if re.search(rf"\b{label}\b", stem, re.I):
            return label
    return "unspecified"


def question_quality_and_diversity(generated_questions: list[dict[str, Any]]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    opening_counts: dict[str, int] = {}
    template_counts: dict[str, int] = {}
    demographic_counts: dict[str, int] = {}
    distractor_family_counts: dict[str, int] = {}
    diagnosis_counts: dict[str, int] = {}
    objective_counts: dict[str, int] = {}

    for idx, q in enumerate(generated_questions, start=1):
        stem = str(q.get("stem") or "")
        for pat in TRIVIAL_RECALL_PATTERNS:
            if pat.search(stem):
                findings.append({
                    "questionIndex": idx,
                    "severity": "error",
                    "issue": "trivial_or_non_nbme_wording",
                    "detail": pat.pattern,
                })
        choices = q.get("answerChoices") or []
        choice_texts = [normalize_key(c.get("text", "")) for c in choices if isinstance(c, dict)]
        if len(set(choice_texts)) != len(choice_texts):
            findings.append({
                "questionIndex": idx,
                "severity": "error",
                "issue": "duplicate_answer_choice_text",
                "detail": choice_texts,
            })
        if len([c for c in choice_texts if len(c.split()) <= 1]) >= 3:
            findings.append({
                "questionIndex": idx,
                "severity": "warning",
                "issue": "overly_short_distractors",
                "detail": choice_texts,
            })

        increment_map(opening_counts, opening_phrase(stem))
        increment_map(template_counts, str(q.get("stemTemplate") or "unspecified"))
        increment_map(demographic_counts, demographic_signature(stem))
        increment_map(distractor_family_counts, str(q.get("distractorFamily") or "unspecified"))
        increment_map(diagnosis_counts, str(q.get("diagnosisOrTarget") or q.get("testedConcept") or "unspecified"))
        increment_map(objective_counts, str(q.get("educationalObjective") or ""))

    total = max(1, len(generated_questions))
    repeated_limits = [
        ("opening_phrase_overuse", opening_counts, 0.20),
        ("stem_template_overuse", template_counts, 0.35),
        ("demographic_overuse", demographic_counts, 0.45),
        ("distractor_family_overuse", distractor_family_counts, 0.35),
        ("diagnosis_overuse", diagnosis_counts, 0.15),
        ("educational_objective_repeated", objective_counts, 0.01),
    ]
    for issue, counts, fraction in repeated_limits:
        for value, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
            if not value or value == "unspecified":
                continue
            if issue == "educational_objective_repeated" and count > 1:
                findings.append({"severity": "error", "issue": issue, "detail": {"value": value, "count": count}})
            elif issue != "educational_objective_repeated" and count / total > fraction and count >= 3:
                findings.append({"severity": "warning", "issue": issue, "detail": {"value": value, "count": count, "fraction": round(count / total, 3)}})

    return {
        "findings": findings,
        "statistics": {
            "totalQuestions": len(generated_questions),
            "openingPhrases": sorted(opening_counts.items(), key=lambda kv: kv[1], reverse=True)[:25],
            "stemTemplates": sorted(template_counts.items(), key=lambda kv: kv[1], reverse=True),
            "demographics": sorted(demographic_counts.items(), key=lambda kv: kv[1], reverse=True),
            "distractorFamilies": sorted(distractor_family_counts.items(), key=lambda kv: kv[1], reverse=True),
            "diagnoses": sorted(diagnosis_counts.items(), key=lambda kv: kv[1], reverse=True)[:30],
            "educationalObjectivesRepeated": [(k, v) for k, v in sorted(objective_counts.items(), key=lambda kv: kv[1], reverse=True) if v > 1],
        },
    }


def question_fingerprint(stem: str, choices: list[dict[str, Any]]) -> str:
    text = normalize_key(stem)
    text = re.sub(r"\b\d+\b", "#", text)
    choice_text = "|".join(normalize_key(c.get("text", "")) for c in choices if isinstance(c, dict))
    return short_hash(text[:500] + "|" + choice_text[:500])


def build_explanation_sections(q: dict[str, Any], table_notes: list[str], explanation_image_placeholders: list[str]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    correct = str(q.get("correctExplanation") or "").strip()
    if correct:
        sections.append({"heading": "Correct Answer Explanation", "body": [correct]})
    incorrect_lines: list[str] = []
    for item in q.get("incorrectExplanations") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip().upper()
        explanation = str(item.get("explanation") or "").strip()
        if label and explanation:
            incorrect_lines.append(f"Choice {label}: {explanation}")
    if incorrect_lines:
        sections.append({"heading": "Incorrect Answer Explanation", "body": incorrect_lines})
    extras: list[str] = []
    extras.extend(table_notes)
    extras.extend(explanation_image_placeholders)
    if extras:
        sections.append({"heading": "Slide Figures and Tables", "body": extras})
    edu = str(q.get("educationalObjective") or "").strip()
    if edu:
        sections.append({"heading": "Educational Objective", "body": [edu]})
    return sections


def sanitize_invalid_explanation_labels(q: dict[str, Any]) -> dict[str, Any]:
    allowed_labels = {
        str(choice.get("label") or "").strip().upper()
        for choice in q.get("answerChoices") or []
        if isinstance(choice, dict)
    }
    if not allowed_labels:
        return q

    cleaned_incorrect: list[dict[str, str]] = []
    for item in q.get("incorrectExplanations") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip().upper()
        explanation = clean_sentence(item.get("explanation"))
        if label in allowed_labels and explanation:
            cleaned_incorrect.append({"label": label, "explanation": explanation})
    q["incorrectExplanations"] = cleaned_incorrect

    for section in q.get("explanationSections") or []:
        if not isinstance(section, dict):
            continue
        body = section.get("body")
        if not isinstance(body, list):
            continue
        cleaned_body = []
        for line in body:
            text = str(line or "")
            match = re.match(r"\s*Choice\s+([A-Z])\s*:", text, re.I)
            if match and match.group(1).upper() not in allowed_labels:
                continue
            cleaned_body.append(line)
        section["body"] = cleaned_body
    return q


def build_app_ready_payload(normalized_payload: dict[str, Any], generated_questions: list[dict[str, Any]]) -> dict[str, Any]:
    slide_by_id = {s["slideId"]: s for s in normalized_payload.get("slides") or []}
    questions: list[dict[str, Any]] = []
    for index, gen_q in enumerate(generated_questions, start=1):
        slide_id = str(gen_q.get("slideId") or "")
        slide = slide_by_id.get(slide_id)
        if not slide:
            raise PipelineError(f"Generated Q{index} references unknown slideId: {slide_id}")
        q = normalize_generated_question(gen_q)
        q = sanitize_invalid_explanation_labels(q)
        images, explanation_images, figure_refs, table_notes, exp_placeholders = build_media_routes(q, slide, index)
        sections = build_explanation_sections(q, table_notes, exp_placeholders)
        question = {
            "id": f"lecture_slide_q{index:03d}_{short_hash(slide_id)}",
            "questionNumber": index,
            "sourceQuestionNumber": slide.get("slideId"),
            "stem": q["stem"],
            "answerChoices": q["answerChoices"],
            "correctAnswer": q["correctAnswer"],
            "educationalObjective": q["educationalObjective"],
            "explanationSections": sections,
            "retrievalTag": q["retrievalTag"],
            "reviewPearl": q["reviewPearl"],
            "clinicalPearl": None,
            "hasEmbeddedFigure": bool(figure_refs),
            "figureRefs": figure_refs,
            "images": images,
            "explanationImages": explanation_images,
            "tables": table_notes_to_tables(slide),
            "sharedGroup": None,
            "extractionWarnings": q.get("extractionWarnings") or [],
            "metadata": {
                "sourceType": "lecture-slide-generator",
                "sourceFormat": "lecture-slides",
                "slideId": slide_id,
                "slideTypes": slide.get("slideType") or [],
                "yieldScore": slide.get("yieldScore"),
                "questionPotential": slide.get("questionPotential"),
                "testedConcept": q.get("testedConcept"),
                "diagnosisOrTarget": q.get("diagnosisOrTarget"),
                "stemTemplate": q.get("stemTemplate"),
                "imageRouting": q.get("imageRouting") or [],
                "tableUse": q.get("tableUse") or [],
                "sourceTextHash": slide.get("sourceTextHash"),
                "figureAttachments": {},
            },
        }
        questions.append(question)
    return {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "testTitle": f"{Path(normalized_payload['sourceFile']).stem} Lecture Questions",
        "sourceFormat": SOURCE_FORMAT,
        "expectedQuestionCount": sum(1 for _ in questions),
        "actualExtractedQuestionCount": len(questions),
        "extractionWarnings": normalized_payload.get("normalizationWarnings") or [],
        "questions": questions,
    }


def normalize_generated_question(q: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(q, dict):
        raise PipelineError("Generated question is not an object.")
    stem = re.sub(r"\s+", " ", str(q.get("stem") or "").strip())
    choices = q.get("answerChoices") or q.get("choices") or []
    if not isinstance(choices, list):
        choices = []
    normalized_choices: list[dict[str, str]] = []
    for idx, choice in enumerate(choices[:4]):
        if not isinstance(choice, dict):
            continue
        label = str(choice.get("label") or LABELS[idx]).strip().upper()
        text = re.sub(r"\s+", " ", str(choice.get("text") or "").strip())
        if label not in LABELS:
            label = LABELS[idx]
        normalized_choices.append({"label": label, "text": text})
    if len(normalized_choices) != 4:
        raise PipelineError("Generated question does not have exactly 4 answer choices.")
    if [c["label"] for c in normalized_choices] != LABELS:
        normalized_choices = [{"label": LABELS[idx], "text": c["text"]} for idx, c in enumerate(normalized_choices)]
    correct = str(q.get("correctAnswer") or "").strip().upper()
    if correct not in LABELS:
        raise PipelineError("Generated question has invalid correctAnswer.")
    out = dict(q)
    out["stem"] = stem
    out["answerChoices"] = normalized_choices
    out["correctAnswer"] = correct
    out["educationalObjective"] = clean_sentence(q.get("educationalObjective"))
    out["retrievalTag"] = clean_tag(q.get("retrievalTag") or q.get("testedConcept") or "")
    out["reviewPearl"] = clean_sentence(q.get("reviewPearl") or q.get("correctExplanation") or "")
    out["correctExplanation"] = clean_sentence(q.get("correctExplanation"))
    out = sanitize_invalid_explanation_labels(out)
    return out


def clean_sentence(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = re.sub(r"^(clinical pearl|educational objective)\s*:\s*", "", text, flags=re.I)
    return text


def clean_tag(value: Any) -> str:
    text = clean_sentence(value)
    return text[:90].rstrip(" .;:")


def table_notes_to_tables(slide: dict[str, Any]) -> list[dict[str, Any]]:
    tables = []
    for table in slide.get("tables") or []:
        tables.append({
            "id": table.get("tableId"),
            "title": table.get("title") or "Slide table",
            "headers": table.get("headers") or [],
            "rows": table.get("rows") or [],
            "placement": "explanation",
        })
    return tables


def build_media_routes(q: dict[str, Any], slide: dict[str, Any], q_num: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str], list[str]]:
    image_by_id = {img.get("imageId"): img for img in slide.get("images") or []}
    stem_images: list[dict[str, Any]] = []
    explanation_images: list[dict[str, Any]] = []
    figure_refs: list[dict[str, Any]] = []
    explanation_placeholders: list[str] = []
    used: dict[str, str] = {}
    for route in q.get("imageRouting") or []:
        if not isinstance(route, dict):
            continue
        image_id = str(route.get("imageId") or "").strip()
        placement = str(route.get("placement") or "ignored").strip().lower()
        if placement not in {"stem", "explanation", "ignored"}:
            placement = "ignored"
        if not image_id or image_id not in image_by_id or placement == "ignored":
            continue
        if image_id in used and used[image_id] != placement:
            raise PipelineError(f"Q{q_num}: image {image_id} routed to both stem and explanation.")
        used[image_id] = placement
        img = image_by_id[image_id]
        entry = image_entry_for_question(img, q_num, placement)
        placeholder = f"[FIGURE: {entry['figureId']}]"
        if placement == "stem":
            stem_images.append(entry)
            if placeholder not in q["stem"]:
                q["stem"] = q["stem"].rstrip() + "\n\n" + placeholder
            figure_refs.append({
                "id": entry["figureId"],
                "placeholder": placeholder,
                "location": "stem",
                "visibleText": [],
            })
        elif placement == "explanation":
            explanation_images.append(entry)
            explanation_placeholders.append(placeholder)
            figure_refs.append({
                "id": entry["figureId"],
                "placeholder": placeholder,
                "location": "explanation",
                "visibleText": [],
            })
    table_notes: list[str] = []
    table_ids = {t.get("tableId") for t in slide.get("tables") or []}
    for table_use in q.get("tableUse") or []:
        if not isinstance(table_use, dict):
            continue
        table_id = table_use.get("tableId")
        if table_id and table_id in table_ids:
            table_notes.append(f"Table used for explanation only: {table_id}")
    if not table_notes:
        for table in slide.get("tables") or []:
            table_notes.append(f"Table used for explanation only: {table.get('tableId')}")
    return stem_images, explanation_images, figure_refs, table_notes, explanation_placeholders


def image_entry_for_question(img: dict[str, Any], q_num: int, placement: str) -> dict[str, Any]:
    asset_path = BASE_DIR / str(img.get("assetPath") or "")
    if not asset_path.exists():
        raise PipelineError(f"Image asset missing: {img.get('assetPath')}")
    figure_id = f"lecture_q{q_num:03d}_{img.get('imageId')}"
    return {
        "figureId": figure_id,
        "figureKey": None,
        "dataUrl": data_url(asset_path, img.get("mimeType") or mime_for(asset_path)),
        "isLabTable": False,
        "kind": "figure",
        "source": "lecture-slide-generator",
        "originalFileName": asset_path.name,
        "assetPath": str(asset_path.relative_to(BASE_DIR)),
        "placement": placement,
        "slideImageId": img.get("imageId"),
    }


def validate_app_ready_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schemaVersion") != OUTPUT_SCHEMA_VERSION:
        errors.append("schemaVersion must be nbme-gemini-json-v3.")
    if payload.get("sourceFormat") != SOURCE_FORMAT:
        errors.append("sourceFormat must remain an existing accepted value: mixed.")
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        errors.append("questions must be a non-empty array.")
        return errors
    seen_numbers: set[int] = set()
    seen_fps: dict[str, int] = {}
    diagnosis_usage: dict[str, int] = {}
    objective_usage: dict[str, int] = {}
    for idx, q in enumerate(questions, start=1):
        prefix = f"Q{idx}"
        if q.get("questionNumber") != idx:
            errors.append(f"{prefix}: questionNumber must be {idx}.")
        if q.get("questionNumber") in seen_numbers:
            errors.append(f"{prefix}: duplicate questionNumber.")
        seen_numbers.add(q.get("questionNumber"))
        stem = str(q.get("stem") or "")
        sentence_count = len(re.findall(r"[.!?](?:\s|$)", stem))
        word_count = len(re.findall(r"\b[A-Za-z0-9][A-Za-z0-9'-]*\b", stem))
        if not stem.strip():
            errors.append(f"{prefix}: missing stem.")
        elif sentence_count < 2 or word_count < 35:
            errors.append(f"{prefix}: stem is too short for clinical reasoning.")
        if re.search(r"\b(which of the following is true|all except|except)\b", stem, re.I):
            errors.append(f"{prefix}: forbidden shallow stem phrasing.")
        choices = q.get("answerChoices")
        if not isinstance(choices, list) or len(choices) != 4:
            errors.append(f"{prefix}: answerChoices must contain exactly 4 choices.")
            choices = []
        labels = [c.get("label") for c in choices if isinstance(c, dict)]
        if labels != LABELS:
            errors.append(f"{prefix}: answerChoices labels must be A-D.")
        if q.get("correctAnswer") not in LABELS:
            errors.append(f"{prefix}: correctAnswer must be A-D.")
        if q.get("correctAnswer") not in labels:
            errors.append(f"{prefix}: correctAnswer is not present in choices.")
        allowed_label_set = set(labels)
        if not clean_sentence(q.get("educationalObjective")):
            errors.append(f"{prefix}: missing educationalObjective.")
        if re.search(r"clinical pearl\s*:", str(q.get("educationalObjective") or ""), re.I):
            errors.append(f"{prefix}: educationalObjective has forbidden prefix.")
        sections = q.get("explanationSections")
        if not isinstance(sections, list) or not sections:
            errors.append(f"{prefix}: missing explanationSections.")
        elif allowed_label_set:
            for sec_idx, section in enumerate(sections):
                body = section.get("body") if isinstance(section, dict) else []
                if not isinstance(body, list):
                    continue
                for line_idx, line in enumerate(body):
                    match = re.match(r"\s*Choice\s+([A-Z])\s*:", str(line or ""), re.I)
                    if match and match.group(1).upper() not in allowed_label_set:
                        errors.append(f"{prefix}: explanationSections[{sec_idx}].body[{line_idx}] references absent answer choice {match.group(1).upper()}.")
        validate_text_contamination(prefix, q, errors)
        validate_html(prefix, q, errors)
        images = q.get("images")
        exp_images = q.get("explanationImages")
        if not isinstance(images, list):
            errors.append(f"{prefix}: images must be an array.")
            images = []
        if not isinstance(exp_images, list):
            errors.append(f"{prefix}: explanationImages must be an array.")
            exp_images = []
        validate_figure_routes(prefix, q, images, exp_images, errors)
        fp = question_fingerprint(stem, choices)
        if fp in seen_fps:
            errors.append(f"{prefix}: duplicate question similarity with Q{seen_fps[fp]}.")
        seen_fps[fp] = idx
        diagnosis = normalize_key(q.get("metadata", {}).get("diagnosisOrTarget") or q.get("metadata", {}).get("testedConcept") or q.get("retrievalTag") or "")
        if diagnosis:
            diagnosis_usage[diagnosis] = diagnosis_usage.get(diagnosis, 0) + 1
        objective = normalize_key(q.get("educationalObjective") or "")
        if objective:
            objective_usage[objective] = objective_usage.get(objective, 0) + 1
    for diagnosis, count in diagnosis_usage.items():
        if count > 2:
            errors.append(f"duplicate diagnosis/target appears too often: {diagnosis} ({count})")
    for objective, count in objective_usage.items():
        if count > 1:
            errors.append(f"duplicate educational objective: {objective}")
    return errors


def validate_text_contamination(prefix: str, q: dict[str, Any], errors: list[str]) -> None:
    text = json.dumps(q, ensure_ascii=False)
    for forbidden in FORBIDDEN_STRINGS:
        if forbidden.lower() in text.lower():
            errors.append(f"{prefix}: forbidden artifact found: {forbidden}")
    for pattern in OCR_FRAGMENT_PATTERNS:
        if pattern.search(text):
            errors.append(f"{prefix}: OCR artifact pattern found: {pattern.pattern}")


def validate_html(prefix: str, q: dict[str, Any], errors: list[str]) -> None:
    for field_name in ["correctBlurb", "explanation"]:
        if not q.get(field_name):
            continue
        parser = StrictHTMLParser()
        try:
            parser.feed(str(q.get(field_name)))
            parser.close()
        except Exception as exc:
            errors.append(f"{prefix}: malformed HTML in {field_name}: {exc}")
        for err in parser.errors:
            errors.append(f"{prefix}: malformed HTML in {field_name}: {err}")
    for sec in q.get("explanationSections") or []:
        if not isinstance(sec, dict):
            continue
        for body in sec.get("body") or []:
            if "<" in str(body) or ">" in str(body):
                parser = StrictHTMLParser()
                try:
                    parser.feed(str(body))
                    parser.close()
                except Exception as exc:
                    errors.append(f"{prefix}: malformed HTML in explanation section: {exc}")
                for err in parser.errors:
                    errors.append(f"{prefix}: malformed HTML in explanation section: {err}")


def validate_figure_routes(prefix: str, q: dict[str, Any], images: list[dict[str, Any]], exp_images: list[dict[str, Any]], errors: list[str]) -> None:
    refs = q.get("figureRefs")
    if not isinstance(refs, list):
        errors.append(f"{prefix}: figureRefs must be an array.")
        refs = []
    stem_ids = {img.get("figureId") for img in images if isinstance(img, dict)}
    exp_ids = {img.get("figureId") for img in exp_images if isinstance(img, dict)}
    overlap = stem_ids & exp_ids
    if overlap:
        errors.append(f"{prefix}: duplicate image routing stem and explanation: {sorted(overlap)}")
    ref_ids = {ref.get("id") or ref.get("figureId") for ref in refs if isinstance(ref, dict)}
    for image_id in stem_ids | exp_ids:
        if image_id and image_id not in ref_ids:
            errors.append(f"{prefix}: image {image_id} lacks matching figureRef.")
    combined_text = str(q.get("stem") or "") + " " + json.dumps(q.get("explanationSections") or [])
    for ref in refs:
        if not isinstance(ref, dict):
            errors.append(f"{prefix}: figureRef is not an object.")
            continue
        ref_id = ref.get("id") or ref.get("figureId")
        placeholder = ref.get("placeholder")
        location = ref.get("location")
        if not ref_id or not placeholder:
            errors.append(f"{prefix}: figureRef missing id or placeholder.")
        if placeholder and placeholder not in combined_text:
            errors.append(f"{prefix}: figureRef placeholder not present in stem or explanation.")
        if location == "stem" and ref_id not in stem_ids:
            errors.append(f"{prefix}: stem figureRef lacks matching stem image.")
        if location == "explanation" and ref_id not in exp_ids:
            errors.append(f"{prefix}: explanation figureRef lacks matching explanation image.")
    for image_list_name, image_list in [("images", images), ("explanationImages", exp_images)]:
        seen: set[str] = set()
        for img in image_list:
            if not isinstance(img, dict):
                errors.append(f"{prefix}: {image_list_name} entry is not an object.")
                continue
            if img.get("dataUrl") and img.get("figureKey"):
                errors.append(f"{prefix}: {image_list_name} entry has both dataUrl and figureKey before import.")
            if not img.get("dataUrl") and not img.get("figureKey"):
                errors.append(f"{prefix}: {image_list_name} entry lacks dataUrl or figureKey.")
            sig = str(img.get("figureId") or img.get("assetPath") or "")
            if sig in seen:
                errors.append(f"{prefix}: duplicate image entry in {image_list_name}.")
            seen.add(sig)


def write_report(report: dict[str, Any], prefix: str) -> Path:
    path = REPORT_DIR / f"{prefix}_{now_stamp()}.json"
    write_json(path, report)
    log(f"Report -> {path.relative_to(BASE_DIR)}")
    return path


def process_pdf(pdf_path: Path, generate: bool) -> Path:
    slide_payload = load_or_decompose_pdf(pdf_path)
    normalized_payload = normalize_slides(slide_payload, generate=generate)
    memory = empty_memory()
    allocations = allocate_questions(normalized_payload, memory)
    questions = generate_questions(normalized_payload, allocations, memory, generate=generate)
    if not questions:
        raise PipelineError(f"No questions allocated/generated for {pdf_path.name}.")
    grounding_findings = semantic_grounding_findings(questions, normalized_payload)
    diversity_report = question_quality_and_diversity(questions)
    app_payload = build_app_ready_payload(normalized_payload, questions)
    errors = validate_app_ready_payload(app_payload)
    if generate:
        errors.extend(
            f"Semantic grounding Q{f.get('questionIndex', '?')}: {f.get('issue')} {f.get('detail')}"
            for f in grounding_findings
            if f.get("severity") == "error"
        )
        errors.extend(
            f"Question quality Q{f.get('questionIndex', '?')}: {f.get('issue')} {f.get('detail')}"
            for f in diversity_report.get("findings", [])
            if f.get("severity") == "error"
        )
    report = {
        "sourceFile": pdf_path.name,
        "mode": "generate" if generate else "dry-run",
        "slideCount": len(slide_payload.get("slides") or []),
        "normalizationStats": normalized_payload.get("normalizationStats") or {},
        "normalizationCompletionRate": (
            round((normalized_payload.get("normalizationStats") or {}).get("normalizedSlideCount", 0) / max(1, (normalized_payload.get("normalizationStats") or {}).get("expectedSlideCount", 0)), 4)
        ),
        "normalizationTruncationWarningCount": sum(
            1 for w in normalized_payload.get("normalizationWarnings") or []
            if "truncation" in str(w).lower()
        ),
        "skippedSlideCount": sum(1 for a in allocations if int(a.get("questionCount") or 0) == 0),
        "allocatedQuestionCount": sum(int(a.get("questionCount") or 0) for a in allocations),
        "generatedQuestionCount": len(questions),
        "questionPerSlideDistribution": question_per_slide_distribution(allocations),
        "imageRoutedQuestionCount": sum(1 for q in questions if q.get("imageRouting")),
        "tableRoutedQuestionCount": sum(1 for q in questions if q.get("tableUse")),
        "allocationSummary": [
            {
                "slideId": a["slideId"],
                "questionCount": a["questionCount"],
                "reason": a["reason"],
                "yieldScore": a["yieldScore"],
                "redundancyScore": a["redundancyScore"],
                "contentRichness": a["contentRichness"],
            }
            for a in allocations
        ],
        "semanticGroundingFindings": grounding_findings,
        "questionQualityFindings": diversity_report.get("findings", []),
        "stemDiversityStatistics": diversity_report.get("statistics", {}),
        "validationErrors": errors,
    }
    write_report(report, "lecture_slide_generation_report")
    if errors:
        raise PipelineError("Final validation failed:\n" + "\n".join(f"- {err}" for err in errors[:80]))
    out_path = APP_READY_DIR / f"{slugify(pdf_path.stem)}_lecture_app_ready.json"
    write_json(out_path, app_payload)
    json.loads(out_path.read_text(encoding="utf-8"))
    log(f"App-ready -> {out_path.relative_to(BASE_DIR)}")
    return out_path


def question_per_slide_distribution(allocations: list[dict[str, Any]]) -> dict[str, int]:
    dist = {"0": 0, "1": 0, "2": 0}
    for allocation in allocations:
        count = str(max(0, min(2, int(allocation.get("questionCount") or 0))))
        dist[count] = dist.get(count, 0) + 1
    return dist


def validate_only(path: Path) -> None:
    payload = read_json(path)
    errors = validate_app_ready_payload(payload)
    if errors:
        raise PipelineError("Validation failed:\n" + "\n".join(f"- {err}" for err in errors[:120]))
    print(f"Validation OK: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate NBME-style questions from lecture-slide PDFs.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Run deterministic pipeline without Gemini.")
    mode.add_argument("--generate", action="store_true", help="Run semantic normalization and question generation with Gemini.")
    mode.add_argument("--repair-existing", action="store_true", help="Repair existing generated questions without rerunning full-deck generation.")
    mode.add_argument("--validate-only", default="", help="Validate an app-ready JSON output.")
    parser.add_argument("--input-dir", default="", help="Folder containing lecture PDFs.")
    parser.add_argument("--limit", type=int, default=0, help="Limit PDFs processed.")
    return parser.parse_args()


def main() -> int:
    ensure_dirs()
    args = parse_args()
    try:
        if args.validate_only:
            validate_only(Path(args.validate_only).resolve())
            return 0
        if not args.dry_run and not args.generate and not args.repair_existing:
            print("No action specified. Use --dry-run, --generate, --repair-existing, or --validate-only.")
            return 2
        input_dir = Path(args.input_dir).resolve() if args.input_dir else INPUT_DIR
        pdfs = supported_pdfs(input_dir)
        if args.limit:
            pdfs = pdfs[:args.limit]
        if not pdfs:
            raise PipelineError(f"No PDF files found in {input_dir}")
        outputs: list[Path] = []
        for pdf in pdfs:
            if args.repair_existing:
                outputs.append(repair_existing_questions(pdf))
            else:
                outputs.append(process_pdf(pdf, generate=args.generate))
        print("Generated app-ready files:")
        for output in outputs:
            print(f"  {output}")
        return 0
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
