#!/usr/bin/env python3
"""
NBME Normalized JSON → App-Ready JSON converter (Milestone 5)

Reads every *_normalized.json from output_json/normalized/ and writes a
corresponding *_app_ready.json to output_json/app_ready/.

Output: canonical NBME Gemini JSON v3 schema accepted by validateNbmeGeminiJsonImport.

Usage:
  python3 normalized_to_app_json.py
  python3 normalized_to_app_json.py --dry-run   # validate only, no writes
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR     = Path(__file__).parent.resolve()
NORMALIZED_DIR = SCRIPT_DIR / "output_json" / "normalized"
APP_READY_DIR  = SCRIPT_DIR / "output_json" / "app_ready"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_SCHEMA_VERSION = "nbme-gemini-json-v3"

CONTAMINATION_PHRASES = [
    "Here are the extracted questions",
    "eftab720",
    "tightenfactor0",
    "Below is the JSON",
    "```json",
    "```",
]

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def _first_sentence(text):
    """Return the first sentence (up to ~200 chars) of a string."""
    text = text.strip()
    m = re.search(r'[.!?](?:\s|$)', text)
    if m:
        return text[:m.end()].strip()
    return text[:200].strip()


def _short_tag(text, max_len=70):
    """Extract a concise concept tag from a longer text string."""
    text = text.strip()
    # Strip leading "To diagnose", "Recognize", "Identify" lead-ins
    text = re.sub(
        r'^(?:to\s+)?(?:diagnose|recognize|identify|understand|distinguish|manage|'
        r'describe|explain|evaluate|treat|know)\s+',
        '', text, flags=re.IGNORECASE
    ).strip()
    # Capitalize first letter
    if text:
        text = text[0].upper() + text[1:]
    # Truncate at sentence end or max_len
    m = re.search(r'[.!?](?:\s|$)', text)
    if m and m.end() <= max_len:
        return text[:m.end()].rstrip('.!? ').strip()
    return text[:max_len].rstrip('.!? ').strip()


def _make_retrieval_tag(normalized_q):
    """Return retrievalTag: use source value or derive from educationalObjective / stem."""
    tag = (normalized_q.get("retrievalTag") or "").strip()
    if tag:
        return tag
    edu = (normalized_q.get("educationalObjective") or "").strip()
    if edu:
        return _short_tag(edu)
    correct_exp = (normalized_q.get("correctExplanation") or "").strip()
    if correct_exp:
        return _short_tag(_first_sentence(correct_exp))
    stem = (normalized_q.get("stem") or "").strip()
    # Very rough: last sentence of stem is usually the question prompt
    if stem:
        lines = [l.strip() for l in stem.splitlines() if l.strip()]
        return _short_tag(lines[-1] if lines else stem)
    return ""


def _make_review_pearl(normalized_q):
    """Return reviewPearl: use source value or derive from educationalObjective."""
    pearl = (normalized_q.get("reviewPearl") or "").strip()
    if pearl:
        return pearl
    edu = (normalized_q.get("educationalObjective") or "").strip()
    if edu:
        # educationalObjective is usually a pearl-worthy statement
        return _first_sentence(edu)[:200]
    correct_exp = (normalized_q.get("correctExplanation") or "").strip()
    if correct_exp:
        return _first_sentence(correct_exp)[:200]
    return ""


# ---------------------------------------------------------------------------
# explanationSections builder
# ---------------------------------------------------------------------------

def _build_explanation_sections(correct_explanation, incorrect_explanations, review_pearl):
    """
    Build explanationSections list for the NBME Gemini JSON importer.
    Format: [{heading: str, body: [str, ...]}]
    """
    sections = []

    if correct_explanation and correct_explanation.strip():
        sections.append({
            "heading": "Correct Answer Explanation",
            "body":    [correct_explanation.strip()],
        })

    if incorrect_explanations:
        ie_lines = [
            f"{entry['label']}. {entry.get('explanation', '').strip()}"
            for entry in incorrect_explanations
            if entry.get("label") and entry.get("explanation", "").strip()
        ]
        if ie_lines:
            sections.append({
                "heading": "Incorrect Answer Explanation",
                "body":    ie_lines,
            })

    if review_pearl and review_pearl.strip():
        sections.append({
            "heading": "Clinical Pearl",
            "body":    [review_pearl.strip()],
        })

    return sections


# ---------------------------------------------------------------------------
# Contamination check
# ---------------------------------------------------------------------------

def _contains_contamination(text):
    """Return first contamination phrase found, or None."""
    lower = str(text).lower()
    for phrase in CONTAMINATION_PHRASES:
        if phrase.lower() in lower:
            return phrase
    return None


def _scan_for_contamination(q_norm):
    """Check all text fields of a normalized question. Returns list of error strings."""
    fields = [
        ("stem",                 q_norm.get("stem", "")),
        ("correctExplanation",   q_norm.get("correctExplanation", "")),
        ("educationalObjective", q_norm.get("educationalObjective", "")),
        ("reviewPearl",          q_norm.get("reviewPearl", "")),
        ("retrievalTag",         q_norm.get("retrievalTag", "")),
    ]
    for ch in q_norm.get("choices", []):
        fields.append((f"choice_{ch.get('label','?')}", ch.get("text", "")))
    for ie in q_norm.get("incorrectExplanations", []):
        lbl = ie.get("label", "?")
        fields.append((f"ie_{lbl}", ie.get("explanation", "")))

    found = []
    for field_name, text in fields:
        hit = _contains_contamination(text)
        if hit:
            found.append(f"field '{field_name}' contains forbidden phrase: '{hit}'")
    return found


# ---------------------------------------------------------------------------
# Per-question conversion
# ---------------------------------------------------------------------------

def _convert_question(q_norm):
    """
    Convert one normalized question to NBME Gemini JSON v3 per-question format.
    Returns (question_dict, validation_errors).
    """
    errors = []

    stem         = (q_norm.get("stem") or "").strip()
    choices      = q_norm.get("choices") or []
    correct_ans  = (q_norm.get("correctAnswer") or "").strip()
    edu_obj      = (q_norm.get("educationalObjective") or "").strip()
    correct_exp  = (q_norm.get("correctExplanation") or "").strip()
    incorr_exps  = q_norm.get("incorrectExplanations") or []
    review_pearl = _make_review_pearl(q_norm)
    retrieval    = _make_retrieval_tag(q_norm)
    figures      = q_norm.get("figures") or []
    tables       = q_norm.get("tables") or []
    warnings     = q_norm.get("warnings") or []
    q_num        = q_norm.get("sourceQuestionNumber") or 0
    q_id         = q_norm.get("questionId") or f"q{q_num:03d}"

    # Validation
    if not stem:
        errors.append(f"q{q_num}: stem is empty")
    if len(choices) < 2:
        errors.append(f"q{q_num}: fewer than 2 answer choices ({len(choices)})")
    choice_labels = [c.get("label", "") for c in choices]
    if correct_ans and correct_ans not in choice_labels:
        errors.append(
            f"q{q_num}: correctAnswer '{correct_ans}' not in choices {choice_labels}"
        )
    for hit in _scan_for_contamination(q_norm):
        errors.append(f"q{q_num}: {hit}")

    # answerChoices: normalized uses {label, text}; importer expects same
    answer_choices = [
        {"label": c.get("label", ""), "text": c.get("text", "")}
        for c in choices
    ]

    # figureRefs: normalized uses {figureId, location, visibleText}
    # importer expects {id, placeholder, ...}
    figure_refs = [
        {
            "id":          fig.get("figureId", ""),
            "placeholder": f"[FIGURE: {fig.get('figureId', '')}]",
            "location":    fig.get("location", "stem"),
            "visibleText": fig.get("visibleText") or [],
        }
        for fig in figures
    ]
    has_figure = len(figure_refs) > 0

    explanation_sections = _build_explanation_sections(
        correct_exp, incorr_exps, review_pearl
    )

    question = {
        "id":                  q_id,
        "questionNumber":      q_num,
        "sourceQuestionNumber": q_num,
        "retrievalTag":        retrieval,
        "reviewPearl":         review_pearl,
        "clinicalPearl":       None,
        "stem":                stem,
        "hasEmbeddedFigure":   has_figure,
        "figureRefs":          figure_refs,
        "answerChoices":       answer_choices,
        "correctAnswer":       correct_ans or None,
        "educationalObjective": edu_obj or None,
        "explanationSections": explanation_sections,
        "tables":              tables,
        "sharedGroup":         None,
        "extractionWarnings":  warnings,
    }

    return question, errors


# ---------------------------------------------------------------------------
# File-level conversion
# ---------------------------------------------------------------------------

def convert_normalized_file(norm_path, dry_run=False):
    """
    Convert one _normalized.json → _app_ready.json.
    Returns a result summary dict.
    """
    stem = norm_path.stem
    if stem.endswith("_normalized"):
        stem = stem[: -len("_normalized")]

    result = {
        "filename":       norm_path.name,
        "status":         "ok",
        "warnings":       [],
        "question_count": 0,
        "skipped_count":  0,
        "output_path":    None,
    }

    try:
        payload = json.loads(norm_path.read_text(encoding="utf-8"))
    except Exception as e:
        result["status"] = "error"
        result["warnings"].append(f"Could not read file: {e}")
        return result

    items = payload.get("items") or []
    if not items:
        result["status"] = "warning"
        result["warnings"].append("No items in normalized file — nothing to convert")
        return result

    title       = stem.replace("_", " ").replace("-", " ")
    source_file = payload.get("sourceFile", norm_path.name)

    questions  = []
    all_errors = []

    for q_norm in items:
        question, errors = _convert_question(q_norm)
        if errors:
            all_errors.extend(errors)
            result["skipped_count"] += 1
            for e in errors:
                result["warnings"].append(f"SKIP: {e}")
        else:
            questions.append(question)

    result["question_count"] = len(questions)

    if not questions:
        result["status"] = "error"
        result["warnings"].append("No valid questions after conversion — output not written")
        return result

    out_payload = {
        "schemaVersion":              OUTPUT_SCHEMA_VERSION,
        "testTitle":                  title,
        "sourceFormat":               "mixed",
        "expectedQuestionCount":      len(items),
        "actualExtractedQuestionCount": len(questions),
        "extractionWarnings":         [],
        "questions":                  questions,
    }

    out_path = APP_READY_DIR / f"{stem}_app_ready.json"

    if not dry_run:
        try:
            out_path.write_text(
                json.dumps(out_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            result["output_path"] = str(out_path.relative_to(SCRIPT_DIR))
        except Exception as e:
            result["status"] = "error"
            result["warnings"].append(f"Could not write output: {e}")
            return result

    if result["status"] == "ok" and (result["warnings"] or result["skipped_count"]):
        result["status"] = "warning"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert NBME normalized JSON → app-ready JSON (Milestone 5)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and report without writing any output files",
    )
    args = parser.parse_args()

    APP_READY_DIR.mkdir(parents=True, exist_ok=True)

    norm_files = sorted(NORMALIZED_DIR.glob("*_normalized.json"))
    if not norm_files:
        print(f"\nNo *_normalized.json files in {NORMALIZED_DIR.relative_to(SCRIPT_DIR)}/")
        print("Run the extract pipeline first:\n  python3 extract_pdfs.py --normalize-gemini\n")
        sys.exit(0)

    mode_label = " [DRY RUN]" if args.dry_run else ""
    print(f"\nFound {len(norm_files)} normalized file(s) — converting to app-ready JSON{mode_label}...\n")

    icons   = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
    total_q = 0
    total_s = 0
    any_err = False

    for norm_path in norm_files:
        print(f"  {norm_path.name} ...", end=" ", flush=True)
        r = convert_normalized_file(norm_path, dry_run=args.dry_run)

        icon = icons.get(r["status"], "?")
        msg  = f"[{icon}]  {r['question_count']} questions"
        if r["skipped_count"]:
            msg += f", {r['skipped_count']} skipped"
        print(msg)

        for w in r["warnings"]:
            print(f"         ⚠  {w}")
        if r["output_path"] and not args.dry_run:
            print(f"         → {r['output_path']}")

        total_q += r["question_count"]
        total_s += r["skipped_count"]
        if r["status"] == "error":
            any_err = True

    print(f"\n{'='*60}")
    print(f"  Total questions written : {total_q}")
    if total_s:
        print(f"  Total skipped (errors)  : {total_s}")
    if args.dry_run:
        print(f"  Dry run — no files written")
    print(f"{'='*60}\n")

    sys.exit(1 if any_err else 0)


if __name__ == "__main__":
    main()
