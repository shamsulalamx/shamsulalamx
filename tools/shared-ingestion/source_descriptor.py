#!/usr/bin/env python3
"""
Source descriptors for the shared normalized chunk engine.

This module is metadata only. It describes how a source behaves without
rewriting the source-specific extractor or generator.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Modality = Literal["pdf", "pptx", "image", "audio", "text", "json"]
ExtractionStyle = Literal["native_text", "ocr", "slide_decomposition", "question_extraction", "transcript"]
GenerationStyle = Literal["deterministic", "llm_normalization", "llm_generation", "existing_downstream"]
AssetPolicy = Literal["none", "preserve", "route_to_stem", "route_to_explanation", "manual_review"]
CachePolicy = Literal["none", "read_only", "read_write", "source_hash"]


@dataclass(frozen=True)
class SourceDescriptor:
    source_type: str
    modality: Modality
    extraction_style: ExtractionStyle
    generation_style: GenerationStyle
    asset_policy: AssetPolicy
    cache_policy: CachePolicy
    schema_version: str = "shared-source-descriptor-v1"
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SOURCE_DESCRIPTORS: dict[str, SourceDescriptor] = {
    "amboss_pdf": SourceDescriptor(
        source_type="amboss_pdf",
        modality="pdf",
        extraction_style="question_extraction",
        generation_style="existing_downstream",
        asset_policy="route_to_explanation",
        cache_policy="read_write",
        notes="Uses existing AMBOSS page decomposition/extraction artifacts; downstream question conversion is unchanged.",
    ),
    "nbme_pdf": SourceDescriptor(
        source_type="nbme_pdf",
        modality="pdf",
        extraction_style="ocr",
        generation_style="llm_normalization",
        asset_policy="manual_review",
        cache_policy="source_hash",
        notes="Uses existing NBME OCR/chunk artifacts; app-ready conversion remains in the existing generator.",
    ),
    "fast_facts_pptx": SourceDescriptor(
        source_type="fast_facts_pptx",
        modality="pptx",
        extraction_style="slide_decomposition",
        generation_style="existing_downstream",
        asset_policy="preserve",
        cache_policy="read_write",
        notes="Uses existing Fast Facts slide decomposition only; generation quality logic is untouched.",
    ),
    "emma_holiday_pdf": SourceDescriptor(
        source_type="emma_holiday_pdf",
        modality="pdf",
        extraction_style="slide_decomposition",
        generation_style="existing_downstream",
        asset_policy="preserve",
        cache_policy="source_hash",
        notes="Profile-style source using shared normalized slide chunks before invoking the existing Emma downstream generator.",
        metadata={
            "profileStatus": "active",
            "downstreamGenerator": "tools/lecture-slide-question-generator/generate_lecture_slide_questions.py",
            "promptPolicy": "unchanged",
        },
    ),
}


def get_source_descriptor(source_type: str) -> SourceDescriptor:
    try:
        return SOURCE_DESCRIPTORS[source_type]
    except KeyError as exc:
        known = ", ".join(sorted(SOURCE_DESCRIPTORS))
        raise ValueError(f"Unknown source_type: {source_type}. Known source types: {known}") from exc
