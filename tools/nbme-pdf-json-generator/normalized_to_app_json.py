#!/usr/bin/env python3
"""
NBME Normalized JSON → App-Ready JSON converter (Milestone 5)

Reads every *_normalized.json from output_json/normalized/ and writes a
corresponding *_app_ready.json to output_json/app_ready/.

Output schema: nbme-gemini-json-v1
Compatible with the shamsulalamx quiz app (internal question format).

Usage:
  python3 normalized_to_app_json.py
  python3 normalized_to_app_json.py --dry-run   # validate only, no writes
"""

import argparse
import html
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

OUTPUT_SCHEMA_VERSION = "nbme-gemini-json-v1"
SOURCE_LABEL          = "nbme-pdf-json-generator"

CONTAMINATION_PHRASES = [
    "Here are the extracted questions",
    "eftab720",
    "tightenfactor0",
    "Below is the JSON",
    "```json",
    "```",
]


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """HTML-escape a plain-text string for safe inline embedding."""
    return html.escape(str(text), quote=False)


def _build_correct_blurb(
    correct_explanation: str,
    incorrect_explanations: list,
    review_pearl: str,
) -> str:
    """
    Build the correctBlurb pre-escaped HTML string.

    Sections produced (only when non-empty):
      <div class="ngj-exp-section">
        <strong>Correct Answer Explanation</strong>
        <p>...</p>
      </div>
      <div class="ngj-exp-section">
        <strong>Incorrect Answer Explanations</strong>
        <p><strong>A.</strong> ...</p>
        ...
      </div>
      <div class="ngj-exp-section">
        <strong>Clinical Pearl</strong>
        <p>...</p>
      </div>
    """
    parts = []

    if correct_explanation and correct_explanation.strip():
        parts.append(
            '<div class="ngj-exp-section">'
            "<strong>Correct Answer Explanation</strong>"
            f"<p>{_esc(correct_explanation.strip())}</p>"
            "</div>"
        )

    if incorrect_explanations:
        ie_paras = "".join(
            f"<p><strong>{_esc(entry['label'])}.</strong> "
            f"{_esc(entry.get('explanation', '').strip())}</p>"
            for entry in incorrect_explanations
            if entry.get("explanation", "").strip()
        )
        if ie_paras:
            parts.append(
                '<div class="ngj-exp-section">'
                "<strong>Incorrect Answer Explanations</strong>"
                + ie_paras
                + "</div>"
            )

    if review_pearl and review_pearl.strip():
        parts.append(
            '<div class="ngj-exp-section">'
            "<strong>Clinical Pearl</strong>"
            f"<p>{_esc(review_pearl.strip())}</p>"
            "</div>"
        )

    return "".join(parts)


def _build_explanation_sections(
    correct_explanation: str,
    incorrect_explanations: list,
    review_pearl: str,
) -> list:
    """
    Build explanationSections list for metadata (mirrors correctBlurb structure).
    Format: [{heading: str, body: [str, ...]}]
    """
    sections = []

    if correct_explanation and correct_explanation.strip():
        sections.append({
            "heading": "Correct Answer Explanation",
            "body": [correct_explanation.strip()],
        })

    if incorrect_explanations:
        ie_lines = [
            f"{entry['label']}. {entry.get('explanation', '').strip()}"
            for entry in incorrect_explanations
            if entry.get("explanation", "").strip()
        ]
        if ie_lines:
            sections.append({
                "heading": "Incorrect Answer Explanations",
                "body": ie_lines,
            })

    if review_pearl and review_pearl.strip():
        sections.append({
            "heading": "Clinical Pearl",
            "body": [review_pearl.strip()],
        })

    return sections


def _build_per_choice_e(incorrect_explanations: list) -> dict:
    """Build e dict: {label: explanation_text} for per-choice lookup."""
    return {
        entry["label"]: entry.get("explanation", "").strip()
        for entry in incorrect_explanations
        if entry.get("label") and entry.get("explanation", "").strip()
    }


# ---------------------------------------------------------------------------
# Contamination check
# ---------------------------------------------------------------------------

def _contains_contamination(text: str):
    """Return the first contamination phrase found, or None."""
    lower = text.lower()
    for phrase in CONTAMINATION_PHRASES:
        if phrase.lower() in lower:
            return phrase
    return None


def _scan_for_contamination(q_norm: dict):
    """Check all text fields of a normalized question for contamination phrases."""
    fields_to_check = [
        ("stem",                 q_norm.get("stem", "")),
        ("correctExplanation",   q_norm.get("correctExplanation", "")),
        ("educationalObjective", q_norm.get("educationalObjective", "")),
        ("reviewPearl",          q_norm.get("reviewPearl", "")),
        ("retrievalTag",         q_norm.get("retrievalTag", "")),
    ]
    for ch in q_norm.get("choices", []):
        fields_to_check.append((f"choice_{ch.get('label','?')}", ch.get("text", "")))
    for ie in q_norm.get("incorrectExplanations", []):
        lbl = ie.get("label", "?")
        fields_to_check.append((f"ie_{lbl}", ie.get("explanation", "")))

    found = []
    for field_name, text in fields_to_check:
        hit = _contains_contamination(str(text))
        if hit:
            found.append(f"field '{field_name}' contains forbidden phrase: '{hit}'")
    return found


# ---------------------------------------------------------------------------
# Per-question conversion
# ---------------------------------------------------------------------------

def _convert_question(q_norm: dict, imported_at: str):
    """
    Convert one normalized question object to app-ready format.
    Returns (question_dict, validation_errors).
    """
    errors = []

    stem         = q_norm.get("stem", "").strip()
    choices      = q_norm.get("choices", [])
    correct_ans  = q_norm.get("correctAnswer", "").strip()
    edu_obj      = q_norm.get("educationalObjective", "").strip()
    correct_exp  = q_norm.get("correctExplanation", "").strip()
    incorr_exps  = q_norm.get("incorrectExplanations", [])
    review_pearl = q_norm.get("reviewPearl", "").strip()
    retrieval    = q_norm.get("retrievalTag", "").strip()
    tags_raw     = q_norm.get("tags", [])
    figures      = q_norm.get("figures", [])
    tables       = q_norm.get("tables", [])
    warnings     = q_norm.get("warnings", [])
    q_num        = q_norm.get("sourceQuestionNumber", 0)
    q_id         = q_norm.get("questionId", f"q{q_num:03d}")

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
    contamination = _scan_for_contamination(q_norm)
    for hit in contamination:
        errors.append(f"q{q_num}: {hit}")

    # Build output fields
    o_choices = [{"l": c.get("label", ""), "t": c.get("text", "")} for c in choices]
    e_map     = _build_per_choice_e(incorr_exps)

    # tags: retrievalTag always first if non-empty
    tags = [retrieval] if retrieval else []
    for t in tags_raw:
        if t and t != retrieval:
            tags.append(t)

    correct_blurb       = _build_correct_blurb(correct_exp, incorr_exps, review_pearl)
    explanation_sections = _build_explanation_sections(correct_exp, incorr_exps, review_pearl)

    has_figure = len(figures) > 0

    question = {
        "n":                    q_num,
        "t":                    stem,
        "o":                    o_choices,
        "c":                    correct_ans or None,
        "e":                    e_map,
        "tags":                 tags,
        "retrievalTag":         retrieval,
        "reviewPearl":          review_pearl,
        "educationalObjective": edu_obj,
        "correctBlurb":         correct_blurb,
        "metadata": {
            "sourceType":          SOURCE_LABEL,
            "sourceQuestionNumber": q_num,
            "sourceId":            q_id,
            "retrievalTag":        retrieval,
            "reviewPearl":         review_pearl,
            "hasEmbeddedFigure":   has_figure,
            "figureRefs":          figures,
            "tables":              tables,
            "sharedGroup":         None,
            "extractionWarnings":  warnings,
            "explanationSections": explanation_sections,
            "schemaVersion":       OUTPUT_SCHEMA_VERSION,
            "figureAttachments":   {},
            "sourceFormat":        "normalized-json",
            "importedAt":          imported_at,
        },
    }

    return question, errors


# ---------------------------------------------------------------------------
# File-level conversion
# ---------------------------------------------------------------------------

def convert_normalized_file(norm_path: Path, dry_run: bool = False) -> dict:
    """
    Convert one _normalized.json → _app_ready.json.
    Returns a result summary dict.
    """
    stem = norm_path.stem
    if stem.endswith("_normalized"):
        stem = stem[: -len("_normalized")]

    result = {
        "filename":        norm_path.name,
        "status":          "ok",
        "warnings":        [],
        "question_count":  0,
        "skipped_count":   0,
        "error_count":     0,
        "output_path":     None,
    }

    try:
        payload = json.loads(norm_path.read_text(encoding="utf-8"))
    except Exception as e:
        result["status"] = "error"
        result["warnings"].append(f"Could not read file: {e}")
        return result

    items = payload.get("items", [])
    if not items:
        result["status"] = "warning"
        result["warnings"].append("No items in normalized file — nothing to convert")
        return result

    imported_at = datetime.now(timezone.utc).isoformat()
    title       = stem.replace("_", " ").replace("-", " ")
    source_file = payload.get("sourceFile", norm_path.name)

    questions  = []
    all_errors = []

    for q_norm in items:
        question, errors = _convert_question(q_norm, imported_at)
        if errors:
            all_errors.extend(errors)
            result["skipped_count"] += 1
            for e in errors:
                result["warnings"].append(f"SKIP: {e}")
        else:
            questions.append(question)

    result["question_count"] = len(questions)
    result["error_count"]    = len(all_errors)

    if not questions:
        result["status"] = "error"
        result["warnings"].append("No valid questions after conversion — output not written")
        return result

    out_payload = {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "title":         title,
        "source":        SOURCE_LABEL,
        "sourceFile":    source_file,
        "createdAt":     imported_at,
        "questionCount": len(questions),
        "questions":     questions,
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

    icons = {"ok": "OK", "warning": "WARN", "error": "ERROR"}
    total_q = 0
    total_skip = 0
    any_error = False

    for norm_path in norm_files:
        print(f"  {norm_path.name} ...", end=" ", flush=True)
        r = convert_normalized_file(norm_path, dry_run=args.dry_run)

        icon = icons.get(r["status"], "?")
        print(f"[{icon}]  {r['question_count']} questions", end="")
        if r["skipped_count"]:
            print(f", {r['skipped_count']} skipped", end="")
        print()

        for w in r["warnings"]:
            print(f"         ⚠  {w}")
        if r["output_path"] and not args.dry_run:
            print(f"         → {r['output_path']}")

        total_q    += r["question_count"]
        total_skip += r["skipped_count"]
        if r["status"] == "error":
            any_error = True

    print(f"\n{'='*60}")
    print(f"  Total questions written : {total_q}")
    if total_skip:
        print(f"  Total skipped (errors)  : {total_skip}")
    if args.dry_run:
        print(f"  Dry run — no files written")
    print(f"{'='*60}\n")

    sys.exit(1 if any_error else 0)


if __name__ == "__main__":
    main()
