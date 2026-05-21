# NBME Self-Assessment Suite — Project Status

**Last updated:** 2026-05-19
**HEAD:** `5514c85` — "Add working Anki notes question generator"
**Branch:** `main`
**Purpose:** Zero-ambiguity current state for any session resuming work.

---

## 1. Current Working State

The app is fully functional. All three external tool pipelines are working. No unresolved bugs in the core app or tools as of this date.

### App (index.html)

| Area | Status |
|---|---|
| Quiz engine (timed/untimed, tutor/block mode) | Stable |
| Focus mode (fullscreen quiz) | Stable |
| Timer system (per-question + total) | Stable — timer cross-test leakage FIXED |
| NBME Gemini JSON importer | Stable — Psych Shelf 3–8 validated |
| Figure attachment/rendering | Stable — `fr.id \|\| fr.figureId` fix applied |
| Score reports + PDF export | Stable |
| Pearl flashcard system | Stable |
| Incorrects test generation | Stable |
| Persistent stem highlights | Stable — Drive-synced |
| Mark reasons | Stable — Drive-synced |
| Review Later notes | Stable |
| Search (all field types indexed) | Stable |
| Google Drive backup/restore | Stable — cross-device restore PENDING validation |
| Gemini hints + tagging (callGeminiDirect) | Stable |
| UWorld/Divine Gemini (Electron IPC) | Stable |
| Responsive CSS (clamp/min) | Stable |
| Performance summary cards | Stable |
| Editable notes | Stable |

### External Tool Pipelines

| Tool | Status | Last validated |
|---|---|---|
| `tools/nbme-pdf-json-generator/` | Stable | 2026-05-19 (8A_app_ready.json) |
| `tools/uworld-notes-question-generator/` | Stable | 2026-05-19 (test_cardiology_app_ready.json) |
| `tools/anki-question-generator/` | Stable | 2026-05-19 (test_cardiology_anki + test_medicine_anki) |

---

## 2. Latest Stable Tags

### App milestone tags

| Tag | Description |
|---|---|
| `v2.3-anki-generator-working` | Anki generator working end-to-end |
| `v2.3-anki-generator-wrapper` | Anki wrapper script added |
| `v2.2-working-nbme-import-pipeline` | NBME pipeline + import fully working |
| `v2.1-nbme-figure-attachments-fixed` | Figure upload `fr.id \|\| fr.figureId` fix |
| `v2.0-uworld-generation-working` | UWorld generator working end-to-end |
| `v1.9-uworld-gemini-generation` | UWorld Gemini generation added |
| `v1.6-app-ready-json-converter` | normalized_to_app_json.py added |
| `v1.5-ocr-gemini-working` | OCR + Gemini normalization working |

### In-app source pipeline tags

| Tag | Pipeline |
|---|---|
| `anki-v1-stable` | Anki in-app import pipeline |
| `divine-gemini-v1-stable` | Divine podcast Gemini IPC pipeline |
| `ome-v1-stable` | OME PDF in-app import pipeline |
| `uworld-gemini-v1-stable` | UWorld DOCX Gemini IPC pipeline |
| `mehlman-v1-stable` | Mehlman in-app pipeline |

---

## 3. Known-Good Workflows

These workflows have been verified end-to-end:

| Workflow | Status |
|---|---|
| NBME Shelf exam PDF → 8A_app_ready.json → import into app | Validated |
| UWorld notes .txt → test_cardiology_app_ready.json → import | Validated |
| Anki notes .txt → test_cardiology_anki_app_ready.json → import | Validated |
| Import Psych_Shelf_3–8_app_ready.json → quiz → score report | Validated (300 Qs) |
| Import UWorld_Notes_Psych_Questions_enhanced_app_ready.json | Validated |
| Google Drive backup (main Mac app) | Validated |
| Google Drive restore (incognito browser) | Validated (with Gemini key auto-populated) |

---

## 4. Unresolved Issues (Pending Validation)

### VAL-002: Figure rendering end-to-end test
**What:** Import `test-data/Psych_Shelf_8_full_app_ready.json`, navigate to Q25/Q34/Q48 (questions with `[FIGURE: ...]` markers), verify placeholder box appears, then attach an image via the figure attachment panel and verify inline rendering.
**Status:** Code is correct (figure attachment key bug fixed in `v2.1`). End-to-end UI test not yet performed.

### VAL-003: Save-valid-questions-only smoke test
**What:** Import a JSON file with at least one invalid question, confirm "Save valid questions only" button works, verify skipped-count toast and correct questions in library.
**Status:** `saveValidNbmeGeminiJsonQuestionsOnly()` fully implemented (`e29420c`). Smoke test not yet run.

### VAL-004: Shared-group rendering validation
**What:** Import `Psych_Shelf_3_app_ready.json`, navigate to Q33–Q36 (shared-stem group), verify shared vignette renders above per-question stem via `buildSharedGroupHTML`.
**Status:** Not yet end-to-end tested.

### Cross-device Drive restore
**What:** Run full Backup Now → open GitHub Pages in fresh browser → Connect Drive → Restore. Verify all data, Gemini key, misc docs, score history.
**Status:** Validated on personal incognito browser. **School Windows computer retest pending** (Drive OAuth `origin_mismatch` may require Google Cloud Console credential check).

---

## 5. What Is Intentionally NOT Implemented

| Item | Why deferred |
|---|---|
| OME external tool pipeline | Not yet built — plan is in `NEXT_STEPS_OME.md` |
| Phase 2 pearl generation (Electron IPC `nbme:ai:generate-pearls`) | Deferred until after exam |
| `backfill-pearls.js` run for Psych Shelf 3–8 | Requires Gemini API key, deferred |
| Windows Electron build | GitHub Pages may be sufficient for school |
| ETag concurrency protection for Drive | Deferred post-exam (single-user app, low risk) |
| React / build system | No need; single-file SPA is sufficient |
| Supabase / Firebase / any server DB | Never. Private personal tool. |

---

## 6. App-Ready Outputs (current state)

### In test-data/ (committed to main)

| File | Questions | Notes |
|---|---|---|
| `Psych_Shelf_3_app_ready.json` | 50 | 4 shared-stem groups (Q33–Q36) |
| `Psych_Shelf_4_app_ready.json` | 50 | 4 shared-stem groups |
| `Psych_Shelf_5_app_ready.json` | 50 | UI footer artifacts cleaned |
| `Psych_Shelf_6_app_ready.json` | 50 | Lab tables in `tables[]` |
| `Psych_Shelf_7_repaired_app_ready.json` | 50 | Repaired extraction |
| `Psych_Shelf_8_full_app_ready.json` | 50 | FigureRefs (Q25/Q34/Q48) |
| `Psych_Divine_Intervention_FULL_app_ready.json` | varies | Divine podcast content |
| `OME_Mood_app_ready.json` | varies | Mood disorders OME |

### In test-data/ (untracked — local only, permissions `-rw-------`)

`Psych_Shelf_1_FULL`, `Psych_Shelf_2_FULL`, `Psych_Shelf_2_FIXED_50`, `OME_Peds_Psych_FULL`, `OME_Personality_FULL`, `OME_Sleep_Sex_Drugs_FULL`, `Psych_Anki_Questions`, `Psych_Emma_Holiday_FULL`, `Psych_Fast_Facts_FULL`, `Psych_Mehlman`, `UWorld_Notes_Psych_Questions_enhanced`

### In tools/ app_ready outputs (untracked)

| File | Pipeline |
|---|---|
| `tools/nbme-pdf-json-generator/output_json/app_ready/8A_app_ready.json` | NBME |
| `tools/uworld-notes-question-generator/output_json/app_ready/test_cardiology_app_ready.json` | UWorld |
| `tools/anki-question-generator/output_json/app_ready/test_cardiology_anki_app_ready.json` | Anki |
| `tools/anki-question-generator/output_json/app_ready/test_medicine_anki_app_ready.json` | Anki |

### In test-assets/known-good/ (untracked)

| File | Purpose |
|---|---|
| `8A_app_ready_WORKING.json` | Known-good reference for NBME Shelf 8A import regression |

---

## 7. Git Status (as of 2026-05-19)

```
M  .claude/settings.local.json   (modified — tool config, not app code)
?? test-assets/                  (untracked — local test reference files)
```

No uncommitted app logic changes. All app changes are committed on `main`.

---

## 8. Immediate Next Priorities (ordered)

1. **Validate cross-device Drive restore** (school Windows computer — Drive OAuth may need credential check in Google Cloud Console)
2. **Run VAL-002** — figure rendering smoke test with `Psych_Shelf_8_full_app_ready.json` Q25/Q34/Q48
3. **Run VAL-003** — save-valid-only smoke test
4. **Backfill `retrievalTag` + `reviewPearl`** — `node backfill-pearls.js` for Psych Shelf 3–8 (requires `GEMINI_API_KEY`)
5. **Build OME external tool pipeline** — see `NEXT_STEPS_OME.md` for full plan
6. **Extract more NBME shelf subjects** — Medicine, Surgery, Family Medicine, Pediatrics, OB/GYN, Neurology

---

## 9. Do Not

- Test against `dist/mac-arm64/...app` unless after a full `npm run electron:build:mac`
- Move `_totTimerRef` inside `initState()` — causes cross-test timer leakage
- Reduce `.modal-overlay` z-index below 10000 when `quiz-fullscreen-mode` is active
- Put Gemini API key in exported JSON, `process.env` reads in renderer, or committed files
- Call `scheduleGoogleDriveSave()` after `DB.save()` — double-debounce delay
- Reintroduce Netlify functions as active call sites
- Create a schema fork or new importer — reuse the existing NBME Gemini JSON importer
- Remove `_isLabPara()` guards (length > 400, `/\?/.test(para)`) — prevents stem truncation
