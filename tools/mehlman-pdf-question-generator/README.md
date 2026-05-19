# Mehlman Medical Mastery PDF → Step 2 Question Generator

External tool pipeline that converts Mehlman Medical Mastery PDFs into
`nbme-gemini-json-v3` app-ready JSON, ready for import into the NBME Self-Assessment app.

**Milestone 1**: Deterministic extraction + chunking + dry-run output.  
**Milestone 2** (deferred): Live Gemini question generation from chunk manifests.

---

## Pipeline

```
PDF file (input_pdfs/)
  │
  ▼ Stage 1: pdfplumber per-page text extraction (body-crop strips headers/footers)
  │   extracted_text/<stem>_text.json        ← per-page text + asset metadata
  │   Optional: extracted_figures/<stem>_p<N>_<hash>.png  (PyMuPDF)
  │   Optional: extracted_tables/<stem>_p<N>_t<M>.json    (pdfplumber lattice)
  │
  ▼ Stage 2: Long-PDF chunking (8,000–12,000 chars/chunk with page metadata)
  │   output_json/chunks/<stem>_chunks.json  ← chunk manifest (chunkId, pageStart, pageEnd, …)
  │
  ▼ Stage 3: Question generation (placeholder or Gemini)
  │   Prompt: prompts/mehlman_pdf_to_questions_prompt.txt
  │   Schema: nbme-gemini-json-v3, sourceFormat: mehlman-pdf
  │   Validation + retry: reused from UWorld generator
  │
  ▼ output_json/app_ready/<stem>_app_ready.json
  │
  ▼ Import via: App → NBME Gemini JSON importer
```

---

## Usage

### Dry-run (no API key required)

```bash
cd tools/mehlman-pdf-question-generator

# Basic dry-run (placeholder questions)
python3 generate_mehlman_questions.py --dry-run

# With figure and table extraction
python3 generate_mehlman_questions.py --dry-run --extract-assets

# Limit to first 2 chunks (fast test)
python3 generate_mehlman_questions.py --dry-run --max-chunks 2

# Custom questions per chunk
python3 generate_mehlman_questions.py --dry-run --questions-per-chunk 3
```

### Stage-by-stage (incremental, recommended for large PDFs)

```bash
# Stage 1: Extract text per page
python3 generate_mehlman_questions.py --extract-only

# Stage 1 + assets: also extract figures and tables
python3 generate_mehlman_questions.py --extract-only --extract-assets

# Stage 2: Build chunk manifests from existing extracted text
python3 generate_mehlman_questions.py --chunk-only

# Stage 3 (dry-run): Placeholder questions from existing chunks
python3 generate_mehlman_questions.py --dry-run --resume
```

### Incremental run behavior

`--resume` reuses existing extracted text and chunk files when present.  
`--force` ignores existing files and reprocesses from scratch.

- If `extracted_text/<stem>_text.json` exists and `--resume` is set, Stage 1 is skipped.
- If `output_json/chunks/<stem>_chunks.json` exists and `--resume` is set, Stage 2 is skipped.
- `--resume` and `--force` are mutually exclusive.

### Live generation (Milestone 2)

```bash
export GEMINI_API_KEY='your-api-key-here'
python3 generate_mehlman_questions.py --generate
python3 generate_mehlman_questions.py --generate --questions-per-chunk 5
python3 generate_mehlman_questions.py --generate --max-chunks 2  # test first 2 chunks
python3 generate_mehlman_questions.py --generate --resume        # skip already-extracted
```

---

## Input

Drop Mehlman Medical Mastery PDFs into `input_pdfs/`. Only `.pdf` files are processed.

**PDF requirements for best extraction:**
- Native text (not scanned/image-only)
- Bordered tables detected via pdfplumber lattice strategy
- Figures extracted via PyMuPDF (min 80×80 px, max aspect ratio 8:1)

---

## Output

`output_json/app_ready/<stem>_app_ready.json`

Import via: **App → Import → NBME Gemini JSON → select file → validate → preview → save**

---

## Dependencies

| Package | Required | Notes |
|---|---|---|
| Python ≥ 3.9 | Required | `str.removesuffix()` used |
| pdfplumber | Required | Text extraction + lattice table detection |
| PyMuPDF (fitz) | Required for `--extract-assets` | Figure extraction |
| Gemini API key | Required for `--generate` | `export GEMINI_API_KEY=...` |

```bash
pip install pdfplumber pymupdf
```

No additional pip packages required for `--dry-run` or `--extract-only`.

---

## Stage Details

### Stage 1: Per-page extraction

- Crops each page to body zone (strips top 8% and bottom 8% — removes headers/footers)
- Extracts text with pdfplumber (`x_tolerance=2, y_tolerance=2`)
- Saves per-page JSON: `{pageNum, text, figures, tables, warnings}`
- `--extract-assets`:
  - Tables: pdfplumber lattice strategy (lines only — avoids false positives on body text)
  - Figures: PyMuPDF `get_images(full=True)`, min 80×80 px, max aspect ratio 8:1
  - High confidence: ≥200×200 px; MD5 hash deduplication prevents duplicate extraction

### Stage 2: Long-PDF chunking

- Merges per-page text into chunks of **8,000–12,000 characters**
- Splits at page boundaries when possible (preserves clinical topic cohesion)
- Falls back to paragraph splits for pages exceeding 12,000 chars
- Each chunk includes `pageStart` and `pageEnd` for traceability
- Chunk manifest saved to `output_json/chunks/<stem>_chunks.json`

### Stage 3: Question generation

- `--dry-run`: placeholder questions only, no Gemini API calls
- `--generate`: calls `call_gemini_with_retry()` (reused from UWorld), injects asset markers
- Asset markers (`[DETECTED FIGURE: ...]`, `[DETECTED TABLE: ...]`) prepended to chunk text
- Validation + 1 automatic repair retry per chunk
- `sourceFormat: "mehlman-pdf"` in output

---

## Chunk Manifest Fields

Each `chunks` array entry in `output_json/chunks/<stem>_chunks.json`:

| Field | Description |
|---|---|
| `chunkId` | Sequential integer (1-based) |
| `sourceFile` | Source PDF filename |
| `pageStart` | First page number included in this chunk |
| `pageEnd` | Last page number included in this chunk |
| `charCount` | Character count of the chunk text |
| `text` | Cleaned body text (headers/footers stripped) |
| `figures` | List of figure metadata dicts from this chunk's pages |
| `tables` | List of table metadata dicts (filename, rows, cols, markdown) |
| `warnings` | Per-page extraction warnings |

---

## Report Fields

Each run produces a report in `reports/mehlman_generation_report_<timestamp>.json`.

Per-file fields (`files.<stem>.*`):

| Field | Description |
|---|---|
| `totalPages` | Total pages in the PDF |
| `totalTextChars` | Total body chars extracted (after header/footer stripping) |
| `chunksCreated` | Number of chunks in the manifest |
| `chunksProcessed` | Chunks actually processed (≤ chunksCreated when --max-chunks set) |
| `figuresDetected` | Total images found by PyMuPDF |
| `figuresKept` | Images passing size and aspect filters |
| `figuresIgnored` | Images rejected (too small, bad aspect, or duplicate hash) |
| `tablesDetected` | Tables found by pdfplumber lattice strategy |
| `tablesExtracted` | Tables successfully written to extracted_tables/ |
| `questionsGenerated` | Questions in app-ready output |
| `validationFailures` | Questions that failed initial validation |
| `repairsSucceeded` | Questions successfully repaired on retry |
| `repairFailures` | Questions that failed both attempts |

---

## Test Fixtures

| File | Purpose |
|---|---|
| `input_pdfs/test_mehlman_cardiology_fixture.pdf` | Synthetic 13-page PDF for `--dry-run`. Contains native text, repeated headers/footers, one bordered NYHA classification table (page 6), and one embedded PNG image (page 13). |

---

## Infrastructure Reuse

This tool imports from
`tools/uworld-notes-question-generator/generate_uworld_questions.py`.

Reused without modification:
- `_raw_gemini_call()` — Gemini HTTP client
- `_clean_llm_json()`, `_extract_json_payload()`, `_parse_gemini_json()` — JSON cleaning
- `validate_question()` — schema enforcement
- `call_gemini_with_retry()`, `_build_repair_prompt()` — retry/repair flow
- `build_app_ready_json()` — produces `nbme-gemini-json-v3` (patched for `sourceFormat`)
- `write_report()` — consistent report format
- `_placeholder_question()` — dry-run placeholders
- `check_duplicate_stems()`, `renumber_questions()`

Mehlman-specific additions:
1. `extract_pdf_pages()` — pdfplumber body-crop text + lattice tables + PyMuPDF figures
2. `split_pages_into_chunks()` — long-PDF chunking (8,000–12,000 chars) with page metadata
3. `_inject_asset_markers()` — prepend `[DETECTED FIGURE/TABLE]` markers to chunk text
4. 4-mode CLI: `--extract-only`, `--chunk-only`, `--dry-run`, `--generate`
5. `--resume` / `--force` incremental run support
6. `prompts/mehlman_pdf_to_questions_prompt.txt`

---

## Known Limitations

| Limitation | Details |
|---|---|
| Image-only PDFs | Scanned PDFs extract no text; pipeline warns but produces empty chunks |
| Table detection scope | Lattice-only strategy detects bordered tables; text-alignment tables without lines are not detected (intentional — avoids false positives) |
| Header/footer stripping | Fixed 8%/92% crop zones; PDFs with unusual margin layouts may include partial headers/footers in body text |
| Chunk size variability | Final chunk per file may be well under 8,000 chars if total content is small |
| Figure context | Figures are not sent to Gemini; only their dimensions and filenames are visible in the prompt |
| Milestone 2 not validated | Live `--generate` mode is wired but untested with real Mehlman PDFs; validate manually before relying on output |

---

## Verification Checklist

Before declaring a run successful:

- [ ] `schemaVersion` is `"nbme-gemini-json-v3"` in output
- [ ] `sourceFormat` is `"mehlman-pdf"` in output
- [ ] All questions have 4 answerChoices (A-D)
- [ ] All questions have non-empty `retrievalTag` and `reviewPearl`
- [ ] No "according to Mehlman" wording in any question
- [ ] `figureRefs` is `[]` in all questions
- [ ] Chunk manifest exists with `pageStart`, `pageEnd`, `charCount` per chunk
- [ ] No chunk exceeds 12,000 chars
- [ ] App import: validation modal shows ≥ 90% pass rate (live generation)
- [ ] App import: preview shows full stems without truncation
