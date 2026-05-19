# Anki Question Generator

Converts Anki study notes into NBME-style Step 2 CK multiple-choice questions (app-ready JSON).

**This is a thin wrapper** around the stable UWorld notes pipeline at
`tools/uworld-notes-question-generator/`. It reuses the Gemini client, JSON
cleaning, retry/repair flow, validation, duplicate detection, and report
generation unchanged — only paths and the prompt are overridden.

---

## Workflow

```
Anki notes
  → export as .txt
  → drop into input_notes/
  → python3 generate_anki_questions.py --dry-run   (verify structure)
  → python3 generate_anki_questions.py --generate  (call Gemini)
  → output_json/app_ready/<stem>_app_ready.json    (import this)
  → localhost import → Generate Test
```

---

## Exact Commands

### 1. Dry-run (no API key needed — verify pipeline end-to-end)
```bash
cd tools/anki-question-generator
python3 generate_anki_questions.py --dry-run
```

### 2. Live generation (requires GEMINI_API_KEY)
```bash
export GEMINI_API_KEY=your_key_here
python3 generate_anki_questions.py --generate
```

### 3. Control question count per file
```bash
python3 generate_anki_questions.py --generate --questions-per-file 10
python3 generate_anki_questions.py --generate --questions-per-file 20
```

### 4. Flags
| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | off | Placeholder JSON, no Gemini calls |
| `--generate` | off | Hard-fail if GEMINI_API_KEY missing |
| `--questions-per-file N` | 15 | Target questions per input file |

`--dry-run` and `--generate` are mutually exclusive.

---

## Supported Input Formats

Place files in `input_notes/`. Supported extensions:

| Format | Extension |
|--------|-----------|
| Plain text | `.txt` |
| Markdown | `.md` |
| Rich Text | `.rtf` (requires `pip install striprtf`) |
| Word | `.docx` (requires `pip install python-docx`) |

**Recommended:** Export Anki notes as `.txt` — no extra dependencies.

---

## Known-Good Output Paths

After a successful run:

```
output_json/
  raw_text/       <stem>_raw.txt           — extracted plain text
  chunks/         <stem>_chunks.json       — topic chunks fed to Gemini
  generated/      <stem>_generated.json    — raw Gemini output (live runs only)
  app_ready/      <stem>_app_ready.json    — ← IMPORT THIS FILE
reports/          anki_generation_report_<timestamp>.json
```

The `app_ready/` JSON matches the canonical `nbme-gemini-json-v3` schema.

---

## Localhost Import Instructions

1. Start the local app: `npm start` or open `index.html` in your browser.
2. Click **Import JSON** (or use the app's import flow).
3. Select `output_json/app_ready/<stem>_app_ready.json`.
4. Click **Generate Test** to start a session.

---

## Troubleshooting

**No files found**
- Confirm files are in `input_notes/` with a supported extension.
- Run `ls input_notes/` to verify.

**`GEMINI_API_KEY` not set**
- Without `--generate`, the script falls back to dry-run automatically.
- With `--generate`, it hard-fails with a clear error message.
- Fix: `export GEMINI_API_KEY=your_key_here`

**JSON parse failure**
- The raw Gemini response is saved to `output_json/generated/debug/chunk<N>_raw_response.txt`.
- The pipeline automatically retries with a repair prompt before failing.

**UWorld generator not found**
- The script expects `tools/uworld-notes-question-generator/` to exist as a sibling directory.
- Do not move `generate_anki_questions.py` out of `tools/anki-question-generator/`.

**Import fails in app**
- Verify `schemaVersion` is `nbme-gemini-json-v3` in the app-ready JSON.
- Dry-run output is valid but contains placeholder stems — import works, questions are stubs.

**`striprtf` or `python-docx` not installed**
- The script skips `.rtf`/`.docx` files and prints a warning with the install command.
- Use `.txt` to avoid optional dependencies.

---

## Pipeline Internals (for reference)

All generation logic lives in:
```
tools/uworld-notes-question-generator/generate_uworld_questions.py
```

`generate_anki_questions.py` imports that module and patches these module-level
globals before any pipeline function runs:

| Variable | Anki override |
|----------|--------------|
| `INPUT_DIR` | `input_notes/` |
| `RAW_DIR` | `output_json/raw_text/` |
| `CHUNK_DIR` | `output_json/chunks/` |
| `GEN_DIR` | `output_json/generated/` |
| `DEBUG_DIR` | `output_json/generated/debug/` |
| `APP_DIR` | `output_json/app_ready/` |
| `REPORT_DIR` | `reports/` |
| `PROMPT_FILE` | `prompts/anki_notes_to_questions_prompt.txt` |

No pipeline code is duplicated.
