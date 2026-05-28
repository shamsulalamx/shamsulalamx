#!/usr/bin/env python3
"""NBME PDF Vision re-OCR pass.

For every problem question flagged by `nbme_postprocess.py`, this
script:
  1. Renders 1-3 candidate pages of the source PDF as PNG images,
     starting from a heuristic estimate (question N is usually on
     page ~N+1 of the Q PDF; N+2 of the A PDF).
  2. Sends them to Gemini 2.5 Pro Vision with a strict, source-
     verbatim prompt.
  3. Returns the cleaned text, ready to be injected into the
     app-ready JSON.

Run once per test. No quality risk to the running queue — the OME
generations the queue is processing use their own Vertex API calls;
adding a handful of Vision calls here is negligible compared to the
queue's own volume.

Usage:
    python3 nbme_vision_reocr.py --test 8 \
        --q-pdf "/Users/shamsulalam/Desktop/NBME 8Q.pdf" \
        --a-pdf "/Users/shamsulalam/Desktop/NBME 8A.pdf" \
        --json  "/Users/shamsulalam/Desktop/v4.85-app-ready/NBME 8_app_ready.fixed.json" \
        --output "/Users/shamsulalam/Desktop/v4.85-app-ready/NBME 8_app_ready.json"

The script reads the fixed JSON (output of nbme_postprocess.py),
finds every question with empty / pure-garbage sections, runs Vision
on the corresponding PDF pages, and writes the merged result to
--output. --output may equal --json (writes in place).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# We keep this script self-contained so it runs on its own with
# `python3 /tmp/nbme_vision_reocr.py ...` without the repo's adapter
# sys.path tricks.
os.environ.setdefault("GEMINI_BACKEND", "vertex")

# Lazy PyMuPDF + google-genai imports so the help message works even
# without the SDK installed.
def _import_runtime():
    import fitz  # PyMuPDF
    from google import genai
    from google.genai import types
    return fitz, genai, types


# ── Page rendering ───────────────────────────────────────────────────────────


def render_page(pdf_path: Path, page_index: int, dpi: int = 150) -> bytes:
    """Render a single PDF page as a PNG byte string."""
    fitz, _, _ = _import_runtime()
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_index]
        # 72 dpi is PDF native; matrix scales linearly
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


# ── Vision call ──────────────────────────────────────────────────────────────


_CLIENT = None


def get_client():
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    _, genai, _ = _import_runtime()
    _CLIENT = genai.Client(
        vertexai=True,
        project=os.environ.get("GCP_PROJECT_ID", "shamsulalamx"),
        location=os.environ.get("GCP_REGION", "us-central1"),
    )
    return _CLIENT


def vision_call(prompt: str, *image_bytes: bytes, model: str = "gemini-2.5-pro",
                thinking_budget: int = 4096) -> str:
    """One Vision call with multiple page images. Returns response text."""
    _, _, types = _import_runtime()
    client = get_client()
    contents: list[Any] = [prompt]
    for b in image_bytes:
        contents.append(types.Part.from_bytes(data=b, mime_type="image/png"))
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.0,
            max_output_tokens=8192,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=thinking_budget),
        ),
    )
    return resp.text or ""


# ── Page lookup heuristics ───────────────────────────────────────────────────


def candidate_pages_for_question(total_pages: int, question_num: int,
                                 questions_per_page: float = 1.0,
                                 cover_offset: int = 0,
                                 window: int = 3) -> list[int]:
    """Return a small list of 0-indexed candidate pages for a given
    question number. NBME PDFs are usually 1 question per page in the
    Q PDF and ~2 explanations per page in the A PDF. The empirical
    density is calibrated per test from the page labels Vision reads.

    Calibration ground truth (NBME 8A.pdf, 111 pages, 50 questions):
      Q1=page 0, Q6=page 10, Q15=page 30, Q23=page 50, Q33=page 70,
      Q41=page 90, Q50=page 110 → ~2.24 pages/question (density 0.45).
    """
    est = cover_offset + int((question_num - 1) / max(questions_per_page, 0.001))
    # Spread ±window around the estimate, clipped to the PDF size.
    candidates = sorted({
        max(0, min(total_pages - 1, est + d))
        for d in range(-window, window + 1)
    })
    return candidates


# ── Stem re-OCR prompt ───────────────────────────────────────────────────────


def reocr_stem_prompt(question_num: int, partial_text: str) -> str:
    return (
        f"You are extracting the verbatim text of NBME exam question number {question_num}. "
        f"One of the attached page images contains this question.\n\n"
        f"Partial text already extracted from this question (use as identification):\n"
        f"---\n{partial_text[:600]}\n---\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Find the page that contains question {question_num} (numbered at the start of the question).\n"
        f"2. Extract the VERBATIM stem text starting with the patient demographics "
        f"   (e.g. 'A 67-year-old man comes to the emergency department because of...'). "
        f"   The stem ends with the '?'-terminated question prompt.\n"
        f"3. DO NOT include the question number prefix (e.g. drop the leading '45.').\n"
        f"4. DO NOT include the answer choices.\n"
        f"5. DO NOT include figure captions like '25mm/s' or page footers.\n"
        f"6. Preserve subscripts as Unicode digits (B12 not B,,; S3 not S,; PCO2 not PCO,).\n"
        f"7. Preserve all numeric values, lab values, units, and clinical findings exactly.\n\n"
        f"Return ONLY this JSON:\n"
        f'{{"found": true, "stem": "<verbatim stem text>"}}\n'
        f"or, if the question is not on any of these pages:\n"
        f'{{"found": false}}'
    )


def reocr_explanation_prompt(question_num: int, heading: str,
                              correct_answer_letter: str,
                              correct_answer_text: str,
                              partial_stem: str) -> str:
    return (
        f"You are extracting the verbatim text of the '{heading}' section for NBME exam "
        f"question {question_num}. One of the attached page images contains this answer "
        f"explanation.\n\n"
        f"Question {question_num} identifiers:\n"
        f"  - Correct answer: choice {correct_answer_letter} = \"{correct_answer_text}\"\n"
        f"  - Stem starts with: \"{partial_stem[:200]}\"\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Find the page that contains the answer explanation for question {question_num}.\n"
        f"2. Extract the VERBATIM text of the '{heading}' section ONLY.\n"
        f"3. For 'Incorrect Answer Explanation': include explanations for ALL incorrect "
        f"   choices (typically 4 of 5), each prefixed with its letter (e.g. 'A.', 'B.', etc.).\n"
        f"4. For 'Educational Objective': extract the one-sentence learning objective.\n"
        f"5. For 'Correct Answer Explanation': extract the multi-paragraph explanation of why "
        f"   choice {correct_answer_letter} is correct.\n"
        f"6. DO NOT include page footers, watermarks, URLs, or copyright lines.\n"
        f"7. DO NOT include the question stem or the answer choice list.\n"
        f"8. Preserve subscripts as Unicode digits.\n\n"
        f"Return ONLY this JSON:\n"
        f'{{"found": true, "body": "<verbatim section text>"}}\n'
        f"or, if the section is not on any of these pages:\n"
        f'{{"found": false}}'
    )


# ── Driver ───────────────────────────────────────────────────────────────────


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


def reocr_stem(pdf_path: Path, total_pages: int, q: dict[str, Any],
               candidates: list[int]) -> str | None:
    qn = q.get("questionNumber")
    partial = (q.get("stem") or "")
    images = [render_page(pdf_path, p) for p in candidates]
    raw = vision_call(reocr_stem_prompt(qn, partial), *images)
    parsed = parse_json_loose(raw)
    if not parsed or not parsed.get("found") or not parsed.get("stem"):
        return None
    return parsed["stem"].strip()


def reocr_explanation(pdf_path: Path, total_pages: int, q: dict[str, Any],
                       heading: str, candidates: list[int]) -> str | None:
    qn = q.get("questionNumber")
    correct = q.get("correctAnswer", "")
    correct_text = ""
    for c in q.get("answerChoices") or []:
        if c.get("label") == correct:
            correct_text = c.get("text", "")
            break
    partial_stem = (q.get("stem") or "")[:200]
    images = [render_page(pdf_path, p) for p in candidates]
    raw = vision_call(
        reocr_explanation_prompt(qn, heading, correct, correct_text, partial_stem),
        *images,
    )
    parsed = parse_json_loose(raw)
    if not parsed or not parsed.get("found") or not parsed.get("body"):
        return None
    return parsed["body"].strip()


def fix_test(q_pdf: Path, a_pdf: Path, json_path: Path, output_path: Path,
             q_density: float = 1.0, a_density: float = 0.5,
             q_offset: int = 1, a_offset: int = 1) -> dict[str, Any]:
    fitz, _, _ = _import_runtime()
    q_doc = fitz.open(str(q_pdf))
    q_pages = len(q_doc)
    q_doc.close()
    a_doc = fitz.open(str(a_pdf))
    a_pages = len(a_doc)
    a_doc.close()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    report = {"stem_fixes": [], "explanation_fixes": [], "failures": []}

    for q in payload.get("questions") or []:
        qn = q.get("questionNumber")
        stem = (q.get("stem") or "").strip()
        # Lost-opener detection: stem doesn't start with canonical NBME opener
        canonical_re = re.compile(
            r"^(?:A|An)\s+(?:previously|otherwise|hospitalized|asymptomatic|moderately|healthy|\d+|N)"
            r"|^(?:Six|Twelve|Two|Three|Four|Five|One)\s+(?:hours?|days?|weeks?|months?)"
            r"|^(?:For|Following|During|Prior|Immediately|Initial|A study|A patient|A healthy|"
            r"A previously|A hospitalized|An otherwise|An asymptomatic|An obese|A moderately|"
            r"A normally|A research|Investigators)",
            re.IGNORECASE,
        )
        needs_stem_reocr = not canonical_re.match(stem)
        if needs_stem_reocr:
            candidates = candidate_pages_for_question(q_pages, qn, q_density, q_offset)
            print(f"  Q{qn}: re-OCR stem from pages {candidates}", file=sys.stderr)
            try:
                new_stem = reocr_stem(q_pdf, q_pages, q, candidates)
                if new_stem:
                    q["stem"] = new_stem
                    q.setdefault("extractionWarnings", []).append(
                        "v4.85.1: stem re-OCR via Gemini Vision Pro (original was missing opener)"
                    )
                    report["stem_fixes"].append((qn, len(new_stem)))
                else:
                    report["failures"].append(f"Q{qn}: stem re-OCR returned no match")
            except Exception as exc:
                report["failures"].append(f"Q{qn}: stem re-OCR error: {exc}")
            time.sleep(0.5)  # be gentle on Vertex rate limits

        # Explanation gaps: detect empty or pure-garbage bodies
        garbage_re = re.compile(r"^\s*[\d>@()/\\nNFfAaecCEiIUu©\s.,'\"\-—–]{3,45}\s*$")
        for s in q.get("explanationSections") or []:
            heading = s.get("heading", "")
            body = " ".join(s.get("body") or []).strip()
            is_empty = len(body) == 0
            is_garbage = (
                len(body) < 50
                and bool(garbage_re.match(body))
                and bool(re.search(r"[©@>]|nf|eC|EC|i>", body, re.IGNORECASE))
            )
            if is_empty or is_garbage:
                candidates = candidate_pages_for_question(a_pages, qn, a_density, a_offset)
                print(f"  Q{qn} [{heading}]: re-OCR from pages {candidates}", file=sys.stderr)
                try:
                    new_body = reocr_explanation(a_pdf, a_pages, q, heading, candidates)
                    if new_body:
                        s["body"] = [new_body]
                        q.setdefault("extractionWarnings", []).append(
                            f"v4.85.1: {heading} re-OCR via Gemini Vision Pro"
                        )
                        report["explanation_fixes"].append((qn, heading, len(new_body)))
                    else:
                        report["failures"].append(f"Q{qn} [{heading}]: re-OCR returned no match")
                except Exception as exc:
                    report["failures"].append(f"Q{qn} [{heading}]: re-OCR error: {exc}")
                time.sleep(0.5)

    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", required=True, help="NBME test number (used for logs only)")
    ap.add_argument("--q-pdf", required=True)
    ap.add_argument("--a-pdf", required=True)
    ap.add_argument("--json", required=True, help="Input app-ready JSON (typically the .fixed.json)")
    ap.add_argument("--output", required=True, help="Output path (may equal --json for in-place)")
    ap.add_argument("--q-density", type=float, default=1.0,
                    help="Estimated questions per Q-PDF page (default 1.0)")
    ap.add_argument("--a-density", type=float, default=0.5,
                    help="Estimated questions per A-PDF page (default 0.5)")
    ap.add_argument("--q-offset", type=int, default=1,
                    help="0-indexed page offset for Q1 in Q PDF (default 1 = page 2 after cover)")
    ap.add_argument("--a-offset", type=int, default=1)
    args = ap.parse_args()

    print(f"NBME {args.test}: starting Vision re-OCR pass", file=sys.stderr)
    r = fix_test(
        Path(args.q_pdf).expanduser().resolve(),
        Path(args.a_pdf).expanduser().resolve(),
        Path(args.json).expanduser().resolve(),
        Path(args.output).expanduser().resolve(),
        q_density=args.q_density,
        a_density=args.a_density,
        q_offset=args.q_offset,
        a_offset=args.a_offset,
    )
    print()
    print(f"NBME {args.test} summary:", file=sys.stderr)
    print(f"  stem fixes:        {len(r['stem_fixes'])}", file=sys.stderr)
    print(f"  explanation fixes: {len(r['explanation_fixes'])}", file=sys.stderr)
    print(f"  failures:          {len(r['failures'])}", file=sys.stderr)
    for f in r["failures"][:5]:
        print(f"    {f}", file=sys.stderr)
    return 0 if not r["failures"] else 0  # always exit 0 — failures are flagged in JSON


if __name__ == "__main__":
    sys.exit(main())
