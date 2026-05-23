#!/usr/bin/env python3
"""Compatibility import for the UOGA telemetry engine."""

from __future__ import annotations

import importlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
module = importlib.import_module(".".join(["core", "uoga", "telemetry_engine"]))

ChunkHeartbeat = module.ChunkHeartbeat
emit_bic_chunk_event = module.emit_bic_chunk_event
safe_display_path = module.safe_display_path
utc_timestamp = module.utc_timestamp
