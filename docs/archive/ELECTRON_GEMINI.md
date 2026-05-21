# Electron Gemini Integration — Architecture Reference

Last updated: 2026-05-11  
Model: `gemini-2.5-flash`  
Active IPC channels: `nbme:ai:get-status`, `nbme:ai:refine-uworld-draft`, `nbme:ai:refine-divine-draft`

---

## 1. Architecture Overview

All Gemini API access is owned by the Electron main process. The renderer never holds an API key, never calls Gemini directly, and never touches `process.env`. The preload exposes a frozen, narrow bridge that forwards calls through IPC.

```
Renderer (index.html)
│
│  window.nbmeDesktop.ai.refineUWorldDraft(payload)
│  window.nbmeDesktop.ai.refineDivineDraft(payload)
│  window.nbmeDesktop.ai.getStatus()
│
│  ← payload built from sanitized, in-memory pipeline state
│  ← no API key, no prompt text, no env access
│
▼  contextBridge (contextIsolation: true, sandbox: true)
│
Preload (electron/preload.js)
│
│  Object.freeze({ isElectron: true, ai: { getStatus, refineUWorldDraft, refineDivineDraft } })
│  ipcRenderer.invoke('nbme:ai:refine-*', payload)
│
▼  ipcMain.handle
│
Main Process (electron/main.js)
│
│  1. sanitize*(payload)           clamp, reject malformed, require key fields
│  2. build*Prompt(input)          assemble prompt from sanitized fields
│  3. fetch(GEMINI_ENDPOINT, ...)  AbortController, 30 s timeout
│  4. extractGeminiJson(data)      two-attempt JSON extraction
│  5. validate*(parsed, input)     schema + anti-copy + voice-marker + provenance
│  6. return { ok, refinedDraft }  or safeError(errorCode, message)
│
▼  contextBridge reply
│
Renderer
│
│  result.ok → store draft.refinedDraft, re-render
│  !result.ok → store draft.refinementError, show user-friendly message
```

### Key security properties

| Property | Value |
|---|---|
| `GEMINI_API_KEY` source | `process.env` in main.js only |
| API key exposure to renderer | Never |
| API key in localStorage | Never |
| API key in Drive backup | Never |
| API key in debug exports | Never |
| `contextIsolation` | `true` |
| `sandbox` | `true` |
| `nodeIntegration` | `false` |
| Preload API surface | Frozen object — three methods only |

---

## 2. IPC Channels

### `nbme:ai:get-status`

Returns current AI availability state. No payload. No Gemini call.

```json
{
  "available": true,
  "provider": "gemini",
  "model": "gemini-2.5-flash",
  "hasApiKey": true,
  "desktopMode": true
}
```

### `nbme:ai:refine-uworld-draft`

Refines a UWorld deterministic draft scaffold into a Step 2/NBME-style question using the source concept and draft as medical input.

### `nbme:ai:refine-divine-draft`

Refines a Divine deterministic scaffold using a teaching-cluster summary as the sole medical input. Gemini extracts the testable fact itself.

---

## 3. Shared IPC Patterns

All IPC handlers in `electron/main.js` share the same structural skeleton:

```javascript
ipcMain.handle('nbme:ai:refine-*', async (_event, payload) => {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return safeError('NO_API_KEY', '...');

  const input = sanitize*(payload);
  if (!input) return safeError('MODEL_RESPONSE_INVALID', '...');

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const response = await fetch(GEMINI_ENDPOINT, {
      method: 'POST',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', 'x-goog-api-key': apiKey },
      body: JSON.stringify({ contents: [...], generationConfig: { ... } })
    });

    if (response.status === 429) return safeError('RATE_LIMITED', '...');
    if (!response.ok)            return safeError('NETWORK_ERROR', '...');

    const data = await response.json();

    let parsed;
    try   { parsed = extractGeminiJson(data); }
    catch { return safeError('MODEL_RESPONSE_INVALID', '...'); }

    let refinedDraft;
    try   { refinedDraft = validate*(parsed, input); }
    catch { return safeError('MODEL_RESPONSE_INVALID', '...'); }

    return { ok: true, refinedDraft };
  } catch (err) {
    if (err?.name === 'AbortError') return safeError('TIMEOUT', '...');
    if (err instanceof TypeError)   return safeError('NETWORK_ERROR', '...');
    return safeError('MODEL_RESPONSE_INVALID', '...');
  } finally {
    clearTimeout(timeout);
  }
});
```

### Shared utility functions

| Function | Purpose |
|---|---|
| `safeError(errorCode, message)` | Returns `{ ok: false, errorCode, message }` — never throws, never exposes internals |
| `clampText(value, maxLength)` | `String(value).replace(/\s+/g, ' ').trim().slice(0, maxLength)` — safe on null/undefined |
| `normalizeStringArray(value, maxItems)` | Filters non-empty, clamps each item to 160 chars, caps at maxItems |
| `extractGeminiJson(data)` | Two-attempt JSON extraction (see §8) |

---

## 4. Sanitization Philosophy

Sanitization runs in the main process, before any field enters a prompt. The renderer's values are never trusted.

### Principles

1. **Clamp before use** — every string field passes through `clampText(value, maxLength)`. This collapses internal whitespace, trims, and slices. It handles `null`, `undefined`, and non-string values safely.
2. **Require critical identity fields** — if a field needed for provenance (`draftId`, `clusterId`, `conceptId`) is missing or empty after clamping, `sanitize*` returns `null` and the handler returns `MODEL_RESPONSE_INVALID` immediately without calling Gemini.
3. **Normalize arrays** — all array fields pass through `normalizeStringArray` or explicit `Array.isArray` guards before slicing.
4. **No renderer trust for provenance** — provenance values from the renderer are clamped and stored in sanitized form, but are used only as audit-trail data. They are never used to authorize actions or change behavior.
5. **Return null on structural failure** — `sanitize*` always returns `null` for any structural issue (wrong type, missing required field, value that fails a minimum-length check). The caller maps `null` to `MODEL_RESPONSE_INVALID` without exposing the specific failure to the renderer.

### Field-level clamping limits (Divine)

| Field | Limit | Required |
|---|---|---|
| `clusterSummary` | ≤400 chars, ≥20 chars | Yes |
| `conceptType` | ≤80 chars | No |
| `sourceContext` | ≤300 chars | No |
| `variantType` | ≤60 chars | No |
| `sourceMeta.draftId` | ≤80 chars | Yes |
| `sourceMeta.clusterId` | ≤80 chars | Yes |
| `sourceMeta.sourceName` | ≤220 chars | No |
| `sourceMeta.sourceHash` | ≤96 chars | No |
| Provenance arrays | ≤12 entries each | No |
| `timestampRange.start/end` | ≤20 chars each | No |

### Field-level clamping limits (UWorld)

| Field | Limit | Required |
|---|---|---|
| `draft.draftId` | ≤80 chars | Yes |
| `draft.stem` | ≤1600 chars | No |
| `draft.choices` | 5 items max | No |
| `draft.correctAnswer` | ≤2 chars | No |
| `draft.teachingPoint` | ≤700 chars | No |
| `concept.conceptId` | ≤80 chars | Yes |
| `concept.topic` | ≤220 chars | No |
| `concept.testedFact` | ≤1600 chars | No |
| `concept.sourceSnippet` | ≤1200 chars | No |
| `sourceMeta.sourceName` | ≤220 chars | No |
| `sourceMeta.sourceHash` | ≤96 chars | No |

---

## 5. Prompt Construction Philosophy

### Principles

- **One medical source per prompt.** The prompt has a clearly labeled primary source. All other fields are secondary or metadata.
- **No raw transcript text as medical input.** The `sourceContext` / `sourceSnippet` fields are appended last, labeled "do not copy" or "provenance only." They exist for coherence checking and anti-copy enforcement — not as medical content.
- **Explicit output schema.** Every prompt includes a `JSON.stringify`-formatted schema example so Gemini knows the exact structure expected. No prose in the schema — only field names with type annotations.
- **Explicit forbidden language.** Podcast/coaching phrases are listed verbatim in the prompt so Gemini avoids them in the stem.
- **Strict JSON only.** The prompt always says: "Return strict JSON only. Do not include markdown fences or explanatory text outside JSON."
- **`responseMimeType: 'application/json'`** is set in `generationConfig` as a belt-and-suspenders measure alongside the prompt instruction.

### Divine prompt structure

```
[System role and output format rules]
[Numbered CRITICAL RULES — 10 items]
[Required JSON schema — JSON.stringify of example object]
[Concept type: <conceptType>]       (if present)
[Variant hint: <variantType>]       (if present)
[Teaching cluster (primary medical input):]
<clusterSummary>
[Source context — provenance only, do NOT copy or echo any phrasing:]
<sourceContext or "(none)">
```

### UWorld prompt structure

```
[System role and output format rules]
[Numbered rules — 10 items including no-copy, no-coaching-language]
[Required JSON schema — JSON.stringify of example object]
[Input:]
<JSON.stringify of { draft, concept, sourceBlockIds, sourceMeta }>
```

### Gemini generation config (both pipelines)

| Parameter | UWorld | Divine |
|---|---|---|
| `responseMimeType` | `'application/json'` | `'application/json'` |
| `temperature` | `0.25` | `0.30` |
| `maxOutputTokens` | `2200` | `2400` |

---

## 6. Why Gemini Receives Teaching-Cluster Summaries (Not Raw Transcript Text)

Sending raw podcast transcript text to Gemini as a medical source would produce questions that are unreliable or unusable for three reasons:

### 1. Podcast voice contaminates vignette stems

Transcripts contain first-person coaching register: "remember", "high yield", "I think", "they give you a question about", "don't forget". If Gemini receives this phrasing as its medical source, stems reproduce that register. The anti-copy and voice-marker gates would then reject the response — or worse, pass a response that carries a subtle coaching tone not caught by regex.

The `clusterSummary` is the voice-stripped version of the same content. `VOICE_STRIP_PHRASES` removes coaching phrases before the field is assembled, so Gemini receives medical prose rather than teaching phrasing.

### 2. Raw transcript contains promo and meta-commentary mixed with medical content

Podcast transcripts interleave subscription prompts, course advertisements, episode intros, and personal anecdotes with medical teaching. Sending a raw excerpt to Gemini risks grounding a question in promotional content.

The pipeline's cleaning and quality-gate stages (meta-commentary detection, testability scoring) filter this out before `clusterSummary` is constructed.

### 3. The 300-char sourceContext cap prevents transcript reproduction

`sourceContext` (the raw `sourceSnippet`) is capped at 300 chars and labeled "do not copy or echo any phrasing" in the prompt. It reaches the main process only as a provenance anchor and anti-copy reference. Gemini is explicitly instructed not to reproduce it.

The 8-word verbatim overlap check (`divineCopyOverlapDetected`) then enforces this server-side, hard-rejecting any response where Gemini's stem or choices share an 8-word n-gram with `sourceContext`.

---

## 7. Request and Response Schemas

### 7a. Divine — renderer payload (before main-process sanitization)

```json
{
  "conceptType": "mechanism",
  "clusterSummary": "Lithium inhibits adenylyl cyclase and reduces inositol recycling. Therapeutic window is narrow: 0.6–1.2 mEq/L. Toxicity presents with tremor, polyuria, and ataxia.",
  "sourceContext": "so lithium is really the classic mood stabilizer you'll see on boards remember the narrow window",
  "variantType": "mechanism/risk-factor",
  "sourceMeta": {
    "draftId": "divine-draft-00001",
    "clusterId": "divine-cluster-00001",
    "sourceName": "Divine Intervention Podcast, Season 5"
  },
  "provenance": {
    "sourceSegmentIds": ["divine-seg-0003", "divine-seg-0007"],
    "originalLineRanges": [[42, 58], [101, 115]],
    "cleanedLineRanges": [[38, 52], [93, 105]],
    "timestampRanges": [{"start": "00:03:12", "end": "00:04:05"}],
    "timestampRange": {"start": "00:03:12", "end": "00:04:05"}
  }
}
```

### 7b. Divine — Gemini raw response (expected structure)

```json
{
  "extractedTestableFact": "Lithium has a narrow therapeutic window (0.6–1.2 mEq/L); toxicity manifests as tremor, polyuria, and ataxia.",
  "questionType": "mechanism",
  "stem": "A 34-year-old woman with bipolar I disorder maintained on lithium presents with a 3-day history of coarse hand tremor, increased thirst, and difficulty walking a straight line. Her lithium level is 1.8 mEq/L. Which of the following best explains her current symptoms?",
  "choices": [
    {"label": "A", "text": "Lithium toxicity due to levels exceeding the therapeutic range"},
    {"label": "B", "text": "Hypothyroidism from chronic lithium use"},
    {"label": "C", "text": "Nephrogenic diabetes insipidus unrelated to lithium level"},
    {"label": "D", "text": "Serotonin syndrome from a drug interaction"},
    {"label": "E", "text": "Tardive dyskinesia from concurrent antipsychotic use"}
  ],
  "correctAnswer": "A",
  "teachingPoint": "Lithium toxicity occurs when serum levels exceed the therapeutic range of 0.6–1.2 mEq/L. Early signs include tremor, polyuria, and ataxia.",
  "rationales": {
    "A": "Level of 1.8 mEq/L exceeds the therapeutic ceiling; neurologic and renal symptoms are classic for toxicity.",
    "B": "Hypothyroidism from lithium is chronic and presents with fatigue and weight gain, not acute ataxia.",
    "C": "Nephrogenic DI can occur with lithium but does not explain the neurologic findings or elevated level.",
    "D": "Serotonin syndrome requires a serotonergic drug trigger; no such drug is mentioned.",
    "E": "Tardive dyskinesia involves involuntary movements and is a delayed complication of antipsychotics."
  },
  "confidence": 0.91,
  "needsReview": false,
  "warnings": []
}
```

### 7c. Divine — validated result returned to renderer

```json
{
  "extractedTestableFact": "Lithium has a narrow therapeutic window (0.6–1.2 mEq/L); toxicity manifests as tremor, polyuria, and ataxia.",
  "questionType": "mechanism",
  "refinedDraftId": "divine-refined-divine-draft-00001-1k2m3n",
  "draftId": "divine-draft-00001",
  "clusterId": "divine-cluster-00001",
  "sourceName": "Divine Intervention Podcast, Season 5",
  "sourceHash": "",
  "provenance": {
    "sourceSegmentIds": ["divine-seg-0003", "divine-seg-0007"],
    "originalLineRanges": [[42, 58], [101, 115]],
    "cleanedLineRanges": [[38, 52], [93, 105]],
    "timestampRanges": [{"start": "00:03:12", "end": "00:04:05"}],
    "timestampRange": {"start": "00:03:12", "end": "00:04:05"}
  },
  "stem": "A 34-year-old woman with bipolar I disorder...",
  "choices": [...],
  "correctAnswer": "A",
  "teachingPoint": "Lithium toxicity occurs when...",
  "rationales": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."},
  "confidence": 0.91,
  "needsReview": false,
  "warnings": ["requires review before use"],
  "model": "gemini-2.5-flash",
  "generationMethod": "electron-gemini-divine-cluster-v2",
  "createdAt": "2026-05-11T22:00:00.000Z"
}
```

### 7d. UWorld — renderer payload

```json
{
  "draft": {
    "draftId": "uworld-draft-00001",
    "stem": "A 58-year-old man with a history of...",
    "choices": [
      {"label": "A", "text": "..."},
      {"label": "B", "text": "..."},
      {"label": "C", "text": "..."},
      {"label": "D", "text": "..."},
      {"label": "E", "text": "..."}
    ],
    "correctAnswer": "A",
    "teachingPoint": "...",
    "warnings": []
  },
  "concept": {
    "conceptId": "uworld-concept-00001",
    "topic": "Cardiac physiology",
    "testedFact": "Atrial kick contributes approximately 20–30% of end-diastolic volume...",
    "sourceSnippet": "...",
    "confidence": 0.88,
    "warnings": []
  },
  "sourceMeta": {
    "sourceName": "UWorld DOCX Export",
    "sourceHash": "abc123"
  },
  "sourceBlockIds": ["block-001", "block-004"]
}
```

### 7e. UWorld — validated result returned to renderer

```json
{
  "refinedDraftId": "refined-uworld-draft-00001",
  "sourceDraftId": "uworld-draft-00001",
  "sourceConceptId": "uworld-concept-00001",
  "sourceBlockIds": ["block-001", "block-004"],
  "sourceName": "UWorld DOCX Export",
  "sourceHash": "abc123",
  "stem": "...",
  "choices": [...],
  "correctAnswer": "A",
  "teachingPoint": "...",
  "rationales": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "..."},
  "confidence": 0.88,
  "needsReview": false,
  "warnings": ["requires review before use"],
  "model": "gemini-2.5-flash",
  "generationMethod": "electron-gemini-uworld-draft-refinement-v1",
  "createdAt": "2026-05-11T22:00:00.000Z"
}
```

---

## 8. JSON Extraction (`extractGeminiJson`)

Gemini occasionally wraps JSON in markdown fences or includes brief prose before the JSON object despite `responseMimeType: 'application/json'`. Two-attempt extraction handles this robustly without `eval`.

```
Attempt 1: strip leading/trailing markdown fences (``` or ```json), JSON.parse
           → succeeds for well-formed direct responses

Attempt 2: find first '{', walk character-by-character tracking:
           - brace depth (increment on '{', decrement on '}')
           - inString state (toggle on unescaped '"')
           - escape state (set on '\' while inString)
           When depth returns to 0: JSON.parse(text.slice(start, i+1))
           → handles prose before or after the JSON object

If both fail: throw SyntaxError('no valid JSON object found in model response')
             → caller maps to MODEL_RESPONSE_INVALID
```

The brace-scan strategy tracks string and escape state so inner braces inside JSON string values are not counted as object boundaries.

---

## 9. Validation Pipeline

### Divine validation checklist (`validateDivineRefinedDraft`)

| Step | Field | Requirement |
|---|---|---|
| 1 | `extractedTestableFact` | string, trimmed, ≥10 chars |
| 2 | `questionType` | nonempty string, ≤80 chars |
| 3 | `stem` | string, ≥40 chars, ≤3000 chars |
| 4 | `choices` | exactly 5 items |
| 5 | each choice label | A, B, C, D, E in order |
| 6 | each choice text | nonempty |
| 7 | `correctAnswer` | one of A, B, C, D, E |
| 8 | `teachingPoint` | string, ≥20 chars, ≤1200 chars |
| 9 | `rationales.A` through `rationales.E` | all present, all nonempty |
| 10 | stem vs `sourceContext` | no 8-word verbatim overlap |
| 11 | each choice vs `sourceContext` | no 8-word verbatim overlap |
| 12 | stem voice-marker scan | no podcast/coaching phrases |

### UWorld validation checklist (`validateRefinedDraft`)

| Step | Field | Requirement |
|---|---|---|
| 1 | `choices` | exactly 5 items |
| 2 | each choice label | A, B, C, D, E in order |
| 3 | each choice text | nonempty |
| 4 | `stem` | ≥20 chars |
| 5 | `teachingPoint` | ≥8 chars |
| 6 | `correctAnswer` | one of A, B, C, D, E |
| 7 | `rationales.A` through `rationales.E` | all present, all nonempty |

Any failure throws with a specific human-readable message. The handler catches this and returns `safeError('MODEL_RESPONSE_INVALID', ...)`.

---

## 10. Anti-Copy Enforcement

### 8-word verbatim overlap check (`divineCopyOverlapDetected`)

Applied to: Divine IPC only (UWorld does not include this check in v1).

```
srcWords  = sourceContext.toLowerCase().split(/\s+/).filter(Boolean)
testWords = text.toLowerCase().split(/\s+/).filter(Boolean)

if srcWords.length < 8 or testWords.length < 8: return false
testStr = testWords.join(' ')

for i in 0..srcWords.length-8:
    ngram = srcWords[i..i+8].join(' ')
    if ngram in testStr: return true

return false
```

Checked independently against:
- The Gemini-generated `stem`
- Each of the five `choices[].text` values

A match triggers hard rejection: `MODEL_RESPONSE_INVALID` with message "stem/choice contains verbatim overlap with source context (≥8 consecutive words)".

### Podcast-voice marker rejection (stem only)

```javascript
const DIVINE_STEM_VOICE_MARKERS = [
  /\byou need to\b/i,      /\bI think\b/i,
  /\bremember\b/i,         /\bdon'?t forget\b/i,
  /\bhigh[\s-]yield\b/i,   /\bboards?\b/i,
  /\bpodcast\b/i,          /\bI want you to\b/i,
  /\bthey give you\b/i
];
```

Any match in the stem triggers hard rejection: `MODEL_RESPONSE_INVALID` with message "stem contains podcast/coaching language matching /…/".

---

## 11. Provenance Handling

### Core principle

All provenance in the result object is assembled by the main process from the **sanitized input**. Nothing from Gemini's raw response is trusted for provenance. Gemini cannot inject, modify, or fabricate audit-trail data.

### Provenance assembly (Divine)

```
result.draftId        ← sanitizedInput.sourceMeta.draftId
result.clusterId      ← sanitizedInput.sourceMeta.clusterId
result.sourceName     ← sanitizedInput.sourceMeta.sourceName
result.sourceHash     ← sanitizedInput.sourceMeta.sourceHash
result.provenance.*   ← sanitizedInput.provenance.* (all arrays/ranges)
result.model          ← GEMINI_MODEL constant (hardcoded in main.js)
result.generationMethod ← 'electron-gemini-divine-cluster-v2' (hardcoded)
result.createdAt      ← new Date().toISOString() at validation time
result.refinedDraftId ← 'divine-refined-' + draftId + '-' + Date.now().toString(36)
```

### Provenance assembly (UWorld)

```
result.sourceDraftId    ← sanitizedInput.draft.draftId
result.sourceConceptId  ← sanitizedInput.concept.conceptId
result.sourceBlockIds   ← sanitizedInput.sourceBlockIds.slice()
result.sourceName       ← sanitizedInput.sourceMeta.sourceName
result.sourceHash       ← sanitizedInput.sourceMeta.sourceHash
result.model            ← GEMINI_MODEL constant
result.generationMethod ← 'electron-gemini-uworld-draft-refinement-v1'
result.createdAt        ← new Date().toISOString()
result.refinedDraftId   ← 'refined-' + draftId
```

### What Gemini is allowed to contribute to provenance

Nothing. `confidence`, `needsReview`, and `warnings` are accepted from Gemini output but are validated and clamped before use. They do not affect routing, permissions, or save behavior — only display state.

---

## 12. Error Handling Behavior

### Error code reference

| Code | Trigger | Renderer display |
|---|---|---|
| `NO_API_KEY` | `GEMINI_API_KEY` not in `process.env` | "Gemini API key not configured. Open Settings to add it." |
| `RATE_LIMITED` | HTTP 429 from Gemini | "Request timed out (30 s). Check your connection and try again." |
| `NETWORK_ERROR` | Non-2xx/429, or `fetch` `TypeError` | "Network error — no response from Gemini." |
| `TIMEOUT` | `AbortController` fires at 30 s | "Request timed out (30 s). Check your connection and try again." |
| `MODEL_RESPONSE_INVALID` | Parse failure, schema failure, sanitization failure, anti-copy, voice marker | Message varies by specific failure; never exposes internals |

### What is never included in error messages

- `GEMINI_API_KEY` or any portion of it
- Prompt text (which contains `clusterSummary` or `sourceContext`)
- Renderer-supplied transcript content
- Gemini raw response body
- Internal stack traces

The `safeError(errorCode, message)` factory is the sole error-return path for all IPC handlers. It always returns `{ ok: false, errorCode, message }` — it never throws, never logs sensitive fields.

### Retry behavior

**No auto-retry** is implemented in the main process. Each IPC call is one request, one result.

- **Divine pipeline**: per-draft retry button in the renderer UI. The user triggers retry explicitly.
- **UWorld pipeline**: the batch queue (`processNextLiveBatchItem`) has renderer-level pause/cancel/retry controls. Consecutive failures stop the queue (requires manual resume). This logic lives entirely in the renderer; the main process handles one request at a time.

---

## 13. Timeout Behavior

Every Gemini request uses an `AbortController` tied to a 30-second `setTimeout`:

```javascript
const controller = new AbortController();
const timeout = setTimeout(() => controller.abort(), 30000);
try {
  const response = await fetch(GEMINI_ENDPOINT, { signal: controller.signal, ... });
  ...
} catch (err) {
  if (err?.name === 'AbortError') return safeError('TIMEOUT', '...');
  ...
} finally {
  clearTimeout(timeout);  // always clears, even on success
}
```

The `finally` block guarantees the timer is cleared on every code path — success, error, or timeout — preventing timer leaks across IPC calls.

---

## 14. Local-Only API Key Strategy

`GEMINI_API_KEY` is read exclusively from `process.env` inside `electron/main.js`. It is never:

- Stored in `localStorage`, `sessionStorage`, or `IndexedDB`
- Written to Google Drive backups or the manifest
- Included in debug exports, parser artifacts, or JSON exports
- Passed to the renderer or preload in any form
- Embedded in packaged assets or build outputs

The renderer detects Gemini availability by calling `window.nbmeDesktop.ai.getStatus()`, which returns `{ hasApiKey: true/false }` without ever returning the key value itself.

For local development, `GEMINI_API_KEY` is set in the shell environment before launching Electron. For future packaged distribution (not yet implemented), a native secure storage integration would be required — the current approach is appropriate for personal/local use only.

---

## 15. Deterministic Scaffolds vs Gemini-Refined Drafts

Both pipelines produce a deterministic draft first. Gemini refinement is optional and non-destructive — the original scaffold is always preserved.

### Deterministic scaffold

| Property | Value |
|---|---|
| Generated by | Renderer — `generateDivineDraftScaffolds` (Divine) or notes equivalent (UWorld) |
| Medical inference | None — no Gemini, no NLP |
| Stem | Template-based; embeds `sourceSnippet` verbatim in brackets |
| Choices | Labeled `[PLACEHOLDER — ...]` strings |
| Teaching point | Quotes `sourceSnippet` directly |
| `draftMethod` | `'divine-deterministic-scaffold-v1'` |
| Usable without Gemini | Yes — can be approved as `'original'` mode after manual review |
| Suitable for direct exam use | No — placeholders must be replaced before use |

### Gemini-refined draft

| Property | Value |
|---|---|
| Generated by | Main process — Gemini API via IPC |
| Medical inference | Gemini extracts `extractedTestableFact`, determines `questionType` |
| Stem | Real clinical vignette (patient demographics, presentation, question) |
| Choices | Clinically plausible, mutually exclusive |
| Teaching point | Clinical declarative statement |
| `generationMethod` | `'electron-gemini-divine-cluster-v2'` (Divine) or `'electron-gemini-uworld-draft-refinement-v1'` (UWorld) |
| Usable without review | No — `'requires review before use'` always appended to warnings |
| Provenance | Assembled entirely server-side; Gemini output not trusted for provenance |

### approvalMode (Divine only)

After refinement, the user chooses which version to approve per draft:

- `'original'` — save the deterministic scaffold (after manual review/editing)
- `'refined'` — save the Gemini-generated vignette

`convertApprovedDivineToQuizObject` branches on `approvalMode` to select the correct data. If `approvalMode === 'refined'` but `refinedDraft` is absent (refinement failed), it falls back to `'original'` automatically.

---

## 16. Renderer Safety Assumptions

The renderer (`index.html`) makes the following assumptions about the IPC layer:

1. `window.nbmeDesktop` may be `undefined` in browser mode. All calls guard with `window.nbmeDesktop?.ai?.refineUWorldDraft` before invoking.
2. A result with `result.ok === true` guarantees that `result.refinedDraft` is a validated, schema-conforming object — the renderer does not re-validate Gemini output.
3. A result with `result.ok === false` guarantees that `result.errorCode` is one of the known enum values and `result.message` contains no sensitive data.
4. The renderer **never** calls Gemini directly and has no fallback Gemini path. If Electron is not available, refinement is simply unavailable.
5. Netlify Functions remain as a browser-mode rollback for tagging and hints only — not for draft refinement. New refinement features go through Electron IPC.

---

## Appendix A: Gemini Endpoint and Model

```javascript
const GEMINI_MODEL    = 'gemini-2.5-flash';
const GEMINI_ENDPOINT = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`;
```

The model string `gemini-2.5-flash` must not be changed without updating all dependent generation-method strings, validation logic, and documentation. It appears as a constant in `electron/main.js` and is returned in every `refinedDraft.model` field.

## Appendix B: Netlify Gemini (Legacy Browser Path)

Netlify Functions (`netlify/functions/`) still handle:
- Per-question tag generation (one Gemini call per generated test)
- Per-question hint generation (cached as `q.hint`)

These calls use the Netlify environment variable for `GEMINI_API_KEY`, not `process.env` in Electron. They are not part of the draft-refinement IPC architecture and must not be confused with it.

Draft refinement (UWorld, Divine) does not use Netlify Functions and never did in the Electron path. Netlify remains available as a rollback compatibility layer only.
