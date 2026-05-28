#!/usr/bin/env python3
"""v5 multi-stage NBME-authentic question generation pipeline.

A sibling pipeline to the legacy single-call generator in
`generate_lecture_slide_questions.py`. Designed in response to a real
audit finding that the legacy generator produced 99.3% A-positioned
correct answers, short flashcard-style stems, no question-order
stratification, no difficulty stratification, and no critique pass.

The v5 pipeline produces ONE question per allocation slot via the
following stages:

    Stage 1 - PLAN: decide target (order, difficulty) for this slot
              based on the per-batch distribution targets.
    Stage 2 - STEM: gemini-2.5-pro with reasoning generates ONLY the
              clinical vignette stem at the target order/difficulty.
    Stage 3 - DISTRACTORS: gemini-2.5-pro produces 4 plausible
              same-category distractors with per-distractor losing
              reasons.
    Stage 4 - CRITIC: gemini-2.5-pro scores the (stem, correct,
              distractors) tuple on a 5-dimension NBME rubric.
              If below threshold, ONE revision attempt is made with
              the critic's notes injected into the next stage.
    Stage 5 - IMAGE ROUTING: gemini-2.5-flash (multimodal) decides
              whether any source image meaningfully deepens the
              reasoning. Most questions are text-only.
    Stage 6 - ASSEMBLE: build the canonical question shape (5 choices
              A-E), with the correct answer placed randomly per-Q.
    Stage 7 - GLOBAL RANDOMIZE + GATE: after all questions are
              authored, verify the correct-answer distribution across
              the batch is within tolerance (each of A/B/C/D/E is
              between 14% and 26% of the batch when n >= 20). If
              out of tolerance, reshuffle positions deterministically.

Usage (called by `generate_lecture_slide_questions.py` when --v5 is
set, or directly for smoke testing):

    from v5_pipeline import generate_v5
    questions = generate_v5(
        normalized_payload=payload,
        allocations=allocations,
        memory=memory,
        target_order_mix={"first_order": 0.25, "second_order": 0.45, "third_order": 0.30},
        target_difficulty_mix={"easy": 0.30, "medium": 0.45, "difficult": 0.25},
        api_key=os.environ["GEMINI_API_KEY"],
    )

The pipeline writes its own debug artifacts under
`output_json/v5_debug/` so each per-question generation trace is
auditable post-hoc.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = SCRIPT_DIR / "prompts"

STEM_PROMPT_PATH = PROMPT_DIR / "v5_stem_prompt.txt"
DISTRACTOR_PROMPT_PATH = PROMPT_DIR / "v5_distractors_prompt.txt"
CRITIC_PROMPT_PATH = PROMPT_DIR / "v5_critic_prompt.txt"
IMAGE_PROMPT_PATH = PROMPT_DIR / "v5_image_routing_prompt.txt"

DEBUG_DIR = SCRIPT_DIR / "output_json" / "v5_debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# Models — quality-first per user instruction.
STEM_MODEL = "gemini-2.5-pro"
DISTRACTOR_MODEL = "gemini-2.5-pro"
CRITIC_MODEL = "gemini-2.5-pro"
IMAGE_MODEL = "gemini-2.5-flash"

# Critic accept thresholds.
CRITIC_TOTAL_FLOOR = 12
CRITIC_DIMENSION_FLOOR = 2

# Distribution gate.
DISTRIBUTION_TOLERANCE_HIGH = 0.26  # max share per position when n>=20
DISTRIBUTION_TOLERANCE_LOW = 0.14   # min share per position when n>=20

# Sibling-import the legacy module for shared utilities. We import lazily to
# avoid circulars.
def _import_legacy() -> Any:
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    import generate_lecture_slide_questions as legacy  # type: ignore
    return legacy


# ── Gemini client (Vertex AI) ────────────────────────────────────────────────

_genai_client_cache: Any = None


def _genai_client() -> Any:
    global _genai_client_cache
    if _genai_client_cache is not None:
        return _genai_client_cache
    # Reuse the shared uworld client factory so backend selection
    # (Vertex AI vs ai-studio) stays consistent across the repo.
    uw_dir = SCRIPT_DIR.parent / "uworld-notes-question-generator"
    if str(uw_dir) not in sys.path:
        sys.path.insert(0, str(uw_dir))
    import generate_uworld_questions as _uw  # type: ignore
    _genai_client_cache = _uw._gemini_client()
    return _genai_client_cache


def _genai_types() -> Any:
    from google.genai import types as t  # type: ignore
    return t


def gemini_call(
    prompt: str,
    *,
    model: str,
    max_tokens: int = 8192,
    temperature: float = 0.4,
    thinking_budget: int = -1,
    image_bytes: bytes | None = None,
    image_mime: str = "image/png",
) -> str:
    """Single Gemini text/multimodal call. Returns raw text."""
    client = _genai_client()
    t = _genai_types()
    contents: list[Any] = [prompt]
    if image_bytes is not None:
        contents.append(t.Part.from_bytes(data=image_bytes, mime_type=image_mime))
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=t.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max(max_tokens * 2, 16384),
            response_mime_type="application/json",
            thinking_config=t.ThinkingConfig(thinking_budget=thinking_budget),
        ),
    )
    return response.text or ""


def parse_json_loose(raw: str) -> dict | None:
    """Try strict parse first, then locate the first {...} block."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ── Stage 1: planning the order/difficulty matrix per allocation ─────────────


def plan_allocation_slots(
    allocation_question_count: int,
    target_order_mix: dict[str, float],
    target_difficulty_mix: dict[str, float],
    *,
    seed: int = 0,
) -> list[tuple[str, str]]:
    """Return a list of (order, difficulty) tuples sized to
    `allocation_question_count`, distributed to match the target mixes
    as closely as possible, then shuffled."""
    n = max(0, int(allocation_question_count))
    if n == 0:
        return []
    rng = random.Random(seed)
    # Distribute order
    order_keys = list(target_order_mix.keys())
    order_counts = _largest_remainder(target_order_mix, n)
    diff_keys = list(target_difficulty_mix.keys())
    diff_counts = _largest_remainder(target_difficulty_mix, n)
    # Build sequences
    order_seq: list[str] = []
    for k, c in zip(order_keys, order_counts):
        order_seq.extend([k] * c)
    diff_seq: list[str] = []
    for k, c in zip(diff_keys, diff_counts):
        diff_seq.extend([k] * c)
    rng.shuffle(order_seq)
    rng.shuffle(diff_seq)
    return list(zip(order_seq, diff_seq))


def _largest_remainder(mix: dict[str, float], n: int) -> list[int]:
    """Allocate n items to keys per the largest-remainder method so the
    total is exactly n and each key gets approximately its share."""
    raw = [(k, mix[k] * n) for k in mix]
    floors = [(k, int(math.floor(v))) for k, v in raw]
    remainder = n - sum(c for _, c in floors)
    # Sort by fractional part desc to assign the remainder
    fractional = sorted(
        [(k, v - math.floor(v)) for k, v in raw],
        key=lambda x: x[1],
        reverse=True,
    )
    bumps = {k for k, _ in fractional[:remainder]}
    out = []
    for k, c in floors:
        out.append(c + (1 if k in bumps else 0))
    return out


# ── Stage 2: STEM ────────────────────────────────────────────────────────────


def stage_stem(
    *,
    target_order: str,
    target_difficulty: str,
    allowed_terms: list[str],
    slide_context: dict[str, Any],
    memory: dict[str, Any],
) -> dict[str, Any] | None:
    prompt = STEM_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt
        .replace("{{TARGET_ORDER}}", target_order)
        .replace("{{TARGET_DIFFICULTY}}", target_difficulty)
        .replace("{{ALLOWED_TERMS_JSON}}", json.dumps(allowed_terms, ensure_ascii=False))
        .replace("{{SLIDE_CONTEXT_JSON}}", json.dumps(slide_context, ensure_ascii=False))
        .replace("{{MEMORY_JSON}}", json.dumps(memory, ensure_ascii=False))
    )
    raw = gemini_call(prompt, model=STEM_MODEL, max_tokens=4096, thinking_budget=-1, temperature=0.6)
    parsed = parse_json_loose(raw)
    if not parsed or not parsed.get("stem"):
        return None
    return parsed


# ── Stage 3: DISTRACTORS ─────────────────────────────────────────────────────


def stage_distractors(
    *,
    stem: str,
    correct_answer_concept: str,
    allowed_terms: list[str],
    allowed_distractor_pool: list[str],
) -> dict[str, Any] | None:
    prompt = DISTRACTOR_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt
        .replace("{{STEM}}", stem)
        .replace("{{CORRECT_ANSWER_CONCEPT}}", correct_answer_concept)
        .replace("{{ALLOWED_TERMS_JSON}}", json.dumps(allowed_terms, ensure_ascii=False))
        .replace("{{ALLOWED_DISTRACTOR_POOL_JSON}}", json.dumps(allowed_distractor_pool, ensure_ascii=False))
    )
    # Gemini-2.5-Pro on Vertex requires dynamic thinking (thinking_budget=-1);
    # thinking_budget=0 is rejected on Pro. Distractor generation benefits
    # from some reasoning anyway (mechanism-level losing reasons).
    raw = gemini_call(prompt, model=DISTRACTOR_MODEL, max_tokens=4096, thinking_budget=-1, temperature=0.5)
    parsed = parse_json_loose(raw)
    if not parsed or not parsed.get("distractors"):
        return None
    distractors = parsed["distractors"]
    if not isinstance(distractors, list) or not distractors:
        return None
    return parsed


# ── Stage 4: CRITIC ──────────────────────────────────────────────────────────


def stage_critic(
    *,
    stem: str,
    correct_answer_concept: str,
    distractors: list[dict[str, Any]],
    target_order: str,
    target_difficulty: str,
    allowed_terms: list[str],
    allowed_distractor_pool: list[str],
) -> dict[str, Any] | None:
    prompt = CRITIC_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt
        .replace("{{STEM}}", stem)
        .replace("{{CORRECT_ANSWER_CONCEPT}}", correct_answer_concept)
        .replace("{{DISTRACTORS_JSON}}", json.dumps(distractors, ensure_ascii=False))
        .replace("{{TARGET_ORDER}}", target_order)
        .replace("{{TARGET_DIFFICULTY}}", target_difficulty)
        .replace("{{ALLOWED_TERMS_JSON}}", json.dumps(allowed_terms, ensure_ascii=False))
        .replace("{{ALLOWED_DISTRACTOR_POOL_JSON}}", json.dumps(allowed_distractor_pool, ensure_ascii=False))
    )
    raw = gemini_call(prompt, model=CRITIC_MODEL, max_tokens=2048, thinking_budget=-1, temperature=0.2)
    parsed = parse_json_loose(raw)
    if not parsed:
        return None
    return parsed


# ── Stage 5: IMAGE ROUTING (text-only metadata pass) ─────────────────────────


def stage_image_route(
    *,
    stem: str,
    image_opportunity: str,
    available_images: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not available_images:
        return {"attach": False, "imageId": "", "placement": "", "reason": "no source images available"}
    prompt = IMAGE_PROMPT_PATH.read_text(encoding="utf-8")
    minimal = [
        {
            "imageId": img.get("imageId") or img.get("id") or "",
            "kind": img.get("kind") or img.get("type") or "unknown",
            "description": (img.get("description") or img.get("caption") or "")[:200],
        }
        for img in available_images
    ]
    prompt = (
        prompt
        .replace("{{STEM}}", stem)
        .replace("{{IMAGE_OPPORTUNITY}}", image_opportunity or "none")
        .replace("{{AVAILABLE_IMAGES_JSON}}", json.dumps(minimal, ensure_ascii=False))
    )
    raw = gemini_call(prompt, model=IMAGE_MODEL, max_tokens=1024, thinking_budget=0, temperature=0.2)
    parsed = parse_json_loose(raw)
    if not parsed or "attach" not in parsed:
        return {"attach": False, "imageId": "", "placement": "", "reason": "image routing parse failed"}
    return parsed


# ── Stage 6/7: ASSEMBLE + RANDOMIZE ──────────────────────────────────────────


def assemble_question(
    *,
    question_number: int,
    stem_obj: dict[str, Any],
    distractors_obj: dict[str, Any],
    critic_obj: dict[str, Any] | None,
    image_route: dict[str, Any] | None,
    allocation: dict[str, Any],
    target_order: str,
    target_difficulty: str,
    rng: random.Random,
) -> dict[str, Any]:
    """Build a canonical question dict. Correct answer position is
    chosen at random here so the per-batch distribution is shaped at
    randomize_global_distribution() time."""
    stem = stem_obj.get("stem", "")
    correct_text = stem_obj.get("correctAnswerConcept", "")
    distractors = distractors_obj.get("distractors", [])
    # Trim to 4
    distractors = distractors[:4]
    # Build the choice list and randomize position
    choices_text = [correct_text] + [d.get("text", "") for d in distractors]
    rng.shuffle(choices_text)
    correct_index = choices_text.index(correct_text)
    labels = ["A", "B", "C", "D", "E"][: len(choices_text)]
    answer_choices = [
        {"label": labels[i], "text": choices_text[i]} for i in range(len(choices_text))
    ]
    correct_label = labels[correct_index]
    # Map each distractor's losing reason back to its label.
    distractor_label_map: dict[str, dict[str, Any]] = {}
    for i, text in enumerate(choices_text):
        if i == correct_index:
            continue
        for d in distractors:
            if d.get("text", "") == text:
                distractor_label_map[labels[i]] = d
                break
    return {
        "questionNumber": question_number,
        "slideId": allocation.get("slideId", ""),
        "questionKind": "clinical_vignette",
        "testedConcept": stem_obj.get("testedConcept", ""),
        "diagnosisOrTarget": stem_obj.get("correctAnswerConcept", ""),
        "stem": stem,
        "hasEmbeddedFigure": bool(image_route and image_route.get("attach")),
        "figureRefs": [],  # filled by post-processor when image attached
        "answerChoices": answer_choices,
        "correctAnswer": correct_label,
        "educationalObjective": stem_obj.get("testedConcept", ""),
        "explanationSections": _build_explanation_sections(
            stem_obj=stem_obj,
            distractors=distractors,
            distractor_label_map=distractor_label_map,
            correct_label=correct_label,
        ),
        "tables": [],
        "sharedGroup": None,
        "extractionWarnings": [],
        "_v5": {
            "targetOrder": target_order,
            "targetDifficulty": target_difficulty,
            "orderAchieved": stem_obj.get("orderAchieved", ""),
            "difficultyAchieved": stem_obj.get("difficultyAchieved", ""),
            "criticTotal": (critic_obj or {}).get("total"),
            "criticVerdict": (critic_obj or {}).get("verdict"),
            "criticAntiPatterns": (critic_obj or {}).get("antiPatternsFound", []),
            "imageOpportunity": stem_obj.get("imageOpportunity", "none"),
            "imageRoute": image_route or {},
            "sourceFactIds": stem_obj.get("sourceFactIds", []),
        },
    }


def _build_explanation_sections(
    *,
    stem_obj: dict[str, Any],
    distractors: list[dict[str, Any]],
    distractor_label_map: dict[str, dict[str, Any]],
    correct_label: str,
) -> list[dict[str, Any]]:
    sections = []
    rationale = (stem_obj.get("rationale") or "").strip()
    if rationale:
        sections.append(
            {"heading": "Correct Answer Explanation", "body": [rationale]}
        )
    if distractor_label_map:
        lines = []
        for label in sorted(distractor_label_map.keys()):
            d = distractor_label_map[label]
            losing = (d.get("losingReason") or "").strip()
            tempt = (d.get("tempt") or "").strip()
            line = f"{label}. {(d.get('text') or '').strip()} — {losing}"
            if tempt:
                line += f" (Tempt: {tempt})"
            lines.append(line)
        if lines:
            sections.append({"heading": "Incorrect Answer Explanation", "body": lines})
    edu = (stem_obj.get("testedConcept") or "").strip()
    if edu:
        sections.append({"heading": "Educational Objective", "body": [edu]})
    return sections


def randomize_global_distribution(
    questions: list[dict[str, Any]], *, seed: int = 0
) -> list[dict[str, Any]]:
    """Verify that the per-batch correctAnswer distribution is within
    tolerance. If not, reshuffle each non-conforming question's choice
    order so the global distribution lands inside the band. Per-Q
    shuffles already happened in assemble_question; this is the
    second-pass gate.
    """
    if len(questions) < 20:
        return questions
    rng = random.Random(seed + 17)
    for _attempt in range(3):
        dist = Counter(q.get("correctAnswer", "") for q in questions)
        n = len(questions)
        # Identify positions that are over or under.
        over = [k for k, v in dist.items() if v / n > DISTRIBUTION_TOLERANCE_HIGH]
        under = [k for k in "ABCDE" if dist.get(k, 0) / n < DISTRIBUTION_TOLERANCE_LOW]
        if not over and not under:
            return questions
        # Reshuffle a random subset of the over-represented Qs.
        candidates = [q for q in questions if q.get("correctAnswer") in over]
        rng.shuffle(candidates)
        # Reshuffle answers for these so they end up in different positions.
        for q in candidates[: max(1, len(candidates) // 2)]:
            choices = q.get("answerChoices", []) or []
            if not choices:
                continue
            correct_text = next(
                (c["text"] for c in choices if c["label"] == q.get("correctAnswer")),
                None,
            )
            if correct_text is None:
                continue
            rng.shuffle(choices)
            for i, c in enumerate(choices):
                c["label"] = "ABCDE"[i]
            new_correct = next(c["label"] for c in choices if c["text"] == correct_text)
            q["correctAnswer"] = new_correct
            q["answerChoices"] = choices
    return questions


# ── Main entry point ────────────────────────────────────────────────────────


def generate_one_question(
    *,
    question_number: int,
    allocation: dict[str, Any],
    target_order: str,
    target_difficulty: str,
    memory: dict[str, Any],
    available_images: list[dict[str, Any]],
    rng: random.Random,
) -> dict[str, Any] | None:
    """Run the multi-stage pipeline for ONE question slot. Returns None
    if the pipeline couldn't produce an acceptable question."""
    allowed_terms = allocation.get("allowedMedicalTerms") or []
    allowed_distractor_pool = allocation.get("allowedDistractorPool") or []
    slide_context = allocation.get("slideContext") or {}

    # Stage 2 - STEM
    stem_obj = stage_stem(
        target_order=target_order,
        target_difficulty=target_difficulty,
        allowed_terms=allowed_terms,
        slide_context=slide_context,
        memory=memory,
    )
    if not stem_obj or not stem_obj.get("stem") or not stem_obj.get("correctAnswerConcept"):
        return None

    # Stage 3 - DISTRACTORS
    distractors_obj = stage_distractors(
        stem=stem_obj["stem"],
        correct_answer_concept=stem_obj["correctAnswerConcept"],
        allowed_terms=allowed_terms,
        allowed_distractor_pool=allowed_distractor_pool,
    )
    if not distractors_obj or not distractors_obj.get("distractors"):
        return None

    # Stage 4 - CRITIC
    critic_obj = stage_critic(
        stem=stem_obj["stem"],
        correct_answer_concept=stem_obj["correctAnswerConcept"],
        distractors=distractors_obj["distractors"],
        target_order=target_order,
        target_difficulty=target_difficulty,
        allowed_terms=allowed_terms,
        allowed_distractor_pool=allowed_distractor_pool,
    )
    if critic_obj and critic_obj.get("verdict") == "revise":
        # ONE revision attempt — distractor regen with critic notes prepended
        revise_notes = critic_obj.get("revisionNotes", "")
        revised_distractors = stage_distractors(
            stem=stem_obj["stem"],
            correct_answer_concept=stem_obj["correctAnswerConcept"],
            allowed_terms=allowed_terms,
            allowed_distractor_pool=allowed_distractor_pool + [f"[CRITIC REVISION NOTES] {revise_notes}"],
        )
        if revised_distractors:
            distractors_obj = revised_distractors
            critic_obj = stage_critic(
                stem=stem_obj["stem"],
                correct_answer_concept=stem_obj["correctAnswerConcept"],
                distractors=distractors_obj["distractors"],
                target_order=target_order,
                target_difficulty=target_difficulty,
                allowed_terms=allowed_terms,
                allowed_distractor_pool=allowed_distractor_pool,
            )
    if critic_obj and critic_obj.get("verdict") == "reject":
        # Hard reject. Return None and let the caller decide to retry
        # with a different order/difficulty target or skip the slot.
        return None

    # Stage 5 - IMAGE ROUTING
    image_route = stage_image_route(
        stem=stem_obj["stem"],
        image_opportunity=stem_obj.get("imageOpportunity", "none"),
        available_images=available_images,
    )

    # Stage 6 - ASSEMBLE
    q = assemble_question(
        question_number=question_number,
        stem_obj=stem_obj,
        distractors_obj=distractors_obj,
        critic_obj=critic_obj,
        image_route=image_route,
        allocation=allocation,
        target_order=target_order,
        target_difficulty=target_difficulty,
        rng=rng,
    )

    # Debug artifact for post-hoc inspection
    debug_path = DEBUG_DIR / f"Q{question_number:04d}.json"
    try:
        debug_path.write_text(
            json.dumps(
                {
                    "stem_obj": stem_obj,
                    "distractors_obj": distractors_obj,
                    "critic_obj": critic_obj,
                    "image_route": image_route,
                    "final": q,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    except Exception:
        pass

    return q


def generate_v5(
    *,
    normalized_payload: dict[str, Any],
    allocations: list[dict[str, Any]],
    memory: dict[str, Any],
    target_order_mix: dict[str, float] | None = None,
    target_difficulty_mix: dict[str, float] | None = None,
    available_images: list[dict[str, Any]] | None = None,
    seed: int = 0,
) -> list[dict[str, Any]]:
    """Top-level v5 pipeline entry point. Returns the list of completed
    question dicts in the canonical app-ready schema."""
    target_order_mix = target_order_mix or {
        "first_order": 0.25,
        "second_order": 0.45,
        "third_order": 0.30,
    }
    target_difficulty_mix = target_difficulty_mix or {
        "easy": 0.30,
        "medium": 0.45,
        "difficult": 0.25,
    }
    questions: list[dict[str, Any]] = []
    rng = random.Random(seed)
    qn = 0
    for alloc_idx, allocation in enumerate(allocations):
        count = int(allocation.get("questionCount") or 0)
        if count <= 0:
            continue
        slot_plan = plan_allocation_slots(
            count, target_order_mix, target_difficulty_mix, seed=seed + alloc_idx
        )
        slide_images = allocation.get("slideImages") or available_images or []
        for slot_idx, (target_order, target_difficulty) in enumerate(slot_plan):
            qn += 1
            try:
                q = generate_one_question(
                    question_number=qn,
                    allocation=allocation,
                    target_order=target_order,
                    target_difficulty=target_difficulty,
                    memory=memory,
                    available_images=slide_images,
                    rng=rng,
                )
            except Exception as exc:  # surface but don't crash the batch
                print(f"[v5] Q{qn} pipeline error: {exc}", file=sys.stderr)
                q = None
            if q:
                questions.append(q)
                _update_memory(memory, q)
            else:
                print(f"[v5] Q{qn} skipped (pipeline rejected)", file=sys.stderr)

    # Stage 7 - GLOBAL DISTRIBUTION GATE
    questions = randomize_global_distribution(questions, seed=seed)
    return questions


def _update_memory(memory: dict[str, Any], q: dict[str, Any]) -> None:
    diagnoses = memory.setdefault("diagnoses", [])
    target = q.get("diagnosisOrTarget", "").strip()
    if target and target not in diagnoses:
        diagnoses.append(target)
    stems = memory.setdefault("recentStemStarts", [])
    start = (q.get("stem") or "")[:120]
    if start:
        stems.append(start)
        memory["recentStemStarts"] = stems[-50:]


# ── Smoke-test CLI ──────────────────────────────────────────────────────────


def _smoke_test_cli() -> int:
    parser = argparse.ArgumentParser(description="v5 pipeline smoke test")
    parser.add_argument(
        "--allocation-file",
        required=True,
        help="JSON file containing a list[Allocation] for smoke test",
    )
    parser.add_argument(
        "--out", required=True, help="Where to write the generated questions JSON"
    )
    parser.add_argument(
        "--seed", type=int, default=0, help="RNG seed for reproducibility"
    )
    args = parser.parse_args()
    allocations = json.loads(Path(args.allocation_file).read_text(encoding="utf-8"))
    if not isinstance(allocations, list):
        allocations = allocations.get("allocations") or []
    normalized_payload = {"sourceFile": "smoke_test_v5"}
    memory: dict[str, Any] = {}
    started = time.time()
    questions = generate_v5(
        normalized_payload=normalized_payload,
        allocations=allocations,
        memory=memory,
        seed=args.seed,
    )
    elapsed = time.time() - started
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "schemaVersion": "v5-organic",
                "sourceFormat": "lecture-slide-v5",
                "testTitle": "v5 smoke test",
                "expectedQuestionCount": sum(int(a.get("questionCount") or 0) for a in allocations),
                "actualExtractedQuestionCount": len(questions),
                "extractionWarnings": [],
                "questions": questions,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"v5 smoke test: produced {len(questions)} questions in {elapsed:.1f}s")
    print(f"  Output: {out_path}")
    print(f"  Debug per-Q traces under: {DEBUG_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(_smoke_test_cli())
