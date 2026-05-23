# NBME Self-Assessment Suite — Known-Good Workflows

**Last updated:** 2026-05-23
**Current stable tag:** `v4.48-lecture-explanation-tables-stable`
**Purpose:** Exact commands, verified test assets, and critical warnings. Copy-paste safe.

> **BIC-driven runs vs. CLI runs.** When you launch a generator through the Batch Import Center (packaged or dev Electron), outputs go to `~/Library/Application Support/nbme-self-assessment-suite/batch-import-center/jobs/<jobId>/<generator-dir>/...` because `BIC_JOB_OUTPUT_ROOT` is set in the subprocess environment. When you run the generator directly from a terminal with the commands below, outputs go to the in-repo `tools/<generator-dir>/output_json/`. Both paths produce the same artifacts.

---

## ⚠️ CRITICAL WARNINGS — READ FIRST

### 1. DO NOT test against the stale Electron/v1 packaged build

The packaged `.app` at:
```
dist/mac-arm64/shamsulalamx.app/Contents/Resources/app/index.html
```
is a **frozen bundle**. Edits to the project root `index.html` are **completely invisible** to it. Multiple debugging sessions were wasted this way.

**Always use the dev server for development.**

### 2. DO NOT restart electron:dev between edits

`npm run electron:dev` is a dev server. A single `Cmd+R` reload picks up `index.html` changes. Restarting the process is never required for code changes.

### 3. `dist/` is gitignored — do not commit it

The `dist/` directory is not tracked. Do not commit `dist/` files as source of truth.

---

## Workflow 1: Start the App (Development)

```bash
cd "/Users/shamsulalam/Desktop/shamsulalamx"
npm run electron:dev
```

Electron opens, serves `index.html` at `http://127.0.0.1:8888`.
Reload with `Cmd+R` after any `index.html` edit.

### First time only (or after dependency changes)

```bash
npm install
```

### Run in browser (no Electron IPC features)

Open `https://shamsulalamx.dpdns.org` in any browser (served from `main` branch).
UWorld/Divine Gemini refinement is not available in the browser.

---

## Workflow 2: NBME PDF → App-Ready JSON

### Prerequisites

```bash
pip3 install pdfplumber    # required
# Optional — only for fully scanned/image-only PDFs:
pip3 install pymupdf pytesseract
brew install tesseract
```

### Step 1: Drop PDF into input directory

```bash
cp "NBME_Psych_9.pdf" tools/nbme-pdf-json-generator/input_pdfs/
```

### Step 2: Extract and chunk

```bash
cd tools/nbme-pdf-json-generator
python3 extract_pdfs.py
```

Output: `output_json/raw_text/NBME_Psych_9_raw.txt` + `output_json/chunks/NBME_Psych_9_chunks.json`

### Step 3: Normalize via Gemini

```bash
export GEMINI_API_KEY='your-api-key-here'
python3 extract_pdfs.py --normalize-gemini
```

Output: `output_json/normalized/NBME_Psych_9_normalized.json`
Report: `reports/extraction_report_<timestamp>.json`

Validates each Gemini response. One automatic repair retry on failure. Failures recorded in `failures[]`.

### Step 4: Convert to app-ready JSON

```bash
python3 normalized_to_app_json.py
```

Output: `output_json/app_ready/NBME_Psych_9_app_ready.json`

### Step 5: Import into app

In the running Electron app: **Import → NBME Gemini JSON → select `NBME_Psych_9_app_ready.json` → validate → preview → save**

### Dry-run (no API key, end-to-end pipeline test)

```bash
cd tools/nbme-pdf-json-generator
python3 extract_pdfs.py --normalize-dry-run
python3 normalized_to_app_json.py --dry-run
```

### macOS double-click launcher

Double-click `tools/nbme-pdf-json-generator/Generate_NBME_JSONs.command` in Finder.
(Right-click → Open if macOS blocks it.)

---

## Workflow 3: UWorld Notes → App-Ready JSON

### Prerequisites

```bash
# No dependencies required (uses only Python stdlib)
# Optional for DOCX/RTF support:
pip3 install python-docx    # for .docx files
pip3 install striprtf       # for .rtf files
```

### Step 1: Drop notes file into input directory

```bash
cp "UWorld_Psych_Notes.txt" tools/uworld-notes-question-generator/input_notes/
```

Supported formats: `.txt`, `.md`, `.docx` (needs python-docx), `.rtf` (needs striprtf)
**Recommended: `.txt`** — no extra dependencies.

### Step 2: Generate questions

```bash
cd tools/uworld-notes-question-generator
export GEMINI_API_KEY='your-api-key-here'
python3 generate_uworld_questions.py --generate
```

Default: 15 questions per file. Override:
```bash
python3 generate_uworld_questions.py --generate --questions-per-file 10
python3 generate_uworld_questions.py --generate --questions-per-file 20
```

Output: `output_json/app_ready/<stem>_app_ready.json`
Report: `reports/question_generation_report_<timestamp>.json`

### Step 3: Import into app

In the running Electron app: **Import → NBME Gemini JSON → select `<stem>_app_ready.json` → validate → preview → save**

### Dry-run (no API key)

```bash
python3 generate_uworld_questions.py --dry-run
```

Produces placeholder questions. Full pipeline tested. Safe to run without a key.

---

## Workflow 4: Anki Notes → App-Ready JSON

### Step 1: Export Anki deck as plain text (.txt)

In Anki: File → Export → Cards in plain text. Save as `my_deck.txt`.

### Step 2: Drop file into input directory

```bash
cp "my_deck.txt" tools/anki-question-generator/input_notes/
```

### Step 3: Generate questions

```bash
cd tools/anki-question-generator
export GEMINI_API_KEY='your-api-key-here'
python3 generate_anki_questions.py --generate
```

```bash
python3 generate_anki_questions.py --generate --questions-per-file 10
```

Output: `output_json/app_ready/<stem>_app_ready.json`

### Step 4: Import into app

Same as Workflow 3, Step 3.

### Dry-run

```bash
python3 generate_anki_questions.py --dry-run
```

---

## Workflow 5: Google Drive Backup/Restore

### Full backup

In the app: **Settings → Backup Now** → wait for "Drive backup complete" (green status).
Do not navigate away mid-backup.

### Restore on a new device/browser

1. Open `https://shamsulalamx.dpdns.org` in Chrome (or `npm run electron:dev`)
2. Settings → Connect Drive → (OAuth popup) → authorize
3. Settings → Restore Drive
4. Wait for "Drive restore complete. Reloading…" and automatic page reload
5. Verify: tests visible, Gemini key populated, misc docs present, score history intact

### If Drive OAuth fails with `origin_mismatch`

Verify the `274374578651-5edirahp87c5hpv69donfpvcr81tmidk` credential in Google Cloud Console:
- Credential type must be **Web application** (not Desktop)
- Authorized JavaScript Origins must include: `https://shamsulalamx.dpdns.org`, `http://localhost:8888`, `http://localhost:8080`

---

## Known-Good Test Asset Paths

### For NBME import regression testing

```
test-assets/known-good/8A_app_ready_WORKING.json
```
Import this file via the NBME Gemini JSON importer. It should validate cleanly, show 50 questions in preview, and save without errors.

### For end-to-end quiz testing (committed to main)

```
test-data/Psych_Shelf_3_app_ready.json   — 50 Qs, shared-stem groups Q33–Q36
test-data/Psych_Shelf_4_app_ready.json   — 50 Qs
test-data/Psych_Shelf_5_app_ready.json   — 50 Qs
test-data/Psych_Shelf_6_app_ready.json   — 50 Qs, lab tables
test-data/Psych_Shelf_7_repaired_app_ready.json  — 50 Qs
test-data/Psych_Shelf_8_full_app_ready.json      — 50 Qs, figureRefs (Q25/Q34/Q48)
```

### For figure rendering validation

```
test-data/Psych_Shelf_8_full_app_ready.json
```
Navigate to Q25, Q34, Q48 in quiz mode to test `[FIGURE: ...]` placeholder rendering and figure attachment upload.

### For UWorld pipeline smoke testing

```
test-data/UWorld_Notes_Psych_Questions_enhanced_app_ready.json  (local only — not committed)
```

### For tool pipeline outputs (not committed — local only)

```
tools/nbme-pdf-json-generator/output_json/app_ready/8A_app_ready.json
tools/uworld-notes-question-generator/output_json/app_ready/test_cardiology_app_ready.json
tools/anki-question-generator/output_json/app_ready/test_cardiology_anki_app_ready.json
tools/anki-question-generator/output_json/app_ready/test_medicine_anki_app_ready.json
```

---

## Known-Good JSON Structure (minimal import file)

```json
{
  "schemaVersion": "nbme-gemini-json-v3",
  "testTitle": "Test Name Here",
  "sourceFormat": "uworld-notes",
  "actualExtractedQuestionCount": 1,
  "extractionWarnings": [],
  "questions": [
    {
      "id": "q001",
      "questionNumber": 1,
      "stem": "A 28-year-old woman presents with...",
      "answerChoices": [
        { "label": "A", "text": "Adjustment disorder" },
        { "label": "B", "text": "Major depressive disorder" },
        { "label": "C", "text": "Bipolar disorder" },
        { "label": "D", "text": "Dysthymia" }
      ],
      "correctAnswer": "B",
      "educationalObjective": "Diagnose major depressive disorder.",
      "explanationSections": [
        {
          "heading": "Correct Answer Explanation",
          "body": ["The patient meets 5 of 9 SIGECAPS criteria for 2+ weeks."]
        }
      ],
      "retrievalTag": "MDD diagnostic criteria SIGECAPS",
      "reviewPearl": "MDD requires 5 of 9 SIGECAPS symptoms for at least 2 weeks.",
      "hasEmbeddedFigure": false,
      "figureRefs": [],
      "tables": [],
      "extractionWarnings": []
    }
  ]
}
```

---

## Verification Checklist After Any Import

1. Validation modal shows: green "X questions passed validation"
2. Preview shows full stems (no truncation — confirms `_isLabPara()` guards are intact)
3. Correct answer shown in preview
4. No "contamination phrase" warnings in validation output
5. After save: test appears in target folder
6. Start quiz → answer Q1 → explanation panel shows educational objective + explanation

---

## Gemini API Key Setup

The API key must be set in the environment for all Python tool pipelines:

```bash
export GEMINI_API_KEY='your-api-key-here'
```

Or inline:
```bash
GEMINI_API_KEY='your-key' python3 generate_uworld_questions.py --generate
```

**The key is never stored in files, printed to terminal, or committed to git.**

For the in-app Gemini features (hints, tagging): enter the key in **Settings → Gemini API Key** inside the Electron app. It is stored in `db.settings.geminiApiKey` and synced through Google Drive.

---

## Stale/Generated Files That Should NOT Be Committed

The following are gitignored or should remain untracked:

| Path | Why |
|---|---|
| `dist/` | Generated Electron builds — frozen bundles, not source |
| `node_modules/` | npm dependencies |
| `.netlify/` | Local Netlify dev state |
| `tools/*/input_pdfs/*.pdf` | Source exam files — potentially copyrighted |
| `tools/*/input_notes/*.txt` | Source notes — potentially copyrighted |
| `tools/*/output_json/` | Generated intermediate and final JSON — local artifacts |
| `tools/*/reports/` | Pipeline run reports — local artifacts |
| `test-assets/` | Currently untracked; large binary reference files |
| `test-data/*` (some) | Files with `-rw-------` permissions are local-only |
| `.DS_Store` | macOS metadata (gitignored) |
| `.env`, `.env.*` | Environment variables with API keys (gitignored) |
