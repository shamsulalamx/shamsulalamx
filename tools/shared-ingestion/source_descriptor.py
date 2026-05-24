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
ExtractionStyle = Literal["native_text", "ocr", "slide_decomposition", "question_extraction", "transcript", "multimodal_asset"]
GenerationStyle = Literal["deterministic", "llm_normalization", "llm_generation", "existing_downstream", "attachment_first"]
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
    "uworld_notes": SourceDescriptor(
        source_type="uworld_notes",
        modality="text",
        extraction_style="native_text",
        generation_style="existing_downstream",
        asset_policy="none",
        cache_policy="source_hash",
        notes="High-yield UWorld notes profile (v4.59). Emits normalized text chunks before invoking the existing UWorld generator; the user confirmed UWorld notes are text-only so this source skips all image/table machinery. Default density is ~1 question per 500 chars (roughly 3× Mehlman) because the user's UWorld notes are the densest content in the library.",
        metadata={
            "profileStatus": "active",
            "supportedInputs": [".txt", ".md", ".rtf", ".docx"],
            "downstreamGenerator": "tools/uworld-notes-question-generator/generate_uworld_questions.py",
            "promptPolicy": "unchanged",
            "densityPolicy": "auto-scale --questions-per-file to ~1 question per 500 chars; override via --questions-per-file",
            "assetHandling": "none — text-only source",
        },
    ),
    "anki_notes": SourceDescriptor(
        source_type="anki_notes",
        modality="text",
        extraction_style="native_text",
        generation_style="existing_downstream",
        asset_policy="none",
        cache_policy="source_hash",
        notes="Profile-style Anki plain-text export source. Emits normalized text chunks while preserving card fields, cloze text, tags, and provenance; selected-input dry-run handoff to the existing wrapper and BIC dry-run auto-import are validated in dev and packaged app.",
        metadata={
            "profileStatus": "foundation",
            "supportedInputs": [".txt", ".md"],
            "downstreamGenerator": "tools/anki-question-generator/generate_anki_questions.py",
            "downstreamStatus": "selected-input dry-run handoff validated; live Gemini generation intentionally disabled and semantic question quality unvalidated",
            "promptPolicy": "unchanged",
        },
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
    "mehlman_pdf": SourceDescriptor(
        source_type="mehlman_pdf",
        modality="pdf",
        extraction_style="native_text",
        generation_style="existing_downstream",
        asset_policy="preserve",
        cache_policy="source_hash",
        notes="Profile-style text-heavy PDF source using shared normalized text chunks before invoking the existing Mehlman downstream generator.",
        metadata={
            "profileStatus": "active",
            "downstreamGenerator": "tools/mehlman-pdf-question-generator/generate_mehlman_questions.py",
            "promptPolicy": "unchanged",
            "pageLimitPolicy": "initial validation capped to first 5-10 pages",
            "assetHandling": "preserve embedded figures and lattice-detected tables as normalized refs",
        },
    ),
    "ome_pdf": SourceDescriptor(
        source_type="ome_pdf",
        modality="pdf",
        extraction_style="native_text",
        generation_style="existing_downstream",
        asset_policy="none",
        cache_policy="source_hash",
        notes="OME text-layer PDF profile. Emits normalized text chunks through the existing deterministic OME PDF extraction and chunking path without question generation.",
        metadata={
            "profileStatus": "normalized-chunks-plus-optional-dry-run-handoff",
            "supportedInputs": [".pdf"],
            "downstreamGenerator": "tools/ome-pdf-question-generator/generate_ome_questions.py",
            "downstreamStatus": "shared ingestion validates normalized chunks first; the OME profile runner can optionally hand off one selected PDF to the existing generator in dry-run mode",
            "ocrPolicy": "none; reuse OME native text extraction only",
        },
    ),
    "divine_transcript": SourceDescriptor(
        source_type="divine_transcript",
        modality="text",
        extraction_style="transcript",
        generation_style="deterministic",
        asset_policy="none",
        cache_policy="source_hash",
        notes="Transcript-first Divine shared-ingestion profile. Emits normalized transcript chunks only and does not perform audio ingestion, Gemini invocation, semantic generation, or BIC registration.",
        metadata={
            "profileStatus": "transcript-normalization-only",
            "supportedInputs": [".txt", ".md"],
            "milestoneScope": "transcript-first normalized chunks only",
            "audioIngestion": "not supported",
            "semanticGeneration": "not supported",
            "bicRegistration": "not registered",
            "geminiPolicy": "no Gemini invocation",
        },
    ),
    "images_tables_source": SourceDescriptor(
        source_type="images_tables_source",
        modality="image",
        extraction_style="multimodal_asset",
        generation_style="attachment_first",
        asset_policy="preserve",
        cache_policy="source_hash",
        notes="Image-first and table-first profile source. Emits normalized image/table chunks, preserves assets, and creates lightweight app-ready cards without semantic question generation.",
        metadata={
            "profileStatus": "active",
            "downstreamGenerator": "tools/shared-ingestion/images_tables_profile_runner.py",
            "supportedInputs": [".png", ".jpg", ".jpeg", ".webp", "small folders containing supported images"],
            "assetKinds": ["stem_image", "explanation_image", "table_image", "algorithm", "chart", "unknown"],
            "ocrPolicy": "Use local tesseract when available; otherwise preserve filename-derived text with warning.",
        },
    ),
}


def get_source_descriptor(source_type: str) -> SourceDescriptor:
    try:
        return SOURCE_DESCRIPTORS[source_type]
    except KeyError as exc:
        known = ", ".join(sorted(SOURCE_DESCRIPTORS))
        raise ValueError(f"Unknown source_type: {source_type}. Known source types: {known}") from exc
