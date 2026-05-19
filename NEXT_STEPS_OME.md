# NBME Self-Assessment Suite — Next Steps: OME External Tool Pipeline

**Last updated:** 2026-05-19
**Status:** PLANNED — DO NOT IMPLEMENT YET. This file documents the architecture plan only.
**Purpose:** Exact plan for building the OME external tool pipeline when work resumes.

---

## ⚠️ Do Not Implement OME Yet

The existing OME in-app importer (`ome-v1-stable`) is stable. The external tool pipeline has not been built.

This document exists so the next session can start cleanly without architecture debates.

---

## 1. Current State

### What exists

**In-app OME importer (v1) — STABLE:**
- Handles OME PDF import directly inside `index.html`
- Uses PDF.js text-layer extraction (in-browser)
- Produces quiz objects stored in the app's OME folder
- Tagged: `ome-v1-stable`

**App-ready JSON files in test-data/ (local only):**
- `test-data/OME_Mood_app_ready.json` — committed
- `test-data/OME_Peds_Psych_FULL_app_ready.json` — local only
- `test-data/OME_Personality_FULL_app_ready.json` — local only
- `test-data/OME_Sleep_Sex_Drugs_FULL_app_ready.json` — local only

### What does NOT exist

An **external Python tool** (like the NBME, UWorld, and Anki tools in `tools/`) that converts OME PDFs into `nbme-gemini-json-v3` app-ready JSON. This is what needs to be built.

---

## 2. OME Architecture Plan

### Target directory structure

```
tools/ome-pdf-question-generator/
├── generate_ome_questions.py          ← main pipeline script
├── README.md
├── input_pdfs/                        ← drop OME PDF files here
├── prompts/
│   └── ome_to_questions_prompt.txt    ← new OME-specific Gemini prompt
├── output_json/
│   ├── raw_text/                      ← pdfplumber text output
│   ├── chunks/                        ← topic chunks
│   ├── generated/                     ← raw Gemini output
│   └── app_ready/                     ← ← IMPORT THIS FILE
└── reports/
```

### High-level pipeline

```
OME PDF (input_pdfs/)
  │
  ▼ pdfplumber text extraction (per page)
  │  NO OCR — OME PDFs are vector-based text-layer PDFs
  │  Standard pdfplumber is sufficient
  │
  ▼ raw_text/<stem>_raw.txt
  │
  ▼ split_into_chunks()  ← REUSE from uworld generator
  │  Topic/section boundaries → 3000-char cap
  │
  ▼ chunks/<stem>_chunks.json
  │
  ▼ Gemini: gemini-2.5-flash  ← REUSE uworld Gemini client
  │  Prompt: ome_to_questions_prompt.txt  (new)
  │  Validation: REUSE validate_question() from uworld generator
  │  Repair: REUSE call_gemini_with_retry() from uworld generator
  │
  ▼ app_ready/<stem>_app_ready.json  (schema: nbme-gemini-json-v3)
  │
  ▼ Import via: existing NBME Gemini JSON importer in index.html
```

---

## 3. Hybrid Extraction Strategy

### Text extraction

OME lesson PDFs are high-quality vector-based PDFs (not scanned). `pdfplumber` extracts text cleanly. **No OCR needed. No PyMuPDF. No pytesseract.**

This is confirmed by the existing OME app-ready files in `test-data/` which were produced without OCR.

### Selective figure extraction (if needed)

Some OME slides contain key diagrams (drug mechanisms, pathophysiology flowcharts). The question is whether to:

**Option A (recommended for v1): Skip figure extraction**
- Generate text-only questions from the conceptual content
- Describe figures in text ("A diagram shows the dopamine pathway...")
- Import cleanly with zero figure attachment complexity

**Option B (for v2, if needed): Selective figure crops**
- Use PyMuPDF to render specific pages with diagrams to image
- Attach as figure references in the question
- Use the existing `FigureStore` + figure attachment UI in the app
- Only worthwhile if questions require visual interpretation

**Start with Option A.** Build Option B only if the content genuinely requires figures.

---

## 4. No-OCR Reasoning

Do NOT add OCR to the OME pipeline because:

1. OME PDFs are rendered from source (not scanned) — pdfplumber extracts 100% of text
2. OCR introduces noise and errors on crisp vector text
3. OCR adds PyMuPDF + pytesseract dependencies (optional in NBME pipeline for good reason)
4. The existing OME app-ready files prove pdfplumber is sufficient
5. The NBME pipeline's OCR fallback only triggers when pdfplumber finds < 50 chars per page — OME pages will never hit this threshold

---

## 5. Reuse Requirements

The OME tool MUST reuse the following from `tools/uworld-notes-question-generator/generate_uworld_questions.py`:

| Component | Function | Why reuse |
|---|---|---|
| Gemini HTTP client | `_raw_gemini_call()` | Proven, no SDK dependency |
| JSON cleaning | `_clean_llm_json()` | Handles all Gemini formatting bugs |
| JSON payload extraction | `_extract_json_payload()` | Handles leading prose, nested structures |
| 3-stage JSON parse | `_parse_gemini_json()` | Saves debug files on failure without crashing |
| Validation | `validate_question()` | Consistent schema enforcement |
| Repair prompt builder | `_build_repair_prompt()` | Targeted fix without full regeneration |
| Retry/repair flow | `call_gemini_with_retry()` | 2-attempt pattern already tuned |
| Chunker | `split_into_chunks()` | Heading-based + paragraph fallback |
| App-ready builder | `build_app_ready_json()` | Produces valid `nbme-gemini-json-v3` |
| Report writer | `write_report()` | Consistent report format |
| Forbidden strings | `FORBIDDEN_STRINGS` | Same list applies |

**Implementation options:**
1. **Import the module:** `import sys; sys.path.insert(0, '../uworld-notes-question-generator'); import generate_uworld_questions as uw` — then patch globals (same pattern as Anki tool)
2. **Copy needed functions:** Copy only what's needed if the module import approach causes path complexity

The Anki wrapper (`generate_anki_questions.py`) demonstrates the wrapper/import pattern cleanly. Prefer option 1.

---

## 6. What Is New (OME-Specific)

Only two things need to be written from scratch:

### A. OME prompt (`prompts/ome_to_questions_prompt.txt`)

The UWorld notes prompt generates from notes/summaries. The OME prompt must:
- Work from structured lesson text (headers, bullet points, tables from PDF)
- Extract testable clinical concepts appropriate for NBME-style MCQs
- Generate 4-choice questions (A-D) with `retrievalTag` and `reviewPearl`
- Follow the same output schema as the UWorld prompt (since validation is shared)

Base it heavily on the UWorld notes prompt — the schema is identical.

### B. PDF text extraction (top of `generate_ome_questions.py`)

Replace the DOCX/RTF/TXT `extract_text()` with a pdfplumber extraction loop:

```python
import pdfplumber

def extract_pdf_text(filepath: Path) -> str:
    pages = []
    with pdfplumber.open(str(filepath)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append(f"## Page {i+1}\n\n{text.strip()}")
    return "\n\n".join(pages)
```

Supported extension: `.pdf` only (unlike UWorld which supports .txt/.md/.docx/.rtf).

---

## 7. Risks and Constraints

| Risk | Severity | Mitigation |
|---|---|---|
| OME PDF structure varies by lesson type | Medium | Dry-run on multiple lesson types first |
| Some OME slides are mostly figures | Low | Text-only approach avoids this entirely |
| Gemini may struggle with bullet-heavy slide text | Low | UWorld notes prompt handles similar formats |
| pdfplumber may miss text in some OME PDFs | Very low | Confirmed working on existing OME files |
| Schema mismatch with app importer | None | Using `nbme-gemini-json-v3` — importer already handles it |
| Breaking existing in-app OME importer | None | External tool does not touch `index.html` |

---

## 8. Do NOT Do These When Building OME Tool

- **Do not add OCR.** OME PDFs are vector-based. OCR adds noise, not value.
- **Do not create a new app importer.** The NBME Gemini JSON importer already handles `nbme-gemini-json-v3`. Use it.
- **Do not create a new schema version.** Use `nbme-gemini-json-v3`.
- **Do not duplicate the Gemini client.** Import/reuse from the UWorld generator.
- **Do not modify `index.html` for this pipeline.** The existing infrastructure handles it.
- **Do not build figure extraction in v1.** Start text-only. Add figures only if needed.
- **Do not use the NBME pipeline's `extract_pdfs.py` as a base.** The NBME tool is more complex (has OCR fallback, intermediate normalized schema, separate converter). The UWorld/Anki pattern is simpler and more appropriate for OME.

---

## 9. Verification Checklist (for when OME tool is eventually built)

Before declaring the OME tool ready:

- [ ] Dry-run produces valid placeholder JSON (`--dry-run` flag)
- [ ] Live run produces valid `nbme-gemini-json-v3` JSON
- [ ] `schemaVersion` is `"nbme-gemini-json-v3"` in output
- [ ] All questions have 4 answerChoices (A-D)
- [ ] All questions have non-empty `retrievalTag` and `reviewPearl`
- [ ] All questions have non-empty `explanationSections[].body`
- [ ] `correctAnswer` is one of A/B/C/D and matches a choice label
- [ ] No forbidden strings in output (`"Here are the questions"`, ` ```json`, etc.)
- [ ] App import: validation modal shows ≥ 90% pass rate
- [ ] App import: preview shows full stems without truncation
- [ ] App import: quiz runs correctly on imported test
- [ ] App import: explanation panel shows educational objective + explanation
- [ ] Run on ≥ 3 different OME lesson types to catch structural variation

---

## 10. Entry Point for Next Session

```
1. Read PROJECT_CONTEXT.md — understand the two-layer architecture
2. Read PIPELINE_ARCHITECTURE.md — understand shared vs. separate infrastructure
3. Read KNOWN_GOOD_WORKFLOWS.md — understand how UWorld/Anki tools work
4. Read tools/uworld-notes-question-generator/generate_uworld_questions.py — this is the base
5. Read tools/anki-question-generator/generate_anki_questions.py — this is the wrapper pattern
6. Create tools/ome-pdf-question-generator/ using the wrapper/import pattern
7. Write the OME prompt — base it on the UWorld notes prompt
8. Test with --dry-run first, then one real OME lesson PDF
9. Import into app via NBME Gemini JSON importer — no app changes needed
```

The safest entry point is step 6–7. Steps 1–5 are reading only.
