#!/usr/bin/env python3
"""Shared review artifact writer for organic generation failures."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


REVIEW_DRAFT_SCHEMA_VERSION = "uoga-review-draft-v1"


def durable_review_dir(job_output_root: str | Path | None = None) -> Path:
    root = Path(job_output_root or os.environ.get("BIC_JOB_OUTPUT_ROOT") or ".").expanduser().resolve()
    return root / "review"


def write_review_draft(
    *,
    job_output_root: str | Path | None = None,
    source_type: str,
    source_file: str,
    candidate_questions: list[dict[str, Any]],
    review_items: list[dict[str, Any]],
    telemetry: dict[str, Any] | None = None,
    filename: str = "review_draft.json",
) -> Path:
    review_dir = durable_review_dir(job_output_root)
    review_dir.mkdir(parents=True, exist_ok=True)
    path = review_dir / filename
    payload = {
        "schemaVersion": REVIEW_DRAFT_SCHEMA_VERSION,
        "sourceType": source_type,
        "sourceFile": source_file,
        "candidateQuestions": candidate_questions,
        "reviewItems": review_items,
        "telemetry": telemetry or {},
    }
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path
