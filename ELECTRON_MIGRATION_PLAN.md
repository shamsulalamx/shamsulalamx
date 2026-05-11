# Electron Migration Plan

## Purpose

This is the active Electron migration roadmap for the NBME Self-Assessment Suite.

It is different from:

- `PROJECT_CONTEXT.md`: durable architecture/context rules.
- `PROJECT_STATUS_2026-05-08.md`: current project status and handoff snapshot.

This file should track migration stages, decisions, risks, verification checkpoints, and future migration log entries.

Ownership: this file is the staged Electron roadmap. Durable architecture rules belong in `PROJECT_CONTEXT.md`; current runtime status belongs in `PROJECT_STATUS_2026-05-08.md`; prompt files are operational/debug guidance only.

## Current Baseline

- Stable checkpoint commit: `2ba4b1d Stabilize parser/render pipeline before Electron migration`.
- Long-term target is a desktop-only Electron app.
- Current app still has browser/Netlify compatibility, but those paths are now transitional during migration.
- Electron dev scaffolding and planning have started.
- Browser/Netlify mode remains a rollback and compatibility layer until desktop-native Gemini, storage, backup/restore, and packaging paths are verified.
- UWorld DOCX pipeline is implemented inside the current app and now includes normalized blocks, concept extraction, deterministic clustering/deduplication, selected clusters, deterministic draft scaffolds, one-at-a-time Electron-local Gemini refinement, live batch queue controls, review controls, duplicate warnings, section/topic coverage summaries, preflight safeguards, approved JSON export, quiz-object preview, and controlled save into real tests.
- Electron-local UWorld Gemini refinement uses Electron main/preload. The renderer never receives the API key, and `GEMINI_API_KEY` is read from `process.env` only. Gemini JSON extraction hardened with two-attempt brace-scanning strategy (tagged uworld-gemini-v1-stable).
- UWorld v1 implementation complete, pending real-world validation.
- Anki v1 is implemented inside the current app using plain-text `.txt` imports only, cloze/basic concept extraction, tag-first clustering, deterministic variant draft preview, review controls, approved-variant JSON export, quiz-object preview, and controlled save into real tests. Approval-state and save-path bugs fixed (tagged anki-v1-stable).
- Anki v1 intentionally does not use Gemini yet.
- OME v1 is implemented inside the current app using short high-quality PDF imports only, PDF.js text-layer extraction only, structure/block preview, concept extraction, concept clustering, selected clusters, deterministic draft preview, review controls, approved-draft JSON export, quiz-object preview, and controlled save into real tests. Cluster index provenance bug fixed (tagged ome-v1-stable).
- OME v1 intentionally does not add OCR fallback and does not use Gemini yet.
- Source-level validation across NBME, UWorld, Anki, and OME passed without modifying files during validation.
- Runtime and live fixture validation remain pending.
- Live Gemini validation/testing is intentionally deferred to conserve API credits.
- Primary local origin is `http://localhost:8888`; secondary/fallback local origin is `http://localhost:8080`.
- Localhost dev loading remains intentional during migration. Packaged/local app loading should come later, after storage and service boundaries are verified.
- Early Electron work should run locally and should not require push or Netlify deploys.

## Migration Principles

- Wrap the current app first.
- Preserve browser/Netlify compatibility during transition, but do not design new long-term features around Netlify.
- Avoid rewrites initially.
- Avoid breaking the stable parser/render pipeline.
- Preserve parser/debug tooling.
- Keep NBME, UWorld, and Anki pipelines isolated from one another.
- Keep NBME, UWorld, Anki, and OME pipelines isolated from one another.
- Preserve current Google Drive behavior initially.
- Preserve Netlify/browser rollback behavior while routing Electron-local UWorld refinement through Electron main/preload.
- Avoid Netlify deploys during local Electron iteration.
- Do not expose API keys client-side.
- Do not store Gemini API keys in localStorage, renderer/frontend code, Google Drive backups, debug exports, or packaged assets.
- Keep migration steps small and reversible.
- Do not remove Netlify Functions, browser storage, Drive sync, or localhost loading until Electron-native replacements are implemented and verified.

## Staged Order Rationale

- The migration order matters because the browser app is the stable fallback and the parser/render pipeline is already fragile in known areas.
- Stabilization comes first so every later Electron change can be compared against a known-good browser baseline.
- HTTP loading comes before desktop features because Drive and Gemini depend on an HTTP/HTTPS origin, not `file://`.
- Main/preload/renderer boundary isolation comes before native helpers so privileged Electron capabilities do not leak into the renderer.
- Storage planning comes before storage migration because `localStorage`, `FigureStore`, and Google Drive currently divide metadata, image data, and backup state in a deliberate way.
- Render planning comes before render changes because grouped questions, stem crops, and shared answer banks have known duplication and ordering risks.
- Importer planning comes before new source types so PDFs, DOCX, pasted text, Anki, transcripts, and notes can normalize into a common block format instead of creating source-specific parser shortcuts.
- Debug tooling planning comes before parser rewrites so future fixes can use small focused artifacts rather than large raw exports.
- Packaging comes last because packaged builds make origin, storage, OAuth, signing, and rollback problems harder to inspect.
- Later work: narrow native helpers, app-data exports, explicit storage import/export, render-mode review UI, importer adapters, fixture runner, and packaging configuration after verification gates are defined.
- Work that should not happen prematurely: broad parser/OCR rewrites, silent stored-quiz migration, removing Netlify Functions before Electron main-process Gemini is verified, replacing Drive sync before local backup/restore is verified, exposing filesystem access to the renderer, hardcoding render behavior by question number, or packaging before dev mode is stable.

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

### Stage 6: Preserve Netlify Gemini Initially, Then Migrate To Main

- Netlify Functions remain available as a transitional/rollback layer.
- Electron-local UWorld draft refinement now uses Electron main/preload for Gemini requests.
- Keep `gemini-2.5-flash`.
- Desktop target: keep Gemini requests in the Electron main process behind narrow preload APIs.
- Main process should own API key lookup, request construction, response validation, rate/error handling, and redaction.
- Do not expose Gemini keys to renderer code, preload globals, localStorage, Drive backups, or packaged assets.
- Do not remove Netlify Functions until the Electron main-process Gemini path is implemented, verified, and rollback-safe.

### UWorld Notes Pipeline

Status: UWorld v1 implementation complete, pending real-world validation.

Current implemented flow:

```text
DOCX import
→ normalized blocks
→ concept extraction
→ deterministic clustering/deduplication
→ selected clusters
→ deterministic draft scaffolds
→ one-at-a-time Electron-local Gemini refinement
→ review controls
→ duplicate warnings and section/topic coverage summaries
→ approved draft JSON export
→ quiz-object preview
→ controlled save into real tests
```

Safeguards:

- UWorld importer and draft generation are separate from the NBME PDF parser/OCR/render pipeline.
- Concept clustering and selected-cluster controls are implemented.
- Save-to-quiz is controlled and review-gated. It requires approved refined drafts, valid quiz-object previews, an explicit save target, a nonempty test name, and review confirmation.
- No UWorld path should expose API keys, store secrets, or write Gemini prompt/debug content to Drive backups or debug exports.
- Live batch refinement is implemented as a conservative one-at-a-time queue. It reuses Electron main as the only Gemini caller, avoids duplicate refinements by draft hash, tracks explicit queue states, supports pause/cancel/retry, stops after repeated failures, and keeps save/export limited to reviewed approved outputs.
- Duplicate refined-question warnings, review filters/sorts, section/topic coverage summaries, and live-run preflight safeguards are implemented as display/review aids only. They do not auto-approve, auto-reject, auto-save, or block saving.
- Live Gemini validation/testing is intentionally deferred to conserve API credits.

Current batch queue flow:

```text
selected clusters
→ deterministic drafts
→ one-at-a-time queue
→ cache by draft hash
→ pause/cancel/retry
→ preflight confirmation
→ review-gated save
```

Remaining validation should use real imported UWorld notes and a small confirmed batch before any large run.

### Anki Notes Pipeline

Status: Anki v1 implementation complete, pending real-world validation.

Current flow:

```text
plain-text Anki export (.txt only)
→ normalized cards
→ cloze/basic concept extraction
→ tag-first clustering
→ deterministic variant draft preview
→ review controls
→ approved-variant JSON export
→ quiz-object preview
→ controlled save into real tests
```

Safeguards:

- `.apkg` is intentionally unsupported.
- Anki v1 uses deterministic logic only and does not call Gemini yet.
- Approved variants only are eligible for preview, export, and save.
- Anki save requires an explicit Anki subfolder, a nonempty test name, and an inline confirmation checkbox.
- Anki provenance is preserved separately from quiz-object preview data.
- Keep the Anki pipeline isolated from the NBME parser/OCR/render path and from the UWorld DOCX path.
- Do not migrate app data yet.

### OME Notes Pipeline

Status: OME v1 implementation complete, pending real-world validation.

Current flow:

```text
short high-quality PDF
→ PDF.js text-layer extraction only
→ structure/block preview
→ concept extraction
→ concept clustering
→ selected clusters
→ deterministic draft preview
→ review controls
→ approved-draft JSON export
→ quiz-object preview
→ controlled save into real tests
```

Safeguards:

- OME accepts short high-quality PDFs in v1.
- OME intentionally does not add OCR fallback in v1.
- OME preview uses PDF.js text-layer extraction only.
- OME structure, concept, cluster, draft, review, export, preview, and save logic stay isolated from the NBME PDF parser/OCR/render path, the UWorld DOCX path, and the Anki path.
- Approved OME drafts only are eligible for export, quiz-object preview, and controlled save.
- The OME save flow requires an explicit OME subfolder target, a nonempty test name, and an inline review confirmation.
- OME provenance stays separate from UWorld provenance and Anki provenance.
- No Gemini is used in OME v1 yet.
- OME v1 does not modify NBME parser/OCR/render behavior.

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
- Long-term desktop target: replace browser-only storage assumptions with Electron app-data as the active persistence layer after staged export/import, backup, and rollback are proven.
- Future Electron migration should be staged:
  - Add read-only export diagnostics from current browser storage.
  - Add explicit user-triggered export to local app-data JSON without changing the active save path.
  - Add explicit user-triggered import/restore from local app-data after validation and backup.
  - Move active Electron metadata writes to local JSON only after parity checks and rollback are available.
  - Migrate figure/image persistence separately from metadata, preserving `figureKey` references and Drive file IDs.
  - Keep Google Drive manifest compatibility so browser and Electron backups can coexist during transition, or until a local desktop backup replacement is verified.
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

### Future Debugging And Token-Efficiency Tooling

- Current parser debugging is local-only and exports a large JSON bundle with raw OCR output, normalized item maps, answer maps, skipped items, source-number recovery, count audits, final rendered arrays, grouped range audits, focused item traces, and full generated quiz JSON.
- Current pain points:
  - exports are large and expensive to paste into model chats
  - focused item lists are static historical examples rather than user-selected ranges
  - repeated runs are not automatically saved or comparable
  - source-number, grouped-question, and render-mode audits are embedded inside one large export
  - fixture checks are not exposed as a one-command desktop workflow
  - local logs and failed-run artifacts are not retained unless manually exported
- Future Electron-only helpers should include:
  - parser run history with immutable manifests
  - source-number audit summary exports
  - grouped-question audit summary exports
  - render-mode audit summary exports after render-mode metadata exists
  - focused debug exports by source-number range or selected item IDs
  - local logs for parse stages, warnings, errors, and user-approved corrections
  - fixture runner entrypoint with pass/fail summaries and artifact links
  - open debug folder helper through narrow preload/main IPC
- Recommended debug export structure:
  - `manifest.json`: run ID, timestamps, app checkpoint, source names/hashes, parser settings, expected counts, artifact index.
  - `summary.json`: compact stage counts, missing/duplicate source numbers, grouped range status, warning counts, and pass/fail flags.
  - `source-number-audit.json`: item-number detection by page, fallback detections, missing/duplicate numbers, displayed-to-source mapping.
  - `grouped-audit.json`: shared group IDs, expected ranges, linked item IDs, authoritative shared choices, and render-order checks.
  - `render-audit.json`: render mode, stem/image availability, duplicate-answer-bank risk, and selected display assets.
  - `focused-items/`: one small JSON file per selected item or item range with raw text, normalized text, parsed object, merged object, final object, and answer mapping.
  - `artifacts/`: OCR raw text, normalized blocks, parser snapshots, and optional redacted excerpts.
  - `logs/`: append-only local logs for the run.
- Default model-facing export should be a compact summary plus selected focused items, not the full raw export.
- Debug artifacts may contain copyrighted/private exam content and must remain local/private unless the user intentionally exports selected files.

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
- Stage 14 packaging assessment is documentation-only. Do not add packaging config until packaging is explicitly approved.
- Packaging should wait until:
  - Electron dev mode reliably loads the app from the intended HTTP origin.
  - Browser/Netlify mode remains verified.
  - PDF upload, OCR parsing, grouped-question behavior, debug exports, Drive, and Gemini have been checked in the Electron dev workflow.
  - Storage and app-data decisions are explicit enough to avoid destructive migration.
  - The app has a clear policy for local credentials, OAuth tokens, and debug artifacts.
- Future packaging approach:
  - Consider `electron-builder` or a similarly standard tool only after dev mode is stable.
  - macOS: build `.dmg` and optional `.zip`; expect Gatekeeper warnings unless signed and notarized with an Apple Developer ID.
  - Windows: build NSIS installer and optional portable `.exe`; expect SmartScreen warnings unless signed with a trusted code-signing certificate and reputation is established.
  - Portable builds are useful for private testing but should not imply durable app-data portability unless the storage path is explicitly designed.
  - Installer builds are better for normal use once app-data location, updates, and rollback behavior are defined.
- Packaging prerequisites:
  - no `file://` dependency for Drive or Gemini workflows
  - no API keys in renderer code, localStorage, Drive backups, or packaged assets
  - parser/debug artifacts remain local/private
  - local app-data path and backup strategy are documented
  - clean install, upgrade, and uninstall behavior are understood
  - package output is tested on a clean machine or clean user profile
- Do not package, sign, notarize, publish, or create installers during early migration stages.

## Architecture Decisions To Track

- Renderer/main/preload boundary.
- Local storage model.
- App-data folder structure.
- Gemini strategy.
- Google Drive strategy.
- Render-mode strategy.
- Importer/intermediate schema strategy.

## Open Decisions

- Exact credential storage mechanism for Electron main-process Gemini calls.
- Whether local storage remains JSON/local files or eventually uses SQLite.
- Whether Google Drive remains as optional sync or is replaced by local desktop backup/export.
- How Google Drive OAuth should work in Electron if Drive is retained.
- When packaged/local app loading should replace localhost dev loading.
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

### Highest Regression-Risk Areas

- Parser logic: risk of losing source items, changing source-number recovery, or collapsing generated questions. Verify raw OCR, normalized, parsed, post-merge, and final counts before changing parser code.
- OCR normalization: risk of broad spacing/token fixes corrupting valid medical text. Keep cleanup conservative, traceable, and fixture-backed.
- Grouped-question handling: risk of breaking shared instructions, shared stems, carry-forward ranges, linked item IDs, independent scoring, or `sharedGroup.sharedChoices` authority.
- Answer-choice parsing: risk of misreading quoted choices, two-column choices, OCR option letters, or shared answer banks.
- Answer/explanation alignment: risk of matching the wrong answer key item, losing explanations, or shifting answer mappings after source-number recovery.
- Render-mode selection: risk of duplicating answer banks, hiding useful parsed text, showing contaminated stem crops, or misordering grouped content.
- localStorage migration: risk of reintroducing image data into localStorage, losing metadata, corrupting saved quizzes, or silently mutating stale generated tests.
- Drive sync: risk of losing image references, overwriting Drive manifests, restoring stale data, or storing Gemini/API secrets in backups.
- Gemini calls: risk of exposing API keys, breaking Netlify Function routes, changing `gemini-2.5-flash`, or making Electron depend on a local key before strategy is approved.
- Web/desktop branching: risk of browser and Electron behavior diverging through hidden conditional paths, broad preload APIs, or premature filesystem assumptions.
- Debug tooling: risk of exposing copyrighted/private parser artifacts outside local-only workflows.
- Packaging: risk of shipping before Drive, Gemini, storage, parser/debug, and browser fallback behavior are verified.
- UWorld notes generation: risk of duplicate concepts, duplicate generated questions, weak deterministic draft scaffolds, over-trusting AI output, saving pending/rejected drafts, or modifying NBME parser/render paths while working on UWorld-only features.

## Local File Notes

- `deno.lock` remains untracked and should not be touched unless explicitly requested.

## Verification Checklist

Use lightweight checks for documentation-only stages and narrow Electron scaffolding changes. Use full regression checks before storage, parser, importer, render-mode, Drive, Gemini, packaging, or release changes.

Lightweight checks:

- Browser mode still opens from the existing local or Netlify workflow.
- Electron app opens from the project root.
- Electron loads the app over the intended localhost HTTP origin.
- Electron does not use `file://` for app loading.
- `index.html` remains authoritative and unsplit.
- Preload exposes only approved narrow APIs.
- No API keys are exposed in renderer code, localStorage, Drive backups, packaged assets, or preload.

Full regression checks:

- Browser mode still works after a refresh.
- Electron app opens and basic navigation works.
- `http://localhost:8888` or the approved local HTTP origin serves the app.
- PDF upload accepts question and answer PDFs.
- OCR/PDF extraction completes.
- Parser counts match expected source count at raw OCR, normalized, parsed, post-merge, and final stages.
- No missing source numbers.
- No duplicate source numbers or duplicate final/displayed question numbers.
- Answer-choice parsing still handles quoted choices and shared answer banks.
- Answer/explanation alignment remains correct.
- Grouped questions still preserve shared instructions, shared stems, linked ranges, authoritative `sharedGroup.sharedChoices`, independent selection, and independent scoring.
- Render behavior remains correct; later render-mode metadata must preserve text, image, and hybrid behavior without duplicating grouped answer banks.
- Debug exports work and remain local/private.
- Google Drive connect, backup, restore, image restore, and manifest behavior work from an approved HTTP/HTTPS origin.
- Gemini tagging, hints, and backend status work through Netlify Functions with `gemini-2.5-flash`.
- No unintended `file://` dependency is introduced.
- Browser and Electron behavior do not diverge except for explicitly approved desktop-only features.

Run full regression before packaging, before storage migration, after parser/OCR/render changes, after Drive/Gemini changes, and after adding native filesystem helpers.

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

### 2026-05-10

- Stage: UWorld v1 workflow completion, pending live validation.
- Change: UWorld DOCX pipeline is implemented end-to-end with deterministic clustering/deduplication, selected clusters, deterministic draft generation, single-draft Electron Gemini refinement, live one-at-a-time batch queue, review controls, duplicate warnings, review filtering/sorting, section/topic coverage summaries, preflight safeguards, approved JSON export, quiz-object preview, and controlled save into real tests.
- Verification: Source-level and syntax checks passed during implementation work. Live Gemini validation/testing is intentionally deferred to conserve API credits.
- Decision: Preserve Electron-first direction while keeping browser/Netlify rollback support. Preserve NBME parser isolation, grouped-question safeguards, and existing browser storage paths.
- Rollback notes: No OCR/PDF parser logic, grouped-question behavior, Netlify removal, app-data migration, packaging, push, or deployment is part of UWorld v1 completion.

### 2026-05-11

- Stage: Bug fixes across Anki v1, OME v1, and UWorld Electron Gemini (no new importers).
- Change: (1) Anki approval-state and save-path bugs fixed in `index.html`: `getApprovedAnkiVariantDrafts()` now calls `getApprovedAnkiDraftsFromReviewSnapshot()` directly; two `.map()` calls on the `{ ok, errors }` return value of `validateAnkiQuizObjectPreviewItem()` fixed to `.errors.map()` in the preview and save paths; temporary debug panels removed. (2) OME cluster index provenance bug fixed in `index.html`: `createOmeCluster()` now stores `clusterIndex: index` on the returned object, unblocking quiz-object preview validation and controlled save. (3) UWorld Electron Gemini JSON extraction hardened in `electron/main.js`: `extractGeminiJson()` now attempts fence-stripping parse first, then falls back to brace-depth scanning for prose-wrapped JSON; parse failures and schema validation failures return distinct `MODEL_RESPONSE_INVALID` messages with `reason` fields; no API key, prompt text, or source content appears in error messages; no auto-retry added.
- Verification: `node -c electron/main.js` syntax check passed. `git diff --check` whitespace check passed. Only `index.html` and `electron/main.js` modified; `electron/preload.js` and `deno.lock` untouched.
- Decision: Remaining work is real-world validation and eventual modularization, not new importers. `deno.lock` remains untracked.
- Rollback notes: All changes are targeted single-function fixes. NBME OCR/parser/render, UWorld renderer logic, Drive, and Netlify paths were not modified. Rollback by reverting `index.html` and `electron/main.js` to prior state if regressions appear.

### Entry Template

- Date:
- Stage:
- Change:
- Verification:
- Decision:
- Rollback notes:
