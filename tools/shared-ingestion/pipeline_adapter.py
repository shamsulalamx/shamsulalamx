#!/usr/bin/env python3
"""
Thin adapters from existing pipeline artifacts to shared normalized chunks.

Adapters may call extraction/decomposition functions, but they do not change
existing downstream generation logic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from asset_router import normalize_image_refs, normalize_table_refs
from normalized_chunk_schema import NormalizedChunk, build_chunk_bundle
from source_descriptor import get_source_descriptor


ADAPTER_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = ADAPTER_DIR.parents[1]
LECTURE_DIR = PROJECT_ROOT / "tools" / "lecture-slide-question-generator"
NBME_DIR = PROJECT_ROOT / "tools" / "nbme-pdf-json-generator"


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


def _import_lecture_generator() -> Any:
    sys.path.insert(0, str(LECTURE_DIR))
    import generate_lecture_slide_questions as generator  # type: ignore
    return generator


def _import_nbme_modules() -> tuple[Any, Any]:
    sys.path.insert(0, str(NBME_DIR))
    import extract_pdfs  # type: ignore
    import nbme_batch_wrapper  # type: ignore
    return extract_pdfs, nbme_batch_wrapper


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


def emit_normalized_chunks(source_type: str, input_path: Path, output_path: Path, limit: int = 5, refresh: bool = False) -> dict[str, Any]:
    if source_type == "amboss_pdf":
        bundle = amboss_to_normalized_chunks(input_path, limit=limit)
    elif source_type == "emma_holiday_pdf":
        bundle = emma_to_normalized_chunks(input_path, limit=limit)
    elif source_type == "nbme_pdf":
        bundle = nbme_to_normalized_chunks(input_path, limit=limit, refresh=refresh)
    elif source_type == "fast_facts_pptx":
        bundle = fast_facts_to_normalized_chunks(input_path, limit=limit)
    else:
        raise ValueError(f"No normalized chunk adapter exists for source_type: {source_type}")
    write_json(output_path, bundle)
    return bundle
