# NBME Self-Assessment Suite — Pipeline Architecture

**Last updated:** 2026-05-19
**Purpose:** Diagrams and explains all external tool pipelines, their shared infrastructure, their intentionally separate infrastructure, and the planned OME pipeline. Read before building or modifying any pipeline.

> Historical pipeline note. Current `shamsulalamx` ingestion guidance is in `ARCHITECTURE.md`, `BATCH_IMPORT_ARCHITECTURE.md`, `SHARED_INGESTION_ARCHITECTURE.md`, `VALIDATED_PIPELINES.md`, and `PROJECT_STATUS_2026-05-21.md`. The current primary workflow is Batch Import, manual app-ready import uses Import JSON, and OME/Anki/Divine validation claims must distinguish dry-run orchestration from live and semantic validation.

---

## 1. The Two-Layer Model

All question content enters the app through one of two paths:

```
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1: External Tool Pipelines  (tools/)                     │
│  Python scripts run outside the app.                            │
│  Input: raw source files (PDFs, DOCX, TXT)                      │
│  Output: *_app_ready.json (nbme-gemini-json-v1 or v3)           │
│                                                                 │
│  ┌──────────────────┐  ┌───────────────────┐  ┌─────────────┐  │
│  │  NBME PDF tool   │  │  UWorld notes tool│  │  Anki tool  │  │
│  └────────┬─────────┘  └────────┬──────────┘  └──────┬──────┘  │
└───────────┼─────────────────────┼────────────────────┼─────────┘
            │                     │                    │
            │         *_app_ready.json (user imports)  │
            └─────────────────────┼────────────────────┘
                                  ↓
┌─────────────────────────────────────────────────────────────────┐
│  LAYER 2: In-App Import Pipelines  (index.html)                 │
│                                                                 │
│  NBME Gemini JSON importer  ← accepts Layer 1 outputs           │
│  NBME PDF OCR importer      ← scanned PDFs directly             │
│  UWorld DOCX importer       ← DOCX + Electron IPC Gemini        │
│  OME PDF importer           ← short text-layer PDFs             │
│  Anki text importer         ← plain .txt                        │
│  Divine podcast importer    ← transcripts + Electron IPC Gemini │
│  Mehlman importer           ← structured notes                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Pipeline 1: NBME Scanned PDF

### Source: Physical NBME exam PDF (scanned pages or text-layer)

```
PDF file
  │
  ▼ pdfplumber text extraction (per page)
  │  └─ OCR fallback: PyMuPDF (fitz) renders page → pytesseract if text < 50 chars
  │
  ▼ extract_pdfs.py (Milestone 1-2)
  output_json/raw_text/<stem>_raw.txt        ← Markdown: one "## Page N" per page
  output_json/chunks/<stem>_chunks.json      ← chunkId, questionNumber, rawText, confidence
  │
  ▼ extract_pdfs.py --normalize-gemini (Milestone 4)
  │  Gemini: gemini-2.5-flash
  │  Prompt: tools/nbme-pdf-json-generator/prompts/chunk_to_normalized_question_prompt.txt
  │  Validation: 17 required fields, choices array, correctAnswer in choices, no contamination
  │  Retry: 1 automatic repair attempt on validation failure
  │
  ▼ output_json/normalized/<stem>_normalized.json    (schema: normalized-question-batch-v1)
  │
  ▼ normalized_to_app_json.py (Milestone 5)
  │  Maps normalized fields → internal quiz schema
  │  Builds correctBlurb HTML from explanationSections
  │  Handles figureRefs: fig.get("figureId", "") — normalized uses {figureId, location, visibleText}
  │
  ▼ output_json/app_ready/<stem>_app_ready.json     (schema: nbme-gemini-json-v1)
  │
  ▼ User imports via: App → NBME Gemini JSON importer in index.html
```

**Script entry points:**
```bash
cd tools/nbme-pdf-json-generator
python3 extract_pdfs.py                    # PDF → raw text + chunks
python3 extract_pdfs.py --normalize-gemini # chunks → Gemini → normalized JSON
python3 normalized_to_app_json.py          # normalized → app-ready JSON
```

**Double-click launcher:** `Generate_NBME_JSONs.command` (macOS Finder)

**OCR dependencies (optional — only for fully scanned/image-only PDFs):**
```bash
pip3 install pymupdf pytesseract
brew install tesseract
```
Without these, pages with < 50 chars of pdfplumber text produce empty raw text and 0 chunks.

---

## 3. Pipeline 2: UWorld Notes

### Source: UWorld notes exported as .txt / .md / .docx / .rtf

```
Notes file (input_notes/)
  │
  ▼ extract_text()  — utf-8 text or DOCX/RTF parsing (graceful degradation)
  output_json/raw_text/<stem>_raw.txt
  │
  ▼ split_into_chunks()  — heading-based splits, 3000-char cap, paragraph fallback
  output_json/chunks/<stem>_chunks.json
  │
  ▼ call_gemini_with_retry()  — per-chunk Gemini call
  │  Gemini: gemini-2.5-flash
  │  Prompt: tools/uworld-notes-question-generator/prompts/notes_to_questions_prompt.txt
  │  Validation: stem, 4 answerChoices (A-D), correctAnswer, explanationSections, retrievalTag, reviewPearl
  │  Repair: 1 automatic retry with targeted repair prompt on validation failure
  │
  ▼ output_json/generated/<stem>_generated.json  (raw Gemini output — live runs only)
  │
  ▼ build_app_ready_json()
  output_json/app_ready/<stem>_app_ready.json   (schema: nbme-gemini-json-v3)
  │
  ▼ User imports via: App → NBME Gemini JSON importer in index.html
```

**Script entry points:**
```bash
cd tools/uworld-notes-question-generator
python3 generate_uworld_questions.py --dry-run    # no API key needed; placeholder output
python3 generate_uworld_questions.py --generate   # hard-fail if GEMINI_API_KEY missing
python3 generate_uworld_questions.py --generate --questions-per-file 15
```

---

## 4. Pipeline 3: Anki Notes

### Source: Anki notes exported as .txt (or .md / .docx / .rtf)

```
Anki export (input_notes/)
  │
  ▼  generate_anki_questions.py
     Patches module-level globals in generate_uworld_questions.py:
       INPUT_DIR → input_notes/
       PROMPT_FILE → prompts/anki_notes_to_questions_prompt.txt
     Then calls: generate_uworld_questions.main()
  │
  ▼ Same pipeline as UWorld (see Pipeline 2 above)
  │
  ▼ output_json/app_ready/<stem>_app_ready.json  (schema: nbme-gemini-json-v3)
  │
  ▼ User imports via: App → NBME Gemini JSON importer in index.html
```

**Script entry points:**
```bash
cd tools/anki-question-generator
python3 generate_anki_questions.py --dry-run
python3 generate_anki_questions.py --generate
python3 generate_anki_questions.py --generate --questions-per-file 10
```

**Critical:** The Anki tool is a thin wrapper. It imports `generate_uworld_questions` and patches globals. Do not move `generate_anki_questions.py` out of `tools/anki-question-generator/` — it expects the sibling UWorld tool directory.

---

## 5. Pipeline 4: OME (Planned — NOT YET BUILT)

### Source: OME video lesson PDF (text-layer, vector-based — NOT scanned)

See `NEXT_STEPS_OME.md` for the full plan. Architecture summary:

```
OME PDF file (input_pdfs/)
  │
  ▼ pdfplumber text extraction  ← NO OCR NEEDED (OME PDFs are vector-based)
  raw_text/<stem>_raw.txt
  │
  ▼ split_into_chunks()  ← REUSE from uworld generator
  chunks/<stem>_chunks.json
  │
  ▼ Gemini  ← REUSE uworld Gemini client + repair flow
  │  Prompt: new OME-specific prompt
  │
  ▼ app_ready/<stem>_app_ready.json  (schema: nbme-gemini-json-v3)
  │
  ▼ User imports via: existing NBME Gemini JSON importer in index.html
```

The OME in-app importer (Pipeline 2B, v1) already exists in `index.html`. The **external tool** does not exist yet. The external tool approach (like UWorld/Anki) is the correct model — do NOT build a new in-app importer.

**Key constraint:** Do not add OCR. OME PDFs are text-layer PDFs. pdfplumber extracts them cleanly.

---

## 6. What Infrastructure Is Shared

All three working external tool pipelines share:

| Component | Location | Notes |
|---|---|---|
| Gemini API client | `generate_uworld_questions.py` `_raw_gemini_call()` | Raw `urllib.request.Request` — no SDK |
| JSON cleaning | `generate_uworld_questions.py` `_clean_llm_json()`, `_extract_json_payload()` | Strips BOM, fences, smart quotes, trailing commas |
| 3-stage JSON parse | `generate_uworld_questions.py` `_parse_gemini_json()` | Tries raw → cleaned → extracted; saves debug on fail |
| Retry/repair flow | `generate_uworld_questions.py` `call_gemini_with_retry()` | 2 attempts: initial + targeted repair prompt |
| Validation | `generate_uworld_questions.py` `validate_question()` | Checks stem, 4 choices, correctAnswer, explanationSections, retrievalTag, reviewPearl |
| Duplicate stem check | `generate_uworld_questions.py` `check_duplicate_stems()` | Warns; does not fail |
| App-ready wrapper | `generate_uworld_questions.py` `build_app_ready_json()` | Produces `nbme-gemini-json-v3` |
| Report generation | `generate_uworld_questions.py` `write_report()` | JSON report to `reports/` |
| Gemini model constant | Both Python files | `gemini-2.5-flash` — do not change |
| Forbidden strings | Both Python files | `"Here are the questions"`, ` ```json`, `"eftab720"`, etc. |

In-app, all pipelines share:
- `safeExportJson()` — strips `geminiApiKey` at any depth from all downloads
- NBME Gemini JSON importer (`validateNbmeGeminiJsonImport` + `normalizeNbmeGeminiJsonImport`)
- Save gate: preview → folder → name → confirm
- IndexedDB figure storage (`FigureStore`)
- Google Drive backup/restore

---

## 7. What Infrastructure Is Intentionally Separate

| Area | Why separate |
|---|---|
| NBME PDF extraction (`pdfplumber` + OCR) | Different source format — PDFs, not notes files |
| `normalized_to_app_json.py` converter | NBME has intermediate "normalized" schema; UWorld/Anki go directly to app-ready |
| NBME Gemini prompt | Extracts exam questions from raw text; very different task from generating questions from notes |
| UWorld/Anki Gemini prompt | Generates clinical vignette MCQs from notes; different task from NBME extraction |
| NBME `nbme-gemini-json-v1` schema | Has `metadata.figureRefs`, `metadata.tables`, `metadata.explanationSections` in a different layout than v3 |
| UWorld/Anki `nbme-gemini-json-v3` schema | Cleaner structure, `answerChoices`, flat `explanationSections` |
| In-app UWorld DOCX pipeline | Entirely in-app; uses Electron IPC for Gemini; no external tool |
| In-app Divine pipeline | Entirely in-app; uses Electron IPC for Gemini; no external tool |
| `electron/main.js` Gemini calls | IPC handlers for UWorld + Divine refinement only — completely separate from tool pipelines |

---

## 8. Schema Versions Quick Reference

### `nbme-gemini-json-v1` (NBME PDF pipeline output)

Top-level: `schemaVersion`, `title`, `source`, `sourceFile`, `createdAt`, `questionCount`, `questions[]`

Per question: `n`, `t`, `o[{l,t}]`, `c`, `e{A:...,B:...}`, `tags[]`, `retrievalTag`, `reviewPearl`, `educationalObjective`, `correctBlurb`, `metadata{sourceType, figureRefs[], tables[], explanationSections[], figureAttachments, ...}`

### `nbme-gemini-json-v3` (UWorld/Anki pipeline output)

Top-level: `schemaVersion`, `testTitle`, `sourceFormat`, `actualExtractedQuestionCount`, `extractionWarnings[]`, `questions[]`

Per question: `id`, `questionNumber`, `stem`, `answerChoices[{label,text}]`, `correctAnswer`, `educationalObjective`, `explanationSections[{heading,body[]}]`, `retrievalTag`, `reviewPearl`, `clinicalPearl`, `hasEmbeddedFigure`, `figureRefs[]`, `tables[]`, `sharedGroup`, `extractionWarnings[]`

### Both schemas are accepted by the in-app NBME Gemini JSON importer.
