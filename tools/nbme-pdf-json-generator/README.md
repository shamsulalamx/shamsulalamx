# NBME PDF → JSON Generator

**Current: Milestone 4 — Gemini-powered normalization with schema validation**

Staged pipeline for converting NBME-style PDF answer files into app-ready JSON.

```
PDF → raw text → chunks → Gemini → normalized JSON → (Milestone 5: app-ready JSON)
```

---

## Directory layout

```
tools/nbme-pdf-json-generator/
├── Generate_NBME_JSONs.command        ← double-click launcher (macOS)
├── extract_pdfs.py                    ← core pipeline script (M1–M4)
├── README.md                          ← this file
│
├── schema/
│   ├── normalized_question_schema.json  ← JSON Schema for one normalized question
│   └── app_ready_schema_notes.md        ← mapping: normalized → app storage fields
│
├── prompts/
│   └── chunk_to_normalized_question_prompt.txt  ← Gemini prompt
│
├── input_pdfs/                        ← DROP YOUR PDFs HERE
│
├── output_json/
│   ├── raw_text/                      ← one _raw.txt per PDF          (M1)
│   ├── chunks/                        ← one _chunks.json per PDF      (M2)
│   └── normalized/                    ← one _normalized.json per PDF  (M3/M4)
│
└── reports/                           ← timestamped pipeline reports
```

---

## API key setup

The Gemini normalization step requires a Google Gemini API key.
**The key is never stored in files or printed to the terminal.**

Set it in your shell before running:

```bash
export GEMINI_API_KEY='your-api-key-here'
```

Or prefix it inline:

```bash
GEMINI_API_KEY='your-api-key-here' python3 extract_pdfs.py --normalize-gemini
```

If the key is missing, the script exits immediately with a clear error message.

---

## How to use

### Full staged workflow

```bash
cd tools/nbme-pdf-json-generator

# Step 1: extract PDFs → raw text + chunks
python3 extract_pdfs.py

# Step 2: normalize chunks via Gemini (requires GEMINI_API_KEY)
python3 extract_pdfs.py --normalize-gemini
```

### Individual commands

| Command | What it does |
|---|---|
| `python3 extract_pdfs.py` | Extract PDFs → raw text → question chunks |
| `python3 extract_pdfs.py --chunk-only` | Re-chunk existing raw_text files (skip PDF re-extraction) |
| `python3 extract_pdfs.py --normalize-dry-run` | Create empty placeholder normalized JSON (no LLM, no key needed) |
| `python3 extract_pdfs.py --normalize-gemini` | Call Gemini to normalize chunks (requires `GEMINI_API_KEY`) |

### Double-click launcher

Double-click `Generate_NBME_JSONs.command` in Finder. Right-click → Open if macOS blocks it.

---

## Output formats

### Raw text (`output_json/raw_text/<stem>_raw.txt`)

Markdown-style, one `## Page N` section per PDF page.

### Chunks JSON (`output_json/chunks/<stem>_chunks.json`)

```json
{
  "schemaVersion": "nbme-chunk-v1",
  "sourceFile": "NBME_Psych_9_raw.txt",
  "createdAt": "2026-05-19T...",
  "chunkCount": 50,
  "fileWarnings": [],
  "chunks": [
    {
      "chunkId": "q001",
      "questionNumber": 1,
      "rawText": "1. A 28-year-old woman...",
      "startMarker": "1.",
      "endMarker": "2.",
      "confidence": "high",
      "warnings": []
    }
  ]
}
```

### Normalized JSON — Gemini mode (`output_json/normalized/<stem>_normalized.json`)

```json
{
  "schemaVersion": "normalized-question-batch-v1",
  "sourceFile": "NBME_Psych_9_raw.txt",
  "sourceChunkFile": "NBME_Psych_9_chunks.json",
  "createdAt": "2026-05-19T...",
  "normalizationMode": "gemini",
  "normalizedCount": 49,
  "failedCount": 1,
  "items": [
    {
      "schemaVersion": "nbme-normalized-question-v1",
      "sourceFile": "NBME_Psych_9_raw.txt",
      "sourceQuestionNumber": 1,
      "questionId": "q001",
      "stem": "A 28-year-old woman presents with...",
      "choices": [
        { "label": "A", "text": "Adjustment disorder" },
        { "label": "B", "text": "Major depressive disorder" }
      ],
      "correctAnswer": "B",
      "educationalObjective": "Diagnose major depressive disorder...",
      "correctExplanation": "The patient meets criteria because...",
      "incorrectExplanations": [
        { "label": "A", "explanation": "Adjustment disorder requires..." }
      ],
      "reviewPearl": "MDD requires 5 of 9 SIGECAPS symptoms for 2 weeks.",
      "retrievalTag": "MDD diagnostic criteria",
      "tags": ["MDD diagnostic criteria"],
      "figures": [],
      "tables": [],
      "warnings": [],
      "confidence": "high"
    }
  ],
  "failures": [
    {
      "chunkId": "q012",
      "questionNumber": 12,
      "error": "correctAnswer not found in choices",
      "rawResponsePreview": "...",
      "attempts": 2
    }
  ]
}
```

### Pipeline report (`reports/extraction_report_<timestamp>.json`)

Report schema v4 — includes per-file `failedCount` and `validationErrorCount`:

```json
{
  "schemaVersion": "nbme-pdf-extractor-report-v4",
  "mode": "normalize-gemini",
  "summary": {
    "totalNormalized": 49,
    "totalFailed": 1,
    "totalValidationErrors": 3
  }
}
```

---

## Gemini model

Uses `gemini-2.5-flash` — the same model used throughout the app.

---

## Validation (M4)

Each Gemini response is validated before being written. Checks:

- All 17 required fields present
- `choices` is an array; each entry has `label` (A–F) and `text`
- `correctAnswer` is a single letter A–F or empty string
- `confidence` is `high`, `medium`, or `low`
- `warnings`, `tags`, `figures`, `tables`, `incorrectExplanations` are arrays
- No forbidden phrases in text fields:
  `Here are the extracted questions`, `eftab720`, `tightenfactor0`,
  `Below is the JSON`, ```` ```json ````, ```` ``` ````

On validation failure: one automatic retry with a repair prompt.
After 2 failed attempts: chunk recorded in `failures[]`, pipeline continues.

---

## Security note

- `GEMINI_API_KEY` is read from the environment only.
- It is **never** printed, logged, or written to any file.
- Never commit your key to git.

---

## Schema reference

### `schema/normalized_question_schema.json`

JSON Schema (draft-07) for one normalized question.

### `schema/app_ready_schema_notes.md`

Field mapping from normalized → app quiz schema (`q.t`, `q.o`, `q.c`, etc.).

---

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.9+ (standard library only for M4 HTTP calls — `urllib.request`)
- `pdfplumber` — for PDF extraction only

```bash
pip3 install pdfplumber
```

No additional packages are needed for the Gemini API calls.

---

## Notes

- Chunks are processed **sequentially** with a 0.5s delay between Gemini calls.
- Image-only PDFs produce empty raw text → no chunks → 0 normalized questions.
- This tool does not touch any app files (`index.html`, `js/`, etc.).
- Each run appends a new timestamped report to `reports/`.
