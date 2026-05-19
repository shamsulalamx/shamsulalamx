# NBME Self-Assessment Suite — Current Features

**Last updated:** 2026-05-18  
**Purpose:** Complete inventory of all currently implemented features. Does not cover planned/deferred features — see `BUGS_AND_NEXT_STEPS.md`.

---

## Study Library

### Folder Hierarchy
- Top-level source folders → Subfolders → Tests
- Default top-level folders (order matches the landing grid):
  - NBME, UWorld, Anki, OME, Divine Podcasts, Mehlman, Images and Tables, Amboss, Emma Holiday, Fast Facts
  - Miscellaneous Documents (document storage only — no quiz engine)
  - Incorrects (dedicated folder for generated incorrects tests)
- `ensureSourceFolders()` appends missing folders to any existing install automatically on load
- Old pre-hierarchy folders are migrated under NBME by default

### Test Operations
- Create, rename, delete tests
- Mark questions, flag questions, add per-question notes
- Track: correct/incorrect/unanswered per question, time per question, total elapsed
- Score history per test (multiple attempts)
- Search across all tests and questions

---

## Quiz Engine

### Modes
- **Tutor mode:** Immediate feedback after each answer (explanation shown right away)
- **Block mode:** Deferred feedback — explanations shown only after finishing or reviewing

### Navigation
- Previous / Next buttons
- Collapsible question navigation panel
- Active question highlighted in navigation panel (improved 2026-05-18)
- Jump directly to any question number

### Answer Selection
- Single-select multiple choice (A–E; supports up to K for large choice sets)
- Shared answer choice sets (`sharedGroup.sharedChoices`) for grouped questions
- Per-question answer locking after selection in block mode

### Timers
- **Per-question timer** (`#q-timer` / `.timer-val`):
  - Shows elapsed time for the current question
  - Warning state (amber color) activates at 90-second elapsed mark
  - Warning clears automatically when navigating to the next question
- **Total test timer** (`#block-timer` / `.block-timer-display`):
  - Shows total elapsed time for the entire test
  - Module-level `_totTimerRef` — fires every 1000ms
  - Geometrically centered in the bottom bar (3-column flex layout)
  - `tabular-nums` prevents layout reflow on digit changes
  - Cross-test isolation: always cleared before a new test starts

### Focus Mode (Fullscreen)
- Toggle button in quiz chrome
- `body.quiz-fullscreen-mode` applied to body element
- `#screen-quiz`: `position:fixed; z-index:9999` — covers full viewport
- All app chrome (sidebar, top nav, landing area) hidden
- Modal dialogs correctly elevated to `z-index:10000` in focus mode
- Togglable during an active test without data loss

### Explanation and Review in Quiz
- Educational Objective block (blue-bordered)
- Correct answer explanation (`correctBlurb` — structured HTML sections)
- Per-choice rationales (A–E)
- Legacy `q.explanation` (for PDF OCR imports)
- **Pearl block** (`#q-pearl-block` — amber): shows `retrievalTag` + `reviewPearl` immediately after answering

### Other Quiz Features
- Gemini-powered hints (one per question; `callGeminiDirect` — works browser + Electron)
- Question highlighting (yellow highlighter)
- Text zoom / font-size control (stem and choices synchronized via `_applyQuestionFontSize`)
- Lab values panel (slide-in panel for reference lab values)
- Calculator
- Labs and tutor controls in bottom quiz panel

---

## Score Reports and Review

### Score Summary
- Per-question results table: Question #, Retrieval Tag, Review Pearl, Result, Time
- Total score, percent correct, time statistics
- Score history with previous attempt comparison

### Review Mode
- Review each question after the test
- Full stem, all choices, correct answer highlighted
- Pearl block (`#rev-pearl-block` — amber): `retrievalTag` + `reviewPearl` displayed below explanation
- Jump to any reviewed question

### PDF Report Generation
- jsPDF-based report
- Includes: score summary, answer choice pills, per-question explanation, `retrievalTag`, `reviewPearl`
- Educational Objective, correct blurb sections, per-choice rationales all included
- PDF layout is sensitive to font state and page breaks — do not modify jsPDF calls carelessly

---

## Flashcard System (Pearl Flashcards)

Auto-generates clinical pearl flashcards from incorrectly answered questions:
- **Source content:** `q.reviewPearl || q.explanation` for each incorrect answer
- **Trigger:** End of each test / score report display
- **Deduplication:** Content-hash based — same pearl from multiple tests stored once
- **Organization:** Source folder → test name hierarchy
- **Persistence:** Synced to Google Drive as part of Drive backup
- **Access:** Sidebar navigation → Notes section
- Added 2026-05-18; extraction and trigger bugs fixed same day

---

## Incorrects Test Generation

Generates a focused practice test from wrong answers:
- Available from score report / review mode
- Produces a new test object from all incorrect questions (or a subsection)
- Routes to the dedicated "Incorrects" folder
- User selects test name and save destination
- Appears in library immediately after save
- Added 2026-05-18; naming and destination selection refined same day

---

## Source Import Pipelines

### NBME PDF OCR
- Import NBME PDF screenshots/scans
- Tesseract.js OCR with normalization
- Grouped/shared-stem question support
- Source-number recovery (fallback to paragraph-level item numbers)
- Stem crop generation for image-based rendering
- Hybrid render mode: text for clean/grouped stems, image for figure-heavy stems

### NBME Gemini JSON Import (nbme-gemini-json)
- Import pre-structured JSON (user runs NBME exam through Gemini externally)
- Full validation: blocking errors vs warnings
- Preview all questions with full stems (no truncation) before saving
- Figure attachment panel (optional upload per figureId)
- Shared-group questions (`sharedGroup.sharedStem`, `sharedGroup.sharedChoices`)
- Lab value tables (from `tables[]` or `figureRef.visibleText`)
- Two-phase sanitizer: UI artifact removal (Phase A) + OCR separator removal (Phase B)
- Retrieval Tag and Review Pearl support (`retrievalTag`, `reviewPearl` fields)
- Validated: Psych Shelf 3–8 (300 questions), UWorld Notes (enhanced)

### UWorld DOCX
- Import UWorld DOCX export
- Normalized blocks → concept extraction → clustering → deterministic scaffolds
- One-at-a-time Gemini refinement via Electron IPC
- Batch queue with pause/cancel/retry controls
- Duplicate warnings, coverage summaries
- Review controls: approve or discard each draft
- Gemini refinement: **Electron only** (unavailable in browser)
- Tagged: `uworld-gemini-v1-stable`

### OME PDF
- Short, high-quality PDF import (PDF.js text-layer, no OCR fallback)
- Structure/block preview → concept extraction → clustering
- Deterministic draft preview, review controls
- Tagged: `ome-v1-stable`

### Anki Text Export
- Plain-text `.txt` export only (no `.apkg`)
- Normalized cards → cloze/basic concept extraction → tag-first clustering
- Deterministic variant draft preview, review controls
- Tagged: `anki-v1-stable`

### Mehlman Structured Notes
- Structured text notes (not transcripts)
- Deterministic pipeline, no Gemini in v1
- Tagged: `mehlman-v1-stable`

### Divine Podcasts
- Transcript text import (`.txt`, `.md`, `.txt.md`)
- Cleaning → segmentation → concept extraction → teaching clusters
- `clusterSummary` (≤400 chars) is the sole medical input to Gemini
- One-at-a-time Gemini refinement via Electron IPC (`nbme:ai:refine-divine-draft`)
- Anti-copy: 8-word verbatim overlap check vs `sourceContext`
- Voice-marker rejection: podcast/coaching phrases rejected from stems
- Gemini refinement: **Electron only** (unavailable in browser)
- Tagged: `divine-v1-stable`, `divine-gemini-v1-stable`

---

## Retrieval Tag and Review Pearl

High-yield metadata fields supported across all rendering surfaces:
- **`retrievalTag`:** Short searchable memory anchor (e.g., `"PTSD duration threshold"`)
- **`reviewPearl`:** One-line high-yield review statement (e.g., `"PTSD requires symptoms lasting more than 1 month after trauma."`)
- Both displayed in: score summary table, review detail panel (`#rev-pearl-block`), quiz explanation (`#q-pearl-block`), PDF report
- Stored at `q.retrievalTag` (top-level) and `q.metadata.retrievalTag` (mirrored)
- Backward compatible: pearl block hidden for questions without these fields
- Source: imported from NBME JSON (`retrievalTag`, `reviewPearl` fields), or generated via `backfill-pearls.js`

---

## Miscellaneous Documents

Document-only storage (not a quiz source):
- Supported file types: PDF, DOCX, TXT, RTF, MD, PNG, JPG, JPEG
- Upload from the landing page
- Storage: IndexedDB (`MiscDocStore`, `nbme_misc_docs_v1`)
- Organization: files organized into user-created subfolders (added 2026-05-18)
- Open: PDFs and images → new tab (blob URL); DOCX/TXT/MD/RTF → download
- Delete: per-file with confirmation
- Drive backup: saved to `NBME_MiscDocs_backup.json` (separate file in same Drive folder)

---

## Google Drive Backup and Restore

- OAuth 2.0 web client flow (no redirect URIs; GIS token flow)
- Backs up: full DB snapshot (tests, folders, history, settings), Gemini key, all images, Misc Docs
- Restores to a fresh device/browser: all data + Gemini key auto-populated
- Autosave: debounced, triggered by `DB.save()` (not called redundantly)
- Post-restore guard: prevents startup DB write from overwriting just-restored manifest
- Drive dirty-state indicator: not yet implemented (deferred)

---

## Gemini Integration

### Hints (browser + Electron)
- Per-question Gemini hints
- `callGeminiDirect()` — direct renderer fetch, works in all modes
- One hint per question; usage tracked

### Question Tagging (browser + Electron)
- `aiTagQuestions()` — bulk tag generation for untagged questions
- `callGeminiDirect()` — direct renderer fetch
- Tags saved to `q.tags[]`

### UWorld Draft Refinement (Electron only)
- `window.nbmeDesktop.ai.refineUWorldDraft(payload)` → IPC → main → Gemini
- One-at-a-time with pause/cancel controls
- Output validated before presentation to user

### Divine Draft Refinement (Electron only)
- `window.nbmeDesktop.ai.refineDivineDraft(payload)` → IPC → main → Gemini
- `clusterSummary` ≤400 chars is sole medical input
- `extractedTestableFact` and `questionType` returned explicitly
- Anti-copy + voice-marker + schema validation in main process
- Provenance assembled server-side; Gemini output never trusted for provenance

### Key storage
- Canonical: `db.settings.geminiApiKey` (persisted in `nbme_app_v1`)
- Mirror: `localStorage('nbme_gemini_key_v1')` (fast access)
- Drive sync: included in manifest `settings` block
- Export safe: `safeExportJson()` strips key from all downloads

---

## Export and Import Safety

- `safeExportJson(payload, indent)`: central export serializer; strips `_EXPORT_SENSITIVE_KEYS` (currently `{'geminiApiKey'}`) at any depth from all downloadable content
- Used in all 4 JSON export call sites: OME approved drafts, Anki approved variants, UWorld approved drafts, parser debug export
- Drive manifest path intentionally uses raw `JSON.stringify` (Drive backup is the correct sync destination for the key)

---

## What Is NOT Implemented (Deferred)

- Phase 2 pearl generation via Gemini (planned: `ipcMain.handle('nbme:ai:generate-pearls', ...)`)
- Windows Electron build (deferred — GitHub Pages may suffice for school use)
- Drive ETag/modifiedTime concurrency protection (deferred for post-exam)
- Drive dirty-state indicator / close-tab warning
- Anki Gemini refinement (no v1 Gemini)
- OME Gemini refinement (no v1 Gemini)
- Mehlman Gemini refinement (no v1 Gemini)
- `.apkg` file support (Anki)
- OCR fallback for OME (short high-quality PDFs only in v1)
- VAL-002: Figure rendering end-to-end validation (Psych_Shelf_8 Q25/Q34/Q48)
- VAL-003: "Save valid questions only" button
- VAL-004: Shared-group rendering validation (Psych_Shelf_3 Q33–Q36)
