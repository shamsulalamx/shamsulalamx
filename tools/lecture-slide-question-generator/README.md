# Lecture Slide Question Generator

This is an isolated curriculum-to-assessment pipeline.

It converts PDF lecture slides into app-ready NBME-style JSON without modifying the raw NBME importer or `index.html`.

## Source Rule

Slides are the only source of truth. The generator may turn slide-supported bullets into clinical vignettes, but it must not add outside diseases, diagnostics, management, epidemiology, or mechanisms.

## Pipeline

1. PDF decomposition: one PDF page becomes one deterministic slide record with OCR/text, slide image, embedded image metadata, tables, slide index, and PDF metadata.
2. Semantic normalization: slides become structured normalized records. No questions are generated in this stage.
3. Rolling memory and deduplication: concept, diagnosis, distractor, stem-template, and image usage are tracked across chunks.
4. Question allocation: each slide receives 0, 1, or 2 questions based on yield, richness, redundancy, and image/table value.
5. Question generation: allocated normalized slides are converted into canonical `nbme-gemini-json-v3` app-ready JSON.
6. Validation: schema, figure routing, answer count, HTML, OCR contamination, duplicates, and grounding checks run before output is written.

## Commands

Place PDFs in:

```text
tools/lecture-slide-question-generator/input_pdfs/
```

Dry-run the full deterministic path without Gemini:

```bash
python3 generate_lecture_slide_questions.py --dry-run
```

Generate with Gemini:

```bash
export GEMINI_API_KEY='your-key-here'
python3 generate_lecture_slide_questions.py --generate
```

Validate an output file:

```bash
python3 generate_lecture_slide_questions.py --validate-only output_json/app_ready/<file>.json
```

## Output

App-ready JSON is written to:

```text
output_json/app_ready/
```

The output uses the existing app importer schema:

```text
nbme-gemini-json-v3
```

No new app importer is required.
