#!/usr/bin/env python3
"""Shared validation/accounting helpers for organic generation."""

from __future__ import annotations

from typing import Any

from .job_contracts import ChunkAccounting, require_organic_route


def reconcile_cardinality(expected_questions: int, accepted: int, reviewed: int, dropped: int, returned: int | None = None, *, source_type: str = "organic_generation") -> dict[str, Any]:
    require_organic_route(source_type, operation="generation cardinality reconciliation")
    accounting = ChunkAccounting(
        expected_questions=max(0, int(expected_questions or 0)),
        accepted=max(0, int(accepted or 0)),
        reviewed=max(0, int(reviewed or 0)),
        dropped=max(0, int(dropped or 0)),
    )
    if returned is not None:
        returned_count = max(0, int(returned or 0))
        accounting.overflow = max(0, returned_count - accounting.expected_questions)
        accounting.underflow = max(0, accounting.expected_questions - returned_count)
    return accounting.to_dict()
