# NBME Self-Assessment Suite — Recent Major Changes

**Covers:** 2026-05-14 through 2026-05-18 (all commits after the 2026-05-13 session documented in `PROJECT_STATUS_2026-05-13.md`)

For changes up through 2026-05-13, see `PROJECT_STATUS_2026-05-13.md`.

---

## Session continuation: 2026-05-18 (commits e29420c → 81e11f5)

These 9 code commits landed after the main handoff doc (`72cd243`) was written. All changes are to `index.html` only except `60cc867` which modifies `electron/main.js`.

---

### 1. Fix block validate save button — `e29420c`

**What was added:**
- Implemented `saveValidNbmeGeminiJsonQuestionsOnly()` — previously a stub (VAL-003 from `BUGS_AND_NEXT_STEPS.md`)
- Reads `_nbmeGeminiJsonImport.validation.questionResults`, filters to questions where `isValid === true`
- Maps matching normalized items to full question payloads with correct metadata (`sourceType`, `sourceFormat`, `schemaVersion`, `importedAt`, etc.)
- Calls `DB.createTest()` + `DB.updateTest()`, verifying test was actually persisted
- Reports skipped-invalid count in the save toast
- Guards: empty test name, no folder selected, confirmation checkbox unchecked, 3 MB figure-attachment warning

**Why it mattered:**
Completing VAL-003 — users can now import a partially-broken JSON file and save only the valid questions without re-running the full import.

---

### 2. Add editable saved notes — `686e75c`

**What was added:**
- `DB.updateNote(id, newText)` added to DB layer — updates `note.text`, sets `note.updatedAt`, calls `save()`
- `DB.updateNote` exposed in `DB` public API
- `_editingNoteId` state variable in App module tracks which note is currently being edited inline
- Notes list UI: each note now shows an **Edit** button alongside Delete
- Clicking Edit sets `_editingNoteId` and re-renders the list; the targeted note becomes an inline `<textarea>` with Save/Cancel
- `App.startNoteEdit(id)`, `App.saveNoteEdit(id)`, `App.cancelNoteEdit()` exposed on `window.App`
- After render, the active edit textarea is auto-focused at end of content

**Why it mattered:**
Notes were previously delete-only. Users can now correct typos or refine study notes without losing and recreating them.

---

### 3. Persist question stem highlights — `985cfd0`

**What was added:**
- `DB.getStemHighlights(testId)`, `DB.setStemHighlight(testId, qIdx, data)`, `DB.clearStemHighlights(testId)` added to DB layer
- Highlights stored at `db.stemHighlights[testId][String(qIdx)]` — keyed separately from attempt results so `syncMarks` and test finish cannot destroy them
- `stemHighlights` included in Drive backup manifest serialization and Drive restore deserialization
- `Quiz.saveHighlight(qIdx, html)` and `Quiz.saveHighlightPart(qIdx, key, value)` both now call `DB.setStemHighlight()` after updating in-memory state
- On both `startTest()` and `resumeTest()`, saved highlights are loaded from DB and merged into `state.results[i].highlights`

**Why it mattered:**
Previously, highlighting a word in a question stem was lost on pause/resume or after closing the app. Now highlights survive app restart and test resume.

**Risk note:**
Drive manifest serializer explicitly excludes the `highlights` key from IndexedDB blobs (`if (key === ... || key === 'highlights') return undefined`) — this refers to image/figure data, NOT stem highlights. Stem highlights are stored separately under `db.stemHighlights` and are correctly included in the Drive snapshot.

---

### 4. Add Review Later quick notes — `e0bb2e8`

**What was added:**
- `🗒️ Review Later` button in quiz top bar (alongside Mark, Hint, Focus)
- `#modal-review-later` modal: shows test + question context, textarea for quick note, Ctrl/Cmd+Enter to save
- `DB.addNote()` called with `type: 'reviewLater'` — these notes share the existing notes storage but are logically separated by type
- `App.showReviewLater()` sidebar view: filters `DB.getNotes()` to `type === 'reviewLater'`, groups by test, shows timestamp and Edit/Delete buttons
- Normal Notes view filters these notes OUT (shows only non-`reviewLater` notes)
- Sidebar nav item `#nav-review-later` added between Notes and Flashcards
- `_rlEditingNoteId` state variable tracks inline edits in the Review Later list

**Why it mattered:**
Notes (added to explanation panel) and Review Later (added mid-question) are now two distinct workflows. Quick "look this up later" thoughts captured without interrupting the question.

---

### 5. Add marked question review navigation — `608a1c7`

**What was added:**
- `#modal-mark-reason` modal: "Why mark this question?" prompt with Optional textarea, Skip, and Cancel/Unmark buttons. Ctrl/Cmd+Enter to save.
- `DB.getMarkReason(testId, qIdx)`, `DB.setMarkReason(testId, qIdx, text)`, `DB.clearMarkReason(testId, qIdx)` added — stored at `db.markReasons[testId][String(qIdx)]` with `createdAt` / `updatedAt` timestamps
- `markReasons` included in Drive backup serialization and restore
- `Quiz.toggleMark()` updated: on mark, persists first then calls `App.openMarkReasonModal()` after nav panel update; on unmark, removes mark silently (no modal)
- `.marked-item-reason` CSS class: italic text with left amber border, renders mark reason below question preview in the marked items list

**Why it mattered:**
Users can now record why they flagged a question (e.g. "confused about dosing" or "second-guessed myself") and see that reason when reviewing marks. Also fixes the mark toggle to update the nav panel and persist before showing the modal.

---

### 6. Add lightweight performance summaries — `130f531`

**What was added:**
- `getPerformanceStatsForScope(tests)` — computes `testsCreated`, `testsCompleted`, `testsInProgress`, `questionsGenerated`, `questionsAnswered`, `avgScore` from a test array and DB history
- `renderPerformanceSummary(stats)` — returns flex-row HTML of stat cards; returns empty string if no tests exist (no empty-state clutter)
- Injected above test grids in three views: subfolder test list, source landing page, source folder page
- CSS: `.perf-summary`, `.perf-stat`, `.perf-stat-value`, `.perf-stat-label`, `.perf-stat.accent` (green for avg score)

**Why it mattered:**
At-a-glance progress overview — tests completed, questions answered, average score — visible without opening any individual test. Adds no new storage or persistence; computes from existing history.

---

### 7. Fix Electron app close and reload behavior — `60cc867`

**What changed (`electron/main.js` only):**
- `buildAppMenu(win)` — full macOS `Menu.buildFromTemplate` with: standard app submenu (about, quit), Edit (undo/redo/cut/copy/paste/selectAll), View (Cmd+R reload, Cmd+Shift+R hard reload, devtools, fullscreen), Window (minimize, zoom, close). Without this, Electron's default menu had no reload shortcut.
- `win.webContents.on('will-prevent-unload', e => e.preventDefault())` — overrides the renderer's Drive `beforeunload` handler which was silently swallowing window close. The renderer calls `e.preventDefault()` while a Drive sync is pending; in Electron this fires `will-prevent-unload` and was causing the red X to appear to do nothing.
- Two-pass `win.on('close')` handler: first pass (`isClosing = false`) intercepts, sets `isClosing = true`, executes `window.saveGoogleDriveNow()` + `DB.save()` in the renderer (via `executeJavaScript`), waits up to 3 seconds, then calls `win.close()` again. Second pass (`isClosing = true`) proceeds immediately.

**Why it mattered:**
Previously: red X did nothing (Drive `beforeunload` block); Cmd+R had no effect (no menu shortcut). Now: close flushes state then exits cleanly; Cmd+R and Cmd+Shift+R reload work.

---

### 8. Expand search indexing and highlight matches — `415fa79`

**What was added:**
- `_stripSearchHtml(s)` — strips HTML tags, HTML entities, collapses whitespace. Used before indexing and display.
- `buildQuestionSearchFields(q)` — returns ordered `[{label, text}]` covering: stem → retrieval tags (all tag fields + variants) → pearls (`reviewPearl`, `clinicalPearl`, `pearl`, `pearls`, metadata mirrors) → answer choices → explanations (`educationalObjective`, `teachingPoint`, `explanation`, `correctBlurb`, `explanationSections`, `choiceExplanations`). Priority order matters: first-matching field wins per question.
- `buildHighlightedSnippet(rawText, query)` — 300-char context window with `<mark class="search-hl">` wrapped around all case-insensitive query matches. Regex-injection safe. Returns plain escaped text on no match.
- `searchQuestionContent()` rewritten: uses `buildQuestionSearchFields`, deduplicates by `testId__idx`, shows `source` field label and highlighted snippet in results.
- `.search-hl { background: #fff176 }` CSS for yellow highlight in search cards.
- Search result tag now uses `q.retrievalTag` first (falls back to `q.tags[0]`).

**Why it mattered:**
Previously search only looked at `q.explanation` and answer choices (and only for legacy import format). Now all import formats are fully indexed including NBME JSON fields (`educationalObjective`, `correctBlurb`, `retrievalTag`, `reviewPearl`, etc.).

---

### 9. Improve responsive app resizing — `81e11f5`

**What was changed (CSS-only, `index.html`):**
- `@media (max-width: 1280px)` breakpoint: sidebar narrows to 160px on medium screens
- `body { overflow-x: hidden }` — prevents horizontal scrollbar from appearing on resize
- `#topbar` padding: `clamp(10px, 1.2vw, 20px)` instead of fixed 16px
- `.topbar-right`: gap uses `clamp(6px, 0.8vw, 12px)`, added `flex-shrink: 1; min-width: 0`
- `#screen-home` padding: `clamp(14px, 2vw, 28px)`
- `.search-input` width: `min(300px, 38vw)` down from `min(360px, 48vw)`; added `min-width: 0`
- Grid `minmax` patterns use `min(Xpx, 100%)` to prevent horizontal overflow on narrow containers
- `.perf-stat` padding and min-width responsive via `clamp()`; `.perf-stat-value` font-size via `clamp(16px, 1.6vw, 22px)`
- `.quiz-topbar` padding: `clamp(10px, 1.5vw, 20px)`

**Why it mattered:**
The app was overflowing horizontally on screens narrower than ~1400px. `clamp()`/`min()` values keep the layout fluid without transform:scale hacks. No functional changes.

---

## Summary: All post-handoff functional changes (e29420c → 81e11f5)

| Area | What changed | Commit |
|---|---|---|
| Block validate save | `saveValidNbmeGeminiJsonQuestionsOnly()` implemented (VAL-003 resolved) | `e29420c` |
| Editable notes | `DB.updateNote()` + inline edit UI in Notes panel | `686e75c` |
| Persistent highlights | Stem highlights survive pause/resume/restart; Drive-synced | `985cfd0` |
| Review Later | New note type + sidebar view + quiz top-bar button | `e0bb2e8` |
| Mark reasons | Mark reason modal + DB storage + display in marked items list | `608a1c7` |
| Performance summaries | Stat cards above test grids (completed, in-progress, avg score) | `130f531` |
| Electron close/reload | `will-prevent-unload` fix, 3s flush-then-close, Cmd+R menu | `60cc867` |
| Search indexing | All field types indexed; highlighted snippets in results | `415fa79` |
| Responsive resizing | `clamp()`/`min()` CSS; sidebar breakpoint; overflow fix | `81e11f5` |

---

## Session: 2026-05-18 — Major Feature and Fix Day

All commits on this date are on the `main` branch (HEAD: `be965b2`). 30+ commits total, all to `index.html` only.

---

### 1. Focus Mode (Fullscreen Quiz) — `b1d1c09`, `678b97b`

**What was added:**
- `toggleFocusMode()` exported from the active quiz module
- `body.quiz-fullscreen-mode` CSS class controls fullscreen state
- `#screen-quiz` gets `position:fixed; z-index:9999` in focus mode
- All app chrome (sidebar, header, navigation bars) hidden via CSS when in focus mode

**Subsequent fix — `3cf94eb` (Modal z-index):**
- Root cause: `.modal-overlay` (z-index 1000) rendered behind `#screen-quiz` (z-index 9999) in focus mode
- Fix: `body.quiz-fullscreen-mode .modal-overlay { z-index: 10000; }` — CSS-only
- Without this, clicking "Finish" in focus mode showed the modal invisibly behind the screen, making tests unsubmittable

---

### 2. Electron Server and Build Diagnostics — `fba6133`, `5d12e88`

- Added Electron build marker diagnostics to distinguish build from dev mode
- Added server route diagnostics for Electron dev server
- These were debug aids; relevant log noise removed in `5c20f06`

**Drive restore debug logs — `d0795e3`:**
- Added debug logging for Drive backup/restore flow to aid troubleshooting
- Removed in `5c20f06` along with other noisy debug logs

**Electron package fix — `abdb663`:**
- Fixed `electron:build:mac` to include runtime app files in the Electron package
- Previously some supporting files were excluded, causing the packaged app to behave differently from dev

---

### 3. Labs and Tutor Controls — `9587970`

- Moved labs and tutor controls into the bottom quiz panel
- Previously in a different location; moved for better UX consistency in the quiz chrome

---

### 4. Pearl Flashcard System — `de50089`, `d0e04a4`, `92d6d2b`

**What was added (`de50089`):**
- Auto-generates clinical pearl flashcards after each test from incorrectly answered questions
- Source: `q.reviewPearl || q.explanation` for each incorrect answer
- Deduplicated by content hash
- Organized: source folder → test name hierarchy
- Synced to Google Drive
- Sidebar navigation item added under "Notes"

**Bug fixes:**
- `d0e04a4`: Fixed incorrect pearl flashcard extraction (was extracting wrong field)
- `92d6d2b`: Fixed flashcard generation trigger (was not firing reliably after test completion)

---

### 5. Miscellaneous Document Subfolders — `8e01c5a`

- Added subfolder support to Miscellaneous Documents
- Previously all Misc Docs were in a flat list
- Now organized into user-created subfolders
- 165 lines changed in `index.html`
- IndexedDB schema (`MiscDocStore`) updated to support subfolder metadata

---

### 6. UI Enlargement and Font Sync — `43243dd`, `1d5d0c0`, `dab7678`, `ab9c060`, `d11b66e`

- `43243dd`: Enlarged UI elements across the app (CSS-only change)
- `1d5d0c0`: Enlarged quiz reading area for better readability
- `dab7678`: Matched question stem font-size to answer choice font-size (visual mismatch fix)
- `ab9c060`: Fixed stem/choice font-size mismatch via `_applyQuestionFontSize` helper
- `d11b66e`: Fixed `compareStemChoiceFont` helper to use `#options-list` as the canonical choice element reference (was using a now-absent element selector)

---

### 7. Question Timer Warning System — `94f1905`, `09b49e2`, `b5aaf03`, `76b723f`

**What was added (`94f1905`):**
- Per-question timer now shows a visual warning at 90 seconds elapsed
- Warning state: amber/orange color change on the timer display
- Threshold: ≤91 seconds elapsed (triggers the warning CSS class)
- Warning clears on navigation to the next question

**Refinement (`09b49e2`):**
- Refined the visual appearance and timing of the question timer warning

**Color/build adjustment (`b5aaf03`):**
- Adjusted timer warning color and added a build marker for version identification

**Log cleanup (`76b723f`):**
- Removed noisy timer debug logs that were polluting the console during quiz sessions

---

### 8. Total Timer Fixes — `b45b5ca`, `1149aa1`

**Bug fix (`b45b5ca`) — Three simultaneous root causes fixed:**

**Root cause 1 — Cross-test leakage:**
- `_totTimerRef` was inside `initState()`. When a new test started, `initState()` replaced the state object with one where `totTimerRef: null`. The old interval was never cleared — its reference was lost. It kept writing to `state.totSecs` via the module-level `state` ref.
- Fix: Hoisted `_totTimerRef` to module level. Always cleared before any new interval.

**Root cause 2 — Visual jumping:**
- Interval was firing at 500ms (twice per second). String length changes like `09:59` → `10:00` or `59:59` → `1:00:00` caused layout reflow and visual jumping/seizing.
- Fix: Interval changed to 1000ms. `.block-timer-display` given `min-width`, `text-align:center`, `font-variant-numeric:tabular-nums`.

**Root cause 3 — Timer not centered:**
- Timer was in the left group of the bottom bar.
- Fix: Bottom bar restructured to 3-column flex: `left:flex:1 (score/controls)`, `center:flex:1 (timer)`, `right:flex:1 (nav buttons)`.

**Typography match (`1149aa1`):**
- `.block-timer-display`: font-size 13→17px, color `#9ab0c8`→white, removed letter-spacing, min-width 52→70px
- Matches `.timer-val` normal state exactly

---

### 9. Incorrects Test Generation — `4e26061`, `b769fc5`, `dfc80ee`, `8685f5c`, `be965b2`

**Initial implementation (`4e26061`):**
- Grouped review sections in the score report UI
- Added "Generate Incorrects Test" button to create a focused practice test from wrong answers
- 424-line change in `index.html`

**Subsection incorrects (`b769fc5`):**
- Added ability to generate an incorrects test from just one review section (not the whole test)

**Routing (`dfc80ee`):**
- Routed generated incorrects tests to a dedicated "Incorrects" folder
- Ensures they don't pollute the main NBME or source folders

**Save destination (`8685f5c`):**
- Added save destination selection UI for incorrects tests
- User can choose which folder/subfolder to save to
- 194-line change (157 additions)

**Naming and destination fix (`be965b2`):**
- Fixed generated test naming (was producing malformed names)
- Fixed destination selection (was sometimes saving to wrong location)
- 132-line change (99 additions, 33 deletions)

---

### 10. Question Navigation Active State — `49e2d89`

- Improved active question highlighting in the collapsible navigation panel
- The currently active question now has a clearer visual indicator
- 5-line change (4 additions, 1 deletion)

---

### 11. Debug Log Cleanup — `5c20f06`

- Removed all noisy debug logs added during the 2026-05-18 session
- Removed temporary timer debug logs
- Removed Drive restore debug logs
- Removed Electron build marker diagnostics from renderer output
- 0 functional changes; code behavior unchanged

---

## Summary: All 2026-05-18 Functional Changes

| Area | What changed | Commits |
|---|---|---|
| Focus mode | Fullscreen quiz, app chrome hidden | `b1d1c09`, `678b97b` |
| Modal z-index | Modals visible in focus mode | `3cf94eb` |
| Electron packaging | Runtime files included in package | `abdb663` |
| Labs/tutor controls | Moved to bottom panel | `9587970` |
| Pearl flashcards | Auto-generated from incorrect answers, Drive-synced | `de50089`, `d0e04a4`, `92d6d2b` |
| Misc doc subfolders | Subfolders for Misc Documents | `8e01c5a` |
| UI enlargement | CSS-only size increases | `43243dd`, `1d5d0c0` |
| Font sync | Stem + choice font-size synchronized | `dab7678`, `ab9c060`, `d11b66e` |
| Question timer warning | Warning at 90s elapsed | `94f1905`, `09b49e2`, `b5aaf03`, `76b723f` |
| Total timer | Cross-test leakage, visual jumping, centering all fixed | `b45b5ca`, `1149aa1` |
| Incorrects generation | Generate, route, name, and save incorrects tests | `4e26061`, `b769fc5`, `dfc80ee`, `8685f5c`, `be965b2` |
| Nav active state | Active question highlighting | `49e2d89` |
| Debug cleanup | All noisy logs removed | `5c20f06` |
