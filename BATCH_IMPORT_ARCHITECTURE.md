# Batch Import Center Architecture

Last updated: 2026-05-23

Current stable tag: `v4.48-lecture-explanation-tables-stable`.

Batch Import Center is the Electron/Python orchestration layer for source profiles. The Phase 10C survivability layer (tagged at v4.40) protects the queue across process restarts and filesystem inconsistencies.

## Files

- `tools/batch-import-center/pipeline_registry.json`
- `tools/batch-import-center/run_pipeline_job.py`
- `electron/main.js`
- `electron/preload.js`
- `index.html`

## Registry

The registry defines active sources:

- source label,
- supported input extensions,
- whether Gemini is required,
- whether directories are allowed,
- working directory,
- dry-run steps,
- live steps,
- output directories,
- notes.

Current registered sources:

- `emma_holiday_pdf`
- `mehlman_pdf`
- `images_tables_source`
- `anki_notes`
- `ome_pdf`
- `divine_transcript`
- `fast_facts_pptx`
- `amboss_pdf`
- `nbme_pdf`

## Job Flow

```text
renderer BIC modal
  -> window.nbmeDesktop.batchImport.launchJob()
  -> electron/main.js writes manifest
  -> run_pipeline_job.py executes registered steps
  -> progress events stream to renderer
  -> output discovery finds *_app_ready.json
  -> renderer validates/auto-imports output
  -> job history updated
```

## Native Selection

Electron main process owns native file selection.

Images & Tables uses `allowDirectories: true`, so its picker supports files and folders. Other sources use file selection unless their registry entry changes.

## Existing-Output Validation Mode

v4.13 added an existing-output mode to prove BIC auto-import wiring without rerunning live generation. It:

- skips generation,
- accepts an existing `*_app_ready.json`,
- still uses BIC launch/reporting,
- still reads output JSON through Electron,
- still validates/imports through the same renderer path.

This mode was used to separate Emma generation quality from BIC import wiring.

## Anki Registry Boundary

The active `anki_notes` registry entry is dry-run only.

- `requiresGemini` is `false` because the validated BIC path does not run live Gemini generation.
- `dryRunSteps` emit normalized chunks and app-ready dry-run output through the Anki profile runner.
- `liveSteps` are intentionally mapped to the same dry-run handoff for now. Selecting a live BIC run must not be read as live Anki Gemini validation.
- The visible BIC source option includes Anki Notes.
- The BIC modal has an optional test-name input that can override the imported app-ready title on this path.

## OME Registry Boundary

The active `ome_pdf` registry entry is dry-run only.

- `requiresGemini` is `false` because the current BIC path runs the selected-input OME dry-run handoff.
- `dryRunSteps` call the OME profile runner and request app-ready dry-run output.
- `liveSteps` intentionally map to the same dry-run handoff. This does not enable or validate live OME Gemini generation.
- Registry notes are displayed in the BIC UI, including the dry-run-only OME note.
- OME note visibility and dry-run auto-import were validated in dev Electron and packaged app.

## Divine (Audio + Transcript) Registry Boundary

The active `divine_transcript` registry entry accepts both Divine Intervention podcast audio and pre-cleaned transcripts. Live BIC generation enabled at v4.55.

- Its visible source label is "Divine (Audio + Transcript)".
- Supported inputs are `.txt`, `.md`, `.mp3`, `.m4a`, and `.wav`.
- `requiresGemini` is `true` because the live path runs Gemini for transcription, transcript cleaning, and question generation.
- `dryRunSteps` accept text inputs only and emit transcript normalized chunks plus app-ready dry-run output through the Divine profile runner. Audio inputs in dry-run mode are rejected with a clear error so transcription tokens are never wasted.
- `liveSteps` invoke the profile runner with `--emit-app-ready-live`. For audio inputs, the profile runner skips the shared chunk pipeline (no text exists yet) and delegates to `tools/divine-audio-question-generator/generate_divine_questions.py --generate --input-file <audio> --output-dir <durable>`, which uploads to the Gemini File API, transcribes, cleans, chunks, and generates questions in one process. For text inputs the live path runs the same generator without the upload/transcribe/clean stages.
- Raw and cleaned transcripts land under `<jobOutputRoot>/transcripts/raw/` and `<jobOutputRoot>/transcripts/cleaned/` (redirected via `--output-dir`, not into the packaged tree).
- App-ready output lands at `tools/shared-ingestion/output/divine_app_ready_live/<stem>/app_ready/<stem>_app_ready.json` with `schemaVersion: nbme-gemini-json-v3` and `sourceFormat: divine-audio`.
- Registry notes shown in the BIC UI document the audio/text dual support and the live-mode-required constraint for audio.
- Field-validated at v4.55 on a 17.2 MB Divine Intervention podcast MP3 (`Test Divine.mp3`, 131s total: upload → transcribe → clean → chunk → generate → 7 valid questions).

## Images & Tables Registry Boundary

The active `images_tables_source` registry entry runs live per-image Gemini classification and NBME-style question generation. Live BIC generation enabled at v4.56.

- Its visible source label is "Images & Tables".
- Supported inputs are `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, `.tiff`. `allowDirectories: true`, so the file picker accepts both individual files and folders.
- `requiresGemini` is `true`. Live mode requires `GEMINI_API_KEY` in the launched environment.
- `dryRunSteps` keep the v4.15 attachment-first stub (no Gemini, lightweight placeholder cards) as a sanity check that does not spend API tokens.
- `liveSteps` invoke the profile runner with `--mode generate`. The runner delegates each input image to `tools/images-tables-question-generator/generate_images_tables_questions.py --generate --input-file <image> --output-dir <durable_root>/app_ready`, which classifies the screenshot (`diagnostic_stem_image` / `explanation_only_image` / `explanation_only_table` / `unclear_skip`) and emits one NBME-style question with `q.images[]` for stem placements and `q.explanationImages[]` for explanation-only placements. Tables and charts are forced into the explanation panel by both the prompt and a post-classification override; a table can never appear in the stem.
- Multi-input handling: BIC iterates inputs and invokes the runner once per file. Each invocation appends its fresh per-image output (`*_per_image.json`) and rewrites a single stable-named `images_tables_combined_app_ready.json` that contains every question accumulated so far. The per-image files use the `_per_image.json` suffix so BIC's `discover_outputs` (`*_app_ready.json` glob) ignores them; only the combined file is auto-imported. By the time the last input completes, the combined file holds every generated question.
- App-ready output lands at `<jobOutputRoot>/images-tables-question-generator/app_ready/images_tables_combined_app_ready.json` with `schemaVersion: nbme-internal-app-ready-v2` and `sourceFormat: images-tables`. Per-image debug artifacts remain alongside under `_per_image.json`.
- Renderer support: `q.correctBlurb` (HTML-escaped) is the preferred explanation field; legacy plain-text `q.explanation` is rendered only when `correctBlurb` is absent (the v4.56 renderer guard prevents the duplicate-block bug when both were populated).
- Field-validated at v4.56 on a 5-image packaged-app BIC run (mixed diagnostic / explanation-only / table inputs from Step 2 fixtures): 5 questions imported in one test, correct stem/explanation placement, no duplicate explanation blocks.

## Fast Facts Registry Boundary

The active `fast_facts_pptx` registry entry has a narrow stabilization live path.

- Live Fast Facts validation currently requests diagnostic reporting.
- `--fast-facts-question-limit 3`, `--no-reuse-cache`, and `--limit 3` cap the current stabilization registry path.
- A visible Electron dev BIC live run validated output discovery, auto-import, first-question rendering, scoring, and reload persistence for one small PPTX with one final app-ready question.
- That run validated the observed Turner Syndrome screening ontology failure path only. It does not establish broad Fast Facts semantic stability, all-deck coverage, or packaged validation for this fix.
- A global renderer Gemini alert can remain out of sync with BIC batch key availability in a fresh dev profile. BIC batch success should be judged from the batch job path until that separate UI consistency issue is addressed.

## Output Discovery

The runner discovers outputs by scanning each source's registered `outputDirectories` for `*_app_ready.json` files created or touched during the run.

For existing-output validation, the explicitly selected output can be used after discovery even if the selected file sits outside the packaged app resource output directory. This is intentional for validation handoffs.

## Error Handling

Python steps emit newline-delimited JSON progress events. Non-JSON stdout is forwarded as log events. Failed steps emit `stage_failed`, then the job returns a failed `job_complete`.

Do not hide Python stderr. It often contains the only real source-specific blocker.

## Job History

Electron stores BIC job history under app `userData`, not in the repo. It is useful for local inspection but should not be treated as a source-controlled validation artifact.

## Validation Boundary

BIC proves orchestration and import path. It does not prove semantic quality. A BIC success can coexist with a weak generated question set.

## Phase 10C Survivability (v4.40)

The BIC queue survives Electron restarts, single-instance violations, and filesystem mismatches through:

- `requestSingleInstanceLock` — only one packaged or dev Electron instance owns the queue.
- Filesystem-first queue/history reconciliation on startup (`reconcileQueueAndHistoryOnStartup`).
- Queue corruption preservation — corrupt queue files are quarantined, not auto-deleted.
- Completed-job protection — historical jobs are not invalidated by spurious post-completion filesystem changes.
- Durable per-job `process_registry.json` under each `<outputRoot>`.
- Guarded process-group cleanup on cancellation.
- Startup cleanup for stale tracked runner PIDs that no longer exist.

When making any change to `electron/main.js` or `run_pipeline_job.py`, the rebuilt packaged app must retain these mechanisms. Verify by grepping the packaged `Resources/app/electron/main.js` for `requestSingleInstanceLock`, `process_registry`, and `reconcileQueueAndHistoryOnStartup`.

## Job Output Root Redirection

When BIC launches a Python pipeline, it sets `BIC_JOB_OUTPUT_ROOT=<userData>/batch-import-center/jobs/<jobId>` in the subprocess environment. The lecture-slide generator (and other source-specific generators) honor this by computing `RUNTIME_DIR = JOB_OUTPUT_ROOT / "<generator-dir>"` instead of writing into the repo. This means BIC-driven runs never pollute the source tree under `tools/<generator>/output_json/`; those locations are only used when the generator is run standalone from the CLI.
