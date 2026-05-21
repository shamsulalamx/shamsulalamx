#!/usr/bin/env python3
"""
Thin adapters from existing pipeline artifacts to shared normalized chunks.

Adapters may call extraction/decomposition functions, but they do not change
existing downstream generation logic.
"""

from __future__ import annotations

import json
import mimetypes
import csv
import re
import shutil
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Any

from asset_router import normalize_image_refs, normalize_table_refs
from normalized_chunk_schema import NormalizedChunk, build_chunk_bundle
from source_descriptor import get_source_descriptor


ADAPTER_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = ADAPTER_DIR.parents[1]
LECTURE_DIR = PROJECT_ROOT / "tools" / "lecture-slide-question-generator"
NBME_DIR = PROJECT_ROOT / "tools" / "nbme-pdf-json-generator"
MEHLMAN_DIR = PROJECT_ROOT / "tools" / "mehlman-pdf-question-generator"
IMAGES_TABLES_DIR = PROJECT_ROOT / "tools" / "images-tables-question-generator"
IMAGES_TABLES_ASSET_DIR = IMAGES_TABLES_DIR / "output_assets"
SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
SUPPORTED_ANKI_EXTS = {".txt", ".md"}


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def file_sha(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(value: str) -> str:
    import re

    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("._")
    return value or "asset"


def mime_for(path: Path) -> str:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if path.suffix.lower() == ".png":
        return "image/png"
    if path.suffix.lower() == ".webp":
        return "image/webp"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def image_dimensions(path: Path) -> tuple[int, int]:
    sips = shutil.which("sips")
    if not sips:
        return 0, 0
    result = subprocess.run(
        [sips, "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        return 0, 0
    width = height = 0
    for line in result.stdout.splitlines():
        if "pixelWidth:" in line:
            width = int(line.rsplit(":", 1)[-1].strip() or 0)
        if "pixelHeight:" in line:
            height = int(line.rsplit(":", 1)[-1].strip() or 0)
    return width, height


def ocr_image_text(path: Path) -> tuple[str, list[str]]:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        return "", ["OCR unavailable: tesseract not found."]
    result = subprocess.run(
        [tesseract, str(path), "stdout", "--psm", "6"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )
    warnings: list[str] = []
    if result.returncode != 0:
        warnings.append((result.stderr or "OCR failed.").strip()[:240])
    text = " ".join(result.stdout.split())
    return text, warnings


def supported_images_from_input(input_path: Path, limit: int = 0) -> list[Path]:
    input_path = input_path.resolve()
    if input_path.is_file():
        files = [input_path] if input_path.suffix.lower() in SUPPORTED_IMAGE_EXTS else []
    elif input_path.is_dir():
        files = [
            path for path in sorted(input_path.iterdir())
            if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in SUPPORTED_IMAGE_EXTS
        ]
    else:
        files = []
    return files[:limit] if limit else files


def classify_images_tables_asset(path: Path, ocr_text: str) -> tuple[str, float, str]:
    haystack = f"{path.stem} {ocr_text}".lower()
    if any(token in haystack for token in ("algorithm", "flowchart", "pathway", "process", "approach", "workup")):
        return "algorithm", 0.86, "filename/OCR matched algorithm or pathway language"
    if any(token in haystack for token in ("table", "vitamin", "criteria", "score", "lab", "classification")):
        return "table_image", 0.86, "filename/OCR matched table language"
    if any(token in haystack for token in ("chart", "graph", "axis", "plot", "curve")):
        return "chart", 0.78, "filename/OCR matched chart language"
    if ocr_text:
        return "stem_image", 0.62, "OCR text present but no table/algorithm/chart signal"
    return "unknown", 0.45, "no OCR text or filename signal"


def copy_images_tables_asset(src: Path) -> Path:
    IMAGES_TABLES_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    digest = file_sha(src)[:12]
    dest = IMAGES_TABLES_ASSET_DIR / f"{slugify(src.stem)}_{digest}{src.suffix.lower()}"
    if not dest.exists() or file_sha(dest) != file_sha(src):
        shutil.copy2(src, dest)
    return dest


def _import_lecture_generator() -> Any:
    sys.path.insert(0, str(LECTURE_DIR))
    import generate_lecture_slide_questions as generator  # type: ignore
    return generator


def _import_nbme_modules() -> tuple[Any, Any]:
    sys.path.insert(0, str(NBME_DIR))
    import extract_pdfs  # type: ignore
    import nbme_batch_wrapper  # type: ignore
    return extract_pdfs, nbme_batch_wrapper


def _import_mehlman_generator() -> Any:
    sys.path.insert(0, str(MEHLMAN_DIR))
    import generate_mehlman_questions as generator  # type: ignore
    return generator


def _lecture_slide_chunk(source_type: str, source_file: str, source_path: str, slide: dict[str, Any], chunk_type: str = "slide") -> dict[str, Any]:
    slide_id = str(slide.get("slideId") or slide.get("pageId") or f"{source_type}_chunk")
    grounding = {
        "slideId": slide.get("slideId"),
        "pageId": slide.get("pageId"),
        "slideIndex": slide.get("slideIndex"),
        "pageIndex": slide.get("pageIndex"),
        "sourcePath": source_path,
    }
    text = str(slide.get("ocrText") or slide.get("nativeText") or slide.get("questionText") or "")
    text_blocks = slide.get("textBlocks") if isinstance(slide.get("textBlocks"), list) else []
    return NormalizedChunk(
        chunkId=slide_id,
        chunkType=chunk_type,  # type: ignore[arg-type]
        sourceType=source_type,
        sourceFile=source_file,
        sourceGrounding=grounding,
        text=text,
        textBlocks=text_blocks,
        imageRefs=normalize_image_refs(slide.get("images") or [], source_id=slide_id, source_type=source_type, grounding=grounding),
        tableRefs=normalize_table_refs(slide.get("tables") or [], source_id=slide_id, source_type=source_type, grounding=grounding),
        confidence=0.75 if text else 0.45,
        metadata={k: v for k, v in (slide.get("metadata") or {}).items()},
        warnings=list(slide.get("warnings") or []),
    ).to_dict()


def amboss_to_normalized_chunks(input_path: Path, limit: int = 5) -> dict[str, Any]:
    generator = _import_lecture_generator()
    payload = generator.decompose_amboss_input(input_path.resolve(), limit_pages=limit)
    source_file = str(payload.get("sourceFile") or input_path.name)
    source_path = str(payload.get("sourcePath") or input_path)
    chunks = [
        _lecture_slide_chunk("amboss_pdf", source_file, source_path, page, chunk_type="question")
        for page in payload.get("pages") or []
        if isinstance(page, dict)
    ]
    return build_chunk_bundle(
        source_descriptor=get_source_descriptor("amboss_pdf").to_dict(),
        source_file=source_file,
        source_path=source_path,
        chunks=chunks,
        warnings=[],
    )


def emma_to_normalized_chunks(input_path: Path, limit: int = 5) -> dict[str, Any]:
    generator = _import_lecture_generator()
    payload = generator.load_or_decompose_pdf(input_path.resolve())
    source_file = str(payload.get("sourceFile") or input_path.name)
    source_path = str(payload.get("sourcePath") or input_path)
    slides = payload.get("slides") or []
    if limit:
        slides = slides[:limit]
    chunks = [
        _lecture_slide_chunk("emma_holiday_pdf", source_file, source_path, slide, chunk_type="slide")
        for slide in slides
        if isinstance(slide, dict)
    ]
    return build_chunk_bundle(
        source_descriptor=get_source_descriptor("emma_holiday_pdf").to_dict(),
        source_file=source_file,
        source_path=source_path,
        chunks=chunks,
        warnings=[],
    )


def nbme_to_normalized_chunks(input_path: Path, limit: int = 5, refresh: bool = False) -> dict[str, Any]:
    extract_pdfs, wrapper = _import_nbme_modules()
    input_path = input_path.resolve()
    paths = wrapper.artifact_paths(input_path, limit)
    if refresh or not paths["chunks"].exists():
        wrapper.run_ocr(type("Args", (), {"input_file": str(input_path), "max_pages": limit, "force_ocr": False})())
        wrapper.run_chunking(type("Args", (), {"input_file": str(input_path), "max_pages": limit})())
    if not paths["chunks"].exists():
        raise FileNotFoundError(f"NBME chunk file was not produced: {paths['chunks']}")
    payload = read_json(paths["chunks"])
    source_file = str(payload.get("sourceFile") or input_path.name)
    source_path = rel(input_path)
    chunks: list[dict[str, Any]] = []
    for item in payload.get("chunks") or []:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunkId") or f"nbme_q{item.get('questionNumber', len(chunks) + 1):03d}")
        grounding = {
            "questionNumber": item.get("questionNumber"),
            "sourceChunkFile": rel(paths["chunks"]),
            "sourcePath": source_path,
        }
        chunks.append(NormalizedChunk(
            chunkId=chunk_id,
            chunkType="question",
            sourceType="nbme_pdf",
            sourceFile=source_file,
            sourceGrounding=grounding,
            text=str(item.get("rawText") or ""),
            imageRefs=[],
            tableRefs=[],
            confidence=0.65 if item.get("rawText") else 0.35,
            metadata={k: v for k, v in item.items() if k not in {"rawText", "warnings"}},
            warnings=list(item.get("warnings") or []),
        ).to_dict())
    return build_chunk_bundle(
        source_descriptor=get_source_descriptor("nbme_pdf").to_dict(),
        source_file=source_file,
        source_path=source_path,
        chunks=chunks,
        warnings=list(payload.get("fileWarnings") or []),
    )


def anki_notes_to_normalized_chunks(input_path: Path, limit: int = 25) -> dict[str, Any]:
    input_path = input_path.resolve()
    if input_path.suffix.lower() not in SUPPORTED_ANKI_EXTS:
        raise ValueError(f"Unsupported Anki notes extension: {input_path.suffix}. Supported: {', '.join(sorted(SUPPORTED_ANKI_EXTS))}")
    raw_text = input_path.read_text(encoding="utf-8", errors="replace")
    source_file = input_path.name
    source_path = rel(input_path)
    cards: list[dict[str, Any]] = []
    directives: dict[str, str] = {}
    tag_column = 0

    for line_number, line in enumerate(raw_text.splitlines(), start=1):
        if not line.strip():
            continue
        if line.startswith("#"):
            if ":" in line:
                key, value = line[1:].split(":", 1)
                directives[key.strip()] = value.strip()
                if key.strip().lower() == "tags column":
                    try:
                        tag_column = int(value.strip())
                    except ValueError:
                        tag_column = 0
            else:
                directives[line[1:].strip()] = ""
            continue
        row = next(csv.reader(StringIO(line), delimiter="\t"))
        fields = [field.strip() for field in row]
        nonempty = [field for field in fields if field]
        front = nonempty[0] if nonempty else ""
        back = nonempty[1] if len(nonempty) > 1 else ""
        tags_text = fields[tag_column - 1] if tag_column and len(fields) >= tag_column else ""
        tags = [tag for tag in re.split(r"\s+", tags_text.strip()) if tag]
        cloze_terms = re.findall(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}", "\n".join(nonempty))
        cards.append({
            "lineNumber": line_number,
            "fieldCount": len(fields),
            "fields": fields,
            "front": front,
            "back": back,
            "tags": tags,
            "clozeTerms": cloze_terms,
            "rawText": line,
        })

    selected_cards = cards[:limit] if limit else cards
    chunks: list[dict[str, Any]] = []
    for index, card in enumerate(selected_cards, start=1):
        chunk_id = f"{slugify(input_path.stem)}_anki_card_{index:04d}"
        grounding = {
            "cardIndex": index,
            "lineNumber": card["lineNumber"],
            "sourcePath": source_path,
        }
        text_parts = [card["front"], card["back"]]
        for field in card["fields"]:
            if field and field not in text_parts:
                text_parts.append(field)
        chunks.append(NormalizedChunk(
            chunkId=chunk_id,
            chunkType="text",
            sourceType="anki_notes",
            sourceFile=source_file,
            sourceGrounding=grounding,
            text="\n\n".join(part for part in text_parts if part),
            textBlocks=[
                {"role": "front", "text": card["front"]},
                {"role": "back", "text": card["back"]},
                {"role": "raw", "text": card["rawText"]},
            ],
            imageRefs=[],
            tableRefs=[],
            confidence=0.8 if card["front"] or card["back"] else 0.45,
            metadata={
                "sourceFormat": "anki-plain-text-export",
                "cardIndex": index,
                "lineNumber": card["lineNumber"],
                "fieldCount": card["fieldCount"],
                "front": card["front"],
                "back": card["back"],
                "fields": card["fields"],
                "clozeTerms": card["clozeTerms"],
                "tags": card["tags"],
                "directives": directives,
                "downstreamHandoff": "validated selected-input dry-run handoff to existing Anki wrapper; BIC dry-run auto-import validated in dev and packaged app; live Gemini generation and semantic question quality remain unvalidated",
            },
            warnings=[],
        ).to_dict())

    return build_chunk_bundle(
        source_descriptor=get_source_descriptor("anki_notes").to_dict(),
        source_file=source_file,
        source_path=source_path,
        chunks=chunks,
        warnings=[] if cards else ["No Anki card rows found in source file."],
    )


def fast_facts_to_normalized_chunks(input_path: Path, limit: int = 10) -> dict[str, Any]:
    input_path = input_path.resolve()
    if input_path.suffix.lower() == ".json":
        payload = read_json(input_path)
    else:
        generator = _import_lecture_generator()
        payload = generator.decompose_fast_facts_pptx(input_path, limit_slides=limit)
    source_file = str(payload.get("sourceFile") or input_path.name)
    source_path = str(payload.get("sourcePath") or input_path)
    slides = payload.get("slides") or []
    if limit and input_path.suffix.lower() == ".json":
        slides = slides[:limit]
    chunks = [
        _lecture_slide_chunk("fast_facts_pptx", source_file, source_path, slide, chunk_type="slide")
        for slide in slides
        if isinstance(slide, dict)
    ]
    return build_chunk_bundle(
        source_descriptor=get_source_descriptor("fast_facts_pptx").to_dict(),
        source_file=source_file,
        source_path=source_path,
        chunks=chunks,
        warnings=list(payload.get("failures") or []),
    )


def _mehlman_asset_entries(chunk: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    figures: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    for fig in chunk.get("figures") or []:
        if not isinstance(fig, dict):
            continue
        filename = str(fig.get("filename") or "")
        figures.append({
            "imageId": Path(filename).stem if filename else "",
            "path": rel(MEHLMAN_DIR / "extracted_figures" / filename) if filename else "",
            "visibleText": "",
            "width": fig.get("width"),
            "height": fig.get("height"),
            "confidence": fig.get("confidence"),
            "kind": "embedded_figure",
        })
    for table in chunk.get("tables") or []:
        if not isinstance(table, dict):
            continue
        filename = str(table.get("filename") or "")
        tables.append({
            "tableId": Path(filename).stem if filename else "",
            "path": rel(MEHLMAN_DIR / "extracted_tables" / filename) if filename else "",
            "text": str(table.get("markdown") or ""),
            "rows": table.get("rows"),
            "cols": table.get("cols"),
            "kind": "embedded_table",
        })
    return figures, tables


def mehlman_to_normalized_chunks(input_path: Path, limit: int = 10) -> dict[str, Any]:
    generator = _import_mehlman_generator()
    input_path = input_path.resolve()
    for directory in (generator.TEXT_DIR, generator.FIG_DIR, generator.TABLE_DIR, generator.CHUNK_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    stats = generator._empty_stats()
    pages = generator.extract_pdf_pages(input_path, extract_assets=True, stats=stats, max_pages=limit or None)
    chunks = generator.split_pages_into_chunks(pages)
    source_file = input_path.name
    source_path = rel(input_path)
    normalized_chunks: list[dict[str, Any]] = []
    page_lookup = {int(page.get("pageNum")): page for page in pages if isinstance(page, dict) and page.get("pageNum")}
    for item in chunks:
        if not isinstance(item, dict):
            continue
        chunk_id = f"{input_path.stem.replace(' ', '_')}_p{int(item.get('pageStart') or 0):03d}_p{int(item.get('pageEnd') or 0):03d}_c{int(item.get('chunkId') or len(normalized_chunks) + 1):03d}"
        grounding = {
            "pageStart": item.get("pageStart"),
            "pageEnd": item.get("pageEnd"),
            "sourcePath": source_path,
        }
        figures, tables = _mehlman_asset_entries(item)
        text_blocks = []
        start = int(item.get("pageStart") or 0)
        end = int(item.get("pageEnd") or start)
        for page_num in range(start, end + 1):
            page = page_lookup.get(page_num)
            if page:
                text_blocks.append({
                    "pageNum": page_num,
                    "text": str(page.get("text") or ""),
                    "warnings": list(page.get("warnings") or []),
                })
        normalized_chunks.append(NormalizedChunk(
            chunkId=chunk_id,
            chunkType="text",
            sourceType="mehlman_pdf",
            sourceFile=source_file,
            sourceGrounding=grounding,
            text=str(item.get("text") or ""),
            textBlocks=text_blocks,
            imageRefs=normalize_image_refs(figures, source_id=chunk_id, source_type="mehlman_pdf", grounding=grounding),
            tableRefs=normalize_table_refs(tables, source_id=chunk_id, source_type="mehlman_pdf", grounding=grounding),
            confidence=0.8 if item.get("text") else 0.35,
            metadata={
                "charCount": item.get("charCount"),
                "sourceChunkId": item.get("chunkId"),
                "totalSourcePages": stats.get("totalSourcePages") or stats.get("totalPages"),
                "processedPages": stats.get("totalPages"),
            },
            warnings=list(item.get("warnings") or []),
        ).to_dict())
    return build_chunk_bundle(
        source_descriptor=get_source_descriptor("mehlman_pdf").to_dict(),
        source_file=source_file,
        source_path=source_path,
        chunks=normalized_chunks,
        warnings=list(stats.get("warnings") or []),
    )


def images_tables_to_normalized_chunks(input_path: Path, limit: int = 5) -> dict[str, Any]:
    input_path = input_path.resolve()
    files = supported_images_from_input(input_path, limit=limit)
    if not files:
        raise ValueError(f"No supported image assets found in {input_path}. Supported: {', '.join(sorted(SUPPORTED_IMAGE_EXTS))}")
    chunks: list[dict[str, Any]] = []
    bundle_warnings: list[str] = []
    source_file = input_path.name
    source_path = rel(input_path)
    for index, src in enumerate(files, start=1):
        asset_path = copy_images_tables_asset(src)
        ocr_text, ocr_warnings = ocr_image_text(asset_path)
        kind, confidence, reason = classify_images_tables_asset(src, ocr_text)
        width, height = image_dimensions(asset_path)
        chunk_type = "table" if kind == "table_image" else "image"
        chunk_id = f"{slugify(src.stem)}_{file_sha(src)[:8]}"
        grounding = {
            "assetIndex": index,
            "sourcePath": rel(src),
            "assetPath": rel(asset_path),
            "width": width,
            "height": height,
        }
        image_asset = {
            "imageId": chunk_id,
            "path": rel(asset_path),
            "visibleText": ocr_text,
            "caption": src.stem.replace("_", " "),
            "kind": kind,
            "width": width,
            "height": height,
            "mimeType": mime_for(asset_path),
            "sha256": file_sha(asset_path),
            "attachmentConfidence": confidence,
            "classificationReason": reason,
        }
        image_refs = normalize_image_refs([image_asset], source_id=chunk_id, source_type="images_tables_source", grounding=grounding)
        table_refs: list[dict[str, Any]] = []
        if kind == "table_image":
            table_refs = normalize_table_refs([{
                "tableId": f"{chunk_id}_table",
                "path": rel(asset_path),
                "text": ocr_text,
                "title": src.stem.replace("_", " "),
                "rows": [],
                "headers": [],
                "attachmentConfidence": confidence,
            }], source_id=chunk_id, source_type="images_tables_source", grounding=grounding)
        warnings = ocr_warnings[:]
        if not ocr_text:
            warnings.append("No OCR text extracted; filename/caption used as fallback text.")
        chunks.append(NormalizedChunk(
            chunkId=chunk_id,
            chunkType=chunk_type,  # type: ignore[arg-type]
            sourceType="images_tables_source",
            sourceFile=source_file,
            sourceGrounding=grounding,
            text=ocr_text or src.stem.replace("_", " "),
            textBlocks=[{
                "kind": "ocr",
                "text": ocr_text,
                "available": bool(ocr_text),
                "fallbackText": src.stem.replace("_", " "),
            }],
            imageRefs=image_refs,
            tableRefs=table_refs,
            confidence=confidence,
            metadata={
                "assetKind": kind,
                "attachmentConfidence": confidence,
                "classificationReason": reason,
                "originalFileName": src.name,
                "mimeType": mime_for(asset_path),
                "assetPolicy": "preserve",
            },
            warnings=warnings,
        ).to_dict())
        bundle_warnings.extend(f"{src.name}: {warning}" for warning in warnings if warning)
    return build_chunk_bundle(
        source_descriptor=get_source_descriptor("images_tables_source").to_dict(),
        source_file=source_file,
        source_path=source_path,
        chunks=chunks,
        warnings=bundle_warnings,
    )


def emit_normalized_chunks(source_type: str, input_path: Path, output_path: Path, limit: int = 5, refresh: bool = False) -> dict[str, Any]:
    if source_type == "amboss_pdf":
        bundle = amboss_to_normalized_chunks(input_path, limit=limit)
    elif source_type == "emma_holiday_pdf":
        bundle = emma_to_normalized_chunks(input_path, limit=limit)
    elif source_type == "nbme_pdf":
        bundle = nbme_to_normalized_chunks(input_path, limit=limit, refresh=refresh)
    elif source_type == "anki_notes":
        bundle = anki_notes_to_normalized_chunks(input_path, limit=limit)
    elif source_type == "fast_facts_pptx":
        bundle = fast_facts_to_normalized_chunks(input_path, limit=limit)
    elif source_type == "mehlman_pdf":
        bundle = mehlman_to_normalized_chunks(input_path, limit=limit)
    elif source_type == "images_tables_source":
        bundle = images_tables_to_normalized_chunks(input_path, limit=limit)
    else:
        raise ValueError(f"No normalized chunk adapter exists for source_type: {source_type}")
    write_json(output_path, bundle)
    return bundle
