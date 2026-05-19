# OME PDF → Step 2 Question Generator (v1 / v2)

External tool pipeline that converts OME (Online MedEd) video lesson PDFs into
`nbme-gemini-json-v3` app-ready JSON, ready for import into the NBME Self-Assessment app.

---

## Pipeline

### v1 — text only (default)

```
OME PDF (input_pdfs/)
  │
  ▼ pdfplumber text extraction — NO OCR needed (OME PDFs are vector-based)
  output_json/raw_text/<stem>_raw.txt
  │
  ▼ split_into_chunks() — heading/section boundaries, 3000-char cap
  output_json/chunks/<stem>_chunks.json
  │
  ▼ Gemini: gemini-2.5-flash  (reused from UWorld generator)
  │  Prompt: prompts/ome_to_questions_prompt.txt
  │  Validation + retry/repair: reused from UWorld generator
  │
  ▼ output_json/app_ready/<stem>_app_ready.json  (schema: nbme-gemini-json-v3)
  │
  ▼ Import via: App → NBME Gemini JSON importer
```

### v2 — hybrid text + asset extraction (`--extract-assets`)

Same as v1, plus:

```
OME PDF (input_pdfs/)
  │
  ├─▶ PyMuPDF figure extraction
  │     extracted_figures/<stem>_p<N>_fig<M>.png
  │     Filtered: ≥80×80 px, aspect ratio ≤ 8:1, MD5-dedup
  │
  ├─▶ pdfplumber table extraction (lattice/stream)
  │     extracted_tables/<stem>_p<N>_table<M>.json
  │     Filtered: ≥ 2 rows × 2 cols
  │
  └─▶ Asset metadata injected into chunk text as [DETECTED FIGURE: ...] and
      [DETECTED TABLE: ...] markers. Tables rendered as markdown inline.
      No image bytes sent to Gemini. No OCR. No schema changes. No app changes.
```

**figureRefs stays `[]`** in all output. The app and importer are unchanged.

---

## Usage

### Dry-run (no API key required)

```bash
cd tools/ome-pdf-question-generator
python3 generate_ome_questions.py --dry-run
python3 generate_ome_questions.py --dry-run --extract-assets
```

Produces placeholder app-ready JSON. Full pipeline exercised except Gemini calls.

### Generate questions (requires GEMINI_API_KEY)

```bash
cd tools/ome-pdf-question-generator
export GEMINI_API_KEY='your-api-key-here'

# v1 — text only
python3 generate_ome_questions.py --generate
python3 generate_ome_questions.py --generate --questions-per-file 15

# v2 — hybrid text + figure/table extraction
python3 generate_ome_questions.py --generate --extract-assets
python3 generate_ome_questions.py --generate --extract-assets --questions-per-file 15
```

Default: 15 questions per PDF file.

---

## Input

Drop OME lesson PDF files into `input_pdfs/`. Only `.pdf` files are processed.

OME PDFs are vector-based (text-layer); pdfplumber extracts them cleanly without OCR.

---

## Output

`output_json/app_ready/<stem>_app_ready.json`

Import this file via:
**App → Import → NBME Gemini JSON → select file → validate → preview → save**

v2 also produces:
- `extracted_figures/<stem>_p<N>_fig<M>.png` — filtered embedded images
- `extracted_tables/<stem>_p<N>_table<M>.json` — pdfplumber table data

---

## Dependencies

| Package | Required | Install |
|---|---|---|
| pdfplumber | Required | `pip3 install pdfplumber` |
| PyMuPDF (fitz) | Required for `--extract-assets` (v2) | `pip3 install pymupdf` |
| Gemini API key | Required for `--generate` | Set `GEMINI_API_KEY` env var |

All Gemini infrastructure is inherited from the UWorld generator (no additional deps).

---

## Report fields

Each run produces a JSON report in `reports/ome_generation_report_<timestamp>.json`.

Per-file fields include:

| Field | Description |
|---|---|
| `pagesProcessed` | Pages with extractable text |
| `charsExtracted` | Total character count of extracted text |
| `figuresDetected` | Raw image count found by PyMuPDF (0 in v1) |
| `figuresKept` | Images that passed size/ratio/dedup filtering (0 in v1) |
| `figuresIgnored` | Images filtered out (too small, banner-shaped, or duplicate) |
| `tablesDetected` | Tables found by pdfplumber with ≥2×2 dimensions (0 in v1) |
| `tablesExtracted` | Tables saved to `extracted_tables/` (0 in v1) |
| `assetOutputPaths` | Absolute paths of all saved figure/table files |
| `pdfExtractionWarnings` | Pages with no extractable text or extraction errors |
| `questionsGenerated` | Questions produced for this file |
| `validationFailures` | Questions that failed initial validation |
| `repairsSucceeded` | Questions successfully repaired on retry |
| `repairFailures` | Questions that failed both attempts |

Top-level report fields:

| Field | Description |
|---|---|
| `extractAssets` | `true` if `--extract-assets` was passed (v2), `false` otherwise |
| `dryRun` | Whether this was a dry-run |

---

## v1 vs v2 Scope

| Capability | v1 (default) | v2 (`--extract-assets`) |
|---|---|---|
| Native text extraction | Yes | Yes |
| Embedded figure extraction | No | Yes (PyMuPDF, filtered) |
| Table extraction | No | Yes (pdfplumber lattice/stream) |
| OCR | No | No |
| Image bytes sent to Gemini | No | No |
| App/importer changes | None | None |
| Schema changes | None | None |
| `figureRefs` | `[]` | `[]` |

---

## Known Limitations (v2)

- **Figure content is not interpreted**: Asset markers provide spatial context and
  dimensions but Gemini cannot see the image pixels. Questions about figure content
  are based on surrounding slide text plus the marker hint only.
- **Not all embedded images are educational**: Logos, watermarks, and decorative
  dividers are filtered out by size/ratio heuristics but filtering is imperfect.
- **pdfplumber table detection requires borders**: Borderless/merged-cell tables may
  not be detected. Complex multi-page tables are not reconstructed.
- **No OCR path**: If a slide is a scanned image (no text layer), that page produces
  an extraction warning and is skipped. This is rare in OME PDFs (vector-based).

---

## Infrastructure Reuse

This tool is a thin wrapper over
`tools/uworld-notes-question-generator/generate_uworld_questions.py`.

The following are reused without modification:

- `_raw_gemini_call()` — Gemini HTTP client (no SDK dependency)
- `_clean_llm_json()`, `_extract_json_payload()`, `_parse_gemini_json()` — JSON cleaning
- `validate_question()` — schema enforcement
- `call_gemini_with_retry()`, `_build_repair_prompt()` — retry/repair flow
- `split_into_chunks()` — heading-based chunker with paragraph fallback
- `build_app_ready_json()` — produces valid `nbme-gemini-json-v3`
- `write_report()` — consistent report format
- `_placeholder_question()` — dry-run placeholders
- `check_duplicate_stems()`, `renumber_questions()`

OME-specific components:

1. `extract_pdf_text()` — pdfplumber text + optional PyMuPDF figures + pdfplumber tables
2. `prompts/ome_to_questions_prompt.txt` — prompt adapted for lecture/slide structure
3. `--extract-assets` flag and v2 asset pipeline

---

## Test Fixtures

| File | Purpose | Size |
|---|---|---|
| `input_pdfs/test_ome_mood_disorders.pdf` | v1 text-only dry-run fixture | ~3 KB |
| `input_pdfs/test_ome_assets_fixture.pdf` | v2 fixture: text + image + table | ~10 KB |

---

## Verification Checklist

Before declaring a run successful:

- [ ] `schemaVersion` is `"nbme-gemini-json-v3"` in output
- [ ] `sourceFormat` is `"ome-pdf"` in output
- [ ] All questions have 4 answerChoices (A-D)
- [ ] All questions have non-empty `retrievalTag` and `reviewPearl`
- [ ] All questions have non-empty `explanationSections[].body`
- [ ] `correctAnswer` is one of A/B/C/D and matches a choice label
- [ ] No forbidden strings in output
- [ ] App import: validation modal shows ≥ 90% pass rate
- [ ] App import: preview shows full stems without truncation
- [ ] App import: quiz runs correctly on imported test

v2 additional checks:

- [ ] `extracted_figures/` directory created and contains at least one `.png`
- [ ] `extracted_tables/` directory created and contains at least one `.json`
- [ ] Report shows `figuresKept` > 0 and `tablesExtracted` > 0
- [ ] `assetOutputPaths` lists the saved file paths
- [ ] v1 dry-run (`--dry-run` without `--extract-assets`) still works correctly
