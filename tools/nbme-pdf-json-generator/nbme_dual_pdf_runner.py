#!/usr/bin/env python3
"""
nbme_dual_pdf_runner.py — single-entrypoint NBME orchestrator (v4.61).

Replaces the prior multi-stage NBME wrapper for BIC. Handles three input
modes automatically:

  • Dual PDF (Q + A separate): auto-detect roles, join by question number.
  • Q-only PDF: extract stems + choices, Gemini generates explanations
    based on the canonical nbme-gemini-json-v3 schema.
  • Combined PDF (Q + A inline): keeps the v4.60 path for legacy
    inline-answer formats.

Auto-detection layers (all decided before any Gemini token is spent):

  1. File role (Q vs A) — filename keywords + content sniff.
  2. Mode (combined vs Q-only vs dual) — file count + inline-answer
     presence.
  3. A-PDF format (NBME interface vs plain numbered text) — presence of
     `Item N of M` chrome.
  4. Screenshot mode per PDF — fraction of pages where pdfplumber returns
     non-trivial text. If <50% pass, the PDF is treated as a screenshot.

Figure detection (smart-trigger to keep cost down):
  • Only fires Gemini multimodal on a per-question basis when EITHER the
    stem contains image-language phrases OR PyMuPDF reports embedded
    raster images on the page.
  • Skips silently when neither signal fires — text-only questions get
    no figure call.
  • Aspect-ratio guard (0.30–3.00) rejects whole-page-as-image traps on
    screenshot pages.

BIC orchestration: BIC iterates over the manifest's input list, so this
script is invoked once per file. A completion marker in the job dir
deduplicates work — the first invocation does the orchestration, every
subsequent invocation no-ops with exit 0.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# v4.79: Vertex migration — reuse _uw._gemini_client() factory.
_UW_DIR = SCRIPT_DIR.parent / "uworld-notes-question-generator"
if str(_UW_DIR) not in sys.path:
    sys.path.insert(0, str(_UW_DIR))
import generate_uworld_questions as _uw  # noqa: E402
try:
    from google.genai import types as _genai_types  # noqa: E402
    _GENAI_SDK_AVAILABLE = True
except ImportError:
    _GENAI_SDK_AVAILABLE = False

import extract_pdfs  # noqa: E402  — reuses OCR / chunker / Gemini text-norm
import nbme_extract_figures  # noqa: E402  — reuses CV figure extractor

GEMINI_MODEL = "gemini-2.5-flash"          # default for extraction / completion / figure-detection
POLISH_MODEL = "gemini-2.5-pro"            # v4.63: canonical-polish quality bump (reviewPearl, retrievalTag, educationalObjective)
CRITIC_MODEL = "gemini-2.5-flash"          # v4.63: quick LLM critic of polish output
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# v4.63: critic-and-regenerate is on by default. Disable with NBME_CRITIC_ENABLED=0.
CRITIC_ENABLED = os.environ.get("NBME_CRITIC_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off", "")

# ── Auto-detect heuristics ────────────────────────────────────────────────────

# Filename keywords scored: positive = Q-PDF, negative = A-PDF. Accept both
# the full word ("Questions" / "Answers") and the conventional one-letter
# shorthand ("…_Q.pdf" / "…_A.pdf" / "… Q.pdf" / "… A.pdf" / "…3Q.pdf"),
# which the user uses for selective test extracts. v4.84: the previous
# lookbehind only accepted `_`, space, or `-` before Q/A — so files like
# "NBME 8Q.pdf" failed to detect because of the digit before Q. Widened to
# also accept digit boundaries so "NBME 3Q.pdf" / "8A.pdf" detect correctly.
_Q_KEYWORDS = re.compile(
    r"(?:\b(?:questions?|stems?)\b|(?:[_\s\-]|\d)Q(?=[._\s\-]|$))",
    re.IGNORECASE,
)
_A_KEYWORDS = re.compile(
    r"(?:\b(?:answers?|key|explanations?)\b|(?:[_\s\-]|\d)A(?=[._\s\-]|$))",
    re.IGNORECASE,
)

# Content sniff — phrases that strongly indicate an A-PDF (or inline answers
# inside a combined PDF). Used both for role detection AND combined-mode
# detection.
_A_CONTENT_PHRASES = re.compile(
    r"\b(correct\s+answer|educational\s+objective|incorrect\s+answers?)\b",
    re.IGNORECASE,
)

# Tightened image-language regex (v4.61 follow-up). The original ran too
# hot on this NBME Self-Assessment PDF — 47 of 49 Gemini multimodal calls
# returned "no figure found." We now require the stem to *specifically*
# reference a figure rather than mention a generic word like "image" or
# "chart." Real clinical questions that need an image attached almost
# always use one of these specific phrases.
_IMAGE_LANGUAGE_RE = re.compile(
    r"\b("
    r"shown\s+(above|below|in\s+the\s+(image|figure|photograph))"
    r"|the\s+(photograph|radiograph|chest\s+x[-\s]?ray|abdominal\s+x[-\s]?ray|"
        r"ECG|EKG|electrocardiogram|histology\s+slide|histologic\s+section|"
        r"gross\s+specimen|dermatology\s+(image|photograph)|skin\s+lesion\s+image|"
        r"angiogram|venogram|ultrasound|CT\s+scan|MRI(?:\s+image)?|biopsy(?:\s+specimen)?|"
        r"tracing|peripheral\s+blood\s+smear|fundoscopy|funduscopic\s+(image|examination))"
    r"|illustrated\s+(above|below)"
    r"|depicted\s+(above|below|in\s+the\s+(image|figure))"
    r"|as\s+seen\s+in\s+the\s+(image|figure|photograph)"
    r")\b",
    re.IGNORECASE,
)

# A-PDF NBME interface signature — same anchor used by extract_pdfs for Q-PDF
# chunking. Presence = NBME interface; absence = plain numbered text.
_NBME_INTERFACE_RE = re.compile(r"\bItem\s+\d+\s+of\s+\d+\b", re.IGNORECASE)

# Per-page screenshot threshold. If pdfplumber returns <100 useful chars on
# >50% of pages, we treat the PDF as a screenshot.
_SCREENSHOT_PAGE_CHAR_THRESHOLD = 100
_SCREENSHOT_PDF_RATIO = 0.50

# Aspect-ratio guard from v4.60.
AUTO_ATTACH_MIN_ASPECT = nbme_extract_figures.AUTO_ATTACH_MIN_ASPECT
AUTO_ATTACH_MAX_ASPECT = nbme_extract_figures.AUTO_ATTACH_MAX_ASPECT

# Cost ceiling guard (rough — counts Gemini calls and bails if too many).
_HARD_CALL_CEILING = 500


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[WARN] {msg}", flush=True, file=sys.stderr)


# ── BIC integration ──────────────────────────────────────────────────────────

def discover_job_inputs() -> list[Path]:
    """Read BIC manifest from BIC_JOB_OUTPUT_ROOT and return all input paths."""
    root = os.environ.get("BIC_JOB_OUTPUT_ROOT")
    job_id = os.environ.get("BIC_JOB_ID")
    if not root:
        return []
    root_path = Path(root)
    candidate = (root_path / f"{job_id}.json") if job_id else None
    if not candidate or not candidate.exists():
        manifests = sorted(root_path.glob("batch-*.json"))
        if not manifests:
            return []
        candidate = manifests[0]
    try:
        manifest = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return []
    inputs = manifest.get("inputs") or []
    paths: list[Path] = []
    for entry in inputs:
        if isinstance(entry, dict) and entry.get("path"):
            p = Path(str(entry["path"])).expanduser()
            if p.exists():
                paths.append(p)
        elif isinstance(entry, str):
            p = Path(entry).expanduser()
            if p.exists():
                paths.append(p)
    return paths


def completion_marker_path() -> Path | None:
    root = os.environ.get("BIC_JOB_OUTPUT_ROOT")
    return (Path(root) / "nbme_orchestration_done.flag") if root else None


# ── File role detection ──────────────────────────────────────────────────────

def detect_file_role(path: Path) -> tuple[str, float, str]:
    """Return (role, confidence, reasoning).

    role ∈ {"q", "a", "combined", "unknown"}.
    confidence ∈ [0, 1].
    """
    name = path.name
    name_score_q = 1 if _Q_KEYWORDS.search(name) else 0
    name_score_a = 1 if _A_KEYWORDS.search(name) else 0

    # Content sniff: read first ~6 KB of text via pdfplumber for a cheap
    # signal. We deliberately don't OCR — that's done later if needed.
    text_sample = ""
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages_to_sniff = pdf.pages[:3]
            text_sample = "\n".join((p.extract_text() or "") for p in pages_to_sniff)
    except Exception:
        text_sample = ""

    a_phrases_found = bool(_A_CONTENT_PHRASES.search(text_sample))
    nbme_interface = bool(_NBME_INTERFACE_RE.search(text_sample))

    # Heuristic: if BOTH stems-with-choices pattern AND answer phrases are
    # present, it's likely a combined PDF.
    has_stem_pattern = bool(re.search(r"\b\d+\.\s+A\s+\d+-year-old\b", text_sample, re.IGNORECASE))

    reasoning_parts: list[str] = []
    reasoning_parts.append(f"filename q={name_score_q} a={name_score_a}")
    reasoning_parts.append(f"a_phrases={a_phrases_found} nbme_iface={nbme_interface} stem_pattern={has_stem_pattern}")

    if name_score_q and not name_score_a and not a_phrases_found:
        return "q", 0.95, "; ".join(reasoning_parts)
    if name_score_a and not name_score_q and a_phrases_found:
        return "a", 0.95, "; ".join(reasoning_parts)
    if has_stem_pattern and a_phrases_found:
        return "combined", 0.80, "; ".join(reasoning_parts)
    if a_phrases_found and not has_stem_pattern:
        return "a", 0.70, "; ".join(reasoning_parts)
    if has_stem_pattern and not a_phrases_found:
        return "q", 0.70, "; ".join(reasoning_parts)
    if name_score_q:
        return "q", 0.55, "; ".join(reasoning_parts)
    if name_score_a:
        return "a", 0.55, "; ".join(reasoning_parts)
    return "unknown", 0.0, "; ".join(reasoning_parts)


def detect_mode(inputs: list[Path]) -> tuple[str, dict[str, Path | None]]:
    """Return (mode, {'q': path or None, 'a': path or None}).

    mode ∈ {"dual", "q_only", "combined", "a_only"}.
    a_only is rejected upstream — we keep the label for explicit error.
    """
    roles: list[tuple[Path, str, float]] = []
    for p in inputs:
        role, conf, reasoning = detect_file_role(p)
        log(f"  role detect: {p.name} → {role} (conf={conf:.2f}) [{reasoning}]")
        roles.append((p, role, conf))

    q_files = [(p, c) for p, r, c in roles if r == "q"]
    a_files = [(p, c) for p, r, c in roles if r == "a"]
    combined_files = [(p, c) for p, r, c in roles if r == "combined"]
    unknown_files = [(p, c) for p, r, c in roles if r == "unknown"]

    if len(inputs) == 1:
        only = inputs[0]
        if combined_files:
            return "combined", {"q": only, "a": None}
        if q_files:
            return "q_only", {"q": only, "a": None}
        if a_files:
            return "a_only", {"q": None, "a": only}
        # Unknown single file — treat as combined (safest fallback,
        # matches v4.60 behavior).
        return "combined", {"q": only, "a": None}

    if len(inputs) >= 2:
        # Prefer the highest-confidence Q and A.
        q = max(q_files, key=lambda x: x[1])[0] if q_files else None
        a = max(a_files, key=lambda x: x[1])[0] if a_files else None
        # If both detected explicitly, dual.
        if q and a:
            return "dual", {"q": q, "a": a}
        # Q + "combined": combined-classified file has stems AND answer phrases
        # but the OTHER uploaded file looks like Q-only. The user intended
        # this as a dual pair — treat combined-classified file as A-PDF.
        if q and combined_files:
            return "dual", {"q": q, "a": max(combined_files, key=lambda x: x[1])[0]}
        # A + "combined": symmetric case — combined file becomes the Q-PDF
        # (it has stems we can extract) and the explicit "a" file is the
        # answer key.
        if a and combined_files:
            return "dual", {"q": max(combined_files, key=lambda x: x[1])[0], "a": a}
        # If we have Q + unknown, treat unknown as A.
        if q and unknown_files:
            return "dual", {"q": q, "a": unknown_files[0][0]}
        # If we have A + unknown, treat unknown as Q.
        if a and unknown_files:
            return "dual", {"q": unknown_files[0][0], "a": a}
        # If both unknown, pick the larger as Q (assume Q has more text/figures).
        if len(unknown_files) >= 2:
            sorted_by_size = sorted(unknown_files, key=lambda x: x[0].stat().st_size, reverse=True)
            return "dual", {"q": sorted_by_size[0][0], "a": sorted_by_size[1][0]}
        # If we have two combined PDFs, treat the SMALLER as A-PDF (less
        # content) and the larger as Q-PDF.
        if len(combined_files) >= 2:
            sorted_by_size = sorted(combined_files, key=lambda x: x[0].stat().st_size, reverse=True)
            return "dual", {"q": sorted_by_size[0][0], "a": sorted_by_size[1][0]}
        if combined_files:
            return "combined", {"q": combined_files[0][0], "a": None}

    return "combined", {"q": inputs[0] if inputs else None, "a": None}


# ── Per-page screenshot detection ────────────────────────────────────────────

def detect_screenshot_mode(pdf_path: Path) -> tuple[bool, dict[str, Any]]:
    """Return (is_screenshot, diagnostics).

    A PDF is "screenshot mode" when pdfplumber returns <100 useful chars
    on more than 50% of pages. We check the FIRST 10 pages to keep this
    cheap.
    """
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            pages = pdf.pages[:10]
            char_counts = [len((p.extract_text() or "").strip()) for p in pages]
    except Exception as exc:
        return True, {"error": f"pdfplumber open failed: {exc}", "char_counts": []}
    if not char_counts:
        return True, {"reason": "no pages sampled", "char_counts": []}
    text_pages = sum(1 for c in char_counts if c >= _SCREENSHOT_PAGE_CHAR_THRESHOLD)
    text_ratio = text_pages / len(char_counts)
    is_screenshot = text_ratio < (1 - _SCREENSHOT_PDF_RATIO)
    return is_screenshot, {
        "pagesScanned": len(char_counts),
        "textPages": text_pages,
        "textRatio": round(text_ratio, 2),
        "charCounts": char_counts,
        "decision": "screenshot" if is_screenshot else "text-extractable",
    }


# ── A-PDF parsing (NBME interface + plain text) ──────────────────────────────

_A_QUESTION_HEADER = re.compile(
    r"(?:"
    r"\bItem\s+(\d+)\s+of\s+\d+\b"          # NBME interface header
    r"|^\s*(\d+)[.)]\s+(?=Correct|Answer|The correct|[A-Z])"  # plain numbered
    r"|\bAnswer\s+(\d+)[:.]"                # "Answer 1:" style
    r"|\bQuestion\s+(\d+)[:.]"              # "Question 1:" style
    r")",
    re.MULTILINE | re.IGNORECASE,
)

# Allow A-N letter labels — NBME matching sets occasionally have 12+
# options (q20, q26 confirmed K/L; A-N gives headroom). Extended option
# sets also appear in medication-selection questions.
# v4.84: NBME 3A PDF prints the header as "CorrectAnswer: H" (no space
# between "Correct" and "Answer") on every item. The previous `\s+` was
# too strict and forced every NBME-3 answer onto the Gemini-completion
# fallback path, which then guessed wrong on Q26 (J vs the printed H).
# `\s*` accepts both the space-separated and concatenated OCR variants.
_CORRECT_ANSWER_RE = re.compile(
    r"\bCorrect\s*Answer\s*[:.]?\s*([A-N])\b",
    re.IGNORECASE,
)


def parse_a_pdf(text: str) -> dict[int, dict[str, str]]:
    """Return {question_number: {correctAnswer, explanationText}}.

    Handles both NBME interface format (`Item N of M`) and plain numbered
    text (`1. Correct answer: E. ...`). The join key is the question
    number, so out-of-order A-PDFs (q13 → q4 → q28) are handled naturally.
    """
    headers = list(_A_QUESTION_HEADER.finditer(text))
    if not headers:
        return {}
    by_number: dict[int, dict[str, str]] = {}
    for idx, m in enumerate(headers):
        nums = [g for g in m.groups() if g is not None]
        if not nums:
            continue
        try:
            q_num = int(nums[0])
        except ValueError:
            continue
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
        block = text[m.start():end]
        ans_match = _CORRECT_ANSWER_RE.search(block)
        correct = ans_match.group(1).upper() if ans_match else ""
        # Explanation = block after the "Correct Answer: X" line, stripped.
        if ans_match:
            explanation = block[ans_match.end():].strip()
        else:
            # No explicit "Correct Answer" — use everything after the header.
            explanation = text[m.end():end].strip()
        # v4.61 follow-up: stronger chrome scrub via _clean_explanation_chrome.
        # Catches "Exam Section :", "Item N of M", OCR noise fragments, etc.
        explanation = _clean_explanation_chrome(explanation)
        if q_num in by_number and len(by_number[q_num]["explanationText"]) >= len(explanation):
            continue  # Keep the longer of two candidates.
        by_number[q_num] = {
            "correctAnswer": correct,
            "explanationText": explanation,
        }
    return by_number


# ── Q-PDF chunk → structured fields (deterministic) ──────────────────────────

# NBME Self-Assessment Q-PDF choice format: `0 A) Chronic migraines`.
# The leading `0 ` is the OCR rendering of the empty radio-button circle.
# Some PDFs render the same widget as `o `, `O `, `(○) `, or `■ `.
# Accept any single non-letter prefix char (with optional whitespace) before
# the labelled letter. The lookahead `(?=[A-Z]|[a-z])` on the choice text
# rejects accidental matches inside the stem like "as B) is shown".
_CHOICE_LINE_RE = re.compile(
    r"^[\s0Oo■►▪◯●◦·*~\(\)\[\]]*([A-N])\)\s+(.+?)$",
    re.MULTILINE,
)

# NBME UI chrome lines to strip from the stem.
_STEM_CHROME_PATTERNS = [
    re.compile(r"^.*?Item\s+\d+\s+of\s+\d+.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^.*?Mark\s+Medicine\s+Self[-\s]?Assessment.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^.*?Time\s+Remaining\b.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*[■►▪◯●]+\s*$", re.MULTILINE),
    re.compile(r"^\s*\d+\s*hr\s+\d+\s*min\s+\d+\s*sec\s*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*https?://\S+\s*$", re.MULTILINE),
    re.compile(r"^.*?(?:Previous\s+)?Next\s+(?:Score\s+Report\s+)?Lab\s+Values\s+Calculator.*$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\s*[~`r,p\\\s]+\s*$", re.MULTILINE),  # OCR-noise lines like "r r ,", "~ ~", "p ,"
]


def _clean_stem_chrome(text: str) -> str:
    for pat in _STEM_CHROME_PATTERNS:
        text = pat.sub("", text)
    # Collapse blank lines and strip the leading stem-number prefix
    # ("1. ", "~ 1. ", "* 1. ", etc.) introduced by the NBME interface.
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^\s*[~*•·●◦‣■►▪]?\s*\d+[.)]\s+", "", text.strip())
    return text.strip()


# v4.61 follow-up: NBME-specific chrome and OCR noise patterns that leak
# into A-PDF explanation text when the chunker's end-boundary doesn't
# perfectly clip page breaks. The first live BIC run on Internal Medicine 3
# surfaced these explicitly:
#   ". \" ' , r-- r ,,, ~ Exam Section :"
#   "nics. r ,,, ~ Exam Section :"
#   "Apply the tested clinical reasoning."  (placeholder leaking)
# These patterns scrub them out.
_EXPLANATION_CHROME_PATTERNS = [
    re.compile(r"Exam\s+Section\s*[:.]?\s*(Item\s+\d+\s+of\s+\d+.*)?$", re.MULTILINE),
    re.compile(r"National\s+Board\s+of\s+Medical\s+Examiners", re.IGNORECASE),
    re.compile(r"Mark\s+Medicine\s+Self[-\s]?Assessment", re.IGNORECASE),
    re.compile(r"Time\s+Remaining\s*[:.]?\s*\d+\s*hr\s+\d+\s*min\s+\d+\s*sec", re.IGNORECASE),
    re.compile(r"\d+\s*hr\s+\d+\s*min\s+\d+\s*sec", re.IGNORECASE),
    re.compile(r"https?://\S+"),
    re.compile(r"\b(?:Next|Score\s+Report|Lab\s+Values|Calculator|Help|Pause|Previous|Review|Mark|Flag|Hint)\b"),
    # OCR-noise lines: "r r ,", "p ,", "~ ~", "r ,,,", "\" ' ,", "r--", "p---",
    # plus stray punctuation/single-letter fragments left by the OCR layer.
    re.compile(r"^\s*[~`r,p\".'\-_\\\s]+\s*$", re.MULTILINE),
    re.compile(r"\br[-]+\s*r\b", re.IGNORECASE),
    re.compile(r"\bp[-]+\b", re.IGNORECASE),
    re.compile(r"~\s*~"),
    re.compile(r"r\s+,\s*,\s*,"),
    re.compile(r"\"\s*'\s*,"),
    # Header banner trailing fragments — "■" checkbox, "Item N" mid-line.
    re.compile(r"\bItem\s+\d+\s+of\s+\d+\b", re.IGNORECASE),
    re.compile(r"■+"),
    # Page-break leakage: any line that starts with the next question's
    # stem number ("28. A 36-year-old...") AFTER our current explanation
    # — usually means the chunker's boundary missed and we crossed pages.
]


def _clean_explanation_chrome(text: str) -> str:
    """Apply NBME-specific chrome + OCR noise scrubbing to A-PDF explanation
    text. v4.61 follow-up after first live run surfaced widespread chrome
    leakage like 'Exam Section :' and OCR fragments like 'r ,,, ~'.
    """
    for pat in _EXPLANATION_CHROME_PATTERNS:
        text = pat.sub("", text)
    # Collapse multiple newlines and runs of whitespace.
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Strip dangling fragment characters left by OCR around words.
    text = re.sub(r"\s+,\s+", ", ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


# ── Suspicion detection (v4.61 follow-up) ────────────────────────────────────
# When deterministic parse_q_chunk returns something that looks wrong, we
# escalate to Gemini multimodal extraction. Signals computed offline,
# zero Gemini cost.

_MATCHING_SET_RE = re.compile(
    r"response\s+options.{0,80}items.{0,40}same",
    re.IGNORECASE | re.DOTALL,
)

_TABULAR_HEADER_HINTS = re.compile(
    r"\b(Specific\s+Gravity|/?hpf|Casts|Hemoglobin|Hematocrit|MCV|Bilirubin\s+Total|"
    r"Direct\s+Bilirubin|ALT|AST|Alkaline\s+Phosphatase|Sodium\s+Potassium|"
    r"Glucose\s+Protein|Urinalysis)\b",
    re.IGNORECASE,
)


def detect_chunk_suspicion(chunk_text: str, stem: str, choices: list[dict[str, str]]) -> tuple[bool, list[str]]:
    """Return (suspicious, signals).

    Any signal flips us to Gemini multimodal page extraction. Free to compute.
    """
    signals: list[str] = []
    if _MATCHING_SET_RE.search(chunk_text):
        signals.append("matching_set_instruction")
    # Any choice whose text contains another labelled letter (e.g. " F) ")
    # is a strong sign of two-column layout where the second column got
    # absorbed into the first column's text.
    if any(re.search(r"\s[A-N]\)\s", (c["text"] or "")) for c in choices):
        signals.append("multi_column_choice_leakage")
    if 1 <= len(choices) <= 3:
        signals.append("too_few_choices")
    if len(choices) > 10:
        signals.append("too_many_choices")
    if len(stem.strip()) < 100 and len(chunk_text) > 500:
        signals.append("stem_too_short")
    if choices:
        avg_len = sum(len(c["text"]) for c in choices) / len(choices)
        if avg_len < 8:
            signals.append("choice_text_too_short")
        # Tabular row hint: choice text looks like multiple space-separated values
        # rather than English prose.
        digit_heavy = sum(1 for c in choices if re.search(r"\b\d+(\.\d+)?\b.*\b\d+(\.\d+)?\b", c["text"]))
        if choices and digit_heavy >= len(choices) - 1:
            signals.append("choices_look_tabular")
    if _TABULAR_HEADER_HINTS.search(chunk_text):
        # Header phrase present — could be a tabular question OR a lab-values
        # block inside a stem. Treat as suspicious only if choices ALSO look
        # tabular (already added above) or if no choices were extracted.
        if "choices_look_tabular" in signals or not choices:
            signals.append("tabular_header_present")
    return (len(signals) > 0), signals


def deterministic_multi_column_parse(chunk_text: str) -> dict[str, Any] | None:
    """v4.61 follow-up: deterministic recovery for multi-column / matching-set
    layouts that defeat the standard `_CHOICE_LINE_RE` regex.

    Finds ALL `[A-N])` markers in the chunk text (not just line-anchored),
    splits the text between consecutive markers, and treats each region as
    one choice. For matching-set pages, also locates the per-item stem that
    appears AFTER the shared choice block (numbered like "28. A 36-year-old...").

    Returns {stem, choices} or None when the layout doesn't look multi-column.
    """
    # Letter-marker regex: lookbehind ensures we don't match inside words like
    # "stage A) condition". Must be followed by whitespace.
    markers = list(re.finditer(r"(?<![A-Za-z0-9])([A-N])\)\s+", chunk_text))
    if len(markers) < 4:
        return None

    # Per-choice text: from this marker's end to the next marker's start,
    # cut at newline so we don't bleed into the next visual row.
    raw_choices: list[dict[str, str]] = []
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(chunk_text)
        segment = chunk_text[m.end():end]
        # Stop at newline (single line per choice in two-column layout).
        line = segment.split("\n", 1)[0].strip()
        # Strip trailing OCR-bubble noise. The empty-radio-button glyph
        # gets OCR'd as "0", "o", "O", "Q", "*", "•", or "■" depending on
        # font + scan quality. Strip whichever variant trails the choice
        # text so we don't ship "Cellulitis O" or "Cellulitis 0".
        line = re.sub(r"[\s0OoQ■►▪◯●◦·*~]+$", "", line).strip()
        # Filter degenerate choices whose extracted text is only a single
        # bubble character / digit / blank (q20 had an OCR-empty F slot
        # whose text was just "0" — meaningless on its own).
        if not line or re.fullmatch(r"[\s0OoQ■►▪◯●◦·*~]+", line):
            continue
        if len(line) < 2:
            continue
        raw_choices.append({"label": m.group(1).upper(), "text": line})

    # Dedupe by label, keep first, then sort alphabetically so the
    # rendered output matches the on-page reading order A → J even when
    # we discovered them in left-column / right-column / left-column
    # ordering during the scan.
    seen: set[str] = set()
    choices: list[dict[str, str]] = []
    for c in raw_choices:
        if c["label"] in seen:
            continue
        seen.add(c["label"])
        choices.append(c)
    choices.sort(key=lambda c: c["label"])

    # Try to find a matching-set stem AFTER the choices block. Looks like
    # "28. A 36-year-old man comes to the physician...". We scan from after
    # the LAST marker's choice text to the chunk end.
    last_marker = markers[-1]
    last_choice_end = last_marker.end() + (
        chunk_text[last_marker.end():].split("\n", 1)[0].__len__()
    )
    rest = chunk_text[last_choice_end:]
    stem: str | None = None
    stem_m = re.search(
        r"^\s*\d+[.)]\s+(.+?)(?=\n\s*(?:[~rp]\s*[,]?|https?://|Item\s+\d+\s+of)\b|\Z)",
        rest,
        re.MULTILINE | re.DOTALL,
    )
    if stem_m:
        stem = stem_m.group(1).strip()
        # Strip leading OCR-bubble noise ("0 ", "0\n", "* ", etc.) the same
        # way `_clean_stem_chrome` does for standard stems.
        stem = re.sub(r"^[\s0Oo■►▪◯●◦·*~]+", "", stem).strip()
        # Prefix with the topic / instruction line that appeared BEFORE the choices.
        pre = chunk_text[:markers[0].start()].strip()
        pre_lines = [
            l.strip() for l in pre.split("\n")
            if l.strip()
            and not l.startswith("Item ")
            and "Mark Medicine" not in l
            and "Time Remaining" not in l
            and l.strip() != "■"
            and not re.match(r"^\s*\d+\s*hr\s+\d+\s*min", l)
            # Filter OCR-bubble noise lines: just "0", "* 0", "0 0", etc.
            and not re.fullmatch(r"[\s0Oo■►▪◯●◦·*~]+", l.strip())
        ]
        topic = ""
        # The TOPIC line is typically the LAST line before the choices that
        # tells the test-taker what to match (e.g. "For each patient with X,
        # select the most likely Y."). Skip the response-options instruction.
        for line in reversed(pre_lines):
            if re.search(r"response\s+options.+items.+same", line, re.IGNORECASE):
                continue
            topic = line
            break
        if topic:
            stem = f"{topic} {stem}"

    if not choices:
        return None
    return {"stem": stem, "choices": choices}


def parse_q_chunk(chunk_text: str) -> dict[str, Any]:
    """Best-effort deterministic stem + choices extraction.

    Returns {stem, choices}. The stem is everything from the chunk start
    to the first choice line, with NBME UI chrome lines stripped. The
    choices list captures labelled answer options A-H even when OCR has
    prefixed them with the empty-radio-button character `0`.
    """
    choices: list[dict[str, str]] = []
    stem_end = len(chunk_text)
    seen_labels: set[str] = set()
    for m in _CHOICE_LINE_RE.finditer(chunk_text):
        label = m.group(1).strip().upper()
        text = m.group(2).strip()
        # Trim trailing URL / footer noise.
        text = re.sub(r"https?://\S+.*$", "", text).strip()
        if not text or label in seen_labels:
            continue
        if not choices:
            stem_end = m.start()
        choices.append({"label": label, "text": text})
        seen_labels.add(label)
    stem = chunk_text[:stem_end].strip()
    stem = _clean_stem_chrome(stem)
    return {"stem": stem, "choices": choices}


# ── Gemini wrappers ──────────────────────────────────────────────────────────

_call_count = 0


def _api_key_or_die() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is required for NBME live BIC runs. Set it in the .app environment."
        )
    return key


def _bump_call_count() -> None:
    global _call_count
    _call_count += 1
    if _call_count > _HARD_CALL_CEILING:
        raise RuntimeError(
            f"Hard Gemini-call ceiling of {_HARD_CALL_CEILING} reached; aborting to prevent runaway cost."
        )


def gemini_text(prompt: str, max_tokens: int = 8192, temperature: float = 0.2, model: str | None = None, thinking_budget: int = -1) -> str:
    """Plain-text Gemini call (no images).

    v4.63: optional `model` override lets callers route the polish pass to
    gemini-2.5-pro and the critic to gemini-2.5-flash while extraction and
    completion stay on the default Flash model.

    v4.79: rewritten to use google-genai SDK via _uw._gemini_client().
    Preserves the responseMimeType=application/json behavior (forces JSON-only
    output, drastically reduces parse failures) and the v4.63 model override.

    v4.84: explicit `thinking_budget` parameter. Default -1 (dynamic) for
    polish/critic where reasoning helps. Extraction callsites pass 0 to
    disable thinking and reserve the full token budget for the JSON output —
    fixes the v4.79 regression where dynamic thinking consumed most of the
    12K-token budget on multimodal extractions, leaving Gemini to return
    empty or truncated JSON.
    """
    _bump_call_count()
    if not _GENAI_SDK_AVAILABLE:
        raise RuntimeError(
            "google-genai SDK not installed. Install with: pip install google-genai"
        )
    use_model = (model or GEMINI_MODEL).strip()
    try:
        client = _uw._gemini_client()
        response = client.models.generate_content(
            model=use_model,
            contents=prompt,
            config=_genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max(max_tokens * 2, 16384),
                response_mime_type="application/json",
                thinking_config=_genai_types.ThinkingConfig(thinking_budget=thinking_budget),
            ),
        )
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("Gemini timed out") from exc
    except EnvironmentError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Gemini call failed: {exc}") from exc
    text = getattr(response, "text", None)
    if not text:
        candidates = getattr(response, "candidates", None) or []
        raise RuntimeError(f"Gemini candidate had no text part. candidates={candidates!r}"[:400])
    return str(text)


def gemini_image(prompt: str, image_paths: list[Path], max_tokens: int = 4096, temperature: float = 0.0, thinking_budget: int = 0) -> str:
    """Multimodal Gemini call.

    v4.79: rewritten to use google-genai SDK via _uw._gemini_client(). The SDK
    handles base64 encoding internally via types.Part.from_bytes.
    Preserves responseMimeType=application/json (NBME's structured-output flow
    depends on getting clean JSON back, not markdown-fenced JSON).

    v4.84: thinking_budget default flipped to 0 (no thinking). Multimodal
    extraction is a structured page-parse task — when thinking was dynamic
    (-1), Flash routinely consumed most of the 12K-token budget on reasoning
    and returned empty/truncated JSON, dropping ~30 of 50 questions per NBME
    test. Callers that genuinely need reasoning (e.g. figure-classification)
    can opt in with thinking_budget=-1.
    """
    _bump_call_count()
    if not _GENAI_SDK_AVAILABLE:
        raise RuntimeError(
            "google-genai SDK not installed. Install with: pip install google-genai"
        )
    contents: list[Any] = [prompt]
    for image_path in image_paths:
        mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
        contents.append(_genai_types.Part.from_bytes(
            data=image_path.read_bytes(),
            mime_type=mime,
        ))
    try:
        client = _uw._gemini_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=_genai_types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max(max_tokens * 3, 12288),
                response_mime_type="application/json",
                thinking_config=_genai_types.ThinkingConfig(thinking_budget=thinking_budget),
            ),
        )
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("Gemini multimodal timed out") from exc
    except EnvironmentError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Gemini multimodal call failed: {exc}") from exc
    text = getattr(response, "text", None)
    if not text:
        candidates = getattr(response, "candidates", None) or []
        raise RuntimeError(f"Gemini multimodal candidate had no text part. candidates={candidates!r}"[:400])
    return str(text)


# ── Q-only Gemini completion prompt ──────────────────────────────────────────

_Q_ONLY_PROMPT = """You are an NBME / USMLE Step 2 question writer.

Given this question STEM and ANSWER CHOICES (from an NBME-style PDF where
the answer key is not available), identify the correct answer letter and
write the full canonical explanation set.

STEM:
{stem}

ANSWER CHOICES:
{choices}

Output a single JSON object with these exact keys (no markdown fences):

{{
  "correctAnswer": "<one of A B C D E F G H>",
  "explanationSections": [
    {{ "heading": "Correct Answer Explanation", "body": ["<2-4 sentence clinical reasoning>"] }},
    {{ "heading": "Incorrect Answer Explanation", "body": ["<1-2 sentences per wrong choice, grouped together>"] }},
    {{ "heading": "Educational Objective", "body": ["<single sentence, ≤20 words, stating the tested concept>"] }}
  ],
  "educationalObjective": "<same one-sentence educational objective>",
  "reviewPearl": "<one concise, high-yield, board-relevant rule from this question>",
  "retrievalTag": "<under 12 words; hyperspecific (e.g. 'pheochromocytoma preoperative alpha-blockade before beta-blockade sequence')>"
}}

Do not invent diagnoses, labs, or findings outside the stem. Stay grounded.
Return ONLY the JSON object, nothing before or after."""


# ── Canonical polish call (v4.61 follow-up) ──────────────────────────────────
#
# After the orchestrator has stem + choices + correctAnswer + explanationText
# (from A-PDF parse, combined-mode inline parse, or Gemini completion), run
# one more Gemini text call to polish into the canonical app-ready shape:
# proper explanationSections, reviewPearl, retrievalTag, educationalObjective.
#
# Before this fix, the happy path used string-splitting and left these meta
# fields as placeholders ("Refer to the explanation.", "Apply the tested
# clinical reasoning."). Adds ~$0.005/question and ~3 sec/question wall time.

_POLISH_PROMPT = """You are polishing an NBME exam question into the canonical
study-card format. The stem, answer choices, correct answer letter, and raw
explanation text are already extracted from the source PDF. Your job is to
restructure them into the canonical 3-section explanation block plus a review
pearl, retrieval tag, and educational objective — without changing any
clinical facts.

STEM:
{stem}

ANSWER CHOICES:
{choices}

CORRECT ANSWER: {correct_answer}

RAW EXPLANATION TEXT (may contain OCR noise — clean as you transcribe):
{explanation}

Output JSON only (no markdown fences, no commentary):

{{
  "explanationSections": [
    {{"heading": "Correct Answer Explanation",
      "body": ["<2-4 sentences explaining WHY the correct answer is right, citing the discriminating clinical clue. Use the raw explanation text as your source; clean OCR noise but do not invent new facts.>"]}},
    {{"heading": "Incorrect Answer Explanation",
      "body": ["<1-2 sentences per wrong choice, grouped into one body. Cover every wrong option (A,B,C,etc. — whichever ones are NOT the correct answer).>"]}},
    {{"heading": "Educational Objective",
      "body": ["<single sentence, ≤20 words, stating the tested reasoning task>"]}}
  ],
  "reviewPearl": "<one concise, high-yield, board-relevant rule from THIS question>",
  "retrievalTag": "<under 12 words, hyperspecific. Examples: 'pheochromocytoma preoperative alpha-blockade before beta-blockade', 'HFrEF ICD primary prevention EF ≤35% three-month GDMT', 'Type A aortic dissection emergency surgery'.>",
  "educationalObjective": "<same single sentence as in explanationSections.Educational Objective>"
}}

Do NOT invent diagnoses, labs, treatments, or findings outside the provided
stem and explanation text. If the raw explanation is sparse, write a shorter
grounded version rather than padding."""


# ── v4.63: critic + regenerate infrastructure ────────────────────────────────
# Deterministic placeholder lists drawn from observed v4.60 / v4.61 failures
# (the canonical-polish path historically emitted these strings when Gemini
# truncated or fell into a low-confidence response).
_PLACEHOLDER_PEARLS = {
    "refer to the explanation.",
    "refer to the explanation",
    "apply the tested clinical reasoning.",
    "apply the tested clinical reasoning",
    "see the explanation.",
    "see the explanation",
    "see explanation.",
    "see explanation",
    "review the explanation.",
    "review the explanation",
    "n/a",
    "tbd",
    "todo",
}

_PLACEHOLDER_EDU_OBJS = {
    "apply the tested clinical reasoning.",
    "apply the tested clinical reasoning",
    "demonstrate clinical reasoning.",
    "demonstrate clinical reasoning",
    "identify the correct answer.",
    "identify the correct answer",
}

_CRITIC_PROMPT = """You are a strict NBME exam-quality reviewer. Below is a question stem, its choices, the correct answer, and the auto-generated polish fields. Decide if the polish fields meet a board-quality bar.

QUESTION STEM:
{stem}

CHOICES:
{choices}

CORRECT ANSWER: {correct_answer}

POLISH FIELDS:
- reviewPearl: {pearl}
- retrievalTag: {tag}
- educationalObjective: {edu_obj}

Quality bar:
- reviewPearl must be a concise, board-relevant, hyperspecific clinical rule (NOT generic, NOT a placeholder like "refer to the explanation").
- retrievalTag must be hyperspecific (e.g., "pheochromocytoma preoperative alpha-blockade before beta-blockade"); generic categories like "cardiology" or "treatment" are NOT acceptable.
- educationalObjective must state the actual tested reasoning task (e.g., "identify next step in management of acute pancreatitis").

Return ONLY a JSON object — first character '{{', last character '}}':

{{
  "ok": <true if all three fields meet the bar, false otherwise>,
  "issues": [<short specific issues if any, max 5>]
}}"""


def _critic_polish_fields(
    stem: str,
    choices: list[dict[str, str]],
    correct_answer: str,
    polish: dict[str, Any],
) -> tuple[bool, list[str]]:
    """v4.63: critic gate on polish output. Returns (ok, issues).

    Deterministic checks first (free, instant). LLM critic call (Flash,
    ~$0.001) only runs if deterministic checks pass — saves cost on
    obviously-bad outputs.

    Returns (True, []) on any critic-internal failure so a flaky critic
    never blocks a polish that already passed deterministic guards.
    """
    pearl = str(polish.get("reviewPearl") or "").strip()
    tag = str(polish.get("retrievalTag") or "").strip()
    edu_obj = str(polish.get("educationalObjective") or "").strip()

    issues: list[str] = []

    # Deterministic guards (free, instant).
    if pearl.lower() in _PLACEHOLDER_PEARLS or len(pearl.split()) < 5:
        issues.append("reviewPearl is a placeholder or too short (<5 words)")
    tag_word_count = len(tag.split())
    if not tag or tag_word_count < 2 or tag_word_count > 12:
        issues.append(f"retrievalTag must be 2-12 words (got {tag_word_count})")
    if edu_obj.lower() in _PLACEHOLDER_EDU_OBJS or len(edu_obj.split()) < 5:
        issues.append("educationalObjective is a placeholder or too short (<5 words)")

    if issues:
        return False, issues

    # LLM critic — only runs if deterministic passes.
    choices_text = "\n".join(f"{c.get('label','?')}) {c.get('text','')}" for c in choices)
    prompt = _CRITIC_PROMPT.format(
        stem=stem[:1500],
        choices=choices_text,
        correct_answer=correct_answer or "?",
        pearl=pearl,
        tag=tag,
        edu_obj=edu_obj,
    )
    try:
        raw = gemini_text(prompt, max_tokens=512, model=CRITIC_MODEL)
        if raw.strip().startswith("{"):
            parsed = json.loads(raw)
        else:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return True, []  # malformed critic response — don't block
            parsed = json.loads(m.group(0))
        ok = bool(parsed.get("ok"))
        critic_issues = parsed.get("issues") or []
        if not isinstance(critic_issues, list):
            critic_issues = [str(critic_issues)]
        return ok, [str(i) for i in critic_issues[:5]]
    except Exception:
        return True, []  # critic itself failed — don't block the polish


def gemini_polish_question(
    stem: str,
    choices: list[dict[str, str]],
    correct_answer: str,
    explanation_text: str,
    retries: int = 2,
) -> dict[str, Any]:
    """Single Gemini text call that turns (stem, choices, correct, raw expl)
    into canonical (explanationSections, reviewPearl, retrievalTag,
    educationalObjective). Always invoked per-question regardless of which
    pipeline tier produced the inputs.

    Retries on JSON parse failures (same pattern as gemini_complete_q_only).
    On total failure, returns an empty-canonical dict so the caller can
    proceed with placeholder values rather than dropping the question.

    v4.63: routed to gemini-2.5-pro (POLISH_MODEL) for higher-quality
    reviewPearl / retrievalTag / educationalObjective output. After a
    successful polish, a Flash critic call (CRITIC_MODEL, gated by
    CRITIC_ENABLED) scores the output against a rubric; if the critic
    finds issues, ONE regeneration attempt is made with the critic's
    issues fed back as a fix hint. Disable via NBME_CRITIC_ENABLED=0.
    """
    choices_text = "\n".join(f"{c['label']}) {c['text']}" for c in choices)
    base_prompt = _POLISH_PROMPT.format(
        stem=stem,
        choices=choices_text,
        correct_answer=correct_answer or "(unknown)",
        explanation=explanation_text[:6000] if explanation_text else "(no raw explanation available)",
    )
    last_err: Exception | None = None
    parsed: dict[str, Any] | None = None
    for attempt in range(retries + 1):
        prompt = base_prompt
        if attempt > 0:
            prompt += (
                "\n\nIMPORTANT: previous response was not valid JSON. Return "
                "ONLY the JSON object — no markdown fences, no commentary, no "
                "trailing prose. First char must be '{', last char must be '}'."
            )
        try:
            # v4.61 follow-up: 10-choice matching-set questions need a full
            # incorrect-explanation section covering 9 wrong choices, which
            # routinely overflows 2048 tokens and triggers Gemini to truncate
            # mid-string. 4096 tokens fits even the longest matching-set polish
            # responses observed in field testing.
            raw = gemini_text(prompt, max_tokens=4096, model=POLISH_MODEL)
            parsed = json.loads(raw)
            break
        except json.JSONDecodeError as exc:
            last_err = exc
            try:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    parsed = json.loads(m.group(0))
                    break
            except Exception:
                pass
            continue
        except Exception as exc:
            last_err = exc
            continue

    # v4.63: critic + regenerate gate. Only runs on the success path with
    # parsed JSON. Critic itself is best-effort — if it fails internally
    # the polish is accepted unchanged. Regeneration is capped at 1.
    if parsed is not None and CRITIC_ENABLED:
        ok, issues = _critic_polish_fields(stem, choices, correct_answer, parsed)
        if not ok:
            try:
                fix_prompt = base_prompt + (
                    "\n\nIMPORTANT: a previous attempt produced low-quality polish "
                    "fields. Fix these specific issues this time:\n"
                    + "\n".join(f"- {issue}" for issue in issues[:5])
                    + "\nReturn ONLY the JSON object."
                )
                raw = gemini_text(fix_prompt, max_tokens=4096, model=POLISH_MODEL)
                regen = json.loads(raw)
                parsed = regen  # trust regen (cap of 1 retry — no loops)
            except Exception:
                # Regen failed — keep the original parsed output.
                pass

    if parsed is not None:
        return parsed

    # Total polish failure — try a tiny salvage call that asks Gemini for
    # JUST the meta fields (pearl, tag, eduObj). Much smaller response,
    # less chance of truncation. The big explanation text we already have
    # from the A-PDF is used as raw input rather than re-emitted.
    salvage_prompt = (
        "Given this NBME exam question stem and its explanation, write "
        "three short meta fields. Return ONLY a JSON object with these "
        "three keys; first character '{', last character '}'.\n\n"
        f"STEM: {stem[:1500]}\n\n"
        f"CORRECT ANSWER: {correct_answer}\n\n"
        f"EXPLANATION: {explanation_text[:2000]}\n\n"
        "{\n"
        '  "reviewPearl": "<one concise board-relevant rule, ≤20 words>",\n'
        '  "retrievalTag": "<hyperspecific, ≤12 words>",\n'
        '  "educationalObjective": "<single sentence stating the tested reasoning task, ≤20 words>"\n'
        "}"
    )
    salvage_pearl = ""
    salvage_tag = ""
    salvage_obj = ""
    try:
        raw = gemini_text(salvage_prompt, max_tokens=512, model=POLISH_MODEL)
        parsed_salvage = json.loads(raw) if raw.strip().startswith("{") else json.loads(
            re.search(r"\{.*\}", raw, re.DOTALL).group(0)
        )
        salvage_pearl = str(parsed_salvage.get("reviewPearl") or "").strip()
        salvage_tag = str(parsed_salvage.get("retrievalTag") or "").strip()
        salvage_obj = str(parsed_salvage.get("educationalObjective") or "").strip()
    except Exception:
        pass
    return {
        "explanationSections": [],
        "reviewPearl": salvage_pearl,
        "retrievalTag": salvage_tag,
        "educationalObjective": salvage_obj,
        "_polishFailed": str(last_err) if last_err else "unknown",
    }


def gemini_complete_q_only(stem: str, choices: list[dict[str, str]], retries: int = 2) -> dict[str, Any]:
    """Call Gemini text completion with retry on JSON parse errors.

    v4.61 follow-up: the first cut dropped questions when Gemini returned
    malformed JSON. Now we retry up to `retries` times before giving up.
    Each retry uses an increasingly explicit reminder that the response
    MUST be raw JSON.
    """
    choices_text = "\n".join(f"{c['label']}) {c['text']}" for c in choices)
    base_prompt = _Q_ONLY_PROMPT.format(stem=stem, choices=choices_text)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        prompt = base_prompt
        if attempt > 0:
            prompt += (
                "\n\nIMPORTANT: your previous response was not valid JSON. "
                "Return ONLY the JSON object, with no markdown code fences, "
                "no commentary before or after, and no trailing prose. The "
                "first character must be '{' and the last character must be '}'."
            )
        try:
            # v4.84: thinking_budget=0 — Q-only completion is structured extraction;
            # dynamic thinking starves the output token budget.
            raw = gemini_text(prompt, max_tokens=4096, thinking_budget=0)
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            last_err = exc
            # Try a quick salvage: extract the first {...} block from the raw response.
            try:
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if m:
                    return json.loads(m.group(0))
            except Exception:
                pass
            continue
    raise RuntimeError(f"Gemini completion JSON parse failed after {retries + 1} attempts: {last_err}")


# ── Gemini A-PDF normalizer (when deterministic parse is too noisy) ──────────

_A_BLOCK_PROMPT = """You are extracting NBME answer explanations.

Below is OCR'd text from an NBME ANSWERS PDF. The block belongs to question
number {q_num}. Extract the correct answer letter and the full explanation
text.

BLOCK:
{block}

Output JSON only, no markdown fences:

{{
  "correctAnswer": "<A-H letter>",
  "explanationText": "<the explanation text, cleaned of UI chrome like 'Next Score Report Lab Values Calculator Help Pause' and stripped URLs>"
}}"""


def gemini_extract_a_block(q_num: int, block_text: str) -> dict[str, str]:
    # v4.84: thinking_budget=0 — A-PDF block extraction is structured, no reasoning needed.
    raw = gemini_text(
        _A_BLOCK_PROMPT.format(q_num=q_num, block=block_text[:6000]),
        max_tokens=2048,
        thinking_budget=0,
    )
    return json.loads(raw)


# ── Gemini multimodal figure detection ───────────────────────────────────────

_FIG_DETECT_PROMPT = """You are analyzing an NBME exam question page.

Identify any CLINICAL IMAGES embedded in the question stem — X-rays, CT/MRI
scans, EKG tracings, clinical photographs, histology slides, gross
pathology, dermatology images, ultrasound, angiograms, etc.

STRICTLY EXCLUDE the following (NEVER return their bounding boxes):
  • The dark blue NBME header banner at the very top of the page containing
    "Item N of 50" / "National Board of Medical Examiners" / "Time Remaining".
  • The "Mark Medicine Self-Assessment" subtitle and any timer text.
  • The ■ checkbox glyph.
  • The footer UI bar with "Previous Next Lab Values Calculator Review Help
    Pause" buttons.
  • The URL footer ("https://t.me/...").
  • Answer choice radio bubbles (the small "0" circles before A) B) C)...).
  • Any text that's part of the question stem itself.

The clinical image (when present) is typically in the MIDDLE of the page
between the stem text and the answer choices, with a clear rectangular
visual boundary.

Return JSON only (no markdown fences). bbox values MUST be FRACTIONAL
coordinates between 0.0 and 1.0 representing the position relative to the
TOTAL page width and height:

{
  "figures": [
    {
      "description": "<2-5 word description, e.g. 'chest x-ray PA view'>",
      "bbox": [x1_frac, y1_frac, x2_frac, y2_frac],
      "confidence": "high|medium|low"
    }
  ]
}

Constraints on fractional bbox:
  • y1 MUST be >= 0.10 (the top 10% of the page is the NBME header banner —
    never return a bbox that overlaps it).
  • y2 MUST be <= 0.92 (the bottom 8% is footer UI chrome).
  • The bbox area (x2-x1)*(y2-y1) MUST be between 0.04 and 0.70 of the page
    (smaller than 4% is too small to be a real clinical image; larger than
    70% means you've grabbed the wrong region).

If NO clinical image is present on the page, return {"figures": []}. Do
not invent a figure just because the stem mentions one — only return
bboxes for images you can actually SEE on the page."""


def gemini_detect_figures(page_image: Path) -> list[dict[str, Any]]:
    raw = gemini_image(_FIG_DETECT_PROMPT, [page_image], max_tokens=1024)
    parsed = json.loads(raw)
    figures = parsed.get("figures", []) or []
    # Validate bbox fractional constraints; drop any that violate the
    # NBME chrome guards. Belt-and-braces in case Gemini ignored the prompt.
    validated: list[dict[str, Any]] = []
    for fig in figures:
        bbox = fig.get("bbox") or []
        if len(bbox) != 4:
            continue
        try:
            x1, y1, x2, y2 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            continue
        # Coerce coordinates into [0,1] in case Gemini returned absolute pixels.
        if max(x1, y1, x2, y2) > 1.5:
            # Looks like absolute pixel coords — try to normalize assuming
            # Gemini was looking at a 1024-wide image (its typical downscale).
            scale = 1024.0
            x1, y1, x2, y2 = x1 / scale, y1 / scale, x2 / scale, y2 / scale
        # Clamp to [0,1].
        x1 = max(0.0, min(1.0, x1))
        y1 = max(0.0, min(1.0, y1))
        x2 = max(0.0, min(1.0, x2))
        y2 = max(0.0, min(1.0, y2))
        # Safety guards.
        if y1 < 0.08 or y2 > 0.94:
            continue  # overlaps header or footer
        if x2 <= x1 or y2 <= y1:
            continue
        area = (x2 - x1) * (y2 - y1)
        if area < 0.03 or area > 0.75:
            continue
        fig["bbox"] = [x1, y1, x2, y2]
        validated.append(fig)
    return validated


# ── Gemini multimodal Q-PDF page extraction ─────────────────────────────────
#
# Universal fallback for unusual Q-PDF formats: matching sets where choices
# are at the top and stem at the bottom, tabular choices (item 30 style),
# multi-column choice layouts, and OCR-missed boundaries (gap recovery).
# Sending the rendered page lets Gemini see the layout directly.

_Q_PAGE_EXTRACT_PROMPT = """Extract the full structure of an NBME exam question from this page.

The page may be in any of these formats:

1. STANDARD: stem at top, then 4-14 answer choices labeled A through N.

2. MATCHING SET: two instruction lines at the top
   ("The response options for the next N items are the same. Select one
   answer for each item in the set." plus a topic line like "For each
   patient with X, select the most likely diagnosis."), then 10-14 shared
   answer choices (A through J, sometimes A through L or A through N)
   usually in two columns, then the numbered stem ("28. A 36-year-old man...")
   at the bottom of the page. Count the letters carefully — some sets
   have 10, others 12, occasionally up to 14.

3. TABULAR: stem with a "Which of the following is the most likely set of
   findings on..." question, then column-header row(s) like "Specific
   Gravity / Glucose / Protein / WBC / RBC / Casts / Findings", then
   choices A-F where each choice text is a row of values aligned to those
   columns.

EXCLUDE from extraction:
  - "Item N of 50 National Board of Medical Examiners" header banner
  - "Mark Medicine Self-Assessment X hr Y min Z sec" timer line
  - The ■ checkbox glyph
  - Footer UI chrome: "Previous Next Lab Values Calculator Review Help Pause"
  - URLs / page numbers

If this page is a MATCHING SET, copy the topic instruction line ("For each
patient with X, select the most likely Y.") as a prefix to the per-item
stem so each generated question is self-contained — the imported question
should NOT depend on the user remembering which set it belongs to.

If this page is TABULAR, write each choice text as a SELF-CONTAINED string
that includes the column name in front of each value, separated by " | ".
This makes each choice readable in isolation even when the renderer can
only show plain text without table alignment. Example for a urinalysis
question with column headers "Specific Gravity | Glucose | Protein | WBC |
RBC | Casts | Findings":

  Correct format:
    A) Specific Gravity 1.003 | Glucose 1+ | Protein - | WBC 30 | RBC 5 | Casts muddy brown | Findings tubular epithelial cells

  WRONG format (do NOT do this):
    A) 1.003 | 1+ | - | 30 | 5 | muddy brown | tubular epithelial cells

Use a dash ("-") for empty cells. The stem should ALSO contain the column-
header row at its end so the user sees both the headers and the per-choice
labelled values. Do NOT skip column names on any choice — every choice
must repeat the same column names verbatim.

Return JSON only — no markdown fences, no prose before or after:

{{
  "questionNumber": <integer if visible in the page>,
  "stem": "<the question prompt text, ending in the question-mark sentence>",
  "answerChoices": [
    {{"label": "A", "text": "<choice text — for tabular, row values joined by ' | '>"}},
    ...
  ],
  "isMatchingSet": <true or false>,
  "isTabular": <true or false>,
  "format": "standard|matching_set|tabular"
}}"""


def gemini_multimodal_extract_question(
    page_image: Path,
    expected_q_num: int | None = None,
    retries: int = 2,
) -> dict[str, Any]:
    """Send the rendered page to Gemini and ask it to extract the full question.

    v4.61 follow-up:
      - Do NOT bias Gemini with "you are extracting question N" — that
        caused gap recovery to insert hallucinated questions when the page
        actually contained a different one. Ask Gemini to report the
        question number it actually sees.
      - Retry on JSON parse errors (Gemini occasionally returns truncated
        JSON or prose intro before the object).
      - For matching-set pages, retry once with stricter emphasis if the
        first call returned fewer than 8 choices. Matching sets usually
        have 10 (A-J) but go up to 12-14 (A-L, A-N). Fewer than 8 means
        Gemini collapsed two-column layout into one column.
    """
    base_prompt = _Q_PAGE_EXTRACT_PROMPT
    if expected_q_num is not None:
        base_prompt += (
            f"\n\nThe caller expects this page to contain question {expected_q_num}. "
            f"Set `questionNumber` to whatever number is ACTUALLY printed on the "
            f"page (look at the 'Item N of M' header or the leading stem prefix). "
            f"If the page contains a different question, return that question's "
            f"actual number — do NOT relabel it. If no question is visible at "
            f"all, return `null` for questionNumber and empty stem/choices."
        )

    matching_set_emphasis = (
        "\n\nIMPORTANT for MATCHING SET pages: the answer choices are arranged "
        "in TWO COLUMNS — left column starts at A, right column starts where the "
        "left column ends (often F, but matching sets sometimes have 12 or 14 "
        "total choices, in which case the right column goes through L or N). "
        "Count the letters carefully. You must return ALL choices as SEPARATE "
        "entries in answerChoices. Each lettered choice is ONE distinct option — "
        "do not merge two letters into one entry. For example, if you see "
        "'A) Acute cholecystitis    F) Chronic hepatitis C' on the same horizontal "
        "line, return TWO entries: {label: 'A', text: 'Acute cholecystitis'} and "
        "{label: 'F', text: 'Chronic hepatitis C'}. If you see 'E) Cellulitis    "
        "K) Stasis dermatitis', that is 2 entries. Up to 14 entries total are valid."
    )

    json_emphasis = (
        "\n\nIMPORTANT: return ONLY the JSON object. No markdown code fences, "
        "no commentary before or after, no trailing prose. The first character "
        "must be '{' and the last character must be '}'."
    )

    last_extracted: dict[str, Any] = {}
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        prompt = base_prompt
        if attempt > 0:
            # Add reinforcement on retry — strict JSON + matching-set guidance.
            prompt += matching_set_emphasis + json_emphasis
        try:
            raw = gemini_image(prompt, [page_image], max_tokens=2048)
            try:
                extracted = json.loads(raw)
            except json.JSONDecodeError:
                # Salvage attempt — find the first {...} block.
                m = re.search(r"\{.*\}", raw, re.DOTALL)
                if not m:
                    raise
                extracted = json.loads(m.group(0))
            choices = extracted.get("answerChoices") or []
            is_matching = bool(extracted.get("isMatchingSet"))
            # Retry condition: matching set but too few choices means Gemini
            # collapsed the two-column layout.
            if is_matching and len(choices) < 8 and attempt < retries:
                last_extracted = extracted
                continue
            return extracted
        except Exception as exc:
            last_err = exc
            continue
    if last_extracted:
        return last_extracted
    raise RuntimeError(f"gemini_multimodal_extract_question failed after {retries + 1} attempts: {last_err}")


# ── Page rendering helper ────────────────────────────────────────────────────

def render_page_to_png(pdf_path: Path, page_num: int, out_dir: Path, target_width: int = 1200) -> Path:
    """v4.61 follow-up: render at a fixed target_width (1200 px by default)
    rather than a fixed DPI. PDFs with non-standard page dimensions used
    to render at 5000+ px wide which made Gemini's downscaled-coordinate
    bbox responses unusable. A 1200-px-wide render is close to Gemini's
    native input size (it doesn't downscale further) so the fractional
    bbox math works correctly.
    """
    import fitz
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pdf_path.stem}_p{page_num:03d}.png"
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_num - 1]
        page_width_pt = page.rect.width
        if page_width_pt <= 0:
            page_width_pt = 612  # default US letter width in pt
        # Compute the scale factor that gives us a render exactly target_width wide.
        scale = target_width / page_width_pt
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)
        pix.save(str(out_path))
    finally:
        doc.close()
    return out_path


def crop_bbox_from_page(page_png: Path, bbox: list[float], out_path: Path) -> Path | None:
    """v4.61 follow-up: bbox values are FRACTIONAL (0.0-1.0) relative to
    the rendered page dimensions. Convert to pixel coordinates using the
    actual loaded image's width and height — eliminates the prior coordinate-
    system mismatch where Gemini returned coordinates in its own downscaled
    space but the crop applied them to the full-res page render.
    """
    try:
        from PIL import Image
        img = Image.open(page_png)
    except Exception:
        return None
    if len(bbox) != 4:
        return None
    x1f, y1f, x2f, y2f = bbox
    # If any value > 1.5, assume absolute pixels (legacy callers or Gemini
    # ignoring the fractional instruction) and try to coerce.
    if max(x1f, y1f, x2f, y2f) > 1.5:
        # Best-effort normalization assuming 1024-wide reference.
        ref = max(1024.0, max(x1f, y1f, x2f, y2f))
        x1f, y1f, x2f, y2f = x1f / ref, y1f / ref, x2f / ref, y2f / ref
    # Clamp.
    x1f = max(0.0, min(1.0, x1f))
    y1f = max(0.0, min(1.0, y1f))
    x2f = max(0.0, min(1.0, x2f))
    y2f = max(0.0, min(1.0, y2f))
    # Apply NBME header/footer safety again (defence-in-depth — Gemini
    # validation also rejects but this is the final guard before disk).
    if y1f < 0.08 or y2f > 0.94:
        return None
    if x2f <= x1f or y2f <= y1f:
        return None
    area = (x2f - x1f) * (y2f - y1f)
    if area < 0.03 or area > 0.75:
        return None
    x1 = int(x1f * img.width)
    y1 = int(y1f * img.height)
    x2 = int(x2f * img.width)
    y2 = int(y2f * img.height)
    width = x2 - x1
    height = y2 - y1
    aspect = width / max(1, height)
    if aspect < AUTO_ATTACH_MIN_ASPECT or aspect > AUTO_ATTACH_MAX_ASPECT:
        return None
    cropped = img.crop((x1, y1, x2, y2))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(out_path)
    return out_path


# ── PyMuPDF embedded raster check ────────────────────────────────────────────

def page_has_significant_raster(
    pdf_path: Path,
    page_num: int,
    min_dim_px: int = 400,
    min_area_px: int = 150_000,
) -> bool:
    """v4.61 follow-up: ignore tiny UI icons. Real clinical images at 200 DPI
    are at least 400×400 px and over 150,000 px² in area. NBME UI chrome
    (the ■ block character, button glyphs, page header logos) all stay
    well under these thresholds, so they get filtered out cleanly.
    """
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        try:
            page = doc[page_num - 1]
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                pix = fitz.Pixmap(doc, xref)
                w, h = pix.width, pix.height
                pix = None
                if w >= min_dim_px and h >= min_dim_px and (w * h) >= min_area_px:
                    return True
        finally:
            doc.close()
    except Exception:
        return False
    return False


# Back-compat alias for the previous loose version.
page_has_embedded_raster = page_has_significant_raster


# ── Question-number → page-number map (Q-PDF) ────────────────────────────────

def build_q_page_map(raw_text: str) -> dict[int, int]:
    """Find every "## Page N" marker, then every "Item M of K" inside that page block.
    Return {questionNumber: pageNumber}.
    """
    page_re = re.compile(r"##\s*Page\s+(\d+)", re.IGNORECASE)
    item_re = re.compile(r"\bItem\s+(\d+)\s+of\s+\d+\b", re.IGNORECASE)
    page_positions = [(int(m.group(1)), m.end()) for m in page_re.finditer(raw_text)]
    if not page_positions:
        return {}
    out: dict[int, int] = {}
    for i, (page_num, pos) in enumerate(page_positions):
        end = page_positions[i + 1][1] if i + 1 < len(page_positions) else len(raw_text)
        block = raw_text[pos:end]
        m = item_re.search(block)
        if m:
            try:
                out[int(m.group(1))] = page_num
            except ValueError:
                continue
    return out


# ── Orchestrator ─────────────────────────────────────────────────────────────

def build_app_ready(
    questions: list[dict[str, Any]],
    source_stem: str,
    warnings_list: list[str],
) -> dict[str, Any]:
    return {
        "schemaVersion": "nbme-gemini-json-v3",
        "testTitle": source_stem,
        "sourceFormat": "nbme-pdf",
        "expectedQuestionCount": len(questions),
        "actualExtractedQuestionCount": len(questions),
        "extractionWarnings": warnings_list,
        "questions": questions,
    }


def assemble_question(
    q_num: int,
    stem: str,
    choices: list[dict[str, str]],
    correct_answer: str,
    explanation_sections: list[dict[str, Any]],
    review_pearl: str,
    educational_objective: str,
    retrieval_tag: str,
    figures: list[dict[str, Any]],
) -> dict[str, Any]:
    figure_refs = [
        {
            "id": f["figureId"],
            "placeholder": f"[FIGURE: {f['figureId']}]",
            "location": "stem",
            "visibleText": [],
        }
        for f in figures
    ]
    return {
        "id": f"q{q_num:03d}",
        "questionNumber": q_num,
        "sourceQuestionNumber": q_num,
        "stem": stem,
        "answerChoices": choices,
        "correctAnswer": correct_answer,
        "explanationSections": explanation_sections,
        "educationalObjective": educational_objective,
        "reviewPearl": review_pearl,
        "retrievalTag": retrieval_tag,
        "hasEmbeddedFigure": bool(figures),
        "figureRefs": figure_refs,
        "images": figures,
        "explanationImages": [],
        "tables": [],
        "extractionWarnings": [],
    }


def process_pdf_full_text(pdf_path: Path) -> str:
    """Run the existing OCR + per-page text extraction. Returns concatenated raw text."""
    extract_pdfs.ensure_dirs()
    result = extract_pdfs.extract_pdf(pdf_path)
    if result.get("status") == "error":
        warns = "; ".join(result.get("warnings") or [])
        raise RuntimeError(f"extract_pdf failed: {warns}")
    output_path = result.get("output_path")
    if not output_path:
        raise RuntimeError("extract_pdf returned no output path")
    return Path(output_path).read_text(encoding="utf-8")


def chunk_text(raw_text: str) -> list[dict[str, Any]]:
    """Reuse the v4.60 two-tier chunker, returning the chunks list."""
    text = extract_pdfs._strip_page_markers(raw_text)
    matches = list(extract_pdfs._Q_BOUNDARY_STRONG_RE.finditer(text))
    if not matches:
        matches = list(extract_pdfs._Q_BOUNDARY_FALLBACK_RE.finditer(text))
    if not matches:
        return []
    chunks: list[dict[str, Any]] = []
    for idx, m in enumerate(matches):
        try:
            q_num = int(next(g for g in m.groups() if g is not None))
        except (StopIteration, ValueError):
            continue
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chunk_text = text[m.start():end].strip()
        chunks.append({"questionNumber": q_num, "chunkText": chunk_text})
    return chunks


def _data_url_from_path(p: Path) -> str:
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    encoded = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def detect_and_attach_figures(
    pdf_path: Path,
    question_number_to_page: dict[int, int],
    stems_by_q: dict[int, str],
    is_screenshot_pdf: bool,
    job_output_root: Path,
) -> dict[int, list[dict[str, Any]]]:
    """For each question, if image-language present OR embedded raster present,
    call Gemini multimodal on the page to identify and crop figures.
    Returns {questionNumber: [figure dicts]}.
    """
    figures_by_q: dict[int, list[dict[str, Any]]] = {}
    render_dir = job_output_root / "rendered_pages"
    crop_dir = job_output_root / "figure_crops"

    for q_num, page_num in question_number_to_page.items():
        stem = stems_by_q.get(q_num, "")
        # v4.63: liberalized — figure detection now runs on EVERY question,
        # not just smart-triggered ones. Catches cases where the stem describes
        # a finding without naming "the photograph" or similar trigger words.
        # The has_image_lang / has_embedded booleans are still computed because
        # downstream code may use them for logging or confidence scoring.
        has_image_lang = bool(_IMAGE_LANGUAGE_RE.search(stem))
        has_embedded = page_has_embedded_raster(pdf_path, page_num)
        try:
            page_png = render_page_to_png(pdf_path, page_num, render_dir)
            detected = gemini_detect_figures(page_png)
        except Exception as exc:
            warn(f"figure detection failed for q{q_num} (page {page_num}): {exc}")
            continue
        attached: list[dict[str, Any]] = []
        for i, fig in enumerate(detected, start=1):
            bbox = fig.get("bbox") or []
            if len(bbox) != 4:
                continue
            fig_id = f"nbme_q{q_num:03d}_p{page_num:03d}_{i:02d}"
            crop_path = crop_dir / f"{fig_id}.png"
            cropped = crop_bbox_from_page(page_png, bbox, crop_path)
            if not cropped:
                continue
            attached.append({
                "figureId":         fig_id,
                "figureKey":        None,
                "dataUrl":          _data_url_from_path(cropped),
                "isLabTable":       False,
                "kind":             "figure",
                "source":           "nbme-pdf-generator",
                "originalFileName": cropped.name,
                "assetPath":        str(cropped.relative_to(job_output_root)) if cropped.is_relative_to(job_output_root) else str(cropped),
                "placement":        "stem",
                "pageNum":          page_num,
                "confidence":       fig.get("confidence") or "medium",
                "description":      fig.get("description") or "",
                "bbox":             bbox,
            })
        if attached:
            figures_by_q[q_num] = attached
    return figures_by_q


def orchestrate(inputs: list[Path], job_output_root: Path) -> dict[str, Any]:
    log(f"Discovered {len(inputs)} input(s): {[p.name for p in inputs]}")
    mode, role_map = detect_mode(inputs)
    q_pdf = role_map.get("q")
    a_pdf = role_map.get("a")
    log(f"Mode: {mode}  (Q-PDF: {q_pdf.name if q_pdf else 'none'}, A-PDF: {a_pdf.name if a_pdf else 'none'})")

    if mode == "a_only":
        raise RuntimeError("A-only mode is not supported. Upload at least a Questions PDF.")

    warnings_list: list[str] = []
    warnings_list.append(f"detected_mode: {mode}")

    if not q_pdf:
        raise RuntimeError("No Q-PDF detected.")

    # Screenshot detection for both PDFs.
    q_is_screenshot, q_diag = detect_screenshot_mode(q_pdf)
    log(f"Q-PDF screenshot detect: {q_diag}")
    warnings_list.append(f"q_pdf_screenshot: {q_is_screenshot}")
    a_is_screenshot = False
    if a_pdf:
        a_is_screenshot, a_diag = detect_screenshot_mode(a_pdf)
        log(f"A-PDF screenshot detect: {a_diag}")
        warnings_list.append(f"a_pdf_screenshot: {a_is_screenshot}")

    # 1. Q-PDF text extraction + chunking
    q_raw = process_pdf_full_text(q_pdf)
    q_chunks = chunk_text(q_raw)
    log(f"Q-PDF: {len(q_chunks)} chunk(s)")
    if not q_chunks:
        raise RuntimeError("Q-PDF chunking produced no boundaries; cannot proceed.")
    question_to_page = build_q_page_map(q_raw)

    # 2. Deterministic stem + choices per chunk, with multimodal escalation
    #    when the result looks suspicious (matching sets, tabular choices,
    #    multi-column layouts — see detect_chunk_suspicion).
    stems_by_q: dict[int, str] = {}
    choices_by_q: dict[int, list[dict[str, str]]] = {}
    render_dir = job_output_root / "rendered_pages"
    for c in q_chunks:
        q_num = int(c["questionNumber"])
        parsed = parse_q_chunk(c["chunkText"])
        stem = parsed["stem"]
        choices = parsed["choices"]
        suspicious, signals = detect_chunk_suspicion(c["chunkText"], stem, choices)
        if suspicious:
            page_num = question_to_page.get(q_num)
            log(f"  q{q_num}: suspicious parse [{','.join(signals)}]")
            rescued = False
            # Tier 1 (free): deterministic two-column / matching-set splitter
            # handles the most common edge case without spending a Gemini call.
            if (
                "multi_column_choice_leakage" in signals
                or "matching_set_instruction" in signals
            ):
                det = deterministic_multi_column_parse(c["chunkText"])
                if det and len(det["choices"]) >= 8:
                    if det.get("stem"):
                        stem = det["stem"]
                    choices = det["choices"]
                    rescued = True
                    log(f"  q{q_num}: deterministic multi-column rescue → {len(choices)} choices")
                    warnings_list.append(f"q{q_num}: deterministic multi-column rescue succeeded ({len(choices)} choices)")
            # Tier 2: Gemini multimodal page extraction for anything still suspicious.
            if not rescued and page_num:
                warnings_list.append(f"q{q_num}: suspicious deterministic parse ({','.join(signals)}); falling back to Gemini multimodal page extraction")
                try:
                    page_png = render_page_to_png(q_pdf, page_num, render_dir)
                    extracted = gemini_multimodal_extract_question(page_png, expected_q_num=q_num)
                    new_stem = str(extracted.get("stem") or "").strip()
                    new_choices = extracted.get("answerChoices") or []
                    if new_stem and new_choices:
                        stem = new_stem
                        choices = [
                            {"label": str(ch.get("label") or "").strip().upper(),
                             "text":  str(ch.get("text") or "").strip()}
                            for ch in new_choices
                            if str(ch.get("label") or "").strip() and str(ch.get("text") or "").strip()
                        ]
                        warnings_list.append(f"q{q_num}: multimodal extraction succeeded ({extracted.get('format', 'unknown')} format)")
                    else:
                        warnings_list.append(f"q{q_num}: multimodal extraction returned empty stem or choices; keeping deterministic result")
                except Exception as exc:
                    warnings_list.append(f"q{q_num}: multimodal extraction failed: {exc}; keeping deterministic result")
        stems_by_q[q_num] = stem
        choices_by_q[q_num] = choices

    # 2b. Gap-recovery: render any page that has an expected question number
    #     but is missing from chunks (Q-PDF OCR lost the "Item N of M"
    #     boundary). v4.61 follow-up: tighter probe gating — only attempt
    #     high-confidence single-question gaps where both neighbouring
    #     questions are known and exactly one page separates them. This
    #     matches NBME's one-question-per-page layout and prevents wasted
    #     Gemini calls on large gaps where we can't reliably guess pages.
    if stems_by_q:
        all_known_qs = sorted(stems_by_q.keys())
        expected_qs = range(min(all_known_qs), max(all_known_qs) + 1)
        missing_qs = [n for n in expected_qs if n not in stems_by_q]
        probable_gaps = []
        for missing_q in missing_qs:
            prev_page = question_to_page.get(missing_q - 1)
            next_page = question_to_page.get(missing_q + 1)
            if prev_page and next_page and (next_page - prev_page) == 2:
                probable_gaps.append((missing_q, prev_page + 1))
        if probable_gaps:
            log(f"Gap recovery: {len(probable_gaps)} single-page gap(s) — probing via multimodal extraction")
            warnings_list.append(f"gap_recovery: probing {len(probable_gaps)} single-page gap(s): {[g[0] for g in probable_gaps]}")
            for missing_q, probe_page in probable_gaps:
                try:
                    page_png = render_page_to_png(q_pdf, probe_page, render_dir)
                    extracted = gemini_multimodal_extract_question(page_png, expected_q_num=missing_q)
                    # Verify Gemini reports the same q-number we expect.
                    # Refuses hallucinated results where the page contains a
                    # different question entirely.
                    found_qn = extracted.get("questionNumber")
                    if not isinstance(found_qn, int) or found_qn != missing_q:
                        warnings_list.append(f"q{missing_q}: gap-recovery on page {probe_page} returned questionNumber={found_qn}; rejected")
                        continue
                    new_stem = str(extracted.get("stem") or "").strip()
                    new_choices_raw = extracted.get("answerChoices") or []
                    if new_stem and new_choices_raw:
                        stems_by_q[missing_q] = new_stem
                        choices_by_q[missing_q] = [
                            {"label": str(ch.get("label") or "").strip().upper(),
                             "text":  str(ch.get("text") or "").strip()}
                            for ch in new_choices_raw
                            if str(ch.get("label") or "").strip() and str(ch.get("text") or "").strip()
                        ]
                        question_to_page[missing_q] = probe_page
                        warnings_list.append(f"q{missing_q}: gap-recovery succeeded via multimodal extraction (page {probe_page})")
                    else:
                        warnings_list.append(f"q{missing_q}: gap-recovery returned empty stem or choices")
                except Exception as exc:
                    warnings_list.append(f"q{missing_q}: gap-recovery probe on page {probe_page} failed: {exc}")
        # Note any gaps we COULDN'T probe (so the user knows we tried).
        unprobed = [n for n in missing_qs if n not in stems_by_q]
        if unprobed:
            warnings_list.append(f"gap_recovery: {len(unprobed)} missing question(s) had no clean single-page gap and were not probed: {unprobed[:10]}{'...' if len(unprobed) > 10 else ''}")

    # 3. A-PDF parse (if present)
    answers_by_q: dict[int, dict[str, str]] = {}
    if a_pdf:
        a_raw = process_pdf_full_text(a_pdf)
        # NBME interface variant uses chunking; plain text variant uses parse_a_pdf.
        if _NBME_INTERFACE_RE.search(a_raw):
            log("A-PDF format: NBME interface")
            warnings_list.append("a_pdf_format: nbme_interface")
            # Use chunker so we get one block per question; then parse each.
            # Duplicate "Item N of M" boundaries occur naturally because the
            # A-PDF has both a per-page header and a system-index page that
            # repeats the references. We resolve duplicates by preferring
            # the chunk with an actual "Correct Answer: X" line — never
            # let an empty chunk overwrite a good one.
            a_chunks = chunk_text(a_raw)
            for c in a_chunks:
                q_num = int(c["questionNumber"])
                ans_match = _CORRECT_ANSWER_RE.search(c["chunkText"])
                correct = ans_match.group(1).upper() if ans_match else ""
                existing = answers_by_q.get(q_num)
                # Skip empty chunks if we already have a good one.
                if existing and existing.get("correctAnswer") and not correct:
                    continue
                if ans_match:
                    expl = c["chunkText"][ans_match.end():].strip()
                else:
                    expl = c["chunkText"].strip()
                expl = _clean_explanation_chrome(expl)
                answers_by_q[q_num] = {"correctAnswer": correct, "explanationText": expl}
        else:
            log("A-PDF format: plain numbered text")
            warnings_list.append("a_pdf_format: plain_numbered_text")
            answers_by_q = parse_a_pdf(a_raw)
        log(f"A-PDF: parsed {len(answers_by_q)} answer block(s)")

    # 4. Combined-mode short-circuit (no separate A-PDF, but the Q-PDF has
    # inline answers). Reuse the v4.60 normalization path via Gemini text call.
    if mode == "combined":
        log("Combined mode: parsing inline answers from Q-PDF chunks")
        for c in q_chunks:
            q_num = int(c["questionNumber"])
            ans_match = _CORRECT_ANSWER_RE.search(c["chunkText"])
            if ans_match:
                correct = ans_match.group(1).upper()
                expl = c["chunkText"][ans_match.end():].strip()
                expl = _clean_explanation_chrome(expl)
                answers_by_q[q_num] = {"correctAnswer": correct, "explanationText": expl}

    # 5. Figure detection on Q-PDF (smart-triggered)
    figures_by_q = detect_and_attach_figures(
        q_pdf,
        question_to_page,
        stems_by_q,
        is_screenshot_pdf=q_is_screenshot,
        job_output_root=job_output_root,
    )
    log(f"Figures attached: {sum(len(v) for v in figures_by_q.values())} on {len(figures_by_q)} question(s)")

    # 6. Per-question assembly
    questions: list[dict[str, Any]] = []
    q_numbers = sorted(stems_by_q.keys())
    for q_num in q_numbers:
        stem = stems_by_q.get(q_num, "")
        choices = choices_by_q.get(q_num, [])
        ans = answers_by_q.get(q_num)
        figures = figures_by_q.get(q_num, [])

        if ans and ans.get("correctAnswer") and ans.get("explanationText"):
            # We have a clean A-PDF (or inline) answer. v4.61 follow-up: run
            # the canonical polish call so retrievalTag, reviewPearl, and
            # educationalObjective get real values (the prior happy-path
            # string-split left these as placeholders).
            correct_answer = ans["correctAnswer"]
            expl_text = ans["explanationText"]
            log(f"  q{q_num}: polishing canonical fields via Gemini")
            polished = gemini_polish_question(stem, choices, correct_answer, expl_text)
            explanation_sections = polished.get("explanationSections") or [
                {"heading": "Correct Answer Explanation", "body": [expl_text]},
                {"heading": "Incorrect Answer Explanation", "body": ["See correct answer explanation."]},
                {"heading": "Educational Objective", "body": ["Apply the tested clinical reasoning."]},
            ]
            review_pearl = str(polished.get("reviewPearl") or "").strip() or "Refer to the explanation."
            retrieval_tag = str(polished.get("retrievalTag") or "").strip()
            educational_objective = str(polished.get("educationalObjective") or "").strip()
            if polished.get("_polishFailed"):
                warnings_list.append(f"q{q_num}: canonical polish failed ({polished['_polishFailed']}); using raw explanation text")
        elif stem and choices:
            # Either Q-only mode (no A-PDF) OR dual mode but A-PDF block missing
            # / incomplete for this question (OCR garbled the "Correct Answer"
            # line, or the block was on a page the chunker missed). Fall through
            # to Gemini completion — cheaper than re-OCR'ing the page.
            fallback_reason = "q_only mode" if mode == "q_only" else "dual mode but A-PDF block missing/garbled"
            log(f"  q{q_num}: Gemini completion fallback ({fallback_reason})")
            completion_failed = False
            correct_answer = ""
            explanation_sections = []
            review_pearl = ""
            retrieval_tag = ""
            educational_objective = ""
            try:
                completion = gemini_complete_q_only(stem, choices)
                correct_answer = str(completion.get("correctAnswer") or "").strip().upper()
                explanation_sections = completion.get("explanationSections") or []
                review_pearl = str(completion.get("reviewPearl") or "")
                retrieval_tag = str(completion.get("retrievalTag") or "")
                educational_objective = str(completion.get("educationalObjective") or "")
                if mode == "dual":
                    warnings_list.append(f"q{q_num}: A-PDF block missing — Gemini generated explanation")
            except Exception as exc:
                # Tier 5 fallback: rather than drop the question entirely,
                # ship a stub with the deterministic stem + choices and a
                # warning. User can still see the question in the app.
                completion_failed = True
                warnings_list.append(f"q{q_num}: Gemini completion failed ({exc}); shipping stub with extractionWarnings")
                explanation_sections = [
                    {"heading": "Correct Answer Explanation", "body": [
                        "Could not be auto-generated. Please review the question stem and choices and add an explanation manually."
                    ]},
                    {"heading": "Incorrect Answer Explanation", "body": [""]},
                    {"heading": "Educational Objective", "body": [""]},
                ]
        else:
            # No stem or no choices at all — last-resort stub. Better than dropping
            # the question silently.
            log(f"  q{q_num}: no stem/choices extracted — emitting stub")
            warnings_list.append(f"q{q_num}: no stem/choices extracted; emitting stub for manual review")
            correct_answer = ""
            explanation_sections = [
                {"heading": "Correct Answer Explanation", "body": [
                    "Stem and answer choices could not be extracted from the source PDF. Please review the original PDF for question " f"{q_num}" "."
                ]},
                {"heading": "Incorrect Answer Explanation", "body": [""]},
                {"heading": "Educational Objective", "body": [""]},
            ]
            review_pearl = ""
            retrieval_tag = ""
            educational_objective = ""
            # Use whatever we have for stem; choices may be empty.
            stem = stem or f"[Question {q_num} could not be extracted — see source PDF page {question_to_page.get(q_num, '?')}]"

        questions.append(assemble_question(
            q_num=q_num,
            stem=stem,
            choices=choices,
            correct_answer=correct_answer,
            explanation_sections=explanation_sections,
            review_pearl=review_pearl,
            educational_objective=educational_objective,
            retrieval_tag=retrieval_tag,
            figures=figures,
        ))

    # 7. Write app-ready JSON to the job dir
    app_ready_dir = job_output_root / "app_ready"
    app_ready_dir.mkdir(parents=True, exist_ok=True)
    source_stem = q_pdf.stem
    app_path = app_ready_dir / f"{source_stem}_app_ready.json"
    app_ready = build_app_ready(questions, source_stem, warnings_list)
    app_path.write_text(json.dumps(app_ready, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"App-ready written: {app_path} ({len(questions)} question(s))")

    return {
        "mode": mode,
        "questions": len(questions),
        "appReadyPath": str(app_path),
        "warnings": warnings_list,
        "geminiCalls": _call_count,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NBME dual-PDF orchestrator (v4.61)")
    parser.add_argument("--input-file", default="", help="Optional explicit input file. BIC iterates and passes one per call; the runner reads the full input list from the BIC manifest.")
    args = parser.parse_args(argv)

    job_output_root = os.environ.get("BIC_JOB_OUTPUT_ROOT")
    if not job_output_root:
        # Local-CLI mode for testing — use a temp dir if BIC env not set.
        if args.input_file:
            job_output_root = str(Path(args.input_file).parent / f".nbme_runner_test_{int(time.time())}")
        else:
            print("ERROR: BIC_JOB_OUTPUT_ROOT not set and no --input-file provided.", file=sys.stderr)
            return 1
    job_root = Path(job_output_root)
    job_root.mkdir(parents=True, exist_ok=True)

    marker = job_root / "nbme_orchestration_done.flag"
    if marker.exists():
        log("nbme_orchestration_done.flag present; this BIC iteration is a duplicate. Skipping.")
        return 0

    inputs = discover_job_inputs()
    if not inputs and args.input_file:
        inputs = [Path(args.input_file).expanduser().resolve()]
    if not inputs:
        warn("No inputs discovered from BIC manifest or CLI; nothing to do.")
        return 1

    started = time.time()
    try:
        result = orchestrate(inputs, job_root)
    except Exception as exc:
        warn(f"Orchestration failed: {exc}")
        marker.write_text(json.dumps({
            "status": "failed",
            "error": str(exc),
            "timestamp": datetime.now().isoformat(),
        }))
        return 1
    result["runtimeSeconds"] = round(time.time() - started, 2)
    marker.write_text(json.dumps({"status": "completed", **result, "timestamp": datetime.now().isoformat()}, indent=2))
    log(f"Orchestration complete in {result['runtimeSeconds']}s — {result['questions']} questions, {result['geminiCalls']} Gemini call(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
