# Batch Import Center Architecture

Last updated: 2026-05-21

Batch Import Center is the Electron/Python orchestration layer for source profiles.

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

## Divine Transcript Registry Boundary

The active `divine_transcript` registry entry is dry-run only.

- Its visible source label is Divine Transcript.
- Supported inputs are `.txt` and `.md`.
- `requiresGemini` is `false` because the validated BIC path runs the selected-input dry-run handoff.
- `dryRunSteps` emit transcript normalized chunks and app-ready dry-run output through the Divine Transcript profile runner.
- `liveSteps` intentionally map to the same dry-run handoff. This does not enable or validate live Divine Gemini generation.
- Registry notes are shown in the BIC UI, including the dry-run-only and no-audio note.
- Packaged dry-run auto-import passed for `.txt` and `.md` transcript inputs.

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
