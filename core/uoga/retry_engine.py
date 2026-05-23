#!/usr/bin/env python3
"""Shared bounded retry authority for organic generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .execution_graph import ExecutionGraph
from .job_contracts import require_organic_route


@dataclass(frozen=True)
class RetryStep:
    global_retry_id: int
    retry_phase: str

    @property
    def attempt(self) -> int:
        return self.global_retry_id

    @property
    def fallback_mode(self) -> str:
        return self.retry_phase


DEFAULT_RETRY_PLAN = (
    RetryStep(1, "initial"),
    RetryStep(2, "repair"),
    RetryStep(3, "fallback"),
)


@dataclass(frozen=True)
class RetryContext:
    source_type: str = "organic_generation"
    chunk_label: str = ""
    chunk_id: str = ""
    execution_graph: ExecutionGraph | None = None
    metadata: dict[str, Any] | None = None
    retry_plan: tuple[RetryStep, ...] = DEFAULT_RETRY_PLAN


class RetryExhaustedError(Exception):
    def __init__(self, context: RetryContext, last_error: Exception | None) -> None:
        self.context = context
        self.last_error = last_error
        super().__init__(str(last_error) if last_error else "retry exhausted")


def execute(
    task: Callable[[RetryStep], Any],
    context: RetryContext,
    *,
    on_retry: Callable[[RetryStep, Exception], None] | None = None,
) -> Any:
    require_organic_route(context.source_type, operation="generation retry")
    if context.execution_graph is None or not context.chunk_id:
        raise ValueError("generation retry requires ExecutionGraph and chunk_id in UOGA mode")
    last_error: Exception | None = None
    for step in context.retry_plan:
        if context.execution_graph and context.chunk_id:
            state = "running" if step.retry_phase == "initial" else "retrying"
            context.execution_graph.mark_chunk_state(context.chunk_id, state)
        try:
            result = task(step)
            if context.execution_graph and context.chunk_id:
                context.execution_graph.record_attempt(context.chunk_id, step.retry_phase, "success")
            return result
        except Exception as exc:
            last_error = exc
            if context.execution_graph and context.chunk_id:
                context.execution_graph.record_attempt(context.chunk_id, step.retry_phase, "failure", str(exc))
            if on_retry and step != context.retry_plan[-1]:
                on_retry(step, exc)
    raise RetryExhaustedError(context, last_error)


def bounded_retry(
    operation: Callable[[RetryStep], Any],
    *,
    source_type: str = "organic_generation",
    retry_plan: tuple[RetryStep, ...] = DEFAULT_RETRY_PLAN,
    on_retry: Callable[[RetryStep, Exception], None] | None = None,
) -> Any:
    return execute(
        operation,
        RetryContext(source_type=source_type, retry_plan=retry_plan),
        on_retry=on_retry,
    )
