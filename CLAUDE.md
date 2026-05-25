# CLAUDE.md — Working agreement with the user

This file is the project's binding protocol for any Claude session. Read it at
the start of every conversation on this repo. Violations have eroded trust
historically — don't repeat the patterns.

## Hard constraints (no exceptions)

### 1. Static checks ≠ behavior verification
`node --check`, `python3 -m py_compile`, and grep counts confirm the code
PARSES. They do NOT confirm it WORKS. Past bugs that passed these gates:
- `asyncPrompt` defined in the wrong scope (v4.80.0) — caller threw
  `ReferenceError`, but `node --check` was fine because the function existed
  somewhere
- Gemini 2.5 thinking-mode token consumption — calls "worked" but returned
  empty responses
- Drive token cache returning stale value — `if (_accessToken) return token`
  short-circuit
- Cancelled job reported as `completed` — reconciler overrode status on
  app restart, latent for many versions

The lesson: every change needs a RUNTIME verification step. The user is
often the only person who can do that for UI changes (see constraint 3).

### 2. No commit / no tag / no push without user verification
Sequence is ALWAYS:
1. Make change
2. Run every static check (syntax, scope, grep counts, MD5 source↔bundle)
3. Rebuild the .app
4. Write a specific test plan + DevTools command
5. STOP. Tell user to verify.
6. User reports ✅ or ❌ (with console output if ❌)
7. ONLY ON ✅: commit, tag, push

Tag suffix stays `-pending-validation` until the user explicitly approves
promotion to `-stable`. Never auto-promote.

### 3. I cannot click-through test an Electron app
The available preview tools are for web dev servers (Vite, Next.js, etc.)
— they don't interact with Electron renderers, native menus, or actual UI.
For any UI-facing change, the user IS the verification step.

When the user is unavailable, the workflow stops at "committed locally,
awaiting validation." No push. No tag. No declaring it "done."

### 4. Scope-sensitive edits need scope verification
This codebase has multiple IIFEs and multiple top-level functions with the
SAME name (`escapeHTML` exists twice; `renameFolder` exists in DB layer +
App layer). When adding a function that will be CALLED by code in a
specific scope:
- Grep for the calling function's location
- Grep for the IIFE boundaries between caller and proposed placement
- If there's a `})();` between them, the placement is wrong

Example check:
```bash
awk '/^const App = \(\(\)/{app=NR}/function YOUR_FN/{f=NR}END{print "App:",app,"| fn:",f,"=>",(f>app?"INSIDE":"OUTSIDE")}' index.html
```

### 5. Don't use a non-unique anchor for Edit
If `Edit old_string` matches multiple times in the file, the edit might
land in the wrong scope (this is the asyncPrompt bug). Always:
1. Grep for the anchor first to count matches
2. If >1 match, expand the context to be unique
3. Verify the edit landed where intended by reading the area after

## User-side protocol

When the user is actively engaged:
- They give a one-line test plan up front ("after this fix, X should Y")
- After my rebuild: they quit + relaunch the .app, run DevTools commands,
  click through the UI, report ✅ or ❌ with console output
- ✅ → I commit + tag + push
- ❌ → I diagnose from the actual console error, fix, rebuild, ask to retest

When the user is unavailable (e.g., overnight, studying):
- I work on the branch, commit incrementally with detailed messages
- I do NOT tag, do NOT push
- I write a comprehensive STATUS document explaining what's ready to test
- I leave the branch in a state they can verify when they're back

## High-trust-cost areas (extra caution)

These domains have had the most repeated bugs. Triple-check anything here:

1. **Drive sync / OAuth** — token caching, scope grants, refresh logic
2. **Vertex AI migration** — backend dispatch, thinking mode, response shape
3. **Floating job widgets / pipeline log** — event filtering, duplicates,
   minimize/restore state
4. **Cancellation flow** — reconciler status normalization, race conditions
5. **Rename / prompt flows** — scope of helpers, async function exports

For changes in these areas: always require user click-through verification.
No exceptions.

## Communication protocol

### Don't recommend things the user has explicitly rejected
If the user says "stop recommending X" — drop it permanently. No
re-mentioning the same recommendation in a different phrasing.

### Don't conflate "looks ready" with "is ready"
- "All static checks pass" = ✅ checks pass
- "Migration is complete" = ❌ wait for user verification first
- "v4.80 is ready" = ❌ pending user click-through validation

### Honest expectation setting
- "1-2 hour fix" — if it's been 3 hours and we're still debugging, say so
- "Live validation pending" — never claim "stable" or "shipped" without it
- "I cannot click-through test Electron" — be upfront about this limit

## What this file is NOT

- This is not a list of "best practices to consider"
- It is the user's binding rules for working on this project
- Future sessions should READ this file first, then proceed
