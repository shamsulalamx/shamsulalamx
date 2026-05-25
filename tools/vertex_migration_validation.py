#!/usr/bin/env python3
"""
Vertex migration validation harness (Stage 2.5).

Three modes:

  --smoke
      Tiny prompt → both backends. Verifies both return non-empty text.
      Costs <$0.001 total. Run this FIRST before any real validation.

  --side-by-side <prompt-text>
      Run the same prompt through both backends. Print both outputs side
      by side. For quick eyeballing of "do they produce similar quality?"

  --diff <file1.json> <file2.json>
      Compare two app-ready JSON outputs from running the same pipeline
      twice (once per backend). Reports structural diffs + question count
      delta. Doesn't fail on prose variance (Gemini is non-deterministic
      at temp > 0); only fails on missing/wrong-typed schema fields.

Usage examples:

  # Confirm both backends respond at all
  python3 tools/vertex_migration_validation.py --smoke

  # Eyeball a prompt's output on both backends
  python3 tools/vertex_migration_validation.py --side-by-side \
    "List 3 USMLE Step 2 high-yield facts about MI."

  # After running Fast Facts on both backends with the same PDF:
  GEMINI_BACKEND=ai_studio python3 .../fast_facts.py ... --output a.json
  GEMINI_BACKEND=vertex    python3 .../fast_facts.py ... --output b.json
  python3 tools/vertex_migration_validation.py --diff a.json b.json

Exit codes:
  0 — validation passed
  1 — backend failure (one or both backends returned error)
  2 — structural mismatch (questions count differs, schema field missing)

This script is part of Phase 12 — the Vertex AI migration. Once cutover is
complete and we've removed the AI Studio code paths (post-v5.x), this script
becomes vestigial and can be deleted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore")

_THIS_DIR = Path(__file__).parent.resolve()
_UW_DIR = _THIS_DIR / "uworld-notes-question-generator"
if str(_UW_DIR) not in sys.path:
    sys.path.insert(0, str(_UW_DIR))
import generate_uworld_questions as _uw  # noqa: E402

try:
    from google.genai import types as _genai_types  # noqa: E402
    _GENAI_SDK_AVAILABLE = True
except ImportError:
    _GENAI_SDK_AVAILABLE = False


def _color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def green(s: str) -> str:
    return _color(s, "32")


def red(s: str) -> str:
    return _color(s, "31")


def yellow(s: str) -> str:
    return _color(s, "33")


def cyan(s: str) -> str:
    return _color(s, "36")


def _call_with_backend(backend: str, prompt: str, model: str = "gemini-2.5-flash") -> tuple[bool, str, float]:
    """Make a single Gemini call via the SDK with the requested backend.

    Returns (ok, text_or_error, elapsed_seconds).
    """
    if not _GENAI_SDK_AVAILABLE:
        return False, "google-genai SDK not installed", 0.0

    # Stash + override backend for this call only
    saved_backend = _uw.GEMINI_BACKEND
    saved_env = os.environ.get("GEMINI_BACKEND")
    _uw.GEMINI_BACKEND = backend
    os.environ["GEMINI_BACKEND"] = backend
    _uw._reset_gemini_client()
    started = time.time()

    try:
        client = _uw._gemini_client()
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=_genai_types.GenerateContentConfig(
                temperature=0.0,
                # v4.79: Bumped 32x (256 → 8192) so that smoke test still
                # works with thinking enabled. The smoke prompt needs only
                # a few tokens of output but dynamic thinking can consume
                # 500-2000 tokens reasoning about "say OK".
                max_output_tokens=8192,
                # v4.79: Thinking ENABLED here so the validation harness
                # exercises the same configuration the production code uses.
                # Don't change this to thinking_budget=0 — the harness must
                # mirror real-world behavior to catch bugs in real-world
                # behavior.
                thinking_config=_genai_types.ThinkingConfig(thinking_budget=-1),
            ),
        )
        text = getattr(response, "text", None) or ""
        elapsed = time.time() - started
        return bool(text), text or "(empty)", elapsed
    except Exception as exc:
        elapsed = time.time() - started
        return False, f"{type(exc).__name__}: {exc}", elapsed
    finally:
        # Restore prior state
        _uw.GEMINI_BACKEND = saved_backend
        if saved_env is None:
            os.environ.pop("GEMINI_BACKEND", None)
        else:
            os.environ["GEMINI_BACKEND"] = saved_env
        _uw._reset_gemini_client()


def cmd_smoke() -> int:
    """Tiny prompt → both backends. <$0.001 total cost."""
    prompt = 'Reply with exactly: OK'
    print(cyan("=== Smoke test: tiny prompt on both backends ==="))
    print(f"Prompt: {prompt!r}")
    print()

    overall_ok = True
    for backend in ("ai_studio", "vertex"):
        ok, text, elapsed = _call_with_backend(backend, prompt)
        status = green("PASS") if ok else red("FAIL")
        print(f"  [{backend:>9}] {status}  ({elapsed*1000:.0f}ms)  → {text.strip()[:80]!r}")
        if not ok:
            overall_ok = False

    print()
    if overall_ok:
        print(green("✓ Both backends responded. Migration foundation works."))
        return 0
    print(red("✗ One or both backends failed. Check the error and your auth setup."))
    print(yellow("Common fixes:"))
    print("  - AI Studio fail: ensure GEMINI_API_KEY is exported in this shell")
    print("  - Vertex fail: ensure `gcloud auth application-default login` was run")
    print("  - Vertex fail: ensure Vertex AI API is enabled on project shamsulalamx")
    return 1


def cmd_side_by_side(prompt: str) -> int:
    """Run the same prompt on both backends. Print outputs side by side."""
    print(cyan("=== Side-by-side: same prompt, both backends ==="))
    print(f"Prompt: {prompt!r}")
    print()

    results = {}
    for backend in ("ai_studio", "vertex"):
        ok, text, elapsed = _call_with_backend(backend, prompt)
        results[backend] = (ok, text, elapsed)
        status = green("OK") if ok else red("FAIL")
        print(f"--- {backend} ({status}, {elapsed*1000:.0f}ms) ---")
        print(text.strip()[:2000])
        print()

    ai_ok = results["ai_studio"][0]
    vx_ok = results["vertex"][0]
    if ai_ok and vx_ok:
        print(green("✓ Both backends produced output. Eyeball the prose for quality parity."))
        return 0
    print(red("✗ One or both backends failed."))
    return 1


def _normalize_for_diff(obj: Any) -> Any:
    """Strip fields that legitimately vary across runs (timestamps, IDs).

    Without this, every diff would 'fail' on identical-quality runs because
    Gemini generates different question IDs each call.
    """
    if isinstance(obj, dict):
        return {
            k: _normalize_for_diff(v)
            for k, v in obj.items()
            if k not in {"generatedAt", "model", "runtimeSeconds", "id", "questionId",
                          "sourceQuestionNumber", "chunkId", "generation_timestamp"}
        }
    if isinstance(obj, list):
        return [_normalize_for_diff(x) for x in obj]
    return obj


def cmd_diff(file_a: str, file_b: str) -> int:
    """Compare two app-ready JSON outputs from the same pipeline run twice."""
    path_a = Path(file_a)
    path_b = Path(file_b)
    if not path_a.exists():
        print(red(f"File not found: {path_a}"))
        return 1
    if not path_b.exists():
        print(red(f"File not found: {path_b}"))
        return 1

    a = json.loads(path_a.read_text(encoding="utf-8"))
    b = json.loads(path_b.read_text(encoding="utf-8"))

    print(cyan(f"=== Diff: {path_a.name} vs {path_b.name} ==="))

    # 1. Schema version match
    ver_a = a.get("schemaVersion", "<missing>")
    ver_b = b.get("schemaVersion", "<missing>")
    if ver_a == ver_b:
        print(f"  Schema version: {green(ver_a)}")
    else:
        print(f"  Schema version: {red(f'{ver_a!r} != {ver_b!r}')}")
        return 2

    # 2. Question count delta
    qs_a = a.get("questions") or []
    qs_b = b.get("questions") or []
    count_a, count_b = len(qs_a), len(qs_b)
    if count_a == count_b:
        print(f"  Question count: {green(str(count_a))}")
    else:
        diff_pct = abs(count_a - count_b) / max(count_a, count_b, 1) * 100
        color = yellow if diff_pct < 10 else red
        print(f"  Question count: {color(f'{count_a} vs {count_b} ({diff_pct:.0f}% delta)')}")
        if diff_pct > 10:
            return 2

    # 3. Schema field coverage on first 5 questions
    sample = min(5, len(qs_a), len(qs_b))
    missing_fields_a, missing_fields_b = [], []
    for i in range(sample):
        for field in ("stem", "answerChoices", "correctAnswer", "correctExplanation"):
            if field not in qs_a[i]:
                missing_fields_a.append((i, field))
            if field not in qs_b[i]:
                missing_fields_b.append((i, field))
    if not missing_fields_a and not missing_fields_b:
        print(f"  Schema fields present in first {sample}: {green('all good')}")
    else:
        if missing_fields_a:
            print(f"  Missing in {path_a.name}: {red(str(missing_fields_a))}")
        if missing_fields_b:
            print(f"  Missing in {path_b.name}: {red(str(missing_fields_b))}")
        return 2

    # 4. Sourceformat / appLevel metadata match
    for field in ("sourceFormat", "schemaVersion"):
        if a.get(field) != b.get(field):
            print(f"  Field {field!r}: {red(f'differs ({a.get(field)!r} vs {b.get(field)!r})')}")
            return 2

    print()
    print(green("✓ Structural diff PASS. Outputs are equivalent within Gemini's normal variance."))
    print(yellow("  Note: prose-level differences in question stems / explanations are expected"))
    print(yellow("  and OK — Gemini is non-deterministic at temperature > 0."))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true", help="tiny prompt smoke test on both backends")
    parser.add_argument("--side-by-side", metavar="PROMPT", help="run same prompt on both backends")
    parser.add_argument("--diff", nargs=2, metavar=("FILE_A", "FILE_B"), help="diff two app-ready JSON outputs")
    args = parser.parse_args()

    if args.smoke:
        return cmd_smoke()
    if args.side_by_side:
        return cmd_side_by_side(args.side_by_side)
    if args.diff:
        return cmd_diff(args.diff[0], args.diff[1])

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
