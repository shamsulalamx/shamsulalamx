#!/usr/bin/env python3
"""Shared append-only telemetry engine for organic generation."""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .job_contracts import (
    ChunkEventType,
    ExecutionMode,
    OrganicPhase,
    PipelineRoute,
    classify_pipeline_route,
    determine_execution_mode,
    require_chunk_event_fields,
)


UOGA_TELEMETRY_EVENTS = {
    ChunkEventType.CHUNK_PLAN.value,
    ChunkEventType.CHUNK_START.value,
    ChunkEventType.CHUNK_HEARTBEAT.value,
    ChunkEventType.CHUNK_SUCCESS.value,
    ChunkEventType.CHUNK_DROP.value,
    ChunkEventType.JOB_COMPLETE.value,
    ChunkEventType.STALL_WARNING.value,
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_display_path(path: str | Path, root: str | Path | None = None) -> str:
    resolved = Path(path).expanduser().resolve()
    if root:
        try:
            return str(resolved.relative_to(Path(root).expanduser().resolve()))
        except ValueError:
            return str(resolved)
    return str(resolved)


class TelemetryEmitter:
    def __init__(
        self,
        *,
        source: str = "",
        job_id: str = "",
        progress_prefix: str = "BIC_PROGRESS ",
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.source = source or str(os.environ.get("BIC_PROGRESS_SOURCE") or "")
        self.job_id = job_id or str(os.environ.get("BIC_JOB_ID") or "")
        self.progress_prefix = progress_prefix
        self.event_sink = event_sink
        self.route = classify_pipeline_route(self.source) if self.source else PipelineRoute.EXTRACTIVE_TRANSFORMATION

    def emit(self, event_type: str | ChunkEventType, *, message: str = "", **payload: Any) -> dict[str, Any]:
        event_name = event_type.value if isinstance(event_type, ChunkEventType) else str(event_type)
        source = payload.pop("source", self.source)
        route = classify_pipeline_route(str(source or ""))
        mode = determine_execution_mode(str(source or ""))
        uoga_event = event_name in UOGA_TELEMETRY_EVENTS
        if mode != ExecutionMode.UOGA and uoga_event:
            raise ValueError(f"{event_name} is restricted to organic generation telemetry; sourceType={source!r} route={route.value}")
        if uoga_event and payload.get("executionGraph") is None:
            return {}
        event = {
            "event": event_name,
            "chunkEvent": event_name,
            "phase": payload.pop("phase", OrganicPhase.GENERATING.value),
            "timestamp": utc_timestamp(),
            "jobId": str(payload.pop("jobId", self.job_id) or ""),
            "source": source,
            "route": route.value,
            **payload,
        }
        missing = require_chunk_event_fields(event)
        if uoga_event and missing:
            raise ValueError(f"{event_name} missing required UOGA field(s): {', '.join(missing)}")
        if self.event_sink:
            self.event_sink(event)
        if event["source"]:
            bic_payload = {
                "phase": event["phase"],
                "source": event["source"],
                "message": message or event_name,
                **event,
            }
            print(self.progress_prefix + json.dumps(bic_payload, ensure_ascii=False), flush=True)
        return event


def emit_bic_chunk_event(event_type: str, *, message: str = "", **payload: Any) -> dict[str, Any]:
    return TelemetryEmitter(source=str(payload.get("source") or "")).emit(event_type, message=message, **payload)


class ChunkHeartbeat(AbstractContextManager["ChunkHeartbeat"]):
    def __init__(
        self,
        emit: Callable[..., dict[str, Any]],
        *,
        job_id: str = "",
        chunk_label: str,
        chunk_index: int,
        total_chunks: int,
        phase: str,
        retry_attempt: int | None = None,
        global_retry_id: int | None = None,
        retry_phase: str = "initial",
        execution_graph: dict[str, Any] | None = None,
        interval_seconds: float = 3.0,
        stall_seconds: float = 25.0,
    ) -> None:
        self.emit = emit
        self.job_id = job_id
        self.chunk_label = chunk_label
        self.chunk_index = chunk_index
        self.total_chunks = total_chunks
        self.phase = phase
        self.global_retry_id = int(global_retry_id if global_retry_id is not None else retry_attempt if retry_attempt is not None else 1)
        self.retry_phase = retry_phase
        self.execution_graph = execution_graph
        self.interval_seconds = max(0.5, float(interval_seconds or 3.0))
        self.stall_seconds = max(self.interval_seconds, float(stall_seconds or 25.0))
        self.started_at = time.time()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_event: dict[str, Any] | None = None
        self._stall_emitted = False

    def __enter__(self) -> "ChunkHeartbeat":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _payload(self) -> dict[str, Any]:
        payload = {
            "jobId": self.job_id,
            "chunkLabel": self.chunk_label,
            "chunkIndex": self.chunk_index,
            "totalChunks": self.total_chunks,
            "phase": self.phase,
            "elapsedMs": int((time.time() - self.started_at) * 1000),
            "globalRetryId": self.global_retry_id,
            "retryPhase": self.retry_phase,
        }
        if self.execution_graph is not None:
            payload["executionGraph"] = self.execution_graph
        return payload

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            payload = self._payload()
            self._last_event = self.emit(ChunkEventType.CHUNK_HEARTBEAT.value, **payload)
            if not self._stall_emitted and payload["elapsedMs"] >= int(self.stall_seconds * 1000):
                self.emit(
                    ChunkEventType.STALL_WARNING.value,
                    **payload,
                    lastEvent=self._last_event,
                    chunkState={
                        "chunkLabel": self.chunk_label,
                        "chunkIndex": self.chunk_index,
                        "totalChunks": self.total_chunks,
                        "phase": self.phase,
                    },
                    retryCount=self.global_retry_id,
                )
                self._stall_emitted = True
