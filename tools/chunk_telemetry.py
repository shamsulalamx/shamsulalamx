#!/usr/bin/env python3
"""Shared chunk telemetry helpers for Batch Import generators."""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any, Callable


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_bic_chunk_event(event_type: str, *, message: str = "", **payload: Any) -> dict[str, Any]:
    event = {
        "event": event_type,
        "phase": payload.get("phase") or "generating",
        "timestamp": utc_timestamp(),
        "jobId": str(os.environ.get("BIC_JOB_ID") or payload.get("jobId") or ""),
        **payload,
    }
    progress_source = str(payload.get("source") or os.environ.get("BIC_PROGRESS_SOURCE") or "").strip()
    if progress_source:
        bic_payload = {
            "phase": event.get("phase") or "generating",
            "source": progress_source,
            "message": message or event_type,
            "chunkEvent": event_type,
            **event,
        }
        print("BIC_PROGRESS " + json.dumps(bic_payload, ensure_ascii=False), flush=True)
    return event


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
        retry_attempt: int,
        interval_seconds: float = 3.0,
        stall_seconds: float = 25.0,
    ) -> None:
        self.emit = emit
        self.job_id = job_id
        self.chunk_label = chunk_label
        self.chunk_index = chunk_index
        self.total_chunks = total_chunks
        self.phase = phase
        self.retry_attempt = retry_attempt
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
        return {
            "jobId": self.job_id,
            "chunkLabel": self.chunk_label,
            "chunkIndex": self.chunk_index,
            "totalChunks": self.total_chunks,
            "phase": self.phase,
            "elapsedMs": int((time.time() - self.started_at) * 1000),
            "retryAttempt": self.retry_attempt,
        }

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            payload = self._payload()
            self._last_event = self.emit("CHUNK_HEARTBEAT", **payload)
            if not self._stall_emitted and payload["elapsedMs"] >= int(self.stall_seconds * 1000):
                self.emit(
                    "STALL_WARNING",
                    **payload,
                    lastEvent=self._last_event,
                    chunkState={
                        "chunkLabel": self.chunk_label,
                        "chunkIndex": self.chunk_index,
                        "totalChunks": self.total_chunks,
                        "phase": self.phase,
                    },
                    retryCount=self.retry_attempt,
                )
                self._stall_emitted = True
