# NBME Self-Assessment Suite — Architecture Reference

Last updated: 2026-05-11  
Covers: Electron runtime, IPC/Gemini flow, persistence, all six source pipelines, Divine pipeline detail, deterministic vs AI responsibility split, anti-copy/validation, provenance, error handling.

---

## 1. Platform Overview

The app is a single-page application written in plain HTML, CSS, and JavaScript inside `index.html`. It runs inside an Electron shell that provides:

- A local HTTP server (`http://localhost:8888`, fallback `8080`, fallback OS-assigned port) serving `index.html` and static assets
- A narrow preload bridge exposing AI methods to the renderer
- An IPC main process that owns all Gemini calls and API key access

**Browser/Netlify mode** remains available as a compatibility/rollback path but is no longer the primary workflow for AI refinement. All active Gemini work runs through Electron IPC.

---

## 2. Electron Runtime Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Electron Main Process  (electron/main.js)                   │
│                                                             │
│  ┌─────────────────────┐  ┌──────────────────────────────┐ │
│  │  Embedded HTTP      │  │  IPC Handlers                │ │
│  │  Server             │  │                              │ │
│  │  127.0.0.1:8888     │  │  nbme:ai:get-status          │ │
│  │  serves index.html  │  │  nbme:ai:refine-uworld-draft │ │
│  │  and static assets  │  │  nbme:ai:refine-divine-draft │ │
│  └─────────────────────┘  └──────────────────────────────┘ │
│                                                             │
│  process.env.GEMINI_API_KEY  (never leaves main process)   │
└────────────────────────┬────────────────────────────────────┘
                         │ contextBridge
┌────────────────────────▼────────────────────────────────────┐
│ Preload  (electron/preload.js)                              │
│                                                             │
│  window.nbmeDesktop = Object.freeze({                       │
│    isElectron: true,                                        │
│    ai: {                                                    │
│      getStatus(),         → invoke('nbme:ai:get-status')   │
│      refineUWorldDraft(), → invoke('nbme:ai:refine-...')   │
│      refineDivineDraft()  → invoke('nbme:ai:refine-...')   │
│    }                                                        │
│  })                                                         │
│                                                             │
│  contextIsolation: true  |  nodeIntegration: false         │
│  sandbox: true           |  webSecurity: true              │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP  (localhost)
┌────────────────────────▼────────────────────────────────────┐
│ Renderer  (index.html)                                      │
│                                                             │
│  All pipeline logic, UI, quiz engine, parsers, storage,     │
│  and review flows live here.                                │
│                                                             │
│  Detects Electron via: window.nbmeDesktop?.isElectron       │
│  AI calls go through: window.nbmeDesktop.ai.*               │
│  No direct Node, no API key access, no raw IPC.             │
└─────────────────────────────────────────────────────────────┘
```

### Security boundaries

- `GEMINI_API_KEY` is read from `process.env` only inside `electron/main.js`. It never reaches the renderer, localStorage, Drive backups, debug exports, or packaged assets.
- The preload exposes a frozen, narrow API surface. No raw IPC wrappers, no filesystem access, no broad Node APIs are exposed.
- The embedded server binds to `127.0.0.1` only and enforces a path-traversal guard (`resolveLocalPath`) and an allowlist of known MIME types. Unknown types are rejected with `403`.

---

## 3. Renderer ↔ Preload ↔ IPC ↔ Gemini Flow

Shown for the Divine draft refinement path; UWorld follows the same pattern.

```
Renderer (index.html)
│
│  window.nbmeDesktop.ai.refineDivineDraft(payload)
│  payload = { conceptType, clusterSummary, sourceContext,
│              sourceMeta, provenance, variantType? }
▼
Preload (electron/preload.js)
│
│  ipcRenderer.invoke('nbme:ai:refine-divine-draft', payload)
▼
Main Process (electron/main.js)
│
│  1. sanitizeDivineDraftInput(payload)
│     ├─ null check, type check
│     ├─ clamp clusterSummary ≤400 chars, reject <20 chars
│     ├─ clamp conceptType ≤80, sourceContext ≤300
│     ├─ require sourceMeta.draftId + sourceMeta.clusterId
│     └─ normalize provenance arrays
│
│  2. buildDivineRefinementPrompt(sanitizedInput)
│     ├─ clusterSummary as sole medical source
│     ├─ sourceContext labeled "do not copy"
│     └─ instructs Gemini to extract extractedTestableFact
│        and determine questionType
│
│  3. fetch(GEMINI_ENDPOINT, { x-goog-api-key: process.env.GEMINI_API_KEY })
│     AbortController timeout: 30 000 ms
│     temperature: 0.30  |  maxOutputTokens: 2400
│     responseMimeType: 'application/json'
▼
Gemini API  (gemini-2.5-flash)
│
│  raw JSON: { extractedTestableFact, questionType, stem,
│              choices[5], correctAnswer, teachingPoint,
│              rationales{A-E}, confidence, needsReview, warnings }
▼
Main Process (electron/main.js)
│
│  4. extractGeminiJson(data)
│     ├─ attempt 1: strip markdown fences, JSON.parse
│     └─ attempt 2: brace-depth scan (handles prose around JSON)
│
│  5. validateDivineRefinedDraft(parsed, sanitizedInput)
│     ├─ extractedTestableFact ≥10 chars
│     ├─ questionType nonempty, ≤80 chars
│     ├─ stem ≥40 chars
│     ├─ exactly 5 choices, labels A–E in order
│     ├─ correctAnswer ∈ {A,B,C,D,E}
│     ├─ teachingPoint ≥20 chars
│     ├─ rationales A–E all nonempty
│     ├─ anti-copy: 8-word overlap check (stem + each choice vs sourceContext)
│     ├─ podcast-voice markers rejected in stem
│     └─ provenance assembled from sanitizedInput — Gemini output not trusted
│
│  6. return { ok: true, refinedDraft }
│     or safeError(errorCode, message)
▼
Renderer (index.html)
│
│  review UI → user approves → controlled save into real test
└─
```

### IPC error codes

| Code | Meaning |
|---|---|
| `NO_API_KEY` | `GEMINI_API_KEY` not set in environment |
| `RATE_LIMITED` | HTTP 429 from Gemini |
| `NETWORK_ERROR` | Network failure or non-2xx non-429 response |
| `TIMEOUT` | AbortController fired at 30 s |
| `MODEL_RESPONSE_INVALID` | Parse failure, schema failure, or sanitization failure |

No API key, prompt text, or source content appears in any error message returned to the renderer.

---

## 4. Local Persistence Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ localStorage  (metadata only, large payloads stripped)       │
│                                                              │
│  source folders, subfolders, tests, questions (text only),  │
│  choices, explanations, tags, history, flags, marks,        │
│  notes, settings, hint usage counter                        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ IndexedDB  (FigureStore)                                     │
│                                                              │
│  cropped stem images, figures, exhibits,                    │
│  restored Drive images                                       │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ Google Drive  (durable cross-device backup)                  │
│                                                              │
│  app folder: "NBME Self-Assessment Suite"                   │
│  manifest:   nbme_manifest.json                             │
│  image files uploaded from FigureStore                      │
│  Drive file IDs stored in q.images                          │
│  restore: tests + metadata + images → local app             │
└──────────────────────────────────────────────────────────────┘
```

**Rules:**
- `DB.save()` and `storagePayload()` guard against writing large image data to localStorage.
- Images always travel through `FigureStore` (IndexedDB), not localStorage.
- Google Drive is the only cross-device persistence path. Drive OAuth requires an approved HTTP/HTTPS origin; `file://` is not supported.
- Supabase was removed and must not be reintroduced unless explicitly requested.

**Save gates for AI-generated content (all pipelines):**  
Approved draft → quiz-object preview → explicit target subfolder → nonempty test name → inline review confirmation → controlled save. Browser `prompt()`/`confirm()` are not used in any Electron save flow.

---

## 5. Pipeline Separation Philosophy

Each source type has its own flat functional pipeline. There are no shared base classes, no prototype chains, and no inheritance between pipelines.

```
NBME PDF      → OCR/parser/render path
UWorld DOCX   → concept extraction → Gemini refinement
OME PDF       → PDF.js text-layer → deterministic drafts
Anki .txt     → normalized cards → deterministic drafts
Mehlman       → structured notes → deterministic drafts
Divine audio  → transcript → cleaning → clusters → Gemini refinement
```

**Isolation rules:**
- No pipeline modifies another pipeline's parser, OCR, clustering, or save logic.
- Provenance namespaces are separate per pipeline (`draftId`, `clusterId` carry their pipeline origin).
- Save targets are scoped per pipeline: each pipeline requires its own explicit subfolder.
- A bug fix in one pipeline must not touch unrelated pipelines.

---

## 6. Deterministic vs AI Responsibilities

The app uses a two-layer architecture for question generation. The boundary is strict.

### Deterministic layer (renderer + main process sanitization/validation)

- Parses and normalizes source content
- Builds intermediate teaching clusters / concept clusters
- Produces deterministic draft scaffolds (usable without Gemini)
- Sanitizes and clamps all renderer-supplied fields before they enter a prompt
- Assembles all provenance fields server-side (main process)
- Enforces schema validation on Gemini output
- Runs anti-copy detection
- Runs podcast-voice marker rejection
- Enforces save gates

The deterministic layer can stand alone. Gemini refinement is an enhancement, not a dependency.

### Gemini layer (main process prompt + Gemini API)

- Identifies the testable medical fact from a teaching cluster (Divine)
- Determines the question type
- Generates a clinical vignette stem and five answer choices
- Provides rationales and a teaching point
- Produces `confidence`, `needsReview`, and `warnings`
- Does **not** manage provenance, save targets, or structural decisions
- Output is validated and normalized by the deterministic layer before use; nothing from Gemini output is trusted for provenance

---

## 7. Why Gemini Now Extracts Testable Facts Dynamically

### The old approach (prior to divine-gemini-v1-stable)

The renderer attempted to pre-extract a structured diagnostic criterion from the transcript — duration thresholds, DSM field names, polarity values — and packaged these into a typed struct. Gemini received this pre-parsed struct as its medical source and was instructed to test only that extracted criterion. The prompt also included per-variant guidance tables that grew with each new question type.

**Problems with that approach:**

1. **Fragility**: Podcast transcripts don't always align with clean criterion-extractable structures. A lecture on mechanism, management, or risk factors doesn't have a "duration" or "polarity" to extract.
2. **Hardcoded coupling**: The app embedded disease-specific logic (DSM-style fields, duration-determines-diagnosis, age-threshold-determines-diagnosis) that had to be maintained and extended for each new topic type.
3. **Prompt rigidity**: Per-variant guidance tables grew with each new question type, making the prompt harder to maintain and less generalizable.
4. **Mismatch risk**: If the renderer incorrectly classified a teaching point, the entire prompt was built on a wrong premise.

### The new approach (divine-gemini-v1-stable onward)

The renderer sends the **cleaned teaching cluster summary** (`clusterSummary`, ≤400 chars) and lets Gemini identify what's testable.

```
Old: renderer pre-extracts criterion → sends typed criterion struct → Gemini tests that criterion only
New: renderer sends clusterSummary → Gemini extracts extractedTestableFact → Gemini generates vignette
```

**Benefits:**

- No hardcoded disease-specific logic in the app. Any medical topic — mechanism, management, timeline, contraindication, risk factor — is handled by the same prompt.
- `extractedTestableFact` is explicit in the output, making it auditable: reviewers can see exactly what Gemini decided was testable before approving the draft.
- `questionType` is Gemini-determined from a fixed enum, not renderer-imposed.
- The prompt is stable across all topic types; new teaching areas don't require new prompt variants.
- `sourceContext` is preserved as a provenance/copy-detection field only (≤300 chars, labeled "do not copy"), so Gemini has coherence context without being instructed to reproduce it.

---

## 8. Divine Transcript Pipeline — Detailed Flow

```
Raw transcript text (podcast audio → text)
│
▼  CLEANING
│  Remove timestamps, speaker labels, filler text,
│  normalize whitespace and encoding artifacts
│
▼  SEGMENTATION  (segmentation into coherent units)
│  Break cleaned transcript into segments at sentence
│  or paragraph boundaries
│
▼  CONCEPT EXTRACTION
│  Identify medical concepts within each segment
│  Each concept carries: text, source segment reference
│
▼  CLUSTERING
│  Group related concepts into teaching clusters
│  Each cluster = one coherent learning objective
│
▼  CLUSTER SUMMARY (clusterSummary)
│  Distill each cluster into ≤400 chars of clean medical prose
│  This is the ONLY medical content sent to Gemini
│
▼  DETERMINISTIC DRAFT SCAFFOLD
│  Generate a question skeleton from cluster metadata
│  Usable as a fallback if Gemini is declined or unavailable
│  sourceMeta.draftId + sourceMeta.clusterId assigned here
│
▼  GEMINI REFINEMENT  (nbme:ai:refine-divine-draft)
│  Main process receives sanitized payload:
│    clusterSummary  → sole medical source
│    sourceContext   → provenance/copy-detection only
│    conceptType     → optional hint
│    variantType     → optional hint
│    sourceMeta      → draftId, clusterId, sourceName, sourceHash
│    provenance      → sourceSegmentIds, lineRanges, timestampRanges
│
│  Gemini returns:
│    extractedTestableFact  (what Gemini identified as testable)
│    questionType           (from fixed enum)
│    stem, choices[5], correctAnswer
│    teachingPoint, rationales{A-E}
│    confidence, needsReview, warnings
│
│  Main process validates and assembles result:
│    all provenance from sanitizedInput (never from Gemini)
│    anti-copy check, voice-marker check, schema check
│    generationMethod: 'electron-gemini-divine-cluster-v2'
│
▼  REVIEW
│  Renderer displays refined draft
│  User sees: extractedTestableFact, questionType, stem,
│             choices, correct answer, teaching point, rationales
│  User approves or rejects each draft individually
│
▼  CONTROLLED SAVE
│  Approved drafts only → quiz-object preview
│  Explicit Divine subfolder target + nonempty test name
│  Inline review confirmation → save into real test
```

---

## 9. Anti-Copy and Validation Strategy

All validation gates run in `electron/main.js` after Gemini returns. The renderer does not validate Gemini output.

### 8-word verbatim overlap check

`divineCopyOverlapDetected(text, sourceContext)`:

- Splits both strings into word arrays (lowercase, whitespace-separated)
- Slides an 8-word window across `sourceContext`
- Checks whether any 8-word n-gram appears in the target text
- Applied to the stem and each of the five answer choices independently
- A match causes hard rejection: `MODEL_RESPONSE_INVALID`

This prevents Gemini from lifting podcast transcript phrasing into the question.

### Podcast/coaching voice markers

`DIVINE_STEM_VOICE_MARKERS` (regex array, checked against the stem):

```
/\byou need to\b/i    /\bI think\b/i         /\bremember\b/i
/\bdon'?t forget\b/i  /\bhigh[\s-]yield\b/i  /\bboards?\b/i
/\bpodcast\b/i        /\bI want you to\b/i   /\bthey give you\b/i
```

A match causes hard rejection.

### Schema validation sequence (validateDivineRefinedDraft)

1. `extractedTestableFact`: string, trimmed, ≥10 chars
2. `questionType`: string, nonempty, clamped ≤80 chars
3. `stem`: string, ≥40 chars, clamped ≤3000
4. `choices`: exactly 5, labels A B C D E in order, each text nonempty
5. `correctAnswer`: must be A, B, C, D, or E
6. `teachingPoint`: string, ≥20 chars, clamped ≤1200
7. `rationales`: all five labels present and nonempty
8. Anti-copy check (stem + each choice)
9. Voice-marker check (stem only)
10. Warnings normalized; `'requires review before use'` always appended

### extractGeminiJson hardening (UWorld and Divine)

Two-attempt extraction prevents fragile single-parse failures:

1. Strip leading/trailing markdown fences (```` ```json ... ``` ````), attempt `JSON.parse`
2. If that fails: scan for first `{`, walk brace depth tracking string/escape state, extract first complete top-level JSON object

Parse failures and schema validation failures return separate `MODEL_RESPONSE_INVALID` messages with distinct reasons.

---

## 10. NBME Gemini JSON Importer Pipeline (nbme-gemini-json)

**Added:** 2026-05-12. This is a new sixth pipeline distinct from all others.

Unlike every other pipeline (OCR-based PDF, DOCX, transcript), this pipeline receives a pre-structured JSON file produced by an external AI step (running the full exam through Gemini with a structured extraction prompt). The app does not call Gemini — it imports, validates, normalizes, and saves.

### Pipeline flow

```
External AI step (outside this app)
│
│  User runs NBME exam through Gemini with extraction prompt
│  Gemini returns a JSON file:
│    { questions: [{ questionNumber, stem, answerChoices, correctAnswer,
│                    educationalObjective, explanationSections, figureRefs }] }
│
▼  USER UPLOADS JSON FILE
│  Opens #modal-nbme-gemini-json-import via App.openNbmeGeminiJsonImportModal()
│  File input reads JSON text
│
▼  PARSE + VALIDATE  (validateNbmeGeminiJsonImport)
│  Checks each question for required fields
│  Returns: { isValid, blockingErrors[], warnings[], questionResults[], counts{} }
│  Blocking errors: missing stem, choices, correctAnswer, or letter mismatch
│  Warnings: missing educationalObjective, explanationSections, or empty figureRefs.visibleText
│
▼  NORMALIZE  (normalizeNbmeGeminiJsonImport)
│  Maps input schema → internal quiz schema
│  q.t          ← question.stem  (FULL TEXT, no truncation)
│  q.c          ← question.correctAnswer
│  q.o          ← question.answerChoices (letter + text)
│  q.correctBlurb        ← _ngjBuildCorrectBlurb(explanationSections)
│  q.educationalObjective ← question.educationalObjective
│  q.e          ← _ngjBuildPerChoiceExplanations(explanationSections, answerChoices)
│  q.metadata.figureRefs ← question.figureRefs
│  q.metadata.figureAttachments ← {} (populated later by user upload)
│  q.metadata.sourceType = 'nbme-gemini-json'
│
▼  PREVIEW RENDER  (renderNbmeGeminiJsonPreview)
│  Shows table of all questions: number, stem (full, no truncation), choices, answer
│  Validation summary: counts of ok / warning / error questions
│
▼  FIGURE ATTACHMENT  (renderNbmeGeminiJsonFigureAttachSection)
│  If any figureRefs exist across any question: shows figure attachment panel
│  Each figureRef row: figureId, location, optional visibleText preview
│  User can upload an image file per figureId (max 2.5 MB, read as base64 DataURL)
│  _nbmeGeminiJsonImport.figureAttachments[figureId] = dataUrl
│  Attachment is optional — questions save without it (using placeholder or visibleText table)
│
▼  SAVE  (createTestFromNbmeGeminiJsonImport)
│  Validates test name and target folder are set
│  Warns if total figure attachment data > 3 MB (localStorage quota risk)
│  Creates test via DB.createTest(folderId, testName, normalizedQuestions)
│  Per question: copies relevant figureAttachments from global state into q.metadata.figureAttachments
│  Updates test with final questions via DB.updateTest(testId, { questions })
│
▼  QUIZ / REVIEW
│  renderQuestion() shows q.t as the stem
│  buildQuestionStemHTML() → buildStemHTML(q.t) → _replaceFigureMarkersInStemHtml(html, q)
│  _replaceFigureMarkersInStemHtml replaces [FIGURE: figureId] with _ngjFigureToHTML(figureId, q)
│  _ngjFigureToHTML renders: attached image | visibleText table | placeholder
│  buildExplanationHTML() renders: educationalObjective | correctBlurb | q.e per-choice
```

### Figure rendering chain

```
window.buildQuestionStemHTML(q, highlightedStemHtml)     ~line 5168
  └─ window.buildStemHTML(q.t)                           ~line 5140
  └─ window._replaceFigureMarkersInStemHtml(html, q)     ~line 5228
       └─ window._ngjFigureToHTML(figureId, q)           ~line 5183
            ├─ if q.metadata.figureAttachments[figureId] → <img src="data:...">
            ├─ if figureRef.visibleText.length > 0       → lab-values <table>
            └─ else                                       → placeholder <div>
```

### Explanation rendering chain

Both `buildExplanationHTML` functions render in this order:
1. `q.educationalObjective` → blue bordered block, `textContent` (safe, plain text)
2. `q.correctBlurb` → `innerHTML` (pre-escaped HTML from `_ngjBuildCorrectBlurb`)
3. `q.explanation` → legacy plain-text fallback (PDF-OCR questions)
4. `q.e` → per-choice explanations, one block per letter

### Key state object

```javascript
let _nbmeGeminiJsonImport = {
  rawText: '', parsed: null, validation: null,
  normalizedItems: [], fileName: '', testName: '',
  targetFolder: '', confirmed: false,
  figureAttachments: {},    // { figureId: base64DataUrl }
  lastSaveResult: null, lastSaveError: null
};
```

### Outstanding issues as of 2026-05-12

- **UNRESOLVED:** Quiz stem truncation (Q1/Q9/Q11/Q24 show 1–2 lines). See `BUGS_AND_NEXT_STEPS.md` BUG-001.
- **Not yet end-to-end validated:** Explanation rendering (VAL-001), figure rendering (VAL-002), "save valid only" button (VAL-003).

---

## 12. Provenance Handling

Provenance is the chain of evidence linking a generated question back to its source material.

### Principle: provenance is assembled server-side, never trusted from Gemini

All provenance fields in the result object are built from the sanitized input that the main process received — not from anything Gemini returns. Gemini cannot inject, overwrite, or fabricate provenance.

### Divine provenance fields (result object)

| Field | Source |
|---|---|
| `draftId` | `sanitizedInput.sourceMeta.draftId` |
| `clusterId` | `sanitizedInput.sourceMeta.clusterId` |
| `sourceName` | `sanitizedInput.sourceMeta.sourceName` |
| `sourceHash` | `sanitizedInput.sourceMeta.sourceHash` |
| `provenance.sourceSegmentIds` | normalized from renderer payload |
| `provenance.originalLineRanges` | normalized from renderer payload |
| `provenance.cleanedLineRanges` | normalized from renderer payload |
| `provenance.timestampRanges` | normalized from renderer payload |
| `provenance.timestampRange` | normalized from renderer payload |
| `generationMethod` | hardcoded: `'electron-gemini-divine-cluster-v2'` |
| `model` | hardcoded: `GEMINI_MODEL` constant |
| `createdAt` | `new Date().toISOString()` at validation time |

### Sanitization rules for renderer-supplied provenance

- All string fields clamped via `clampText(value, maxLength)` which also collapses internal whitespace
- All array fields normalized via `normalizeStringArray` (max 12 items, each item clamped to 160 chars)
- `timestampRange` object fields clamped individually (20 chars each)
- Provenance arrays sliced to max 12 entries to prevent large renderer payloads
- `sourceMeta.draftId` and `sourceMeta.clusterId` are required; null return if either is absent

---

## 11. Error Handling Philosophy (Divine/UWorld Gemini)

### Principle: fail closed, fail silently toward the user, never expose internals

- All IPC handlers return `{ ok: false, errorCode, message }` on failure — never throw to the renderer
- `safeError(errorCode, message)` is the single error factory; `message` must never contain API keys, prompt text, or source content
- Error codes are a fixed enum (see Section 3); the renderer branches on `errorCode`, not message strings
- `AbortController` at 30 s covers all Gemini calls; `AbortError` maps to `TIMEOUT`
- `TypeError` from `fetch` maps to `NETWORK_ERROR`; unexpected throws map to `MODEL_RESPONSE_INVALID`
- The `finally` block always clears the timeout regardless of success or failure path
- No auto-retry logic. No silent re-queuing. One request, one result.
- Parse failures and schema failures are distinct error messages so reviewers can distinguish "Gemini returned unparseable text" from "Gemini returned valid JSON that failed schema validation"

### What is never logged

- `GEMINI_API_KEY` or any prefix/suffix of it
- Prompt text (which contains `clusterSummary` or `sourceContext`)
- Source content from the renderer
- Gemini raw response body (logged only internally during development, not in production paths)

---

## 13. Source Pipeline Summary

| Pipeline | Input | Gemini | Stable tag |
|---|---|---|---|
| NBME | PDF (OCR + crop) | hints + tags via Netlify/browser | — |
| NBME Gemini JSON | Pre-structured JSON (external AI step) | none (JSON is already AI output) | — (added 2026-05-12) |
| UWorld | DOCX | Electron IPC: `refine-uworld-draft` | `uworld-gemini-v1-stable` |
| OME | PDF (PDF.js text-layer) | none in v1 | `ome-v1-stable` |
| Anki | `.txt` export | none in v1 | `anki-v1-stable` |
| Mehlman | structured text notes | none in v1 | `mehlman-v1-stable` |
| Divine Podcasts | transcript text | Electron IPC: `refine-divine-draft` | `divine-v1-stable`, `divine-gemini-v1-stable` |

All pipelines share these invariants:
- Flat functional pipeline code; no shared base classes
- Controlled save gate: approved → preview → explicit target → name → confirm
- Provenance scoped per pipeline
- Isolation: bugs in one pipeline must not affect others

---

## 14. Key Files

| File | Role |
|---|---|
| `index.html` | Entire renderer: all pipeline logic, UI, quiz engine, storage calls |
| `electron/main.js` | Main process: HTTP server, IPC handlers, Gemini calls, all sanitization/validation |
| `electron/preload.js` | Narrow contextBridge surface; exposes only `window.nbmeDesktop` |
| `netlify/` | Legacy/rollback Netlify Functions for browser Gemini (tags, hints) |
| `package.json` | Electron app entry point and build config |

> **Note:** `app.js`, `db.js`, `ocr.js`, `quiz.js`, `results.js`, `style.css`, `css/`, `js/` are legacy split files that are not the active implementation. All active code is in `index.html`.
