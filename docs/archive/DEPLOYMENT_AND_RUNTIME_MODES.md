# NBME Self-Assessment Suite — Deployment and Runtime Modes

**Last updated:** 2026-05-18

---

## Overview

The app runs in exactly three modes. They share the same `index.html` source file. Feature availability differs between modes. **Development must always use Electron dev mode.**

---

## Mode 1: Electron Dev (Development — Always Use This)

**How to run:**
```bash
cd "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite"
npm install          # first time only
npm run electron:dev
```

**What it does:**
- Starts `electron/main.js` directly via the Electron binary
- Spawns an embedded HTTP server at `127.0.0.1:8888` (fallback `8080`, then OS-assigned)
- Loads `index.html` from the project root via that server URL
- Changes to `index.html` are reflected immediately on next `Cmd+R` reload (no restart required)

**Verification:**
- Open devtools (`Cmd+Option+I`) → Network tab → confirm the document URL is `http://127.0.0.1:8888/` or `http://localhost:8888/`
- `window.nbmeDesktop?.isElectron` returns `true`
- `window.location.href` shows `http://127.0.0.1:8888/`

**All features available:** Quiz, timers, focus mode, hints, tagging, Drive sync, flashcards, incorrects generation, UWorld/Divine Gemini refinement (via IPC).

---

## Mode 2: GitHub Pages (Browser — No IPC Features)

**URL:** `https://shamsulalamx.github.io/NBME-Self-Assessment-Suite/`

**Source:** Served directly from `main` branch, `index.html` at repo root. Deployed automatically on every push to `main` via GitHub Pages.

**How to deploy a change:**
```bash
git add index.html
git commit -m "Your commit message"
git push origin main
```
GitHub Pages typically updates within 1–2 minutes. Check the Actions tab in GitHub if the update seems slow.

**What works:** Everything except Electron IPC features.
- ✅ All quiz functionality (timers, focus mode, navigation, explanations)
- ✅ Gemini hints + question tagging (`callGeminiDirect` — direct fetch from renderer)
- ✅ Gemini key entry, storage, Drive sync, and restore
- ✅ NBME Gemini JSON import
- ✅ All non-Gemini import pipelines (OME, Anki, Mehlman)
- ✅ Drive backup and restore (OAuth)
- ✅ Pearl flashcards
- ✅ Incorrects test generation
- ✅ Miscellaneous Documents
- ❌ UWorld Gemini refinement (requires `window.nbmeDesktop.ai.refineUWorldDraft`)
- ❌ Divine Gemini refinement (requires `window.nbmeDesktop.ai.refineDivineDraft`)

**Detection:** `window.nbmeDesktop` is `undefined`. Features gated on `window.nbmeDesktop?.isElectron` are hidden automatically.

**Google Drive OAuth setup:**
- OAuth Client ID: `274374578651-5edirahp87c5hpv69donfpvcr81tmidk.apps.googleusercontent.com`
- Credential type: **Web application** (critical — Desktop type does not support Authorized JavaScript Origins)
- Required origins in Google Cloud Console:
  - `https://shamsulalamx.github.io`
  - `http://localhost:8888`
  - `http://localhost:8080`
- No Redirect URIs needed (GIS token flow, not redirect-based)
- If Drive shows `origin_mismatch`: verify the credential in Google Cloud Console is type "Web application" and all three origins are listed. Changes can take up to a few minutes to propagate.

**`.nojekyll` file:** Present at repo root. Required to prevent GitHub Pages' Jekyll processor from treating underscore-prefixed identifiers as private and mangling them.

---

## Mode 3: Packaged Electron App (Production — NOT For Development)

**Location:**
```
/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/dist/mac-arm64/NBME Self-Assessment Suite.app
```

**How to build:**
```bash
cd "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite"
npm run electron:build:mac
```
Produces the `.app` bundle in `dist/`. Build takes a few minutes. The `dist/` directory is not committed to the repo.

**CRITICAL WARNING:** This bundle contains its own frozen copy of `index.html`:
```
dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html
```
**This file is NOT updated when you edit the project root `index.html`.** Edits are invisible. Multiple debugging sessions were lost because code was "fixed" in the source but the packaged `.app` was always running. (See `DEBUGGING_PITFALLS.md` Pitfall 1.)

**How to manually sync without a full rebuild (emergency fix only):**
```bash
cp "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html" \
   "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html"
```
Verify sizes match:
```bash
wc -c "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/index.html"
wc -c "/Users/shamsulalam/Desktop/NBME Self-Assessment Suite/dist/mac-arm64/NBME Self-Assessment Suite.app/Contents/Resources/app/index.html"
```

**All features available:** All Electron IPC features (UWorld/Divine Gemini) plus everything in browser mode. Identical feature set to Electron dev, but running a frozen snapshot.

---

## Feature Matrix

| Feature | Electron dev | GitHub Pages | Packaged .app |
|---|---|---|---|
| Quiz engine, timers, focus mode | ✅ | ✅ | ✅ |
| Gemini hints + tagging | ✅ | ✅ | ✅ |
| Drive backup / restore | ✅ | ✅ | ✅ |
| Pearl flashcards | ✅ | ✅ | ✅ |
| Incorrects test generation | ✅ | ✅ | ✅ |
| NBME Gemini JSON import | ✅ | ✅ | ✅ |
| OME / Anki / Mehlman pipelines | ✅ | ✅ | ✅ |
| Miscellaneous Documents | ✅ | ✅ | ✅ |
| UWorld Gemini refinement | ✅ | ❌ | ✅ |
| Divine Gemini refinement | ✅ | ❌ | ✅ |
| Reflects source edits immediately | ✅ (on reload) | ✅ (after push) | ❌ (rebuild required) |
| Use for development | ✅ ALWAYS | ❌ | ❌ |

---

## Decision Tree: Which Mode to Use

```
Am I editing code?
├─ YES → npm run electron:dev
└─ NO

Am I testing a bug fix?
├─ YES → npm run electron:dev
└─ NO

Am I sharing the app with someone on another computer?
├─ YES → GitHub Pages URL
└─ NO

Am I distributing a packaged Mac app?
└─ YES → npm run electron:build:mac, then open dist/mac-arm64/...app
```

---

## Electron Server Details

The embedded server in `electron/main.js`:
- Binds to `127.0.0.1` only (not `0.0.0.0`)
- Primary port: `8888`, fallback `8080`, then OS-assigned
- Path-traversal guard: `resolveLocalPath()` enforces that all served paths stay within the app directory
- MIME type allowlist: unknown types rejected with `403`
- Serves `index.html` and static assets from the project root

---

## Stable Tagged Milestones (for reference)

| Tag | Pipeline | Notes |
|---|---|---|
| `mehlman-v1-stable` | Mehlman | Deterministic notes pipeline complete |
| `divine-v1-stable` | Divine Podcasts | Deterministic draft layer complete |
| `divine-gemini-v1-stable` | Divine Podcasts | Electron IPC Gemini refinement complete |
| `uworld-gemini-v1-stable` | UWorld | Electron IPC Gemini refinement, JSON extraction hardened |
| `ome-v1-stable` | OME | Cluster index provenance bug fixed, pipeline complete |
| `anki-v1-stable` | Anki | Approval-state and save-path bugs fixed, pipeline complete |
