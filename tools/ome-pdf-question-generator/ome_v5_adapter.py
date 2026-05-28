#!/usr/bin/env python3
"""OME-PDF → v5.2 allocation adapter (v5.3 ship).

The v5.2 multi-stage organic generator lives in
`tools/lecture-slide-question-generator/v5_pipeline.py`. It expects a list
of `allocations`, each shaped like:

    {
        "slideId":               "<stable id per chunk>",
        "questionCount":         <int>,
        "allowedMedicalTerms":   [<term>, ...],
        "allowedDistractorPool": [<term>, ...],
        "slideContext": {
            "slideTitle":         "<topic>",
            "clinicalFacts":      [<fact>, ...],
            "primaryConcepts":    [<concept>, ...],
            "secondaryConcepts":  [<concept>, ...],
            "highYield":          "<dense paragraph>",
            "fullText":           "<the raw chunk text>",
        },
        "slideImages":           [],
    }

The lecture-slide path builds these directly out of a structured slide
normalization. OME has no equivalent — its source is a single raw PDF
text run, optionally split into multiple topic chunks by
`_uw.split_into_chunks()`. This module is the OME-specific bridge: it
turns the OME chunk shape (`{"chunkIndex", "chunkText", "charCount"}`)
into the v5 allocation shape above.

Term extraction is deliberately conservative: we pull capitalized
multi-word phrases and Title Case headings from the chunk text. The
kernel/stem/distractor stages all have access to the raw `fullText`
field in slideContext as their grounding, so missing a term here only
costs us a tighter ALLOWED_TERMS list, not a fabrication risk — Gemini
2.5 Pro at thinking_budget=-1 reliably picks up additional terms from
the slideContext content itself.

This module imports nothing from v5_pipeline; it just emits the shape
v5 consumes. It can be unit-tested in isolation.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List


# ── Term extraction ──────────────────────────────────────────────────────────

# Match capitalized multi-word phrases (Title Case) and ALL CAPS headers.
# These tend to be diagnoses, drug names, structural labels, and section
# headings in OME slide-deck PDFs. Conservative: prefer false-negatives
# over false-positives (we'd rather miss a term than push a junk term
# into ALLOWED_MEDICAL_TERMS and have the kernel build a trap around it).
_TITLE_CASE_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:[-/][A-Z][a-z]+)*)(?:\s+(?:[A-Z][a-z]+|[A-Z]{2,}|of|the|and|in|to|for|with|on))*\s+(?:[A-Z][a-z]+|[A-Z]{2,})\b"
)
_ALL_CAPS_HEADER_RE = re.compile(r"\b([A-Z]{2,}(?:[\s\-/&][A-Z]{2,})*)\b")
_LEADING_BULLET_RE = re.compile(r"^[•\*\-•·\d]+[\.\)]?\s*")


def _clean_term(term: str) -> str:
    """Normalize whitespace and strip leading bullet artifacts."""
    term = _LEADING_BULLET_RE.sub("", term.strip())
    term = re.sub(r"\s+", " ", term)
    return term.strip(",.;: ")


def extract_terms(text: str, *, max_terms: int = 60) -> List[str]:
    """Pull medical-looking terms from a chunk of raw text.

    Returns a deduplicated list (case-insensitive), preserving first-
    seen order so the caller can use it as both ALLOWED_TERMS and a
    seed for the distractor pool without reshuffling Gemini's view of
    which terms are "primary".

    Returns at most `max_terms` items. Anything above that cap gets
    truncated — the v5 kernel does not need a 200-item ALLOWED list,
    and a bloated list dilutes the kernel's choice signal.
    """
    if not text:
        return []
    seen: set[str] = set()
    out: List[str] = []

    for match in _TITLE_CASE_RE.findall(text):
        term = _clean_term(match)
        if 3 <= len(term) <= 80 and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
            if len(out) >= max_terms:
                return out

    for match in _ALL_CAPS_HEADER_RE.findall(text):
        term = _clean_term(match)
        if 3 <= len(term) <= 80 and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
            if len(out) >= max_terms:
                return out

    return out


# ── Slide-context construction ───────────────────────────────────────────────

_SECTION_HEADING_RE = re.compile(r"^(#{1,6}\s+.+|[A-Z][A-Z\s\-/&]{4,}:?)$", re.MULTILINE)


def _derive_title(chunk_text: str, fallback: str) -> str:
    """First-line / first-heading heuristic for the chunk's display title."""
    for line in chunk_text.splitlines():
        s = line.strip()
        if not s:
            continue
        s = _LEADING_BULLET_RE.sub("", s)
        if s.startswith("#"):
            return s.lstrip("#").strip()[:120]
        if len(s) > 6 and len(s) < 160:
            return s[:120]
    return fallback


def _split_facts(chunk_text: str, *, max_facts: int = 30) -> List[str]:
    """Split the chunk into clinical-fact-shaped lines.

    OME PDFs typically have one fact per line (slide-deck origin). We
    split on newlines, drop empty lines and pure headings, and truncate
    to `max_facts` to keep the slideContext JSON dump reasonable. Long
    paragraphs survive as single facts — the v5 prompts can handle that.
    """
    facts: List[str] = []
    for raw in chunk_text.splitlines():
        s = raw.strip()
        if not s:
            continue
        # Drop bullets but keep the substance
        s = _LEADING_BULLET_RE.sub("", s)
        if not s or len(s) < 12:
            continue
        # Skip lines that are obviously a bare heading (no terminal
        # punctuation, very short, ALL CAPS) — they become the title
        # instead.
        if s.isupper() and len(s.split()) <= 5:
            continue
        facts.append(s[:400])
        if len(facts) >= max_facts:
            break
    return facts


def build_slide_context(chunk: Dict[str, Any], *, fallback_title: str) -> Dict[str, Any]:
    """Turn one chunk dict into the v5 slideContext payload."""
    chunk_text = chunk.get("chunkText") or ""
    title = _derive_title(chunk_text, fallback_title)
    facts = _split_facts(chunk_text)
    terms = extract_terms(chunk_text)
    primary = terms[:8]
    secondary = terms[8:24]
    # `highYield` mirrors the lecture-slide adapter's "dense paragraph"
    # field — Gemini reads this as the topic summary. We use the first
    # ~600 chars of the chunk as a proxy.
    high_yield = (chunk_text or "").strip()[:600]
    return {
        "slideTitle":        title,
        "clinicalFacts":     facts,
        "primaryConcepts":   primary,
        "secondaryConcepts": secondary,
        "highYield":         high_yield,
        # `fullText` is the safety net — the kernel/stem/critic prompts
        # all see this. If the heuristic term extraction missed
        # something important, the model can still find it here.
        "fullText":          chunk_text,
    }


# ── Allocation builder ───────────────────────────────────────────────────────


def distribute_question_count(total: int, n_chunks: int) -> List[int]:
    """Same rule the legacy uworld-family generator uses:
    floor split + remainder front-loaded onto the first chunks."""
    if n_chunks <= 0 or total <= 0:
        return []
    base = total // n_chunks
    remainder = total - base * n_chunks
    return [base + (1 if i < remainder else 0) for i in range(n_chunks)]


# Minimum chars a chunk must have to be eligible for v5 generation.
# Page headers ("## Page 1", "## Page 2 ...") and stray text fragments
# do not give the kernel enough material to design a real question.
# Filtering them out before distributing question budget concentrates
# the question slots on chunks that carry teaching content.
MIN_CHUNK_CHARS_FOR_V5 = 200


def build_v5_allocations(
    *,
    source_stem: str,
    chunks: List[Dict[str, Any]],
    questions_per_file: int,
    min_chunk_chars: int = MIN_CHUNK_CHARS_FOR_V5,
) -> List[Dict[str, Any]]:
    """Convert OME chunks into v5 allocations.

    `source_stem` is used for stable slideId derivation. `chunks` is
    the output of `_uw.split_into_chunks()`. `questions_per_file` is
    the total question budget for this PDF, distributed across the
    chunks via `distribute_question_count`.

    Chunks shorter than `min_chunk_chars` are dropped before
    distribution — these tend to be page headers ("## Page 1") or
    isolated text fragments that can't ground a clinical vignette.
    """
    if not chunks:
        return []
    # Keep original chunk indices so the slideId stays traceable back
    # to the upstream chunker even after filtering.
    eligible = [
        (ci, chunk)
        for ci, chunk in enumerate(chunks)
        if int(chunk.get("charCount") or len(chunk.get("chunkText") or "")) >= min_chunk_chars
    ]
    if not eligible:
        # Fall back to the full chunk list if every chunk was below
        # the threshold — at least we don't silently return zero
        # allocations for a small PDF.
        eligible = list(enumerate(chunks))
    per_chunk = distribute_question_count(questions_per_file, len(eligible))
    allocations: List[Dict[str, Any]] = []
    for slot_idx, (ci, chunk) in enumerate(eligible):
        count = per_chunk[slot_idx] if slot_idx < len(per_chunk) else 0
        if count <= 0:
            continue
        ctx = build_slide_context(
            chunk,
            fallback_title=f"{source_stem} — section {ci + 1}",
        )
        terms = extract_terms(chunk.get("chunkText") or "")
        allocations.append({
            "slideId":               f"{source_stem}_chunk_{ci + 1:03d}",
            "questionCount":         count,
            "allowedMedicalTerms":   terms[:50],
            # Reuse the same term list as the distractor pool seed.
            # The v5 kernel prompt's wording calls this "alternate
            # sources for distractor items" — for OME there is no
            # second corpus, so the chunk's own term list IS the pool.
            "allowedDistractorPool": terms[:50],
            "slideContext":          ctx,
            # OME image extraction (extract-assets mode) writes figures
            # to disk but doesn't pass them to Gemini in v5 — staying
            # consistent with the in-scope plan for the v5.3 ship.
            "slideImages":           [],
        })
    return allocations


# ── v5-question → OME-app-ready field decoration ─────────────────────────────


def decorate_v5_questions_for_ome(v5_questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add the legacy OME app-ready fields that v5 doesn't emit.

    v5 produces questions shaped for the lecture-slide canonical
    schema: `questionNumber`, `slideId`, `stem`, `answerChoices`,
    `correctAnswer`, `explanationSections`, `_v5_2`, ... The OME
    legacy schema also expects `id`, `sourceQuestionNumber`,
    `retrievalTag`, `reviewPearl`, `clinicalPearl`. Without them,
    the BIC importer would reject the questions on the legacy
    sourceFormat path.

    We synthesize retrievalTag + reviewPearl from `_v5_2` /
    `testedConcept` / `educationalObjective` so the validation gate
    that requires both to be non-empty passes. These are derived from
    the kernel's own correctAnswerConcept — they aren't fabricated.
    """
    out: List[Dict[str, Any]] = []
    for q in v5_questions:
        decorated = dict(q)
        n = int(decorated.get("questionNumber") or (len(out) + 1))
        decorated["id"] = f"q{n:03d}"
        decorated["sourceQuestionNumber"] = n
        meta = decorated.get("_v5_2") or {}
        edu = decorated.get("educationalObjective") or meta.get("discriminatingClue") or decorated.get("testedConcept") or ""
        concept = decorated.get("testedConcept") or edu
        if "retrievalTag" not in decorated or not (decorated.get("retrievalTag") or "").strip():
            decorated["retrievalTag"] = (concept or "OME organic v5.2")[:120]
        if "reviewPearl" not in decorated or not (decorated.get("reviewPearl") or "").strip():
            decorated["reviewPearl"] = (edu or concept or "")[:300]
        decorated.setdefault("clinicalPearl", None)
        out.append(decorated)
    return out
