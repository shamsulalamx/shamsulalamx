# NBME Figure Extraction Milestone 1

This is an additive review utility for NBME PDFs. It extracts likely figure/image crop candidates from rendered PDF pages and writes a manifest plus contact sheet for rapid manual review.

It does not modify `index.html`, the app importer, raw text extraction, chunking, Gemini normalization, app-ready JSON conversion, or any existing app-ready JSON file. It does not auto-attach images and does not inject `figureRefs`.

## Purpose

The current milestone is screenshot elimination, not automatic image attachment.

The script renders PDF pages and uses conservative OpenCV contour detection to find likely non-text visual regions. Each crop is saved as a PNG. The contact sheet lets you quickly decide which crops are real clinical figures before any future manual or automated attachment workflow.

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
python3 nbme_extract_figures.py --pdf input_pdfs/8A.pdf --conservative
```

Defaults:

```text
--dpi 200
--conservative true
--contact-sheet true
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
```

These are generated review artifacts and are ignored by git by default.

## Manifest

The manifest has this shape:

```json
{
  "sourcePdf": "input_pdfs/8A.pdf",
  "dpi": 200,
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
      "reasons": [
        "major non-text visual region",
        "same page as one extracted question number",
        "same page as image-reference phrase"
      ],
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
    "needsReview": 0
  },
  "warnings": []
}
```

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
