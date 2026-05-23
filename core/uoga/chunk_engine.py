#!/usr/bin/env python3
"""Shared chunk planning helpers for organic generation."""

from __future__ import annotations

from typing import Any, Iterable

from .job_contracts import ChunkPlanItem, require_organic_route


def chunk_list(items: list[Any], size: int) -> list[list[Any]]:
    safe_size = max(1, int(size or 1))
    return [items[index:index + safe_size] for index in range(0, len(items), safe_size)]


def build_chunk_plan(items: Iterable[Any], *, chunk_size: int, label_prefix: str = "chunk", source_type: str = "organic_generation") -> list[ChunkPlanItem]:
    require_organic_route(source_type, operation="chunk planning")
    chunks = chunk_list(list(items), chunk_size)
    total = len(chunks)
    plan: list[ChunkPlanItem] = []
    for index, chunk in enumerate(chunks, start=1):
        expected = 0
        concept_ids: list[str] = []
        for item in chunk:
            if isinstance(item, dict):
                expected += int(item.get("questionCount") or item.get("expectedQuestions") or 0)
                concept_id = item.get("slideId") or item.get("conceptId") or item.get("id")
                if concept_id:
                    concept_ids.append(str(concept_id))
        plan.append(ChunkPlanItem(
            chunk_label=f"{label_prefix}{index}",
            chunk_index=index,
            total_chunks=total,
            expected_questions=expected,
            concept_ids=concept_ids,
            metadata={"items": chunk},
        ))
    return plan
