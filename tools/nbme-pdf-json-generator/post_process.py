#!/usr/bin/env python3
"""NBME extractor post-processing — runs on every NBME app-ready JSON
right before it's written, cleaning up the seven OCR-failure modes
that the v4.85 extractor leaks on image-only NBME PDFs.

Triggered automatically by `normalized_to_app_json._convert_question`.
Idempotent — running the cleanup on an already-clean field is a no-op.

Bug catalog (with examples observed in NBME 3-8 imports):

  A. OCR footer garbage at the END of Incorrect Answer Explanation
     bodies. The page footer of the answer PDF gets OCR'd as
     `"4 > @ (a EC © @"` or `"(4 nf (/ (a eC i> iu"` and concatenated
     to the explanation text. Always short, always last paragraph.
  B. Entire explanation body IS only footer garbage. The legitimate
     content was lost — this case is detected and flagged via
     `extractionWarnings`; the post-processor cannot recover content.
     Use the v4.85.1 Vision re-OCR companion script for these cases.
  C. Stem prefix junk:
       - leading question number `"NN."`
       - `"■ Mark NN. "` UI button label (NBME 6 issue)
       - `"25mm/s"` / `"Nmm/s"` ECG paper speed merged from figure
       - `"ng:"` / `"les show:"` OCR fragments
       - ECG figure caption gibberish (single-letter OCR junk
         preceding the canonical opener)
  D. Lost stem opener — patient demographics missing. Detected and
     flagged; the post-processor cannot recover the missing text.
  E. Subscript-as-comma OCR (`B,,` → B12, `S,` → S3, `HCO,` → HCO3,
     `PCO,` → PCO2, `PO,` → PO2).
  F. Choice count != 5 — informational flag (some 4/6/7/8-choice
     questions are legitimate NBME formats: lab tables, matching).
  G. Table-format answer choices with bare numeric values
     `"112 | 3.4 | 78 | 24 | 7.40"` — inject the column labels from
     the stem header line so the renderer can show each cell as
     `"Na+ (mEq/L) 112 | K+ (mEq/L) 3.4 | ..."` (matches the format
     the user has verified renders correctly).
"""
from __future__ import annotations

import re
from typing import Any


# ── Bug A: OCR footer garbage detector ───────────────────────────────────────

FOOTER_GARBAGE_RE = re.compile(r"^\s*[\d>@()/\\nNFfAaecCEiIUu©\s.,'\"\-—–]{3,45}\s*$")
FOOTER_GARBAGE_KEYWORDS = re.compile(
    r"(?:[©@>]|nf|eC|EC|i>|\(/|aEC|aeC|nf\s*\(|\(a\s*eC)", re.IGNORECASE
)


def strip_footer_garbage(body: str) -> tuple[str, bool]:
    """Drop trailing paragraphs (\\n\\n-separated) that are pure
    footer garbage. Returns (cleaned_body, changed)."""
    if not body or not body.strip():
        return body, False
    parts = re.split(r"\n\n+", body)
    changed = False
    while parts:
        tail = parts[-1].strip()
        if not tail:
            parts.pop()
            changed = True
            continue
        if FOOTER_GARBAGE_RE.match(tail) and FOOTER_GARBAGE_KEYWORDS.search(tail) and len(tail) < 45:
            parts.pop()
            changed = True
            continue
        break
    return "\n\n".join(parts), changed


def body_is_only_garbage(body: str) -> bool:
    """True iff the entire body, after whitespace normalization, is
    short OCR junk with no real prose. Caller marks the question for
    Vision re-OCR when this returns True."""
    if not body or not body.strip():
        return True
    clean = body.strip()
    if len(clean) >= 50:
        return False
    return bool(FOOTER_GARBAGE_RE.match(clean) and FOOTER_GARBAGE_KEYWORDS.search(clean))


# ── Bug C: stem prefix junk ──────────────────────────────────────────────────

CANONICAL_OPENER_RE = re.compile(
    r"^(?:A|An)\s+(?:previously|otherwise|hospitalized|asymptomatic|moderately|healthy|N|\d+)"
    r"|^(?:Six|Twelve|Two|Three|Four|Five|One)\s+(?:hours?|days?|weeks?|months?)"
    r"|^(?:For|Following|During|Prior|Immediately|Initial|A study|A patient|A healthy|"
    r"A previously|A hospitalized|An otherwise|An asymptomatic|An obese|A moderately|"
    r"A normally|A research|Investigators)",
    re.IGNORECASE,
)


def find_canonical_opener_start(stem: str) -> int:
    """Index where the canonical NBME opener begins, or -1 if the
    stem has no canonical opener in its first 600 chars (Bug D)."""
    if CANONICAL_OPENER_RE.match(stem):
        return 0
    m = CANONICAL_OPENER_RE.search(stem[:600])
    return m.start() if m else -1


JUNK_PREFIX_PATTERNS = [
    re.compile(r"^\s*\d{1,2}\s*\.\s*"),                                   # "NN. "
    re.compile(r"^[■□▢◾◽█▪▫◼◻]\s*Mark\s+\d{0,3}\s*\.?\s*"),                # ■ Mark NN.
    re.compile(r"^\d{0,2}\s*mm\s*/\s*s\s*\n+"),                           # ECG paper speed
    re.compile(r"^(?:ng|les show|tudies show|owing|wsec)\s*:?\s*\n+", re.IGNORECASE),
]


def strip_stem_prefix_junk(stem: str) -> tuple[str, bool]:
    """Strip every junk prefix pattern, looping until stable. Returns
    (cleaned_stem, changed)."""
    changed = False
    prev = None
    while prev != stem:
        prev = stem
        for pat in JUNK_PREFIX_PATTERNS:
            new = pat.sub("", stem)
            if new != stem:
                stem = new
                changed = True
                break
    # ECG / figure-caption sniff: if there's high-junk preamble
    # before a canonical opener, drop the preamble.
    opener = find_canonical_opener_start(stem)
    if opener > 0:
        preamble = stem[:opener]
        non_word_ratio = sum(
            1 for c in preamble if not c.isalnum() and not c.isspace()
        ) / max(len(preamble), 1)
        junk_tokens = sum(
            1 for t in preamble.split()
            if len(t) <= 2 or not re.match(r"^[a-zA-Z]{3,}$", t)
        )
        token_count = max(len(preamble.split()), 1)
        if (
            (non_word_ratio > 0.25 and len(preamble.strip()) > 6)
            or (junk_tokens / token_count > 0.5 and len(preamble.strip()) > 6)
            or len(preamble.strip()) > 200
        ):
            stem = stem[opener:]
            changed = True
    return stem, changed


# ── Bug E: subscript-as-comma fixes ──────────────────────────────────────────

SUBSCRIPT_FIXES = [
    (re.compile(r"\b([Vv])itamin\s+B\s*,,(?=\s*\((cobalamin|cyanocobalamin)\))"), r"\1itamin B12"),
    (re.compile(r"\b([Vv])itamin\s+B\s*,,"), r"\1itamin B12"),
    (re.compile(r"\bB\s*,,(?=\s*\((cobalamin|cyanocobalamin)\))"), "B12"),
    (re.compile(r"\b([Vv])itamin\s+B,(?=\s*\(thiamine\))"), r"\1itamin B1"),
    (re.compile(r"There\s+is\s+an?\s+S,(?!\d)"), "There is an S3"),
    (re.compile(r"\bS,\s+gallop\b"), "S3 gallop"),
    (re.compile(r"\bHCO\s*,(?!\d)"), "HCO3"),
    (re.compile(r"\bHCO3-\s*-"), "HCO3-"),
    (re.compile(r"\bPCO\s*,(?!\d)"), "PCO2"),
    (re.compile(r"\bPO\s*,(?!\d)"), "PO2"),
    (re.compile(r"\bPco\b(?!\d)"), "PCO2"),
]


def apply_subscript_fixes(text: str) -> tuple[str, int]:
    n = 0
    for pat, repl in SUBSCRIPT_FIXES:
        new = pat.sub(repl, text)
        if new != text:
            n += 1
            text = new
    return text, n


# ── Bug G: table column labels ───────────────────────────────────────────────

TABLE_HEADER_LINE_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9+\-]*\s*\([^)]+\)(?:\s*\|\s*(?:[A-Za-z][A-Za-z0-9+\-]*\s*\([^)]+\)|pH))+(?:\s*\|\s*pH)?)",
)
BARE_VALUE_RE = re.compile(r"^\s*[\d.+\-]+\s*$")


def find_table_headers(stem: str) -> list[str] | None:
    for m in TABLE_HEADER_LINE_RE.finditer(stem):
        line = m.group(1).strip()
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        unit_count = sum(1 for p in parts if "(" in p or p.lower() == "ph")
        if unit_count >= 2:
            return parts
    return None


def inject_column_labels(choices: list[dict[str, Any]], headers: list[str]) -> bool:
    if not choices or not headers:
        return False
    matched = sum(
        1 for c in choices
        if len([p for p in (c.get("text") or "").split("|")]) == len(headers)
        and all(BARE_VALUE_RE.match(p.strip()) for p in c.get("text", "").split("|") if p.strip())
    )
    if matched < max(2, len(choices) // 2):
        return False
    changed = False
    for c in choices:
        parts = [p.strip() for p in (c.get("text") or "").split("|")]
        if len(parts) != len(headers):
            continue
        if not all(BARE_VALUE_RE.match(p) for p in parts if p):
            continue
        labeled = []
        for j, val in enumerate(parts):
            header = headers[j].strip()
            labeled.append(f"pH {val}" if header.lower() == "ph" else f"{header} {val}")
        new_text = " | ".join(labeled)
        if new_text != c.get("text"):
            c["text"] = new_text
            changed = True
    return changed


# ── Driver: applied per question during normalized → app-ready conversion ─

def post_process_question(q: dict[str, Any]) -> list[str]:
    """Apply all deterministic post-processor rules to an already-built
    app-ready question dict. Returns a list of warnings to attach to
    `extractionWarnings`.
    """
    notes: list[str] = []

    # Bug C: stem prefix cleanup
    stem = q.get("stem") or ""
    if stem:
        new_stem, changed = strip_stem_prefix_junk(stem)
        if changed:
            q["stem"] = new_stem
            notes.append("post_process: stripped stem prefix junk")
        # Bug D: lost-opener detection
        if find_canonical_opener_start(q["stem"]) < 0:
            notes.append("post_process: stem missing canonical opener (needs Vision re-OCR)")

    # Bug E: subscript fixes across stem + choices + explanations
    fixes = 0
    if q.get("stem"):
        new_text, n = apply_subscript_fixes(q["stem"])
        if n:
            q["stem"] = new_text
            fixes += n
    for c in q.get("answerChoices") or []:
        if c.get("text"):
            new_text, n = apply_subscript_fixes(c["text"])
            if n:
                c["text"] = new_text
                fixes += n
    for s in q.get("explanationSections") or []:
        for i, b in enumerate(s.get("body") or []):
            new_b, n = apply_subscript_fixes(b)
            if n:
                s["body"][i] = new_b
                fixes += n
    if fixes:
        notes.append(f"post_process: applied {fixes} subscript fix(es)")

    # Bug G: inject column labels into table choices
    if q.get("stem") and q.get("answerChoices"):
        headers = find_table_headers(q["stem"])
        if headers and inject_column_labels(q["answerChoices"], headers):
            notes.append(f"post_process: injected {len(headers)} column labels into table choices")

    # Bug A + B: scrub explanation tails / detect garbage-only bodies
    for s in q.get("explanationSections") or []:
        heading = s.get("heading", "")
        for i, b in enumerate(s.get("body") or []):
            if body_is_only_garbage(b):
                notes.append(f"post_process: '{heading}' body is only OCR garbage (needs Vision re-OCR)")
                continue
            new_b, changed = strip_footer_garbage(b)
            if changed:
                s["body"][i] = new_b
                notes.append(f"post_process: stripped footer garbage from '{heading}'")

    # Bug F: informational flag for non-5 choice counts
    n_choices = len(q.get("answerChoices") or [])
    if n_choices != 5:
        notes.append(f"post_process: choice count is {n_choices} (some 4/6/7/8-choice NBME formats are legitimate — verify)")

    return notes
