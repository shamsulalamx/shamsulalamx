#!/usr/bin/env python3
"""Deterministic UOGA job finalization gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .execution_graph import ExecutionGraph
from .job_contracts import ChunkEventType, OrganicPhase


@dataclass
class JobContext:
    state: str = "running"
    active_tasks: int = 0
    final_state_path: str | Path | None = None
    stop_callbacks: list[Callable[[], None]] = field(default_factory=list)

    def has_active_tasks(self) -> bool:
        return self.active_tasks > 0

    def stop_runtime_loops(self) -> None:
        for callback in list(self.stop_callbacks):
            callback()


def finalize_job_gate(
    execution_graph: ExecutionGraph,
    job_context: JobContext,
    emit_event: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    progress = execution_graph.progress()
    terminal_chunks = execution_graph.terminal_chunks()
    if terminal_chunks != execution_graph.total_chunks:
        return None
    if execution_graph.has_active_tasks() or job_context.has_active_tasks():
        return None
    if execution_graph.job_complete_emitted:
        return None

    job_context.stop_runtime_loops()
    job_context.state = "completed"
    reconciliation = execution_graph.finalize_reconciliation()
    execution_graph.job_complete_emitted = True
    final_state_path = execution_graph.persist_final_state(job_context.final_state_path)
    event = emit_event(
        ChunkEventType.JOB_COMPLETE.value,
        jobId=execution_graph.job_id,
        totalChunks=execution_graph.total_chunks,
        completedChunks=terminal_chunks,
        finalizedChunks=progress["completedChunks"],
        droppedChunks=progress["droppedChunks"],
        status="completed",
        phase=OrganicPhase.FINALIZING.value,
        finalReconciliation=reconciliation,
        finalStatePath=final_state_path,
        executionGraph=execution_graph.to_dict(),
    )
    return event
