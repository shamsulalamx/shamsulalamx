#!/usr/bin/env python3
"""Audit gate for v5-generated NBME-style question sets.

Run AFTER `v5_pipeline.py` produces a questions JSON. Reports:

  - Answer-position distribution across A/B/C/D/E
  - Question-order distribution (first/second/third)
  - Difficulty distribution (easy/medium/difficult)
  - Stem length distribution
  - Distractor quality signals
  - Critic verdict distribution

Exits 0 when every gate is within tolerance; exits 2 otherwise.

Usage:
    python3 v5_audit.py <questions_json> [--strict]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

# Gates (matched to the targets in v5_pipeline.py)
ANSWER_POSITION_TARGET = {p: 0.20 for p in "ABCDE"}
ANSWER_POSITION_BAND = (0.14, 0.26)  # for batches >= 20

ORDER_TARGET = {"first_order": 0.25, "second_order": 0.45, "third_order": 0.30}
ORDER_BAND = 0.08  # absolute deviation tolerance per bucket
DIFFICULTY_TARGET = {"easy": 0.30, "medium": 0.45, "difficult": 0.25}
DIFFICULTY_BAND = 0.10

STEM_MIN_AVG_CHARS = 600  # NBME-style averaged minimum
STEM_NO_TRIVIA_FRACTION = 0.90  # >=90% of stems must be > 350 chars


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="Path to a v5-generated questions JSON")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero on any gate failure")
    args = ap.parse_args()

    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    qs = payload.get("questions", []) or []
    n = len(qs)
    if n == 0:
        print("No questions to audit.")
        return 2

    print(f"=== v5 audit · {n} questions · {args.path} ===")

    failures: list[str] = []

    # 1. Answer position
    pos = Counter(q.get("correctAnswer", "") for q in qs)
    print("\n[1] Answer position distribution:")
    for p in "ABCDE":
        share = pos.get(p, 0) / n
        flag = ""
        if n >= 20:
            lo, hi = ANSWER_POSITION_BAND
            if share < lo or share > hi:
                flag = f"  ← FAIL (target band {lo:.0%}-{hi:.0%})"
                failures.append(f"answer_position_{p}")
        print(f"  {p}: {pos.get(p, 0):3d} ({share*100:5.1f}%) {flag}")

    # 2. Order distribution
    print("\n[2] Question order distribution:")
    orders = Counter()
    for q in qs:
        meta = q.get("_v5") or {}
        achieved = meta.get("orderAchieved") or meta.get("targetOrder") or "unknown"
        orders[achieved] += 1
    for k in ("first_order", "second_order", "third_order"):
        share = orders.get(k, 0) / n
        target = ORDER_TARGET.get(k, 0)
        delta = abs(share - target)
        flag = "  ← FAIL" if delta > ORDER_BAND else ""
        if flag:
            failures.append(f"order_{k}")
        print(f"  {k}: {orders.get(k, 0):3d} ({share*100:5.1f}%, target {target*100:.0f}%, Δ {delta*100:+.1f}%){flag}")
    other = sum(v for k, v in orders.items() if k not in ORDER_TARGET)
    if other:
        print(f"  other / unknown: {other}")

    # 3. Difficulty distribution
    print("\n[3] Difficulty distribution:")
    diffs = Counter()
    for q in qs:
        meta = q.get("_v5") or {}
        achieved = meta.get("difficultyAchieved") or meta.get("targetDifficulty") or "unknown"
        diffs[achieved] += 1
    for k in ("easy", "medium", "difficult"):
        share = diffs.get(k, 0) / n
        target = DIFFICULTY_TARGET.get(k, 0)
        delta = abs(share - target)
        flag = "  ← FAIL" if delta > DIFFICULTY_BAND else ""
        if flag:
            failures.append(f"difficulty_{k}")
        print(f"  {k}: {diffs.get(k, 0):3d} ({share*100:5.1f}%, target {target*100:.0f}%, Δ {delta*100:+.1f}%){flag}")
    other = sum(v for k, v in diffs.items() if k not in DIFFICULTY_TARGET)
    if other:
        print(f"  other / unknown: {other}")

    # 4. Stem length
    print("\n[4] Stem length:")
    stem_lens = [len(q.get("stem", "")) for q in qs]
    avg = sum(stem_lens) / n
    median = statistics.median(stem_lens)
    short = sum(1 for L in stem_lens if L < 350)
    long_enough = sum(1 for L in stem_lens if L >= 600)
    print(f"  avg: {avg:.0f}  median: {median:.0f}  min: {min(stem_lens)}  max: {max(stem_lens)}")
    print(f"  short (<350 chars): {short}/{n}")
    print(f"  NBME-length (>=600): {long_enough}/{n}")
    if avg < STEM_MIN_AVG_CHARS:
        failures.append("stem_avg_too_short")
        print(f"  ← FAIL: average below {STEM_MIN_AVG_CHARS} chars")
    flagged_short = (short / n) > (1 - STEM_NO_TRIVIA_FRACTION)
    if flagged_short:
        failures.append("too_many_short_stems")
        print(f"  ← FAIL: more than {(1 - STEM_NO_TRIVIA_FRACTION)*100:.0f}% of stems are short")

    # 5. Distractor checks
    print("\n[5] Distractor quality:")
    five_choice = sum(1 for q in qs if len(q.get("answerChoices", [])) == 5)
    fewer = sum(1 for q in qs if len(q.get("answerChoices", [])) < 5)
    print(f"  exactly 5 choices: {five_choice}/{n}")
    print(f"  fewer than 5 choices: {fewer}/{n}")
    if fewer > n * 0.05:
        failures.append("too_many_fewer_than_5_choices")
        print("  ← FAIL: >5% questions have <5 choices")

    # 6. Critic verdict
    print("\n[6] Critic verdicts:")
    verdicts = Counter()
    for q in qs:
        verdicts[(q.get("_v5") or {}).get("criticVerdict") or "unknown"] += 1
    for k, v in verdicts.most_common():
        print(f"  {k}: {v}")

    print()
    if failures:
        print(f"FAILED gates: {failures}")
        return 2 if args.strict else 0
    print("All gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
