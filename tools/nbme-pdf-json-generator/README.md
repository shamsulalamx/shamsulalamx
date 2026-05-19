# NBME PDF → JSON Generator

**Current: Milestone 2 — Deterministic Question Chunking**

Converts NBME-style PDF answer files into raw extracted text, then splits that
text into per-question chunks ready for the next milestone (Gemini-based JSON generation).

---

## Directory layout

```
tools/nbme-pdf-json-generator/
├── Generate_NBME_JSONs.command   ← double-click this on macOS
├── extract_pdfs.py               ← core script (M1 + M2)
├── README.md                     ← this file
├── input_pdfs/                   ← DROP YOUR PDFs HERE
├── output_json/
│   ├── raw_text/                 ← one _raw.txt per PDF  (M1 output)
│   └── chunks/                   ← one _chunks.json per PDF  (M2 output)
└── reports/                      ← timestamped JSON reports (auto-created)
```

---

## How to use

### Step 1 — Place your PDFs

Copy your NBME answer PDF files into:

```
tools/nbme-pdf-json-generator/input_pdfs/
```

Any `.pdf` file in that folder will be processed. Subfolders are not scanned.

### Step 2 — Run

**Option A — Double-click (macOS Finder)**

Double-click `Generate_NBME_JSONs.command`.

If macOS blocks it the first time: right-click → Open → click "Open" in the dialog.
A Terminal window opens, runs the full pipeline, and prints a summary. Press Enter to close.

**Option B — Terminal (full pipeline)**

```bash
cd tools/nbme-pdf-json-generator
python3 extract_pdfs.py
```

Extracts every PDF in `input_pdfs/` → raw text → question chunks.

**Option C — Terminal (re-chunk only)**

```bash
python3 extract_pdfs.py --chunk-only
```

Skips PDF extraction entirely. Re-reads existing `output_json/raw_text/*_raw.txt` files
and re-runs chunking. Useful when you've already extracted PDFs and want to iterate on
chunking logic without re-running pdfplumber.

---

## Where outputs appear

| Output | Location |
|---|---|
| Raw extracted text (M1) | `output_json/raw_text/<stem>_raw.txt` |
| Question chunks (M2) | `output_json/chunks/<stem>_chunks.json` |
| Pipeline report | `reports/extraction_report_<timestamp>.json` |

---

## Output formats

### Raw text (`_raw.txt`)

Markdown-style document, one section per PDF page:

```
## Page 1

<page text>

---

## Page 2

<page text>
```

### Chunks JSON (`_chunks.json`)

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
      "rawText": "1. A 28-year-old woman presents...",
      "startMarker": "1.",
      "endMarker": "2.",
      "confidence": "high",
      "warnings": []
    }
  ]
}
```

**Chunk confidence levels:**
- `high` — answer choices detected AND text length ≥ 80 chars
- `medium` — answer choices OR long enough text, but not both
- `low` — no answer choices and very short

**Per-chunk warnings (in `chunk.warnings`):**
- Duplicate question number
- Unusually short chunk (< 80 chars)
- No answer choices detected
- No explanation-like content detected
- Contamination phrase found inside chunk

**File-level warnings (in `fileWarnings`):**
- Text skipped before first question (preamble)
- Missing question numbers in sequence
- Contamination phrases found in full text:
  `"Here are the extracted questions"`, `"eftab720"`, `"tightenfactor0"`

### Pipeline report (`extraction_report_<timestamp>.json`)

```json
{
  "schemaVersion": "nbme-pdf-extractor-report-v2",
  "generatedAt": "2026-05-19T...",
  "elapsedSeconds": 1.23,
  "mode": "full",
  "summary": {
    "total": 2,
    "extractionOk": 2,
    "extractionWarning": 0,
    "extractionError": 0,
    "extractionSkipped": 0,
    "chunkingOk": 1,
    "chunkingWarning": 1,
    "chunkingError": 0,
    "chunkingSkipped": 0,
    "totalChunks": 53,
    "totalChunkWarnings": 2
  },
  "files": [
    {
      "filename": "NBME_Psych_9.pdf",
      "pageCount": 62,
      "extractionStatus": "ok",
      "extractionWarnings": [],
      "charCount": 84210,
      "rawTextPath": "output_json/raw_text/NBME_Psych_9_raw.txt",
      "chunkingStatus": "ok",
      "chunkCount": 50,
      "chunkWarningCount": 0,
      "chunkPath": "output_json/chunks/NBME_Psych_9_chunks.json"
    }
  ]
}
```

**Status values (extraction and chunking):**
- `ok` — processed cleanly
- `warning` — processed but issues found (see warnings fields)
- `error` — could not process
- `skipped` — step was not run (e.g. extraction skipped in `--chunk-only` mode)

---

## Question boundary detection

The chunker recognises these patterns at the start of a line:

| Pattern | Example |
|---|---|
| `N. ` | `1. A 32-year-old man…` |
| `N) ` | `1) A 32-year-old man…` |
| `Question N` | `Question 1 A 32-year-old man…` |
| `Item N` | `Item 1 A 32-year-old man…` |

Text before the first detected question is skipped and logged as a file-level warning.

---

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.9+  (`python3 --version`)
- `pdfplumber` — installed automatically by `Generate_NBME_JSONs.command`

To install manually:
```bash
pip3 install pdfplumber
```

---

## Notes

- **Milestone 2** produces raw question chunks only. No Gemini call, no app-ready JSON yet.
- Image-only PDFs (scanned without embedded text) will produce `_raw.txt` files with
  empty pages. The chunker will warn `No question boundaries found`. A future milestone
  adds OCR support.
- This tool does not touch or modify any app files (`index.html`, `js/`, etc.).
- Each run appends a new timestamped report to `reports/` — previous reports are not deleted.
