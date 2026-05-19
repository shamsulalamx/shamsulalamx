# OME PDF → Step 2 Question Generator (v1)

External tool pipeline that converts OME (Online MedEd) video lesson PDFs into
`nbme-gemini-json-v3` app-ready JSON, ready for import into the NBME Self-Assessment app.

**OME v1 extracts native text only. Figure/table-aware multimodal generation is planned
but not active.**

---

## Pipeline

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

---

## Usage

### Dry-run (no API key required)

```bash
cd tools/ome-pdf-question-generator
python3 generate_ome_questions.py --dry-run
```

Produces placeholder app-ready JSON. Full pipeline exercised except Gemini calls.

### Generate questions (requires GEMINI_API_KEY)

```bash
cd tools/ome-pdf-question-generator
export GEMINI_API_KEY='your-api-key-here'
python3 generate_ome_questions.py --generate
python3 generate_ome_questions.py --generate --questions-per-file 15
python3 generate_ome_questions.py --generate --questions-per-file 8
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

---

## Dependencies

| Package | Required | Install |
|---|---|---|
| pdfplumber | Required | `pip3 install pdfplumber` |
| Gemini API key | Required for `--generate` | Set `GEMINI_API_KEY` env var |

No other dependencies. All Gemini infrastructure is inherited from the UWorld generator.

---

## Report fields

Each run produces a JSON report in `reports/ome_generation_report_<timestamp>.json`.

Per-file fields include:

| Field | Description |
|---|---|
| `pagesProcessed` | Pages with extractable text |
| `charsExtracted` | Total character count of extracted text |
| `figuresDetected` | Always 0 in v1 — not implemented |
| `tablesDetected` | Always 0 in v1 — not implemented |
| `pdfExtractionWarnings` | Pages with no extractable text (image-only or blank) |
| `questionsGenerated` | Questions produced for this file |
| `validationFailures` | Questions that failed initial validation |
| `repairsSucceeded` | Questions successfully repaired on retry |
| `repairFailures` | Questions that failed both attempts |

---

## v1 Scope and Limitations

OME v1 is **text-only**. It does not:

- Extract or attach figures
- Parse tables from PDF layout
- Use OCR (OME PDFs are vector-based; OCR is not needed and would add noise)

Figure/table-aware multimodal generation (Option B from `NEXT_STEPS_OME.md`) is planned
for a future version but is not active in v1.

If a page contains only an image with no text layer, it produces an extraction warning
and is skipped. The remaining text-layer content is still processed normally.

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

Only two components are OME-specific:

1. `extract_pdf_text()` — pdfplumber-based extraction (replaces text-file `extract_text`)
2. `prompts/ome_to_questions_prompt.txt` — prompt adapted for lecture/slide structure

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
