# shamsulalamx Handoff Context v4

Last updated: 2026-05-20

Stable checkpoint:

```text
Commit: 4d96496
Tag: v4.0-images-tables-generator-stable
App/project name: shamsulalamx
Repository: /Users/shamsulalam/Desktop/shamsulalamx
```

This file is the current handoff for the shamsulalamx application. It includes the latest stable images/tables generator checkpoint and the packaged Electron verification status. Do not treat older project names as authoritative. References to "NBME Self-Assessment Suite" should be understood only as historical workflow context.

## Current Git State

Current checked state at handoff creation:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
git status --short --branch
```

Observed:

```text
## main...origin/main
 M .claude/settings.local.json
```

Current HEAD:

```text
4d96496 Add images and tables question generator
```

Current tag on HEAD:

```text
v4.0-images-tables-generator-stable
```

Known dirty file:

```text
.claude/settings.local.json
```

This is local Claude configuration. Do not commit it unless explicitly requested.

## Stable Tags

Stable and relevant tags currently present:

```text
v2.0-uworld-generation-working
v2.1-nbme-figure-attachments-fixed
v2.2-working-nbme-import-pipeline
v2.3-anki-generator-working
v2.3-anki-generator-wrapper
v2.4-migration-safe-state
v2.5-ome-text-pdf-generator
v2.6-repo-hygiene-stable
v2.7-ome-asset-extraction
v2.8-electron-production-build
v2.9-divine-audio-pipeline
v3.0-mehlman-milestone1-divine-upload-fix
v3.1-real-mehlman-validation
v3.2-nbme-figure-extraction-milestone1
v3.3-nbme-figure-filtering
v3.4-nbme-figure-review-workflow
v3.5-nbme-figure-review-linking
v3.6-nbme-in-app-figure-viewer
v3.7-nbme-in-app-crop-workflow
v3.8-nbme-crop-attach-workflow
v3.8-nbme-import-crop-attach-workflow
v3.9-nbme-image-attach-dedupe-stable
v4.0-images-tables-generator-stable
```

Latest stable checkpoint:

```bash
git checkout v4.0-images-tables-generator-stable
```

Use a branch if you plan to develop from the tag:

```bash
git checkout -b codex/<short-task-name> v4.0-images-tables-generator-stable
```

## Current Repository Structure

Important root files:

```text
index.html
electron/main.js
electron/preload.js
package.json
package-lock.json
netlify.toml
PROJECT_CONTEXT.md
PROJECT_STATUS.md
PIPELINE_ARCHITECTURE.md
KNOWN_GOOD_WORKFLOWS.md
NBME_JSON_IMPORT.md
shamsulalamx_Handoff_Context_v4.md
```

Important app/runtime directories:

```text
electron/
netlify/functions/
tools/
dist/
node_modules/
```

Important tool directories:

```text
tools/nbme-pdf-json-generator/
tools/images-tables-question-generator/
tools/ome-pdf-question-generator/
tools/mehlman-pdf-question-generator/
tools/divine-audio-question-generator/
tools/anki-question-generator/
tools/uworld-notes-question-generator/
```

The primary active app implementation remains `index.html`. The repository also contains legacy split files such as `app.js`, `db.js`, `quiz.js`, `results.js`, `ocr.js`, `style.css`, `css/`, and `js/`. Do not assume those are the active runtime implementation without checking the Electron/package wiring and the actual loaded app.

## Electron Build Workflow

Current `package.json` scripts:

```json
{
  "electron:dev": "electron .",
  "electron:build:mac": "electron-builder --mac dir --arm64"
}
```

Build packaged app:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
npm run electron:build:mac
```

Open packaged app:

```bash
open dist/mac-arm64/*.app
```

Launch packaged app with remote debugging for verification:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
./dist/mac-arm64/shamsulalamx.app/Contents/MacOS/shamsulalamx --remote-debugging-port=9223
```

The Electron wrapper serves the app through a local HTTP server, not `file://`. This matters for OAuth, local assets, workers, and packaged-app behavior.

## Existing NBME PDF Pipeline

Historical workflow context: the NBME PDF generator pipeline lives at:

```text
tools/nbme-pdf-json-generator/
```

Key files:

```text
tools/nbme-pdf-json-generator/extract_pdfs.py
tools/nbme-pdf-json-generator/normalized_to_app_json.py
tools/nbme-pdf-json-generator/nbme_extract_figures.py
tools/nbme-pdf-json-generator/Generate_NBME_JSONs.command
tools/nbme-pdf-json-generator/README.md
tools/nbme-pdf-json-generator/FIGURE_EXTRACTION_README.md
tools/nbme-pdf-json-generator/schema/app_ready_schema_notes.md
```

High-level pipeline:

```text
PDF
-> raw text/OCR/chunks
-> Gemini normalized JSON
-> app-ready JSON
-> in-app NBME Gemini JSON Import
```

Relevant output folders:

```text
tools/nbme-pdf-json-generator/output_json/raw_text/
tools/nbme-pdf-json-generator/output_json/chunks/
tools/nbme-pdf-json-generator/output_json/normalized/
tools/nbme-pdf-json-generator/output_json/app_ready/
tools/nbme-pdf-json-generator/extracted_figures/
tools/nbme-pdf-json-generator/figure_manifests/
tools/nbme-pdf-json-generator/reports/
```

Gemini API keys are read from `GEMINI_API_KEY` in the environment. They are not supposed to be written to disk, printed, committed, or embedded in frontend JavaScript.

## NBME Image/Crop Workflow

Stable image/crop workflow context:

```text
v3.9-nbme-image-attach-dedupe-stable
```

Relevant app areas in `index.html`:

```text
FigureStore
q.images[]
renderImagesInto()
metadata.figureAttachments
NBME Gemini JSON Import
manual image upload
Crop/Edit workflow
ngjAttachCroppedSuggestedFigure()
```

Current stable behavior:

- The crop/edit path persists attached images through `FigureStore`.
- Rendered question images use `q.images[]`.
- Duplicate rendering is prevented when an image is already represented in `q.images[]`.
- `metadata.figureAttachments` is not the preferred long-term rendering route for the stable v3.9/v4.0 path.
- Existing manual upload and crop/edit flows must remain intact.

Do not reintroduce duplicate image rendering by putting the same screenshot in both `q.images[]` and `metadata.figureAttachments`.

## Images/Tables Generator Workflow

Latest workflow:

```text
tools/images-tables-question-generator/
```

Key files:

```text
tools/images-tables-question-generator/generate_images_tables_questions.py
tools/images-tables-question-generator/Generate_Images_Tables_JSON.command
tools/images-tables-question-generator/README.md
tools/images-tables-question-generator/.gitignore
```

Required folders are automatically created:

```text
tools/images-tables-question-generator/input_images/
tools/images-tables-question-generator/output_json/
tools/images-tables-question-generator/output_json/app_ready/
tools/images-tables-question-generator/output_assets/
tools/images-tables-question-generator/logs/
tools/images-tables-question-generator/intermediate/
```

Supported screenshot formats:

```text
.png
.jpg
.jpeg
.webp
.bmp
.tif
.tiff
```

Workflow:

1. Initialize folders.
2. User drops screenshots into `input_images/`.
3. Generator processes supported images.
4. Gemini analyzes each screenshot.
5. Generator writes per-file logs and raw Gemini responses.
6. Generator writes one combined app-ready JSON file.
7. User imports that JSON through the app.
8. App persists image data to `FigureStore`.
9. App renders the screenshot exactly once from `q.images[]`.

Current known generated JSON verified in packaged app:

```text
tools/images-tables-question-generator/output_json/app_ready/images_tables_20260520_144341_app_ready.json
```

## Exact Commands for Images/Tables Generator

Initialize:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx/tools/images-tables-question-generator
python3 generate_images_tables_questions.py --init
```

Dry run:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx/tools/images-tables-question-generator
python3 generate_images_tables_questions.py --dry-run
```

Generate:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx/tools/images-tables-question-generator
python3 generate_images_tables_questions.py --generate
```

Generate one screenshot:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx/tools/images-tables-question-generator
python3 generate_images_tables_questions.py --generate --limit 1
```

Custom input/output:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx/tools/images-tables-question-generator
python3 generate_images_tables_questions.py --generate --input-dir input_images --output-dir output_json/app_ready
```

Validate a generated file:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx/tools/images-tables-question-generator
python3 generate_images_tables_questions.py --validate-only output_json/app_ready/images_tables_20260520_144341_app_ready.json
```

JSON syntax validation:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
python3 -m json.tool tools/images-tables-question-generator/output_json/app_ready/images_tables_20260520_144341_app_ready.json > /tmp/images_tables_validated.json
```

Double-click launcher:

```text
tools/images-tables-question-generator/Generate_Images_Tables_JSON.command
```

## Gemini Key Setup

Set the Gemini key only in the shell environment:

```bash
export GEMINI_API_KEY='your-key-here'
```

Then run:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx/tools/images-tables-question-generator
python3 generate_images_tables_questions.py --generate
```

Rules:

- Do not commit the key.
- Do not put the key in `index.html`.
- Do not put the key in generated JSON.
- Do not write the key into command files, README files, logs, or screenshots.
- If `GEMINI_API_KEY` is missing, the generator should stop before calling Gemini.

## q.images[] / FigureStore Image Strategy

The v4.0 stable strategy is:

```text
q.images[] is the app-visible image reference.
FigureStore is the durable local image-data store.
metadata.figureAttachments remains empty for this generator workflow.
```

Generator behavior:

- Copies each source screenshot into `output_assets/`.
- Emits exactly one image entry in `q.images[]` per generated question.
- Temporarily embeds `dataUrl` in that image entry for import.
- Does not populate `metadata.figureAttachments`.

App import behavior:

- Landing JSON import accepts internal app-ready questions with `t`, `o`, `c`, and `q.images[]`.
- During import, the app writes each temporary `dataUrl` to `FigureStore`.
- The app assigns a stable `figureKey`.
- The app removes inline `dataUrl` from saved question objects.
- The rendered image loads from `FigureStore` through `q.images[].figureKey`.

Drive sync compatibility:

- Existing Drive image backup logic iterates `q.images[]`.
- This preserves the same image backup/restore path used by the stable crop workflow.

## Packaged App Verification Proof

Stable v4.0 verification used:

```text
Commit: 4d96496
Tag: v4.0-images-tables-generator-stable
Generated file: tools/images-tables-question-generator/output_json/app_ready/images_tables_20260520_144341_app_ready.json
Packaged app: dist/mac-arm64/shamsulalamx.app
```

Validation commands run:

```bash
git status
git log --oneline -5
python3 -m json.tool tools/images-tables-question-generator/output_json/app_ready/images_tables_20260520_144341_app_ready.json > /tmp/images_tables_validated.json
cd tools/images-tables-question-generator
python3 generate_images_tables_questions.py --validate-only output_json/app_ready/images_tables_20260520_144341_app_ready.json
cd /Users/shamsulalam/Desktop/shamsulalamx
npm run electron:build:mac
open dist/mac-arm64/*.app
```

Packaged app import/reload result:

```text
Import succeeded: yes
Generated test appeared: yes
Generated question opened: yes
Image render count before reload: 1
Visible image count before reload: 1
Image render count after reload: 1
Visible image count after reload: 1
metadata.figureAttachments: empty {}
q.images[]: present with one image entry
FigureStore: contained data for q.images[0].figureKey
Relevant runtime errors: none
```

Captured non-app warnings:

```text
Generic Chromium third-party cookie warnings from http://localhost:8888/
```

These were not import, rendering, FigureStore, or reload errors.

## Future Development Rules

Rules for future agents:

- Read current repo state before editing.
- Run `git status` and identify dirty files before touching anything.
- Do not modify app code for documentation-only requests.
- Do not commit `.claude/settings.local.json`.
- Do not call a workflow stable unless the packaged app import/reload path passes.
- Do not substitute localhost-only checks for packaged app verification.
- Do not rerun live generation unless the user asks, or unless validation shows the requested generated file is missing or invalid.
- Do not broaden scope into unrelated app rewrites.
- Preserve the current vanilla app structure unless the user explicitly authorizes a framework migration.
- Keep Electron as a thin wrapper around the HTTP-served app.
- Preserve `q.images[]` and `FigureStore` as the stable image path.
- Keep Google Drive sync behavior intact.
- Keep Gemini keys out of frontend JavaScript.
- Use source-level proof and packaged runtime verification for Electron changes.
- If a task says "Do not modify code," do not modify code unless a real runtime failure is found and the user authorizes the fix.

## What Not To Touch

Do not touch without explicit instruction:

```text
.claude/settings.local.json
deno.lock
index.html runtime logic for docs-only work
electron/main.js unless Electron behavior is the target
existing NBME Gemini JSON Import behavior
manual image upload/crop workflow
q.images[] rendering
FigureStore persistence
Google Drive sync logic
Netlify Gemini backend functions unless deployment/API work is requested
```

Do not remove or bypass:

```text
NBME JSON Import
manual image upload
Crop/Edit
renderImagesInto()
FigureStore
__nbme_local_figure__ Electron route
Drive backup/restore of q.images[]
```

Do not reintroduce:

```text
duplicate image rendering
file:// app loading
frontend Gemini API keys
manual JSON editing requirements
manual folder creation requirements for the images/tables generator
metadata.figureAttachments as a competing source of truth for generated screenshots
```

## Recovery and Rollback Commands

Inspect state:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
git status
git log --oneline -8
git tag --points-at HEAD
```

Return to latest stable checkpoint:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
git checkout main
git reset --hard v4.0-images-tables-generator-stable
```

Only run the hard reset if you intend to discard local changes. Check `git status` first.

Create a safe recovery branch from v4.0:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
git checkout -b codex/recovery-v4 v4.0-images-tables-generator-stable
```

Return to previous image-dedupe stable checkpoint:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
git checkout -b codex/recovery-v3-9 v3.9-nbme-image-attach-dedupe-stable
```

Compare current work against v4.0:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
git diff v4.0-images-tables-generator-stable
```

Rebuild packaged app after rollback:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
npm run electron:build:mac
open dist/mac-arm64/*.app
```

## Known Architecture Risks

Electron packaged behavior:

- Packaged app behavior can differ from localhost and source-level review.
- Always test the actual packaged `.app` for import, image persistence, reload, and console errors.
- The app uses an embedded HTTP server. Do not convert the app back to `file://`.

Image rendering:

- Duplicate rendering can occur if the same image is represented in more than one route.
- The v4.0 images/tables generator must use `q.images[]` only.
- `metadata.figureAttachments` must remain empty for this generator workflow.

Persistence:

- `FigureStore` stores image data in IndexedDB.
- App question objects should store lightweight image references through `figureKey`, not permanent inline base64 data.
- Drive sync depends on `q.images[]` entries with `figureKey`.

Generator schema:

- Gemini output is not trusted as final app schema.
- The generator adapts Gemini's normalized response into internal app-ready questions.
- Validator checks required fields, correct answer, one image attachment, missing assets, and duplicate attachment routes.

Security:

- `GEMINI_API_KEY` must remain server/CLI environment-only.
- Do not expose API keys in frontend code, generated files, logs, or committed configuration.

Repository state:

- `.claude/settings.local.json` is expected to be dirty locally.
- Build outputs and generated screenshots/JSON may exist locally but are not necessarily committed.
- Check `.gitignore` behavior before staging generator outputs.

## Historical Failure Points

Past failure categories to avoid:

- Treating prototype workflows as the real app workflow.
- Claiming stability from code review alone.
- Testing localhost but not packaged Electron.
- Reintroducing image duplication through both `q.images[]` and `metadata.figureAttachments`.
- Breaking the NBME JSON Import while adding a new generator path.
- Breaking manual upload/crop while changing generated-image import behavior.
- Forgetting reload persistence.
- Forgetting Drive sync compatibility.
- Assuming local absolute image paths will work in packaged app imports.
- Asking the user to manually create folders or edit JSON.
- Rerunning Gemini unnecessarily and replacing a known-good generated file.

## Quick Start for Next Agent

Start here:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
git status --short --branch
git log --oneline -5
git tag --points-at HEAD
```

Expected stable state:

```text
HEAD: 4d96496
Tag: v4.0-images-tables-generator-stable
Dirty file allowed: .claude/settings.local.json
```

If working on the images/tables workflow, validate the known generated JSON first:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
python3 -m json.tool tools/images-tables-question-generator/output_json/app_ready/images_tables_20260520_144341_app_ready.json > /tmp/images_tables_validated.json
cd tools/images-tables-question-generator
python3 generate_images_tables_questions.py --validate-only output_json/app_ready/images_tables_20260520_144341_app_ready.json
```

Then verify in the packaged app:

```bash
cd /Users/shamsulalam/Desktop/shamsulalamx
npm run electron:build:mac
open dist/mac-arm64/*.app
```

Stable success criteria:

```text
Import succeeds.
Generated test appears.
Generated question opens.
Screenshot renders exactly once.
Reload preserves exactly one screenshot.
metadata.figureAttachments remains empty.
q.images[] and FigureStore are the image source of truth.
No relevant runtime errors appear.
```
