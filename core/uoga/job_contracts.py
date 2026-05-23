#!/usr/bin/env python3
"""Shared job contracts for organic generation pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OrganicPhase(str, Enum):
    LOAD_INPUT = "load_input"
    BUILD_CONCEPT_GRAPH = "build_concept_graph"
    PLANNING = "planning"
    GENERATING = "generating"
    REPAIRING = "repairing"
    VALIDATING = "validating"
    FINALIZING = "finalizing"


class PipelineRoute(str, Enum):
    ORGANIC_GENERATION = "organic_generation"
    EXTRACTIVE_TRANSFORMATION = "extractive_transformation"
    VISION_ANNOTATION = "vision_annotation"


class ExecutionMode(str, Enum):
    UOGA = "uoga_v6"
    LEGACY = "legacy"


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


def require_uoga_graph_native(source_type: str, *, operation: str) -> None:
    mode = determine_execution_mode(source_type)
    if mode != ExecutionMode.UOGA:
        raise ValueError(f"{operation} requires UOGA graph-native mode; sourceType={source_type!r} mode={mode.value}")


def require_organic_route(source_type: str, *, operation: str) -> None:
    require_uoga_graph_native(source_type, operation=operation)


class ChunkEventType(str, Enum):
    CHUNK_PLAN = "CHUNK_PLAN"
    CHUNK_START = "CHUNK_START"
    CHUNK_HEARTBEAT = "CHUNK_HEARTBEAT"
    CHUNK_SUCCESS = "CHUNK_SUCCESS"
    CHUNK_DROP = "CHUNK_DROP"
    JOB_COMPLETE = "JOB_COMPLETE"
    STALL_WARNING = "STALL_WARNING"


TERMINAL_CHUNK_EVENTS = {
    ChunkEventType.CHUNK_SUCCESS.value,
    ChunkEventType.CHUNK_DROP.value,
}


@dataclass
class ChunkPlanItem:
    chunk_label: str
    chunk_index: int
    total_chunks: int
    expected_questions: int = 0
    concept_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkAccounting:
    expected_questions: int
    accepted: int = 0
    reviewed: int = 0
    dropped: int = 0
    overflow: int = 0
    underflow: int = 0

    def accounted(self) -> int:
        return self.accepted + self.reviewed + self.dropped

    def mismatch(self) -> int:
        return self.expected_questions - self.accounted()

    def to_dict(self) -> dict[str, Any]:
        return {
            "expectedQuestions": self.expected_questions,
            "accepted": self.accepted,
            "reviewed": self.reviewed,
            "dropped": self.dropped,
            "overflow": self.overflow,
            "underflow": self.underflow,
            "accounted": self.accounted(),
            "mismatch": self.mismatch(),
        }


def require_chunk_event_fields(event: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    event_type = str(event.get("event") or event.get("chunkEvent") or "")
    required = ["jobId", "phase"]
    if event_type in {
        ChunkEventType.CHUNK_PLAN.value,
        ChunkEventType.CHUNK_START.value,
        ChunkEventType.CHUNK_SUCCESS.value,
        ChunkEventType.CHUNK_DROP.value,
    } and "executionGraph" not in event:
        missing.append("executionGraph")
    if event_type not in {ChunkEventType.CHUNK_PLAN.value, ChunkEventType.JOB_COMPLETE.value}:
        required.extend(["chunkIndex", "totalChunks", "globalRetryId", "retryPhase"])
    for key in required:
        if key not in event:
            missing.append(key)
    return missing
