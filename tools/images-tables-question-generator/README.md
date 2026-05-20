# Images and Tables Question Generator

This tool creates one app-ready JSON file from screenshot images.

## First run

```bash
python3 generate_images_tables_questions.py --init
```

Then place screenshots in:

```text
tools/images-tables-question-generator/input_images/
```

Supported files: `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff`.

## Generate JSON

```bash
export GEMINI_API_KEY='your-key-here'
python3 generate_images_tables_questions.py --generate
```

Output is written to:

```text
output_json/app_ready/
```

The generated JSON uses `q.images[]` as the only image attachment route. The
app importer stores temporary image data in `FigureStore` and removes inline
data from the saved test.
