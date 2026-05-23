#!/usr/bin/env python3
"""Authoritative execution graph for UOGA jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CHUNK_STATES = {"planned", "running", "retrying", "completed", "dropped"}
ATTEMPT_PHASES = {"initial", "repair", "fallback"}
ATTEMPT_STATUSES = {"success", "failure"}
GRAPH_STATUSES = {"running", "completed", "failed"}


@dataclass
class AttemptEvent:
    attempt_id: int
    phase: str
    status: str
    error: str = ""

    def __post_init__(self) -> None:
        if self.phase not in ATTEMPT_PHASES:
            raise ValueError(f"invalid attempt phase: {self.phase}")
        if self.status not in ATTEMPT_STATUSES:
            raise ValueError(f"invalid attempt status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "attemptId": self.attempt_id,
            "phase": self.phase,
            "status": self.status,
        }
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass
class ChunkNode:
    chunk_id: str
    index: int
    total_chunks: int
    state: str = "planned"
    attempts: list[AttemptEvent] = field(default_factory=list)
    output: dict[str, Any] | None = None
    expected_questions: int = 0
    concept_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state not in CHUNK_STATES:
            raise ValueError(f"invalid chunk state: {self.state}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunkId": self.chunk_id,
            "index": self.index,
            "totalChunks": self.total_chunks,
            "state": self.state,
            "attempts": [attempt.to_dict() for attempt in self.attempts],
            "output": self.output,
            "expectedQuestions": self.expected_questions,
            "conceptIds": list(self.concept_ids),
        }


@dataclass
class ExecutionGraph:
    job_id: str
    chunks: list[ChunkNode]
    global_retry_id: int = 0
    status: str = "running"

    def __post_init__(self) -> None:
        if self.status not in GRAPH_STATUSES:
            raise ValueError(f"invalid graph status: {self.status}")
        total = len(self.chunks)
        seen: set[str] = set()
        for index, chunk in enumerate(self.chunks, start=1):
            if chunk.chunk_id in seen:
                raise ValueError(f"duplicate chunkId: {chunk.chunk_id}")
            seen.add(chunk.chunk_id)
            if chunk.index != index:
                raise ValueError(f"chunk index drift for {chunk.chunk_id}: {chunk.index} != {index}")
            if chunk.total_chunks != total:
                raise ValueError(f"chunk total drift for {chunk.chunk_id}: {chunk.total_chunks} != {total}")

    @property
    def total_chunks(self) -> int:
        return len(self.chunks)

    def get_chunk(self, chunk_id: str) -> ChunkNode:
        for chunk in self.chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        raise KeyError(f"unknown chunkId: {chunk_id}")

    def mark_chunk_state(self, chunk_id: str, state: str, output: dict[str, Any] | None = None) -> None:
        if state not in CHUNK_STATES:
            raise ValueError(f"invalid chunk state: {state}")
        chunk = self.get_chunk(chunk_id)
        chunk.state = state
        if output is not None:
            chunk.output = output
        self._reconcile_status()

    def record_attempt(self, chunk_id: str, phase: str, status: str, error: str = "") -> AttemptEvent:
        chunk = self.get_chunk(chunk_id)
        self.global_retry_id += 1
        attempt = AttemptEvent(self.global_retry_id, phase, status, error)
        chunk.attempts.append(attempt)
        if status == "failure":
            chunk.state = "retrying"
        self._reconcile_status()
        return attempt

    def _reconcile_status(self) -> None:
        if not self.chunks:
            self.status = "completed"
            return
        if all(chunk.state in {"completed", "dropped"} for chunk in self.chunks):
            self.status = "completed"
        elif any(chunk.state == "running" for chunk in self.chunks) or any(chunk.state == "retrying" for chunk in self.chunks):
            self.status = "running"

    def progress(self) -> dict[str, Any]:
        completed = sum(1 for chunk in self.chunks if chunk.state == "completed")
        dropped = sum(1 for chunk in self.chunks if chunk.state == "dropped")
        retrying = sum(1 for chunk in self.chunks if chunk.state == "retrying")
        running = sum(1 for chunk in self.chunks if chunk.state == "running")
        return {
            "completedChunks": completed,
            "droppedChunks": dropped,
            "retryingChunks": retrying,
            "runningChunks": running,
            "totalChunks": self.total_chunks,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "totalChunks": self.total_chunks,
            "chunks": [chunk.to_dict() for chunk in self.chunks],
            "globalRetryId": self.global_retry_id,
            "status": self.status,
            "progress": self.progress(),
        }


def build_execution_graph(job_id: str, chunk_specs: list[dict[str, Any]]) -> ExecutionGraph:
    total = len(chunk_specs)
    chunks = [
        ChunkNode(
            chunk_id=str(spec["chunkId"]),
            index=index,
            total_chunks=total,
            expected_questions=int(spec.get("expectedQuestions") or 0),
            concept_ids=[str(value) for value in (spec.get("conceptIds") or [])],
            output=None,
        )
        for index, spec in enumerate(chunk_specs, start=1)
    ]
    return ExecutionGraph(job_id=job_id, chunks=chunks)
