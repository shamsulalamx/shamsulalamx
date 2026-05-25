#!/usr/bin/env python3
"""
Images/Tables screenshot -> NBME app-ready JSON generator.

Creates one Step 2-style question per screenshot and emits internal app-ready
questions that the app imports through q.images[] / q.explanationImages[] + FigureStore.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).parent.resolve()
INPUT_DIR = BASE_DIR / "input_images"
OUTPUT_DIR = BASE_DIR / "output_json"
APP_READY_DIR = OUTPUT_DIR / "app_ready"
ASSET_DIR = BASE_DIR / "output_assets"
LOG_DIR = BASE_DIR / "logs"
INTERMEDIATE_DIR = BASE_DIR / "intermediate"

# v4.79: Vertex migration — reuse _uw._gemini_client() factory.
_UW_DIR = BASE_DIR.parent / "uworld-notes-question-generator"
if str(_UW_DIR) not in sys.path:
    sys.path.insert(0, str(_UW_DIR))
import generate_uworld_questions as _uw  # noqa: E402
try:
    from google.genai import types as _genai_types  # noqa: E402
    _GENAI_SDK_AVAILABLE = True
except ImportError:
    _GENAI_SDK_AVAILABLE = False

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
SOURCE_FORMAT = "images-tables"
OUTPUT_SCHEMA_VERSION = "nbme-internal-app-ready-v2"
SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
IMAGE_RENDER_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
LABELS = ["A", "B", "C", "D"]


class GeneratorError(Exception):
    pass


def now_stamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dirs() -> None:
    for path in [INPUT_DIR, OUTPUT_DIR, APP_READY_DIR, ASSET_DIR, LOG_DIR, INTERMEDIATE_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def readme_text() -> str:
    return """# Images and Tables Question Generator

This tool creates one app-ready JSON file from screenshot images.

## First run

```bash
python3 generate_images_tables_questions.py --init
```

Then place screenshots in:

```text
tools/images-tables-question-generator/input_images/
```

Supported files: `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff`.

## Generate JSON

```bash
export GEMINI_API_KEY='your-key-here'
python3 generate_images_tables_questions.py --generate
```

Output is written to:

```text
output_json/app_ready/
```

The generated JSON uses `q.images[]` for stem images and `q.explanationImages[]`
for answer-explanation images. The app importer stores temporary image data in
`FigureStore` and removes inline data from the saved test.
"""


def command_text() -> str:
    return """#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo " Images/Tables -> App-Ready JSON"
echo "========================================"
echo ""
PYTHON=$(which python3 2>/dev/null)
if [ -z "$PYTHON" ]; then
  echo "ERROR: python3 not found on PATH."
  read -p "Press Enter to close..."
  exit 1
fi
"$PYTHON" generate_images_tables_questions.py --init
echo ""
"$PYTHON" generate_images_tables_questions.py --generate
STATUS=$?
echo ""
if [ $STATUS -ne 0 ]; then
  echo "Generation failed. See logs/ for details."
else
  echo "Generation complete. Import the JSON from output_json/app_ready/."
fi
read -p "Press Enter to close this window..."
exit $STATUS
"""


def init_tool() -> None:
    ensure_dirs()
    write_text(BASE_DIR / "README.md", readme_text())
    command_path = BASE_DIR / "Generate_Images_Tables_JSON.command"
    write_text(command_path, command_text())
    command_path.chmod(0o755)
    for folder in [INPUT_DIR, APP_READY_DIR, ASSET_DIR, LOG_DIR, INTERMEDIATE_DIR]:
        gitkeep = folder / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")
    print("Initialized images/tables generator folders.")
    print("Next: place screenshots in input_images/")
    print("Then run: python3 generate_images_tables_questions.py --generate")


def supported_images(input_dir: Path) -> list[Path]:
    if not input_dir.exists():
        return []
    files = []
    for path in sorted(input_dir.iterdir()):
        if path.name.startswith(".") or not path.is_file():
            continue
        if path.suffix.lower() in SUPPORTED_EXTS:
            files.append(path)
    return files


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("._")
    return value or "screenshot"


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".webp":
        return "image/webp"
    if ext == ".bmp":
        return "image/bmp"
    if ext in {".tif", ".tiff"}:
        return "image/tiff"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def copy_or_convert_asset(src: Path) -> tuple[Path, str, list[str]]:
    warnings: list[str] = []
    digest = file_sha(src)[:12]
    ext = src.suffix.lower()
    safe_stem = slugify(src.stem)
    if ext in IMAGE_RENDER_EXTS:
        dest = ASSET_DIR / f"{safe_stem}_{digest}{ext}"
        shutil.copy2(src, dest)
        return dest, mime_for(dest), warnings

    dest = ASSET_DIR / f"{safe_stem}_{digest}.png"
    sips = shutil.which("sips")
    if sips:
        result = subprocess.run(
            [sips, "-s", "format", "png", str(src), "--out", str(dest)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode == 0 and dest.exists():
            warnings.append(f"Converted {src.suffix} to PNG for browser rendering.")
            return dest, "image/png", warnings
    fallback = ASSET_DIR / f"{safe_stem}_{digest}{ext}"
    shutil.copy2(src, fallback)
    warnings.append(f"Could not convert {src.suffix}; copied original. Browser rendering may be unsupported.")
    return fallback, mime_for(fallback), warnings


def data_url(path: Path, mime: str) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def build_prompt(schema_text: str) -> str:
    return f"""
You are generating one Step 2-style medical question from one screenshot.
The screenshot may be a diagnostic image, table, tracing, ECG, radiology image, pathology image, dermatology image, clinical image, graph, process diagram, algorithm, pathway, concept map, mixed stimulus, or unclear.

Return valid JSON only. Do not include markdown fences. Do not include commentary outside JSON.
Do not hallucinate illegible table values. If the screenshot is too unclear to safely generate a question, return a failure object.

Use this normalized internal schema exactly:
{schema_text}

Rules:
- First decide whether showing the screenshot before answering would give away the answer.
- Classify the screenshot as exactly one of: diagnostic_stem_image, explanation_only_image, explanation_only_table, unclear_skip.
- Use diagnostic_stem_image only for diagnostic visual stimuli that must be interpreted before answering, such as CT, MRI, x-ray, ultrasound, ECG/EKG, tracing, pathology slide, histology, gross pathology, dermatology photo, clinical physical exam photo, fundoscopic image, or radiology image.
- Use explanation_only_image for process diagrams, mechanism diagrams, pathways, flowcharts, management algorithms, concept maps, labeled explanatory figures, or images that directly name the diagnosis/pathway/process.
- Use explanation_only_table for ALL tables, charts, and graphs without exception. Tables and charts must NEVER appear in the question stem; analyze the table yourself, generate a clinical question about the underlying concept (diagnosis, next best step, mechanism, complication, deficiency, management), and let the table support the answer explanation only. Do not classify a table as diagnostic_stem_image under any circumstance, even if it looks like a diagnostic data display.
- Use unclear_skip when the screenshot is too unreadable or unsafe to use without hallucinating.
- Generate exactly one question object unless returning unclear_skip.
- Use exactly 4 answer choices labeled A, B, C, D.
- For diagnostic_stem_image, the screenshot must be necessary to answer and the stem must naturally refer to the image, tracing, or stimulus. Tables and charts are NEVER eligible for this classification.
- For explanation_only_image and explanation_only_table, generate a Step 2-style question from the concept shown, but do not reveal the screenshot in the stem before answering.
- For tables specifically, analyze the table and generate a clinical question based on the information in it. Do not ask "what does the table show?" The table itself must appear only in the answer explanation.
- Ask about diagnosis, next best step, mechanism, complication, risk factor, management, interpretation, or prevention.
- Do not merely describe the screenshot.
- Do not include unsupported schema fields.
- For unreadable screenshots, return {{"status":"failure","classification":"unclear_skip","reason":"specific reason"}}.
""".strip()


def normalized_schema_text() -> str:
    return json.dumps(
        {
            "status": "ok | failure",
            "classification": "diagnostic_stem_image | explanation_only_image | explanation_only_table | unclear_skip",
            "stimulusType": "ct | mri | xray | ultrasound | ecg | tracing | radiology | pathology | histology | dermatology | clinical_photo | fundoscopic | table | flowchart | algorithm | pathway | concept_map | diagram | graph | mixed | unclear",
            "placementRationale": "brief reason for showing before answer or only after answer",
            "stem": "4-5 sentence clinical vignette ending in one question",
            "choices": [{"label": "A", "text": "choice text"}],
            "correctAnswer": "A",
            "correctExplanation": "why the correct answer is correct",
            "incorrectExplanations": [{"label": "B", "explanation": "why this distractor is wrong"}],
            "educationalObjective": "one focused teaching point",
            "retrievalTag": "specific short tag",
            "reviewPearl": "one-line review pearl",
            "reason": "only for failure",
        },
        indent=2,
    )


def call_gemini(api_key: str, image_path: Path, mime: str, prompt: str) -> str:
    """Multimodal Gemini call — one image + one prompt.

    v4.79: rewritten to use google-genai SDK via _uw._gemini_client(). SDK
    handles base64 encoding internally. Preserves the temperature=0.15 +
    max_tokens=4096 used by this generator. Error wrapping (GeneratorError)
    preserved so the calling retry/skip logic still recognizes failures.
    """
    if not _GENAI_SDK_AVAILABLE:
        raise GeneratorError(
            "google-genai SDK not installed. Install with: pip install google-genai"
        )
    try:
        client = _uw._gemini_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                prompt,
                _genai_types.Part.from_bytes(
                    data=image_path.read_bytes(),
                    mime_type=mime,
                ),
            ],
            config=_genai_types.GenerateContentConfig(
                temperature=0.15,
                max_output_tokens=4096,
                # v4.79: disable Gemini 2.5 thinking (see _uw for rationale).
                thinking_config=_genai_types.ThinkingConfig(thinking_budget=0),
            ),
        )
    except EnvironmentError:
        raise
    except Exception as err:
        raise GeneratorError(f"Gemini call failed: {err}") from err
    text = getattr(response, "text", None)
    if not text:
        candidates = getattr(response, "candidates", None) or []
        raise GeneratorError(f"Gemini candidate had no text part. candidates={candidates!r}"[:400])
    return str(text)


def clean_json_text(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_gemini_json(raw: str) -> dict[str, Any]:
    text = clean_json_text(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as err:
        raise GeneratorError(f"Gemini returned invalid JSON: {err}") from err
    if isinstance(parsed, list):
        if len(parsed) != 1:
            raise GeneratorError("Gemini returned multiple questions for one screenshot.")
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        raise GeneratorError("Gemini JSON root is not an object.")
    return parsed


def normalize_choices(raw_choices: Any) -> list[dict[str, str]]:
    if not isinstance(raw_choices, list):
        raise GeneratorError("Gemini omitted choices.")
    choices = []
    for idx, item in enumerate(raw_choices[:4]):
        if not isinstance(item, dict):
            raise GeneratorError(f"choices[{idx}] is not an object.")
        label = str(item.get("label") or item.get("letter") or LABELS[idx]).strip().upper()
        text = str(item.get("text") or item.get("value") or "").strip()
        if label not in LABELS:
            label = LABELS[idx]
        if not text:
            raise GeneratorError(f"choices[{idx}] is missing text.")
        choices.append({"l": label, "t": text})
    if len(choices) != 4:
        raise GeneratorError(f"Gemini returned {len(choices)} choices; expected 4.")
    if [c["l"] for c in choices] != LABELS:
        choices = [{"l": LABELS[idx], "t": c["t"]} for idx, c in enumerate(choices)]
    return choices


def build_explanation(parsed: dict[str, Any]) -> str:
    correct = str(parsed.get("correctExplanation") or "").strip()
    incorrect = parsed.get("incorrectExplanations") or []
    lines = []
    if correct:
        lines.append(f"Correct answer: {correct}")
    if isinstance(incorrect, list):
        for entry in incorrect:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "").strip().upper()
            exp = str(entry.get("explanation") or "").strip()
            if label and exp:
                lines.append(f"Choice {label}: {exp}")
    objective = str(parsed.get("educationalObjective") or "").strip()
    if objective:
        lines.append(f"Educational objective: {objective}")
    explanation = "\n\n".join(lines).strip()
    if not explanation:
        raise GeneratorError("Gemini omitted explanation.")
    return explanation


def normalize_classification(parsed: dict[str, Any]) -> str:
    raw = str(parsed.get("classification") or "").strip().lower()
    aliases = {
        "image": "diagnostic_stem_image",
        "radiology": "diagnostic_stem_image",
        "pathology": "diagnostic_stem_image",
        "histology": "diagnostic_stem_image",
        "dermatology": "diagnostic_stem_image",
        "clinical_photo": "diagnostic_stem_image",
        "ecg_tracing": "diagnostic_stem_image",
        "graph": "explanation_only_image",
        "mixed": "explanation_only_image",
        "table": "explanation_only_table",
        "unclear": "unclear_skip",
        "failure": "unclear_skip",
    }
    placement = aliases.get(raw, raw)
    allowed = {"diagnostic_stem_image", "explanation_only_image", "explanation_only_table", "unclear_skip"}
    if placement not in allowed:
        raise GeneratorError(f"Unsupported classification: {raw or '(missing)'}")
    stimulus = str(parsed.get("stimulusType") or "").strip().lower()
    if stimulus in {"table", "graph", "chart"} and placement == "diagnostic_stem_image":
        placement = "explanation_only_table" if stimulus == "table" else "explanation_only_image"
    return placement


def asset_path_for_metadata(asset: Path) -> str:
    try:
        return str(asset.relative_to(BASE_DIR))
    except ValueError:
        return str(asset.resolve())


def image_entry(src: Path, asset: Path, mime: str, parsed: dict[str, Any], placement: str) -> dict[str, Any]:
    stimulus_type = str(parsed.get("stimulusType") or "").strip().lower() or placement
    return {
        "figureKey": None,
        "dataUrl": data_url(asset, mime),
        "isLabTable": placement == "explanation_only_table" or stimulus_type in {"table", "graph"},
        "kind": "figure",
        "source": "images-tables-generator",
        "originalFileName": src.name,
        "assetPath": asset_path_for_metadata(asset),
        "classification": placement,
        "stimulusType": stimulus_type,
        "placement": "stem" if placement == "diagnostic_stem_image" else "explanation",
    }


def adapt_question(parsed: dict[str, Any], src: Path, asset: Path, mime: str, q_num: int, warnings: list[str]) -> dict[str, Any] | None:
    status = str(parsed.get("status") or "ok").lower()
    classification = normalize_classification(parsed)
    if status == "failure" or classification == "unclear_skip":
        reason = str(parsed.get("reason") or "Gemini returned failure without reason.").strip()
        raise GeneratorError(f"Gemini skipped screenshot: {reason}")

    stem = str(parsed.get("stem") or "").strip()
    if not stem:
        raise GeneratorError("Gemini omitted stem.")
    choices = normalize_choices(parsed.get("choices"))
    correct = str(parsed.get("correctAnswer") or "").strip().upper()
    if correct not in LABELS:
        raise GeneratorError("Gemini omitted correct answer or used unsupported label.")
    if correct not in [c["l"] for c in choices]:
        raise GeneratorError("Correct answer does not match one of the choices.")

    explanation = build_explanation(parsed)
    question_id = f"images_tables_{q_num:03d}_{file_sha(src)[:8]}"
    image = image_entry(src, asset, mime, parsed, classification)
    stem_images = [image] if classification == "diagnostic_stem_image" else []
    explanation_images = [image] if classification in {"explanation_only_image", "explanation_only_table"} else []
    answer_choices = [{"label": c["l"], "text": c["t"]} for c in choices]
    explanation_sections = [
        {
            "heading": "Answer Explanation",
            "body": [part for part in explanation.split("\n\n") if part.strip()],
        }
    ]
    return {
        "id": question_id,
        "questionNumber": q_num,
        "sourceQuestionNumber": q_num,
        "stem": stem,
        "answerChoices": answer_choices,
        "correctAnswer": correct,
        "explanationSections": explanation_sections,
        "hasEmbeddedFigure": False,
        "figureRefs": [],
        "tables": [],
        "extractionWarnings": warnings,
        "n": q_num,
        "t": stem,
        "o": choices,
        "c": correct,
        "correctBlurb": explanation.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n\n", "<br><br>"),
        "e": {},
        "tags": [str(parsed.get("retrievalTag") or classification).strip()[:80]],
        "retrievalTag": str(parsed.get("retrievalTag") or classification).strip(),
        "reviewPearl": str(parsed.get("reviewPearl") or parsed.get("educationalObjective") or "").strip(),
        "educationalObjective": str(parsed.get("educationalObjective") or "").strip(),
        "images": stem_images,
        "explanationImages": explanation_images,
        "metadata": {
            "sourceType": "images-tables-generator",
            "sourceFormat": SOURCE_FORMAT,
            "originalFileName": src.name,
            "assetPath": asset_path_for_metadata(asset),
            "classification": classification,
            "stimulusType": image.get("stimulusType") or "",
            "stimulusPlacement": classification,
            "placementRationale": str(parsed.get("placementRationale") or "").strip(),
            "stemImageAttachments": len(stem_images),
            "explanationImageAttachments": len(explanation_images),
            "figureAttachments": {},
            "extractionWarnings": warnings,
        },
    }


def validate_payload(payload: dict[str, Any], base_dir: Path = BASE_DIR) -> list[str]:
    errors: list[str] = []
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return ["Final app-ready JSON has no questions."]
    seen_question_numbers: set[int] = set()
    for idx, q in enumerate(questions, start=1):
        prefix = f"Q{idx}"
        if not isinstance(q, dict):
            errors.append(f"{prefix}: question is not an object.")
            continue
        question_number = q.get("questionNumber")
        if not isinstance(question_number, int):
            errors.append(f"{prefix}: missing required field questionNumber.")
        elif question_number != idx:
            errors.append(f"{prefix}: questionNumber must be {idx}; found {question_number}.")
        elif question_number in seen_question_numbers:
            errors.append(f"{prefix}: duplicate questionNumber {question_number}.")
        else:
            seen_question_numbers.add(question_number)
        stem = q.get("stem")
        if not isinstance(stem, str) or not stem.strip():
            errors.append(f"{prefix}: missing required field stem.")
        answer_choices = q.get("answerChoices")
        if not isinstance(answer_choices, list):
            errors.append(f"{prefix}: missing required field answerChoices.")
        elif len(answer_choices) != 4:
            errors.append(f"{prefix}: answerChoices must contain exactly four choices.")
        else:
            canonical_labels = []
            for choice_idx, choice in enumerate(answer_choices):
                if not isinstance(choice, dict):
                    errors.append(f"{prefix}: answerChoices[{choice_idx}] is not an object.")
                    continue
                label = choice.get("label")
                text = choice.get("text")
                canonical_labels.append(label)
                if not isinstance(label, str) or not label.strip():
                    errors.append(f"{prefix}: answerChoices[{choice_idx}].label is missing.")
                if not isinstance(text, str) or not text.strip():
                    errors.append(f"{prefix}: answerChoices[{choice_idx}].text is missing.")
            if canonical_labels == LABELS and q.get("correctAnswer") not in canonical_labels:
                errors.append(f"{prefix}: correctAnswer does not match answerChoices.")
        correct_answer = q.get("correctAnswer")
        if not isinstance(correct_answer, str) or not correct_answer.strip():
            errors.append(f"{prefix}: missing required field correctAnswer.")
        if q.get("hasEmbeddedFigure") is not False:
            errors.append(f"{prefix}: hasEmbeddedFigure must be false for direct q.images[]/q.explanationImages[] attachments.")
        if not isinstance(q.get("figureRefs"), list):
            errors.append(f"{prefix}: figureRefs must be an array.")
        if not isinstance(q.get("tables"), list):
            errors.append(f"{prefix}: tables must be an array.")
        if "explanationSections" not in q:
            errors.append(f"{prefix}: missing required field explanationSections.")
        elif not isinstance(q.get("explanationSections"), list):
            errors.append(f"{prefix}: explanationSections must be an array.")
        if not q.get("t"):
            errors.append(f"{prefix}: missing stem t.")
        choices = q.get("o")
        if not isinstance(choices, list) or len(choices) != 4:
            errors.append(f"{prefix}: must have exactly four choices.")
        else:
            labels = [str(c.get("l") or "") for c in choices if isinstance(c, dict)]
            if labels != LABELS:
                errors.append(f"{prefix}: choices must be labeled A-D.")
            if q.get("c") not in labels:
                errors.append(f"{prefix}: correct answer does not match choices.")
        if not (q.get("explanation") or q.get("correctBlurb")):
            errors.append(f"{prefix}: missing explanation.")
        images = q.get("images")
        explanation_images = q.get("explanationImages", [])
        if not isinstance(images, list):
            errors.append(f"{prefix}: images must be an array.")
            images = []
        if not isinstance(explanation_images, list):
            errors.append(f"{prefix}: explanationImages must be an array.")
            explanation_images = []

        placement = str(q.get("metadata", {}).get("stimulusPlacement") or "").strip()
        if not placement:
            placement = "diagnostic_stem_image" if len(images) == 1 and not explanation_images else ""
        if placement == "diagnostic_stem_image":
            if len(images) != 1 or len(explanation_images) != 0:
                errors.append(f"{prefix}: diagnostic_stem_image requires exactly one stem image and zero explanation images.")
        elif placement == "explanation_only_image":
            if len(images) != 0 or len(explanation_images) != 1:
                errors.append(f"{prefix}: explanation_only_image requires zero stem images and exactly one explanation image.")
        elif placement == "explanation_only_table":
            if len(images) != 0 or len(explanation_images) != 1:
                errors.append(f"{prefix}: explanation_only_table requires zero stem images and exactly one explanation image.")
        else:
            errors.append(f"{prefix}: unsupported or missing stimulusPlacement.")

        seen_refs = set()
        for field, image_list in [("images", images), ("explanationImages", explanation_images)]:
            for img_idx, img in enumerate(image_list):
                if not isinstance(img, dict):
                    errors.append(f"{prefix}: {field}[{img_idx}] is not an object.")
                    continue
                asset_path = img.get("assetPath")
                if asset_path:
                    asset_candidate = Path(str(asset_path))
                    if not asset_candidate.is_absolute():
                        asset_candidate = base_dir / asset_candidate
                    if not asset_candidate.exists():
                        errors.append(f"{prefix}: referenced asset file missing: {asset_path}")
                if not img.get("dataUrl") and not img.get("figureKey"):
                    errors.append(f"{prefix}: {field}[{img_idx}] lacks dataUrl or figureKey.")
                ref_sig = img.get("assetPath") or img.get("figureKey") or img.get("dataUrl")
                if ref_sig in seen_refs:
                    errors.append(f"{prefix}: same image is stored in more than one placement.")
                if ref_sig:
                    seen_refs.add(ref_sig)
        figure_attachments = q.get("metadata", {}).get("figureAttachments") if isinstance(q.get("metadata"), dict) else None
        if figure_attachments:
            errors.append(f"{prefix}: uses metadata.figureAttachments; it must not be a competing image route.")
    return errors


def validate_only(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as err:
        raise GeneratorError(f"JSON is not parseable: {err}") from err
    errors = validate_payload(payload)
    if errors:
        raise GeneratorError("Validation failed:\n" + "\n".join(f"- {e}" for e in errors))
    print(f"Validation OK: {path}")


def write_log(path: Path, message: str) -> None:
    path.write_text(message, encoding="utf-8")


def generate(args: argparse.Namespace) -> Path | None:
    global ASSET_DIR, LOG_DIR, INTERMEDIATE_DIR
    ensure_dirs()
    output_dir = Path(args.output_dir).resolve() if args.output_dir else APP_READY_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.output_dir:
        durable_root = output_dir.parent if output_dir.name == "app_ready" else output_dir
        ASSET_DIR = durable_root / "output_assets"
        LOG_DIR = durable_root / "logs"
        INTERMEDIATE_DIR = durable_root / "intermediate"
        for d in (ASSET_DIR, LOG_DIR, INTERMEDIATE_DIR):
            d.mkdir(parents=True, exist_ok=True)
    if args.input_file:
        selected = Path(args.input_file).expanduser().resolve()
        if not selected.exists() or not selected.is_file():
            raise GeneratorError(f"--input-file does not exist or is not a file: {selected}")
        if selected.suffix.lower() not in SUPPORTED_EXTS:
            raise GeneratorError(f"--input-file has unsupported extension '{selected.suffix}'. Supported: {sorted(SUPPORTED_EXTS)}")
        files = [selected]
    else:
        input_dir = Path(args.input_dir).resolve() if args.input_dir else INPUT_DIR
        files = supported_images(input_dir)
        if args.limit:
            files = files[: args.limit]
        if not files:
            raise GeneratorError(f"No supported input images found in {input_dir}")
    print(f"Found {len(files)} supported image(s).")
    if args.dry_run:
        for path in files:
            print(f"DRY RUN: would process {path.name}")
        return None
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeneratorError("GEMINI_API_KEY is missing. Set it in the environment before --generate.")

    prompt = build_prompt(normalized_schema_text())
    questions: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    run_stamp = now_stamp()

    for src in files:
        log_lines = [f"file: {src}", f"started: {dt.datetime.now().isoformat()}"]
        try:
            asset, mime, asset_warnings = copy_or_convert_asset(src)
            raw = call_gemini(api_key, asset, mime, prompt)
            raw_path = INTERMEDIATE_DIR / f"{src.stem}_{run_stamp}_gemini_raw.txt"
            write_log(raw_path, raw)
            parsed = parse_gemini_json(raw)
            json_path = INTERMEDIATE_DIR / f"{src.stem}_{run_stamp}_gemini_parsed.json"
            write_text(json_path, json.dumps(parsed, indent=2, ensure_ascii=False))
            question = adapt_question(parsed, src, asset, mime, len(questions) + 1, asset_warnings)
            if question:
                questions.append(question)
                log_lines.append("status: ok")
        except Exception as err:
            reason = str(err)
            failures.append({"file": src.name, "reason": reason})
            log_lines.append(f"status: failed")
            log_lines.append(f"reason: {reason}")
        finally:
            write_log(LOG_DIR / f"{src.stem}_{run_stamp}.log", "\n".join(log_lines) + "\n")

    if not questions:
        raise GeneratorError("No valid questions generated. See logs/ for per-file failures.")

    payload = {
        "schemaVersion": OUTPUT_SCHEMA_VERSION,
        "name": f"Images Tables Generated {run_stamp}",
        "sourceFormat": SOURCE_FORMAT,
        "expectedQuestionCount": len(files),
        "actualExtractedQuestionCount": len(questions),
        "imageAttachmentStrategy": "q.images[] for stem images; q.explanationImages[] for explanation images; both persisted through FigureStore",
        "generationWarnings": failures,
        "questions": questions,
    }
    errors = validate_payload(payload)
    if errors:
        raise GeneratorError("Final validation failed:\n" + "\n".join(f"- {e}" for e in errors))
    out_path = output_dir / f"images_tables_{run_stamp}_app_ready.json"
    write_text(out_path, json.dumps(payload, indent=2, ensure_ascii=False))
    json.loads(out_path.read_text(encoding="utf-8"))
    if not out_path.exists():
        raise GeneratorError("Output file not written.")
    print(f"Final JSON path: {out_path}")
    if failures:
        print(f"Skipped {len(failures)} file(s). See logs/.")
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate app-ready JSON from screenshots.")
    parser.add_argument("--init", action="store_true", help="Create folders, README, and command launcher.")
    parser.add_argument("--generate", action="store_true", help="Process input screenshots with Gemini.")
    parser.add_argument("--dry-run", action="store_true", help="Scan files without calling Gemini.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of images processed.")
    parser.add_argument("--input-dir", default="", help="Input image folder.")
    parser.add_argument("--input-file", default="", help="Process a single image file (used by Batch Import Center). Overrides --input-dir when set.")
    parser.add_argument("--output-dir", default="", help="Output app-ready JSON folder.")
    parser.add_argument("--validate-only", default="", help="Validate one generated JSON file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.init:
            init_tool()
            return 0
        if args.validate_only:
            validate_only(Path(args.validate_only).resolve())
            return 0
        if args.generate or args.dry_run:
            generate(args)
            return 0
        print("No action specified. Use --init, --generate, --dry-run, or --validate-only.")
        return 2
    except GeneratorError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
