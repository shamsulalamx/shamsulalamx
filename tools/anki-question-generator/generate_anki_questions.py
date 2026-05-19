#!/usr/bin/env python3
"""
Anki Notes → Step 2 Question Generator
Thin wrapper around the stable UWorld notes pipeline.

Reuses from tools/uworld-notes-question-generator/generate_uworld_questions.py:
  - Gemini calling      - JSON cleaning       - retry logic
  - validation          - repair flow         - app-ready schema
  - duplicate detection - report generation   - dry-run behavior

Overrides only:
  - input/output/report/debug directory paths
  - prompt file
  - sourceFormat label in app-ready output
  - report filename prefix

Usage:
  python3 generate_anki_questions.py --dry-run
  python3 generate_anki_questions.py --generate
  python3 generate_anki_questions.py --generate --questions-per-file 15
"""

import argparse
import os
import sys
import textwrap
import time
from datetime import datetime
from pathlib import Path
from typing import Dict

# ── Import the stable UWorld generator ────────────────────────────────────────
_UW_DIR = Path(__file__).parent.parent / "uworld-notes-question-generator"
if not _UW_DIR.is_dir():
    sys.exit(f"ERROR: UWorld generator not found at expected path: {_UW_DIR}")
sys.path.insert(0, str(_UW_DIR))
import generate_uworld_questions as _uw  # noqa: E402

# ── Patch all path globals to point at Anki workspace ─────────────────────────
_BASE = Path(__file__).parent

_uw.BASE_DIR    = _BASE
_uw.INPUT_DIR   = _BASE / "input_notes"
_uw.RAW_DIR     = _BASE / "output_json" / "raw_text"
_uw.CHUNK_DIR   = _BASE / "output_json" / "chunks"
_uw.GEN_DIR     = _BASE / "output_json" / "generated"
_uw.DEBUG_DIR   = _BASE / "output_json" / "generated" / "debug"
_uw.APP_DIR     = _BASE / "output_json" / "app_ready"
_uw.REPORT_DIR  = _BASE / "reports"
_uw.PROMPT_FILE = _BASE / "prompts" / "anki_notes_to_questions_prompt.txt"

# ── Patch sourceFormat to "anki-notes" ────────────────────────────────────────
_orig_build_app_ready = _uw.build_app_ready_json


def _anki_build_app_ready_json(source_stem, questions, warnings):
    result = _orig_build_app_ready(source_stem, questions, warnings)
    result["sourceFormat"] = "anki-notes"
    return result


_uw.build_app_ready_json = _anki_build_app_ready_json


# ── CLI entry point ────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Anki Notes → Step 2 Question Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python3 generate_anki_questions.py --dry-run
              python3 generate_anki_questions.py --generate
              python3 generate_anki_questions.py --generate --questions-per-file 15
              python3 generate_anki_questions.py --generate --questions-per-file 8
              python3 generate_anki_questions.py --generate --questions-per-file 20
        """),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Gemini calls; produce placeholder app-ready JSON only.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help=(
            "Explicitly run live Gemini generation. "
            "Exits with error if GEMINI_API_KEY is unset (does not silently fall back)."
        ),
    )
    parser.add_argument(
        "--questions-per-file",
        type=int,
        default=15,
        metavar="N",
        help="Target number of questions to generate per input file (default: 15).",
    )
    args = parser.parse_args()

    if args.dry_run and args.generate:
        parser.error("--dry-run and --generate are mutually exclusive.")

    _uw.log("=" * 60)
    _uw.log("Anki Notes → Question Generator")
    _uw.log(f"  Model:              {_uw.GEMINI_MODEL}")
    _uw.log(f"  Dry-run:            {args.dry_run}")
    _uw.log(f"  Generate:           {args.generate}")
    _uw.log(f"  Questions per file: {args.questions_per_file}")
    _uw.log("=" * 60)

    for d in (_uw.RAW_DIR, _uw.CHUNK_DIR, _uw.GEN_DIR, _uw.DEBUG_DIR, _uw.APP_DIR, _uw.REPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)

    files = _uw.discover_input_files()
    if not files:
        _uw.log("No supported input files found in input_notes/")
        _uw.log(f"Supported formats: {', '.join(sorted(_uw.SUPPORTED_EXTENSIONS))}")
        _uw.write_report({"status": "no_input_files", "files": {}}, prefix="anki_generation_report")
        return

    _uw.log(f"Found {len(files)} input file(s): {[f.name for f in files]}")

    dry_run = args.dry_run

    if args.generate:
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            _uw.log("ERROR: --generate requires GEMINI_API_KEY to be set.")
            _uw.log("Set it with: export GEMINI_API_KEY=your_key_here")
            sys.exit(1)
        dry_run = False
    elif not dry_run:
        if not os.environ.get("GEMINI_API_KEY", "").strip():
            _uw.warn("GEMINI_API_KEY is not set — falling back to --dry-run mode.")
            _uw.warn("Pass --generate to treat a missing key as a hard error.")
            dry_run = True

    report_data: Dict = {
        "runTimestamp":     datetime.now().isoformat(),
        "model":            _uw.GEMINI_MODEL,
        "dryRun":           dry_run,
        "questionsPerFile": args.questions_per_file,
        "inputFiles":       [f.name for f in files],
        "files":            {},
    }
    t_total = time.time()

    for filepath in files:
        try:
            _uw.process_file(filepath, args.questions_per_file, dry_run, report_data)
        except Exception as exc:
            _uw.warn(f"Fatal error processing {filepath.name}: {exc}")
            report_data["files"][filepath.name] = {"status": "error", "error": str(exc)}

    report_data["totalElapsedSeconds"] = round(time.time() - t_total, 1)
    _uw.write_report(report_data, prefix="anki_generation_report")
    _uw.log("Done.")


if __name__ == "__main__":
    main()
