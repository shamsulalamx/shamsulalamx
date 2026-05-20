#!/usr/bin/env python3
"""
Images/Tables screenshot -> NBME app-ready JSON generator.

Creates one Step 2-style question per screenshot and emits internal app-ready
questions that the app imports through q.images[] + FigureStore.
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

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
SOURCE_FORMAT = "images-tables"
OUTPUT_SCHEMA_VERSION = "nbme-internal-app-ready-v1"
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

The generated JSON uses `q.images[]` as the only image attachment route. The
app importer stores temporary image data in `FigureStore` and removes inline
data from the saved test.
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
The screenshot may be an image, table, tracing, ECG, radiology image, pathology image, dermatology image, clinical image, graph, mixed stimulus, or unclear.

Return valid JSON only. Do not include markdown fences. Do not include commentary outside JSON.
Do not hallucinate illegible table values. If the screenshot is too unclear to safely generate a question, return a failure object.

Use this normalized internal schema exactly:
{schema_text}

Rules:
- Generate exactly one question object unless returning failure.
- Use exactly 4 answer choices labeled A, B, C, D.
- The screenshot must be central to the question.
- The stem must naturally refer to the image, table, tracing, or stimulus.
- Ask about diagnosis, next best step, mechanism, complication, risk factor, management, interpretation, or prevention.
- Do not merely describe the screenshot.
- Do not include unsupported schema fields.
- For unclear screenshots, return {{"status":"failure","reason":"specific reason","classification":"unclear"}}.
""".strip()


def normalized_schema_text() -> str:
    return json.dumps(
        {
            "status": "ok | failure",
            "classification": "image | table | mixed | ecg_tracing | radiology | pathology | dermatology | clinical_photo | graph | unclear",
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
    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={api_key}"
    body = json.dumps(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.15, "maxOutputTokens": 4096},
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")[:500]
        raise GeneratorError(f"Gemini HTTP {err.code}: {detail}") from err
    candidates = payload.get("candidates") or []
    if not candidates:
        raise GeneratorError(f"Gemini returned no candidates: {str(payload)[:300]}")
    parts = candidates[0].get("content", {}).get("parts") or []
    if not parts or "text" not in parts[0]:
        raise GeneratorError("Gemini candidate had no text part.")
    return str(parts[0]["text"])


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


def adapt_question(parsed: dict[str, Any], src: Path, asset: Path, mime: str, q_num: int, warnings: list[str]) -> dict[str, Any] | None:
    status = str(parsed.get("status") or "ok").lower()
    if status == "failure":
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
    classification = str(parsed.get("classification") or "unclear").strip().lower() or "unclear"
    question_id = f"images_tables_{q_num:03d}_{file_sha(src)[:8]}"
    image = {
        "figureKey": None,
        "dataUrl": data_url(asset, mime),
        "isLabTable": classification in {"table", "mixed", "graph"},
        "kind": "figure",
        "source": "images-tables-generator",
        "originalFileName": src.name,
        "assetPath": str(asset.relative_to(BASE_DIR)),
        "classification": classification,
    }
    return {
        "id": question_id,
        "n": q_num,
        "t": stem,
        "o": choices,
        "c": correct,
        "explanation": explanation,
        "correctBlurb": explanation.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n\n", "<br><br>"),
        "e": {},
        "tags": [str(parsed.get("retrievalTag") or classification).strip()[:80]],
        "retrievalTag": str(parsed.get("retrievalTag") or classification).strip(),
        "reviewPearl": str(parsed.get("reviewPearl") or parsed.get("educationalObjective") or "").strip(),
        "educationalObjective": str(parsed.get("educationalObjective") or "").strip(),
        "images": [image],
        "metadata": {
            "sourceType": "images-tables-generator",
            "sourceFormat": SOURCE_FORMAT,
            "originalFileName": src.name,
            "assetPath": str(asset.relative_to(BASE_DIR)),
            "classification": classification,
            "imageAttachments": 1,
            "figureAttachments": {},
            "extractionWarnings": warnings,
        },
    }


def validate_payload(payload: dict[str, Any], base_dir: Path = BASE_DIR) -> list[str]:
    errors: list[str] = []
    questions = payload.get("questions")
    if not isinstance(questions, list) or not questions:
        return ["Final app-ready JSON has no questions."]
    for idx, q in enumerate(questions, start=1):
        prefix = f"Q{idx}"
        if not isinstance(q, dict):
            errors.append(f"{prefix}: question is not an object.")
            continue
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
        if not isinstance(images, list) or len(images) != 1:
            errors.append(f"{prefix}: must have exactly one screenshot attachment in q.images[].")
        else:
            img = images[0]
            if not isinstance(img, dict):
                errors.append(f"{prefix}: image attachment is not an object.")
            else:
                asset_path = img.get("assetPath")
                if asset_path and not (base_dir / str(asset_path)).exists():
                    errors.append(f"{prefix}: referenced asset file missing: {asset_path}")
                if not img.get("dataUrl") and not img.get("figureKey"):
                    errors.append(f"{prefix}: image lacks dataUrl or figureKey.")
        figure_attachments = q.get("metadata", {}).get("figureAttachments") if isinstance(q.get("metadata"), dict) else None
        if figure_attachments:
            errors.append(f"{prefix}: uses metadata.figureAttachments; q.images[] must be the only attachment route.")
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
    ensure_dirs()
    input_dir = Path(args.input_dir).resolve() if args.input_dir else INPUT_DIR
    output_dir = Path(args.output_dir).resolve() if args.output_dir else APP_READY_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
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
        "imageAttachmentStrategy": "q.images[] + FigureStore",
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
