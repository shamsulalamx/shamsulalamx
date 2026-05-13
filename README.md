# NBME Self-Assessment Suite

A local Electron desktop app for generating and reviewing NBME-style self-assessment questions from personal study materials.

> **This app is review-assisted, not autonomous.** All generated question drafts require human review and approval before being saved. No content is published or exported without an explicit user action. This tool is for personal study use only.

---

## What the App Does

- Import study materials from multiple source types and generate NBME-style question drafts.
- Review, edit, approve, or discard each draft before saving.
- Optionally refine drafts with Gemini AI (local Electron path — your API key, your machine, no third-party server).
- Organize saved tests into a study library with folders, subfolders, notes, marks, and history.
- Take timed or untimed self-assessments with hints, answer review, and score reports.
- Back up and restore your library across devices via Google Drive.

---

## Supported Content Sources

| Source | Format | Gemini Refinement |
|---|---|---|
| NBME | PDF (screenshot/OCR) | No |
| NBME Gemini JSON | Pre-structured `.json` (external AI extraction) | No (JSON is already AI output) |
| Emma Holiday | Pre-structured `.json` (same workflow as NBME Gemini JSON) | No |
| Fast Facts | Pre-structured `.json` (same workflow as NBME Gemini JSON) | No |
| UWorld | DOCX export | Yes (Electron IPC) |
| OME | Short high-quality PDF | No (v1) |
| Anki | Plain-text `.txt` export | No (v1) |
| Mehlman | Structured text notes | No (v1) |
| Divine Podcasts | Transcript `.txt` / `.md` | Yes (Electron IPC) |

Each source pipeline is isolated. Changes to one pipeline do not affect others.

### Emma Holiday and Fast Facts

Emma Holiday and Fast Facts are top-level study library folders that use the identical JSON-import workflow as the NBME source. Import a `.json` file structured using the NBME Gemini JSON schema, run quizzes, review score reports, and access `retrievalTag` / `reviewPearl` fields exactly as with NBME tests. No new parsing logic — these folders are first-class entries in the source folder list that reuse the existing test and folder infrastructure.

---

## Miscellaneous Documents

Miscellaneous Documents is a lightweight study-file repository built into the app. It is **not** a quiz folder — there is no question generation, parsing, or quiz mode. Use it to store reference materials alongside your active tests.

**Supported file types:** PDF, DOCX, TXT, RTF, MD, PNG, JPG, JPEG

**Features:**
- Upload any supported file from the landing page
- Files are stored locally in IndexedDB (`MiscDocStore`, `nbme_misc_docs_v1`) — no server, no sync
- Document list shows filename, file size, and upload date
- Open PDFs and images directly in a new window; download DOCX/TXT/MD/RTF files
- Delete individual files with confirmation

**What it is not:** No quizzes, no score reports, no review mode, no Gemini integration. The existing quiz engine, report engine, review engine, and all import pipelines are completely unaffected.

---

## NBME Gemini JSON Import

The NBME Gemini JSON importer accepts a pre-structured JSON file created by running a full NBME exam through Gemini with an extraction prompt. This bypasses OCR entirely.

**Pipeline summary:**

1. Run your NBME exam through Gemini externally (outside this app) using a structured extraction prompt. Gemini returns a JSON file with all stems, choices, answer keys, educational objectives, explanation sections, and figure references.
2. In the app, open the NBME JSON Import modal.
3. Upload the JSON file. The app validates every question and shows a summary (errors, warnings, ok count).
4. Preview all questions with full stems (no truncation) before saving.
5. If any questions reference figures (`[FIGURE: figureId]` markers in the stem), a Figure Attachment panel appears. You can optionally upload an image per figure. If `visibleText` (lab values) is present in the JSON, a lab-values table renders automatically without uploading.
6. Set a test name and target folder, then save.

Questions with blocking validation errors are not saved. Questions with warnings are saved but flagged.

**Supported question types:**
- Standard 5-choice single-answer questions
- Shared-stem groups (one vignette, multiple questions — `sharedGroup.sharedStem`)
- Shared answer choice sets (`sharedGroup.sharedChoices`)
- Embedded lab tables (`tables[]` field or `figureRef.visibleText`)
- Figure references (`[FIGURE: figureId]` markers with optional image upload)

**High-yield metadata fields (optional):**
- `retrievalTag` — short searchable memory anchor encoding the exact tested concept (e.g., `"PTSD duration threshold"`, `"Clozapine ANC monitoring"`). Displayed in the score summary table, review detail panel, and PDF report.
- `reviewPearl` — one-line high-yield review statement for last-minute recall (e.g., `"PTSD requires symptoms lasting more than 1 month after trauma."`). Displayed alongside `retrievalTag` in all review surfaces.

Both fields are optional and do not affect import validation. Questions without them continue to work normally.

**Sanitizers run automatically at import time:**
- *UI artifact sanitizer* — removes NBME navigation-bar text (`Previous Next Score Report Lab Values Calculator Help Pause`) that leaks into stems or explanations via screenshot OCR.
- *OCR separator sanitizer* — removes long dash/bullet runs (`- - - -- -`), `.... Mark` bookmarks, Morse-like separator strings, and other OCR noise from explanation body text.

**Validated fixture set** (`test-data/`):

| File | Questions | Notes |
|---|---|---|
| `Psych_Shelf_3_app_ready.json` | 50 | Heavy OCR separator artifacts; 49 fields cleaned by sanitizer |
| `Psych_Shelf_4_app_ready.json` | 50 | 4 shared-stem groups |
| `Psych_Shelf_5_app_ready.json` | 50 | UI footer artifact validation (50 removed) |
| `Psych_Shelf_6_app_ready.json` | 50 | Lab tables in `tables[]` field |
| `Psych_Shelf_7_repaired_app_ready.json` | 50 | Repaired extraction |
| `Psych_Shelf_8_full_app_ready.json` | 50 | FigureRefs with lab visibleText (Q25, Q34, Q48) |

Full technical spec: `NBME_JSON_IMPORT.md`.

---

## Divine Podcast Support

The Divine pipeline imports podcast transcript text files and converts teaching content into NBME-style question drafts.

**Pipeline summary:**

1. Import a transcript (`.txt` or `.md`).
2. The app cleans the transcript — removing promotional content, filler phrases, and duplicate segments.
3. Cleaned segments are grouped into teaching clusters by medical concept.
4. Each cluster receives a concise medical summary (voice-stripped, ≤400 characters).
5. A deterministic draft scaffold is generated from the cluster — usable without Gemini.
6. Optionally, Gemini refines the draft: it reads the cluster summary, identifies the testable medical fact, and generates a clinical vignette and five answer choices.
7. You review the draft (scaffold or refined), approve or discard, then save to your library.

Raw transcript text is never sent to Gemini. The cluster summary is the sole medical input. Podcast voice, coaching language, and promotional content are stripped before any AI refinement step.

---

## Gemini-Assisted Refinement

Gemini refinement is available for the **UWorld** and **Divine Podcasts** pipelines. All Gemini calls run through the local Electron main process — your API key never leaves your machine.

**How it works:**

- You provide your own Gemini API key in the app's Settings panel.
- The app sends a sanitized, clamped summary to Gemini (never raw source text).
- Gemini returns a clinical vignette draft with five answer choices.
- The app validates the response: anti-copy checks, voice-marker rejection, schema validation, and provenance assembly all run locally before the draft is shown to you.
- If Gemini is unavailable or you skip refinement, the deterministic scaffold remains available.
- You must review and approve every draft — Gemini output is never auto-saved.

---

## Local Persistence

| Storage | Contents |
|---|---|
| `localStorage` | Test metadata, folders, marks, flags, notes, settings |
| IndexedDB (`FigureStore`) | Question stem images, figures, exhibits |
| IndexedDB (`MiscDocStore`) | Miscellaneous Documents uploads (file blobs + metadata) |
| Google Drive (optional) | Full backup and cross-device restore |

Google Drive backup is optional. If connected, you can back up and restore your full library — tests, images, notes, and history — across devices. Drive is not required to use the app.

---

## Build and Run

### Prerequisites

- [Node.js](https://nodejs.org) (for Electron)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com) (only required for AI refinement)

### Run in development

```bash
npm install
npm run electron:dev
```

> ⚠️ **Always use `npm run electron:dev` for development.** Do not test against the packaged `.app` in `dist/` — it contains its own bundled copy of `index.html` that is not updated when you edit the project source. The packaged app will silently run stale code.

### Build for macOS (Apple Silicon)

```bash
npm run electron:build:mac
```

The built app appears in `dist/`.

If you need to manually sync a fix to the packaged app without a full rebuild:
```bash
cp index.html "dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html"
```

### Gemini API key setup

1. Open the app.
2. Go to **Settings**.
3. Enter your Gemini API key.
4. The key is stored locally and used only by the Electron main process. It is never sent to any third-party server, stored in Google Drive, or committed to the repository.

---

## Stable Tagged Milestones

| Tag | Pipeline | What it marks |
|---|---|---|
| `mehlman-v1-stable` | Mehlman | Deterministic notes pipeline complete |
| `divine-v1-stable` | Divine Podcasts | Deterministic draft layer complete |
| `divine-gemini-v1-stable` | Divine Podcasts | Electron IPC Gemini refinement complete |
| `uworld-gemini-v1-stable` | UWorld | Electron IPC Gemini refinement, JSON extraction hardened |
| `ome-v1-stable` | OME | Cluster index provenance fix, pipeline complete |
| `anki-v1-stable` | Anki | Approval-state and save-path fixes, pipeline complete |

---

## Current Limitations

- **NBME PDF:** PDF import uses OCR. Accuracy depends on screenshot or scan quality. Grouped/shared-stem questions are supported but may require review.
- **NBME Gemini JSON:** Stable. All known bugs resolved as of 2026-05-12. Psych Shelf 3–8 validated. `retrievalTag` and `reviewPearl` fully supported as of 2026-05-13. Figure rendering (VAL-002) and "save valid only" button (VAL-003) have not been end-to-end validated. See `BUGS_AND_NEXT_STEPS.md`.
- **UWorld:** DOCX export only. Gemini refinement is one-at-a-time; batch queue can be paused or cancelled.
- **OME:** Short, high-quality PDFs only. No OCR fallback in v1.
- **Anki:** Plain-text `.txt` export only. `.apkg` files are not supported.
- **Mehlman:** No Gemini refinement in v1.
- **Divine:** Transcript quality affects clustering. Low-testability clusters are filtered out and not shown for review.
- **All pipelines:** Pending broader real-world validation beyond local testing.
- **Netlify Functions** exist in the codebase as a legacy rollback path. They are not the active path for Gemini refinement.
- The app is currently personal/private use. Security and distribution assumptions have not been reviewed for public release.

---

## Disclaimers

- All question drafts are AI-assisted starting points, not verified exam content.
- You are responsible for reviewing every draft before saving it to your library.
- The app does not publish, share, or submit content anywhere without your explicit action.
- Generated questions may contain errors. Do not rely on them as authoritative medical references.
- Do not commit your Gemini API key to this repository or store it in Google Drive backups.
