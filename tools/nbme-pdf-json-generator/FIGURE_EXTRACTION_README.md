# NBME Figure Extraction

This is an additive review utility for NBME PDFs. It extracts likely figure/image crop candidates from rendered PDF pages and writes a manifest plus contact sheet for rapid manual review.

It does not modify `index.html`, the app importer, raw text extraction, chunking, Gemini normalization, app-ready JSON conversion, or any existing app-ready JSON file. It does not auto-attach images and does not inject `figureRefs`.

## Purpose

The current milestone is screenshot elimination, not automatic image attachment.

The script renders PDF pages and uses conservative OpenCV contour detection to find likely non-text visual regions. A second-pass scorer then rejects obvious text, answer-choice blocks, paragraph layouts, plain text tables, and decorative lines. Each kept crop is saved as a PNG. The contact sheet lets you quickly decide which crops are real clinical figures before any future manual or automated attachment workflow.

## Requirements

Install the required Python packages:

```bash
python3 -m pip install pymupdf opencv-python pillow
```

`pdfplumber` is optional but recommended for weak question-number hints:

```bash
python3 -m pip install pdfplumber
```

If OpenCV is missing, the script fails clearly with:

```bash
python3 -m pip install opencv-python
```

## Commands

Run from the tool directory:

```bash
cd tools/nbme-pdf-json-generator
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --dpi 250
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --max-pages 5
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --contact-sheet
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --review-html
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --conservative
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --strict-text-filter
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --min-visual-score 0.50
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --debug-rejected
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --link-figures
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --link-figures --app-ready output_json/app_ready/8A_app_ready.json
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --link-figures --links-html
```

Defaults:

```text
--dpi 200
--conservative true
--contact-sheet true
--review-html true
--strict-text-filter false
--min-visual-score 0.42
--debug-rejected false
```

Start real NBME testing with the limited smoke command first:

```bash
cd tools/nbme-pdf-json-generator
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --max-pages 5
```

## Outputs

The script creates:

```text
extracted_figures/<source>_p###_fig###.png
figure_manifests/<source>_figure_manifest.json
figure_manifests/<source>_contact_sheet.png
figure_manifests/<source>_figure_review.csv
figure_manifests/<source>_figure_review.html
figure_manifests/<source>_suggested_figure_links.json
figure_manifests/<source>_suggested_figure_links.csv
figure_manifests/<source>_suggested_figure_links.html
```

These are generated review artifacts and are ignored by git by default.

## Manifest

The manifest has this shape:

```json
{
  "sourcePdf": "input_pdfs/8A.pdf",
  "dpi": 200,
  "settings": {
    "conservative": true,
    "strictTextFilter": false,
    "minVisualScore": 0.42,
    "debugRejected": false
  },
  "figures": [
    {
      "figureId": "8A_p012_fig001",
      "filePath": "extracted_figures/8A_p012_fig001.png",
      "page": 12,
      "bbox": [100, 200, 620, 480],
      "width": 520,
      "height": 280,
      "cropHash": "...",
      "suggestedQuestionNumber": 11,
      "confidence": "medium",
      "score": 0.62,
      "visualScore": 0.84,
      "textLikeScore": 0.05,
      "reasons": [
        "major non-text visual region",
        "same page as one extracted question number",
        "same page as image-reference phrase"
      ],
      "rejectionReasons": [],
      "kept": true,
      "needsReview": true
    }
  ],
  "summary": {
    "pagesProcessed": 0,
    "figuresDetected": 0,
    "figuresKept": 0,
    "figuresIgnored": 0,
    "duplicatesRemoved": 0,
    "highConfidence": 0,
    "mediumConfidence": 0,
    "lowConfidence": 0,
    "unknownConfidence": 0,
    "needsReview": 0,
    "textLikeKept": 0,
    "rejectedDebugCount": 0
  },
  "warnings": []
}
```

When `--debug-rejected` is used, the manifest also includes `rejectedCandidates[]` with page, bbox, visual/text scores, and rejection reasons. Rejected crops are not included in the contact sheet.

## Second-Pass Filtering

The second pass uses image statistics and connected components rather than OCR. It scores candidates with:

- `visualScore`: higher for photo-like, graph-like, ECG-like, or image-dense regions.
- `textLikeScore`: higher for black text on white background, dense paragraph rows, answer-list layouts, and plain text tables.
- `rejectionReasons`: explains why a candidate was rejected or flagged.
- `kept`: true for candidates written to `extracted_figures/`.

Default behavior is conservative but not maximal. It keeps uncertain medical-looking figures while rejecting obvious answer-choice and text blocks. Use `--strict-text-filter` only when review sheets still contain too many text crops.

## Manual Review Workflow

1. Run the extractor:

```bash
cd tools/nbme-pdf-json-generator
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --debug-rejected
```

2. Open the contact sheet first:

```text
figure_manifests/8A_contact_sheet.png
```

Use it to quickly decide whether the kept crops are mostly real clinical figures.

3. Open the static HTML review page second:

```text
figure_manifests/8A_figure_review.html
```

This page shows each kept PNG beside its metadata, suggested question number, confidence, score, and file path. The checkboxes are for manual review labels only: accept, reject, wrong question, and needs crop. The page is static HTML and does not require a server.

4. Use the CSV as the tracking sheet:

```text
figure_manifests/8A_figure_review.csv
```

Fill `userDecision` and `notes` while reviewing. Use the PNG `filePath` from the CSV or HTML page when manually attaching images later.

No auto-attachment happens in this milestone. The extractor does not inject `figureRefs` and does not modify app-ready JSON.

## Suggested Figure Links

The optional bridge layer links kept figure candidates to existing app-ready questions for manual review only.

```bash
cd tools/nbme-pdf-json-generator
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --link-figures
```

Optional explicit paths:

```bash
python3 nbme_extract_figures.py \
  --pdf input_pdfs/8A.pdf \
  --link-figures \
  --app-ready output_json/app_ready/8A_app_ready.json \
  --manifest figure_manifests/8A_figure_manifest.json
```

The link step reads:

- `figure_manifests/<source>_figure_manifest.json`
- `output_json/app_ready/<source>_app_ready.json`
- `output_json/chunks/<source>_chunks.json` when available
- `output_json/normalized/<source>_normalized.json` when available in future workflows

It writes:

- `figure_manifests/<source>_suggested_figure_links.json`
- `figure_manifests/<source>_suggested_figure_links.csv`
- `figure_manifests/<source>_suggested_figure_links.html`

The link review page shows question number, stem preview, existing figure placeholders, suggested crop images, confidence, reasons, and file paths. Its checkboxes are visual labels only: accept, reject, wrong question, and needs crop.

Suggested links are not app integration. The script does not auto-attach images, does not inject `figureRefs`, and does not rewrite app-ready JSON. Confidence is conservative: high requires multiple strong signals, and most links remain review-needed.

## Association Limits

Candidate association is suggestive only. It is not authoritative.

The script may use weak hints from native page text, image-reference phrases, answer-choice position, and whether the crop is the only major visual candidate on a page. Raster screenshot pages may have little or no native text, so mapping confidence may be `unknown`.

If confidence is not `high`, `needsReview` is set to `true`.

Do not treat any crop as correctly mapped to a question until it has been visually reviewed in the contact sheet or opened directly.

## Known Limitations

Association is suggestive, not authoritative.

Raster screenshots may reduce or eliminate text-based mapping confidence.

Low-confidence and medium-confidence crops require manual review.

False negatives are preferred over excessive false positives.

Auto-attachment is intentionally deferred.

`figureRefs` injection is intentionally deferred.
