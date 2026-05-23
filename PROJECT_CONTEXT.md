# NBME Self-Assessment Suite — Project Context

**Last updated:** 2026-05-23
**Current stable tag:** `v4.48-lecture-explanation-tables-stable`
**Current branch:** `phase11-fastfacts-stability`
**Supersedes:** Previous PROJECT_CONTEXT.md (pre-2026-05-19 versions — stale, contained references to Netlify, old architecture, unresolved bugs since fixed)
**Purpose:** Durable architectural rules and constraints for any session resuming work here. Read this first, then `PROJECT_STATUS_2026-05-23.md`, `ARCHITECTURE.md`, `BATCH_IMPORT_ARCHITECTURE.md`, `KNOWN_LIMITATIONS.md`, `NEXT_STEPS_PRIORITY.md`, and `MIGRATION_HANDOFF.md`.

---

## 1. App Purpose

A personal study tool for NBME medical board exam preparation (Step 2 CK / Shelf exams). The app:

- Imports questions from multiple sources (NBME PDFs via Gemini extraction, UWorld DOCX, OME PDFs, Anki exports, Divine podcast transcripts, Mehlman notes)
- Runs timed or untimed self-assessments with tutor/block mode
- Generates score reports with explanations, retrieval tags, and review pearls
- Creates flashcards from incorrect answers
- Generates targeted re-practice tests from wrong answers
- Backs up and restores all user data via Google Drive

**This is a private, personal-use tool.** Gemini API keys are user-provided and stored locally. No server. No backend database.

---

## 2. Source of Truth

```
index.html
```

The entire app — all HTML, CSS, JavaScript — is inline in this one file (~21,700+ lines, May 2026). No external local JS or CSS files. No build system. No transpiler.

**Every edit goes in `index.html`.** The legacy split files (`app.js`, `db.js`, `ocr.js`, `quiz.js`, `results.js`, `style.css`, `css/`, `js/`) are NOT the active implementation. They may exist as historical artifacts. Do not edit them.

---

## 3. Localhost Workflow

### Development — ALWAYS use this

```bash
cd "/Users/shamsulalam/Desktop/shamsulalamx"
npm run electron:dev
```

Electron starts and serves `index.html` via an embedded HTTP server at `http://127.0.0.1:8888` (fallback port 8080). Edits to `index.html` are reflected immediately on `Cmd+R` reload.

### GitHub Pages (browser, no Electron IPC)

```
https://shamsulalamx.dpdns.org    (CNAME)
```

Served from the `main` branch. UWorld and Divine Gemini refinement are unavailable (Electron IPC only). All other features work.

### Packaged App — NEVER USE FOR DEVELOPMENT

```
dist/mac-arm64/shamsulalamx.app/Contents/Resources/app/index.html
```

This bundle is a frozen copy. Edits to the project root `index.html` are **invisible** to the packaged app. Using it caused multiple wasted debugging sessions.

---

## 4. Canonical Schema

All question sources are normalized into one of two JSON schemas before app import:

| Schema version | Used by | Key fields |
|---|---|---|
| `nbme-gemini-json-v1` | NBME PDF extractor (`tools/nbme-pdf-json-generator/`) | `n`, `t`, `o[{l,t}]`, `c`, `e`, `tags`, `retrievalTag`, `reviewPearl`, `educationalObjective`, `correctBlurb`, `metadata` |
| `nbme-gemini-json-v3` | UWorld notes generator, Anki generator | Same fields + `answerChoices[{label,text}]`, `explanationSections`, `clinicalPearl` |

The app's NBME Gemini JSON importer (`validateNbmeGeminiJsonImport` + `normalizeNbmeGeminiJsonImport` in `index.html`) accepts both schema versions and maps them into the internal quiz object (`q.t`, `q.o`, `q.c`, `q.e`, `q.tags`, `q.retrievalTag`, `q.reviewPearl`, `q.educationalObjective`, `q.correctBlurb`, `q.metadata`).

**Do not create schema forks.** Any new pipeline must output one of these two schema versions.

---

## 5. Importer Architecture

The app contains two distinct layers:

### A. External tool pipelines (`tools/`)

Three standalone Python scripts that run outside the app to convert source material into app-ready JSON:

| Tool | Input | Output schema |
|---|---|---|
| `tools/nbme-pdf-json-generator/` | NBME PDF files | `nbme-gemini-json-v1` |
| `tools/uworld-notes-question-generator/` | Notes files (.txt/.md/.docx) | `nbme-gemini-json-v3` |
| `tools/anki-question-generator/` | Anki export .txt | `nbme-gemini-json-v3` |

These tools produce `*_app_ready.json` files that are then imported into the app via the in-app NBME Gemini JSON importer.

### B. In-app import pipelines (`index.html`)

Seven import types handled inside the app, each with its own parse→validate→preview→confirm→save flow:

| Pipeline | Input | Gemini in-app |
|---|---|---|
| NBME PDF OCR | Scanned PDF | Hints + tagging only (`callGeminiDirect`) |
| NBME Gemini JSON | `*_app_ready.json` from external tools | None |
| UWorld DOCX | DOCX export | Electron IPC only |
| OME PDF | Short PDF | None in v1 |
| Anki text | Plain .txt | None in v1 |
| Divine Podcasts | Transcript text | Electron IPC only |
| Mehlman | Structured notes | None in v1 |

All pipelines share:
- Save gate: approved → preview → explicit target folder → name → confirm
- `safeExportJson()` on all downloadable outputs (strips `geminiApiKey` at any depth)
- No auto-save of unapproved AI output

---

## 6. Stable Pipelines (as of 2026-05-19)

All three external tool pipelines are stable and working:
- NBME PDF pipeline: Psych Shelf 3–8 (300 questions) validated
- UWorld notes pipeline: Psych notes validated
- Anki pipeline: validated (wraps UWorld pipeline)

All seven in-app pipelines are stable. No unresolved bugs.

---

## 7. Core Philosophy

### Deterministic extraction first, Gemini reasoning second

Every pipeline follows this two-step structure:

1. **Deterministic layer:** Parse source content, build structure (chunks/clusters), validate schema, manage provenance, handle errors. This layer works entirely without Gemini.

2. **Gemini layer:** Applied only to the structured output of the deterministic layer. Gemini identifies testable facts, generates clinical vignettes, or refines drafts. Gemini **never** manages provenance, schema, or save targets. All Gemini output is validated by the deterministic layer before use.

**Why this matters:** Broad OCR normalization rules and loosely coupled Gemini calls caused instability in earlier versions. The current architecture is stable because deterministic structure is established before Gemini is invoked.

### No schema forks

All sources flow into the same `nbme-gemini-json-v*` schema. The app's single importer handles all variants. Do not build a new importer or a new schema variant.

### No duplicate Gemini clients

There is one Gemini HTTP client pattern (raw `urllib.request.Request` in Python tools; `callGeminiDirect()` direct fetch in renderer; Electron IPC for UWorld/Divine). Do not create new Gemini client implementations. Reuse existing patterns.

### Infrastructure reuse

New pipelines (like the planned OME external tool) must reuse:
- The UWorld generator's Gemini client, `_clean_llm_json()`, `_extract_json_payload()`, `_parse_gemini_json()`, validation, retry/repair flow
- The existing NBME Gemini JSON importer in the app
- The existing `nbme-gemini-json-v*` schema

---

## 8. Key Architectural Invariants (Do Not Violate)

1. **`index.html` is the authoritative source.** All edits go here.
2. **`_totTimerRef` is module-level in the Quiz IIFE.** Never move inside `initState()` — causes cross-test timer leakage.
3. **`.modal-overlay` z-index ≥ 10000 when `body.quiz-fullscreen-mode` is active.** Never reduce — modals go invisible behind fullscreen screen.
4. **`safeExportJson()` on all user-downloadable content.** Never use raw `JSON.stringify` for downloads.
5. **Gemini key never in `process.env` reads inside renderer.** Only `electron/main.js` reads `process.env.GEMINI_API_KEY`.
6. **`DB.save()` is the sole Drive sync scheduler.** Never call `scheduleGoogleDriveSave()` after `DB.save()`.
7. **`callGeminiDirect()` for hints/tagging.** Works in browser + Electron. Do not route through Netlify.
8. **Netlify Functions are dead code.** They remain in `netlify/` as rollback reference. Not called anywhere.
9. **Figure attachment key:** `fr.id || fr.figureId` — both key names must be checked (some records use one, some the other). Fixing this was required for figure uploads to work.
10. **`_isLabPara()` guards must not be removed.** Both the length guard (`> 400`) and the question-mark guard (`/\?/.test(para)`) prevent clinical vignettes from being misclassified as lab-value table blocks and silently truncated.

---

## 9. What Does NOT Exist (Intentionally)

- No server-side backend. No Netlify. No Supabase. No Firebase.
- No React. No Vue. No build system.
- No automated tests (no Jest, no Mocha, no Playwright).
- No Phase 2 pearl generation (`ipcMain.handle('nbme:ai:generate-pearls')` — deferred until after exam).
- No `dist/` is committed — it's gitignored.

## 9b. What Has Been Added Since Pre-Phase-10 PROJECT_CONTEXT

These items are present in current source but were not in the pre-Phase-10 version of this doc:

- `core/uoga/` — Unified Organic Generation Architecture core package. Graph-native only for `fast_facts_pptx`. Enforced by `scripts/uoga_dependency_graph_validator.py`.
- `core/shared/` and `core/extractive/` and `core/hybrid/` — domain-boundary scaffolding for source routing.
- BIC durability stack (v4.31 onward): durable per-job output root under `~/Library/Application Support/nbme-self-assessment-suite/batch-import-center/jobs/<jobId>/`, BIC queue UI, queue persistence across Electron restarts.
- Phase 10C survivability (v4.40): single-instance lock, `process_registry.json`, filesystem-first reconciliation, completed-job protection, guarded process-group cleanup.
- Phase 11 Fast Facts stabilization (v4.41–v4.47): per-question review draft wiring, generation correctness hardening, unified chunk contract, packaged path fixes, reviewed-import-after-auto-import flow.
- v4.48 lecture-slide explanation tables now render structured `q.tables` / `q.metadata.tables` inline in the explanation panel via `renderExplanationTablesInto`.
- `tools/lecture-slide-question-generator/` consumes shared normalized chunks for Emma and is the active downstream for both Emma and Fast Facts (via `--fast-facts-profile`).
- OME, Anki, Divine Transcript shared-ingestion profiles with dry-run BIC handoffs.

---

## 10. File Map

| File/Path | Role |
|---|---|
| `index.html` | **THE ENTIRE APP** — all HTML, CSS, JS (~21,700+ lines) |
| `electron/main.js` | Electron main: HTTP server (port 8888), IPC handlers, all Gemini API calls |
| `electron/preload.js` | `contextBridge`: exposes only `window.nbmeDesktop` to renderer |
| `package.json` | `"main": "electron/main.js"`, scripts: `electron:dev`, `electron:build:mac` |
| `netlify/` | Dead code — legacy Netlify Functions (rollback reference only) |
| `test-data/` | Validated app-ready JSON fixture files (Psych Shelf 3–8, UWorld Notes, OME, Anki, etc.) |
| `test-assets/known-good/` | Known-working test files for regression reference |
| `backfill-pearls.js` | Utility: backfills `retrievalTag`/`reviewPearl` for existing test-data files |
| `dist/` | Packaged Electron app — NOT source, NOT committed |
| `tools/nbme-pdf-json-generator/` | External NBME PDF → app-ready JSON pipeline |
| `tools/uworld-notes-question-generator/` | External UWorld notes → app-ready JSON pipeline |
| `tools/anki-question-generator/` | External Anki notes → app-ready JSON pipeline (wraps UWorld pipeline) |
