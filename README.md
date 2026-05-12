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
| UWorld | DOCX export | Yes (Electron IPC) |
| OME | Short high-quality PDF | No (v1) |
| Anki | Plain-text `.txt` export | No (v1) |
| Mehlman | Structured text notes | No (v1) |
| Divine Podcasts | Transcript `.txt` / `.md` | Yes (Electron IPC) |

Each source pipeline is isolated. Changes to one pipeline do not affect others.

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

### Build for macOS (Apple Silicon)

```bash
npm run electron:build:mac
```

The built app appears in `dist/`.

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

- **NBME:** PDF import uses OCR. Accuracy depends on screenshot or scan quality. Grouped/shared-stem questions are supported but may require review.
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
