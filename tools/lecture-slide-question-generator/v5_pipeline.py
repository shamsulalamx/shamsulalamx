#!/usr/bin/env python3
"""v5 multi-stage NBME-authentic question generation pipeline.

v5.2 (current) adds five distractor-quality improvements over v5.0:
  A. KERNEL-FIRST DESIGN — design correctAnswer + 4 trap categories +
     discriminating clue BEFORE the stem prose, NBME-committee style.
  B. ADVERSARIAL VERIFICATION — embedded in the critic; each distractor
     gets an argue-for-correct mini-pass to detect competes-too-well or
     too-easily-dismissed failures.
  C. STEM-DISTRACTOR CO-DESIGN — the stem is required to contain the
     kernel's discriminating clue AND every distractor's sharedFeatures,
     verified by self-check + critic literal-stem check.
  D. PER-DISTRACTOR CRITIC SCORING — each of 4 distractors scored
     individually; revise_weakest path targets only the lowest scorer.
  E. LENGTH PARITY — deterministic post-process balances all 5
     answer-choice text lengths to within ~30% of the median, killing
     the "longest = correct" tell.

Stage flow:

    Stage 1 - PLAN          (deterministic) target (order, difficulty)
                            per slot via largest-remainder method.

    Stage 2 - KERNEL        (NEW; Pro+thinking) design correctAnswer +
                            discriminatingClueInStem + 4 trap-category
                            distractor designs.

    Stage 3 - STEM          (Pro+thinking) writes stem from kernel;
                            self-checks discriminator + sharedFeatures
                            presence.

    Stage 4 - DISTRACTORS   (Pro+thinking) polishes kernel-designed
                            distractor items into final answer-choice
                            text, preserving trapCategory.

    Stage 5 - CRITIC        (NEW PER-DISTRACTOR + ADVERSARIAL;
                            Pro+thinking) per-distractor scoring,
                            argues each as correct, verifies clue
                            in stem literally, emits per-distractor
                            verdicts + overall verdict.

    Stage 6 - TARGETED REGEN (Pro+thinking) replaces only the weakest
                             distractor when critic verdict =
                             revise_weakest.

    Stage 7 - LENGTH PARITY (NEW; deterministic) adjusts answer-choice
                            text lengths to within ~30% of median.

    Stage 8 - IMAGE ROUTING (Flash, short-circuited when imageOpportunity
                            == 'none' OR no available images).

    Stage 9 - ASSEMBLE      build canonical app-ready shape; per-Q RNG
                            shuffles correct position.

    Stage 10 - GLOBAL GATE  verify batch correctAnswer distribution in
                            14-26% per position for n>=20; reshuffle
                            outliers.

Usage:
    from v5_pipeline import generate_v5
    questions = generate_v5(...)

Each per-Q debug trace lands under output_json/v5_debug/Q####.json.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROMPT_DIR = SCRIPT_DIR / "prompts"

KERNEL_PROMPT_PATH = PROMPT_DIR / "v5_2_kernel_prompt.txt"
STEM_PROMPT_PATH = PROMPT_DIR / "v5_2_stem_prompt.txt"
DISTRACTOR_PROMPT_PATH = PROMPT_DIR / "v5_2_distractors_prompt.txt"
CRITIC_PROMPT_PATH = PROMPT_DIR / "v5_2_critic_prompt.txt"
REGEN_PROMPT_PATH = PROMPT_DIR / "v5_2_regen_distractor_prompt.txt"
IMAGE_PROMPT_PATH = PROMPT_DIR / "v5_image_routing_prompt.txt"

DEBUG_DIR = SCRIPT_DIR / "output_json" / "v5_debug"
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# Models — quality-first per user instruction.
KERNEL_MODEL = "gemini-2.5-pro"
STEM_MODEL = "gemini-2.5-pro"
DISTRACTOR_MODEL = "gemini-2.5-pro"
CRITIC_MODEL = "gemini-2.5-pro"
REGEN_MODEL = "gemini-2.5-pro"
IMAGE_MODEL = "gemini-2.5-flash"

# Distribution gate.
DISTRIBUTION_TOLERANCE_HIGH = 0.26  # max share per position when n>=20
DISTRIBUTION_TOLERANCE_LOW = 0.14   # min share per position when n>=20

# Length parity band (max length / median length).
LENGTH_PARITY_BAND = 1.30

TRAP_CATEGORIES = {
    "COMPETING_DIAGNOSIS",
    "RIGHT_IDEA_WRONG_TARGET",
    "NEXT_STEP_WRONG_PHASE",
    "CONTRAINDICATED_OR_COMORBID_TRAP",
}


# ── Gemini client (Vertex AI) ────────────────────────────────────────────────

_genai_client_cache: Any = None


def _genai_client() -> Any:
    global _genai_client_cache
    if _genai_client_cache is not None:
        return _genai_client_cache
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


# ── Stage 1: PLAN ───────────────────────────────────────────────────────────


def plan_allocation_slots(
    allocation_question_count: int,
    target_order_mix: dict[str, float],
    target_difficulty_mix: dict[str, float],
    *,
    seed: int = 0,
) -> list[tuple[str, str]]:
    n = max(0, int(allocation_question_count))
    if n == 0:
        return []
    rng = random.Random(seed)
    order_keys = list(target_order_mix.keys())
    order_counts = _largest_remainder(target_order_mix, n)
    diff_keys = list(target_difficulty_mix.keys())
    diff_counts = _largest_remainder(target_difficulty_mix, n)
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
    raw = [(k, mix[k] * n) for k in mix]
    floors = [(k, int(math.floor(v))) for k, v in raw]
    remainder = n - sum(c for _, c in floors)
    fractional = sorted(
        [(k, v - math.floor(v)) for k, v in raw],
        key=lambda x: x[1],
        reverse=True,
    )
    bumps = {k for k, _ in fractional[:remainder]}
    return [c + (1 if k in bumps else 0) for k, c in floors]


# ── Stage 2: KERNEL (NEW; trap-category design BEFORE stem) ──────────────────


def stage_kernel(
    *,
    target_order: str,
    target_difficulty: str,
    allowed_terms: list[str],
    allowed_distractor_pool: list[str],
    slide_context: dict[str, Any],
    memory: dict[str, Any],
) -> dict[str, Any] | None:
    prompt = KERNEL_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt
        .replace("{{TARGET_ORDER}}", target_order)
        .replace("{{TARGET_DIFFICULTY}}", target_difficulty)
        .replace("{{ALLOWED_TERMS_JSON}}", json.dumps(allowed_terms, ensure_ascii=False))
        .replace("{{ALLOWED_DISTRACTOR_POOL_JSON}}", json.dumps(allowed_distractor_pool, ensure_ascii=False))
        .replace("{{SLIDE_CONTEXT_JSON}}", json.dumps(slide_context, ensure_ascii=False))
        .replace("{{MEMORY_JSON}}", json.dumps(memory, ensure_ascii=False))
    )
    raw = gemini_call(prompt, model=KERNEL_MODEL, max_tokens=4096, thinking_budget=-1, temperature=0.5)
    parsed = parse_json_loose(raw)
    if not parsed:
        return None
    required = ("correctAnswerConcept", "discriminatingClueInStem", "distractors")
    if not all(parsed.get(k) for k in required):
        return None
    distractors = parsed.get("distractors") or []
    if not isinstance(distractors, list) or len(distractors) < 3:
        return None
    # Verify each trap is a known category.
    for d in distractors:
        cat = (d.get("trapCategory") or "").strip().upper()
        if cat not in TRAP_CATEGORIES:
            return None
    # Reject if more than one distractor in the same category.
    cats = [d.get("trapCategory", "").upper() for d in distractors]
    if len(set(cats)) != len(cats):
        return None
    return parsed


# ── Stage 3: STEM (consumes kernel) ──────────────────────────────────────────


def stage_stem(
    *,
    kernel: dict[str, Any],
    target_order: str,
    target_difficulty: str,
    allowed_terms: list[str],
    slide_context: dict[str, Any],
) -> dict[str, Any] | None:
    prompt = STEM_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt
        .replace("{{TARGET_ORDER}}", target_order)
        .replace("{{TARGET_DIFFICULTY}}", target_difficulty)
        .replace("{{KERNEL_JSON}}", json.dumps(kernel, ensure_ascii=False))
        .replace("{{ALLOWED_TERMS_JSON}}", json.dumps(allowed_terms, ensure_ascii=False))
        .replace("{{SLIDE_CONTEXT_JSON}}", json.dumps(slide_context, ensure_ascii=False))
    )
    raw = gemini_call(prompt, model=STEM_MODEL, max_tokens=4096, thinking_budget=-1, temperature=0.6)
    parsed = parse_json_loose(raw)
    if not parsed or not parsed.get("stem"):
        return None
    # The author's self-check: did they actually include the clue?
    if not parsed.get("containedDiscriminatingClue", False):
        return None
    # Verify every sharedFeature was kept.
    missing = []
    for entry in parsed.get("containedSharedFeatures", []) or []:
        if entry.get("missing"):
            missing.extend(entry.get("missing"))
    if missing:
        return None
    return parsed


# ── Stage 4: DISTRACTORS (polishes kernel into answer-choice text) ──────────


def stage_distractors(
    *,
    stem: str,
    kernel: dict[str, Any],
) -> dict[str, Any] | None:
    prompt = DISTRACTOR_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt
        .replace("{{STEM}}", stem)
        .replace("{{KERNEL_JSON}}", json.dumps(kernel, ensure_ascii=False))
    )
    raw = gemini_call(prompt, model=DISTRACTOR_MODEL, max_tokens=4096, thinking_budget=-1, temperature=0.4)
    parsed = parse_json_loose(raw)
    if not parsed or not parsed.get("distractors"):
        return None
    distractors = parsed["distractors"]
    if not isinstance(distractors, list) or len(distractors) < 3:
        return None
    return parsed


# ── Stage 5: CRITIC (per-distractor + adversarial argue-each) ───────────────


def stage_critic(
    *,
    stem: str,
    correct_answer_text: str,
    correct_answer_concept: str,
    distractors: list[dict[str, Any]],
    kernel: dict[str, Any],
    target_order: str,
    target_difficulty: str,
) -> dict[str, Any] | None:
    prompt = CRITIC_PROMPT_PATH.read_text(encoding="utf-8")
    correct_payload = {
        "text": correct_answer_text,
        "concept": correct_answer_concept,
    }
    prompt = (
        prompt
        .replace("{{STEM}}", stem)
        .replace("{{CORRECT_ANSWER_JSON}}", json.dumps(correct_payload, ensure_ascii=False))
        .replace("{{DISTRACTORS_JSON}}", json.dumps(distractors, ensure_ascii=False))
        .replace("{{KERNEL_JSON}}", json.dumps(kernel, ensure_ascii=False))
        .replace("{{TARGET_ORDER}}", target_order)
        .replace("{{TARGET_DIFFICULTY}}", target_difficulty)
    )
    raw = gemini_call(prompt, model=CRITIC_MODEL, max_tokens=4096, thinking_budget=-1, temperature=0.2)
    return parse_json_loose(raw)


# ── Stage 6: TARGETED REGEN ──────────────────────────────────────────────────


def stage_regen_distractor(
    *,
    stem: str,
    correct_answer_text: str,
    good_distractors: list[dict[str, Any]],
    rejected_distractor: dict[str, Any],
    critic_issue: str,
    kernel: dict[str, Any],
) -> dict[str, Any] | None:
    prompt = REGEN_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt
        .replace("{{STEM}}", stem)
        .replace("{{CORRECT_ANSWER}}", correct_answer_text)
        .replace("{{GOOD_DISTRACTORS_JSON}}", json.dumps(good_distractors, ensure_ascii=False))
        .replace("{{REJECTED_DISTRACTOR_JSON}}", json.dumps(rejected_distractor, ensure_ascii=False))
        .replace("{{CRITIC_ISSUE}}", critic_issue or "")
        .replace("{{KERNEL_JSON}}", json.dumps(kernel, ensure_ascii=False))
    )
    raw = gemini_call(prompt, model=REGEN_MODEL, max_tokens=2048, thinking_budget=-1, temperature=0.5)
    parsed = parse_json_loose(raw)
    if not parsed or not parsed.get("replacement"):
        return None
    return parsed["replacement"]


# ── Stage 7: LENGTH PARITY (deterministic post-process) ─────────────────────


def length_parity_balance(
    correct_text: str, distractor_texts: list[str]
) -> tuple[str, list[str], dict[str, Any]]:
    """If the correct answer is longer than 1.3x the median, attempt
    safe trimming. If the shortest distractor is much shorter than the
    median, pad with a clinically inert qualifier. This is a
    DETERMINISTIC tuning step; if it cannot bring everything into the
    band without altering meaning, it leaves the text alone and emits
    a warning."""
    all_texts = [correct_text] + list(distractor_texts)
    lens = [len(t) for t in all_texts]
    if not lens:
        return correct_text, distractor_texts, {"applied": False, "reason": "empty"}
    median = statistics.median(lens)
    if median <= 0:
        return correct_text, distractor_texts, {"applied": False, "reason": "zero_median"}
    target_max = int(median * LENGTH_PARITY_BAND)
    info = {"applied": False, "before": lens, "median": median, "warnings": []}

    # Trim only the leading parenthetical or trailing clarifier; never
    # change clinical meaning. If trimming can't get under target_max,
    # we leave the text alone (the critic accepted it as truthful).
    def safe_trim(text: str) -> str:
        if len(text) <= target_max:
            return text
        # Drop a parenthetical: "Aspirin (325 mg orally)" -> "Aspirin"
        m = re.match(r"^(.+?)\s*\([^)]+\)\s*$", text)
        if m and len(m.group(1)) <= target_max:
            return m.group(1).strip()
        # Drop a trailing comma-clause: "X, including Y and Z" -> "X"
        m = re.match(r"^(.+?),\s+[^,]+$", text)
        if m and len(m.group(1)) <= target_max:
            return m.group(1).strip()
        return text

    correct_new = safe_trim(correct_text)
    distractors_new = [safe_trim(d) for d in distractor_texts]
    changed = (correct_new != correct_text) or (distractors_new != list(distractor_texts))
    info["applied"] = changed
    info["after"] = [len(correct_new)] + [len(d) for d in distractors_new]
    info["targetMax"] = target_max
    return correct_new, distractors_new, info


# ── Stage 8: IMAGE ROUTING (short-circuited) ────────────────────────────────


def stage_image_route(
    *,
    stem: str,
    image_opportunity: str,
    available_images: list[dict[str, Any]],
) -> dict[str, Any]:
    if not available_images:
        return {"attach": False, "imageId": "", "placement": "", "reason": "no source images available"}
    if (image_opportunity or "none").strip().lower() == "none":
        return {"attach": False, "imageId": "", "placement": "", "reason": "stem author said no image opportunity"}
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


# ── Stage 9: ASSEMBLE ───────────────────────────────────────────────────────


def assemble_question(
    *,
    question_number: int,
    kernel: dict[str, Any],
    stem_obj: dict[str, Any],
    correct_text: str,
    distractor_texts: list[str],
    distractors_meta: list[dict[str, Any]],
    critic_obj: dict[str, Any] | None,
    image_route: dict[str, Any] | None,
    allocation: dict[str, Any],
    target_order: str,
    target_difficulty: str,
    length_parity_info: dict[str, Any],
    rng: random.Random,
) -> dict[str, Any]:
    """Build canonical question. Correct-answer position is randomized
    per-Q via the RNG; stage 10 then verifies global distribution."""
    stem = stem_obj.get("stem", "")
    choices_text = [correct_text] + list(distractor_texts)
    rng.shuffle(choices_text)
    correct_index = choices_text.index(correct_text)
    labels = ["A", "B", "C", "D", "E"][: len(choices_text)]
    answer_choices = [
        {"label": labels[i], "text": choices_text[i]} for i in range(len(choices_text))
    ]
    correct_label = labels[correct_index]
    # Reattach each distractor's losingReason to its final label
    distractor_label_map: dict[str, dict[str, Any]] = {}
    distractor_lookup = {d.get("text", ""): d for d in distractors_meta}
    for i, text in enumerate(choices_text):
        if i == correct_index:
            continue
        if text in distractor_lookup:
            distractor_label_map[labels[i]] = distractor_lookup[text]
    return {
        "questionNumber": question_number,
        "slideId": allocation.get("slideId", ""),
        "questionKind": "clinical_vignette",
        "testedConcept": kernel.get("correctAnswerConcept", ""),
        "diagnosisOrTarget": kernel.get("correctAnswerConcept", ""),
        "stem": stem,
        "hasEmbeddedFigure": bool(image_route and image_route.get("attach")),
        "figureRefs": [],
        "answerChoices": answer_choices,
        "correctAnswer": correct_label,
        "educationalObjective": kernel.get("correctAnswerConcept", ""),
        "explanationSections": _build_explanation_sections(
            kernel=kernel,
            distractor_label_map=distractor_label_map,
        ),
        "tables": [],
        "sharedGroup": None,
        "extractionWarnings": [],
        "_v5_2": {
            "targetOrder": target_order,
            "targetDifficulty": target_difficulty,
            "orderAchieved": stem_obj.get("orderAchieved", ""),
            "difficultyAchieved": stem_obj.get("difficultyAchieved", ""),
            "criticOverallTotal": (critic_obj or {}).get("overallTotal"),
            "criticVerdict": (critic_obj or {}).get("verdict"),
            "criticAntiPatterns": (critic_obj or {}).get("antiPatternsFound", []),
            "criticDistractorScores": (critic_obj or {}).get("distractorScores", []),
            "discriminatingClueInStem": (critic_obj or {}).get("discriminatingClueInStem", None),
            "trapCategoriesUsed": [d.get("trapCategory") for d in distractors_meta],
            "imageRoute": image_route or {},
            "lengthParity": length_parity_info,
            "sourceFactIds": stem_obj.get("sourceFactIds", []),
            "discriminatingClue": kernel.get("discriminatingClueInStem", ""),
        },
    }


def _build_explanation_sections(
    *, kernel: dict[str, Any], distractor_label_map: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    rationale = (kernel.get("rationale") or "").strip()
    if rationale:
        sections.append({"heading": "Correct Answer Explanation", "body": [rationale]})
    if distractor_label_map:
        lines = []
        for label in sorted(distractor_label_map.keys()):
            d = distractor_label_map[label]
            text = (d.get("text") or "").strip()
            losing = (d.get("losingReason") or "").strip()
            cat = (d.get("trapCategory") or "").strip()
            line = f"{label}. {text} — {losing}"
            if cat:
                line += f"  [trap: {cat.lower().replace('_', ' ')}]"
            lines.append(line)
        if lines:
            sections.append({"heading": "Incorrect Answer Explanation", "body": lines})
    edu = (kernel.get("correctAnswerConcept") or "").strip()
    if edu:
        sections.append({"heading": "Educational Objective", "body": [edu]})
    return sections


# ── Stage 10: GLOBAL DISTRIBUTION GATE ───────────────────────────────────────


def randomize_global_distribution(
    questions: list[dict[str, Any]], *, seed: int = 0
) -> list[dict[str, Any]]:
    if len(questions) < 20:
        return questions
    rng = random.Random(seed + 17)
    for _attempt in range(3):
        dist = Counter(q.get("correctAnswer", "") for q in questions)
        n = len(questions)
        over = [k for k, v in dist.items() if v / n > DISTRIBUTION_TOLERANCE_HIGH]
        under = [k for k in "ABCDE" if dist.get(k, 0) / n < DISTRIBUTION_TOLERANCE_LOW]
        if not over and not under:
            return questions
        candidates = [q for q in questions if q.get("correctAnswer") in over]
        rng.shuffle(candidates)
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


# ── Orchestrator: one question end-to-end ───────────────────────────────────


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
    allowed_terms = allocation.get("allowedMedicalTerms") or []
    allowed_distractor_pool = allocation.get("allowedDistractorPool") or []
    slide_context = allocation.get("slideContext") or {}

    # Stage 2: KERNEL
    kernel = stage_kernel(
        target_order=target_order,
        target_difficulty=target_difficulty,
        allowed_terms=allowed_terms,
        allowed_distractor_pool=allowed_distractor_pool,
        slide_context=slide_context,
        memory=memory,
    )
    if not kernel:
        return None

    # Stage 3: STEM
    stem_obj = stage_stem(
        kernel=kernel,
        target_order=target_order,
        target_difficulty=target_difficulty,
        allowed_terms=allowed_terms,
        slide_context=slide_context,
    )
    if not stem_obj:
        return None

    # Stage 4: DISTRACTORS
    distractors_obj = stage_distractors(stem=stem_obj["stem"], kernel=kernel)
    if not distractors_obj:
        return None
    correct_text = (distractors_obj.get("correctAnswerText") or "").strip()
    distractors = distractors_obj.get("distractors") or []
    if not correct_text or not distractors:
        return None

    # Stage 5: CRITIC (per-distractor + adversarial)
    critic = stage_critic(
        stem=stem_obj["stem"],
        correct_answer_text=correct_text,
        correct_answer_concept=kernel.get("correctAnswerConcept", ""),
        distractors=distractors,
        kernel=kernel,
        target_order=target_order,
        target_difficulty=target_difficulty,
    )
    verdict = (critic or {}).get("verdict", "")

    # Stage 6: TARGETED REGEN
    # revise_weakest: regen just the lowest-scoring distractor.
    # revise_full: regen EVERY distractor scoring below 2 (often 2-3 of
    # them) — each in its kernel-defined trap category — then re-critic
    # the whole set once. This avoids letting questions through with
    # multiple NO_DEFENSE distractors (a real failure mode the smoke
    # test surfaced) while preserving the kernel structure.
    if critic and verdict in ("revise_weakest", "revise_full"):
        scores = critic.get("distractorScores") or []
        # Pick indices to regen
        if verdict == "revise_weakest":
            weakest = critic.get("weakestDistractorIndex")
            to_regen = [int(weakest)] if isinstance(weakest, int) else []
        else:  # revise_full
            to_regen = [
                int(ds.get("index"))
                for ds in scores
                if isinstance(ds.get("index"), int) and int(ds.get("score", 0)) < 2
            ]
        # Defensive: ignore out-of-range indices
        to_regen = [i for i in to_regen if 0 <= i < len(distractors)]
        issues_by_index = {int(ds.get("index")): ds.get("issue", "") for ds in scores if isinstance(ds.get("index"), int)}
        for weak_idx in to_regen:
            rejected = distractors[weak_idx]
            issue = issues_by_index.get(weak_idx, "")
            good = [d for i, d in enumerate(distractors) if i != weak_idx]
            replacement = stage_regen_distractor(
                stem=stem_obj["stem"],
                correct_answer_text=correct_text,
                good_distractors=good,
                rejected_distractor=rejected,
                critic_issue=issue,
                kernel=kernel,
            )
            if replacement:
                distractors[weak_idx] = replacement
        if to_regen:
            # Re-critic the patched set ONCE.
            critic = stage_critic(
                stem=stem_obj["stem"],
                correct_answer_text=correct_text,
                correct_answer_concept=kernel.get("correctAnswerConcept", ""),
                distractors=distractors,
                kernel=kernel,
                target_order=target_order,
                target_difficulty=target_difficulty,
            )
            verdict = (critic or {}).get("verdict", "")
    if critic and verdict == "reject":
        return None
    # After the optional regen pass, if ANY distractor still scores < 2
    # OR adversarialOutcome == NO_DEFENSE OR STRONG_DEFENSE, refuse the
    # question. We accept "accept" or "revise_weakest"/"revise_full"
    # whose re-critic raised all distractors to >= 2 (and no critical
    # outcomes).
    if critic:
        for ds in critic.get("distractorScores") or []:
            score = int(ds.get("score", 0) or 0)
            outcome = ds.get("adversarialOutcome") or ""
            if score < 2 or outcome in ("NO_DEFENSE", "STRONG_DEFENSE"):
                return None

    # Stage 7: LENGTH PARITY (deterministic)
    distractor_texts = [d.get("text", "") for d in distractors]
    correct_text, distractor_texts, parity_info = length_parity_balance(
        correct_text, distractor_texts
    )
    # Reattach the (possibly-trimmed) texts back into distractors meta
    for d, new_text in zip(distractors, distractor_texts):
        d["text"] = new_text

    # Stage 8: IMAGE ROUTING
    image_route = stage_image_route(
        stem=stem_obj["stem"],
        image_opportunity=kernel.get("imageOpportunity", "none"),
        available_images=available_images,
    )

    # Stage 9: ASSEMBLE
    q = assemble_question(
        question_number=question_number,
        kernel=kernel,
        stem_obj=stem_obj,
        correct_text=correct_text,
        distractor_texts=distractor_texts,
        distractors_meta=distractors,
        critic_obj=critic,
        image_route=image_route,
        allocation=allocation,
        target_order=target_order,
        target_difficulty=target_difficulty,
        length_parity_info=parity_info,
        rng=rng,
    )

    # Debug artifact
    try:
        (DEBUG_DIR / f"Q{question_number:04d}.json").write_text(
            json.dumps(
                {
                    "kernel": kernel,
                    "stem_obj": stem_obj,
                    "correct_text": correct_text,
                    "distractors": distractors,
                    "critic": critic,
                    "image_route": image_route,
                    "length_parity": parity_info,
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
            except Exception as exc:
                print(f"[v5.2] Q{qn} pipeline error: {exc}", file=sys.stderr)
                q = None
            if q:
                questions.append(q)
                _update_memory(memory, q)
            else:
                print(f"[v5.2] Q{qn} skipped (pipeline rejected)", file=sys.stderr)
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
    parser = argparse.ArgumentParser(description="v5.2 pipeline smoke test")
    parser.add_argument("--allocation-file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    allocations = json.loads(Path(args.allocation_file).read_text(encoding="utf-8"))
    if not isinstance(allocations, list):
        allocations = allocations.get("allocations") or []
    normalized_payload = {"sourceFile": "smoke_test_v5_2"}
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
                "schemaVersion": "v5_2-organic",
                "sourceFormat": "lecture-slide-v5_2",
                "testTitle": "v5.2 smoke test",
                "expectedQuestionCount": sum(int(a.get("questionCount") or 0) for a in allocations),
                "actualExtractedQuestionCount": len(questions),
                "extractionWarnings": [],
                "questions": questions,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"v5.2 smoke test: produced {len(questions)} questions in {elapsed:.1f}s")
    print(f"  Output: {out_path}")
    print(f"  Debug per-Q traces under: {DEBUG_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(_smoke_test_cli())
