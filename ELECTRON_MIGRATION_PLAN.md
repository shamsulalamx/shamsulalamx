# Electron Migration Plan

## Purpose

This is the active Electron migration roadmap for the NBME Self-Assessment Suite.

It is different from:

- `PROJECT_CONTEXT.md`: durable architecture/context rules.
- `PROJECT_STATUS_2026-05-08.md`: current project status and handoff snapshot.

This file should track migration stages, decisions, risks, verification checkpoints, and future migration log entries.

## Current Baseline

- Stable checkpoint commit: `2ba4b1d Stabilize parser/render pipeline before Electron migration`.
- Current app is the stable browser/Netlify version.
- Electron work has not started yet.
- Browser app remains the fallback.
- Early Electron work should run locally and should not require push or Netlify deploys.

## Migration Principles

- Wrap the current app first.
- Preserve browser compatibility.
- Avoid rewrites initially.
- Avoid breaking the stable parser/render pipeline.
- Preserve parser/debug tooling.
- Preserve current Google Drive behavior initially.
- Preserve current Gemini behavior initially.
- Avoid Netlify deploys during local Electron iteration.
- Do not expose API keys client-side.
- Keep migration steps small and reversible.

## Planned Stages

### Stage 0: Confirm Stable Baseline

- Confirm working tree and checkpoint.
- Confirm browser app still runs locally.
- Confirm parser/render fixtures and debug exports still work.

### Stage 1: Add Minimal Electron Wrapper

- Add only the minimum Electron scaffolding needed for local dev mode.
- Keep existing browser app unchanged.
- Do not package yet.

### Stage 2: Load Existing `index.html` In Electron

- Load the current app as-is.
- Preserve browser/Netlify compatibility.
- Identify any assumptions that differ between browser and Electron.

### Stage 3: Add Preload/Main/Renderer Boundaries

- Define what belongs in Electron main process, preload, and renderer.
- Keep privileged APIs out of the renderer unless exposed through narrow preload bridges.

### Stage 4: Add Desktop-Mode Detection

- Add a minimal way for the app to detect Electron/desktop mode.
- Avoid changing normal browser behavior.

### Stage 5: Add Local Filesystem/Debug Helpers

- Add local-only helpers where Electron provides clear value.
- Keep parser/debug exports local and private.
- Avoid replacing existing browser debug tooling prematurely.
- Use narrow preload/main IPC only when a helper is implemented.
- Candidate future helpers: app-data path lookup, open debug folder, save debug export, and native file dialogs.
- Do not expose direct filesystem access, raw IPC wrappers, or broad Node APIs to the renderer.

### Stage 6: Preserve Netlify Gemini Initially

- Continue using current Netlify Functions path for Gemini during early Electron work.
- Keep `gemini-2.5-flash`.
- Revisit local Gemini strategy later.

### Stage 7: Preserve Or Adapt Drive Workflow

- Preserve current Google Drive backup/restore initially.
- Investigate Electron OAuth behavior before changing the flow.

### Stage 8: Add Local App-Data Structure

- Define app-data folder layout.
- Decide how local metadata, generated quizzes, parser debug artifacts, and image assets should be stored.
- Avoid destructive migration of existing browser data.
- Stage 8 is design-only until an explicit storage migration is approved.
- Proposed future layout under the Electron user data directory:
  - `quizzes/`: generated quiz metadata and question JSON.
  - `sources/`: original imported PDFs, documents, screenshots, transcripts, and other source files.
  - `ocr/raw/`: raw OCR and PDF text extraction output.
  - `ocr/normalized/`: normalized blocks before semantic parsing.
  - `parsed/questions/`: parsed question objects before quiz generation.
  - `debug/snapshots/`: focused parser/debug snapshots and export bundles.
  - `parser-runs/`: per-import run manifests, counts, warnings, and source-number audits.
  - `backups/`: local backup snapshots separate from Google Drive sync.
  - `settings/`: desktop-only settings that should not live in browser localStorage.
  - `logs/`: local application and import logs.
- Do not create these folders, move `FigureStore` images, migrate localStorage, or add filesystem IPC during Stage 8.

### Future Local Storage Migration Strategy

- Current browser storage remains authoritative until an explicit migration is approved.
- `localStorage` currently stores sanitized metadata under `nbme_app_v1`: settings, source folders, subfolders, tests, trash, flags, marks, notes, history, attempts, answers, explanations, tags, and image references.
- `FigureStore` currently stores large image data in IndexedDB database `nbme_figures_v1`, object store `figures`, keyed by figure keys referenced from question image metadata.
- Keep browser compatibility by leaving `DB.save()`, `storagePayload()`, and `FigureStore` behavior unchanged during early Electron work.
- Future Electron migration should be staged:
  - Add read-only export diagnostics from current browser storage.
  - Add explicit user-triggered export to local app-data JSON without changing the active save path.
  - Add explicit user-triggered import/restore from local app-data after validation and backup.
  - Move active Electron metadata writes to local JSON only after parity checks and rollback are available.
  - Migrate figure/image persistence separately from metadata, preserving `figureKey` references and Drive file IDs.
  - Keep Google Drive manifest compatibility so browser and Electron backups can coexist during transition.
- Do not silently mutate stored quizzes, localStorage, IndexedDB images, or Google Drive backups during any storage migration.

### Future Desktop PDF/OCR Workflow Strategy

- Current browser workflow remains authoritative: two PDF inputs, browser drag/drop, PDF.js/Tesseract extraction, OCR review, in-memory parser debug state, and local-only JSON debug download.
- Highest-friction areas to improve later in Electron:
  - repeated manual selection of question and answer PDFs
  - no folder import or batch queue
  - debug artifacts exist only as manual downloads unless saved immediately
  - OCR raw output, normalized blocks, parsed questions, and final render audits are not retained as a run history
  - failed parser runs are difficult to compare against later successful runs
  - local-only debug exports require the user to manage filenames and locations manually
- Future Electron-only improvements should be staged behind narrow preload/main helpers:
  - drag/drop PDFs using the existing browser workflow first, then add desktop file-path awareness only when needed
  - folder import for paired question/answer PDFs after a pairing convention is defined
  - batch processing with an explicit queue, per-file status, and no automatic quiz save on parse failure
  - parser snapshot history saved under `parser-runs/` and `debug/snapshots/`
  - OCR artifacts saved under `ocr/raw/`, `ocr/normalized/`, and `parsed/questions/`
  - debug export save/open-folder helpers using narrow IPC, not direct renderer filesystem access
  - local logs under `logs/` for import events, errors, counts, warnings, and user-approved corrections
- Future parser runs should be tracked with immutable run manifests containing run ID, timestamps, app version/checkpoint, source file names and hashes, parser settings, expected count, stage counts, missing/duplicate source numbers, grouped range audits, warnings, output artifact paths, and whether a quiz was saved.
- Do not change parser logic, OCR normalization, grouped rendering, or save behavior while adding run tracking.

### Future Importer Architecture

- Current PDF ingestion combines source reading, PDF text extraction, OCR fallback, normalization, page grouping, asset extraction, semantic parsing, answer merging, tagging, and debug export generation in the OCR module.
- Future importer work should introduce source adapters that normalize different input types into a common intermediate block format before semantic parsing.
- Candidate adapters:
  - PDF adapter: preserves text-layer output, OCR output, page geometry, source item numbers, stem crops, figures, and lab/table crops.
  - DOCX adapter: extracts paragraphs, headings, tables, embedded images, and source document structure.
  - Pasted text adapter: preserves paragraph breaks, user-provided section labels, and optional answer-key regions.
  - Anki adapter: maps cards, fields, tags, media references, and cloze deletions into source blocks without assuming NBME layout.
  - Audio transcript adapter: preserves timestamps, speaker labels when present, transcript segments, and source file metadata.
  - Video transcript adapter: preserves timestamps, slide/scene markers when available, transcript segments, and media references.
  - Lecture notes adapter: preserves headings, lists, tables, images, and section hierarchy.
- Recommended normalized block model:
  - `sourceId`, `sourceType`, `sourceName`, `sourceHash`
  - `blockId`, `blockType` such as `paragraph`, `heading`, `table`, `image`, `stemCrop`, `answerChoice`, `answerKey`, `transcriptSegment`, or `metadata`
  - `textRaw`, `textNormalized`, `html`, or `rows` depending on block type
  - `pageNumber`, `itemNumber`, `timestamp`, `sectionPath`, and `order`
  - `geometry` for page/canvas coordinates when available
  - `assetRefs` for images, crops, media, or extracted files
  - `confidence`, `warnings`, and `provenance` describing adapter decisions
- Importer boundary: source adapters should read files, extract raw content, normalize into blocks, preserve provenance/assets, and report confidence or warnings.
- Parser boundary: parsers should consume normalized blocks, identify questions, choices, answers, explanations, grouped ranges, tags needed for rendering, and produce structured question candidates.
- Renderer boundary: renderers should consume structured question data plus render-mode metadata, not raw importer heuristics.
- Do not implement new adapters, storage, or parser rewrites until the block schema is reviewed against existing PDF fixtures and grouped-question invariants.

### Stage 9: Design Text/Image/Hybrid Render-Mode Layer

- Define per-question render mode metadata.
- Support text mode, image mode, and hybrid mode.
- Preserve both parsed text and stem/image crops when available.
- Make render mode reviewable/editable by the user.
- Current behavior is implicit: ordinary non-grouped questions with a `stem` image hide parsed stem text and render the stem crop; grouped questions suppress `stem` images and prefer structured shared instruction, shared stem, individual stem, and one selectable answer bank.
- Future render-mode data should be per-question metadata, not hardcoded by source question number.
- Recommended future question fields:
  - `renderMode`: `text`, `image`, or `hybrid`.
  - `renderModeSource`: `auto`, `parser`, or `manual`.
  - `renderConfidence`: numeric or categorical confidence for the selected mode.
  - `renderWarnings`: non-destructive warnings such as OCR corruption, short stem, duplicated answer bank risk, missing stem crop, or layout contamination.
  - `textStem`: structured parsed stem text retained even when image mode is selected.
  - `stemImage`: reference to the selected stem crop, using existing image metadata and `figureKey`.
  - `supplementalImages`: figure, table, lab, and exhibit references that render outside the main stem.
  - `manualRenderOverride`: user-selected override with timestamp and prior mode.
- Render selection strategy:
  - `text` for clean structured stems and all grouped questions unless explicitly reviewed otherwise.
  - `image` for OCR-corrupted or layout-sensitive ordinary questions when a reliable stem crop exists.
  - `hybrid` for usable parsed text with separate figures, tables, or exhibits.
  - Grouped questions must keep shared choices authoritative and must not render a stem crop that duplicates or misorders an answer bank.
- Store both text and image evidence when available so a later user review can switch modes without reparsing.
- Do not change current rendering, grouped behavior, parser logic, or stored quiz shape until a separate implementation stage is approved.

### Stage 10: Package Later Only After Stable Dev Mode

- Package only after local Electron dev mode is stable.
- Confirm browser app remains functional before packaging.

## Architecture Decisions To Track

- Renderer/main/preload boundary.
- Local storage model.
- App-data folder structure.
- Gemini strategy.
- Google Drive strategy.
- Render-mode strategy.
- Importer/intermediate schema strategy.

## Open Decisions

- Whether Gemini stays through Netlify Functions or later moves to Electron main process with a user-provided local key or hybrid mode.
- Whether local storage remains JSON/local files or eventually uses SQLite.
- How Google Drive OAuth should work in Electron.
- How render-mode review UI should work.
- How future importers should plug into the canonical intermediate question format.

## Regression Risks

- Parser/render breakage.
- Grouped-question behavior regression.
- OCR normalization regression.
- Stale saved quizzes after parser/render changes.
- localStorage or app-data migration mistakes.
- Google Drive restore breakage.
- Gemini hints/tags breakage.
- Browser/Electron divergence.
- Messy Electron architecture from moving too much too early.

## Verification Checklist

For each stage, verify:

- Web version still works.
- Electron app opens.
- PDF upload still works.
- Parser counts match expected source count.
- Grouped questions still work.
- Debug exports still work.
- Google Drive backup/restore still works.
- Gemini hints/tags still work.
- No API keys are exposed client-side.

## Rollback Plan

- Stable checkpoint: `2ba4b1d`.
- Browser version is the fallback.
- Avoid destructive migration steps.
- Prefer branches or local checkpoints before major stages.
- If Electron changes destabilize the app, revert the Electron-specific layer first and preserve the browser app.

## Migration Log

Append future entries here.

### 2026-05-09

- Stage: 2, load existing `index.html` in Electron.
- Change: Documentation-only verification entry; no runtime or app-logic changes.
- Verification: Electron successfully loaded the existing app over `http://localhost:8888`; `file://` was not used; browser/Netlify mode still works; basic Electron interaction verification passed.
- Decision: Keep Gemini routed through Netlify Functions for now. Local Gemini verification remains intentionally skipped during early Electron migration.
- Rollback notes: No parser, render, OCR, Gemini, Drive, storage, packaging, or deployment changes were made for this verification.

### Entry Template

- Date:
- Stage:
- Change:
- Verification:
- Decision:
- Rollback notes:
