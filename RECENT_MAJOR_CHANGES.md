# NBME Self-Assessment Suite — Recent Major Changes

**Covers:** 2026-05-14 through 2026-05-18 (all commits after the 2026-05-13 session documented in `PROJECT_STATUS_2026-05-13.md`)

For changes up through 2026-05-13, see `PROJECT_STATUS_2026-05-13.md`.

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
