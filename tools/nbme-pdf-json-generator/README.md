# NBME PDF → JSON Generator

**Current: Milestone 3 — Normalized Scaffold (schema + prompt + dry-run)**

Staged pipeline for converting NBME-style PDF answer files into app-ready JSON.

```
PDF → raw text → chunks → normalized scaffold → (Milestone 4: app-ready JSON)
```

---

## Directory layout

```
tools/nbme-pdf-json-generator/
├── Generate_NBME_JSONs.command        ← double-click launcher (macOS)
├── extract_pdfs.py                    ← core pipeline script
├── README.md                          ← this file
│
├── schema/
│   ├── normalized_question_schema.json  ← JSON Schema for one normalized question
│   └── app_ready_schema_notes.md        ← mapping: normalized → app storage fields
│
├── prompts/
│   └── chunk_to_normalized_question_prompt.txt  ← LLM prompt (Milestone 4)
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

## How to use

### Step 1 — Place your PDFs

```
tools/nbme-pdf-json-generator/input_pdfs/
```

### Step 2 — Run

**Full pipeline (PDF → raw text → chunks):**

```bash
cd tools/nbme-pdf-json-generator
python3 extract_pdfs.py
```

**Re-chunk only (skip PDF re-extraction):**

```bash
python3 extract_pdfs.py --chunk-only
```

**Normalize dry run (create placeholder normalized JSON, no LLM):**

```bash
python3 extract_pdfs.py --normalize-dry-run
```

Reads all `output_json/chunks/*_chunks.json` files and writes one
`output_json/normalized/*_normalized.json` per chunk file.
Every question becomes a placeholder with all fields empty and
`"warnings": ["normalize dry run only; LLM not called"]`.
Gemini is **not** called.

**Double-click launcher (macOS Finder):**

Double-click `Generate_NBME_JSONs.command`.
Right-click → Open if macOS blocks it the first time.

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

### Normalized JSON (`output_json/normalized/<stem>_normalized.json`)

One file per source PDF, containing one normalized question object per chunk.
In dry-run mode all question fields are empty placeholders.
In Milestone 4 (LLM mode) each question will be fully populated.

```json
{
  "schemaVersion": "nbme-normalized-file-v1",
  "sourceChunkFile": "NBME_Psych_9_chunks.json",
  "createdAt": "2026-05-19T...",
  "isDryRun": true,
  "questionCount": 50,
  "fileWarnings": [],
  "questions": [
    {
      "schemaVersion": "nbme-normalized-question-v1",
      "sourceFile": "NBME_Psych_9_chunks.json",
      "sourceQuestionNumber": 1,
      "questionId": "q001",
      "stem": "",
      "choices": [],
      "correctAnswer": "",
      "educationalObjective": "",
      "correctExplanation": "",
      "incorrectExplanations": [],
      "reviewPearl": "",
      "retrievalTag": "",
      "tags": [],
      "figures": [],
      "tables": [],
      "warnings": ["normalize dry run only; LLM not called"],
      "confidence": "low"
    }
  ]
}
```

### Pipeline report (`reports/extraction_report_<timestamp>.json`)

Report schema v3 — includes extraction, chunking, and normalization status per file:

```json
{
  "schemaVersion": "nbme-pdf-extractor-report-v3",
  "mode": "normalize-dry-run",
  "summary": {
    "total": 2,
    "totalChunks": 53,
    "normalizationOk": 1,
    "normalizationWarning": 1,
    "normalizationError": 0,
    "normalizationSkipped": 0,
    "totalNormalized": 53
  },
  "files": [
    {
      "filename": "NBME_Psych_9.pdf",
      "chunkingStatus": "skipped",
      "chunkPath": "output_json/chunks/NBME_Psych_9_chunks.json",
      "normalizationStatus": "ok",
      "normalizedCount": 50,
      "normalizedOutputPath": "output_json/normalized/NBME_Psych_9_normalized.json"
    }
  ]
}
```

---

## Schema reference

### `schema/normalized_question_schema.json`

JSON Schema (draft-07) describing one normalized question object.
See the file for full field definitions including validation rules and descriptions.

### `schema/app_ready_schema_notes.md`

Documents how normalized fields map into the app's internal quiz schema:
- `stem` → `q.t`
- `choices` → `q.o` (rename `label`→`l`, `text`→`t`)
- `correctAnswer` → `q.c`
- `educationalObjective` → `q.educationalObjective`
- `correctExplanation` + `incorrectExplanations` + `reviewPearl` → `q.correctBlurb`
- `retrievalTag` → `q.retrievalTag` + `q.metadata.retrievalTag` + `q.tags[0]`
- `figures` → `q.metadata.figureRefs`
- `tables` → `q.metadata.tables`
- `warnings` → `q.metadata.extractionWarnings`

---

## LLM prompt

`prompts/chunk_to_normalized_question_prompt.txt` contains the prompt for
Milestone 4 (Gemini call). It instructs the LLM to:

- Convert exactly one raw chunk → exactly one normalized JSON object
- Preserve all wording verbatim from source
- Never invent answer choices or correct answers
- Never add content not supported by source text
- Detect and flag contamination phrases (`eftab720`, `tightenfactor0`, etc.)
- Output JSON only — no markdown, no commentary

---

## Question boundary detection (M2)

| Pattern | Example |
|---|---|
| `N. ` | `1. A 32-year-old man…` |
| `N) ` | `1) A 32-year-old man…` |
| `Question N` | `Question 1 A 32-year-old man…` |
| `Item N` | `Item 1 A 32-year-old man…` |

---

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.9+
- `pdfplumber` — auto-installed by `Generate_NBME_JSONs.command`

```bash
pip3 install pdfplumber
```

---

## Notes

- **Milestone 3** adds schema, prompt scaffolding, and dry-run normalization only.
  No LLM is called at any point in the current pipeline.
- Image-only PDFs produce empty raw text → no chunk boundaries found → 0 normalized placeholders.
- This tool does not modify any app files (`index.html`, `js/`, etc.).
- Each run appends a new timestamped report to `reports/`.
