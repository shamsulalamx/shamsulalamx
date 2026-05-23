# NBME Self-Assessment Suite

A personal study tool for generating and reviewing NBME-style self-assessment questions from personal study materials. Runs as an Electron desktop app on Mac or as a static web app hosted on GitHub Pages — no backend required.

> **This app is review-assisted, not autonomous.** All generated question drafts require human review and approval before being saved. No content is published or exported without an explicit user action. This tool is for personal study use only.

---

## Deployment

| Mode | URL / How to run |
|---|---|
| **GitHub Pages (browser)** | https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/ |
| **Electron (Mac, dev)** | `npm run electron:dev` |
| **Electron (Mac, packaged)** | `npm run electron:build:mac` → open `dist/mac-arm64/…` |

All three modes share the same `index.html`. Electron-only features (UWorld and Divine Gemini refinement via IPC) are silently unavailable in the browser; all other features work identically.

---

## What the App Does

- Import study materials from multiple source types and generate NBME-style question drafts.
- Review, edit, approve, or discard each draft before saving.
- Optionally refine drafts with Gemini AI (your API key, your machine, no third-party server).
- Organize saved tests into a study library with folders, subfolders, notes, marks, and history.
- Take timed or untimed self-assessments with hints, answer review, and score reports.
- **Focus mode (fullscreen):** hide all app chrome during a quiz for distraction-free test-taking.
- **Per-question timer with warning:** shows elapsed time per question with a visual warning at 90 seconds.
- **Total test timer:** shows cumulative elapsed time, geometrically centered in the quiz chrome.
- **Pearl flashcards:** auto-generates clinical pearl cards from incorrectly answered questions after each test; synced to Google Drive.
- **Incorrects test generation:** generate a focused practice test from your wrong answers after any test.
- Back up and restore your library across devices via Google Drive.

---

## Supported Content Sources

| Source | Format | Gemini Refinement |
|---|---|---|
| NBME | PDF (screenshot/OCR) | No |
| NBME Gemini JSON | Pre-structured `.json` (external AI extraction) | No (JSON is already AI output) |
| Emma Holiday | Pre-structured `.json` (same workflow as NBME Gemini JSON) | No |
| Fast Facts | Pre-structured `.json` (same workflow as NBME Gemini JSON) | No |
| UWorld | DOCX export | Yes (Electron IPC only) |
| OME | Short high-quality PDF | No (v1) |
| Anki | Plain-text `.txt` export | No (v1) |
| Mehlman | Structured text notes | No (v1) |
| Divine Podcasts | Transcript `.txt` / `.md` | Yes (Electron IPC only) |

Each source pipeline is isolated. Changes to one pipeline do not affect others.

### Emma Holiday and Fast Facts

Emma Holiday and Fast Facts are top-level study library folders that use the identical JSON-import workflow as the NBME source. Import a `.json` file structured using the NBME Gemini JSON schema, run quizzes, review score reports, and access `retrievalTag` / `reviewPearl` fields exactly as with NBME tests. No new parsing logic — these folders are first-class entries in the source folder list that reuse the existing test and folder infrastructure.

---

## Miscellaneous Documents

Miscellaneous Documents is a lightweight study-file repository built into the app. It is **not** a quiz folder — there is no question generation, parsing, or quiz mode. Use it to store reference materials alongside your active tests.

**Supported file types:** PDF, DOCX, TXT, RTF, MD, PNG, JPG, JPEG

**Features:**
- Upload any supported file from the landing page
- Files are stored locally in IndexedDB (`MiscDocStore`, `nbme_misc_docs_v1`)
- Drive backup saves all docs to a separate `NBME_MiscDocs_backup.json` file in the same Drive folder as the main manifest
- Document list shows filename, file size, and upload date
- Open PDFs and images directly in a new window (blob URL — not blocked by popup blockers); download DOCX/TXT/MD/RTF files
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

Full historical technical spec: `docs/archive/NBME_JSON_IMPORT.md` (preserved for reference; current behavior is documented in `ARCHITECTURE.md` and `BATCH_IMPORT_ARCHITECTURE.md`).

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

Gemini refinement is available for the **UWorld** and **Divine Podcasts** pipelines in Electron, and for **hints** and **question tagging** in both Electron and the browser. All Gemini calls are direct from the app — no server intermediary, no Netlify functions.

**Architecture:**

- Your Gemini API key is stored in `db.settings.geminiApiKey` (the app's local database) and mirrored to `localStorage('nbme_gemini_key_v1')` for fast access. It is never committed to the repository and never included in exported test JSON files.
- Because this is a private single-user app, the key **is** included in Google Drive backups (`settings` block of the Drive manifest). Restoring from Drive on a new device automatically restores the key — no manual re-entry required.
- Hint and tagging requests (`requestHint`, `aiTagQuestions`) call the Gemini API directly from the renderer via `fetch` with an `x-goog-api-key` header. These work in both the browser and Electron.
- UWorld and Divine refinement requests go through the Electron IPC layer (`nbme:ai:refine-uworld-draft`, `nbme:ai:refine-divine-draft`), which receives the key from the renderer payload and falls back to `process.env.GEMINI_API_KEY` if absent. These are not available in the browser.

**How it works:**

- You provide your own Gemini API key in the app's Settings panel. It is saved to the app database and syncs through Google Drive to other devices.
- The app sends a sanitized, clamped summary to Gemini (never raw source text).
- Gemini returns a clinical vignette draft with five answer choices.
- The app validates the response: anti-copy checks, voice-marker rejection, schema validation, and provenance assembly all run locally before the draft is shown to you.
- If Gemini is unavailable or you skip refinement, the deterministic scaffold remains available.
- You must review and approve every draft — Gemini output is never auto-saved.

---

## Google Drive / OAuth Setup

Drive backup uses a Google OAuth 2.0 web client. The following origins must be registered in [Google Cloud Console](https://console.cloud.google.com) → **APIs & Services → Credentials** → the OAuth Client ID starting with `274374578651-`.

| Origin | Required for |
|---|---|
| `https://shamsulalamx.github.io` | GitHub Pages browser app |
| `http://localhost:8080` | Electron embedded server (fallback port) |
| `http://localhost:8888` | Electron embedded server (primary port) |

**Credential type must be Web application.** Desktop-type credentials do not support Authorized JavaScript Origins and will not work.

To add a new static hosting origin without changing app logic, add it to `DRIVE_EXTRA_ORIGINS[]` near the top of the Drive IIFE in `index.html` and register it in Google Cloud Console.

---

## Local Persistence

| Storage | Contents |
|---|---|
| `localStorage` (`nbme_app_v1`) | Test metadata, folders, marks, flags, notes, settings (including Gemini key) |
| IndexedDB (`FigureStore`) | Question stem images, figures, exhibits |
| IndexedDB (`MiscDocStore`) | Miscellaneous Documents uploads (file blobs + metadata) |
| Google Drive — main manifest | Full DB snapshot: tests, folders, history, settings, Gemini key |
| Google Drive — `NBME_MiscDocs_backup.json` | Miscellaneous Documents blobs (separate file, same Drive folder) |

Google Drive backup is optional. If connected, you can back up and restore your full library — tests, images, notes, Gemini key, and misc docs — across devices. Drive is not required to use the app.

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

1. Open the app (browser or Electron).
2. Go to **Settings**.
3. Enter your Gemini API key.
4. The key is saved to the local app database and synced through Google Drive. It is never sent to any third-party server and never committed to the repository.

---

## Stable Tagged Milestones

Current stable tag: **`v4.53-uworld-family-review-survivor-stable`**.

The full milestone log lives in `GIT_TAG_HISTORY.md`. Highlights:

| Tag | What it marks |
|---|---|
| `v4.40-phase10c-survivability-stable` | Batch Import queue survives Electron restarts (single-instance lock, filesystem-first reconciliation, durable `process_registry.json`, packaged app parity). |
| `v4.41-phase11-generation-correctness-stable` | Phase 11 generation correctness hardening. |
| `v4.44-phase11-observability-stable` | Phase 11.7 observability + unified chunk contract system. |
| `v4.47-emma-pdf-batch-import-stable` | Emma PDF batch import routing stabilization. |
| `v4.48-lecture-explanation-tables-stable` | Lecture-slide explanation panel renders structured `q.tables` / `q.metadata.tables` inline instead of the placeholder line. |
| `v4.49-lecture-chunk-recovery-stable` | Quota-aware retry stop + targeted missing-slide recovery for lecture-slide generation. Field-validated on Test_Emma: 18 allocated → 17 generated, recovery loop fired for 5 short-returning slides and recovered 4 of them. |
| `v4.50-fastfacts-review-merge-stable` | Reviewed-accepted questions merge into the same auto-imported test for the BIC job and carry the canonical `explanationSections[]` shape. Field-validated on a small Fast Facts PPTX: 1 validated + 2 reviewed-accepted = one 3-question test with full explanations on all three. |
| `v4.51-stem-quality-and-ome-live-stable` | Explicit-final-question stem-quality contract across all 6 organic generators (lecture-slide + 5 UWorld-wrapping generators) + enabled OME live generation through BIC. Field-validated on small OME PDF: questions end with proper one-best-answer question sentences, packaged auto-import succeeded. |
| `v4.52-uworld-chunk-and-token-fix-stable` | Enabled live Anki generation through BIC + fixed two long-standing bugs in the shared UWorld machinery (`split_into_chunks` not honoring its `max_chars` cap; `_raw_gemini_call` `maxOutputTokens` raised 8192 → 16384). Field-validated on 15-card Anki .txt: 15 real questions generated cleanly. Fix applies to OME, Mehlman, Divine, Anki, and UWorld. |
| `v4.53-uworld-family-review-survivor-stable` | Ports the v4.50 review-survivor flow to the UWorld-family wrappers (Anki, OME, Mehlman, Divine, UWorld). Questions that fail BOTH initial validation AND the repair retry now surface in the BIC review modal for human accept/edit/reject instead of being silently included with `extractionWarnings`. Single source change in the shared UWorld machinery — all 5 wrappers inherit the fix. Offline-validated; failure-path field validation pending an organic partial-failure run. |

Earlier source-specific tags such as `mehlman-v1-stable`, `divine-v1-stable`, `uworld-gemini-v1-stable`, `ome-v1-stable`, and `anki-v1-stable` remain as historical rollback points for their respective pipelines.

---

## Current Limitations

- **Browser (GitHub Pages):** UWorld and Divine Gemini refinement (Electron IPC) are unavailable. Drive OAuth requires the `https://shamsulalamx.github.io` origin registered in Google Cloud Console as a Web application credential (not Desktop).
- **NBME PDF:** PDF import uses OCR. Accuracy depends on screenshot or scan quality. Grouped/shared-stem questions are supported but may require review.
- **NBME Gemini JSON:** Stable. Psych Shelf 3–8 and UWorld Notes validated. Figure rendering and "save valid only" button have not been end-to-end validated. See `KNOWN_LIMITATIONS.md` for current open items and `docs/archive/BUGS_AND_NEXT_STEPS.md` for historical context.
- **UWorld:** DOCX export only. Gemini refinement is one-at-a-time; batch queue can be paused or cancelled. Electron only.
- **OME:** Short, high-quality PDFs only. No OCR fallback in v1.
- **Anki:** Plain-text `.txt` export only. `.apkg` files are not supported.
- **Mehlman:** No Gemini refinement in v1.
- **Divine:** Transcript quality affects clustering. Low-testability clusters are filtered out and not shown for review. Gemini refinement is Electron only.
- **All pipelines:** Pending broader real-world validation beyond local testing.
- The app is currently personal/private use. Security and distribution assumptions have not been reviewed for public release.

---

## Do Not

- Reintroduce Netlify functions or any server-side backend.
- Hardcode the Gemini API key anywhere in the source.
- Put the Gemini API key into exported test JSON files (use `safeExportJson()` for all downloads).
- Perform major storage migrations before the exam unless absolutely necessary.
- Implement Supabase, Firebase, or any external database.
- Refactor into React or introduce a build system without clear need.
- Move `_totTimerRef` inside `initState()` — causes cross-test timer leakage.
- Reduce `.modal-overlay` z-index below 10000 when `body.quiz-fullscreen-mode` is active — modals become invisible.
- Test against the packaged `.app` in `dist/` during development — it runs stale code from its own bundle.

---

## Disclaimers

- All question drafts are AI-assisted starting points, not verified exam content.
- You are responsible for reviewing every draft before saving it to your library.
- The app does not publish, share, or submit content anywhere without your explicit action.
- Generated questions may contain errors. Do not rely on them as authoritative medical references.
- Do not commit your Gemini API key to this repository.
