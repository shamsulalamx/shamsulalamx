#!/usr/bin/env python3
"""UWorld-family → v5.2 allocation adapter (v5.8 ship, promoted from
the original v5.3 OME-specific adapter).

Shared by every source whose generator extends
`tools/uworld-notes-question-generator/generate_uworld_questions.py`:
  - OME PDF      (since v5.3)
  - UWorld notes (since v5.8)
  - Mehlman PDF  (since v5.8)
  - Anki notes   (since v5.8)
  - Divine podcast transcripts (since v5.8)

All of these use the uworld base's `split_into_chunks(text, max_chars)`
helper, which produces the same `{"chunkIndex", "chunkText", "charCount"}`
chunk shape. The adapter doesn't care which source produced the text —
it just turns chunks into v5 allocations.

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
    questions_per_file: int = 0,
    questions_per_chunk: int = 0,
    min_chunk_chars: int = MIN_CHUNK_CHARS_FOR_V5,
) -> List[Dict[str, Any]]:
    """Convert OME chunks into v5 allocations.

    Two budget modes:
      - questions_per_chunk > 0: each eligible chunk gets exactly that
        many questions. This is the v5.6 mode — the chunker controls
        coverage density by chunk size, the user controls depth per
        chunk. Total questions scale with the PDF's text length.
      - questions_per_chunk == 0 (legacy): the questions_per_file
        budget is distributed across eligible chunks via floor-split.
        Pre-v5.6 callers keep working unchanged.

    `source_stem` is used for stable slideId derivation. `chunks` is
    the output of `_uw.split_into_chunks()`. Chunks shorter than
    `min_chunk_chars` are dropped before distribution — these tend to
    be page headers ("## Page 1") or isolated text fragments that
    can't ground a clinical vignette.
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
    # v5.6: when questions_per_chunk is set, give every eligible chunk
    # that exact count. Otherwise fall back to v5.3-style distribution
    # of questions_per_file across the eligible chunks.
    if questions_per_chunk and questions_per_chunk > 0:
        per_chunk = [int(questions_per_chunk)] * len(eligible)
    else:
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


def decorate_v5_questions_for_uworld_family(v5_questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add the legacy uworld-family app-ready fields that v5 doesn't emit.

    v5 produces questions shaped for the lecture-slide canonical
    schema: `questionNumber`, `slideId`, `stem`, `answerChoices`,
    `correctAnswer`, `explanationSections`, `_v5_2`, ... The legacy
    uworld-family schema (shared by OME, UWorld, Mehlman, Anki, Divine)
    also expects `id`, `sourceQuestionNumber`, `retrievalTag`,
    `reviewPearl`, `clinicalPearl`.

    v5.6.1: `retrievalTag` / `reviewPearl` / `educationalObjective`
    are now produced as DISTINCT fields by the kernel and assembled
    by `assemble_question`. This function just passes them through;
    the fallback below only fires when the kernel output predates
    v5.6.1 (e.g., re-assembling a cached old kernel). Pre-v5.6.1
    this function was the bug site — it routed all three fields
    through the same `correctAnswerConcept` value, making them
    identical strings in the output.
    """
    out: List[Dict[str, Any]] = []
    for q in v5_questions:
        decorated = dict(q)
        n = int(decorated.get("questionNumber") or (len(out) + 1))
        decorated["id"] = f"q{n:03d}"
        decorated["sourceQuestionNumber"] = n
        concept = (decorated.get("testedConcept") or "").strip()
        edu = (decorated.get("educationalObjective") or "").strip()
        # Fallback chain only for pre-v5.6.1 questions where the kernel
        # didn't emit retrievalTag / reviewPearl. New kernels populate
        # these fields directly in assemble_question; this leaves
        # whatever the kernel produced untouched.
        if not (decorated.get("retrievalTag") or "").strip():
            decorated["retrievalTag"] = (concept or "OME organic v5.2")[:120]
        if not (decorated.get("reviewPearl") or "").strip():
            decorated["reviewPearl"] = (edu or concept or "")[:300]
        decorated.setdefault("clinicalPearl", None)
        out.append(decorated)
    return out


# ── Backward-compat alias (so OME code that imports the original
# function name keeps working without touching the call sites) ──
decorate_v5_questions_for_ome = decorate_v5_questions_for_uworld_family


# ── Shared v5 dispatch helpers (v5.8) ────────────────────────────────────────


def parse_mix_arg(arg: str, keys: list, label: str) -> Dict[str, float]:
    """Parse a comma-separated mix like '0.25,0.45,0.30' into a dict
    keyed by `keys`. Raises ValueError on malformed input. Tolerates
    a small rounding band (~2%) on the sum. Shared by every uworld-
    family generator's `--v5-order-mix` / `--v5-difficulty-mix` flag
    parsing."""
    parts = [p.strip() for p in arg.split(",") if p.strip()]
    if len(parts) != len(keys):
        raise ValueError(f"--{label} must have {len(keys)} comma-separated floats, got {len(parts)}: {arg!r}")
    values = [float(p) for p in parts]
    if abs(sum(values) - 1.0) > 0.02:
        raise ValueError(f"--{label} must sum to ~1.0, got {sum(values):.3f}: {arg!r}")
    return dict(zip(keys, values))


def process_file_v5_uworld_family(
    *,
    uw_module: Any,
    filepath: Any,
    questions_per_file: int,
    v5_cfg: Dict[str, Any],
    report_data: Dict[str, Any],
    pipeline_label: str = "v5.2-organic",
    chunk_size: int = 3000,
    questions_per_chunk: int = 0,
    v5_pipeline_dir: Any = None,
    pre_extracted_text: Any = None,
    output_stem: Any = None,
) -> Any:
    """v5 dispatch shared across every uworld-family generator (OME,
    UWorld, Mehlman, Anki, Divine). Mirrors the legacy `_uw.process_file()`
    filesystem side effects (raw_text/, chunks/, generated/, app_ready/)
    and report shape so BIC's downstream consumers don't need source-
    specific handling.

    Each generator hands in:
      - `uw_module`:           the imported `generate_uworld_questions`
                               module with its per-source monkey patches
                               (extract_text, SUPPORTED_EXTENSIONS,
                               build_app_ready_json, path globals) already
                               applied.
      - `filepath`:            the input file Path.
      - `questions_per_file`:  legacy budget; used only when
                               `questions_per_chunk` is 0 (v5.3 mode).
      - `v5_cfg`:              dict with `order_mix`, `difficulty_mix`,
                               `seed` (parsed by the generator from its
                               CLI flags).
      - `report_data`:         the rolling per-file report dict the
                               generator builds for its `write_report`
                               call.
      - `pipeline_label`:      tag put in the app-ready JSON's
                               `pipeline` field (default "v5.2-organic").
      - `chunk_size`:          v5.6 char cap for `split_into_chunks`.
      - `questions_per_chunk`: v5.6 per-chunk Q count (0 = v5.3 mode).
      - `v5_pipeline_dir`:     optional explicit path to the directory
                               holding v5_pipeline.py. When None, the
                               function looks for it as a sibling of
                               this shared adapter's parent (i.e.,
                               tools/lecture-slide-question-generator/).

    Raises `RuntimeError("no_v5_allocations")` when zero chunks pass
    the size filter — the caller can catch this and fall back to
    legacy `_uw.process_file()`.
    """
    # Lazy imports — keep this module light when v5 isn't engaged.
    import json
    import sys
    import time
    from pathlib import Path
    t_start = time.time()
    uw_module.log(f"Processing (v5): {filepath.name}")
    # `output_stem` lets Divine (which already wrote a `{stem}_cleaned.txt`
    # to disk and would otherwise produce `{stem}_cleaned_app_ready.json`)
    # ship its app-ready file under the original audio/transcript stem.
    stem = str(output_stem) if output_stem else filepath.stem

    # 1. Extract raw text. Sources that already have the text (e.g.
    # Divine's cleaned transcript) pass it via `pre_extracted_text`
    # so the shared adapter skips disk I/O.
    if pre_extracted_text is not None:
        raw_text = str(pre_extracted_text)
    else:
        raw_text = uw_module.extract_text(filepath)
    if not raw_text.strip():
        uw_module.warn(f"No text extracted from {filepath.name} — skipping (v5).")
        report_data["files"][filepath.name] = {"status": "skipped", "reason": "empty_text"}
        return None

    raw_path = uw_module.RAW_DIR / f"{stem}_raw.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(raw_text, encoding="utf-8")
    uw_module.log(f"  Raw text saved → {raw_path.name} ({len(raw_text):,} chars)")

    # 2. Chunk with the requested cap.
    chunks = uw_module.split_into_chunks(raw_text, max_chars=int(chunk_size))
    chunk_path = uw_module.SEGMENT_DIR / f"{stem}_chunks.json"
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_path.write_text(
        json.dumps({"sourceFile": filepath.name, "chunks": chunks, "chunkSize": int(chunk_size)}, indent=2),
        encoding="utf-8",
    )
    uw_module.log(f"  {len(chunks)} chunk(s) (max_chars={chunk_size}) → {chunk_path.name}")

    # 3. Build v5 allocations.
    allocations = build_v5_allocations(
        source_stem=stem.replace(" ", "_"),
        chunks=chunks,
        questions_per_file=questions_per_file,
        questions_per_chunk=int(questions_per_chunk),
    )
    if not allocations:
        uw_module.warn(f"v5: no eligible chunks for {filepath.name} after size filter; falling back to legacy.")
        raise RuntimeError("no_v5_allocations")
    total_alloc_qs = sum(int(a.get("questionCount") or 0) for a in allocations)
    uw_module.log(
        f"  v5 allocations: {len(allocations)} chunk(s), {total_alloc_qs} question slot(s) "
        f"(Q/chunk={questions_per_chunk or 'auto'})"
    )

    # 4. Locate and run the v5 pipeline.
    if v5_pipeline_dir is None:
        v5_pipeline_dir = Path(__file__).resolve().parent.parent / "lecture-slide-question-generator"
    if str(v5_pipeline_dir) not in sys.path:
        sys.path.insert(0, str(v5_pipeline_dir))
    import v5_pipeline as v5  # type: ignore
    started_v5 = time.time()
    v5_questions = v5.generate_v5(
        normalized_payload={"sourceFile": str(filepath)},
        allocations=allocations,
        memory={},
        target_order_mix=v5_cfg["order_mix"],
        target_difficulty_mix=v5_cfg["difficulty_mix"],
        seed=v5_cfg["seed"],
    )
    v5_elapsed = round(time.time() - started_v5, 1)
    uw_module.log(f"  v5 produced {len(v5_questions)} question(s) in {v5_elapsed}s")

    # 5. Decorate v5 questions with legacy uworld-family fields.
    decorated = decorate_v5_questions_for_uworld_family(v5_questions)
    gen_path = uw_module.GEN_DIR / f"{stem}_generated.json"
    gen_path.parent.mkdir(parents=True, exist_ok=True)
    gen_path.write_text(json.dumps(decorated, indent=2, ensure_ascii=False), encoding="utf-8")
    uw_module.log(f"  Generated JSON → {gen_path.name} ({len(decorated)} questions)")

    # 6. Wrap in canonical app-ready shape. Each source patches
    # `_uw.build_app_ready_json` to set its own sourceFormat tag, so
    # this call automatically lands the correct one.
    file_warnings = []
    if total_alloc_qs and len(v5_questions) < total_alloc_qs:
        file_warnings.append(
            f"v5 produced {len(v5_questions)}/{total_alloc_qs} requested questions"
            f" (some slots failed pipeline gates and were skipped)"
        )
    app_json = uw_module.build_app_ready_json(stem, decorated, file_warnings)
    app_json["pipeline"] = pipeline_label
    app_path = uw_module.APP_DIR / f"{stem}_app_ready.json"
    app_path.parent.mkdir(parents=True, exist_ok=True)
    app_path.write_text(json.dumps(app_json, indent=2, ensure_ascii=False), encoding="utf-8")
    uw_module.log(f"  App-ready JSON → {app_path.name} ({len(decorated)} questions)")

    elapsed = round(time.time() - t_start, 1)
    report_data["files"][filepath.name] = {
        "status":             "ok",
        "rawChars":           len(raw_text),
        "chunksProcessed":    len(chunks),
        "questionsGenerated": len(decorated),
        "v5Allocations":      len(allocations),
        "v5RequestedSlots":   total_alloc_qs,
        "v5ElapsedSeconds":   v5_elapsed,
        "needsReviewCount":   0,
        "reviewDraftPath":    "",
        "validationFailures": 0,
        "retries":            0,
        "repairsSucceeded":   0,
        "repairFailures":     0,
        "validationWarnings": [],
        "warnings":           file_warnings,
        "chunkStats":         [],
        "outputPaths": {
            "appReady":  str(app_path),
            "generated": str(gen_path),
            "chunks":    str(chunk_path),
            "rawText":   str(raw_path),
        },
        "elapsedSeconds": elapsed,
        "dryRun":         False,
        "pipeline":       pipeline_label,
    }
    return app_json


def resolve_v5_cfg(args: Any) -> Dict[str, Any]:
    """Build the `v5_cfg` dict from an argparse Namespace that carries
    `--v5-order-mix`, `--v5-difficulty-mix`, and `--v5-seed`. Raises
    ValueError on malformed mix strings."""
    return {
        "order_mix": parse_mix_arg(
            args.v5_order_mix,
            ["first_order", "second_order", "third_order"],
            "v5-order-mix",
        ),
        "difficulty_mix": parse_mix_arg(
            args.v5_difficulty_mix,
            ["easy", "medium", "difficult"],
            "v5-difficulty-mix",
        ),
        "seed": int(args.v5_seed),
    }


def add_v5_cli_args(parser: Any, include_chunk_args: bool = True) -> None:
    """Attach the v5 CLI flags to an argparse parser. Each Group B
    generator calls this from its `main()` so the flag spec stays
    identical across sources.

    `include_chunk_args=False` skips `--chunk-size` and
    `--questions-per-chunk`. Useful for generators (like Mehlman)
    that already have a `--questions-per-chunk` flag in their
    legacy CLI — they reuse it for v5 instead of having two
    conflicting flags.
    """
    parser.add_argument(
        "--v5",
        action="store_true",
        help=(
            "Use the v5.2 multi-stage organic generator (kernel → stem → "
            "distractors → critic → regen → length parity → image route → "
            "assemble). Higher cost (~$0.14/Q at v5.6 budgets) but produces "
            "NBME-authentic questions with order/difficulty stratification, "
            "4 distinct trap-category distractors per question, and balanced "
            "answer position distribution. The legacy single-call path is "
            "the default and is preserved as the fallback when v5 raises."
        ),
    )
    parser.add_argument(
        "--v5-order-mix",
        default="0.25,0.45,0.30",
        help="v5 only: first_order,second_order,third_order shares.",
    )
    parser.add_argument(
        "--v5-difficulty-mix",
        default="0.30,0.45,0.25",
        help="v5 only: easy,medium,difficult shares.",
    )
    parser.add_argument(
        "--v5-seed",
        type=int,
        default=0,
        help="v5 only: RNG seed for reproducible per-Q position randomization.",
    )
    if include_chunk_args:
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=3000,
            help=(
                "v5 only: max characters per chunk passed to the v5 kernel "
                "(default 3000 = pre-v5.6 behavior). Smaller chunks give finer "
                "per-paragraph coverage; larger chunks pack more concept context."
            ),
        )
        parser.add_argument(
            "--questions-per-chunk",
            type=int,
            default=0,
            help=(
                "v5 only: when >0, every eligible chunk gets exactly this many "
                "questions and the total scales with the number of chunks. When "
                "0 (default), falls back to distributing --questions-per-file "
                "across the eligible chunks (v5.3 behavior)."
            ),
        )
