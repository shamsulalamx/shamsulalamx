# NBME Self-Assessment Suite — Debugging Pitfalls

**Last updated:** 2026-05-18  
**Purpose:** Catalogue of every debugging trap this project has fallen into. Read before diagnosing any issue.

---

## Pitfall 1: Testing Against the Packaged App Instead of Dev Server

**The trap:** Opening `dist/mac-arm64/NBME Self-Assessment Suite.app` directly and then making edits to `index.html` and wondering why nothing changes.

**Why it happens:** The packaged `.app` bundle contains its own frozen copy of `index.html` at:
```
dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html
```
This file is only updated by a full `npm run electron:build:mac`. Edits to the project root `index.html` are completely invisible to the running `.app`.

**How to detect:** Run `wc -c` on both files. If sizes differ, the bundle is stale.
```bash
wc -c "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html"
wc -c "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html"
```

**Fix:** Always develop with `npm run electron:dev`. If you must use the packaged app:
```bash
cp "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html" \
   "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html"
```

**Real impact:** Multiple sessions of debugging "fixed" code that had no effect because the stale bundle was always running. (BUG-004)

---

## Pitfall 2: Grepping for Code and Assuming the App Uses It

**The trap:** `grep -n "function foo"` finds the function. You conclude the fix is applied and working.

**Why it doesn't work:** Grep finds text in files on disk. It cannot tell you:
- Whether the running Electron process loaded the current file or a stale bundle
- Whether the function is actually called by the live code path
- Whether a CSS rule is being overridden by an inline style
- Whether the DOM element you're targeting actually exists

**Correct approach:** After any fix, verify at runtime using Electron devtools (`Cmd+Option+I`):
```javascript
// CSS check
getComputedStyle(document.querySelector('.timer-val')).color

// Inline style override check
document.querySelector('#q-timer').style.display

// DOM presence check
document.querySelector('#q-pearl-block')  // returns null if missing

// Text content verification
document.querySelector('#exp-body').innerText.length  // was 39 when stem was truncated (BUG-001)
```

**Rule:** Runtime observation > grep. Always.

---

## Pitfall 3: CSS Rules Overridden by Inline Styles

**The trap:** You add or modify a CSS rule and it has no effect. You've confirmed the rule is in the stylesheet. The element still looks wrong.

**Why it happens:** Inline `style=""` attributes on DOM elements override external/embedded CSS rules, even with high specificity. Many dynamic behaviors in this app set inline styles directly.

**How to detect:**
```javascript
const el = document.querySelector('#your-element');
console.log(el.style.display);           // inline style
console.log(getComputedStyle(el).display); // computed (what actually renders)
```
If `el.style.display` differs from what your CSS says, the inline style wins.

**Fix:** Either remove the inline style in JS, or use `!important` in CSS (sparingly and with a comment).

---

## Pitfall 4: Wrong Worktree / Wrong File Path

**The trap:** Claude Code is operating in a git worktree at:
```
/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/.claude/worktrees/silly-lewin-6c2cae/
```
But the real source file lives at:
```
/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html
```

**Why it matters:** If you Read or Edit a file relative to the worktree working directory without using the absolute path to the main repo, you may be editing a worktree copy that never gets deployed.

**How to verify:** Always use the absolute path:
```bash
cd "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite"
git status
git diff index.html
```
Confirm the diff shows your intended changes in the main repo before concluding success.

---

## Pitfall 5: Cross-Test Timer Leakage (Module-Level State)

**The trap:** Starting a second test shows the total timer counting from where the previous test left off.

**Root cause (BUG history):** `_totTimerRef` (the interval ID for the total test timer) was originally inside `initState()`. When a new test starts, `initState()` creates a fresh state object. The new state has `totTimerRef: null`. `startTotalTimer()` checks `state.totTimerRef`, finds null, and creates a new interval — **but never clears the previous interval**, because the reference was lost when the old state object was discarded. The orphaned interval keeps writing to `state.totSecs` via the module-level `state` variable.

**Fix:** `_totTimerRef` must be a **module-level** variable outside `initState()`. It is always cleared before any new interval is created. This is an architectural invariant — do not move it back into state.

```javascript
// CORRECT — module-level
let _totTimerRef = null;
function startTotalTimer() {
  if (_totTimerRef) clearInterval(_totTimerRef);  // always clears
  _totTimerRef = setInterval(() => { ... }, 1000);
}

// WRONG — inside state (do not do this)
function initState() {
  state = { totTimerRef: null, ... };
}
function startTotalTimer() {
  if (state.totTimerRef) clearInterval(state.totTimerRef); // silently fails after state reset
  state.totTimerRef = setInterval(() => { ... }, 1000);
}
```

---

## Pitfall 6: Modal Hidden Behind Focus-Mode Fullscreen Screen

**The trap:** User clicks "Finish" in focus mode. Nothing seems to happen. The modal is invisible.

**Root cause (BUG history):** `body.quiz-fullscreen-mode` sets `#screen-quiz` to `position:fixed; z-index:9999`, creating a stacking context that covers the full viewport. `.modal-overlay` with `z-index:1000` is a DOM sibling — it renders behind the fullscreen screen.

**Fix:** One CSS rule elevates all `.modal-overlay` elements to `z-index:10000` when focus mode is active:
```css
body.quiz-fullscreen-mode .modal-overlay {
  z-index: 10000;
}
```

**Never reduce this.** If a future feature adds a new fullscreen layer, check that all modal/dialog z-indices are elevated appropriately.

---

## Pitfall 7: `_isLabPara()` Truncating Clinical Vignettes

**The trap:** A question in quiz mode shows only 1–2 lines of text and no scrollbar. The full stem is inaccessible. This can easily be misdiagnosed as a CSS overflow issue.

**Root cause:** `_isLabPara()` determines whether a text paragraph should be rendered as a lab-values table. The regex `_LAB_SCAN_RE` includes `%` as a recognized lab unit. Clinical vignettes containing phrases like "80% intelligible" or "14% of his total body surface area" matched the regex. `buildStemHTML` then rendered the entire 1300-character vignette as a lab table, extracting one row ("he sustained second-degree burns to" | "14%") and silently discarding the rest.

**Verification method (how BUG-001 was found):**
```javascript
const stemEl = document.querySelector('#stem-text');
console.log(stemEl.innerText.length);  // was 39 — should be hundreds
console.log(stemEl.scrollHeight, stemEl.clientHeight);  // were equal — no hidden overflow
// The text was NEVER in the DOM
```

**Guards (do not remove either):**
```javascript
function _isLabPara(para) {
  if (para.length > 400) return false;   // BUG-001: long paragraphs are vignettes
  if (/\?/.test(para)) return false;     // BUG-005: question stems have '?'
  ...
}
```

---

## Pitfall 8: Explanation Panel Empty for NBME JSON Questions

**The trap:** After answering a JSON-imported question, the explanation panel is blank.

**Root cause:** `buildExplanationHTML` originally only checked `q.explanation`. JSON-imported questions set `q.correctBlurb` (pre-escaped HTML) and `q.educationalObjective` (plain text), not `q.explanation`.

**Fix:** Both `buildExplanationHTML` copies (local ~line 5640, global ~line 5820) must render all four sources: `educationalObjective`, `correctBlurb`, `explanation` (legacy), `q.e` (per-choice). Verify both copies were updated — only fixing one causes intermittent behavior depending on which call path is active.

---

## Pitfall 9: GitHub Pages vs Electron — Feature Availability Confusion

**The trap:** Testing a feature in GitHub Pages (browser), it doesn't work, and you assume the feature is broken.

**Why:** Some features are Electron-only:
- UWorld Gemini refinement (`window.nbmeDesktop.ai.refineUWorldDraft`)
- Divine Gemini refinement (`window.nbmeDesktop.ai.refineDivineDraft`)
- `window.nbmeDesktop?.isElectron` — this is `undefined` in the browser

These features silently fail or hide themselves in browser mode via guards like:
```javascript
if (!window.nbmeDesktop?.isElectron) { /* hide the button */ }
```

**Other features work identically in browser and Electron:**
- All quiz functionality
- All score reports
- Gemini hints/tagging (`callGeminiDirect` — direct fetch from renderer)
- Drive backup/restore
- All import pipelines (except UWorld/Divine Gemini refinement)
- All flashcard functionality
- Incorrects test generation

**Rule:** Always note which runtime you're testing in and whether the feature is expected to work there.

---

## Pitfall 10: Drive Autosave Racing Against Fresh Restore

**The trap:** User restores from Drive. App reloads. Startup code runs a DB migration that calls `DB.save()` and `scheduleGoogleDriveSave()`. The startup write races against the fresh restore, potentially overwriting the just-restored manifest with stale local state.

**Fix:** Post-restore guard:
```javascript
// In restoreGoogleDriveNow():
sessionStorage.setItem('nbme_post_restore_v1', '1');
location.reload();

// In DOMContentLoaded:
const postRestore = sessionStorage.getItem('nbme_post_restore_v1');
sessionStorage.removeItem('nbme_post_restore_v1');
if (postRestore) return; // skip migration DB.save()
```

**Rule:** Never add a second `scheduleGoogleDriveSave()` call after `DB.save()`. `DB.save()` already schedules Drive sync internally. A second call resets the debounce timer and extends the sync delay.

---

## Pitfall 11: Per-Question Stem Font-Size Out of Sync with Choice Font-Size

**The trap:** Increasing or decreasing font size via the zoom control only affects the stem (or only affects the choices), creating a visual mismatch.

**Root cause:** Two separate DOM subtrees controlled font size independently. The stem had one `font-size` setting; the choices (`#options-list`) had another.

**Fix (2026-05-18):** `_applyQuestionFontSize()` synchronizes both via a shared reference (`#options-list` as the canonical choice reference). The `compareStemChoiceFont` helper was fixed to use `#options-list` (not a now-absent element selector).

**Rule:** When modifying font size behavior, always verify both the stem element AND `#options-list` are updated together.

---

## Quick Diagnostic Checklist

When something is broken:

- [ ] Am I running `npm run electron:dev`? (not the packaged `.app`)
- [ ] Does `git diff index.html` show my intended changes?
- [ ] Is the correct file at `/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html`?
- [ ] Is there an inline style overriding my CSS? (`el.style.* !== ''`)
- [ ] Is the DOM element actually present? (`document.querySelector('#id')`)
- [ ] Is the feature Electron-only and I'm testing in the browser?
- [ ] Is a stacking context (z-index issue) hiding a modal?
- [ ] Is `_totTimerRef` still module-level?
- [ ] Does `_isLabPara()` still have both length and `?` guards?
- [ ] Did `DB.save()` run twice (`scheduleGoogleDriveSave()` called redundantly)?
