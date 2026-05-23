#!/usr/bin/env python3
from __future__ import annotations

from enum import Enum


class ExecutionMode(str, Enum):
    UOGA = "uoga_v6"
    LEGACY = "legacy"


class PipelineRoute(str, Enum):
    ORGANIC_GENERATION = "organic_generation"
    EXTRACTIVE_TRANSFORMATION = "extractive_transformation"
    VISION_ANNOTATION = "vision_annotation"


ORGANIC_SOURCE_MARKERS = (
    "fast_facts",
    "lecture_slide_generation",
    "lecture_slide_pdf",
    "lecture_slide_generator",
    "lecture-slide-generator",
    "emma",
    "question_synthesis",
    "organic_generation",
)
EXTRACTIVE_SOURCE_MARKERS = (
    "amboss_pdf",
    "amboss",
    "pdf_extraction",
    "nbme",
    "curated_dataset",
    "imported_questions",
    "static_bank",
    "anki_notes",
    "anki",
    "uworld",
    "divine",
    "mehlman_pdf",
    "mehlman",
    "ome_pdf",
    "ome",
    "images_tables_source",
    "images_tables",
    "images-tables",
)
UOGA_GRAPH_NATIVE_SOURCE_TYPES = {
    "fast_facts_pptx",
}


def normalize_source_type(source_type: str) -> str:
    return str(source_type or "").strip().lower().replace("-", "_")


def classify_pipeline_route(source_type: str, *, has_images: bool = False, amboss_context: bool = False) -> PipelineRoute:
    normalized = normalize_source_type(source_type)
    if any(marker in normalized for marker in ORGANIC_SOURCE_MARKERS):
        return PipelineRoute.ORGANIC_GENERATION
    if any(marker in normalized for marker in EXTRACTIVE_SOURCE_MARKERS):
        return PipelineRoute.EXTRACTIVE_TRANSFORMATION
    if has_images and amboss_context:
        return PipelineRoute.VISION_ANNOTATION
    raise ValueError(f"Ambiguous pipeline sourceType cannot be routed safely: {source_type!r}")


def determine_execution_mode(source_type: str) -> ExecutionMode:
    normalized = normalize_source_type(source_type)
    route = classify_pipeline_route(source_type)
    if route == PipelineRoute.ORGANIC_GENERATION:
        if normalized in UOGA_GRAPH_NATIVE_SOURCE_TYPES:
            return ExecutionMode.UOGA
        raise ValueError(
            f"Organic sourceType is not graph-native and cannot run in hybrid mode: {source_type!r}"
        )
    return ExecutionMode.LEGACY
