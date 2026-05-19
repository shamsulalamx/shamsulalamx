# NBME PDF → JSON Generator

**Milestone 1 — Deterministic Extraction Skeleton**

Converts NBME-style PDF answer files into raw extracted text, ready for
the next milestone (Gemini-based JSON generation).

---

## Directory layout

```
tools/nbme-pdf-json-generator/
├── Generate_NBME_JSONs.command   ← double-click this on macOS
├── extract_pdfs.py               ← core extraction script
├── README.md                     ← this file
├── input_pdfs/                   ← DROP YOUR PDFs HERE
├── output_json/
│   └── raw_text/                 ← one .txt file per PDF (auto-created)
└── reports/                      ← JSON extraction reports (auto-created)
```

---

## How to use

### Step 1 — Place your PDFs

Copy your NBME answer PDF files into:

```
tools/nbme-pdf-json-generator/input_pdfs/
```

Any `.pdf` file in that folder will be processed. Subfolders are not scanned.

### Step 2 — Run the extractor

**Option A — Double-click (macOS Finder)**

Double-click `Generate_NBME_JSONs.command`.

If macOS blocks it the first time:
- Right-click → Open → click "Open" in the security dialog.

A Terminal window opens, runs the extractor, and prints a summary.
Press Enter when done to close.

**Option B — Terminal**

```bash
cd tools/nbme-pdf-json-generator
python3 extract_pdfs.py
```

---

## Where outputs appear

| Output | Location |
|---|---|
| Raw extracted text (one per PDF) | `output_json/raw_text/<stem>_raw.txt` |
| Extraction report (JSON) | `reports/extraction_report_<timestamp>.json` |

### Raw text format

Each `_raw.txt` file is a markdown-style document with one section per page:

```
## Page 1

<extracted text from page 1>

---

## Page 2

<extracted text from page 2>
```

### Extraction report format

Each run writes one timestamped JSON report:

```json
{
  "schemaVersion": "nbme-pdf-extractor-report-v1",
  "generatedAt": "2026-05-19T...",
  "elapsedSeconds": 1.23,
  "summary": {
    "total": 3,
    "ok": 2,
    "warning": 1,
    "error": 0
  },
  "files": [
    {
      "filename": "NBME_Psych_9.pdf",
      "pageCount": 62,
      "status": "ok",
      "charCount": 84210,
      "warnings": [],
      "outputPath": "output_json/raw_text/NBME_Psych_9_raw.txt"
    }
  ]
}
```

**Status values:**
- `ok` — text extracted cleanly
- `warning` — extraction succeeded but some pages had no text (image-only pages), or minor issues
- `error` — PDF could not be opened or processed

---

## Requirements

- macOS (Apple Silicon or Intel)
- Python 3.9+  (`python3 --version`)
- `pdfplumber` library — installed automatically by `Generate_NBME_JSONs.command`

To install manually:
```bash
pip3 install pdfplumber
```

---

## Notes

- This is **Milestone 1 only**. It does not call Gemini and does not produce
  app-ready JSON yet.
- Image-only PDFs (scanned without OCR) will extract empty text. The status
  will be `warning` with a message per page. A future milestone adds OCR support.
- This tool does not touch or modify any app files (`index.html`, `js/`, etc.).
- All outputs are gitignored by default. Add your PDFs to `.gitignore` if needed.
