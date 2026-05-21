# NBME Self-Assessment Suite — Project Status

**Last updated:** 2026-05-18  
**Supersedes:** PROJECT_STATUS_2026-05-13.md  
**Purpose:** Master handoff snapshot. Zero-ambiguity current state.

---

## 1. How to Run the App

### Development (always use this)
```bash
cd "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite"
npm install          # first time only, or after dependency changes
npm run electron:dev
```
Electron starts, serves `index.html` from project root at `http://127.0.0.1:8888`.

### GitHub Pages (browser, no IPC features)
```
https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/
```

### Packaged App (DO NOT USE FOR DEVELOPMENT)
```
dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html
```
Frozen bundle — invisible to source edits. Use `npm run electron:build:mac` for a full rebuild.

---

## 2. Current Branch State

| Branch | HEAD | Notes |
|---|---|---|
| `main` | `81e11f5` | GitHub Pages source; all app work |
| `origin/main` | `81e11f5` | In sync with local main |

---

## 3. Architecture Overview

Single-file SPA: `index.html` (~21,700+ lines). All HTML, CSS, JS inline.

| Module | Role |
|---|---|
| `DB` IIFE | localStorage: tests, folders, marks, flags, notes, history, settings |
| `FigureStore` | IndexedDB: stem/exhibit images |
| `MiscDocStore` | IndexedDB (`nbme_misc_docs_v1`): Misc Doc file blobs + subfolder metadata |
| `Quiz` IIFE | Test-taking engine: state, navigation, timers, focus mode, answer selection |
| `Results` IIFE | Score report, review mode, PDF report |
| `App` IIFE | Home screen, import pipelines, Drive sync, flashcard system |
| `electron/main.js` | HTTP server, IPC handlers, Gemini API calls |
| `electron/preload.js` | `window.nbmeDesktop` contextBridge |

---

## 4. Source Pipelines — Current Status

| Pipeline | Status | Gemini |
|---|---|---|
| NBME PDF OCR | Stable | Hints + tagging (browser direct call) |
| NBME Gemini JSON | **Stable** — all bugs resolved, Psych Shelf 3–8 + UWorld Notes validated | None |
| UWorld DOCX | Stable (`uworld-gemini-v1-stable`) | Electron IPC only |
| OME PDF | Stable (`ome-v1-stable`) | None in v1 |
| Anki text | Stable (`anki-v1-stable`) | None in v1 |
| Divine Podcasts | Stable (`divine-gemini-v1-stable`) | Electron IPC only |
| Mehlman | Stable (`mehlman-v1-stable`) | None in v1 |

---

## 5. What Changed on 2026-05-18 (Today)

Full details: `RECENT_MAJOR_CHANGES.md`. Summary of first session (commits up to `72cd243`):

| Area | Change |
|---|---|
| **Focus mode** | Fullscreen quiz mode added (`body.quiz-fullscreen-mode`); app chrome hidden |
| **Modal z-index** | Fixed modal dialogs hidden behind focus-mode screen (`z-index:10000` in focus mode) |
| **Pearl flashcards** | Auto-generated from incorrect answers; Drive-synced; sidebar nav under Notes |
| **Misc doc subfolders** | Subfolder organization added to Miscellaneous Documents |
| **UI enlargement** | Quiz reading area and elements enlarged (CSS only) |
| **Font sync** | Stem + choice font-size synchronized via `_applyQuestionFontSize` |
| **Question timer warning** | Visual warning at 90 seconds elapsed (amber color) |
| **Total timer** | Fixed cross-test leakage (module-level `_totTimerRef`), visual jumping (1000ms interval + tabular-nums), and centering (3-column flex bottom bar) |
| **Incorrects generation** | Generate focused test from wrong answers; route to Incorrects folder |
| **Nav active state** | Active question highlighting improved in navigation panel |
| **Electron packaging** | Fixed: runtime files now included in packaged app |
| **Debug cleanup** | All noisy debug logs removed |

Summary of second session (commits `e29420c` → `81e11f5`):

| Area | Change |
|---|---|
| **Block validate save** | `saveValidNbmeGeminiJsonQuestionsOnly()` fully implemented (VAL-003 resolved) |
| **Editable notes** | `DB.updateNote()` + inline edit UI in Notes panel |
| **Persistent highlights** | Stem highlights survive pause/resume/restart; Drive-synced under `db.stemHighlights` |
| **Review Later** | New `type:'reviewLater'` note type; quiz top-bar button; sidebar panel; separate from study notes |
| **Mark reasons** | Mark reason modal; `db.markReasons` storage; displayed in marked items list |
| **Performance summaries** | Stat cards (tests completed, in-progress, avg score) above test grids |
| **Electron close/reload** | `will-prevent-unload` fix; 3s flush-then-close; `buildAppMenu` with Cmd+R/Cmd+Shift+R |
| **Search indexing** | All field types indexed (tags, pearls, explanations, choices); highlighted snippets |
| **Responsive resizing** | `clamp()`/`min()` CSS; sidebar breakpoint at 1280px; horizontal overflow fix |

---

## 6. What Changed on 2026-05-13 (Previous Session)

Full details: `PROJECT_STATUS_2026-05-13.md`. Summary:

| Change | Status |
|---|---|
| BUG-001: `_isLabPara()` false-positive on `%` in clinical prose | ✅ Fixed |
| BUG-002: Explanation panel empty for JSON questions | ✅ Fixed |
| BUG-003: Import preview truncated at 240 chars | ✅ Fixed |
| BUG-005: `_isLabPara()` false-positive on short stems with inline lab values | ✅ Fixed |
| BUG-006: Pearl block missing from quiz explanation view | ✅ Fixed |
| BUG-007: PDF report missing explanations for JSON questions | ✅ Fixed |
| FEAT-001: retrievalTag + reviewPearl display in all surfaces | ✅ Complete |
| FEAT-002: Emma Holiday, Fast Facts, Miscellaneous Documents folders | ✅ Complete |
| FEAT-003: No-Netlify Gemini — callGeminiDirect for hints/tagging | ✅ Complete |
| FEAT-004: safeExportJson — prevent key leakage in downloads | ✅ Complete |
| FEAT-005: Drive autosave hardening (no redundant schedule, post-restore guard) | ✅ Complete |
| FEAT-006: GitHub Pages deployment (`.nojekyll`, merge to main) | ✅ Complete |

---

## 7. Timer Architecture (Critical Invariants)

### Per-question timer
- DOM: `#q-timer` / `.timer-val`
- Warning: CSS class added at ≤91 seconds elapsed (amber color)
- Cleared on question navigation

### Total timer
- Module-level: `let _totTimerRef = null;` — **outside `initState()`**
- This is architecturally critical. Moving it inside `initState()` causes cross-test leakage.
- Fires every 1000ms (not 500ms — prevents layout reflow)
- DOM: `#block-timer` / `.block-timer-display`
- Centered via 3-column flex bottom bar: left(flex:1), center(flex:1), right(flex:1)
- `font-variant-numeric: tabular-nums` — prevents reflow on digit changes

---

## 8. Focus Mode Architecture (Critical Invariants)

- `body.quiz-fullscreen-mode` — CSS class on body
- `#screen-quiz`: `position:fixed; z-index:9999` in focus mode
- **Critical:** `body.quiz-fullscreen-mode .modal-overlay { z-index: 10000; }`
  - Without this, modals are invisible behind the fullscreen screen
  - Do not reduce this z-index

---

## 9. Gemini Architecture (Current)

Two call paths:

**Path 1 — Hints + tagging (browser + Electron):**
- `callGeminiDirect()` in renderer
- Direct fetch to Gemini API with `x-goog-api-key` header
- Key from `getLocalGeminiKey()` → `db.settings.geminiApiKey`

**Path 2 — UWorld + Divine refinement (Electron only):**
- `window.nbmeDesktop.ai.*` → IPC → main → Gemini
- Key: from renderer payload + fallback `process.env.GEMINI_API_KEY`

**Key sync:** `db.settings.geminiApiKey` → mirrored to `localStorage('nbme_gemini_key_v1')` → included in Drive manifest → restored on new device

**Netlify:** Dead code. Not called anywhere. Kept as rollback reference.

---

## 10. Validated Fixture Set

All in `test-data/`, committed to `main`.

| File | Qs | Notes |
|---|---|---|
| `Psych_Shelf_3_app_ready.json` | 50 | 4 shared-stem groups (Q33–Q36) |
| `Psych_Shelf_4_app_ready.json` | 50 | 4 shared-stem groups |
| `Psych_Shelf_5_app_ready.json` | 50 | UI footer artifacts (50 cleaned) |
| `Psych_Shelf_6_app_ready.json` | 50 | Lab tables in `tables[]` |
| `Psych_Shelf_7_repaired_app_ready.json` | 50 | Repaired extraction |
| `Psych_Shelf_8_full_app_ready.json` | 50 | FigureRefs with visibleText (Q25/Q34/Q48) |
| `UWorld_Notes_Psych_Questions_enhanced_app_ready.json` | ~50 | BUG-005 validated here |
| `OME_Mood_app_ready.json` | varies | Mood disorders OME content |
| `Psych_Divine_Intervention_FULL_app_ready.json` | varies | Divine podcast content |
| Others in test-data/ | varies | Various Psych content |

Untracked test data files (not committed — local only):
- `test-data/OME_Peds_Psych_FULL_app_ready.json`
- `test-data/OME_Personality_FULL_app_ready.json`
- `test-data/OME_Sleep_Sex_Drugs_FULL_app_ready.json`
- `test-data/Psych_Anki_Questions_app_ready.json`
- `test-data/Psych_Emma_Holiday_FULL_app_ready.json`
- `test-data/Psych_Fast_Facts_FULL_app_ready.json`
- `test-data/Psych_Mehlman_app_ready.json`
- `test-data/Psych_Shelf_1_FULL_app_ready.json`
- `test-data/Psych_Shelf_2_FIXED_50_app_ready.json`
- `test-data/Psych_Shelf_2_FULL_app_ready.json`

---

## 11. Pending Validation

| Item | Status |
|---|---|
| VAL-002: Figure rendering (Psych_Shelf_8 Q25/Q34/Q48) | ⏳ Not yet end-to-end tested |
| VAL-003: "Save valid questions only" button | ✅ Implemented (`e29420c`) — needs runtime smoke test |
| VAL-004: Shared-group rendering (Psych_Shelf_3 Q33–Q36) | ⏳ Not yet end-to-end tested |
| Cross-device Drive restore (incognito + school Windows) | ⏳ School browser retest pending |
| Pearl flashcard Drive sync validation | ⏳ Not yet tested cross-device |
| Stem highlight persistence cross-device (Drive restore) | ⏳ `stemHighlights` included in manifest — not yet validated on restore |
| Mark reason persistence cross-device (Drive restore) | ⏳ `markReasons` included in manifest — not yet validated on restore |

---

## 12. Immediate Next Priorities

### Study prep (urgent)
1. **Full Drive backup** — Settings → Backup Now → confirm green status
2. **Cross-device restore validation** — GitHub Pages incognito → Connect Drive → Restore → confirm all data
3. **School Windows retest** — if Drive OAuth still fails, verify `274374578651-` credential is type "Web application" in Google Cloud Console

### Content work
- **P0** — Backfill `retrievalTag` + `reviewPearl`: `node backfill-pearls.js` for Psych Shelf 3–8 (requires `GEMINI_API_KEY`)
- **P1** — VAL-002: Figure rendering (Psych_Shelf_8 Q25/Q34/Q48)
- **P2** — VAL-003: Save-valid-only button
- **P3** — Next NBME shelf extraction (Medicine, Surgery, Family Medicine, Pediatrics, OB/GYN, Neurology)
- **P4** — VAL-004: Shared-group rendering validation
- **P5 (post-exam)** — Phase 2 pearl generation via Electron IPC

---

## 13. Do Not

- Reintroduce Netlify functions or any server-side backend
- Hardcode the Gemini API key anywhere in source
- Put Gemini API key in exported test JSON files (use `safeExportJson()`)
- Perform major storage migrations before the exam
- Implement Supabase, Firebase, or any external database
- Refactor into React or add a build system without a documented reason
- Move `_totTimerRef` inside `initState()` — causes cross-test timer leakage
- Reduce `.modal-overlay` z-index below 10000 in `quiz-fullscreen-mode`
- Call `scheduleGoogleDriveSave()` after `DB.save()` — `DB.save()` already schedules it
