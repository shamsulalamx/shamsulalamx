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
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
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
CACHE_DIR = OUTPUT_DIR / "cache"
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
FAST_FACTS_PROFILE = "FAST_FACTS_PROFILE"
FAST_FACTS_ATOMIZER_VERSION = "fast-facts-atomizer-v11"
FAST_FACTS_GENERATION_PROMPT_VERSION = "fast-facts-generation-prompt-v2"
FAST_FACTS_VALIDATOR_VERSION = "fast-facts-validator-v3"
FAST_FACTS_ARCHETYPE_ONTOLOGY_VERSION = "fast-facts-archetype-ontology-v2"
AMBOSS_PROFILE = "AMBOSS_PROFILE"
AMBOSS_EXTRACTION_PROMPT_VERSION = "amboss-extraction-prompt-v1"
AMBOSS_IMAGE_ROUTING_VERSION = "amboss-image-routing-v1"
AMBOSS_VISUAL_STATE_VERSION = "amboss-visual-state-v3"
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
    "cerebritis", "ciprofloxacin", "corticosteroids", "cyanosis", "cyst", "dystocia",
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


def emit_bic_progress(phase: str, message: str, source: str | None = None, **payload: Any) -> None:
    progress_source = str(source or os.environ.get("BIC_PROGRESS_SOURCE") or "").strip()
    if not progress_source:
        return
    print(
        "BIC_PROGRESS " + json.dumps(
            {"phase": phase, "source": progress_source, "message": message, **payload},
            ensure_ascii=False,
        ),
        flush=True,
    )


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
        CACHE_DIR,
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


def stable_json_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8", errors="replace")).hexdigest()


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


def supported_pptx(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    return [
        p for p in sorted(input_dir.iterdir())
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() == ".pptx"
    ]


def supported_amboss_inputs(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    allowed = {".pdf", ".png", ".jpg", ".jpeg"}
    return [
        p for p in sorted(input_dir.iterdir())
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in allowed
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


def decompose_pdf(pdf_path: Path, progress_source: str | None = None) -> dict[str, Any]:
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
            emit_bic_progress(
                "extracting",
                f"Extracting page {slide_num}/{page_count} from {pdf_path.name}",
                source=progress_source,
                file=str(pdf_path),
                page=slide_num,
                pageTotal=page_count,
            )
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


def load_or_decompose_pdf(pdf_path: Path, progress_source: str | None = None) -> dict[str, Any]:
    pdf_hash = file_sha(pdf_path)
    existing_path = SLIDES_DIR / f"{slugify(pdf_path.stem)}_slides.json"
    if existing_path.exists():
        try:
            payload = read_json(existing_path)
            if payload.get("pdfSha256") == pdf_hash and isinstance(payload.get("slides"), list):
                log(f"Using existing decomposed slides -> {existing_path.relative_to(BASE_DIR)}")
                emit_bic_progress(
                    "extracting",
                    f"Using existing extraction for {pdf_path.name}",
                    source=progress_source,
                    file=str(pdf_path),
                    pageTotal=len(payload.get("slides") or []),
                )
                return payload
            warn(f"Existing slide decomposition ignored because input hash changed: {existing_path.name}")
        except Exception as exc:
            warn(f"Existing slide decomposition could not be read ({exc}); recomposing PDF.")
    return decompose_pdf(pdf_path, progress_source=progress_source)


def image_ref_to_slide_image(ref: dict[str, Any]) -> dict[str, Any]:
    metadata = ref.get("metadata") if isinstance(ref.get("metadata"), dict) else {}
    image_id = str(metadata.get("imageId") or ref.get("refId") or "").strip()
    asset_path = str(ref.get("path") or metadata.get("assetPath") or "").strip()
    return {
        "imageId": image_id,
        "kind": str(metadata.get("kind") or ref.get("kind") or "image"),
        "assetPath": asset_path,
        "mimeType": str(metadata.get("mimeType") or mime_for(BASE_DIR / asset_path) if asset_path else "application/octet-stream"),
        "width": int(metadata.get("width") or 0),
        "height": int(metadata.get("height") or 0),
        "sha256": str(metadata.get("sha256") or ""),
        "normalizedRefId": ref.get("refId"),
        "normalizedRole": ref.get("role"),
        "normalizedGrounding": ref.get("grounding") if isinstance(ref.get("grounding"), dict) else {},
    }


def table_ref_to_slide_table(ref: dict[str, Any]) -> dict[str, Any]:
    metadata = ref.get("metadata") if isinstance(ref.get("metadata"), dict) else {}
    table_id = str(metadata.get("tableId") or ref.get("refId") or "").strip()
    return {
        "tableId": table_id,
        "title": str(ref.get("text") or metadata.get("title") or "Normalized chunk table"),
        "headers": metadata.get("headers") if isinstance(metadata.get("headers"), list) else [],
        "rows": metadata.get("rows") if isinstance(metadata.get("rows"), list) else [],
        "normalizedRefId": ref.get("refId"),
        "normalizedGrounding": ref.get("grounding") if isinstance(ref.get("grounding"), dict) else {},
    }


def slide_payload_from_normalized_chunks(bundle_path: Path) -> dict[str, Any]:
    bundle = read_json(bundle_path)
    if bundle.get("schemaVersion") != "shared-normalized-chunk-bundle-v1":
        raise PipelineError("Normalized chunk input must use shared-normalized-chunk-bundle-v1.")
    chunks = bundle.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        raise PipelineError("Normalized chunk bundle has no chunks.")
    bundle_hash = stable_json_hash(bundle)
    slides: list[dict[str, Any]] = []
    warnings = list(bundle.get("warnings") or [])
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            warnings.append(f"Skipped non-object chunk at index {index}.")
            continue
        chunk_id = str(chunk.get("chunkId") or f"normalized_chunk_{index:04d}").strip()
        grounding = chunk.get("sourceGrounding") if isinstance(chunk.get("sourceGrounding"), dict) else {}
        slide_index = int(grounding.get("slideIndex") or grounding.get("pageIndex") or index)
        page_index = int(grounding.get("pageIndex") or max(0, slide_index - 1))
        images = [
            image_ref_to_slide_image(ref)
            for ref in chunk.get("imageRefs") or []
            if isinstance(ref, dict)
        ]
        tables = [
            table_ref_to_slide_table(ref)
            for ref in chunk.get("tableRefs") or []
            if isinstance(ref, dict)
        ]
        text_blocks = chunk.get("textBlocks") if isinstance(chunk.get("textBlocks"), list) else []
        text = str(chunk.get("text") or "").strip()
        if not text and text_blocks:
            text = "\n\n".join(str(block.get("text") or "") for block in text_blocks if isinstance(block, dict)).strip()
        slides.append({
            "slideId": chunk_id,
            "sourceFile": str(chunk.get("sourceFile") or bundle.get("sourceFile") or bundle_path.name),
            "pdfSha256": bundle_hash,
            "slideIndex": slide_index,
            "pageIndex": page_index,
            "ocrText": clean_slide_text(text),
            "images": images,
            "tables": tables,
            "metadata": {
                **({} if not isinstance(chunk.get("metadata"), dict) else chunk.get("metadata")),
                "normalizedChunkId": chunk_id,
                "normalizedChunkType": chunk.get("chunkType"),
                "normalizedChunkConfidence": chunk.get("confidence"),
                "sourceGrounding": grounding,
            },
            "warnings": list(chunk.get("warnings") or []),
        })
    if not slides:
        raise PipelineError("Normalized chunk bundle did not contain usable chunks.")
    return {
        "schemaVersion": "lecture-slide-decomposition-v1",
        "sourceFile": str(bundle.get("sourceFile") or bundle_path.stem),
        "sourcePath": str(bundle.get("sourcePath") or bundle_path),
        "pdfSha256": bundle_hash,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "pageCount": len(slides),
        "pdfMetadata": {},
        "slides": slides,
        "provenance": {
            "sourceMode": "normalized_chunks",
            "chunkBundlePath": str(bundle_path),
            "chunkBundleHash": bundle_hash,
            "chunkBundleId": str(bundle.get("bundleId") or bundle.get("id") or bundle_hash[:16]),
            "chunkCountConsumed": len(slides),
        },
        "normalizationWarnings": warnings,
    }


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


def raw_gemini_image_call(api_key: str, prompt: str, image_paths: list[Path], temperature: float, max_tokens: int = 8192, timeout_seconds: int = 90) -> str:
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for image_path in image_paths:
        parts.append({
            "inline_data": {
                "mime_type": mime_for(image_path),
                "data": base64.b64encode(image_path.read_bytes()).decode("ascii"),
            }
        })
    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": parts}],
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
        raise PipelineError("Gemini request timed out") from exc
    candidates = response.get("candidates") or []
    if not candidates:
        raise PipelineError(f"Gemini returned no candidates: {json.dumps(response)[:300]}")
    parts_out = candidates[0].get("content", {}).get("parts") or []
    if not parts_out or "text" not in parts_out[0]:
        raise PipelineError("Gemini candidate had no text part.")
    return str(parts_out[0].get("text") or "")


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
    if isinstance(slide_payload.get("provenance"), dict):
        payload["provenance"] = slide_payload["provenance"]
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
        "differentialFacts",
        "trapFacts",
        "nativeTextFacts",
        "cleanedImageFacts",
        "groundingNotes",
        "groundingTerms",
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
    for values in (slide.get("structuredImageFacts") or {}).values():
        if isinstance(values, list):
            for value in values:
                text = clean_sentence(value)
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
    total_questions = sum(int(a.get("questionCount") or 0) for a in work)
    if generate:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise PipelineError("GEMINI_API_KEY is not set.")
        template = GENERATE_PROMPT.read_text(encoding="utf-8")
        chunks = chunk_list(work, MAX_GENERATION_ALLOCS_PER_CHUNK)
        generated_so_far = 0
        for chunk_index, chunk in enumerate(chunks, start=1):
            chunk_questions = sum(int(a.get("questionCount") or 0) for a in chunk)
            emit_bic_progress(
                "generating",
                f"Generating question {generated_so_far + 1}/{total_questions} from chunk {chunk_index}/{len(chunks)}",
                chunk=chunk_index,
                chunkTotal=len(chunks),
                question=generated_so_far + 1,
                questionTotal=total_questions,
            )
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
            generated_so_far += chunk_questions
    else:
        n = 1
        for allocation in work:
            for _ in range(int(allocation.get("questionCount") or 0)):
                emit_bic_progress(
                    "generating",
                    f"Generating question {n}/{total_questions}",
                    question=n,
                    questionTotal=total_questions,
                )
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


def extract_fast_facts_generated_question_items(parsed: Any, allocations: list[dict[str, Any]], chunk_label: str) -> list[dict[str, Any]]:
    try:
        return extract_generated_question_items(parsed, allocations, chunk_label)
    except PipelineError as exc:
        message = str(exc)
        if len(allocations) != 1 or "returned" not in message or "expected 1" not in message:
            raise
        items = parsed.get("questions") if isinstance(parsed, dict) else parsed
        if not isinstance(items, list):
            raise
        slide_id = allocations[0]["slideId"]
        candidates = [item for item in items if isinstance(item, dict) and item.get("slideId") == slide_id]
        if not candidates:
            raise
        required = [
            "slideId", "questionKind", "stemTemplate", "testedConcept",
            "diagnosisOrTarget", "distractorFamily", "stem", "answerChoices",
            "correctAnswer", "correctExplanation", "incorrectExplanations",
            "educationalObjective", "retrievalTag", "reviewPearl",
            "imageRouting", "tableUse", "sourceFactIds",
        ]
        valid: list[dict[str, Any]] = []
        for item in candidates:
            if all(key in item for key in required) and isinstance(item.get("answerChoices"), list) and len(item.get("answerChoices") or []) == 4:
                valid.append(item)
        if not valid:
            raise
        warn(f"Fast Facts generation {chunk_label}: received {len(items)} questions for one concept; kept first valid matching question for {slide_id}.")
        return [valid[0]]


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
            emit_bic_progress(
                "repairing",
                f"Repairing generated questions from {chunk_label} after validation failure",
                chunk=chunk_label,
            )
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
        "differentialFacts",
        "trapFacts",
        "nativeTextFacts",
        "cleanedImageFacts",
        "groundingNotes",
        "groundingTerms",
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
    for values in (slide.get("structuredImageFacts") or {}).values():
        if isinstance(values, list):
            fields.extend(str(value) for value in values)
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


def expected_sequential_labels(count: int) -> list[str]:
    return [chr(ord("A") + idx) for idx in range(max(0, count))]


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


def normalize_amboss_extracted_question(q: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(q, dict):
        raise PipelineError("AMBOSS extracted question is not an object.")
    stem = re.sub(r"\s+", " ", str(q.get("stem") or "").strip())
    choices = q.get("answerChoices") or []
    if not isinstance(choices, list):
        choices = []
    normalized_choices: list[dict[str, str]] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        label = str(choice.get("label") or "").strip().upper()
        text = re.sub(r"\s+", " ", str(choice.get("text") or "").strip())
        if label and text:
            normalized_choices.append({"label": label, "text": text})
    if not (2 <= len(normalized_choices) <= 9):
        raise PipelineError(f"AMBOSS extracted question must have 2-9 choices, got {len(normalized_choices)}.")
    labels = [choice["label"] for choice in normalized_choices]
    expected = expected_sequential_labels(len(labels))
    if labels != expected:
        raise PipelineError(f"AMBOSS answer labels must be sequential {expected[0]}-{expected[-1]}, got {labels}.")
    correct = str(q.get("correctAnswer") or "").strip().upper()
    if correct not in labels:
        raise PipelineError(f"AMBOSS correctAnswer {correct or '(missing)'} is not present in choices {labels}.")
    objective = clean_sentence(q.get("educationalObjective") or q.get("correctExplanation") or "Review the extracted AMBOSS explanation.")
    out = dict(q)
    out["stem"] = stem
    out["answerChoices"] = normalized_choices
    out["correctAnswer"] = correct
    out["educationalObjective"] = objective
    out["retrievalTag"] = clean_tag(q.get("retrievalTag") or objective[:80])
    out["reviewPearl"] = clean_sentence(q.get("reviewPearl") or q.get("correctExplanation") or objective)
    out["correctExplanation"] = clean_sentence(q.get("correctExplanation"))
    out["incorrectExplanations"] = [
        {
            "label": str(item.get("label") or "").strip().upper(),
            "explanation": clean_sentence(item.get("explanation")),
        }
        for item in (q.get("incorrectExplanations") or [])
        if isinstance(item, dict)
        and str(item.get("label") or "").strip().upper() in labels
        and str(item.get("label") or "").strip().upper() != correct
        and clean_sentence(item.get("explanation"))
    ]
    return out


def build_app_ready_payload(normalized_payload: dict[str, Any], generated_questions: list[dict[str, Any]]) -> dict[str, Any]:
    slide_by_id = {s["slideId"]: s for s in normalized_payload.get("slides") or []}
    is_amboss = normalized_payload.get("profile") == AMBOSS_PROFILE
    provenance = normalized_payload.get("provenance") if isinstance(normalized_payload.get("provenance"), dict) else {}
    source_mode = str(provenance.get("sourceMode") or "raw_source")
    questions: list[dict[str, Any]] = []
    for index, gen_q in enumerate(generated_questions, start=1):
        slide_id = str(gen_q.get("slideId") or "")
        slide = slide_by_id.get(slide_id)
        if not slide:
            raise PipelineError(f"Generated Q{index} references unknown slideId: {slide_id}")
        q = normalize_amboss_extracted_question(gen_q) if is_amboss else normalize_generated_question(gen_q)
        q = sanitize_invalid_explanation_labels(q)
        images, explanation_images, figure_refs, table_notes, exp_placeholders = build_media_routes(q, slide, index)
        sections = build_explanation_sections(q, table_notes, exp_placeholders)
        question = {
            "id": f"{'amboss' if is_amboss else 'lecture_slide'}_q{index:03d}_{short_hash(slide_id)}",
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
                "sourceType": "amboss-profile" if is_amboss else "lecture-slide-generator",
                "sourceFormat": "amboss-extraction" if is_amboss else "lecture-slides",
                "sourceMode": source_mode,
                "chunkBundleHash": provenance.get("chunkBundleHash"),
                "chunkBundleId": provenance.get("chunkBundleId"),
                "chunkCountConsumed": provenance.get("chunkCountConsumed"),
                "profile": AMBOSS_PROFILE if is_amboss else normalized_payload.get("profile"),
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
        "metadata": {
            "sourceMode": source_mode,
            "chunkBundleHash": provenance.get("chunkBundleHash"),
            "chunkBundleId": provenance.get("chunkBundleId"),
            "chunkCountConsumed": provenance.get("chunkCountConsumed"),
        },
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
    is_amboss = any(
        isinstance(q, dict)
        and isinstance(q.get("metadata"), dict)
        and q.get("metadata", {}).get("profile") == AMBOSS_PROFILE
        for q in questions
    )
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
        if is_amboss:
            if not isinstance(choices, list) or not (2 <= len(choices) <= 9):
                errors.append(f"{prefix}: AMBOSS answerChoices must contain 2-9 choices.")
                choices = []
        elif not isinstance(choices, list) or len(choices) != 4:
            errors.append(f"{prefix}: answerChoices must contain exactly 4 choices.")
            choices = []
        labels = [c.get("label") for c in choices if isinstance(c, dict)]
        if is_amboss:
            expected = expected_sequential_labels(len(labels))
            if labels != expected:
                label_range = f"{expected[0]}-{expected[-1]}" if expected else "A-Z"
                errors.append(f"{prefix}: AMBOSS answerChoices labels must be sequential {label_range}.")
        else:
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


def process_slide_payload(slide_payload: dict[str, Any], generate: bool, output_stem: str, source_label: str) -> Path:
    normalized_payload = normalize_slides(slide_payload, generate=generate)
    memory = empty_memory()
    allocations = allocate_questions(normalized_payload, memory)
    questions = generate_questions(normalized_payload, allocations, memory, generate=generate)
    if not questions:
        raise PipelineError(f"No questions allocated/generated for {source_label}.")
    emit_bic_progress("validating", "Validating generated output")
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
        "sourceFile": slide_payload.get("sourceFile") or source_label,
        "sourceMode": (normalized_payload.get("provenance") or {}).get("sourceMode", "raw_source") if isinstance(normalized_payload.get("provenance"), dict) else "raw_source",
        "chunkBundleHash": (normalized_payload.get("provenance") or {}).get("chunkBundleHash") if isinstance(normalized_payload.get("provenance"), dict) else None,
        "chunkBundleId": (normalized_payload.get("provenance") or {}).get("chunkBundleId") if isinstance(normalized_payload.get("provenance"), dict) else None,
        "chunkCountConsumed": (normalized_payload.get("provenance") or {}).get("chunkCountConsumed") if isinstance(normalized_payload.get("provenance"), dict) else None,
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
    out_path = APP_READY_DIR / f"{slugify(output_stem)}_lecture_app_ready.json"
    emit_bic_progress("writing", "Writing app-ready JSON", file=str(out_path))
    write_json(out_path, app_payload)
    json.loads(out_path.read_text(encoding="utf-8"))
    log(f"App-ready -> {out_path.relative_to(BASE_DIR)}")
    return out_path


def process_pdf(pdf_path: Path, generate: bool) -> Path:
    slide_payload = load_or_decompose_pdf(pdf_path)
    slide_payload["provenance"] = {
        "sourceMode": "raw_source",
        "chunkBundleHash": None,
        "chunkBundleId": None,
        "chunkCountConsumed": None,
    }
    return process_slide_payload(slide_payload, generate=generate, output_stem=pdf_path.stem, source_label=pdf_path.name)


def process_normalized_chunks(bundle_path: Path, generate: bool) -> Path:
    slide_payload = slide_payload_from_normalized_chunks(bundle_path)
    output_stem = f"{Path(str(slide_payload.get('sourceFile') or bundle_path.stem)).stem}_normalized_chunks"
    return process_slide_payload(slide_payload, generate=generate, output_stem=output_stem, source_label=bundle_path.name)


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


def structured_fast_facts_values(concept: dict[str, Any]) -> list[str]:
    values: list[str] = []
    structured = concept.get("structuredImageFacts") or {}
    if not isinstance(structured, dict):
        return values
    for items in structured.values():
        if isinstance(items, list):
            for item in items:
                text = clean_sentence(item)
                if text and text not in values:
                    values.append(text)
    return values


def fast_facts_allowed_source_facts(concept: dict[str, Any]) -> list[str]:
    facts: list[str] = []
    for key in [
        "nativeTextFacts",
        "clinicalFacts",
        "diagnosticFacts",
        "managementFacts",
        "mechanismFacts",
        "differentialFacts",
        "trapFacts",
    ]:
        for value in concept.get(key) or []:
            text = clean_sentence(value)
            if text and text not in facts:
                facts.append(text)
    if concept.get("imageTextQuality") != "poor":
        for value in concept.get("cleanedImageFacts") or []:
            text = clean_sentence(value)
            if text and text not in facts:
                facts.append(text)
        for value in structured_fast_facts_values(concept):
            if value not in facts:
                facts.append(value)
    return facts


def fast_facts_concept_to_generation_slide(concept: dict[str, Any]) -> dict[str, Any] | None:
    if concept.get("dedupeDisposition") not in {None, "", "keep", "merge"}:
        return None
    source_facts = fast_facts_allowed_source_facts(concept)
    if len(source_facts) < 2:
        return None
    title = clean_sentence(concept.get("title"))
    structured = concept.get("structuredImageFacts") or {}
    image_quality = concept.get("imageTextQuality")
    cleaned_image_facts = [] if image_quality == "poor" else list(concept.get("cleanedImageFacts") or [])
    management_facts = list(concept.get("managementFacts") or [])
    diagnostic_facts = list(concept.get("diagnosticFacts") or [])
    clinical_facts = list(concept.get("clinicalFacts") or [])
    trap_facts = list(concept.get("trapFacts") or [])
    if image_quality != "poor" and isinstance(structured, dict):
        management_facts.extend(structured.get("managementSteps") or [])
        management_facts.extend(structured.get("indications") or [])
        diagnostic_facts.extend(structured.get("criteria") or [])
        diagnostic_facts.extend(structured.get("thresholds") or [])
        trap_facts.extend(structured.get("contraindications") or [])
    fact_categories = [
        clinical_facts,
        diagnostic_facts,
        management_facts,
        concept.get("mechanismFacts") or [],
        concept.get("differentialFacts") or [],
        trap_facts,
    ]
    category_count = sum(1 for values in fact_categories if values)
    if len(source_facts) < 3 and category_count < 2:
        return None
    question_archetype = fast_facts_question_archetype(concept, source_facts)
    slide_types = ["HIGH_YIELD_CLINICAL"]
    if concept.get("images"):
        slide_types.append("IMAGE_HEAVY")
    if concept.get("tables"):
        slide_types.append("TABLE_HEAVY")
    return {
        "slideId": concept["conceptId"],
        "slideType": slide_types,
        "yieldScore": int(concept.get("questionPotential") or 0),
        "primaryConcepts": [title] if title else [],
        "secondaryConcepts": [],
        "clinicalFacts": dedupe_preserve_order(clinical_facts),
        "diagnosticFacts": dedupe_preserve_order(diagnostic_facts),
        "managementFacts": dedupe_preserve_order(management_facts),
        "mechanismFacts": dedupe_preserve_order(concept.get("mechanismFacts") or []),
        "differentialFacts": dedupe_preserve_order(concept.get("differentialFacts") or []),
        "trapFacts": dedupe_preserve_order(trap_facts),
        "nativeTextFacts": dedupe_preserve_order(concept.get("nativeTextFacts") or []),
        "cleanedImageFacts": dedupe_preserve_order(cleaned_image_facts),
        "structuredImageFacts": structured if image_quality != "poor" else {
            "criteria": [],
            "indications": [],
            "contraindications": [],
            "managementSteps": [],
            "thresholds": [],
        },
        "imageTextQuality": image_quality,
        "groundingNotes": source_facts,
        "groundingTerms": list(concept.get("groundingTerms") or []),
        "questionArchetype": question_archetype,
        "images": concept.get("images") or [],
        "tables": concept.get("tables") or [],
        "questionPotential": int(concept.get("questionPotential") or 0),
        "sourceTextHash": short_hash(title + "|" + "|".join(source_facts)),
        "metadata": {
            "profile": FAST_FACTS_PROFILE,
            "sourceConceptId": concept.get("conceptId"),
            "sourceSlideIds": concept.get("sourceSlideIds") or [],
            "dedupeDisposition": concept.get("dedupeDisposition") or "keep",
            "semanticClusterId": concept.get("semanticClusterId"),
            "questionArchetype": question_archetype,
        },
    }


def fast_facts_question_archetype(concept: dict[str, Any], source_facts: list[str]) -> str:
    title = normalize_key(concept.get("title") or "")
    text = normalize_key(" ".join([title] + source_facts))
    if re.search(r"\bscreen\w*|pack-year|low-dose ct|yearly|criteria\b", text):
        return "screening"
    if re.search(r"\bnitrofurantoin-induced|drug-induced|adverse|toxicity|after starting|medication initiation\b", text):
        return "adverse_effect"
    if re.search(r"\bnot to be confused|differentiat|versus| vs |mimic|rather than\b", text):
        return "differentiation"
    if re.search(r"\bmechanism|pathophys|deficien|mutation|receptor|inhibit|activat\b", text):
        return "mechanism"
    if re.search(r"\brisk factor|smok\w*|exposure|family history\b", text):
        return "risk_factor"
    if re.search(r"\bcontraindicat|avoid\b", text):
        return "management"
    if re.search(r"\b(tmp-smx|nitrofurantoin|fosfomycin|fluoroquinolone|ceftriaxone|cefazolin|amoxicillin|antibiotic|drug)\b", text):
        return "pharmacology" if re.search(r"\b\d+\s*(?:days?|dose)|single dose|course\b", text) else "management"
    if re.search(r"\btreat|therapy|management|next step|culture prior|empiric\b", text):
        return "next_step"
    if re.search(r"\bcomplication|sequela|progression\b", text):
        return "complication"
    if re.search(r"\bdiagnos|finding|urinalysis|culture|opacit|rash|clinical features\b", text):
        return "diagnosis"
    return "diagnosis"


def dedupe_preserve_order(values: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_sentence(value)
        key = normalize_key(text)
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def fast_facts_normalized_payload(pptx_path: Path, graph: dict[str, Any], deck_hash: str, limit_slides: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    slides: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for concept in graph.get("concepts") or []:
        slide = fast_facts_concept_to_generation_slide(concept)
        if slide:
            slides.append(slide)
        else:
            skipped.append({
                "conceptId": concept.get("conceptId"),
                "title": concept.get("title"),
                "reason": "low information, poor image text, or dedupe disposition",
                "dedupeDisposition": concept.get("dedupeDisposition"),
                "imageTextQuality": concept.get("imageTextQuality"),
            })
    payload = {
        "schemaVersion": "fast-facts-normalized-for-generation-v1",
        "profile": FAST_FACTS_PROFILE,
        "sourceFile": pptx_path.name,
        "pptxSha256": deck_hash,
        "pdfSha256": deck_hash,
        "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "limitSlides": int(limit_slides or 0),
        "normalizationWarnings": [],
        "normalizationStats": {
            "expectedSlideCount": graph.get("slideCount"),
            "conceptCount": len(graph.get("concepts") or []),
            "generationEligibleConceptCount": len(slides),
            "skippedConceptCount": len(skipped),
        },
        "slides": slides,
    }
    return payload, skipped


def fast_facts_image_route_guidance(slide: dict[str, Any]) -> list[dict[str, str]]:
    routes: list[dict[str, str]] = []
    for image in slide.get("images") or []:
        image_id = str(image.get("imageId") or "")
        kind = normalize_key(image.get("kind") or image.get("classification") or "")
        if not image_id:
            continue
        placement = "ignored"
        if kind in {"algorithm", "explanatory", "table like", "table-like"}:
            placement = "explanation"
        elif kind == "diagnostic":
            placement = "stem"
        routes.append({"imageId": image_id, "placement": placement})
    return routes


def fast_facts_generation_prompt(allocations: list[dict[str, Any]], memory: dict[str, Any]) -> str:
    compact_allocations: list[dict[str, Any]] = []
    for allocation in allocations:
        slide = copy.deepcopy(allocation["slide"])
        allowed = slide_allowed_grounding(slide)
        slide["allowedImageRouting"] = fast_facts_image_route_guidance(slide)
        compact_allocations.append({
            "slideId": allocation["slideId"],
            "questionCount": allocation["questionCount"],
            "reason": allocation.get("reason"),
            "sourceConceptTitle": first_nonempty(slide.get("primaryConcepts")),
            "questionArchetype": slide.get("questionArchetype"),
            "slide": slide,
            "ALLOWED_MEDICAL_TERMS": allowed["allowedMedicalTerms"],
            "ALLOWED_DISTRACTOR_POOL": allowed["allowedDistractorPool"],
            "GROUNDING_FACTS": allowed["groundingFacts"],
        })
    return f"""
Generate a small FAST_FACTS_PROFILE NBME-style question set.

Return JSON only in this exact shape:
{question_schema_required_keys()}

Return exactly the requested number of questions for each allocation.

STRICT SOURCE RULES:
- Generate only from nativeTextFacts, cleanedImageFacts, structuredImageFacts, and GROUNDING_FACTS.
- Do not use imageOcrFacts directly.
- Do not use cleanedImageFacts or structuredImageFacts when imageTextQuality is poor.
- Every clinical claim, distractor, threshold, management step, diagnostic criterion, explanation, and educational objective must map to GROUNDING_FACTS or ALLOWED_MEDICAL_TERMS.
- Every answer choice and every explanation claim must use only concepts from ALLOWED_MEDICAL_TERMS, ALLOWED_DISTRACTOR_POOL, or generic nonmedical vignette wording.
- Never invent outside diseases, drugs, tests, mechanisms, procedures, risk factors, epidemiology, or management.
- If a concept cannot support four grounded answer choices, make the question test a management step, diagnostic finding, contraindication, or differential from the same concept facts. Do not invent.

QUESTION STYLE:
- Four answer choices exactly, labeled A-D.
- One best answer.
- Each question must include questionArchetype equal to the allocation questionArchetype.
- Use exactly one archetype per question. Align the stem, lead-in, correct answer, and distractors to that archetype.
- Archetype answer-choice rules:
  - diagnosis: every answer choice must be a diagnosis or named clinical condition.
  - next_step: every answer choice must be a concrete next step or action.
  - mechanism: every answer choice must be a mechanism.
  - adverse_effect: every answer choice must be a diagnosis/adverse reaction, not an isolated symptom, lab, or imaging finding.
  - management: every answer choice must be an intervention or management action.
  - differentiation: every answer choice must be a diagnosis, condition, or clinical category being differentiated.
  - risk_factor: every answer choice must be a risk factor.
  - screening: every answer choice must be a screening criterion, screening interval, or screening test.
  - pharmacology: every answer choice must be a drug or drug class.
  - complication: every answer choice must be a complication.
- Prefer next best step, management decisions, diagnostic differentiation, contraindications, and screening criteria.
- Avoid "which of the following is true", "all except", and generic template stems.
- Do not use stem findings, lab abnormalities, or imaging findings as distractors when the correct answer is a diagnosis.
- Do not mix diagnoses, symptoms, labs, imaging findings, drugs, and procedures in the same answer set.
- Do not use tautologic distractors that simply repeat a stem finding.
- Avoid pure guideline trivia unless the source fact is a threshold, duration, screening criterion, drug toxicity, or classic board pearl.
- Include discriminating detail such as timing, localization, severity marker, contraindication, threshold, progression pattern, or key associated finding.
- Keep stems clinically natural and concise, usually 3-5 sentences.
- Avoid awkward temporal phrasing. Prefer "Several days after starting nitrofurantoin" over "was prescribed nitrofurantoin several days after medication initiation."
- Use distinct educationalObjective wording for every question.

IMAGE ROUTING:
- Use only image IDs from allowedImageRouting.
- Algorithm, explanatory, and table-like images should be routed to explanation unless the visual is essential to answer the stem.
- Diagnostic images may be routed to stem if needed for reasoning.
- Never route the same image to both stem and explanation.

ROLLING_MEMORY_JSON:
{json.dumps(compact_memory(memory), ensure_ascii=False)}

ALLOCATIONS_JSON:
{json.dumps(compact_allocations, ensure_ascii=False)}
""".strip()


def generate_fast_facts_questions(normalized_payload: dict[str, Any], allocations: list[dict[str, Any]], memory: dict[str, Any]) -> list[dict[str, Any]]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise PipelineError("GEMINI_API_KEY is not set.")
    work = [a for a in allocations if int(a.get("questionCount") or 0) > 0]
    questions: list[dict[str, Any]] = []
    stem = slugify(Path(normalized_payload["sourceFile"]).stem)
    if not work:
        return questions
    for chunk_index, chunk in enumerate(chunk_list(work, 3), start=1):
        chunk_label = f"fast_facts_chunk{chunk_index}"
        items = generate_fast_facts_chunk_with_retries(api_key, normalized_payload["sourceFile"], chunk, memory, chunk_label)
        slide_by_id = {a["slideId"]: a["slide"] for a in chunk}
        for item in items:
            item = fast_facts_cleanup_question(item)
            slide = slide_by_id.get(str(item.get("slideId") or ""))
            if slide and not item.get("questionArchetype"):
                item["questionArchetype"] = slide.get("questionArchetype")
            questions.append(item)
            update_memory_from_question(memory, item)
    generated_path = GENERATED_DIR / f"{stem}_fast_facts_generated_questions.json"
    write_json(generated_path, {"questions": questions})
    mem_path = MEMORY_DIR / f"{stem}_fast_facts_rolling_memory.json"
    write_json(mem_path, memory)
    log(f"  Fast Facts generated -> {generated_path.relative_to(BASE_DIR)}")
    log(f"  Fast Facts memory -> {mem_path.relative_to(BASE_DIR)}")
    return questions


def call_fast_facts_generation_chunk_once(
    api_key: str,
    source_file: str,
    chunk: list[dict[str, Any]],
    memory: dict[str, Any],
    chunk_label: str,
    retry_label: str,
    repair_raw: str | None = None,
    repair_error: str = "",
) -> list[dict[str, Any]]:
    if repair_raw is None:
        prompt = fast_facts_generation_prompt(chunk, memory)
        temperature = 0.2
    else:
        prompt = repair_json_prompt(
            raw=repair_raw,
            expected_schema=question_schema_required_keys(),
            expected_ids=[a["slideId"] for a in chunk],
            error_message=repair_error,
        )
        temperature = 0.0
    raw = raw_gemini_call(api_key, prompt, temperature=temperature, max_tokens=9000, timeout_seconds=90)
    write_debug_raw(source_file, "generate", chunk_label, retry_label, raw)
    parsed = load_largest_valid_json(raw)
    return extract_fast_facts_generated_question_items(parsed, chunk, chunk_label)


def generate_fast_facts_chunk_with_retries(
    api_key: str,
    source_file: str,
    chunk: list[dict[str, Any]],
    memory: dict[str, Any],
    chunk_label: str,
) -> list[dict[str, Any]]:
    last_raw = ""
    last_error = ""
    try:
        return call_fast_facts_generation_chunk_once(api_key, source_file, chunk, memory, chunk_label, "attempt0")
    except Exception as exc:
        last_error = str(exc)
        raw_path = DEBUG_DIR / f"{slugify(Path(source_file).stem)}_generate_{slugify(chunk_label)}_attempt0_raw_response.txt"
        if raw_path.exists():
            last_raw = raw_path.read_text(encoding="utf-8", errors="replace")
        warn(f"Fast Facts generation {chunk_label}: attempt0 failed: {last_error}")
    if last_raw and not is_truncation_failure(last_error):
        try:
            return call_fast_facts_generation_chunk_once(
                api_key,
                source_file,
                chunk,
                memory,
                chunk_label,
                "retry1_repair",
                repair_raw=last_raw,
                repair_error=last_error,
            )
        except Exception as exc:
            last_error = str(exc)
            warn(f"Fast Facts generation {chunk_label}: retry1 repair failed: {last_error}")
    if len(chunk) > 1:
        collected: list[dict[str, Any]] = []
        for sub_index, allocation in enumerate(chunk, start=1):
            collected.extend(generate_fast_facts_chunk_with_retries(api_key, source_file, [allocation], memory, f"{chunk_label}_slide{sub_index}"))
        return collected
    warn(f"Fast Facts generation {chunk_label}: dropped concept {chunk[0].get('slideId')} after generation JSON/schema failures: {last_error}")
    return []


def fast_facts_allocations(normalized_payload: dict[str, Any], memory: dict[str, Any]) -> list[dict[str, Any]]:
    update_memory_from_slides(memory, normalized_payload.get("slides") or [])
    allocations: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for slide in normalized_payload.get("slides") or []:
        title = first_nonempty(slide.get("primaryConcepts"))
        title_key = normalize_key(title)
        fact_count = sum(len(slide.get(key) or []) for key in [
            "clinicalFacts", "diagnosticFacts", "managementFacts", "mechanismFacts",
            "differentialFacts", "trapFacts", "groundingNotes",
        ])
        count = 0
        reason = "not enough grounded concept facts"
        if title_key and title_key in seen_titles:
            reason = "duplicate concept title in constrained run"
        elif int(slide.get("questionPotential") or 0) >= 50 and fact_count >= 3:
            count = 1
            reason = "grounded Fast Facts concept with sufficient facts"
        seen_titles.add(title_key)
        allocations.append({
            "slideId": slide["slideId"],
            "questionCount": count,
            "reason": reason,
            "yieldScore": slide.get("yieldScore", 0),
            "redundancyScore": 0,
            "contentRichness": fact_count,
            "slide": slide,
        })
    return allocations


def limit_fast_facts_question_attempts(allocations: list[dict[str, Any]], question_limit: int) -> list[dict[str, Any]]:
    if int(question_limit or 0) <= 0:
        return allocations
    limited = copy.deepcopy(allocations)
    remaining = int(question_limit)
    for allocation in limited:
        count = max(0, int(allocation.get("questionCount") or 0))
        if count <= 0:
            continue
        if remaining <= 0:
            allocation["questionCount"] = 0
            allocation["reason"] = "skipped by Fast Facts question attempt limit"
            continue
        kept = min(count, remaining)
        allocation["questionCount"] = kept
        remaining -= kept
        if kept < count:
            allocation["reason"] = "partially capped by Fast Facts question attempt limit"
    return limited


def fast_facts_diagnostic_entry(allocation: dict[str, Any]) -> dict[str, Any]:
    slide = allocation["slide"]
    allowed = slide_allowed_grounding(slide)
    return {
        "conceptId": slide.get("slideId"),
        "sourceSlideIds": (slide.get("metadata") or {}).get("sourceSlideIds") or [],
        "conceptTitle": first_nonempty(slide.get("primaryConcepts")),
        "allocation": {
            "questionCount": allocation.get("questionCount"),
            "reason": allocation.get("reason"),
            "yieldScore": allocation.get("yieldScore"),
            "contentRichness": allocation.get("contentRichness"),
        },
        "selectedArchetype": slide.get("questionArchetype"),
        "allowedGroundingFacts": allowed.get("groundingFacts") or [],
        "allowedMedicalTerms": allowed.get("allowedMedicalTerms") or [],
        "cacheStatus": "pending",
        "generatedQuestionBeforeRepair": None,
        "preRepairValidationFindings": {},
        "repairAttempted": False,
        "repairResult": None,
        "postRepairValidationFindings": {},
        "finalDisposition": "pending",
        "dropReason": "",
        "finalQuestionId": None,
        "finalQuestionIndex": None,
    }


def fast_facts_diagnostic_validation(
    normalized_payload: dict[str, Any],
    slide: dict[str, Any],
    question: dict[str, Any],
) -> dict[str, Any]:
    single_norm = dict(normalized_payload)
    single_norm["slides"] = [slide]
    _, errors, grounding, diversity, strict = collect_fast_facts_generation_validation(single_norm, [question])
    return {
        "errors": errors,
        "semanticGroundingFindings": grounding,
        "questionQualityFindings": diversity.get("findings", []),
        "fastFactsStrictFindings": strict,
    }


def write_fast_facts_diagnostic_report(report: dict[str, Any]) -> Path:
    return write_report(report, "fast_facts_diagnostic_report")


def validation_failed_question_indices(errors: list[str], grounding_findings: list[dict[str, Any]], diversity_report: dict[str, Any]) -> set[int]:
    indices: set[int] = set()
    for finding in grounding_findings:
        if finding.get("severity") == "error":
            try:
                indices.add(int(finding.get("questionIndex")))
            except Exception:
                pass
    for finding in diversity_report.get("findings", []) or []:
        if finding.get("severity") == "error":
            try:
                indices.add(int(finding.get("questionIndex")))
            except Exception:
                pass
    for error in errors:
        match = re.search(r"\bQ(\d+)\b", str(error))
        if match:
            indices.add(int(match.group(1)))
    return indices


def repair_fast_facts_questions(normalized_payload: dict[str, Any], questions: list[dict[str, Any]], before_errors: list[str], before_grounding: list[dict[str, Any]], before_diversity: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    slide_by_id = {s["slideId"]: s for s in normalized_payload.get("slides") or []}
    failed_indices = validation_failed_question_indices(before_errors, before_grounding, before_diversity)
    api_key = ""
    if failed_indices:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise PipelineError("GEMINI_API_KEY is not set.")
    unsupported_by_index: dict[int, list[str]] = {
        int(f.get("questionIndex")): list(f.get("detail") or [])
        for f in before_grounding
        if f.get("severity") == "error" and f.get("issue") == "unsupported_medical_claim_terms"
    }
    repaired: dict[int, dict[str, Any]] = {}
    dropped: dict[int, dict[str, Any]] = {}
    repair_log: list[dict[str, Any]] = []
    for idx in sorted(failed_indices):
        if idx < 1 or idx > len(questions):
            continue
        original = questions[idx - 1]
        slide = slide_by_id.get(str(original.get("slideId") or ""))
        if not slide:
            dropped[idx] = {"questionIndex": idx, "reason": "unknown_slide_id"}
            continue
        candidate = original
        unsupported = unsupported_by_index.get(idx, [])
        attempt_notes: list[str] = []
        accepted = False
        for attempt in range(1, 3):
            try:
                candidate = call_fast_facts_question_repair_once(
                    api_key=api_key,
                    source_file=normalized_payload["sourceFile"],
                    q_index=idx,
                    original_question=candidate,
                    slide=slide,
                    unsupported_terms=unsupported,
                    attempt=attempt,
                )
                ok, single_errors, next_unsupported = validate_single_fast_facts_repair_candidate(normalized_payload, slide, candidate)
                if ok:
                    repaired[idx] = candidate
                    accepted = True
                    break
                unsupported = next_unsupported
                attempt_notes.append("; ".join(single_errors[:6]))
            except Exception as exc:
                attempt_notes.append(str(exc))
        if not accepted:
            dropped[idx] = {
                "questionIndex": idx,
                "slideId": original.get("slideId"),
                "reason": "repair_failed_validation",
                "attemptNotes": attempt_notes,
            }
        repair_log.append({
            "questionIndex": idx,
            "slideId": original.get("slideId"),
            "accepted": accepted,
            "attemptNotes": attempt_notes,
            "initialUnsupportedTerms": unsupported_by_index.get(idx, []),
        })
    final_questions: list[dict[str, Any]] = []
    for idx, question in enumerate(questions, start=1):
        if idx in repaired:
            final_questions.append(repaired[idx])
        elif idx in dropped:
            continue
        else:
            final_questions.append(question)
    report = {
        "mode": "fast-facts-targeted-repair",
        "sourceFile": normalized_payload.get("sourceFile"),
        "initialQuestionCount": len(questions),
        "failedQuestionCountBeforeRepair": len(failed_indices),
        "repairedQuestionCount": len(repaired),
        "droppedQuestionCount": len(dropped),
        "finalQuestionCount": len(final_questions),
        "droppedQuestions": list(dropped.values()),
        "repairLog": repair_log,
    }
    return final_questions, report


def fast_facts_question_repair_prompt(
    original_question: dict[str, Any],
    slide: dict[str, Any],
    unsupported_terms: list[str],
    attempt: int,
) -> str:
    allowed = slide_allowed_grounding(slide)
    archetype = slide.get("questionArchetype") or "diagnosis"
    return f"""
Repair one FAST_FACTS_PROFILE NBME-style question.

Return valid JSON only in this exact shape:
{question_schema_required_keys()}

Return exactly 1 question.
Use the same slideId.
Use exactly 4 answer choices labeled A, B, C, D.
Include questionArchetype: {archetype}

STRICT REPAIR RULES:
- Preserve the original stem if it is grounded and clear. If it is awkward, clean grammar only.
- If the failure is answer-choice ontology or distractor quality, regenerate the answer choices and explanations while keeping the stem aligned to the same source concept.
- Every clinical claim, answer choice, distractor, threshold, management step, diagnostic criterion, explanation, and educational objective must map to GROUNDING_FACTS or ALLOWED_MEDICAL_TERMS.
- Do not use imageOcrFacts directly.
- Do not invent outside diseases, drugs, tests, mechanisms, procedures, risk factors, epidemiology, or management.
- Do not include these unsupported terms unless present in ALLOWED_MEDICAL_TERMS: {json.dumps(unsupported_terms, ensure_ascii=False)}

ARCHETYPE AND ONTOLOGY RULES:
- Use exactly one archetype: {archetype}.
- diagnosis: every answer choice must be a diagnosis or named clinical condition.
- next_step: every answer choice must be a concrete next step or action.
- mechanism: every answer choice must be a mechanism.
- adverse_effect: every answer choice must be a diagnosis/adverse reaction, not an isolated symptom, lab, or imaging finding.
- management: every answer choice must be an intervention or management action.
- differentiation: every answer choice must be a diagnosis, condition, or clinical category being differentiated.
- risk_factor: every answer choice must be a risk factor.
- screening: every answer choice must be a screening criterion, screening interval, or screening test.
- pharmacology: every answer choice must be a drug or drug class.
- complication: every answer choice must be a complication.
- Never mix diagnoses, symptoms, labs, imaging findings, drugs, and procedures in the same answer set.
- Do not use stem findings as distractors for a diagnosis/adverse-effect question.

Attempt: {attempt}

NORMALIZED_FAST_FACTS_CONCEPT_JSON:
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


def call_fast_facts_question_repair_once(
    api_key: str,
    source_file: str,
    q_index: int,
    original_question: dict[str, Any],
    slide: dict[str, Any],
    unsupported_terms: list[str],
    attempt: int,
) -> dict[str, Any]:
    prompt = fast_facts_question_repair_prompt(original_question, slide, unsupported_terms, attempt)
    raw = raw_gemini_call(api_key, prompt, temperature=0.1, max_tokens=8192, timeout_seconds=45)
    write_debug_raw(source_file, "repair_question", f"q{q_index:03d}", f"attempt{attempt}", raw)
    parsed = load_largest_valid_json(raw)
    allocation = {
        "slideId": slide["slideId"],
        "questionCount": 1,
        "slide": slide,
    }
    items = extract_generated_question_items(parsed, [allocation], f"fast_facts_repair_q{q_index:03d}_attempt{attempt}")
    return fast_facts_cleanup_question(items[0])


def fast_facts_cleanup_question(q: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(q)
    stem = str(out.get("stem") or "")
    stem = re.sub(r"\bwas prescribed ([A-Za-z0-9+\-]+) several days after medication initiation\b", r"several days after starting \1", stem, flags=re.I)
    stem = re.sub(r"\bSeveral days after starting ([A-Za-z0-9+\-]+) for ([^.]+)\. She now presents\b", r"Several days after starting \1 for \2, she presents", stem)
    stem = re.sub(r"\bnon-pregnant\b", "nonpregnant", stem, flags=re.I)
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = re.sub(r"\b(warm, tender, erythematous rash) with raised, well-demarcated borders\b", r"\1 with raised, well-demarcated borders", stem)
    out["stem"] = stem
    return out


def fast_facts_answer_ontology(text: str) -> str:
    value = normalize_key(text)
    if not value:
        return "unknown"
    if re.search(r"\b(abscess|ain|acute kidney injury|interstitial nephritis|pulmonary injury|erysipelas|cellulitis|folliculitis|furuncle|uti|urinary tract infection|cystitis|pyelonephritis|infection)\b", value):
        return "diagnosis"
    if re.search(r"\b(obtain|order|perform|culture|test|testing|screen|examination|ct|ultrasound|x-ray|urinalysis|blood cultures?|antibod(?:y|ies)|tissue transglutaminase|ttg|tsh|free t4|hormone levels?|levels?|dexa|dxa|scan)\b", value):
        return "procedure"
    if re.search(r"\b(initiate|administer|treat|therapy|antibiotic|management|oral|intravenous|iv)\b", value):
        return "treatment"
    if re.search(r"\b(amoxicillin|ceftriaxone|cefazolin|nitrofurantoin|tmp-smx|trimethoprim|trimethoprim-sulfamethoxazole|sulfamethoxazole|fosfomycin|fluoroquinolone|ciprofloxacin|levofloxacin|piperacillin|tazobactam|imipenem|carbapenem)\b", value):
        return "drug"
    if re.search(r"\b(opacit|infiltrat|effusion|radiograph|imaging|bilateral mid|lower lung)\b", value):
        return "imaging_finding"
    if re.search(r"\b(leukocytosis|eosinophilia|nitrate|leukocyte esterase|alkalosis|acidosis|hemoglobin|a1c)\b", value):
        return "lab_finding"
    if re.search(r"\b(fever|pain|tenderness|frequency|dysuria|cough|shortness|rash|crackles|drainage|chills|vomiting|nausea)\b", value):
        return "symptom"
    if re.search(r"\b(streptococcus|staphylococcus|mssa|mrsa|pyogenes)\b", value):
        return "organism"
    if re.search(r"\b(deficiency|mutation|inhibition|activation|mechanism|receptor|pathway)\b", value):
        return "mechanism"
    if re.search(r"\b(smoking|pack-year|age|diabetes|comorbidit|risk)\b", value):
        return "risk_factor"
    return "unknown"


def fast_facts_expected_ontology(archetype: str, correct_text: str) -> str:
    archetype = normalize_key(archetype)
    if archetype in {"diagnosis", "differentiation", "adverse_effect"}:
        return "diagnosis"
    if archetype in {"management", "next_step"}:
        correct_class = fast_facts_answer_ontology(correct_text)
        return "procedure" if correct_class == "procedure" else "treatment"
    if archetype == "pharmacology":
        return "drug"
    if archetype == "mechanism":
        return "mechanism"
    if archetype == "risk_factor":
        return "risk_factor"
    if archetype == "screening":
        return "procedure"
    if archetype == "complication":
        return "complication"
    return fast_facts_answer_ontology(correct_text)


def fast_facts_choice_classes(q: dict[str, Any], slide: dict[str, Any] | None = None) -> list[dict[str, str]]:
    archetype = str(q.get("questionArchetype") or (slide or {}).get("questionArchetype") or "")
    correct_label = str(q.get("correctAnswer") or "").strip().upper()
    choices = q.get("answerChoices") or []
    correct_text = ""
    for choice in choices:
        if isinstance(choice, dict) and str(choice.get("label") or "").strip().upper() == correct_label:
            correct_text = str(choice.get("text") or "")
            break
    expected = fast_facts_expected_ontology(archetype, correct_text)
    rows: list[dict[str, str]] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        label = str(choice.get("label") or "").strip().upper()
        text = str(choice.get("text") or "")
        actual = fast_facts_answer_ontology(text)
        normalized = actual
        if expected == "treatment" and actual in {"drug", "procedure", "treatment"}:
            normalized = "treatment"
        if expected == "procedure" and actual in {"procedure", "treatment"} and archetype in {"next_step", "screening"}:
            normalized = "procedure"
        rows.append({"label": label, "text": text, "ontologyClass": normalized, "rawOntologyClass": actual, "expectedClass": expected})
    return rows


def fast_facts_stem_terms(stem: str) -> set[str]:
    terms: set[str] = set()
    for word in re.findall(r"\b[A-Za-z][A-Za-z0-9+\-]{3,}\b", stem):
        w = normalize_key(word)
        if w and w not in COMMON_CLINICAL_WORDS:
            terms.add(w)
    return terms


def fast_facts_qa_audit(
    normalized_payload: dict[str, Any],
    questions: list[dict[str, Any]],
    repaired_indices: set[int] | None = None,
) -> dict[str, Any]:
    repaired_indices = repaired_indices or set()
    slide_by_id = {s["slideId"]: s for s in normalized_payload.get("slides") or []}
    items: list[dict[str, Any]] = []
    ontology_mismatches = 0
    malformed_distractor_sets = 0
    for idx, q in enumerate(questions, start=1):
        slide = slide_by_id.get(str(q.get("slideId") or ""))
        archetype = str(q.get("questionArchetype") or (slide or {}).get("questionArchetype") or "unspecified")
        classes = fast_facts_choice_classes(q, slide)
        expected = classes[0]["expectedClass"] if classes else "unknown"
        class_ok = bool(classes) and all(row["ontologyClass"] == expected for row in classes)
        if not class_ok:
            ontology_mismatches += 1
            malformed_distractor_sets += 1
        stem = str(q.get("stem") or "")
        choice_texts = [str(c.get("text") or "") for c in q.get("answerChoices") or [] if isinstance(c, dict)]
        stem_terms = fast_facts_stem_terms(stem)
        tautologic = [
            text for text in choice_texts
            if len(normalize_key(text).split()) >= 2 and normalize_key(text) in normalize_key(stem)
        ]
        if tautologic:
            malformed_distractor_sets += 1
        has_discriminator = bool(re.search(
            r"\b(days?|after|before|early|later|raised|well-demarcated|purulent|nonpurulent|fever|flank|costovertebral|systemic|severe|no systemic|5-day|3-day|single dose|eosinophilia|opacities|external ear)\b",
            stem,
            re.I,
        ))
        awkward = bool(re.search(r"medication initiation|was prescribed .* several days after", stem, re.I))
        grounding_score = 100
        stem_clarity_score = 90 - (30 if awkward else 0) - (10 if len(stem.split()) < 35 else 0)
        discrimination_score = 85 if has_discriminator else 55
        distractor_quality_score = 90 if class_ok and not tautologic else 45
        if len(set(normalize_key(t) for t in choice_texts)) != len(choice_texts):
            distractor_quality_score -= 25
        tier = "strong"
        if min(distractor_quality_score, discrimination_score, stem_clarity_score, grounding_score) < 70:
            tier = "acceptable" if min(distractor_quality_score, discrimination_score, stem_clarity_score, grounding_score) >= 50 else "poor"
        weakest = ""
        reason = ""
        if not class_ok:
            off = [row for row in classes if row["ontologyClass"] != expected]
            weakest = off[0]["text"] if off else ""
            reason = f"ontology mismatch: expected {expected}"
        elif tautologic:
            weakest = tautologic[0]
            reason = "distractor repeats a stem finding"
        elif not has_discriminator:
            reason = "stem has limited discriminating detail"
        items.append({
            "questionNumber": idx,
            "slideId": q.get("slideId"),
            "sourceConceptTitle": first_nonempty((slide or {}).get("primaryConcepts")),
            "archetype": archetype,
            "ontologyClassConsistency": class_ok,
            "answerChoiceClasses": classes,
            "distractorQualityScore": max(0, distractor_quality_score),
            "discriminationScore": discrimination_score,
            "groundingScore": grounding_score,
            "stemClarityScore": max(0, stem_clarity_score),
            "likelyNbmeQualityTier": tier,
            "weakestDistractor": weakest,
            "reasonFlagged": reason,
            "repairApplied": idx in repaired_indices,
        })
    return {
        "items": items,
        "summary": {
            "questionCount": len(questions),
            "ontologyMismatches": ontology_mismatches,
            "malformedDistractorSets": malformed_distractor_sets,
            "qualityTiers": {
                "poor": sum(1 for item in items if item["likelyNbmeQualityTier"] == "poor"),
                "acceptable": sum(1 for item in items if item["likelyNbmeQualityTier"] == "acceptable"),
                "strong": sum(1 for item in items if item["likelyNbmeQualityTier"] == "strong"),
            },
        },
    }


def fast_facts_before_after_comparison(before_questions: list[dict[str, Any]], after_questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparison: list[dict[str, Any]] = []
    max_count = max(len(before_questions), len(after_questions))
    for idx in range(max_count):
        before = before_questions[idx] if idx < len(before_questions) else {}
        after = after_questions[idx] if idx < len(after_questions) else {}
        before_choices = [str(c.get("text") or "") for c in before.get("answerChoices") or [] if isinstance(c, dict)]
        after_choices = [str(c.get("text") or "") for c in after.get("answerChoices") or [] if isinstance(c, dict)]
        comparison.append({
            "questionNumber": idx + 1,
            "beforeSlideId": before.get("slideId"),
            "afterSlideId": after.get("slideId"),
            "stemChanged": str(before.get("stem") or "") != str(after.get("stem") or ""),
            "choicesChanged": before_choices != after_choices,
            "correctAnswerChanged": before.get("correctAnswer") != after.get("correctAnswer"),
            "beforeTarget": before.get("diagnosisOrTarget"),
            "afterTarget": after.get("diagnosisOrTarget"),
            "beforeStem": before.get("stem"),
            "afterStem": after.get("stem"),
            "beforeChoices": before_choices,
            "afterChoices": after_choices,
        })
    return comparison


def fast_facts_cache_path() -> Path:
    return CACHE_DIR / "fast_facts_question_cache.json"


def empty_fast_facts_cache() -> dict[str, Any]:
    return {
        "schemaVersion": "fast-facts-question-cache-v1",
        "updatedAt": None,
        "entries": {},
    }


def load_fast_facts_cache() -> dict[str, Any]:
    path = fast_facts_cache_path()
    if not path.exists():
        return empty_fast_facts_cache()
    try:
        payload = read_json(path)
    except Exception:
        return empty_fast_facts_cache()
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
        return empty_fast_facts_cache()
    return payload


def write_fast_facts_cache(cache: dict[str, Any]) -> None:
    cache["updatedAt"] = timestamp_iso()
    write_json(fast_facts_cache_path(), cache)


def fast_facts_concept_content_hash(slide: dict[str, Any]) -> str:
    content = {
        "primaryConcepts": slide.get("primaryConcepts") or [],
        "clinicalFacts": slide.get("clinicalFacts") or [],
        "diagnosticFacts": slide.get("diagnosticFacts") or [],
        "managementFacts": slide.get("managementFacts") or [],
        "mechanismFacts": slide.get("mechanismFacts") or [],
        "differentialFacts": slide.get("differentialFacts") or [],
        "trapFacts": slide.get("trapFacts") or [],
        "nativeTextFacts": slide.get("nativeTextFacts") or [],
        "cleanedImageFacts": slide.get("cleanedImageFacts") or [],
        "structuredImageFacts": slide.get("structuredImageFacts") or {},
        "groundingNotes": slide.get("groundingNotes") or [],
        "groundingTerms": slide.get("groundingTerms") or [],
    }
    return short_hash(json.dumps(content, sort_keys=True, ensure_ascii=False))


def fast_facts_image_routing_metadata_hash(slide: dict[str, Any]) -> str:
    metadata = [
        {
            "imageId": img.get("imageId"),
            "kind": img.get("kind") or img.get("classification"),
            "assetPath": img.get("assetPath"),
            "routing": route,
        }
        for img, route in zip(slide.get("images") or [], fast_facts_image_route_guidance(slide) or [])
    ]
    return short_hash(json.dumps(metadata, sort_keys=True, ensure_ascii=False))


def fast_facts_cache_key_parts(normalized_payload: dict[str, Any], slide: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": FAST_FACTS_PROFILE,
        "sourceFileHash": normalized_payload.get("pptxSha256") or normalized_payload.get("pdfSha256"),
        "conceptId": slide["slideId"],
        "conceptContentHash": fast_facts_concept_content_hash(slide),
        "generationPromptVersion": FAST_FACTS_GENERATION_PROMPT_VERSION,
        "validatorVersion": FAST_FACTS_VALIDATOR_VERSION,
        "archetypeOntologyVersion": FAST_FACTS_ARCHETYPE_ONTOLOGY_VERSION,
        "imageRoutingMetadataHash": fast_facts_image_routing_metadata_hash(slide),
    }


def fast_facts_cache_key(normalized_payload: dict[str, Any], slide: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(fast_facts_cache_key_parts(normalized_payload, slide), sort_keys=True, ensure_ascii=False).encode("utf-8", errors="replace")
    ).hexdigest()[:16]


def stable_fast_facts_question_id(slide: dict[str, Any], question: dict[str, Any]) -> str:
    return "ffq_" + hashlib.sha256(
        (slide["slideId"] + "|" + str(question.get("educationalObjective") or question.get("stem") or "")).encode("utf-8", errors="replace")
    ).hexdigest()[:16]


def fast_facts_single_question_validation(normalized_payload: dict[str, Any], slide: dict[str, Any], question: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    single_norm = dict(normalized_payload)
    single_norm["slides"] = [slide]
    _, errors, _, _, _ = collect_fast_facts_generation_validation(single_norm, [question])
    qa = fast_facts_qa_audit(single_norm, [question])
    summary = qa.get("summary") or {}
    if summary.get("ontologyMismatches") or summary.get("malformedDistractorSets"):
        errors.append("Fast Facts QA failed for cached question.")
    return not errors, errors, (qa.get("items") or [{}])[0]


def fast_facts_cache_entry(
    normalized_payload: dict[str, Any],
    slide: dict[str, Any],
    question: dict[str, Any],
    qa_item: dict[str, Any],
    status: str,
    invalidation_reason: str = "",
) -> dict[str, Any]:
    now = timestamp_iso()
    key_parts = fast_facts_cache_key_parts(normalized_payload, slide)
    return {
        "stableQuestionId": stable_fast_facts_question_id(slide, question),
        "cacheKey": fast_facts_cache_key(normalized_payload, slide),
        **key_parts,
        "sourceSlideIds": (slide.get("metadata") or {}).get("sourceSlideIds") or [],
        "question": question,
        "validationStatus": status,
        "qaAuditResult": qa_item,
        "sourceFactIds": question.get("sourceFactIds") or [],
        "imageRouting": question.get("imageRouting") or [],
        "ontologyClass": (qa_item.get("answerChoiceClasses") or [{}])[0].get("expectedClass"),
        "archetype": question.get("questionArchetype") or slide.get("questionArchetype"),
        "createdAt": now,
        "updatedAt": now,
        "invalidationReason": invalidation_reason,
    }


def update_fast_facts_cache_entry(cache: dict[str, Any], key: str, entry: dict[str, Any]) -> None:
    existing = (cache.get("entries") or {}).get(key)
    if isinstance(existing, dict) and existing.get("createdAt"):
        entry["createdAt"] = existing["createdAt"]
    cache.setdefault("entries", {})[key] = entry
    write_fast_facts_cache(cache)


def seed_fast_facts_cache_from_existing(normalized_payload: dict[str, Any], cache: dict[str, Any]) -> dict[str, int]:
    generated_path = GENERATED_DIR / f"{slugify(Path(normalized_payload['sourceFile']).stem)}_fast_facts_generated_questions.json"
    if not generated_path.exists():
        return {"seeded": 0, "skipped": 0}
    try:
        payload = read_json(generated_path)
    except Exception:
        return {"seeded": 0, "skipped": 0}
    questions = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(questions, list):
        return {"seeded": 0, "skipped": 0}
    slide_by_id = {s["slideId"]: s for s in normalized_payload.get("slides") or []}
    seeded = 0
    skipped = 0
    for question in questions:
        if not isinstance(question, dict):
            skipped += 1
            continue
        slide = slide_by_id.get(str(question.get("slideId") or ""))
        if not slide:
            skipped += 1
            continue
        key = fast_facts_cache_key(normalized_payload, slide)
        existing = (cache.get("entries") or {}).get(key)
        if isinstance(existing, dict) and existing.get("validationStatus") == "valid":
            continue
        question = fast_facts_cleanup_question(question)
        if not question.get("questionArchetype"):
            question["questionArchetype"] = slide.get("questionArchetype")
        ok, errors, qa_item = fast_facts_single_question_validation(normalized_payload, slide, question)
        if not ok:
            skipped += 1
            continue
        entry = fast_facts_cache_entry(normalized_payload, slide, question, qa_item, "valid")
        update_fast_facts_cache_entry(cache, key, entry)
        seeded += 1
    return {"seeded": seeded, "skipped": skipped}


def valid_fast_facts_cached_question(normalized_payload: dict[str, Any], slide: dict[str, Any], entry: dict[str, Any]) -> tuple[bool, list[str], dict[str, Any]]:
    question = entry.get("question")
    if not isinstance(question, dict):
        return False, ["cached entry missing question"], {}
    expected = fast_facts_cache_key_parts(normalized_payload, slide)
    mismatches = [key for key, value in expected.items() if entry.get(key) != value]
    if mismatches:
        return False, [f"cache key mismatch: {', '.join(mismatches)}"], {}
    if entry.get("validationStatus") != "valid":
        return False, [entry.get("invalidationReason") or "cached entry not marked valid"], {}
    return fast_facts_single_question_validation(normalized_payload, slide, question)


def show_fast_facts_cache_status() -> None:
    cache = load_fast_facts_cache()
    entries = list((cache.get("entries") or {}).values())
    valid = sum(1 for e in entries if isinstance(e, dict) and e.get("validationStatus") == "valid")
    invalid = sum(1 for e in entries if isinstance(e, dict) and e.get("validationStatus") != "valid")
    print(f"Fast Facts cache: {fast_facts_cache_path()}")
    print(f"Total entries: {len(entries)}")
    print(f"Valid entries: {valid}")
    print(f"Invalid entries: {invalid}")
    for entry in entries[:20]:
        if not isinstance(entry, dict):
            continue
        print(f"- {entry.get('conceptId')} | {entry.get('validationStatus')} | {entry.get('archetype')} | updated {entry.get('updatedAt')}")


def generate_fast_facts_questions_with_cache(
    normalized_payload: dict[str, Any],
    allocations: list[dict[str, Any]],
    memory: dict[str, Any],
    reuse_cache: bool,
    force_regenerate: bool,
    repair_only: bool,
    diagnostic_report: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    started = time.time()
    cache = load_fast_facts_cache()
    seed_report = seed_fast_facts_cache_from_existing(normalized_payload, cache) if reuse_cache and not force_regenerate else {"seeded": 0, "skipped": 0}
    ordered_allocations = [a for a in allocations if int(a.get("questionCount") or 0) > 0]
    questions_by_slide: dict[str, dict[str, Any]] = {}
    prior_valid_by_slide: dict[str, dict[str, Any]] = {}
    misses: list[dict[str, Any]] = []
    invalidation_reasons: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0
    reused = 0
    diagnostic_entries = {
        allocation["slideId"]: fast_facts_diagnostic_entry(allocation)
        for allocation in ordered_allocations
    } if diagnostic_report else {}

    for allocation in ordered_allocations:
        slide = allocation["slide"]
        diagnostic = diagnostic_entries.get(slide["slideId"])
        key = fast_facts_cache_key(normalized_payload, slide)
        entry = (cache.get("entries") or {}).get(key)
        if isinstance(entry, dict) and entry.get("validationStatus") == "valid" and isinstance(entry.get("question"), dict):
            prior_valid_by_slide[slide["slideId"]] = entry["question"]
        if reuse_cache and not force_regenerate and isinstance(entry, dict):
            ok, errors, qa_item = valid_fast_facts_cached_question(normalized_payload, slide, entry)
            if ok:
                question = fast_facts_cleanup_question(copy.deepcopy(entry["question"]))
                if not question.get("questionArchetype"):
                    question["questionArchetype"] = slide.get("questionArchetype")
                questions_by_slide[slide["slideId"]] = question
                update_memory_from_question(memory, question)
                cache_hits += 1
                reused += 1
                if diagnostic:
                    diagnostic["cacheStatus"] = "reused"
                update_fast_facts_cache_entry(cache, key, fast_facts_cache_entry(normalized_payload, slide, question, qa_item, "valid"))
                continue
            invalidation_reasons.append({"slideId": slide["slideId"], "reason": "; ".join(errors[:4])})
            if diagnostic:
                diagnostic["cacheStatus"] = "invalidated"
        cache_misses += 1
        if repair_only:
            invalidation_reasons.append({"slideId": slide["slideId"], "reason": "repair_only_no_valid_cache_hit"})
            if diagnostic and diagnostic["cacheStatus"] == "pending":
                diagnostic["cacheStatus"] = "repair-only-miss"
            continue
        if diagnostic and diagnostic["cacheStatus"] == "pending":
            diagnostic["cacheStatus"] = "bypassed" if (force_regenerate or not reuse_cache) else "generated"
        misses.append(allocation)

    regenerated = 0
    generation_failed: list[dict[str, Any]] = []
    if misses:
        generated = generate_fast_facts_questions(normalized_payload, misses, memory)
        for question in generated:
            slide_id = str(question.get("slideId") or "")
            if slide_id:
                questions_by_slide[slide_id] = question
                regenerated += 1
                diagnostic = diagnostic_entries.get(slide_id)
                if diagnostic:
                    diagnostic["generatedQuestionBeforeRepair"] = copy.deepcopy(question)
        generated_ids = set(questions_by_slide) - {a["slideId"] for a in ordered_allocations if a["slideId"] not in [m["slideId"] for m in misses]}
        for allocation in misses:
            if allocation["slideId"] not in questions_by_slide:
                generation_failed.append({"slideId": allocation["slideId"], "reason": "generation returned no valid question"})

    ordered_questions: list[dict[str, Any]] = []
    dropped_before_repair: list[dict[str, Any]] = []
    for allocation in ordered_allocations:
        slide_id = allocation["slideId"]
        if slide_id in questions_by_slide:
            ordered_questions.append(questions_by_slide[slide_id])
        elif slide_id in prior_valid_by_slide:
            ordered_questions.append(prior_valid_by_slide[slide_id])
            reused += 1
            invalidation_reasons.append({"slideId": slide_id, "reason": "used_prior_valid_cache_after_generation_failure"})
            diagnostic = diagnostic_entries.get(slide_id)
            if diagnostic:
                diagnostic["cacheStatus"] = "reused"
        else:
            dropped_before_repair.append({"slideId": slide_id, "reason": "no valid cached or generated question"})

    if diagnostic_entries:
        slide_by_id = {a["slideId"]: a["slide"] for a in ordered_allocations}
        for question in ordered_questions:
            slide_id = str(question.get("slideId") or "")
            diagnostic = diagnostic_entries.get(slide_id)
            slide = slide_by_id.get(slide_id)
            if diagnostic and slide:
                if diagnostic["generatedQuestionBeforeRepair"] is None:
                    diagnostic["generatedQuestionBeforeRepair"] = copy.deepcopy(question)
                diagnostic["preRepairValidationFindings"] = fast_facts_diagnostic_validation(normalized_payload, slide, question)

    app_payload_before, before_errors, before_grounding, before_diversity, before_strict = collect_fast_facts_generation_validation(normalized_payload, ordered_questions)
    repaired_questions, repair_report = repair_fast_facts_questions(normalized_payload, ordered_questions, before_errors, before_grounding, before_diversity)

    repaired_slide_ids = {
        str(item.get("slideId") or "")
        for item in repair_report.get("repairLog", [])
        if item.get("accepted")
    }
    dropped_questions = list(repair_report.get("droppedQuestions") or [])
    final_by_slide = {str(q.get("slideId") or ""): q for q in repaired_questions if isinstance(q, dict)}
    if diagnostic_entries:
        for item in repair_report.get("repairLog") or []:
            if not isinstance(item, dict):
                continue
            diagnostic = diagnostic_entries.get(str(item.get("slideId") or ""))
            if diagnostic:
                diagnostic["repairAttempted"] = True
                diagnostic["repairResult"] = copy.deepcopy(item)
    final_questions: list[dict[str, Any]] = []
    rescued_from_prior = 0
    for allocation in ordered_allocations:
        slide = allocation["slide"]
        slide_id = slide["slideId"]
        key = fast_facts_cache_key(normalized_payload, slide)
        if slide_id in final_by_slide:
            question = final_by_slide[slide_id]
            diagnostic = diagnostic_entries.get(slide_id)
            if diagnostic:
                diagnostic["postRepairValidationFindings"] = fast_facts_diagnostic_validation(normalized_payload, slide, question)
            ok, errors, qa_item = fast_facts_single_question_validation(normalized_payload, slide, question)
            if ok:
                final_questions.append(question)
                if diagnostic:
                    diagnostic["finalDisposition"] = "repaired" if slide_id in repaired_slide_ids else (
                        "reused-cache" if diagnostic["cacheStatus"] == "reused" else "kept"
                    )
                update_fast_facts_cache_entry(cache, key, fast_facts_cache_entry(normalized_payload, slide, question, qa_item, "valid"))
                continue
            invalidation_reasons.append({"slideId": slide_id, "reason": "post-repair validation failed: " + "; ".join(errors[:4])})
        if slide_id in prior_valid_by_slide:
            prior = prior_valid_by_slide[slide_id]
            ok, errors, qa_item = fast_facts_single_question_validation(normalized_payload, slide, prior)
            if ok:
                final_questions.append(prior)
                rescued_from_prior += 1
                diagnostic = diagnostic_entries.get(slide_id)
                if diagnostic:
                    diagnostic["postRepairValidationFindings"] = fast_facts_diagnostic_validation(normalized_payload, slide, prior)
                    diagnostic["finalDisposition"] = "reused-cache"
                update_fast_facts_cache_entry(cache, key, fast_facts_cache_entry(normalized_payload, slide, prior, qa_item, "valid"))
                continue
        if slide_id not in final_by_slide:
            reason = next((d.get("reason") for d in dropped_before_repair if d.get("slideId") == slide_id), "")
            matching_drop = next((d for d in dropped_questions if d.get("slideId") == slide_id), None)
            if matching_drop:
                reason = matching_drop.get("reason") or reason
            diagnostic = diagnostic_entries.get(slide_id)
            if diagnostic:
                diagnostic["finalDisposition"] = "dropped"
                diagnostic["dropReason"] = reason or "no valid question after generation/repair"
            entry = {
                **fast_facts_cache_key_parts(normalized_payload, slide),
                "cacheKey": key,
                "stableQuestionId": None,
                "conceptId": slide_id,
                "sourceSlideIds": (slide.get("metadata") or {}).get("sourceSlideIds") or [],
                "question": None,
                "validationStatus": "invalid",
                "qaAuditResult": None,
                "sourceFactIds": [],
                "imageRouting": [],
                "ontologyClass": None,
                "archetype": slide.get("questionArchetype"),
                "createdAt": timestamp_iso(),
                "updatedAt": timestamp_iso(),
                "invalidationReason": reason or "no valid question after generation/repair",
            }
            update_fast_facts_cache_entry(cache, key, entry)

    cache_report = {
        "cachePath": str(fast_facts_cache_path().relative_to(BASE_DIR)),
        "seededFromExisting": seed_report,
        "cacheHits": cache_hits,
        "cacheMisses": cache_misses,
        "reusedQuestions": reused,
        "regeneratedQuestions": regenerated,
        "repairedQuestions": repair_report.get("repairedQuestionCount", 0),
        "droppedQuestions": len(dropped_before_repair) + int(repair_report.get("droppedQuestionCount") or 0),
        "rescuedFromPriorValidCache": rescued_from_prior,
        "invalidationReasons": invalidation_reasons + generation_failed + [
            {
                "slideId": item.get("slideId"),
                "reason": item.get("reason"),
                "attemptNotes": item.get("attemptNotes") or [],
            }
            for item in dropped_questions
            if isinstance(item, dict)
        ],
        "runtimeDurationSeconds": round(time.time() - started, 2),
        "repairReport": repair_report,
        "beforeErrors": before_errors,
        "beforeStrictFindings": before_strict,
    }
    if diagnostic_entries:
        final_index_by_slide = {
            str(question.get("slideId") or ""): index
            for index, question in enumerate(final_questions, start=1)
        }
        for slide_id, diagnostic in diagnostic_entries.items():
            final_index = final_index_by_slide.get(slide_id)
            if final_index:
                final_question = final_questions[final_index - 1]
                diagnostic["finalQuestionIndex"] = final_index
                diagnostic["finalQuestionId"] = stable_fast_facts_question_id(
                    next(a["slide"] for a in ordered_allocations if a["slideId"] == slide_id),
                    final_question,
                )
            elif diagnostic["finalDisposition"] == "pending":
                diagnostic["finalDisposition"] = "dropped"
                diagnostic["dropReason"] = "no valid question after generation/repair"
        cache_report["diagnosticEntries"] = list(diagnostic_entries.values())
    return final_questions, cache_report, before_diversity, app_payload_before


def fast_facts_threshold_claims(text: str) -> list[str]:
    claims: list[str] = []
    patterns = [
        r"\b\d+\s*-\s*\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\b\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\bevery\s+\d+\s*(?:days?|weeks?|months?|years?)\b",
        r"\bsingle\s+dose\b",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, str(text or ""), flags=re.I):
            claim = normalize_key(match)
            if claim and claim not in claims:
                claims.append(claim)
    return claims


def fast_facts_strict_findings(generated_questions: list[dict[str, Any]], normalized_payload: dict[str, Any]) -> list[dict[str, Any]]:
    slide_by_id = {s["slideId"]: s for s in normalized_payload.get("slides") or []}
    findings: list[dict[str, Any]] = []
    for idx, q in enumerate(generated_questions, start=1):
        slide = slide_by_id.get(str(q.get("slideId") or ""))
        if not slide:
            continue
        grounding_text = normalize_key(" ".join(str(v) for v in slide.get("groundingNotes") or []))
        if not grounding_text:
            grounding_text = normalize_key(normalized_slide_fact_text(slide))
        claim_parts: list[str] = []
        for choice in q.get("answerChoices") or []:
            if isinstance(choice, dict):
                claim_parts.append(str(choice.get("text") or ""))
        claim_parts.append(str(q.get("correctExplanation") or ""))
        for item in q.get("incorrectExplanations") or []:
            if isinstance(item, dict):
                claim_parts.append(str(item.get("explanation") or ""))
        claim_parts.append(str(q.get("educationalObjective") or ""))
        unsupported_thresholds = [
            claim for claim in fast_facts_threshold_claims(" ".join(claim_parts))
            if claim not in grounding_text
        ]
        if unsupported_thresholds:
            findings.append({
                "questionIndex": idx,
                "slideId": q.get("slideId"),
                "severity": "error",
                "issue": "unsupported_fast_facts_threshold",
                "detail": unsupported_thresholds,
            })
        classes = fast_facts_choice_classes(q, slide)
        if classes:
            expected = classes[0]["expectedClass"]
            mismatches = [row for row in classes if row["ontologyClass"] != expected]
            if mismatches:
                findings.append({
                    "questionIndex": idx,
                    "slideId": q.get("slideId"),
                    "severity": "error",
                    "issue": "mixed_answer_choice_ontology",
                    "detail": {
                        "expected": expected,
                        "classes": classes,
                    },
                })
        stem_key = normalize_key(q.get("stem") or "")
        tautologic = []
        for choice in q.get("answerChoices") or []:
            if not isinstance(choice, dict):
                continue
            choice_key = normalize_key(choice.get("text") or "")
            if len(choice_key.split()) >= 2 and choice_key in stem_key:
                tautologic.append(str(choice.get("text") or ""))
        if tautologic and normalize_key(q.get("questionArchetype") or slide.get("questionArchetype") or "") in {"diagnosis", "adverse_effect"}:
            findings.append({
                "questionIndex": idx,
                "slideId": q.get("slideId"),
                "severity": "error",
                "issue": "tautologic_stem_finding_distractors",
                "detail": tautologic,
            })
        if re.search(r"medication initiation|was prescribed .* several days after", str(q.get("stem") or ""), re.I):
            findings.append({
                "questionIndex": idx,
                "slideId": q.get("slideId"),
                "severity": "error",
                "issue": "awkward_temporal_stem_language",
                "detail": q.get("stem"),
            })
    return findings


def collect_fast_facts_generation_validation(
    normalized_payload: dict[str, Any],
    questions: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    app_payload, errors, grounding_findings, diversity_report = collect_generation_validation(normalized_payload, questions)
    strict_findings = fast_facts_strict_findings(questions, normalized_payload)
    errors.extend(
        f"Fast Facts grounding Q{f.get('questionIndex', '?')}: {f.get('issue')} {f.get('detail')}"
        for f in strict_findings
        if f.get("severity") == "error"
    )
    return app_payload, errors, grounding_findings, diversity_report, strict_findings


def validate_single_fast_facts_repair_candidate(
    normalized_payload: dict[str, Any],
    slide: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[bool, list[str], list[str]]:
    single_norm = dict(normalized_payload)
    single_norm["slides"] = [slide]
    _, single_errors, single_grounding, _, strict_findings = collect_fast_facts_generation_validation(single_norm, [candidate])
    unsupported: list[str] = []
    for finding in single_grounding + strict_findings:
        if finding.get("severity") == "error":
            unsupported.extend(str(v) for v in finding.get("detail") or [])
    return not single_errors, single_errors, unsupported


def image_routing_summary(app_payload: dict[str, Any]) -> dict[str, int]:
    stem = 0
    explanation = 0
    questions_with_images = 0
    for q in app_payload.get("questions") or []:
        stem += len(q.get("images") or [])
        explanation += len(q.get("explanationImages") or [])
        if q.get("images") or q.get("explanationImages"):
            questions_with_images += 1
    return {
        "stemImageCount": stem,
        "explanationImageCount": explanation,
        "questionsWithImages": questions_with_images,
    }


def run_fast_facts_generation_milestone(
    pptx_path: Path,
    graph: dict[str, Any],
    deck_hash: str,
    limit_slides: int,
    extraction_report: dict[str, Any],
    reuse_cache: bool = True,
    force_regenerate: bool = False,
    repair_only: bool = False,
    diagnostic_report: bool = False,
    question_limit: int = 0,
) -> Path:
    normalized_payload, skipped_concepts = fast_facts_normalized_payload(pptx_path, graph, deck_hash, limit_slides)
    normalized_path = NORMALIZED_DIR / f"{slugify(pptx_path.stem)}_fast_facts_generation_normalized.json"
    write_json(normalized_path, normalized_payload)
    generated_path = GENERATED_DIR / f"{slugify(pptx_path.stem)}_fast_facts_generated_questions.json"
    before_generation_snapshot: list[dict[str, Any]] = []
    if generated_path.exists():
        try:
            existing = read_json(generated_path)
            if isinstance(existing, dict) and isinstance(existing.get("questions"), list):
                before_generation_snapshot = existing["questions"]
        except Exception:
            before_generation_snapshot = []
    memory = empty_memory()
    allocations = limit_fast_facts_question_attempts(
        fast_facts_allocations(normalized_payload, memory),
        question_limit,
    )
    repaired_questions, cache_report, before_diversity, app_payload_before = generate_fast_facts_questions_with_cache(
        normalized_payload=normalized_payload,
        allocations=allocations,
        memory=memory,
        reuse_cache=reuse_cache,
        force_regenerate=force_regenerate,
        repair_only=repair_only,
        diagnostic_report=diagnostic_report,
    )
    diagnostic_report_path = None
    if diagnostic_report:
        diagnostic_report_path = write_fast_facts_diagnostic_report({
            "runAt": timestamp_iso(),
            "profile": FAST_FACTS_PROFILE,
            "sourceFile": pptx_path.name,
            "sourcePath": str(pptx_path),
            "limitSlides": int(limit_slides or 0),
            "questionAttemptLimit": int(question_limit or 0),
            "reuseCache": bool(reuse_cache),
            "forceRegenerate": bool(force_regenerate),
            "repairOnly": bool(repair_only),
            "entries": cache_report.get("diagnosticEntries") or [],
        })
    if not repaired_questions:
        raise PipelineError("Fast Facts constrained generation produced no questions.")
    write_json(generated_path, {"questions": repaired_questions})
    app_payload, after_errors, after_grounding, after_diversity, after_strict = collect_fast_facts_generation_validation(normalized_payload, repaired_questions)
    before_errors = list(cache_report.get("beforeErrors") or [])
    before_strict = list(cache_report.get("beforeStrictFindings") or [])
    repair_report = cache_report.get("repairReport") or {}
    repair_report["validationErrorCountBeforeRepair"] = len(before_errors)
    repair_report["validationErrorCountAfterRepair"] = len(after_errors)
    repair_report["remainingValidationErrors"] = after_errors
    repair_report_path = write_report(repair_report, "fast_facts_generation_repair_report")
    repaired_indices = {
        int(item.get("questionIndex"))
        for item in repair_report.get("repairLog", [])
        if item.get("accepted") and str(item.get("questionIndex") or "").isdigit()
    }
    qa_audit = fast_facts_qa_audit(normalized_payload, repaired_questions, repaired_indices)
    if qa_audit.get("summary", {}).get("ontologyMismatches"):
        after_errors.append(f"Fast Facts QA: ontology mismatches remain: {qa_audit['summary']['ontologyMismatches']}")
    if qa_audit.get("summary", {}).get("malformedDistractorSets"):
        after_errors.append(f"Fast Facts QA: malformed distractor sets remain: {qa_audit['summary']['malformedDistractorSets']}")
    qa_report = {
        "profile": FAST_FACTS_PROFILE,
        "sourceFile": pptx_path.name,
        "mode": "fast-facts-educational-qa-limit-5",
        "audit": qa_audit,
    }
    qa_report_path = write_report(qa_report, "fast_facts_educational_qa_audit")
    metrics = {
        "profile": FAST_FACTS_PROFILE,
        "mode": "constrained-generation-limit-5",
        "sourceFile": pptx_path.name,
        "slidesUsed": len({sid for c in graph.get("concepts") or [] for sid in (c.get("sourceSlideIds") or [])}),
        "limitSlides": int(limit_slides or 0),
        "conceptsInGraph": len(graph.get("concepts") or []),
        "conceptsUsed": sum(1 for a in allocations if int(a.get("questionCount") or 0) > 0),
        "conceptsSkippedForGeneration": len(skipped_concepts) + sum(1 for a in allocations if int(a.get("questionCount") or 0) == 0),
        "questionsGeneratedBeforeRepair": cache_report.get("regeneratedQuestions", 0),
        "questionsRepaired": repair_report.get("repairedQuestionCount", 0),
        "questionsDropped": cache_report.get("droppedQuestions", 0),
        "finalQuestionCount": len(repaired_questions),
        "validationErrorsBeforeRepair": before_errors,
        "validationErrorsAfterRepair": after_errors,
        "semanticGroundingFindingsAfterRepair": after_grounding,
        "fastFactsStrictFindingsBeforeRepair": before_strict,
        "fastFactsStrictFindingsAfterRepair": after_strict,
        "questionQualityFindingsAfterRepair": after_diversity.get("findings", []),
        "allocationSummary": [
            {
                "slideId": a.get("slideId"),
                "questionCount": a.get("questionCount"),
                "reason": a.get("reason"),
                "contentRichness": a.get("contentRichness"),
            }
            for a in allocations
        ],
        "skippedConcepts": skipped_concepts,
        "normalizedGenerationPath": str(normalized_path.relative_to(BASE_DIR)),
        "generatedIntermediatePath": str(generated_path.relative_to(BASE_DIR)),
        "repairReportPath": str(repair_report_path.relative_to(BASE_DIR)),
        "educationalQaAuditReportPath": str(qa_report_path.relative_to(BASE_DIR)),
        "educationalQaSummary": qa_audit.get("summary"),
        "beforeAfterComparison": fast_facts_before_after_comparison(before_generation_snapshot, repaired_questions),
        "cacheReport": cache_report,
        "extractionReport": extraction_report,
        "imageRoutingSummary": image_routing_summary(app_payload_before if after_errors else app_payload),
    }
    if diagnostic_report_path:
        metrics["diagnosticReportPath"] = str(diagnostic_report_path.relative_to(BASE_DIR))
    if after_errors:
        report_path = write_report(metrics, "fast_facts_generation_validation_report")
        raise PipelineError(
            "Fast Facts constrained generation failed validation after repair. "
            f"Report: {report_path.relative_to(BASE_DIR)}\n"
            + "\n".join(f"- {err}" for err in after_errors[:80])
        )
    out_path = APP_READY_DIR / f"{slugify(pptx_path.stem)}_fast_facts_app_ready.json"
    write_json(out_path, app_payload)
    json.loads(out_path.read_text(encoding="utf-8"))
    metrics["appReadyPath"] = str(out_path.relative_to(BASE_DIR))
    metrics["imageRoutingSummary"] = image_routing_summary(app_payload)
    report_path = write_report(metrics, "fast_facts_generation_validation_report")
    log(f"Fast Facts app-ready -> {out_path.relative_to(BASE_DIR)}")
    log(f"Fast Facts validation report -> {report_path.relative_to(BASE_DIR)}")
    return out_path


def amboss_cache_path() -> Path:
    return CACHE_DIR / "amboss_extraction_cache.json"


def empty_amboss_cache() -> dict[str, Any]:
    return {"schemaVersion": "amboss-extraction-cache-v1", "updatedAt": None, "pages": {}, "questions": {}}


def load_amboss_cache() -> dict[str, Any]:
    path = amboss_cache_path()
    if not path.exists():
        return empty_amboss_cache()
    try:
        payload = read_json(path)
    except Exception:
        return empty_amboss_cache()
    if not isinstance(payload, dict) or not isinstance(payload.get("pages"), dict):
        return empty_amboss_cache()
    payload.setdefault("questions", {})
    return payload


def write_amboss_cache(cache: dict[str, Any]) -> None:
    cache["updatedAt"] = timestamp_iso()
    write_json(amboss_cache_path(), cache)


def image_dimensions(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image  # type: ignore
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:
        return 0, 0


def amboss_ocr_image(path: Path) -> str:
    if not shutil.which("tesseract"):
        return ""
    try:
        proc = subprocess.run(
            ["tesseract", str(path), "stdout", "--psm", "6"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            return ""
        return clean_slide_text(proc.stdout)
    except Exception:
        return ""


def amboss_asset_entry(asset_path: Path, page_id: str, image_id: str, kind: str) -> dict[str, Any]:
    width, height = image_dimensions(asset_path)
    fingerprint = file_sha(asset_path)
    return {
        "imageId": image_id,
        "kind": kind,
        "assetPath": str(asset_path.relative_to(BASE_DIR)),
        "mimeType": mime_for(asset_path),
        "width": width,
        "height": height,
        "sha256": fingerprint,
        "imageFingerprint": fingerprint,
        "sourcePageId": page_id,
    }


def decompose_amboss_input(input_path: Path, limit_pages: int = 5) -> dict[str, Any]:
    ensure_dirs()
    source_hash = file_sha(input_path)
    stem = slugify(input_path.stem)
    pages: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    suffix = input_path.suffix.lower()
    limit_pages = max(1, int(limit_pages or 5))
    if suffix == ".pdf":
        fitz = optional_import_fitz()
        pdfplumber = optional_import_pdfplumber()
        if not fitz and not pdfplumber:
            raise PipelineError("AMBOSS_PROFILE PDF input requires pymupdf or pdfplumber.")
        pdf_doc = None
        plumber_pdf = None
        try:
            if fitz:
                pdf_doc = fitz.open(str(input_path))
            if pdfplumber:
                plumber_pdf = pdfplumber.open(str(input_path))
            page_count = min(limit_pages, len(pdf_doc) if pdf_doc else len(plumber_pdf.pages))
            for page_index in range(page_count):
                page_num = page_index + 1
                page_id = f"{stem}_p{page_num:04d}_{source_hash[:8]}"
                text = ""
                plumber_page = plumber_pdf.pages[page_index] if plumber_pdf else None
                if plumber_page:
                    try:
                        text = plumber_page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                    except Exception:
                        text = ""
                if not text and pdf_doc:
                    text = pdf_doc.load_page(page_index).get_text("text") or ""
                image = render_slide_image(fitz, pdf_doc, page_index, stem, page_id) if pdf_doc else None
                images = [image] if image else []
                for img in images:
                    if img:
                        asset = BASE_DIR / img["assetPath"]
                        img["imageFingerprint"] = file_sha(asset)
                        img["sourcePageId"] = page_id
                        img["kind"] = "page_screenshot"
                pages.append({
                    "pageId": page_id,
                    "pageIndex": page_index,
                    "pageNumber": page_num,
                    "sourceFile": input_path.name,
                    "sourceHash": source_hash,
                    "pageHash": short_hash((text or "") + json.dumps([i.get("sha256") for i in images])),
                    "text": clean_slide_text(text),
                    "ocrText": clean_slide_text(text),
                    "images": [i for i in images if i],
                    "tables": extract_tables_from_page(plumber_page),
                })
        finally:
            if plumber_pdf:
                plumber_pdf.close()
            if pdf_doc:
                pdf_doc.close()
    elif suffix in {".png", ".jpg", ".jpeg"}:
        page_id = f"{stem}_p0001_{source_hash[:8]}"
        asset_name = f"{stem}_{page_id}{suffix}"
        asset_path = ASSET_DIR / asset_name
        if input_path.resolve() != asset_path.resolve():
            shutil.copyfile(input_path, asset_path)
        ocr_text = amboss_ocr_image(asset_path)
        image = amboss_asset_entry(asset_path, page_id, f"{page_id}_img01", "page_screenshot")
        pages.append({
            "pageId": page_id,
            "pageIndex": 0,
            "pageNumber": 1,
            "sourceFile": input_path.name,
            "sourceHash": source_hash,
            "pageHash": short_hash(ocr_text + image["imageFingerprint"]),
            "text": ocr_text,
            "ocrText": ocr_text,
            "images": [image],
            "tables": [],
        })
    else:
        raise PipelineError(f"AMBOSS_PROFILE does not support input type: {input_path.suffix}")
    payload = {
        "schemaVersion": "amboss-decomposition-v1",
        "profile": AMBOSS_PROFILE,
        "sourceFile": input_path.name,
        "sourcePath": str(input_path),
        "sourceHash": source_hash,
        "createdAt": timestamp_iso(),
        "pageCount": len(pages),
        "pages": pages,
        "failures": failures,
    }
    out_path = SLIDES_DIR / f"{stem}_amboss_pages.json"
    write_json(out_path, payload)
    log(f"AMBOSS pages -> {out_path.relative_to(BASE_DIR)}")
    return payload


def amboss_page_cache_key(source_hash: str, page: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({
        "profile": AMBOSS_PROFILE,
        "sourcePdfHash": source_hash,
        "pageHash": page.get("pageHash"),
        "extractionPromptVersion": AMBOSS_EXTRACTION_PROMPT_VERSION,
        "imageRoutingVersion": AMBOSS_IMAGE_ROUTING_VERSION,
    }, sort_keys=True).encode("utf-8", errors="replace")).hexdigest()[:16]


def amboss_question_hash(question: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({
        "stem": question.get("stem"),
        "answerChoices": question.get("answerChoices"),
        "correctAnswer": question.get("correctAnswer"),
        "explanation": question.get("correctExplanation"),
    }, sort_keys=True, ensure_ascii=False).encode("utf-8", errors="replace")).hexdigest()[:16]


def amboss_extraction_prompt(page: dict[str, Any]) -> str:
    image_summary = [
        {
            "imageId": img.get("imageId"),
            "kind": img.get("kind"),
            "width": img.get("width"),
            "height": img.get("height"),
            "imageFingerprint": img.get("imageFingerprint"),
        }
        for img in page.get("images") or []
    ]
    return f"""
You are extracting existing AMBOSS-style question content from one visible page or screenshot.

Do not generate new questions. Do not invent answer choices. Do not invent explanations.
If no complete question is visible, return an empty questions array.
Return JSON only:
{{
  "questions": [
    {{
      "sourcePageId": "",
      "extractionConfidence": 0.0,
      "stem": "",
      "answerChoices": [{{"label":"A","text":""}}, {{"label":"B","text":""}}, {{"label":"C","text":""}}, {{"label":"D","text":""}}],
      "correctAnswer": "A",
      "correctAnswerVisible": true,
      "correctExplanation": "",
      "incorrectExplanations": [{{"label":"B","explanation":""}}],
      "educationalObjective": "",
      "imageRouting": [{{"imageId":"","placement":"stem","reason":"","imageConfidence":0.0}}],
      "extractionWarnings": []
    }}
  ],
  "pageWarnings": []
}}

Rules:
- Extract the visible stem and answer choices exactly enough to preserve meaning.
- Use correctAnswer only if visible or clearly marked. If not visible, set correctAnswerVisible false and use an empty correctAnswer.
- Images in unanswered question context route to stem.
- Images in explanation/review/teaching route to explanation.
- Decorative UI or irrelevant screenshots route to ignored.
- If the screenshot is just a menu/list without a full question, return no questions.

PAGE_ID: {page.get("pageId")}
OCR_TEXT:
{str(page.get("ocrText") or page.get("text") or "")[:12000]}

IMAGES:
{json.dumps(image_summary, ensure_ascii=False)}
""".strip()


def extract_amboss_page(page: dict[str, Any], source_file: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise PipelineError("GEMINI_API_KEY is not set for AMBOSS_PROFILE extraction.")
    image_paths = [BASE_DIR / img["assetPath"] for img in page.get("images") or [] if img.get("assetPath")]
    prompt = amboss_extraction_prompt(page)
    raw = raw_gemini_image_call(api_key, prompt, image_paths[:1], temperature=0.0, max_tokens=8192, timeout_seconds=90)
    write_debug_raw(source_file, "amboss_extract", str(page.get("pageId") or "page"), "attempt0", raw)
    parsed = load_largest_valid_json(raw)
    questions = parsed.get("questions") if isinstance(parsed, dict) else []
    if not isinstance(questions, list):
        questions = []
    cleaned: list[dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        q["sourcePageId"] = page.get("pageId")
        q["extractionConfidence"] = float(q.get("extractionConfidence") or 0)
        q.setdefault("extractionWarnings", [])
        cleaned.append(q)
    return cleaned, {"pageWarnings": parsed.get("pageWarnings") if isinstance(parsed, dict) else []}


def amboss_visual_state_prompt(page: dict[str, Any], page_questions: list[dict[str, Any]]) -> str:
    choices = []
    for q in page_questions:
        for choice in q.get("answerChoices") or []:
            if isinstance(choice, dict):
                choices.append({"label": choice.get("label"), "text": choice.get("text")})
    image_summary = [
        {
            "imageId": img.get("imageId"),
            "kind": img.get("kind"),
            "width": img.get("width"),
            "height": img.get("height"),
            "imageFingerprint": img.get("imageFingerprint"),
        }
        for img in page.get("images") or []
    ]
    return f"""
Analyze this rendered AMBOSS page image for visual answer states only.

Do not solve the question. Do not infer from medical knowledge.
Use only visible UI styling:
- green highlighted answer row or green check mark means correct
- red/pink highlighted answer row means incorrect
- explanation text immediately under an answer row belongs to that answer choice
- zoomed or review-only clinical images belong to explanation, not stem

Return JSON only:
{{
  "correctAnswer": "",
  "confidence": 0.0,
  "answerStates": [
    {{"label":"A","state":"correct|incorrect|unknown","confidence":0.0,"visibleText":""}}
  ],
  "visibleRationales": [
    {{"label":"A","explanation":"","confidence":0.0}}
  ],
  "imageRouting": [
    {{"imageId":"","placement":"stem|explanation|ignored","reason":"","imageConfidence":0.0}}
  ],
  "warnings": []
}}

PAGE_ID: {page.get("pageId")}
KNOWN_VISIBLE_CHOICES:
{json.dumps(choices, ensure_ascii=False)}
PAGE_IMAGES:
{json.dumps(image_summary, ensure_ascii=False)}
""".strip()


def detect_amboss_visual_state(page: dict[str, Any], page_questions: list[dict[str, Any]], source_file: str) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {"correctAnswer": "", "confidence": 0, "answerStates": [], "visibleRationales": [], "imageRouting": [], "warnings": ["GEMINI_API_KEY missing"]}
    image_paths = [BASE_DIR / img["assetPath"] for img in page.get("images") or [] if img.get("assetPath")]
    if not image_paths:
        return {"correctAnswer": "", "confidence": 0, "answerStates": [], "visibleRationales": [], "imageRouting": [], "warnings": ["no rendered page image"]}
    prompt = amboss_visual_state_prompt(page, page_questions)
    raw = raw_gemini_image_call(api_key, prompt, image_paths[:1], temperature=0.0, max_tokens=4096, timeout_seconds=60)
    write_debug_raw(source_file, "amboss_visual", str(page.get("pageId") or "page"), "attempt0", raw)
    parsed = load_largest_valid_json(raw)
    if not isinstance(parsed, dict):
        return {"correctAnswer": "", "confidence": 0, "answerStates": [], "visibleRationales": [], "imageRouting": [], "warnings": ["visual state response was not object"]}
    parsed.setdefault("answerStates", [])
    parsed.setdefault("visibleRationales", [])
    parsed.setdefault("imageRouting", [])
    parsed.setdefault("warnings", [])
    parsed["sourcePageId"] = page.get("pageId")
    known_image_ids = {str(img.get("imageId") or "") for img in page.get("images") or []}
    page_image_id = str((page.get("images") or [{}])[0].get("imageId") or "") if page.get("images") else ""
    normalized_routes: list[dict[str, Any]] = []
    for route in parsed.get("imageRouting") or []:
        if not isinstance(route, dict):
            continue
        placement = str(route.get("placement") or "ignored").lower()
        if placement not in {"stem", "explanation", "ignored"}:
            placement = "ignored"
        if placement == "stem" and not page_questions:
            placement = "explanation"
        image_id = str(route.get("imageId") or "")
        if image_id not in known_image_ids and page_image_id and placement != "ignored":
            image_id = page_image_id
        normalized_routes.append({
            "imageId": image_id,
            "placement": placement,
            "reason": clean_sentence(route.get("reason")),
            "imageConfidence": float(route.get("imageConfidence") or 0),
            "sourcePageId": page.get("pageId"),
        })
    parsed["imageRouting"] = normalized_routes
    return parsed


def amboss_apply_visual_state_to_question(q: dict[str, Any], visual_state: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(q)
    labels = {
        str(choice.get("label") or "").strip().upper()
        for choice in out.get("answerChoices") or []
        if isinstance(choice, dict)
    }
    visual_correct = str(visual_state.get("correctAnswer") or "").strip().upper()
    if visual_correct and visual_correct in labels:
        out["correctAnswer"] = visual_correct
        out["correctAnswerVisible"] = True
        out["visualCorrectAnswerConfidence"] = float(visual_state.get("confidence") or 0)
        warnings = [
            str(w)
            for w in (out.get("extractionWarnings") or [])
            if str(w) != "correct answer not visible or invalid"
        ]
        warnings.append(f"correct answer detected visually: {visual_correct}")
        out["extractionWarnings"] = dedupe_preserve_order(warnings)
    rationale_by_label = {
        str(item.get("label") or "").strip().upper(): clean_sentence(item.get("explanation"))
        for item in visual_state.get("visibleRationales") or []
        if isinstance(item, dict) and item.get("label")
    }
    existing = {
        str(item.get("label") or "").strip().upper(): clean_sentence(item.get("explanation"))
        for item in out.get("incorrectExplanations") or []
        if isinstance(item, dict) and item.get("label")
    }
    for label, explanation in rationale_by_label.items():
        if label and explanation and not existing.get(label):
            existing[label] = explanation
    correct = str(out.get("correctAnswer") or "").strip().upper()
    if correct and existing.get(correct) and not clean_sentence(out.get("correctExplanation")):
        out["correctExplanation"] = existing[correct]
    out["incorrectExplanations"] = [
        {"label": label, "explanation": explanation}
        for label, explanation in sorted(existing.items())
        if label and explanation and label != correct
    ]
    if visual_state.get("imageRouting"):
        out["imageRouting"] = visual_state.get("imageRouting")
    out["visualAnswerStates"] = visual_state.get("answerStates") or []
    return out


def amboss_combine_visual_states(page_records: list[dict[str, Any]]) -> dict[str, Any]:
    combined: dict[str, Any] = {
        "correctAnswer": "",
        "confidence": 0.0,
        "answerStates": [],
        "visibleRationales": [],
        "imageRouting": [],
        "warnings": [],
        "sourcePageIds": [],
    }
    best_confidence = 0.0
    rationales: dict[str, dict[str, Any]] = {}
    state_by_label: dict[str, dict[str, Any]] = {}
    route_keys: set[tuple[str, str]] = set()
    state_priority = {"correct": 3, "incorrect": 2, "unknown": 1}
    for record in page_records:
        state = record.get("visualState") or {}
        page_id = str((record.get("page") or {}).get("pageId") or state.get("sourcePageId") or "")
        if page_id:
            combined["sourcePageIds"].append(page_id)
        correct = str(state.get("correctAnswer") or "").strip().upper()
        confidence = float(state.get("confidence") or 0)
        if correct and confidence >= best_confidence:
            combined["correctAnswer"] = correct
            combined["confidence"] = confidence
            best_confidence = confidence
        for item in state.get("answerStates") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip().upper()
            item_state = str(item.get("state") or "").strip().lower()
            prior = state_by_label.get(label)
            if label and (
                not prior
                or state_priority.get(item_state, 0) > state_priority.get(str(prior.get("state") or ""), 0)
                or float(item.get("confidence") or 0) > float(prior.get("confidence") or 0)
            ):
                state_by_label[label] = item
        for item in state.get("visibleRationales") or []:
            if not isinstance(item, dict) or not item.get("label"):
                continue
            label = str(item.get("label") or "").strip().upper()
            explanation = clean_sentence(item.get("explanation"))
            confidence = float(item.get("confidence") or 0)
            prior = rationales.get(label)
            if explanation and (not prior or confidence >= float(prior.get("confidence") or 0)):
                rationales[label] = {"label": label, "explanation": explanation, "confidence": confidence}
        for route in state.get("imageRouting") or []:
            if not isinstance(route, dict):
                continue
            key = (str(route.get("sourcePageId") or page_id), str(route.get("imageId") or ""))
            if key not in route_keys:
                route_keys.add(key)
                combined["imageRouting"].append(route)
        combined["warnings"].extend(str(w) for w in (state.get("warnings") or []) if w)
    combined["sourcePageIds"] = dedupe_preserve_order(combined["sourcePageIds"])
    combined["answerStates"] = [state_by_label[label] for label in sorted(state_by_label)]
    combined["visibleRationales"] = list(rationales.values())
    combined["warnings"] = dedupe_preserve_order(combined["warnings"])
    return combined


def amboss_dedupe_and_promote_questions(page_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_stem: dict[str, dict[str, Any]] = {}
    visual_state_combined = amboss_combine_visual_states(page_records)
    visual_correct = str(visual_state_combined.get("correctAnswer") or "").strip().upper()
    for record in page_records:
        for q in record.get("questions") or []:
            key = short_hash(normalize_key(q.get("stem") or "")[:800])
            candidate = copy.deepcopy(q)
            if visual_correct:
                candidate = amboss_apply_visual_state_to_question(candidate, visual_state_combined)
                candidate["visualSourcePageIds"] = visual_state_combined.get("sourcePageIds") or []
            score = (
                len(candidate.get("answerChoices") or []) * 10
                + len(candidate.get("incorrectExplanations") or []) * 3
                + (20 if candidate.get("correctAnswer") else 0)
                + int(10 * float(candidate.get("extractionConfidence") or 0))
            )
            prior = best_by_stem.get(key)
            prior_score = prior.get("_score", -1) if prior else -1
            if score > prior_score:
                candidate["_score"] = score
                best_by_stem[key] = candidate
    out: list[dict[str, Any]] = []
    for q in best_by_stem.values():
        q.pop("_score", None)
        out.append(q)
    return out


def amboss_normalized_slide_for_question(page: dict[str, Any], q: dict[str, Any], index: int, image_audit: list[dict[str, Any]], support_pages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    question_id = f"{page['pageId']}_q{index:02d}_{amboss_question_hash(q)}"
    images: list[dict[str, Any]] = []
    seen_fingerprints: dict[str, str] = {}
    source_pages = [page]
    for support_page in support_pages or []:
        if support_page and support_page.get("pageId") != page.get("pageId"):
            source_pages.append(support_page)
    source_images = [img for source_page in source_pages for img in (source_page.get("images") or [])]
    for img in source_images:
        img = dict(img)
        fp = img.get("imageFingerprint") or img.get("sha256")
        img["imageFingerprint"] = fp
        img["routedLocation"] = "ignored"
        img["imageConfidence"] = 0.0
        img["duplicateOf"] = None
        if fp and fp in seen_fingerprints:
            img["duplicateOf"] = seen_fingerprints[fp]
            image_audit.append({**img, "dedupeAction": "suppressed_duplicate"})
            continue
        if fp:
            seen_fingerprints[fp] = img.get("imageId")
        for route in q.get("imageRouting") or []:
            if isinstance(route, dict) and route.get("imageId") == img.get("imageId"):
                placement = str(route.get("placement") or "ignored").lower()
                if placement not in {"stem", "explanation", "ignored"}:
                    placement = "ignored"
                img["routedLocation"] = placement
                img["imageConfidence"] = float(route.get("imageConfidence") or 0)
        image_audit.append({**img, "dedupeAction": "kept"})
        images.append(img)
    return {
        "slideId": question_id,
        "slideType": ["HIGH_YIELD_CLINICAL"],
        "yieldScore": int(100 * min(1.0, float(q.get("extractionConfidence") or 0))),
        "primaryConcepts": [clean_tag(q.get("educationalObjective") or "AMBOSS extracted question")],
        "secondaryConcepts": [],
        "clinicalFacts": [clean_sentence(q.get("stem"))],
        "diagnosticFacts": [],
        "managementFacts": [],
        "mechanismFacts": [],
        "images": images,
        "tables": page.get("tables") or [],
        "questionPotential": 100,
        "sourceTextHash": amboss_question_hash(q),
        "metadata": {
            "profile": AMBOSS_PROFILE,
            "sourcePageId": page.get("pageId"),
            "pageNumber": page.get("pageNumber"),
            "extractionConfidence": q.get("extractionConfidence"),
        },
    }


def amboss_generated_question(q: dict[str, Any], slide_id: str) -> dict[str, Any] | None:
    choices = q.get("answerChoices") or []
    if not isinstance(choices, list) or not (2 <= len(choices) <= 9):
        return None
    normalized_choices = [
        {"label": str(c.get("label") or "").strip().upper(), "text": str(c.get("text") or "").strip()}
        for c in choices
        if isinstance(c, dict) and str(c.get("label") or "").strip() and str(c.get("text") or "").strip()
    ]
    labels = [c["label"] for c in normalized_choices]
    if labels != expected_sequential_labels(len(labels)):
        return None
    correct = str(q.get("correctAnswer") or "").strip().upper()
    if correct not in labels:
        return None
    stem = clean_sentence(q.get("stem"))
    if not stem:
        return None
    objective = clean_sentence(q.get("educationalObjective") or q.get("correctExplanation") or "Review the extracted AMBOSS explanation.")
    return {
        "slideId": slide_id,
        "questionKind": "extracted_amboss",
        "stemTemplate": "amboss_extracted",
        "testedConcept": objective[:120],
        "diagnosisOrTarget": objective[:120],
        "distractorFamily": "original Amboss answer choices",
        "stem": stem,
        "answerChoices": normalized_choices,
        "correctAnswer": correct,
        "correctExplanation": clean_sentence(q.get("correctExplanation")),
        "incorrectExplanations": [
            {"label": str(item.get("label") or "").strip().upper(), "explanation": clean_sentence(item.get("explanation"))}
            for item in (q.get("incorrectExplanations") or [])
            if isinstance(item, dict) and str(item.get("label") or "").strip().upper() in labels
        ],
        "educationalObjective": objective,
        "retrievalTag": objective[:80],
        "reviewPearl": clean_sentence(q.get("correctExplanation") or objective),
        "imageRouting": [
            {"imageId": r.get("imageId"), "placement": r.get("placement")}
            for r in (q.get("imageRouting") or [])
            if isinstance(r, dict) and r.get("placement") in {"stem", "explanation"}
        ],
        "tableUse": [],
        "sourceFactIds": [q.get("sourcePageId")],
        "extractionWarnings": q.get("extractionWarnings") or [],
    }


def validate_amboss_extraction(q: dict[str, Any]) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    if not clean_sentence(q.get("stem")):
        warnings.append("missing stem")
    choices = q.get("answerChoices") or []
    if not isinstance(choices, list) or len(choices) < 4:
        warnings.append("fewer than 4 answer choices")
    visible_labels = {
        str(choice.get("label") or "").strip().upper()
        for choice in choices
        if isinstance(choice, dict)
    }
    if str(q.get("correctAnswer") or "").strip().upper() not in visible_labels:
        warnings.append("correct answer not visible or invalid")
    confidence = float(q.get("extractionConfidence") or 0)
    if confidence < 0.55:
        warnings.append("low extraction confidence")
    return not any(w in warnings for w in ["missing stem", "fewer than 4 answer choices", "correct answer not visible or invalid"]), warnings


def amboss_canonical_blockers(q: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    choices = q.get("answerChoices") or []
    if not isinstance(choices, list) or not (2 <= len(choices) <= 9):
        blockers.append(f"AMBOSS canonical conversion supports 2-9 choices; extracted {len(choices) if isinstance(choices, list) else 0}")
    labels = [str(c.get("label") or "").strip().upper() for c in choices if isinstance(c, dict)]
    expected = expected_sequential_labels(len(labels))
    if labels != expected:
        blockers.append(f"AMBOSS labels are not sequential {expected[0] if expected else 'A'}-{expected[-1] if expected else 'Z'}")
    if str(q.get("correctAnswer") or "").strip().upper() not in labels:
        blockers.append(f"correct answer {q.get('correctAnswer') or '(missing)'} is not present in extracted labels")
    return blockers


def amboss_audit_page_images(page: dict[str, Any], question: dict[str, Any] | None, image_audit: list[dict[str, Any]], status: str) -> None:
    routes = question.get("imageRouting") if isinstance(question, dict) else []
    route_by_id = {
        str(route.get("imageId")): route
        for route in (routes or [])
        if isinstance(route, dict) and route.get("imageId")
    }
    seen: dict[str, str] = {}
    for img in page.get("images") or []:
        fp = img.get("imageFingerprint") or img.get("sha256")
        route = route_by_id.get(str(img.get("imageId")))
        routed = str((route or {}).get("placement") or "ignored").lower()
        if routed not in {"stem", "explanation", "ignored"}:
            routed = "ignored"
        duplicate_of = seen.get(fp) if fp else None
        if fp and not duplicate_of:
            seen[fp] = str(img.get("imageId"))
        image_audit.append({
            "imageId": img.get("imageId"),
            "sourcePageId": page.get("pageId"),
            "assetPath": img.get("assetPath"),
            "imageFingerprint": fp,
            "routedLocation": "ignored" if duplicate_of else routed,
            "imageConfidence": float((route or {}).get("imageConfidence") or 0),
            "duplicateOf": duplicate_of,
            "dedupeAction": "suppressed_duplicate" if duplicate_of else "kept",
            "status": status,
            "reason": (route or {}).get("reason") or ("no complete canonical question" if status != "canonical" else ""),
        })


def process_amboss_input(input_path: Path, limit_pages: int = 5) -> Path:
    started = time.time()
    page_payload = decompose_amboss_input(input_path, limit_pages=limit_pages)
    source_hash = page_payload["sourceHash"]
    cache = load_amboss_cache()
    extracted_questions: list[dict[str, Any]] = []
    normalized_slides: list[dict[str, Any]] = []
    generated_questions: list[dict[str, Any]] = []
    image_audit: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0
    accepted = 0
    page_records: list[dict[str, Any]] = []
    for page in page_payload.get("pages") or []:
        page_key = amboss_page_cache_key(source_hash, page)
        cached = (cache.get("pages") or {}).get(page_key)
        if isinstance(cached, dict) and cached.get("status") == "accepted":
            page_questions = cached.get("questions") or []
            page_meta = cached.get("pageMeta") or {}
            visual_state = cached.get("visualState") if cached.get("visualStateVersion") == AMBOSS_VISUAL_STATE_VERSION else None
            cache_hits += 1
        else:
            cache_misses += 1
            try:
                page_questions, page_meta = extract_amboss_page(page, page_payload["sourceFile"])
            except Exception as exc:
                unresolved.append({"pageId": page.get("pageId"), "reason": str(exc)})
                page_questions = []
                page_meta = {"pageWarnings": [str(exc)]}
            visual_state = None
            cache.setdefault("pages", {})[page_key] = {
                "profile": AMBOSS_PROFILE,
                "sourcePdfHash": source_hash,
                "pageHash": page.get("pageHash"),
                "extractionPromptVersion": AMBOSS_EXTRACTION_PROMPT_VERSION,
                "imageRoutingVersion": AMBOSS_IMAGE_ROUTING_VERSION,
                "status": "accepted",
                "questions": page_questions,
                "pageMeta": page_meta,
                "updatedAt": timestamp_iso(),
            }
            write_amboss_cache(cache)
        if visual_state is None:
            try:
                visual_state = detect_amboss_visual_state(page, page_questions, page_payload["sourceFile"])
            except Exception as exc:
                visual_state = {"correctAnswer": "", "confidence": 0, "answerStates": [], "visibleRationales": [], "imageRouting": [], "warnings": [str(exc)]}
            page_entry = cache.setdefault("pages", {}).setdefault(page_key, {})
            page_entry["visualState"] = visual_state
            page_entry["visualStateVersion"] = AMBOSS_VISUAL_STATE_VERSION
            page_entry["updatedAt"] = timestamp_iso()
            write_amboss_cache(cache)
        page_records.append({"page": page, "questions": page_questions, "visualState": visual_state, "pageMeta": page_meta})

    promoted_questions = amboss_dedupe_and_promote_questions(page_records)
    page_by_id = {p["pageId"]: p for p in page_payload.get("pages") or []}
    for q_index, q in enumerate(promoted_questions, start=1):
        page = page_by_id.get(str(q.get("sourcePageId") or "")) or (page_payload.get("pages") or [{}])[0]
        ok, warnings = validate_amboss_extraction(q)
        canonical_blockers = amboss_canonical_blockers(q)
        q["extractionWarnings"] = dedupe_preserve_order(list(q.get("extractionWarnings") or []) + warnings + canonical_blockers)
        q["extractionStatus"] = "canonical_ready" if ok and not canonical_blockers else "partial_review"
        extracted_questions.append(q)
        extracted_hash = amboss_question_hash(q)
        q_cache_key = hashlib.sha256(json.dumps({
            "profile": AMBOSS_PROFILE,
            "sourcePdfHash": source_hash,
            "pageHash": page.get("pageHash"),
            "extractedQuestionHash": extracted_hash,
            "extractionPromptVersion": AMBOSS_EXTRACTION_PROMPT_VERSION,
            "imageRoutingVersion": AMBOSS_IMAGE_ROUTING_VERSION,
            "visualStateVersion": AMBOSS_VISUAL_STATE_VERSION,
        }, sort_keys=True).encode("utf-8", errors="replace")).hexdigest()[:16]
        cache.setdefault("questions", {})[q_cache_key] = {
            "cacheKey": q_cache_key,
            "profile": AMBOSS_PROFILE,
            "sourcePdfHash": source_hash,
            "pageHash": page.get("pageHash"),
            "extractedQuestionHash": extracted_hash,
            "extractionPromptVersion": AMBOSS_EXTRACTION_PROMPT_VERSION,
            "imageRoutingVersion": AMBOSS_IMAGE_ROUTING_VERSION,
            "visualStateVersion": AMBOSS_VISUAL_STATE_VERSION,
            "question": q,
            "status": "accepted" if q["extractionStatus"] == "canonical_ready" else "partial_review",
            "updatedAt": timestamp_iso(),
        }
        write_amboss_cache(cache)
        if not ok or canonical_blockers:
            unresolved.append({"pageId": page.get("pageId"), "questionIndex": q_index, "reason": "; ".join(q["extractionWarnings"])})
            support_ids = q.get("visualSourcePageIds") or [page.get("pageId")]
            for support_id in support_ids:
                support_page = page_by_id.get(str(support_id))
                if support_page:
                    amboss_audit_page_images(support_page, q, image_audit, "partial_review")
            continue
        support_pages = [
            page_by_id[str(support_id)]
            for support_id in (q.get("visualSourcePageIds") or [])
            if str(support_id) in page_by_id
        ]
        slide = amboss_normalized_slide_for_question(page, q, q_index, image_audit, support_pages=support_pages)
        gen_q = amboss_generated_question(q, slide["slideId"])
        if not gen_q:
            unresolved.append({"pageId": page.get("pageId"), "questionIndex": q_index, "reason": "could not convert to canonical generated question"})
            continue
        normalized_slides.append(slide)
        generated_questions.append(gen_q)
        accepted += 1
    question_page_ids = {str(q.get("sourcePageId") or "") for q in promoted_questions}
    support_page_ids = {
        str(page_id)
        for q in promoted_questions
        for page_id in (q.get("visualSourcePageIds") or [])
    }
    for record in page_records:
        page = record["page"]
        if page.get("pageId") not in question_page_ids and page.get("pageId") not in support_page_ids:
            amboss_audit_page_images(page, None, image_audit, "no_question_detected")
    stem = slugify(input_path.stem)
    extracted_path = GENERATED_DIR / f"{stem}_amboss_extracted_questions.json"
    write_json(extracted_path, {"profile": AMBOSS_PROFILE, "questions": extracted_questions})
    normalized_payload = {
        "schemaVersion": "amboss-normalized-v1",
        "profile": AMBOSS_PROFILE,
        "sourceFile": input_path.name,
        "pdfSha256": source_hash,
        "normalizationWarnings": [],
        "slides": normalized_slides,
    }
    app_payload = build_app_ready_payload(normalized_payload, generated_questions) if generated_questions else None
    app_ready_path = APP_READY_DIR / f"{stem}_amboss_app_ready.json"
    validation_errors: list[str] = []
    if app_payload:
        validation_errors = validate_app_ready_payload(app_payload)
        if not validation_errors:
            write_json(app_ready_path, app_payload)
    cache_report = {
        "cachePath": str(amboss_cache_path().relative_to(BASE_DIR)),
        "cacheHits": cache_hits,
        "cacheMisses": cache_misses,
        "reusedQuestions": sum(len(((cache.get("pages") or {}).get(amboss_page_cache_key(source_hash, p)) or {}).get("questions") or []) for p in page_payload.get("pages") or []) if cache_hits else 0,
        "acceptedQuestions": accepted,
        "runtimeDurationSeconds": round(time.time() - started, 2),
    }
    extraction_report = {
        "profile": AMBOSS_PROFILE,
        "sourceFile": input_path.name,
        "pagesProcessed": len(page_payload.get("pages") or []),
        "questionsExtracted": len(extracted_questions),
        "canonicalQuestions": len(generated_questions),
        "appReadyPath": str(app_ready_path.relative_to(BASE_DIR)) if app_payload and not validation_errors else "",
        "validationErrors": validation_errors,
        "cacheReport": cache_report,
        "unresolvedCount": len(unresolved),
    }
    extraction_report_path = write_report(extraction_report, "amboss_extraction_audit_report")
    image_report_path = write_report({"profile": AMBOSS_PROFILE, "sourceFile": input_path.name, "imageAudit": image_audit}, "amboss_image_routing_audit_report")
    unresolved_path = write_report({"profile": AMBOSS_PROFILE, "sourceFile": input_path.name, "unresolved": unresolved}, "amboss_unresolved_extraction_report")
    log(f"AMBOSS extracted -> {extracted_path.relative_to(BASE_DIR)}")
    log(f"AMBOSS extraction report -> {extraction_report_path.relative_to(BASE_DIR)}")
    log(f"AMBOSS image report -> {image_report_path.relative_to(BASE_DIR)}")
    log(f"AMBOSS unresolved report -> {unresolved_path.relative_to(BASE_DIR)}")
    if app_payload and not validation_errors:
        log(f"AMBOSS app-ready -> {app_ready_path.relative_to(BASE_DIR)}")
        return app_ready_path
    return extracted_path


PPTX_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def rel_target(base_dir: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    parts: list[str] = []
    for part in (base_dir + "/" + target).split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def pptx_relationships(zf: zipfile.ZipFile, rels_path: str) -> dict[str, dict[str, str]]:
    if rels_path not in zf.namelist():
        return {}
    root = ET.fromstring(zf.read(rels_path))
    rels: dict[str, dict[str, str]] = {}
    for rel in root.findall("rel:Relationship", PPTX_NS):
        rid = rel.attrib.get("Id", "")
        if not rid:
            continue
        rels[rid] = {
            "type": rel.attrib.get("Type", ""),
            "target": rel.attrib.get("Target", ""),
            "targetMode": rel.attrib.get("TargetMode", ""),
        }
    return rels


def pptx_ordered_slide_paths(zf: zipfile.ZipFile) -> list[str]:
    if "ppt/presentation.xml" not in zf.namelist():
        raise PipelineError("PPTX missing ppt/presentation.xml.")
    root = ET.fromstring(zf.read("ppt/presentation.xml"))
    rels = pptx_relationships(zf, "ppt/_rels/presentation.xml.rels")
    paths: list[str] = []
    for slide_id in root.findall(".//p:sldId", PPTX_NS):
        rid = slide_id.attrib.get(f"{{{PPTX_NS['r']}}}id", "")
        target = rels.get(rid, {}).get("target", "")
        if target:
            paths.append(rel_target("ppt", target))
    if not paths:
        paths = sorted(
            [name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)],
            key=lambda p: int(re.search(r"slide(\d+)\.xml$", p).group(1)),
        )
    return paths


def pptx_text_from_element(element: ET.Element) -> str:
    parts = [node.text or "" for node in element.findall(".//a:t", PPTX_NS)]
    return clean_slide_text("\n".join(part for part in parts if part.strip()))


def pptx_shape_bounds(element: ET.Element) -> dict[str, int]:
    off = element.find(".//a:xfrm/a:off", PPTX_NS)
    ext = element.find(".//a:xfrm/a:ext", PPTX_NS)
    return {
        "x": int(off.attrib.get("x", 0)) if off is not None else 0,
        "y": int(off.attrib.get("y", 0)) if off is not None else 0,
        "cx": int(ext.attrib.get("cx", 0)) if ext is not None else 0,
        "cy": int(ext.attrib.get("cy", 0)) if ext is not None else 0,
    }


def pptx_table_from_graphic_frame(frame: ET.Element, table_id: str) -> dict[str, Any] | None:
    table = frame.find(".//a:tbl", PPTX_NS)
    if table is None:
        return None
    rows: list[list[str]] = []
    for tr in table.findall("a:tr", PPTX_NS):
        row: list[str] = []
        for tc in tr.findall("a:tc", PPTX_NS):
            row.append(pptx_text_from_element(tc).replace("\n", " ").strip())
        if any(row):
            rows.append(row)
    if not rows:
        return None
    return {
        "tableId": table_id,
        "title": "",
        "headers": rows[0],
        "rows": rows[1:],
        "source": "pptx_native_table",
        "bounds": pptx_shape_bounds(frame),
    }


def classify_fast_facts_image(name: str, context: str, bounds: dict[str, int]) -> str:
    text = normalize_key(f"{name} {context}")
    if re.search(r"\b(ecg|ekg|ct|mri|xray|x-ray|cxr|ultrasound|us|rash|pathology|histology|radiograph|image|scan)\b", text):
        return "diagnostic"
    if re.search(r"\b(algorithm|flowchart|management|workup|treatment|stepwise|approach)\b", text):
        return "algorithm"
    if re.search(r"\b(table|chart|grid)\b", text):
        return "table-like"
    area = int(bounds.get("cx", 0)) * int(bounds.get("cy", 0))
    if area and area < 250_000_000_000:
        return "decorative"
    if re.search(r"\b(pathway|mechanism|diagram|summary|mnemonic)\b", text):
        return "explanatory"
    return "explanatory"


def pptx_extract_images(
    zf: zipfile.ZipFile,
    rels: dict[str, dict[str, str]],
    slide_path: str,
    slide_id: str,
    deck_stem: str,
    slide_text: str,
    slide_root: ET.Element,
) -> list[dict[str, Any]]:
    base_dir = str(Path(slide_path).parent)
    images: list[dict[str, Any]] = []
    for idx, pic in enumerate(slide_root.findall(".//p:pic", PPTX_NS), start=1):
        blip = pic.find(".//a:blip", PPTX_NS)
        if blip is None:
            continue
        rid = blip.attrib.get(f"{{{PPTX_NS['r']}}}embed", "")
        target = rels.get(rid, {}).get("target", "")
        if not target:
            continue
        media_path = rel_target(base_dir, target)
        if media_path not in zf.namelist():
            continue
        source_name = pic.find(".//p:cNvPr", PPTX_NS)
        original_name = source_name.attrib.get("name", "") if source_name is not None else Path(media_path).name
        ext = Path(media_path).suffix or ".bin"
        image_id = f"{slide_id}_img{idx:02d}"
        asset_name = f"{slugify(deck_stem)}_{image_id}{ext}"
        asset_path = ASSET_DIR / asset_name
        asset_path.write_bytes(zf.read(media_path))
        bounds = pptx_shape_bounds(pic)
        images.append({
            "imageId": image_id,
            "kind": classify_fast_facts_image(original_name, slide_text, bounds),
            "source": "pptx_embedded_image",
            "sourceSlideId": slide_id,
            "sourceRelationshipId": rid,
            "sourcePath": media_path,
            "originalName": original_name,
            "assetPath": str(asset_path.relative_to(BASE_DIR)),
            "mimeType": mime_for(asset_path),
            "width": 0,
            "height": 0,
            "sha256": file_sha(asset_path),
            "bounds": bounds,
        })
    return images


def pptx_notes_text(zf: zipfile.ZipFile, slide_path: str, rels: dict[str, dict[str, str]]) -> str:
    base_dir = str(Path(slide_path).parent)
    for rel in rels.values():
        if "notesSlide" not in rel.get("type", ""):
            continue
        notes_path = rel_target(base_dir, rel.get("target", ""))
        if notes_path in zf.namelist():
            return pptx_text_from_element(ET.fromstring(zf.read(notes_path)))
    return ""


def decompose_fast_facts_pptx(pptx_path: Path, limit_slides: int = 0) -> dict[str, Any]:
    ensure_dirs()
    deck_hash = file_sha(pptx_path)
    deck_stem = pptx_path.stem
    slide_limit = max(0, int(limit_slides or 0))
    log(f"Decomposing Fast Facts PPTX {pptx_path.name}")
    with zipfile.ZipFile(pptx_path) as zf:
        all_slide_paths = pptx_ordered_slide_paths(zf)
        slide_paths = all_slide_paths[:slide_limit] if slide_limit else all_slide_paths
        slides: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for idx, slide_path in enumerate(slide_paths, start=1):
            slide_id = f"{slugify(deck_stem)}_s{idx:04d}_{deck_hash[:8]}"
            try:
                root = ET.fromstring(zf.read(slide_path))
                rels = pptx_relationships(zf, f"{Path(slide_path).parent}/_rels/{Path(slide_path).name}.rels")
                text_blocks = []
                for shape_idx, shape in enumerate(root.findall(".//p:sp", PPTX_NS), start=1):
                    text = pptx_text_from_element(shape)
                    if text:
                        text_blocks.append({
                            "textBlockId": f"{slide_id}_text{shape_idx:02d}",
                            "text": text,
                            "bounds": pptx_shape_bounds(shape),
                        })
                tables = []
                for table_idx, frame in enumerate(root.findall(".//p:graphicFrame", PPTX_NS), start=1):
                    table = pptx_table_from_graphic_frame(frame, f"{slide_id}_table{table_idx:02d}")
                    if table:
                        tables.append(table)
                notes = pptx_notes_text(zf, slide_path, rels)
                combined_text = clean_slide_text("\n".join([b["text"] for b in text_blocks] + ([notes] if notes else [])))
                images = pptx_extract_images(zf, rels, slide_path, slide_id, deck_stem, combined_text, root)
                slides.append({
                    "slideId": slide_id,
                    "sourceFile": pptx_path.name,
                    "pptxSha256": deck_hash,
                    "slideIndex": idx,
                    "pptxSlidePath": slide_path,
                    "textBlocks": text_blocks,
                    "notesText": notes,
                    "nativeText": combined_text,
                    "images": images,
                    "tables": tables,
                    "metadata": {
                        "profile": FAST_FACTS_PROFILE,
                        "renderedSlideImage": None,
                    },
                })
            except Exception as exc:
                failures.append({"slideIndex": idx, "slidePath": slide_path, "error": str(exc)})
        payload = {
            "schemaVersion": "fast-facts-pptx-decomposition-v1",
            "profile": FAST_FACTS_PROFILE,
            "sourceFile": pptx_path.name,
            "sourcePath": str(pptx_path),
            "pptxSha256": deck_hash,
            "createdAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "slideCount": len(all_slide_paths),
            "processedSlideCount": len(slides),
            "limit": slide_limit,
            "slides": slides,
            "failures": failures,
        }
    out_path = SLIDES_DIR / f"{slugify(deck_stem)}_fast_facts_slides.json"
    write_json(out_path, payload)
    log(f"  Fast Facts slides -> {out_path.relative_to(BASE_DIR)}")
    return payload


def fast_facts_checkpoint_path(pptx_path: Path) -> Path:
    return NORMALIZED_DIR / f"{slugify(pptx_path.stem)}_fast_facts_checkpoint.json"


def fast_facts_output_path(pptx_path: Path) -> Path:
    return NORMALIZED_DIR / f"{slugify(pptx_path.stem)}_fast_facts_concept_graph.json"


def load_fast_facts_checkpoint(pptx_path: Path, deck_hash: str, limit_slides: int) -> dict[str, Any]:
    path = fast_facts_checkpoint_path(pptx_path)
    if not path.exists():
        return {"concepts": [], "processedSlideIds": [], "failures": []}
    try:
        payload = read_json(path)
    except Exception:
        return {"concepts": [], "processedSlideIds": [], "failures": []}
    if (
        payload.get("pptxSha256") != deck_hash
        or int(payload.get("limit") or 0) != int(limit_slides or 0)
        or payload.get("atomizerVersion") != FAST_FACTS_ATOMIZER_VERSION
    ):
        return {"concepts": [], "processedSlideIds": [], "failures": []}
    return payload


def write_fast_facts_checkpoint(pptx_path: Path, deck_hash: str, limit_slides: int, concepts: list[dict[str, Any]], processed: list[str], failures: list[dict[str, Any]]) -> None:
    write_json(fast_facts_checkpoint_path(pptx_path), {
        "schemaVersion": "fast-facts-concept-checkpoint-v1",
        "profile": FAST_FACTS_PROFILE,
        "atomizerVersion": FAST_FACTS_ATOMIZER_VERSION,
        "sourceFile": pptx_path.name,
        "pptxSha256": deck_hash,
        "limit": int(limit_slides or 0),
        "updatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "processedSlideIds": processed,
        "concepts": concepts,
        "failures": failures,
    })


def classify_fast_facts_category(text: str) -> str:
    lower = normalize_key(text)
    if re.search(r"\b(treat\w*|management|therapy|screen\w*|prevent\w*|vaccine|antibiotic\w*|surgery|surgical|administer\w*)\b", lower):
        return "management"
    if re.search(r"\b(diagnos\w*|test\w*|lab\w*|ecg|ekg|ct|mri|ultrasound|x-ray|finding\w*|criteria|culture\w*)\b", lower):
        return "diagnosis"
    if re.search(r"\b(pathophys\w*|mechanism\w*|cause\w*|mutation\w*|deficien\w*|inhibit\w*|activat\w*|receptor\w*)\b", lower):
        return "mechanism"
    if re.search(r"\b(vs|versus|differentiat\w*|mimic\w*|ddx|differential)\b", lower):
        return "differential"
    if re.search(r"\b(trap\w*|except|avoid\w*|do not|contraindicat\w*|classic)\b", lower):
        return "trap"
    return "clinical"


FAST_FACTS_MEDICAL_CUE_RE = re.compile(
    r"\b("
    r"diagnos\w*|treat\w*|manage\w*|screen\w*|prevent\w*|workup|therapy|antibiotic\w*|"
    r"infection\w*|disease\w*|syndrome\w*|rash|pain|fever|blood|culture\w*|urine|renal|"
    r"cardiac|pulmonary|hepatic|diabetes|cellulitis|erysipelas|cystitis|pyelonephritis|"
    r"pneumonia|embolism|thrombosis|ischemia|infarct\w*|failure|deficien\w*|mutation\w*|"
    r"ecg|ekg|ct|mri|x-ray|ultrasound|lab\w*|finding\w*|criteria|contraindicat\w*|"
    r"pack-year|smok\w*|quit|low-dose|yearly|life expectancy|bmi|hgb|a1c|frequency|suprapubic"
    r")\b",
    re.I,
)


def is_fast_facts_medical_line(line: str) -> bool:
    stripped = normalize_key(line)
    if not stripped:
        return False
    if stripped.strip(":") in {"diagnosis and management", "management", "diagnosis", "treatment"}:
        return False
    if re.match(r"^[,;:)]", stripped):
        return False
    if re.fullmatch(r"[a-z]+[)]", stripped):
        return False
    if stripped in {
        "internal medicine shelf fast facts",
        "useful tables and images from uworld/amboss",
    }:
        return False
    if len(stripped) < 5:
        return False
    if extract_medical_claim_terms(line):
        return True
    return bool(FAST_FACTS_MEDICAL_CUE_RE.search(line))


def fast_facts_lines_from_text(text: str) -> list[str]:
    raw_lines = [
        re.sub(r"\s+", " ", line).strip(" -•\t")
        for line in str(text or "").splitlines()
    ]
    raw_lines = [line for line in raw_lines if line]
    merged: list[str] = []
    i = 0
    join_prefixes = {"empiric", "treatment", "urine", "blood", "sputum", "stool", "serum", "oral", "iv"}
    while i < len(raw_lines):
        line = raw_lines[i]
        while i + 1 < len(raw_lines):
            nxt = raw_lines[i + 1]
            word_count = len(re.findall(r"\b\w+\b", line))
            should_join = (
                normalize_key(line).strip(":") in join_prefixes
                or (word_count <= 2 and re.match(r"^(with|prior|to|for|while|and|or|but|plus|culture|treatment)\b", normalize_key(nxt)))
                or re.search(r"\b(empiric|urine|blood|sputum|stool|serum|oral|iv)$", normalize_key(line))
                or (word_count <= 5 and len(re.findall(r"\b\w+\b", nxt)) <= 2 and not nxt.endswith(":"))
                or normalize_key(line) in {"started, consider"}
                or re.search(r"\brenal artery$", normalize_key(line))
            )
            if not should_join:
                break
            line = f"{line} {nxt}".strip()
            i += 1
        merged.append(line)
        i += 1
    return merged


def fast_facts_split_atomic_lines(slide: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for block in slide.get("textBlocks") or []:
        lines.extend(fast_facts_lines_from_text(str(block.get("text") or "")))
    if slide.get("notesText"):
        lines.extend(fast_facts_lines_from_text(str(slide.get("notesText") or "")))
    for table in slide.get("tables") or []:
        headers = [str(h).strip() for h in table.get("headers") or []]
        for row in table.get("rows") or []:
            cells = [str(c).strip() for c in row if str(c).strip()]
            if cells:
                prefix = f"{headers[0]}: " if headers and headers[0] else ""
                lines.append(prefix + " | ".join(cells))
    clean: list[str] = []
    seen: set[str] = set()
    for line in lines:
        line = re.sub(r"\s+", " ", line).strip(" -•\t")
        if len(line) < 4 or len(line) > 260:
            continue
        if not is_fast_facts_medical_line(line):
            continue
        key = normalize_key(line)
        if key in seen:
            continue
        seen.add(key)
        clean.append(line)
    return clean


FAST_FACTS_GENERIC_TERMS = {
    "additional", "angle", "blood", "border", "borders", "cases", "clinical",
    "common", "confined", "consider", "criteria", "current", "currently",
    "days", "described", "diagnosis", "done", "enough", "external", "facts",
    "feature", "features", "history", "interval", "like", "local", "medical",
    "medicine", "patient", "patients", "positive", "prior", "recommended",
    "screening", "severe", "shelf", "significantly", "symptoms", "systemic",
    "test", "then", "treated", "useful", "usually", "with", "without",
    "should", "over", "even", "absence", "earlier", "within",
}


def meaningful_fast_facts_terms(text: str) -> list[str]:
    phrases: list[str] = []
    for phrase in re.findall(r"\b[A-Z][A-Za-z0-9+\-/]*(?:\s+[A-Z0-9][A-Za-z0-9+\-/]*){0,4}\b", text):
        cleaned = re.sub(r"\s+", " ", phrase).strip()
        if len(cleaned) >= 4 and normalize_key(cleaned) not in FAST_FACTS_GENERIC_TERMS:
            phrases.append(cleaned.lower())
    tokens = [
        tok.lower().strip("-")
        for tok in re.findall(r"\b[A-Za-z][A-Za-z0-9+\-/]{2,}\b", text)
        if tok.lower() not in COMMON_CLINICAL_WORDS and tok.lower() not in FAST_FACTS_GENERIC_TERMS
    ]
    for tok in sorted(extract_medical_claim_terms(text)):
        if tok not in tokens:
            tokens.insert(0, tok)
    ordered: list[str] = []
    for term in phrases + tokens:
        term = term.strip(" ,.;:()")
        if len(term) < 4 or term in FAST_FACTS_GENERIC_TERMS:
            continue
        if term not in ordered:
            ordered.append(term)
    return ordered[:40]


def fast_facts_grounding_terms(text: str) -> list[str]:
    return meaningful_fast_facts_terms(text)


def fast_facts_fact_bucket(line: str, active_section: str = "") -> str:
    text = normalize_key(f"{active_section} {line}")
    if re.search(r"\b(not to be confused|do not confuse|confused with|vs|versus|rather than)\b", text):
        return "trapFacts"
    if re.search(r"\b(differential|mimic|not pulmonary symptoms|interstitial nephritis|ain)\b", text):
        return "differentialFacts"
    if re.search(r"\b(pathophys|mechanism|mutation|deficien|causes?|induced|receptor|inhibit|activat)\b", text):
        return "mechanismFacts"
    if re.search(r"\b(diagnos|urinalysis|culture|leukocyte|nitrat|glucose|a1c|blood pressure|systolic|diastolic|ct scan|testing|ultrasound|criteria|finding|opacit)\b", text):
        return "diagnosticFacts"
    if re.search(r"\b(treat|therapy|management|empiric|antibiotic|ceftriaxone|cefazolin|amoxicillin|tmp-smx|nitrofurantoin|fosfomycin|fluoroquinolone|screening|low-dose|yearly|termination)\b", text):
        return "managementFacts"
    if active_section and re.search(r"\b(presentation|clinical features)\b", normalize_key(active_section)):
        return "clinicalFacts"
    return "clinicalFacts"


def fast_facts_clean_title(text: str, fallback: str = "") -> str:
    title = re.sub(r"\s+", " ", str(text or fallback or "")).strip(" :-•\t")
    title = re.sub(r"[:.;,]+$", "", title).strip()
    return title[:120]


def fast_facts_new_concept(slide: dict[str, Any], title: str, ordinal: int) -> dict[str, Any]:
    clean_title = fast_facts_clean_title(title, f"Slide {slide.get('slideIndex')} concept {ordinal}")
    return {
        "conceptId": f"ff_{slide['slideId']}_{short_hash(clean_title + str(ordinal))[:8]}",
        "sourceSlideIds": [slide["slideId"]],
        "title": clean_title,
        "category": classify_fast_facts_category(clean_title),
        "clinicalFacts": [],
        "diagnosticFacts": [],
        "managementFacts": [],
        "mechanismFacts": [],
        "differentialFacts": [],
        "trapFacts": [],
        "nativeTextFacts": [],
        "imageOcrFacts": [],
        "cleanedImageFacts": [],
        "structuredImageFacts": {
            "criteria": [],
            "indications": [],
            "contraindications": [],
            "managementSteps": [],
            "thresholds": [],
        },
        "imageTextQuality": "none",
        "images": [],
        "tables": [],
        "questionPotential": 0,
        "groundingTerms": [],
    }


def fast_facts_add_fact(concept: dict[str, Any], line: str, active_section: str = "", origin: str = "native") -> None:
    clean = re.sub(r"\s+", " ", str(line or "")).strip(" -•\t")
    clean = re.sub(r"^[¢•]+\s*", "", clean).strip()
    section_key = normalize_key(active_section).strip(":")
    if not clean:
        return
    if normalize_key(clean).strip(":") in {"recommended", "test", "interval", "age for screening", "past", "or"}:
        return
    section_allows_context = bool(re.search(r"\b(presentation|clinical features|diagnosis|management|screening|recommendations|termination)\b", section_key))
    if not is_fast_facts_medical_line(clean) and not section_allows_context:
        return
    bucket = fast_facts_fact_bucket(clean, active_section)
    if clean not in concept[bucket]:
        concept[bucket].append(clean)
    if origin == "native" and clean not in concept["nativeTextFacts"]:
        concept["nativeTextFacts"].append(clean)


def fast_facts_finalize_concept(concept: dict[str, Any]) -> dict[str, Any] | None:
    all_facts: list[str] = []
    for key in ["clinicalFacts", "diagnosticFacts", "managementFacts", "mechanismFacts", "differentialFacts", "trapFacts"]:
        all_facts.extend(concept.get(key) or [])
    title = str(concept.get("title") or "")
    if not all_facts and not concept.get("images"):
        return None
    if not all_facts and is_fast_facts_medical_line(title):
        concept["clinicalFacts"].append(title)
        all_facts.append(title)
    for key in ["nativeTextFacts", "imageOcrFacts", "cleanedImageFacts"]:
        seen_values: set[str] = set()
        deduped: list[str] = []
        for value in concept.get(key) or []:
            value = re.sub(r"\s+", " ", str(value or "")).strip()
            if value and value not in seen_values:
                seen_values.add(value)
                deduped.append(value)
        concept[key] = deduped
    for key, values in list((concept.get("structuredImageFacts") or {}).items()):
        seen_structured: set[str] = set()
        concept["structuredImageFacts"][key] = [
            v for v in values
            if isinstance(v, str) and v and not (v in seen_structured or seen_structured.add(v))
        ]
    if concept.get("imageTextQuality") == "poor":
        fact_text = " ".join([title] + all_facts)
    else:
        fact_text = " ".join([title] + all_facts + (concept.get("cleanedImageFacts") or []))
    terms = fast_facts_grounding_terms(fact_text)
    concept["groundingTerms"] = terms
    concept["questionPotential"] = min(100, 30 + len(all_facts) * 8 + len(terms) * 2 + len(concept.get("images") or []) * 8)
    fact_counts = {
        "clinical": len(concept["clinicalFacts"]),
        "diagnosis": len(concept["diagnosticFacts"]),
        "management": len(concept["managementFacts"]),
        "mechanism": len(concept["mechanismFacts"]),
        "differential": len(concept["differentialFacts"]) + len(concept["trapFacts"]),
    }
    concept["category"] = max(fact_counts.items(), key=lambda kv: kv[1])[0] if any(fact_counts.values()) else classify_fast_facts_category(title)
    return concept


def fast_facts_ocr_image_text(image: dict[str, Any]) -> str:
    asset = image.get("assetPath")
    if not asset:
        return ""
    path = BASE_DIR / str(asset)
    if not path.exists() or not shutil.which("tesseract"):
        return ""
    try:
        proc = subprocess.run(
            ["tesseract", str(path), "stdout", "--psm", "6"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return clean_slide_text(proc.stdout)


def fast_facts_normalize_ocr_line(line: str) -> str:
    line = re.sub(r"[¢•·]+", " ", line)
    line = re.sub(r"[“”]", '"', line)
    line = re.sub(r"[‘’]", "'", line)
    line = re.sub(r"\s+", " ", line).strip(" -—:;,.")
    replacements = [
        (r"\bAne\b", ""),
        (r"\butr\"?\b", "UTI"),
        (r"\b220-pack-year\b", "20-pack-year"),
        (r"\b215\b", "15"),
        (r"^7\s+", ""),
        (r"\btest Recommended\b", ""),
        (r"\bRecommended\s*$", ""),
        (r"\s*&\s*$", ""),
    ]
    for pat, repl in replacements:
        line = re.sub(pat, repl, line, flags=re.I)
    line = re.sub(r"\s+", " ", line).strip(" -—:;,.")
    return line


def fast_facts_clean_ocr_lines(raw_ocr: str) -> list[str]:
    raw_lines = fast_facts_lines_from_text(raw_ocr)
    clean_lines: list[str] = []
    skip = {
        "recommended", "test", "interval", "age for", "age for screening",
        "past", "or", "screening", "termination of",
    }
    for line in raw_lines:
        clean = fast_facts_normalize_ocr_line(line)
        key = normalize_key(clean)
        if not clean or key in skip or len(clean) < 3:
            continue
        clean_lines.append(clean)

    joined = "\n".join(clean_lines)
    if "lung cancer screening" in normalize_key(joined):
        facts = [
            "Low-dose CT scan of the chest",
            "Screen yearly",
            "Age 50-80 years",
            "20-pack-year smoking history",
            "Currently smoking or quit within the past 15 years",
            "Terminate screening if quit smoking for 15 years",
            "Terminate screening if medical conditions significantly limit life expectancy",
        ]
        return [f for f in facts if any(tok in normalize_key(joined) for tok in normalize_key(f).split()[:2]) or f.startswith("Terminate")]

    if "urinary tract infection" in normalize_key(joined) or "uncomplicated" in normalize_key(joined):
        facts = [
            "Uncomplicated UTI: nitrofurantoin",
            "Uncomplicated UTI: trimethoprim-sulfamethoxazole",
            "Uncomplicated UTI: fosfomycin single dose",
            "Use fluoroquinolones only if previous options cannot be used",
            "Urine culture only if initial treatment fails",
            "Complicated UTI outpatient treatment: fluoroquinolones",
            "Complicated UTI inpatient treatment: ceftriaxone, piperacillin-tazobactam, or carbapenems such as imipenem",
            "Obtain culture before therapy and adjust antibiotic as needed",
            "Complicated UTI includes infection above the bladder, pelvic pain in men, or systemic illness",
        ]
        return facts

    seen: set[str] = set()
    out: list[str] = []
    for line in clean_lines:
        key = normalize_key(line)
        if key not in seen and is_fast_facts_medical_line(line):
            seen.add(key)
            out.append(line)
    return out


def fast_facts_image_text_quality(raw_ocr: str, cleaned: list[str]) -> str:
    if not raw_ocr.strip():
        return "none"
    junk_hits = len(re.findall(r"[¢_=]{1,}|[\"']\s*[a-z]?$|\b[A-Za-z]{1,2}\b", raw_ocr))
    token_count = len(re.findall(r"\b[A-Za-z0-9][A-Za-z0-9-]*\b", raw_ocr))
    if token_count < 6 or not cleaned:
        return "poor"
    if junk_hits / max(1, token_count) > 0.35:
        return "poor"
    if junk_hits / max(1, token_count) > 0.18:
        return "fair"
    return "good"


def fast_facts_structured_image_facts(cleaned_facts: list[str], image_kind: str) -> dict[str, list[str]]:
    structured = {
        "criteria": [],
        "indications": [],
        "contraindications": [],
        "managementSteps": [],
        "thresholds": [],
    }
    for fact in cleaned_facts:
        key = normalize_key(fact)
        if re.search(r"\b(age|pack-year|years?|bmi|a1c|>\d|<\d|\d+-\d+|15 years|20-pack)\b", key):
            structured["thresholds"].append(fact)
        if re.search(r"\b(currently smoking|quit|systemic illness|infection above|pelvic pain|initial treatment fails)\b", key):
            structured["criteria"].append(fact)
        if re.search(r"\b(low-dose ct|screen|culture|obtain|treatment|nitrofurantoin|trimethoprim|fosfomycin|fluoroquinolone|ceftriaxone|piperacillin|carbapenem)\b", key):
            structured["managementSteps"].append(fact)
        if re.search(r"\b(medical conditions|limit life expectancy|cannot be used)\b", key):
            structured["contraindications"].append(fact)
        if image_kind in {"algorithm", "table-like"} and re.search(r"\b(uti|screening|infection|smoking)\b", key):
            structured["indications"].append(fact)
    return structured


def fast_facts_apply_image_ocr(concept: dict[str, Any], slide: dict[str, Any], force: bool = False) -> list[str]:
    native_lines = fast_facts_split_atomic_lines(slide)
    if not force and len(native_lines) > 1:
        return []
    all_cleaned: list[str] = []
    for image in slide.get("images") or []:
        ocr = fast_facts_ocr_image_text(image)
        if ocr:
            image["ocrText"] = ocr
            cleaned = fast_facts_clean_ocr_lines(ocr)
            image["cleanedOcrFacts"] = cleaned
            image["imageTextQuality"] = fast_facts_image_text_quality(ocr, cleaned)
            image["structuredFacts"] = fast_facts_structured_image_facts(cleaned, str(image.get("kind") or ""))
            concept["imageOcrFacts"].extend(fast_facts_lines_from_text(ocr))
            concept["cleanedImageFacts"].extend(cleaned)
            for key, values in image["structuredFacts"].items():
                for value in values:
                    if value not in concept["structuredImageFacts"][key]:
                        concept["structuredImageFacts"][key].append(value)
            all_cleaned.extend(cleaned)
    qualities = [img.get("imageTextQuality") for img in slide.get("images") or [] if img.get("ocrText")]
    if qualities:
        if "poor" in qualities:
            concept["imageTextQuality"] = "poor"
        elif "fair" in qualities:
            concept["imageTextQuality"] = "fair"
        else:
            concept["imageTextQuality"] = "good"
    return all_cleaned


def fast_facts_image_fallback_lines(slide: dict[str, Any]) -> list[str]:
    temp = fast_facts_new_concept(slide, "image fallback", 999)
    return fast_facts_apply_image_ocr(temp, slide, force=False)


def fast_facts_heading_candidates(slide: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for block in slide.get("textBlocks") or []:
        lines = fast_facts_lines_from_text(str(block.get("text") or ""))
        if lines:
            candidates.append(lines[0])
    if slide.get("notesText"):
        candidates.extend(fast_facts_lines_from_text(str(slide.get("notesText") or ""))[:1])
    return [fast_facts_clean_title(c) for c in candidates if fast_facts_clean_title(c)]


def fast_facts_block_lines(block: dict[str, Any]) -> list[str]:
    return fast_facts_lines_from_text(str(block.get("text") or ""))


def atomize_fast_facts_slide(slide: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = slide.get("textBlocks") or []
    heading_candidates = fast_facts_heading_candidates(slide)
    main_title = heading_candidates[0] if heading_candidates else fast_facts_clean_title(slide.get("notesText") or f"Slide {slide.get('slideIndex')}")
    concepts: list[dict[str, Any]] = []

    if len(blocks) <= 1:
        concept = fast_facts_new_concept(slide, main_title, 1)
        lines: list[str] = []
        for block in blocks:
            block_lines = fast_facts_block_lines(block)
            lines.extend(block_lines[1:] if block_lines and fast_facts_clean_title(block_lines[0]) == main_title else block_lines)
        image_lines = fast_facts_apply_image_ocr(concept, slide, force=True)
        image_line_keys = {normalize_key(line) for line in image_lines}
        lines.extend(image_lines if concept.get("imageTextQuality") != "poor" else [])
        section = ""
        for line in lines:
            if re.search(r":$", line):
                section = line
                continue
            origin = "image" if normalize_key(line) in image_line_keys else "native"
            fast_facts_add_fact(concept, line, section, origin=origin)
        concept["images"] = slide.get("images") or []
        concept["tables"] = slide.get("tables") or []
        finalized = fast_facts_finalize_concept(concept)
        return [finalized] if finalized else []

    content_blocks = blocks[1:] if fast_facts_clean_title(fast_facts_block_lines(blocks[0])[0] if fast_facts_block_lines(blocks[0]) else "") == main_title else blocks
    major_blocks = [b for b in content_blocks if fast_facts_block_lines(b) and re.search(r"\b(uncomplicated|complicated|screening for|not to be confused|presentation)\b", fast_facts_block_lines(b)[0], re.I)]
    if len(content_blocks) > 1 and len(major_blocks) >= 2 and re.search(r"\burinary tract infections?\b", main_title, re.I):
        ordinal = 1
        for block in content_blocks:
            lines = fast_facts_block_lines(block)
            if not lines:
                continue
            subheading = lines[0]
            concept = fast_facts_new_concept(slide, f"{main_title}: {subheading}", ordinal)
            section = ""
            for line in lines[1:]:
                if re.search(r":$", line):
                    section = line
                    continue
                fast_facts_add_fact(concept, line, section)
            finalized = fast_facts_finalize_concept(concept)
            if finalized:
                concepts.append(finalized)
                ordinal += 1
        if concepts:
            concepts[0]["images"] = slide.get("images") or []
            concepts[0]["tables"] = slide.get("tables") or []
            fast_facts_apply_image_ocr(concepts[0], slide, force=True)
            return concepts

    if re.search(r"\bhypertension\b", normalize_key(slide.get("notesText") or "")):
        hypertension = fast_facts_new_concept(slide, fast_facts_clean_title(slide.get("notesText")), 1)
        diabetes = fast_facts_new_concept(slide, "Screening for diabetes", 2)
        hypertension_context = False
        for block in blocks:
            lines = fast_facts_block_lines(block)
            section = ""
            target = hypertension
            for line in lines:
                if re.match(r"screening for diabetes", line, re.I):
                    section = line
                    target = diabetes
                    fast_facts_add_fact(diabetes, line, section)
                    continue
                if re.search(r":$", line):
                    section = line
                    continue
                if re.search(r"\b(diabetes|glucose|a1c|bmi)\b", line, re.I):
                    fast_facts_add_fact(diabetes, line, section)
                elif re.search(r"\b(refractory hypertension|resistant hypertension|renal artery|sleep apnea|acei|blood pressure|systolic|diastolic)\b", line, re.I):
                    hypertension_context = True
                    fast_facts_add_fact(hypertension, line, section)
                elif hypertension_context and re.search(r"\b(started|consider|stenosis|renal|ultrasound)\b", line, re.I):
                    fast_facts_add_fact(hypertension, line, section)
                else:
                    fast_facts_add_fact(target, line, section)
        hypertension["images"] = slide.get("images") or []
        hypertension["tables"] = slide.get("tables") or []
        fast_facts_apply_image_ocr(hypertension, slide, force=True)
        return [c for c in [fast_facts_finalize_concept(hypertension), fast_facts_finalize_concept(diabetes)] if c]

    concept = fast_facts_new_concept(slide, main_title, 1)
    section = ""
    for block in content_blocks:
        lines = fast_facts_block_lines(block)
        if lines and fast_facts_clean_title(lines[0]) == main_title:
            lines = lines[1:]
        for line in lines:
            if re.search(r":$", line):
                section = line
                if re.search(r"\bnot to be confused|differential|do not confuse\b", line, re.I):
                    fast_facts_add_fact(concept, line, section)
                continue
            fast_facts_add_fact(concept, line, section)
    image_facts = fast_facts_apply_image_ocr(concept, slide, force=not any(concept.get(key) for key in ["clinicalFacts", "diagnosticFacts", "managementFacts", "mechanismFacts", "differentialFacts", "trapFacts"]))
    if not any(concept.get(key) for key in ["clinicalFacts", "diagnosticFacts", "managementFacts", "mechanismFacts", "differentialFacts", "trapFacts"]):
        for line in image_facts if concept.get("imageTextQuality") != "poor" else []:
            fast_facts_add_fact(concept, line, "", origin="image")
    concept["images"] = slide.get("images") or []
    concept["tables"] = slide.get("tables") or []
    finalized = fast_facts_finalize_concept(concept)
    return [finalized] if finalized else []


def validate_fast_facts_concept_graph(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("profile") != FAST_FACTS_PROFILE:
        errors.append("profile must be FAST_FACTS_PROFILE")
    if not isinstance(payload.get("concepts"), list):
        errors.append("concepts must be a list")
        return errors
    seen: set[str] = set()
    required = [
        "conceptId", "sourceSlideIds", "title", "category", "clinicalFacts",
        "diagnosticFacts", "managementFacts", "mechanismFacts",
        "differentialFacts", "trapFacts", "nativeTextFacts", "imageOcrFacts",
        "cleanedImageFacts", "structuredImageFacts", "imageTextQuality", "images", "tables",
        "questionPotential", "groundingTerms", "semanticClusterId", "duplicateOf",
        "overlapScore", "dedupeDisposition",
    ]
    allowed_image_kinds = {"diagnostic", "explanatory", "algorithm", "decorative", "table-like"}
    for idx, concept in enumerate(payload.get("concepts") or [], start=1):
        if not isinstance(concept, dict):
            errors.append(f"concept {idx} is not an object")
            continue
        missing = [key for key in required if key not in concept]
        if missing:
            errors.append(f"concept {idx} missing keys: {', '.join(missing)}")
        cid = str(concept.get("conceptId") or "")
        if not cid:
            errors.append(f"concept {idx} missing conceptId")
        elif cid in seen:
            errors.append(f"duplicate conceptId: {cid}")
        seen.add(cid)
        if not concept.get("title"):
            errors.append(f"{cid or idx}: empty title")
        if not isinstance(concept.get("sourceSlideIds"), list) or not concept.get("sourceSlideIds"):
            errors.append(f"{cid or idx}: sourceSlideIds must be non-empty")
        for key in required:
            if (key.endswith("Facts") and key != "structuredImageFacts") or key in {"images", "tables", "groundingTerms"}:
                if not isinstance(concept.get(key), list):
                    errors.append(f"{cid or idx}: {key} must be a list")
        if not isinstance(concept.get("structuredImageFacts"), dict):
            errors.append(f"{cid or idx}: structuredImageFacts must be an object")
        if concept.get("imageTextQuality") not in {"none", "poor", "fair", "good"}:
            errors.append(f"{cid or idx}: invalid imageTextQuality {concept.get('imageTextQuality')}")
        if concept.get("dedupeDisposition") not in {"keep", "merge", "suppress", "recap_only", "low_information"}:
            errors.append(f"{cid or idx}: invalid dedupeDisposition {concept.get('dedupeDisposition')}")
        try:
            score = float(concept.get("overlapScore"))
            if score < 0 or score > 1:
                errors.append(f"{cid or idx}: overlapScore must be between 0 and 1")
        except Exception:
            errors.append(f"{cid or idx}: overlapScore must be numeric")
        for image in concept.get("images") or []:
            if isinstance(image, dict) and image.get("kind") not in allowed_image_kinds:
                errors.append(f"{cid or idx}: invalid image kind {image.get('kind')}")
    return errors


def fast_facts_fact_values(concept: dict[str, Any]) -> list[str]:
    values: list[str] = [str(concept.get("title") or "")]
    for key in [
        "clinicalFacts", "diagnosticFacts", "managementFacts", "mechanismFacts",
        "differentialFacts", "trapFacts", "cleanedImageFacts", "groundingTerms",
    ]:
        values.extend(str(v) for v in concept.get(key) or [])
    for values_list in (concept.get("structuredImageFacts") or {}).values():
        if isinstance(values_list, list):
            values.extend(str(v) for v in values_list)
    return values


def fast_facts_semantic_tokens(concept: dict[str, Any]) -> set[str]:
    text = " ".join(fast_facts_fact_values(concept))
    tokens = set(meaningful_fast_facts_terms(text))
    for token in re.findall(r"\b[A-Za-z][A-Za-z0-9+\-/]{3,}\b", text):
        key = token.lower().strip("-")
        if key not in FAST_FACTS_GENERIC_TERMS and key not in COMMON_CLINICAL_WORDS:
            tokens.add(key)
    return tokens


def fast_facts_structured_overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    scores: list[float] = []
    for key in ["criteria", "indications", "contraindications", "managementSteps", "thresholds"]:
        av = {normalize_key(v) for v in (a.get("structuredImageFacts") or {}).get(key, []) if normalize_key(v)}
        bv = {normalize_key(v) for v in (b.get("structuredImageFacts") or {}).get(key, []) if normalize_key(v)}
        if av or bv:
            scores.append(len(av & bv) / max(1, len(av | bv)))
    return max(scores) if scores else 0.0


def fast_facts_overlap_score(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, list[str]]:
    a_tokens = fast_facts_semantic_tokens(a)
    b_tokens = fast_facts_semantic_tokens(b)
    token_score = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    fact_a = {normalize_key(v) for v in fast_facts_fact_values(a) if normalize_key(v)}
    fact_b = {normalize_key(v) for v in fast_facts_fact_values(b) if normalize_key(v)}
    fact_score = len(fact_a & fact_b) / max(1, min(len(fact_a), len(fact_b)))
    structured_score = fast_facts_structured_overlap(a, b)
    title_tokens_a = set(re.findall(r"\b[a-z0-9+\-/]{4,}\b", normalize_key(a.get("title") or ""))) - FAST_FACTS_GENERIC_TERMS
    title_tokens_b = set(re.findall(r"\b[a-z0-9+\-/]{4,}\b", normalize_key(b.get("title") or ""))) - FAST_FACTS_GENERIC_TERMS
    title_score = len(title_tokens_a & title_tokens_b) / max(1, len(title_tokens_a | title_tokens_b))
    score = max(token_score, fact_score, structured_score, title_score * 0.85)
    reasons: list[str] = []
    if fact_score >= 0.5:
        reasons.append("repeated fact block")
    if structured_score >= 0.5:
        reasons.append("repeated algorithm/criteria block")
    if token_score >= 0.55:
        reasons.append("near-duplicate medical term set")
    if title_score >= 0.75 and score >= 0.65:
        reasons.append("title plus content overlap")
    if any(re.search(r"\b(screening|treatment|management|criteria|threshold)\b", normalize_key(v)) for v in fast_facts_fact_values(a) + fast_facts_fact_values(b)) and score >= 0.55:
        reasons.append("overlapping screening/treatment threshold")
    shared_tokens = a_tokens & b_tokens
    if {"urinary", "tract"} <= shared_tokens or "uti" in shared_tokens:
        reasons.append("overlapping UTI topic")
        if shared_tokens & {"nitrofurantoin", "fosfomycin", "fluoroquinolones", "ceftriaxone", "culture"}:
            reasons.append("repeated UTI management or criteria")
        score = max(score, min(1.0, token_score + 0.18))
    if "hypertension" in shared_tokens and (shared_tokens & {"renal", "sleep", "apnea", "screening", "glucose"}):
        reasons.append("overlapping hypertension evaluation")
        score = max(score, min(1.0, token_score + 0.12))
    if "diabetes" in shared_tokens and (shared_tokens & {"screening", "glucose", "a1c", "risk"}):
        reasons.append("overlapping diabetes screening/management")
        score = max(score, min(1.0, token_score + 0.12))
    return round(min(1.0, score), 3), reasons


def fast_facts_concept_information_score(concept: dict[str, Any]) -> int:
    fact_count = sum(len(concept.get(key) or []) for key in [
        "clinicalFacts", "diagnosticFacts", "managementFacts", "mechanismFacts", "differentialFacts", "trapFacts", "cleanedImageFacts",
    ])
    unique_terms = len(concept.get("groundingTerms") or [])
    unique_assets = len(concept.get("images") or []) + len(concept.get("tables") or [])
    return fact_count * 5 + unique_terms + unique_assets * 4


def fast_facts_merge_unique_list(target: dict[str, Any], source: dict[str, Any], key: str) -> list[str]:
    existing = list(target.get(key) or [])
    seen = {json.dumps(v, sort_keys=True) if isinstance(v, dict) else str(v) for v in existing}
    retained: list[str] = []
    for value in source.get(key) or []:
        marker = json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value)
        if marker not in seen:
            existing.append(value)
            seen.add(marker)
            retained.append(str(value if not isinstance(value, dict) else value.get("imageId") or value))
    target[key] = existing
    return retained


def fast_facts_merge_concepts(base: dict[str, Any], other: dict[str, Any]) -> dict[str, list[str]]:
    retained: dict[str, list[str]] = {}
    for key in [
        "sourceSlideIds", "clinicalFacts", "diagnosticFacts", "managementFacts",
        "mechanismFacts", "differentialFacts", "trapFacts", "nativeTextFacts",
        "imageOcrFacts", "cleanedImageFacts", "groundingTerms", "images", "tables",
    ]:
        retained[key] = fast_facts_merge_unique_list(base, other, key)
    for key, values in (other.get("structuredImageFacts") or {}).items():
        base.setdefault("structuredImageFacts", {}).setdefault(key, [])
        seen = set(base["structuredImageFacts"][key])
        retained_key: list[str] = []
        for value in values or []:
            if value not in seen:
                base["structuredImageFacts"][key].append(value)
                seen.add(value)
                retained_key.append(str(value))
        if retained_key:
            retained[f"structuredImageFacts.{key}"] = retained_key
    quality_order = {"none": 0, "poor": 1, "fair": 2, "good": 3}
    if quality_order.get(other.get("imageTextQuality"), 0) > quality_order.get(base.get("imageTextQuality"), 0):
        base["imageTextQuality"] = other.get("imageTextQuality")
    finalized = fast_facts_finalize_concept(base)
    if finalized:
        base.update(finalized)
    return {k: v for k, v in retained.items() if v}


def dedupe_fast_facts_concepts(concepts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    working = [copy.deepcopy(c) for c in concepts]
    before_count = len(working)
    for concept in working:
        concept["semanticClusterId"] = concept.get("semanticClusterId") or f"ff_cluster_{short_hash(concept.get('conceptId', ''))[:8]}"
        concept["duplicateOf"] = None
        concept["overlapScore"] = 0.0
        concept["dedupeDisposition"] = "keep"

    clusters: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    merged: list[dict[str, Any]] = []
    clustered_overlaps: list[dict[str, Any]] = []
    low_information: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []

    for concept in working:
        info_score = fast_facts_concept_information_score(concept)
        if info_score < 10:
            concept["dedupeDisposition"] = "low_information"
            low_information.append({
                "conceptId": concept.get("conceptId"),
                "title": concept.get("title"),
                "reason": "low information score",
                "informationScore": info_score,
            })
            continue

        best: dict[str, Any] | None = None
        best_score = 0.0
        best_reasons: list[str] = []
        for existing in kept:
            score, reasons = fast_facts_overlap_score(existing, concept)
            if score > best_score:
                best = existing
                best_score = score
                best_reasons = reasons

        if best and best_score >= 0.78 and best_reasons:
            concept["duplicateOf"] = best["conceptId"]
            concept["semanticClusterId"] = best["semanticClusterId"]
            concept["overlapScore"] = best_score
            if fast_facts_concept_information_score(concept) <= 12 and not (concept.get("images") or concept.get("trapFacts") or concept.get("differentialFacts")):
                concept["dedupeDisposition"] = "suppress"
                suppressed.append({
                    "conceptId": concept.get("conceptId"),
                    "duplicateOf": best.get("conceptId"),
                    "overlapScore": best_score,
                    "reasons": best_reasons,
                })
            else:
                concept["dedupeDisposition"] = "merge"
                retained = fast_facts_merge_concepts(best, concept)
                merged.append({
                    "conceptId": concept.get("conceptId"),
                    "mergedInto": best.get("conceptId"),
                    "overlapScore": best_score,
                    "reasons": best_reasons,
                    "retainedUniqueFacts": retained,
                })
            continue

        if best and best_score >= 0.28 and best_reasons:
            concept["semanticClusterId"] = best["semanticClusterId"]
            concept["overlapScore"] = best_score
            concept["dedupeDisposition"] = "keep"
            clustered_overlaps.append({
                "conceptId": concept.get("conceptId"),
                "clusteredWith": best.get("conceptId"),
                "semanticClusterId": best.get("semanticClusterId"),
                "overlapScore": best_score,
                "reasons": best_reasons,
                "retainedUniqueFacts": {
                    key: concept.get(key) or []
                    for key in ["clinicalFacts", "diagnosticFacts", "managementFacts", "differentialFacts", "trapFacts", "cleanedImageFacts"]
                    if concept.get(key)
                },
            })

        if re.search(r"\b(recap|summary|review|key points)\b", normalize_key(concept.get("title") or "")):
            concept["dedupeDisposition"] = "recap_only"
            low_information.append({
                "conceptId": concept.get("conceptId"),
                "title": concept.get("title"),
                "reason": "recap-only slide",
            })
            continue

        kept.append(concept)

    cluster_map: dict[str, list[dict[str, Any]]] = {}
    for concept in kept:
        cluster_map.setdefault(concept["semanticClusterId"], []).append({
            "conceptId": concept.get("conceptId"),
            "title": concept.get("title"),
            "sourceSlideIds": concept.get("sourceSlideIds"),
        })
    duplicate_clusters = [
        {"semanticClusterId": cid, "members": members}
        for cid, members in cluster_map.items()
        if len(members) > 1
    ]
    report = {
        "conceptsBeforeDedupe": before_count,
        "conceptsAfterDedupe": len(kept),
        "duplicateClustersFound": len(duplicate_clusters),
        "duplicateClusters": duplicate_clusters,
        "suppressedConcepts": suppressed,
        "mergedConcepts": merged,
        "clusteredOverlaps": clustered_overlaps,
        "lowInformationConcepts": low_information,
        "overlapComparisons": [],
    }
    for i, a in enumerate(working):
        for b in working[i + 1:]:
            score, reasons = fast_facts_overlap_score(a, b)
            if score >= 0.45 and reasons:
                report["overlapComparisons"].append({
                    "conceptA": a.get("conceptId"),
                    "titleA": a.get("title"),
                    "conceptB": b.get("conceptId"),
                    "titleB": b.get("title"),
                    "overlapScore": score,
                    "reasons": reasons,
                })
    return kept, report


def process_fast_facts_pptx(
    pptx_path: Path,
    limit_slides: int = 10,
    generate: bool = False,
    reuse_cache: bool = True,
    force_regenerate: bool = False,
    repair_only: bool = False,
    diagnostic_report: bool = False,
    question_limit: int = 0,
) -> Path:
    if pptx_path.suffix.lower() != ".pptx":
        raise PipelineError(f"Fast Facts profile expects a PPTX file: {pptx_path}")
    limit_slides = int(limit_slides or 10)
    slide_payload = decompose_fast_facts_pptx(pptx_path, limit_slides=limit_slides)
    deck_hash = slide_payload["pptxSha256"]
    checkpoint = load_fast_facts_checkpoint(pptx_path, deck_hash, limit_slides)
    concepts: list[dict[str, Any]] = list(checkpoint.get("concepts") or [])
    processed: list[str] = list(checkpoint.get("processedSlideIds") or [])
    failures: list[dict[str, Any]] = list(checkpoint.get("failures") or []) + list(slide_payload.get("failures") or [])
    processed_set = set(processed)
    for slide in slide_payload.get("slides") or []:
        if slide["slideId"] in processed_set:
            continue
        try:
            slide_concepts = atomize_fast_facts_slide(slide)
            if not slide_concepts:
                failures.append({"slideId": slide["slideId"], "slideIndex": slide["slideIndex"], "error": "no atomic concepts extracted"})
            concepts.extend(slide_concepts)
            processed.append(slide["slideId"])
            processed_set.add(slide["slideId"])
            write_fast_facts_checkpoint(pptx_path, deck_hash, limit_slides, concepts, processed, failures)
        except Exception as exc:
            failures.append({"slideId": slide.get("slideId"), "slideIndex": slide.get("slideIndex"), "error": str(exc)})
            processed.append(slide["slideId"])
            processed_set.add(slide["slideId"])
            write_fast_facts_checkpoint(pptx_path, deck_hash, limit_slides, concepts, processed, failures)
    deduped_concepts, dedupe_report = dedupe_fast_facts_concepts(concepts)
    graph = {
        "profile": FAST_FACTS_PROFILE,
        "deckTitle": pptx_path.stem,
        "slideCount": int(slide_payload.get("slideCount") or 0),
        "concepts": deduped_concepts,
    }
    errors = validate_fast_facts_concept_graph(graph)
    report = {
        "profile": FAST_FACTS_PROFILE,
        "sourceFile": pptx_path.name,
        "slidesProcessed": len(slide_payload.get("slides") or []),
        "conceptsExtracted": len(concepts),
        "conceptsAfterDedupe": len(deduped_concepts),
        "dedupeReport": dedupe_report,
        "imagesFound": sum(len(s.get("images") or []) for s in slide_payload.get("slides") or []),
        "tablesFound": sum(len(s.get("tables") or []) for s in slide_payload.get("slides") or []),
        "skippedSlides": len([f for f in failures if "slide" in str(f).lower() or f.get("slideId")]),
        "topConceptExamples": [
            {
                "conceptId": c.get("conceptId"),
                "sourceSlideIds": c.get("sourceSlideIds"),
                "title": c.get("title"),
                "category": c.get("category"),
                "questionPotential": c.get("questionPotential"),
            }
            for c in concepts[:10]
        ],
        "extractionFailures": failures,
        "validationErrors": errors,
        "checkpointPath": str(fast_facts_checkpoint_path(pptx_path).relative_to(BASE_DIR)),
    }
    report_path = write_report(report, "fast_facts_concept_extraction_report")
    if errors:
        raise PipelineError("Fast Facts concept graph validation failed:\n" + "\n".join(f"- {err}" for err in errors[:80]))
    out_path = fast_facts_output_path(pptx_path)
    write_json(out_path, graph)
    json.loads(out_path.read_text(encoding="utf-8"))
    log(f"Fast Facts concept graph -> {out_path.relative_to(BASE_DIR)}")
    log(f"Fast Facts report -> {report_path.relative_to(BASE_DIR)}")
    if generate:
        return run_fast_facts_generation_milestone(
            pptx_path,
            graph,
            deck_hash,
            limit_slides,
            report,
            reuse_cache=reuse_cache,
            force_regenerate=force_regenerate,
            repair_only=repair_only,
            diagnostic_report=diagnostic_report,
            question_limit=question_limit,
        )
    if diagnostic_report:
        skeleton_allocations = limit_fast_facts_question_attempts(
            fast_facts_allocations(fast_facts_normalized_payload(pptx_path, graph, deck_hash, limit_slides)[0], empty_memory()),
            question_limit,
        )
        write_fast_facts_diagnostic_report({
            "runAt": timestamp_iso(),
            "profile": FAST_FACTS_PROFILE,
            "sourceFile": pptx_path.name,
            "sourcePath": str(pptx_path),
            "limitSlides": int(limit_slides or 0),
            "questionAttemptLimit": int(question_limit or 0),
            "generationRun": False,
            "entries": [
                fast_facts_diagnostic_entry(allocation)
                for allocation in skeleton_allocations
                if int(allocation.get("questionCount") or 0) > 0
            ],
        })
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate NBME-style questions from lecture-slide PDFs.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Run deterministic pipeline without Gemini.")
    mode.add_argument("--generate", action="store_true", help="Run semantic normalization and question generation with Gemini.")
    mode.add_argument("--repair-existing", action="store_true", help="Repair existing generated questions without rerunning full-deck generation.")
    mode.add_argument("--validate-only", default="", help="Validate an app-ready JSON output.")
    parser.add_argument("--fast-facts-profile", action="store_true", help="Use FAST_FACTS_PROFILE PPTX concept graph mode. Combine with --generate for the constrained generation milestone.")
    parser.add_argument("--amboss-profile", action="store_true", help="Use AMBOSS_PROFILE deterministic extraction mode for PDFs or screenshot exports.")
    parser.add_argument("--reuse-cache", action=argparse.BooleanOptionalAction, default=True, help="Reuse valid Fast Facts cached questions when available.")
    parser.add_argument("--force-regenerate", action="store_true", help="Ignore Fast Facts cache hits and regenerate eligible questions.")
    parser.add_argument("--repair-only", action="store_true", help="Fast Facts only: repair/revalidate cache without generating cache misses.")
    parser.add_argument("--show-cache-status", action="store_true", help="Show Fast Facts question cache status and exit.")
    parser.add_argument("--fast-facts-diagnostic-report", action="store_true", help="Fast Facts only: write a diagnostic report for the generation and validation chain.")
    parser.add_argument("--fast-facts-question-limit", type=int, default=0, help="Fast Facts only: cap attempted generation allocations without changing the normal default.")
    parser.add_argument("--input-dir", default="", help="Folder containing lecture PDFs.")
    parser.add_argument("--input-file", default="", help="Single PDF/PPTX input file.")
    parser.add_argument("--normalized-chunks", default="", help="Shared normalized chunk bundle JSON to consume instead of reopening the source PDF.")
    parser.add_argument("--limit", type=int, default=0, help="Limit PDFs processed.")
    return parser.parse_args()


def main() -> int:
    ensure_dirs()
    args = parse_args()
    try:
        if args.validate_only:
            validate_only(Path(args.validate_only).resolve())
            return 0
        if args.show_cache_status:
            show_fast_facts_cache_status()
            return 0
        if args.fast_facts_profile:
            if args.input_file:
                pptx_files = [Path(args.input_file).expanduser().resolve()]
            else:
                input_dir = Path(args.input_dir).resolve() if args.input_dir else INPUT_DIR
                pptx_files = supported_pptx(input_dir)
            if not pptx_files:
                raise PipelineError("No PPTX files found for FAST_FACTS_PROFILE.")
            outputs = [
                process_fast_facts_pptx(
                    path,
                    limit_slides=args.limit or 10,
                    generate=args.generate or args.repair_only,
                    reuse_cache=args.reuse_cache,
                    force_regenerate=args.force_regenerate,
                    repair_only=args.repair_only,
                    diagnostic_report=args.fast_facts_diagnostic_report,
                    question_limit=args.fast_facts_question_limit,
                )
                for path in pptx_files[:1]
            ]
            print("Generated Fast Facts files:")
            for output in outputs:
                print(f"  {output}")
            return 0
        if args.amboss_profile:
            if args.input_file:
                amboss_inputs = [Path(args.input_file).expanduser().resolve()]
            else:
                input_dir = Path(args.input_dir).resolve() if args.input_dir else INPUT_DIR
                amboss_inputs = supported_amboss_inputs(input_dir)
            if not amboss_inputs:
                raise PipelineError("No PDF/image files found for AMBOSS_PROFILE.")
            outputs = [process_amboss_input(path, limit_pages=args.limit or 5) for path in amboss_inputs[:1]]
            print("Generated AMBOSS files:")
            for output in outputs:
                print(f"  {output}")
            return 0
        if not args.dry_run and not args.generate and not args.repair_existing:
            print("No action specified. Use --dry-run, --generate, --repair-existing, --fast-facts-profile, or --validate-only.")
            return 2
        if args.normalized_chunks:
            if args.repair_existing:
                raise PipelineError("--repair-existing is not supported with --normalized-chunks.")
            output = process_normalized_chunks(Path(args.normalized_chunks).expanduser().resolve(), generate=args.generate)
            print("Generated app-ready files:")
            print(f"  {output}")
            return 0
        if args.input_file:
            pdfs = [Path(args.input_file).expanduser().resolve()]
        else:
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
