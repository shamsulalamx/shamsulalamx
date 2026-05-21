# Runtime Architecture Audit 2026-05-21

Project root audited: `/Users/shamsulalam/Desktop/shamsulalamx`

Scope: documentation and source audit only. Runtime code was not modified. No commit was made. No tag was created. No live Gemini generation was run.

## 1. Current git state

Requested commands were run first.

```text
pwd
/Users/shamsulalam/Desktop/shamsulalamx

git branch --show-current
main

git tag --list 'v4.*' --sort=version:refname
v4.0-images-tables-generator-stable
v4.1-images-tables-placement-stable
v4.2-images-tables-schema-stable
v4.3-emma-holiday-pediatrics-stable
v4.4-fast-facts-cache-foundation
v4.5-amboss-variable-choice-stable
v4.6-batch-import-amboss-live-stable
v4.7-batch-import-gemini-env-stable
v4.8-batch-import-nbme-stable
v4.9-batch-import-orchestration-stable
v4.10-shared-ingestion-foundation
v4.11-emma-shared-ingestion-profile-stable
v4.12-mehlman-shared-ingestion-live-stable
v4.13-bic-existing-output-import-stable
v4.14-emma-normalized-chunk-downstream-stable
v4.15-images-tables-profile-stable
```

Branch: `main`.

Latest relevant v4 tag: `v4.15-images-tables-profile-stable`.

Status summary before this audit document was created:

```text
 M .claude/settings.local.json
 M ARCHITECTURE.md
 M PROJECT_CONTEXT.md
?? BATCH_IMPORT_ARCHITECTURE.md
?? GIT_TAG_HISTORY.md
?? KNOWN_LIMITATIONS.md
?? MIGRATION_HANDOFF.md
?? NEXT_STEPS_PRIORITY.md
?? PROJECT_STATUS_2026-05-21.md
?? SHARED_INGESTION_ARCHITECTURE.md
?? VALIDATED_PIPELINES.md
?? tools/lecture-slide-question-generator/output_assets/...
?? tools/shared-ingestion/output/...
?? tools/validation_samples/
```

Those modified and untracked files pre-existed this audit pass. This audit created only `docs/RUNTIME_ARCHITECTURE_AUDIT_2026-05-21.md` and the requested non-source `/tmp` JSON validation outputs. No runtime code changed.

## 2. Validated behavior vs assumptions

| behavior | evidence source | validation level | what is not proven | risk |
|---|---|---:|---|---|
| Thin Electron wrapper serves the existing vanilla app over local HTTP | `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `electron/main.js` `createWindow()` and `win.loadURL(resolvedDevUrl)` | validated | Current packaged binary was not rebuilt or launched in this audit | packaged-app-sensitive |
| Preload exposes a narrow `window.nbmeDesktop` surface | `electron/preload.js` | validated | Future preload additions remain unknown | high if widened |
| Renderer owns BIC modal, JSON validation, import, DB state, quiz state, and FigureStore persistence | `index.html` `openBatchImportCenter()`, `launchBatchImportJob()`, `validateBatchOutputJsonText()`, `importValidatedBatchOutputJsonText()`, `DB.createTest()`, `_persistLandingJsonInlineImages()` | validated by source | No live UI run in this audit | medium |
| Electron owns native dialogs and Python spawning | `electron/main.js` `select-files`, `launch-job`, `spawn()` | validated by source | Runtime behavior in a freshly rebuilt package was not tested here | packaged-app-sensitive |
| BIC writes temp manifests and runs `run_pipeline_job.py` | `electron/main.js` `writeBatchManifest()`, `BATCH_IMPORT_RUNNER` | validated by source | No job was launched in this audit | medium |
| BIC output discovery scans registered `outputDirectories` for `*_app_ready.json` | `tools/batch-import-center/run_pipeline_job.py` `discover_outputs()` | validated by source | Does not prove a particular generator produced valid semantic output | medium |
| Existing-output validation skips generation but still reads and imports app-ready JSON | `run_pipeline_job.py` `existing_output_validation`, `index.html` auto-import path | validated by source and docs | Not rerun in this audit | medium |
| Images & Tables profile preserves direct `q.images[]` and persists data URLs into FigureStore | `images_tables_profile_runner.py`, `index.html` `_persistLandingJsonInlineImages()` | validated by source and v4.15 docs | Large folders and deep semantic visual generation are not proven | medium |
| Emma shared ingestion emits normalized chunks before invoking existing lecture-slide downstream | `emma_profile_runner.py`, `pipeline_registry.json` | validated by source | Live semantic generation may fail | medium-high |
| Mehlman shared ingestion emits normalized chunks before invoking existing Mehlman downstream | `mehlman_profile_runner.py`, `pipeline_registry.json` | validated by source | Broad PDF variety and scale are not proven | medium |
| Fast Facts cache foundation exists | `GIT_TAG_HISTORY.md`, `generate_lecture_slide_questions.py` cache functions | validated for cache foundation | Semantic quality is not proven | high |
| Semantic validators can reject legitimate source vocabulary | `KNOWN_LIMITATIONS.md`, `VALIDATED_PIPELINES.md`, `generate_lecture_slide_questions.py` unsupported-term validation area | validated category | Exact current failing Emma sample was not rerun | high |
| AMBOSS, NBME, Fast Facts remain source-specific downstream paths | `pipeline_registry.json`, `generate_lecture_slide_questions.py`, `nbme_batch_wrapper.py` | inferred from source | Not all source variants are proven | medium |
| Anki, OME, Divine, UWorld BIC profiles are active | `pipeline_registry.json` placeholders | speculative if claimed | They are placeholders, not active BIC profiles | high |
| Legacy split app files are active | docs warn against legacy split files, no active evidence inspected | dead/unused if found, but not fully audited | This audit did not scan every legacy file | low-medium |
| `job_manifest.schema.json` is an enforced JSON Schema | file contains metadata/example, runner enforces checks manually | inferred not enforced | No schema validator call was found | medium |

## 3. Runtime entrypoints and ownership boundaries

Electron main responsibilities are in `electron/main.js`. It owns the app window, local HTTP app serving, native file/folder dialogs, BIC registry reads, job history under Electron `userData`, temp manifest writing, Python child process spawning, progress event forwarding, cancellation, output JSON reads, Gemini environment resolution for batch jobs, and server-side Gemini IPC used by existing UWorld/Divine workflows.

Preload responsibilities are in `electron/preload.js`. It exposes `window.nbmeDesktop` with `isElectron`, narrow AI methods, and BIC methods. The comments explicitly forbid direct filesystem access, raw IPC wrappers, broad Node APIs, and API keys.

Renderer responsibilities remain in `index.html`. The renderer owns the UI, BIC modal state, selected destination folders, app-ready JSON validation, import into DB, quiz/review/scoring state, local app state persistence, and FigureStore persistence/rendering.

Python runner responsibilities are split by layer. `tools/batch-import-center/run_pipeline_job.py` owns orchestration of registered pipeline steps and output discovery. The source-specific or profile-specific Python scripts own extraction, normalization, generation, app-ready conversion, and source reports.

BIC responsibilities are orchestration only: registry lookup, source selection, manifest creation, process execution, NDJSON progress streaming, output discovery, output reads, renderer validation/import, and job history. BIC does not validate semantic medical quality.

Shared-ingestion responsibilities are descriptor, adapter, normalized chunk schema, chunk validation, and asset routing. Shared ingestion is not a replacement importer and not a universal downstream generator.

Downstream generator responsibilities remain source-specific unless proven otherwise. Emma uses the lecture-slide generator. Mehlman uses the Mehlman generator. Images & Tables uses an attachment-first runner. NBME, AMBOSS, and Fast Facts still use existing source-specific logic.

Hard boundaries:

- Renderer must not gain raw filesystem access.
- Preload must stay narrow and method-based.
- Electron owns native dialogs and Python spawning.
- Python owns extraction/generation.
- Renderer owns import, DB state, quiz state, and FigureStore persistence.
- Gemini keys must not move into broad renderer-controlled runtime paths.

## 4. Batch Import Center call graph

The UI entrypoint is the renderer BIC modal in `index.html`.

1. User opens BIC through `openBatchImportCenter()`.
2. Renderer calls `window.nbmeDesktop.batchImport.getRegistry()`.
3. Preload maps this to `ipcRenderer.invoke('nbme:batch-import:get-registry')`.
4. Electron `ipcMain.handle('nbme:batch-import:get-registry')` returns `pipeline_registry.json`.
5. User selects files through `selectBatchImportFiles()`.
6. Renderer calls `window.nbmeDesktop.batchImport.selectFiles({ sourceType, existingOutputValidation })`.
7. Electron `select-files` uses `dialog.showOpenDialog()`. `allowDirectories` is honored only when the source allows directories and existing-output mode is off.
8. User launches a job through `launchBatchImportJob()`.
9. Renderer computes `runMode`, `dryRun`, `executePipeline`, `existingOutputValidation`, selected `inputPaths`, and destination `folderId`.
10. Renderer subscribes to `api.onProgress()`.
11. Renderer calls `window.nbmeDesktop.batchImport.launchJob()`.
12. Electron `launch-job` validates the active registry source, calls `sanitizeBatchJobPayload()`, resolves Gemini environment if needed, writes a temp manifest with `writeBatchManifest()`, and persists an initial job history record.
13. Electron spawns `python3 tools/batch-import-center/run_pipeline_job.py <manifestPath>`, or a login-shell wrapper when Gemini is only found through the shell.
14. `run_pipeline_job.py` loads the manifest and registry, calls `validate_manifest()`, `get_source()`, and `validate_inputs()`.
15. Runner captures pre-run outputs using `discover_outputs()`.
16. If `existingOutputValidation` is true, generation is skipped.
17. If `dryRun` is true and `executePipeline` is false, pipeline execution is skipped after preflight.
18. Otherwise, runner calls registered `dryRunSteps` or `liveSteps` using `run_command()`.
19. Child stdout is parsed as NDJSON progress when possible; non-JSON lines become log events.
20. Runner calls `emit_source_summary()`, rescans outputs, and emits `outputs_discovered`.
21. Runner emits `job_complete` with `outputs` and a completion report.
22. Electron forwards progress to the renderer and updates job history.
23. Renderer reads each output through `window.nbmeDesktop.batchImport.readOutputJson(outputPath)`.
24. Electron `read-output-json` accepts only paths ending in `_app_ready.json` and returns file text.
25. Renderer validates with `validateBatchOutputJsonText()`.
26. For generate-auto-import or existing-output-auto-import, renderer calls `importValidatedBatchOutputJsonText()`.
27. Import calls `DB.createTest()`, then `_persistLandingJsonInlineImages()`.
28. Renderer builds a completion report with `buildBatchImportCompletionReport()`.
29. Renderer calls `updateJobReport()` so Electron persists import status, output paths, warnings, errors, and imported test metadata.
30. Renderer refreshes BIC job history.

## 5. Job manifest contract

Manifest version: `batch-import-job-v1`.

Required fields enforced by `run_pipeline_job.py validate_manifest()`:

- `manifestVersion`
- `jobId`
- `sourceType`
- `inputs`
- `dryRun`
- `destination`

Additional fields written by Electron:

- `requiresGemini`
- `executePipeline`
- `existingOutputValidation`
- `createdAt`

`dryRun` behavior:

- `dryRun: true` with `executePipeline: false` validates manifest/registry/input and skips pipeline execution.
- `dryRun: true` with `executePipeline: true` runs registered `dryRunSteps`.
- The renderer uses dry-run mode for normal dry-run and for existing-output validation.

`executePipeline` behavior:

- Controls whether a dry-run actually executes dry-run steps.
- Live generation uses `dryRun: false`, so live steps run unless an earlier validation fails.

`existingOutputValidation` behavior:

- Forces selected inputs to `.json` and filenames ending `_app_ready.json`.
- Skips generation.
- Uses selected output paths directly even when outside registered output directories, with a warning if external.
- Sets `requiresGemini` false in `sanitizeBatchJobPayload()`.

Destination fields:

- `destination.folderId` is used by the renderer auto-import path.
- `destination.testName` is currently written but renderer often derives the import name from output `testTitle` or `name`.
- Python runner records target folder in the completion report, but does not import.

Source registry relationship:

- `sourceType` must exist under `registry.sources` and have `status: active`.
- Registry controls input extensions, directory allowance, working directory, Python executable, dry/live steps, and output directories.

What the manifest does not control:

- App-ready JSON schema.
- Semantic validator rules.
- Renderer DB shape.
- FigureStore behavior.
- Source-specific prompt behavior.
- Packaged resource path correctness beyond the selected files and registry paths.

## 6. Source registry audit

| sourceType | label | requiresGemini | input extensions | allowDirectories | workingDirectory | dryRun steps | live steps | output directories | type | validation level | known risks |
|---|---|---:|---|---:|---|---|---|---|---|---|---|
| `emma_holiday_pdf` | Emma Holiday PDF | true | `.pdf` | false | `.` | `emma_profile_runner.py --mode dry-run --limit 0` | `emma_profile_runner.py --mode generate --limit 0` | `tools/lecture-slide-question-generator/output_json/app_ready` | shared-ingestion plus existing downstream | validated profile and downstream handoff, live semantic risk remains | semantic validator may reject legitimate vocabulary such as dystocia |
| `mehlman_pdf` | Mehlman PDF | true | `.pdf` | false | `.` | `mehlman_profile_runner.py --mode dry-run --limit 10` | `mehlman_profile_runner.py --mode generate --limit 10` | `tools/mehlman-pdf-question-generator/output_json/app_ready` | shared-ingestion plus existing downstream | tagged live profile stable | source variety and scaling not fully characterized |
| `images_tables_source` | Images & Tables | false | `.png`, `.jpg`, `.jpeg`, `.webp` | true | `.` | `images_tables_profile_runner.py --mode dry-run --limit 5` | `images_tables_profile_runner.py --mode generate --limit 5` | `tools/images-tables-question-generator/output_json/app_ready` | shared-ingestion, attachment-first | v4.15 packaged validation documented | heuristic classification, no deep visual reasoning, shallow folder assumptions |
| `fast_facts_pptx` | Fast Facts PPTX | true | `.pptx` | false | `tools/lecture-slide-question-generator` | lecture generator `--fast-facts-profile --limit 10` | lecture generator `--fast-facts-profile --generate --limit 10` | `output_json/app_ready` | source-specific | cache foundation only | semantic generation unstable |
| `amboss_pdf` | AMBOSS PDF | true | `.pdf` | false | `tools/lecture-slide-question-generator` | lecture generator `--amboss-profile --limit 5` | lecture generator `--amboss-profile --limit 5` | `output_json/app_ready` | source-specific with adapter foundation | v4.6 live BIC path, v4.5 variable choices | extraction and visual-state assumptions |
| `nbme_pdf` | NBME PDF | true | `.pdf` | false | `tools/nbme-pdf-json-generator` | OCR, chunking, dry normalization, each `--max-pages 5` | OCR, chunking, normalization, app-ready, each `--max-pages 5` | `output_json/app_ready` | source-specific | v4.8/v4.9 BIC orchestration stable | OCR variability, figure linking, source-specific PDF assumptions |

Placeholders in `pipeline_registry.json`:

- `uworld_notes`: placeholder only. Existing external notes pipeline is not part of the active BIC registry.
- `anki_notes`: placeholder only. Existing wrapper pipeline is not part of the active BIC registry.
- `ome_pdf`: placeholder only. External OME generator exists separately and is intentionally not registered.
- `divine_transcript`: placeholder only. Current Divine workflow remains in-app and is not registered as a local Python pipeline.

These placeholders are not active BIC profiles.

## 7. Shared-ingestion contract

`source_descriptor.py` defines source metadata: source type, modality, extraction style, generation style, asset policy, cache policy, notes, and source metadata. Descriptors are metadata/routing intent, not importer schema forks.

`pipeline_adapter.py` maps each supported source into normalized chunks through `emit_normalized_chunks()`. Adapters are source-aware and can call existing extraction functions. They should stay thin and should not rewrite downstream generation or semantic quality logic.

`chunk_pipeline.py` runs adapter emission and `validate_chunk_bundle()`, then reports chunk counts, chunk types, image/table counts, timings, warnings, and errors.

`normalized_chunk_schema.py` defines bundle and chunk shape and validates structural requirements.

`asset_router.py` deduplicates assets, assigns stable IDs, classifies asset kind, assigns source-aware route roles, and normalizes image/table refs. This is heuristic routing, not deep visual reasoning.

Downstream generators remain source-specific unless proven otherwise. Current shared ingestion feeds existing downstream generation for Emma and Mehlman and attachment-first output for Images & Tables.

## 8. Normalized chunk schema

Bundle fields:

- `schemaVersion`
- `sourceDescriptor`
- `sourceFile`
- `sourcePath`
- `createdAt`
- `chunkCount`
- `chunks`
- `warnings`

Chunk fields:

- `schemaVersion`
- `chunkId`
- `chunkType`
- `sourceType`
- `sourceFile`
- `sourceGrounding`
- `text`
- `textBlocks`
- `imageRefs`
- `tableRefs`
- `confidence`
- `metadata`
- `warnings`

Validated chunk types:

- `text`
- `slide`
- `question`
- `transcript`
- `image`
- `table`

Validated asset kinds from docs and router behavior:

- `image`
- `table`
- `stem_image`
- `explanation_image`
- `table_image`
- `algorithm`
- `chart`
- `unknown`

Validation checks in `validate_chunk_bundle()`:

- bundle schema version equals `shared-normalized-chunk-bundle-v1`
- `chunks` is an array
- each chunk is an object
- each chunk has a nonduplicate `chunkId`
- each chunk has expected chunk schema version
- each chunk has allowed `chunkType`
- each chunk has object `sourceGrounding`
- `imageRefs`, `tableRefs`, `warnings`, and `textBlocks` are arrays
- `chunkCount` matches `chunks.length`

Schema validation does not prove medical accuracy, semantic grounding, valid app-ready import, FigureStore persistence, packaged behavior, or quiz/scoring behavior.

## 9. Profile runner handoffs

Emma:

- Input: PDF.
- Normalized chunk emission: `emma_profile_runner.py` calls `run_shared_chunk_pipeline(source_type='emma_holiday_pdf')`.
- Validation: shared chunk validation must pass before downstream call.
- Downstream call: `run_existing_emma_generator()` invokes `generate_lecture_slide_questions.py`, defaulting to `--normalized-chunks`.
- App-ready output: discovered under `tools/lecture-slide-question-generator/output_json/app_ready`.
- Provenance preserved: normalized chunk path, count, asset count, timings, warnings, and output paths in runner report.
- Validated: shared profile and normalized-chunk downstream handoff per docs/tags.
- Unvalidated: live semantic robustness, including the dystocia-style validator failure category.

Mehlman:

- Input: PDF.
- Normalized chunk emission: `mehlman_profile_runner.py` calls `run_shared_chunk_pipeline(source_type='mehlman_pdf')`.
- Validation: shared chunk validation must pass before downstream call.
- Downstream call: `run_existing_mehlman_generator()` invokes existing Mehlman generator.
- App-ready output: discovered under `tools/mehlman-pdf-question-generator/output_json/app_ready`.
- Provenance preserved: normalized chunk path, count, image/table ref counts, timings, warnings, and output paths.
- Validated: tagged shared-ingestion live profile.
- Unvalidated: broad Mehlman source variety and scaling.

Images & Tables:

- Input: image file or small image folder.
- Normalized chunk emission: `images_tables_profile_runner.py` calls `run_shared_chunk_pipeline(source_type='images_tables_source')`.
- Validation: shared chunk validation must pass.
- Downstream call: no semantic generator. It builds lightweight attachment-first app-ready cards with `build_app_ready_payload()`.
- App-ready output: written under `tools/images-tables-question-generator/output_json/app_ready`.
- Provenance preserved: normalized chunk path, source path, chunk ID, asset kind, classification summary, warnings, and image refs.
- Validated: v4.15 docs claim packaged import, FigureStore persistence, image/table rendering, scoring, and reload persistence.
- Unvalidated: advanced semantic question generation, recursive folders, large-scale asset ingestion, and deep table parsing.

## 10. Major downstream generator audit

`tools/lecture-slide-question-generator/generate_lecture_slide_questions.py`:

- CLI entrypoint: `main()`, arguments include `--input-file`, `--limit`, `--generate`, `--validate-only`, `--fast-facts-profile`, `--amboss-profile`, `--reuse-cache`, `--force-regenerate`, `--repair-only`, `--show-cache-status`, and normalized chunk support used by Emma.
- Source profiles handled: Emma/lecture slides, Fast Facts, AMBOSS.
- Deterministic stages: PPTX/PDF/image decomposition, local text extraction, some normalization, cache keying, app-ready payload assembly, validator passes.
- Gemini-dependent stages: semantic normalization/generation, Fast Facts question generation/repair, AMBOSS extraction/visual state where applicable.
- Validator behavior: `validate_app_ready_payload()`, semantic grounding functions, figure route validation, text contamination validation, Fast Facts strict findings, single-question cache validation.
- Output directories: `tools/lecture-slide-question-generator/output_json/app_ready`, plus generated/cache/report directories.
- App-ready shape: `questions[]` with internal fields such as `t`, `o`, `c`, metadata, and image arrays when applicable.
- Cache behavior: Fast Facts has cache and checkpoint functions such as `fast_facts_cache_path()`, `load_fast_facts_cache()`, `valid_fast_facts_cached_question()`, `generate_fast_facts_questions_with_cache()`, and `fast_facts_checkpoint_path()`.
- Fragile assumptions: semantic validators may be brittle, Fast Facts cache validity is not semantic stability, AMBOSS supports variable choices, and image routing differs by source.
- Shared-ingestion handoff: Emma can consume normalized chunk bundles through the profile runner; Fast Facts/AMBOSS have adapter foundations but still use source-specific downstream behavior.

`tools/mehlman-pdf-question-generator/generate_mehlman_questions.py`:

- CLI entrypoint: `main()` with Mehlman PDF generation flags inspected through source function map.
- Source profiles handled: Mehlman PDF.
- Deterministic stages: extraction/chunking, artifact handling, report writing, app-ready assembly.
- Gemini-dependent stages: live generation is Gemini-dependent.
- Validator behavior: source-specific generation and app-ready validation path before writing `*_app_ready.json`.
- Output directories: `output_json/chunks`, `output_json/generated`, `output_json/generated/debug`, `output_json/app_ready`.
- App-ready shape: produced through wrapped UWorld/app-ready builder, then Mehlman metadata is added.
- Cache behavior: no broad stable cache claim from inspected docs.
- Fragile assumptions: text-heavy PDF structure, figure/table extraction variability, first-page cap in BIC validation.
- Shared-ingestion handoff: profile runner emits normalized chunks first, then invokes this generator unchanged.

`tools/nbme-pdf-json-generator/nbme_batch_wrapper.py`:

- CLI entrypoint: `main()` with `--stage`, `--input-file`, `--max-pages`, and `--dry-run`.
- Source profiles handled: NBME PDF batch stages.
- Deterministic stages: OCR/chunk path orchestration and app-ready file path management.
- Gemini-dependent stages: normalization stage requires Gemini behavior from existing NBME generator path.
- Validator behavior: wrapper checks stage files and uses existing conversion path; BIC validates final app-ready JSON after output discovery.
- Output directories: `output_json/raw_text`, `output_json/chunks`, `output_json/normalized`, `output_json/app_ready`.
- App-ready shape: NBME app-ready output consumed by renderer import validation.
- Cache behavior: no stable shared cache claim from inspected docs.
- Fragile assumptions: OCR quality, chunking consistency, figure linking, max-page validation not proving whole-source behavior.
- Shared-ingestion handoff: NBME adapter foundation exists, but BIC uses this source-specific wrapper.

## 11. Import and persistence path

Exact BIC import path:

1. Python emits/discovers one or more `*_app_ready.json` paths.
2. Renderer receives `result.outputs`.
3. Renderer calls `api.readOutputJson(outputPath)`.
4. Electron `read-output-json` reads only files ending `_app_ready.json`.
5. Renderer calls `validateBatchOutputJsonText(read.text, outputPath)`.
6. For auto-import modes, renderer calls `importValidatedBatchOutputJsonText(firstValid.rawText, { folderId, testName })`.
7. Import distinguishes NBME Gemini JSON, internal app-ready questions, legacy app-ready test object, and bare arrays.
8. Internal app-ready questions are normalized through `_landingJsonQuestionFromInternalAppReady()`.
9. Legacy app-ready questions are normalized through `_landingJsonQuestionFromLegacyAppReady()`.
10. Import calls `DB.createTest(folderId, testName, questions)`.
11. Import calls `_persistLandingJsonInlineImages(test)`.
12. `_persistLandingJsonInlineImages()` assigns missing `figureKey` values, writes each `dataUrl` to `FigureStore.put()`, deletes `img.dataUrl`, and calls `DB.updateTest(test.id, { questions: test.questions })`.
13. `DB.save()` and app-state persistence use `storagePayload()` to strip unsafe values such as `dataUrl`, `_figureData`, `blob`, `base64`, and data-image `src`.
14. Quiz/results rendering calls `renderStoredImagesInto()`, which loads from `img.dataUrl`, `FigureStore.get(img.figureKey)`, or Google Drive fallback.
15. Reload persistence depends on IndexedDB app state, localStorage fallback, and FigureStore IndexedDB.
16. Score history persistence uses DB history saved by the app state layer; v4.15 docs validate score history after reload for Images & Tables.

Validated: source-level import path and v4.15 documented packaged validation for Images & Tables. Not validated in this audit: fresh packaged app launch, new import, quiz scoring, reload, or history inspection.

These parts must not be destabilized: `importValidatedBatchOutputJsonText()`, `_persistLandingJsonInlineImages()`, `storagePayload()`, `DB.createTest()`, `DB.updateTest()`, `FigureStore`, and `renderStoredImagesInto()`.

## 12. FigureStore lifecycle

App-ready questions may include direct image arrays:

- `q.images[]`
- `q.explanationImages[]`

Each image should have or receive a `figureKey`. During import, `_persistLandingJsonInlineImages()` persists `img.dataUrl` into IndexedDB via `window.FigureStore.put(img.figureKey, img.dataUrl)` and removes the large inline `dataUrl` from the question object. Then `DB.updateTest()` writes the lean question metadata.

`storagePayload()` is the second guard. It strips `dataUrl`, `_figureData`, `blob`, `base64`, and data-image `src` fields before app-state persistence. This keeps large base64 payloads out of localStorage and app state.

Rendering after reload works through `renderStoredImagesInto()`: if `img.dataUrl` exists it renders directly, otherwise it calls `FigureStore.get(img.figureKey)`, then falls back to Google Drive when configured.

Direct image arrays should not be replaced by `metadata.figureAttachments` unless a new path proves equivalent import, persistence, rendering, reload, and packaged behavior. Prior docs identify direct `q.images[]` and `q.explanationImages[]` as the stable route.

## 13. Fast Facts instability analysis

Fast Facts is unstable semantically.

What v4.4 validated: Fast Facts profile extraction and incremental cache foundation. The current source has extensive cache/checkpoint functions and concept graph processing.

What v4.4 did not validate: stable semantic question quality, broad generated-output correctness, packaged semantic success, or clinically reliable distractor/stem generation.

Where semantic generation quality can fail:

- `atomize_fast_facts_slide()` can split or merge facts incorrectly.
- OCR-derived image facts can be noisy.
- `dedupe_fast_facts_concepts()` can overmerge or undermerge concepts.
- Gemini generation can produce unsupported or weak medical claims.
- Repair loops can alter questions without proving clinical validity.
- Image routing metadata can be structurally valid while semantically wrong.

Where validators may reject or allow bad output:

- Strict term grounding can reject legitimate terms absent from an allowed list or normalized source text.
- Structural app-ready validation can pass medically weak questions.
- Cache validation can accept questions that fit the validator but remain clinically low quality.
- Global loosening can allow unsupported claims to pass.

Cache foundation differs from stable semantic output because a cache can preserve prior outputs and avoid repeated generation, but it does not independently prove that the cached questions are good, source-grounded, or clinically appropriate.

Repeated generation loops are dangerous because they can consume quota, hide the true source of failures, overfit prompts to one sample, and produce inconsistent outputs that appear fixed by chance. Before tuning Fast Facts, inspect concept extraction, OCR quality, concept deduplication, allowed source facts, validator failures, cache hit/miss behavior, and representative bad outputs.

Do not fix Fast Facts in this task.

## 14. Semantic validator fragility

Validators are useful for structural correctness, source-grounding checks, missing field detection, option count/label checks, figure route checks, and catching obvious hallucinated or unsupported content.

They are brittle when a legitimate medical term is absent from allowed vocabulary, when OCR/source text does not include a normalized synonym, when source style differs from the validator assumptions, or when a validator built for one source is reused globally.

Emma dystocia-style failure category: docs report live Emma generation reached downstream but failed semantic validation on Q1 for unsupported term `dystocia`. That category should be treated as semantic validator/generation fragility, not BIC wiring failure.

Global loosening is dangerous because it can allow unsupported content across multiple sources. Source-specific hardening would require the failing source sample, expected legitimate terms, negative controls with unsupported claims, before/after validator reports, and app-ready validation without weakening other profiles.

Negative controls needed:

- unsupported medical terms not present in source,
- altered thresholds or doses,
- swapped correct answer and distractor,
- hallucinated diagnosis not grounded in source,
- invalid image/table route,
- legitimate synonym that should pass for that source.

## 15. Fragile paths and forbidden casual changes

Do not casually change:

- `index.html` app-ready import behavior.
- `index.html` `importValidatedBatchOutputJsonText()`.
- `index.html` `validateBatchOutputJsonText()`.
- `index.html` `_persistLandingJsonInlineImages()`.
- `index.html` `storagePayload()`, `DB.save()`, `DB.createTest()`, and `DB.updateTest()` behavior.
- `index.html` `FigureStore` and `renderStoredImagesInto()`.
- BIC manifest shape in `electron/main.js` and `run_pipeline_job.py`.
- BIC output discovery in `run_pipeline_job.py discover_outputs()`.
- `electron/preload.js` API surface.
- Electron security boundaries: `contextIsolation: true`, no raw Node exposure, no broad IPC.
- Existing source-specific downstream generators.
- Gemini semantic validators and repair loops.
- Fast Facts semantic generation and cache validation.
- Packaged resource path assumptions using `app.getAppPath()`.
- `pipeline_registry.json` `workingDirectory` and `outputDirectories` without packaged validation.

## 16. Safe extension points

Potentially safe if validated:

- Add a new descriptor in `source_descriptor.py`. Required validation: descriptor can be loaded and does not imply importer schema changes.
- Add a thin adapter in `pipeline_adapter.py`. Required validation: emits valid normalized chunks from a small sample and preserves provenance.
- Add a profile runner. Required validation: dry-run, normalized chunks, downstream handoff, report, failure behavior.
- Add a registry entry. Required validation: BIC dry-run, BIC generate, output discovery, existing-output mode if applicable.
- Add source-specific validation tests. Required validation: positive samples and negative controls.
- Add existing-output validation fixtures. Required validation: renderer validation, auto-import, DB save, and report update.
- Add docs. Required validation: source references are current and claims distinguish validated from inferred.

## 17. Packaged app validation requirements

Before claiming success for UI, assets, persistence, Electron, or BIC behavior:

1. Rebuild the packaged app.
2. Kill stale packaged app processes.
3. Launch the packaged binary.
4. Run the BIC path if BIC is involved.
5. Auto-import if import is claimed.
6. Confirm question count and destination folder.
7. Score a quiz.
8. Reload the app.
9. Verify FigureStore/rendering if assets are involved.
10. Verify score history persistence.
11. Verify job history if BIC is involved.

Source-level success alone is not enough for packaged-app-sensitive claims.

## 18. Source convergence roadmap with risk

Anki:

- Likely entrypoint: new descriptor, thin structured-note adapter, profile runner, registry entry only after validation.
- Safest first validation sample: small known deck/export with a few simple cards.
- Primary risks: breaking existing Anki wrapper behavior, approval-state mismatch, overfitting card fields.
- What not to touch: existing importer and DB save path.
- Packaged validation need: required if BIC/UI import is claimed.

OME:

- Likely entrypoint: descriptor plus PDF adapter using existing OME tooling.
- Safest first validation sample: short PDF excerpt with text-only pages.
- Primary risks: PDF text extraction variability, figure/table assumptions.
- What not to touch: NBME or Mehlman generator logic.
- Packaged validation need: required for BIC/import claims.

Divine transcript/audio:

- Likely entrypoint: transcript descriptor and text/transcript adapter before any audio expansion.
- Safest first validation sample: one cleaned transcript excerpt.
- Primary risks: transcript cleanup, source-sensitive semantic refinement, prompt drift.
- What not to touch: existing Divine in-app draft/refinement boundary unless explicitly requested.
- Packaged validation need: required if renderer workflow, persistence, or Electron IPC changes.

UWorld notes:

- Likely entrypoint: notes descriptor and adapter that preserves raw concepts, representatives, clusters, drafts.
- Safest first validation sample: small notes file with known concepts.
- Primary risks: concept overmerge, save readiness regression, AI refinement changes.
- What not to touch: deterministic save flow and approved-draft save behavior.
- Packaged validation need: required if UI/save path changes.

Semantic validator hardening:

- Likely entrypoint: source-specific validator tests and narrow source validator changes.
- Safest first validation sample: known failing Emma term plus negative controls.
- Primary risks: global loosening.
- What not to touch: global validators without source-specific tests.
- Packaged validation need: not always required for pure validator unit/source tests, required if import/runtime changes follow.

Multimodal grounding:

- Likely entrypoint: Images & Tables asset metadata and validation fixtures.
- Safest first validation sample: 2-5 curated images/tables with expected labels.
- Primary risks: visual hallucination and OCR noise.
- What not to touch: attachment-first stable route.
- Packaged validation need: required for image rendering/persistence claims.

Table parsing:

- Likely entrypoint: table-specific asset metadata and parser fixture.
- Safest first validation sample: one simple table with known rows/columns.
- Primary risks: OCR corrupting rows, false confidence.
- What not to touch: table image preservation.
- Packaged validation need: required if rendered/imported output changes.

Scalable asset caching:

- Likely entrypoint: source-hash asset cache index.
- Safest first validation sample: two runs with one changed asset.
- Primary risks: stale cache hits and path mismatches in packaged app.
- What not to touch: FigureStore persistence path.
- Packaged validation need: required.

Shared downstream reuse:

- Likely entrypoint: one source at a time with equivalence fixtures.
- Safest first validation sample: validated Emma or Images & Tables fixture.
- Primary risks: premature abstraction breaking source-specific stable behavior.
- What not to touch: existing generators until output equivalence or improvement is proven.
- Packaged validation need: required for any claimed end-to-end replacement.

## 19. Exact unanswered questions

- The audit did not rebuild or launch the packaged app.
- The audit did not run BIC jobs.
- The audit did not run live Gemini generation.
- The audit did not verify current IndexedDB/localStorage contents.
- The audit did not inspect every legacy or unrelated workflow outside the requested files.
- The audit did not prove that `job_manifest.schema.json` is consumed by a schema validator. Source inspection found manual validation in `run_pipeline_job.py`.
- The audit did not prove current Fast Facts semantic quality.
- The audit did not prove large-folder Images & Tables scaling.
- The audit did not prove broad Mehlman, Emma, NBME, AMBOSS, OME, Anki, Divine, or UWorld source coverage.

## 20. Final rules for future prompts

Every future Codex implementation prompt should follow this checklist:

1. Read current docs and source first.
2. Identify the validated path before editing.
3. Identify the fragile path before editing.
4. Make the smallest source-aware change.
5. Validate source-level output.
6. Validate normalized chunks when shared ingestion is involved.
7. Validate app-ready JSON.
8. Validate BIC dry-run/generate/import when BIC is involved.
9. Validate packaged app when UI, assets, persistence, Electron, or BIC behavior is involved.
10. Do not tag until validation is complete.
11. Separate semantic quality failures from orchestration failures.
12. Do not turn placeholders into active profiles without a small validated sample.
13. Do not replace direct image arrays and FigureStore persistence unless the replacement proves import, rendering, reload, and packaged behavior.
14. Do not globally loosen semantic validators without source-specific positive and negative controls.

## Addendum: Anki Dry-Run BIC Milestone

After this audit was written, the Anki dry-run BIC milestone was validated.

Validated evidence now includes:

- shared-ingestion normalized Anki text chunks,
- selected-input dry-run handoff from `anki_profile_runner.py` into the existing Anki wrapper,
- BIC registry execution,
- visible dev Electron UI auto-import,
- optional BIC test-name input on the validated import path,
- renderer import and DB persistence,
- quiz rendering and reload persistence,
- visible packaged app UI auto-import,
- packaged auto-import and score history persistence.

This addendum records a dry-run milestone only. Live Gemini Anki generation, real semantic Anki question quality, broad real-world Anki export variation, and non-Anki regression testing after the Anki UI additions remain unvalidated.

## Addendum: OME Dry-Run BIC Milestone

After the original audit and the Anki addendum, the OME dry-run BIC milestone was validated.

Validated evidence now includes:

- shared-ingestion normalized OME text chunks from the tracked synthetic fixture,
- selected-input dry-run handoff through the existing OME generator,
- `ome_profile_runner.py --emit-app-ready-dry-run`,
- active BIC registry orchestration and output discovery,
- visible dev Electron BIC auto-import and dry-run-only registry note display,
- visible packaged app BIC auto-import from a clean temporary profile,
- quiz rendering, reload persistence, and score history persistence after reload.

This addendum records a dry-run milestone only. Live Gemini OME generation, any live OME BIC path, real semantic OME question quality, broad real OME PDF coverage, signed or notarized distribution behavior, and non-writable packaged resource tree behavior remain unvalidated. Packaged OME output currently writes under packaged resources; moving generated output to a writable app-data directory remains a future task.
