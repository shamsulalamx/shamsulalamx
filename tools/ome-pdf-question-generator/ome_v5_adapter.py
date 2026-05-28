#!/usr/bin/env python3
"""OME-PDF → v5.2 allocation adapter — backward-compat thin shim.

The original adapter logic lived here from v5.3 through v5.7. In v5.8
it was promoted to `tools/shared-ingestion/v5_uworld_family_adapter.py`
so the four new Group B sources (UWorld notes, Mehlman PDF, Anki notes,
Divine podcast transcripts) could share it without copy-paste drift.

This file now just re-exports the shared API under the original names
so `generate_ome_questions.py` and any other OME-side caller keeps
working unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Locate the shared adapter. tools/ome-pdf-question-generator/ is the
# parent of this file; the shared module lives at
# tools/shared-ingestion/v5_uworld_family_adapter.py.
_SHARED_DIR = Path(__file__).resolve().parent.parent / "shared-ingestion"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from v5_uworld_family_adapter import (  # noqa: E402
    MIN_CHUNK_CHARS_FOR_V5,
    build_slide_context,
    build_v5_allocations,
    decorate_v5_questions_for_ome,            # backward-compat alias
    decorate_v5_questions_for_uworld_family,  # new generic name
    distribute_question_count,
    extract_terms,
)

__all__ = [
    "MIN_CHUNK_CHARS_FOR_V5",
    "build_slide_context",
    "build_v5_allocations",
    "decorate_v5_questions_for_ome",
    "decorate_v5_questions_for_uworld_family",
    "distribute_question_count",
    "extract_terms",
]
