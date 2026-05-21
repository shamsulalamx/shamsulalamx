# Divine Transcript Pipeline — Architecture Reference

Last updated: 2026-05-11  
Stable tags: `divine-v1-stable`, `divine-gemini-v1-stable`  
IPC channel: `nbme:ai:refine-divine-draft` (Electron main process)  
Generation method (Gemini path): `electron-gemini-divine-cluster-v2`  
Generation method (deterministic path): `divine-deterministic-scaffold-v1`

---

## Overview

The Divine pipeline converts podcast transcripts into reviewable NBME-style question drafts. It is fully isolated from all other source pipelines (NBME, UWorld, OME, Anki, Mehlman).

The pipeline is intentionally staged. Each step is user-triggered and produces a visible intermediate result before the next step is unlocked. Nothing is saved until the user explicitly approves a draft and confirms a save.

```
Transcript text (file or paste)
│
▼  CLEANING           remove promo, duplicates, filler; normalize monolithic lines
▼  SEGMENTATION       split into coherent logical blocks
▼  CONCEPT EXTRACTION identify medical concept type per segment
▼  CLUSTERING         group related concepts by type + similarity; collapse duplicates
▼  CLUSTER SUMMARY    strip podcast voice; compute quality scores
▼  QUALITY GATES      block meta-commentary, empty, and low-substance clusters
▼  DETERMINISTIC SCAFFOLDS   placeholder drafts (usable without Gemini)
▼  GEMINI REFINEMENT  Electron IPC → Gemini identifies testable fact + writes vignette
▼  REVIEW             user approves/rejects each draft; chooses refined or original
▼  CONTROLLED SAVE    quiz-object preview → explicit target → confirm → save
```

---

## 1. Transcript Import

### Supported input methods

1. **File upload** — `.txt`, `.md`, or `.txt.md` (e.g. OpenWhispr exports)
2. **Paste** — direct paste into a textarea

No audio transcription is performed. The pipeline requires pre-transcribed text.

### Supported file extensions

| Extension | Notes |
|---|---|
| `.txt` | Standard plain-text transcript |
| `.md` | Markdown-formatted transcript |
| `.txt.md` | OpenWhispr and similar double-extension exports |

### Metadata captured at import

- **Episode title** — optional, used in quiz-object tags and provenance
- **Source meta** — optional, e.g. "Divine Intervention Podcast, Season 5", stored in provenance

The raw transcript text is held in `_divineImportPreview.rawText`. Nothing is written to localStorage, IndexedDB, or Google Drive at this stage.

---

## 2. Why Transcript Voice Cannot Be Used Directly for Vignette Generation

Podcast transcripts are in a **teaching/coaching register** that is structurally unsuitable for NBME-style clinical vignette questions:

- **First-person coaching language**: "remember", "I think", "they give you a question about", "don't forget", "you need to know", "high yield" — these phrases are meaningless or harmful in an exam stem.
- **Promotional and administrative content**: sponsor mentions, subscription prompts, episode intros/outros, personal anecdotes, and course advertisements are interspersed with medical content.
- **Repetition and emphasis fragments**: key facts are often restated multiple times across a podcast episode, producing near-duplicate content.
- **Monolithic lines**: some transcript formats (OpenWhispr) produce very long single-line paragraphs. A promo phrase appearing at the end of such a line would otherwise corrupt an entire educational block.
- **Discourse markers and fillers**: "so", "right", "okay", "now", "and", "but" at clause boundaries add noise without medical content.

Passing raw transcript text directly to Gemini would produce questions that either echo coaching phrasing, lift transcript wording verbatim, or are grounded in promo/meta content rather than medical facts. The cleaning, segmentation, concept extraction, and clustering steps exist specifically to isolate medical content and strip register artifacts before anything reaches Gemini.

---

## 3. Cleaning Pipeline

**Function:** `cleanDivineTranscript(rawText)`  
**Input:** raw transcript string  
**Output:** `{ cleanedText, cleanedLines, excludedSegments, stats, warnings }`

The cleaner runs four passes plus a conservative-mode fallback guard.

### Pass 0 — Monolithic line normalization

`_divineNormalizeToUnits(rawText)` runs before any promo testing.

Long lines exceeding `DIVINE_LONG_LINE_THRESHOLD` are split into atomic units at sentence boundaries. This is a critical root-cause fix: without splitting first, a single promo phrase appearing at the end of a long educational paragraph would exclude the entire paragraph.

Each unit records:
- `text` — the cleaned line text
- `originalLine` — source line number (for provenance)
- `isBlank` — blank line flag
- `timestamp` — extracted timestamp if present (e.g. `[00:01:23]`)

### Pass 1 — Promo detection with scoped exclusion

`_divinePromoScope(unitText, promoRe)` applies scoped exclusion:

- If the promo phrase fires in the **first 60%** of a unit: the entire unit is excluded.
- If the promo phrase fires in the **last 40%** of a unit: the educational prefix up to the nearest sentence boundary is retained; only the promo tail is excluded.

This prevents late outro phrases (e.g. "check out my website" appended after medical content) from deleting the educational portion.

Excluded units are recorded in `excludedSegments` with their reason.

### Pass 2 — Exact duplicate collapse

Case-insensitive, whitespace-normalized duplicate detection across all kept units. Units shorter than 8 characters are exempt. The first occurrence is kept; subsequent duplicates are excluded with a reason string referencing the first occurrence line number.

### Pass 3 — Adjacent repeated short-phrase collapse

For kept units of ≤10 words, if two adjacent units are identical (case-insensitive), the second is excluded. Handles repeated emphasis phrases like "so that's the answer" appearing back-to-back.

### Pass 4 — Filler removal and final assembly

Inline filler cleanup using `DIVINE_FILLER_RE` and `DIVINE_DISCOURSE_RE`. Removes standalone filler words and discourse markers without touching medical terminology. Collapses internal whitespace gaps left by removal.

### Conservative-mode fallback guard

After the normal cleaning run: if the ratio of excluded words to total raw words exceeds **80%**, the entire run is discarded and cleaning re-runs in conservative mode.

Conservative mode:
- Promo exclusion is restricted to units where the promo phrase appears in the **first 30%** of the unit only.
- Later promo phrases are kept with a `promoWarning` flag.
- Filler removal is skipped.

This protects monolithic transcripts (e.g. transcripts pasted without line breaks) where a single late promo phrase would otherwise eliminate almost all content.

### Cleaning output fields

| Field | Meaning |
|---|---|
| `cleanedLines` | Array of `{originalLine, cleanedLineNumber, text, timestamp}` |
| `excludedSegments` | Array of `{originalLine, text, timestamp, reason}` |
| `promoLineCount` | Units excluded for promo content |
| `promoSpansRemoved` | Partial promo tails removed (educational prefix retained) |
| `dupLineCount` | Units excluded as exact or adjacent duplicates |
| `fillerCleanupCount` | Filler match instances removed inline |
| `exclusionRate` | Excluded words / raw words |
| `fallbackModeTriggered` | Whether conservative mode was used |
| `warnings` | Human-readable warnings (elevated exclusion rate, empty output, etc.) |

---

## 4. Segmentation

**Function:** `segmentDivineTranscript(cleanedLines)`  
**Input:** `cleanedLines` from `cleanDivineTranscript` (never contains excluded lines)  
**Output:** array of segment objects

Segments are accumulated into a bucket and flushed at any of four boundaries:

| Boundary trigger | Rule |
|---|---|
| Timestamp gap | Gap between consecutive timestamps ≥ `DIVINE_SEGMENT_TS_GAP_S` seconds |
| Heading line | `_divineIsHeadingLine(trimmed)` is true and bucket is nonempty |
| Word-count cap | Adding the next line would exceed `DIVINE_SEGMENT_MAX_WORDS` words |
| Double blank line | Two consecutive blank lines in the bucket |

Remaining lines in the bucket are flushed after the last line.

### Segment object fields

| Field | Content |
|---|---|
| `segmentId` | e.g. `divine-seg-0001` (sequential, zero-padded) |
| `textRaw` | Joined raw text including blank lines |
| `textClean` | Joined non-blank text, single-spaced |
| `originalLineRange` | `[firstOriginalLine, lastOriginalLine]` |
| `cleanedLineRange` | `[firstCleanedLine, lastCleanedLine]` |
| `timestampRange` | `{start, end}` from contained timestamps, or null |
| `segmentType` | Classification from `_divineClassifySegment` |
| `confidence` | Classification confidence |
| `warnings` | Per-segment classification warnings |

---

## 5. Concept Extraction

**Function:** `extractDivineConceptsFromSegments(segments)`  
**Per-segment:** `_divineExtractConceptsFromSegment(seg, globalIdxRef)`

Concept extraction identifies the dominant medical learning objective within each segment and assigns it a `conceptType` from `DIVINE_CONCEPT_TYPES`.

Concepts with `conceptType === 'unknown'` are extracted but separated in the UI (collapsible section). They are stored in `_divineImportPreview.concepts` alongside typed concepts but are excluded from clustering.

### Concept object fields

| Field | Content |
|---|---|
| `conceptId` | e.g. `divine-concept-00001` |
| `conceptType` | from `DIVINE_CONCEPT_TYPES`, or `'unknown'` |
| `confidence` | 0–1; < 0.60 is flagged as low-confidence |
| `sourceSnippet` | Representative text from the segment |
| `sourceSegmentId` | Parent segment ID |
| `originalLineRange` | `[first, last]` original line numbers |
| `cleanedLineRange` | `[first, last]` cleaned line numbers |
| `timestampRange` | From parent segment |
| `warnings` | Per-concept warnings |

### Concept types

```
high-yield-fact              mechanism
risk-factor                  diagnostic-distinction
management-rule              contraindication-adverse-effect
exam-trap                    clinical-reasoning-framework
differential-diagnosis       unknown
```

---

## 6. Clustering and Deduplication

**Function:** `clusterDivineConcepts(concepts)`  
**Algorithm:** Union-Find over Jaccard similarity within each `conceptType` group

### Clustering rules

1. Concepts are grouped strictly by `conceptType` — concepts of different types are never merged.
2. Jaccard similarity is computed over ≥3-character lowercase word tokens from `sourceSnippet`.
3. If similarity ≥ **0.85**: union the pair, flag as exact duplicate (collapsed into representative).
4. If similarity ≥ **0.65** and < 0.85: union the pair, flag as near-duplicate (warning only).
5. **Timestamp penalty** (timestamp penalty applied to Jaccard similarity): if two concepts are >10 minutes apart by timestamp, similarity is reduced by 0.20. This prevents clustering distant re-mentions of the same topic that may have different pedagogical context.
6. The representative concept per cluster is the member with the highest `confidence`.

After all clusters are built, `distillDivineClusterToObjective(cluster)` is called on each cluster to produce the `distilledObjective` sub-object (which holds `clusterSummary`, quality scores, and gate results).

### Cluster object fields

| Field | Content |
|---|---|
| `clusterId` | e.g. `divine-cluster-00001` |
| `conceptType` | Shared type of all member concepts |
| `concepts` | Array of `conceptId` strings |
| `representativeConcept` | Highest-confidence member concept |
| `sourceSegmentIds` | Unique segment IDs across all members |
| `originalLineRanges` | Per-member `[first, last]` original line ranges |
| `cleanedLineRanges` | Per-member `[first, last]` cleaned line ranges |
| `timestampRanges` | Per-member timestamp ranges |
| `timestampSpan` | `{start, end}` across the whole cluster |
| `sourceSnippet` | Representative concept's source snippet |
| `confidence` | Representative concept's confidence |
| `duplicateWarnings` | Pairs with similarity ≥ 0.85 |
| `nearDupWarnings` | Pairs with similarity 0.65–0.85 |
| `warnings` | Human-readable cluster warnings |
| `distilledObjective` | Teaching cluster summary record (see §7) |

---

## 7. Teaching Cluster Summary (distilledObjective)

**Function:** `distillDivineClusterToObjective(cluster)`  
**Derivation method:** `divine-teaching-cluster-summary-v1`

This step produces the `clusterSummary` that is sent to Gemini as the primary medical source. It does **not** extract conditions, criteria, or diagnostic thresholds. Gemini is responsible for identifying what is medically testable.

### Step 1 — Voice stripping (clusterSummary)

`VOICE_STRIP_PHRASES` (regex array) removes podcast-coaching register from `sourceSnippet`:

```
remember,        don't forget,      I think,           I want you to
let me tell you  the thing is,      the easy way       the way I think
think of it as   pretty high-yield  that's high-yield  high-yield
you're going to see                 they give you a question about
to be completely honest             obviously
```

After stripping, leading discourse connectors (`so`, `and`, `but`, `also`, `then`, `well`, `okay`, `right`, `now`) are removed. Whitespace is collapsed. The result is clamped to **≤400 characters**.

This is the `clusterSummary` sent to Gemini. It surfaces the medical content without coaching phrasing.

### Step 2 — Meta-commentary detection

`META_RE` detects promotional and administrative content:

```
my website, review course, one-on-one tutoring, Apple Podcast,
Spotify, Google Podcast, divineintervention, shoot me an email,
sign up, this is a podcast, this podcast is, on Apple Podcasts
```

Sets `contentType` to `'meta-commentary'` or `'medical-content'`. Meta-commentary clusters are blocked by quality gate 1.

### Step 3 — podcastVoiceScore

Hit count of `DIVINE_VOICE_MARKERS` in the raw `sourceSnippet`, normalized by `wordCount / 5`. A 50-word snippet with 3 voice-marker hits yields a score of approximately 0.30. Capped at 1.0.

### Step 4 — testabilityScore

```
testabilityScore = medicalSignal + substanceScore − voicePenalty − metaPenalty

medicalSignal  = 0.40 if conceptType is a known medical type, else 0
substanceScore = min(0.40, clusterSummary.length / 250)
voicePenalty   = max(0, (podcastVoiceScore − 0.40) × 0.50)
metaPenalty    = 1.0 if contentType === 'meta-commentary', else 0
```

The threshold is deliberately low (0.25) because Gemini performs the semantic interpretation. The score functions as a coarse filter to block clearly empty or voice-only clusters, not as a medical quality assessor.

### distilledObjective fields

| Field | Content |
|---|---|
| `clusterSummary` | Voice-stripped snippet, ≤400 chars — sent to Gemini |
| `conceptType` | Inherited from cluster |
| `podcastVoiceScore` | 0–1, rounded to 2 decimal places |
| `contentType` | `'medical-content'` or `'meta-commentary'` |
| `testabilityScore` | 0–1, rounded to 2 decimal places |
| `derivedFrom` | `'sourceSnippet'` |
| `derivationMethod` | `'divine-teaching-cluster-summary-v1'` |
| `warnings` | Gate failures and short-summary warnings |
| `gateResults` | `{ 'meta-blocked': bool, 'low-testability': bool, 'insufficient-substance': bool }` |

---

## 8. Why Hardcoded Criterion Extraction Was Replaced

### The old approach

Earlier versions of the pipeline attempted to pre-extract a structured diagnostic criterion from the transcript — a typed struct that encoded a specific condition name, a duration or threshold value, a polarity (≥ or <), and distractor candidates. Gemini received this pre-parsed struct as its medical source and was instructed to test only that extracted criterion.

**Why this failed:**

1. **Topic mismatch**: Podcast content covers mechanisms, risk factors, management rules, clinical reasoning frameworks, and contraindications — not just "condition X requires duration Y." Most medical content does not have a clean criterion-extractable structure.

2. **Brittle extraction**: Pattern matching on transcript phrasing for duration thresholds, DSM-style fields, and polarity values was fragile. Slight phrasing variations produced extraction failures, and failed extractions blocked draft generation for valid content.

3. **Hardcoded disease logic**: The app embedded disease-specific templates and per-topic extraction heuristics that had to be extended for every new topic area. This created maintenance debt and made the pipeline inflexible.

4. **Mismatch cascades**: If the renderer incorrectly classified a teaching point (e.g., classified a management rule as a diagnostic-distinction), the entire prompt downstream was built on a wrong premise and Gemini had no recourse.

### The new approach (divine-gemini-v1-stable onward)

The app sends the cleaned teaching cluster summary (`clusterSummary`) to Gemini and lets Gemini identify what is medically testable:

```
Old: renderer pre-extracts criterion → sends typed criterion struct → Gemini tests that criterion only
New: renderer sends clusterSummary → Gemini extracts extractedTestableFact → Gemini generates vignette
```

**Benefits:**

- **No hardcoded disease logic** in the renderer. Any medical topic — mechanism, management, timeline, risk factor, contraindication — is handled by the same prompt structure.
- **Explicit auditability**: `extractedTestableFact` is returned in the Gemini response and visible to reviewers, so a human can verify what Gemini decided was testable before approving.
- **Robust across content types**: Gemini interprets the medical content semantically; the renderer only needs to strip coaching voice and compute coarse quality scores.
- **Stable prompt**: No per-variant guidance tables or disease-specific branches in the prompt. New topic types require no renderer changes.

---

## 9. Quality Gates

**Function:** `_divineCheckObjectiveGates(cluster)`  
**Returns:** `{ blocked: bool, reasons: string[] }`

Three gates. Blocked clusters are skipped in draft generation (`skipped[]` list is returned for display). Non-blocked clusters proceed to scaffold generation.

| Gate | Condition to pass | Reason for blocking |
|---|---|---|
| `meta-blocked` | `contentType !== 'meta-commentary'` | Cluster is promotional or administrative, not medical content |
| `low-testability` | `testabilityScore >= 0.25` | Insufficient medical substance (pure coaching phrases, empty after voice stripping) |
| `insufficient-substance` | `clusterSummary.length >= 20` | Less than 20 chars of content after voice stripping — no usable medical text |

The testability threshold is deliberately low (0.25) because Gemini performs semantic interpretation. These gates are coarse filters, not semantic quality assessors.

Additional scaffold-level guards (in `generateDivineDraftScaffolds`, run after gate check):
- Cluster `confidence < 0.25` → skip
- `sourceSnippet` length < 20 chars → skip
- At most **2 draft variants** generated per cluster to prevent bloat

---

## 10. Deterministic Draft Scaffolds

**Function:** `generateDivineDraftScaffolds(clusters, selection)`  
**Per-draft:** `_divineGenerateDraftScaffold(cluster, variantType, draftIdxRef)`

Scaffold templates exist for each variant type. They embed the `sourceSnippet` directly into placeholder stems and choices. No medical facts are invented or inferred.

### Draft variant types (DIVINE_DRAFT_VARIANT_MAP)

| Concept type | Allowed variant types |
|---|---|
| `high-yield-fact` | recognition/application |
| `mechanism` | mechanism/risk-factor |
| `risk-factor` | mechanism/risk-factor, recognition/application |
| `diagnostic-distinction` | diagnostic-distinction |
| `management-rule` | next-best-step, management-exception |
| `contraindication-adverse-effect` | management-exception |
| `exam-trap` | recognition/application |
| `clinical-reasoning-framework` | clinical-reasoning-framework |
| `differential-diagnosis` | diagnostic-distinction |

### Scaffold templates (DIVINE_SCAFFOLD_TEMPLATES)

Six templates cover all variant types:
- `recognition/application` — "most likely diagnosis/finding" question
- `mechanism/risk-factor` — mechanism or risk factor explanation question
- `diagnostic-distinction` — distinguishing feature question
- `next-best-step` — management step question
- `management-exception` — contraindication/adverse effect question
- `clinical-reasoning-framework` — reasoning framework question

All answer choices in scaffold drafts are labeled `[PLACEHOLDER — ...]`. Stems quote the source snippet directly. Teaching points repeat the source snippet. No placeholder is ever saved into a real test.

### Scaffold draft object fields

| Field | Content |
|---|---|
| `draftId` | e.g. `divine-draft-00001` |
| `clusterId` | Parent cluster ID |
| `variantType` | Selected template variant |
| `stem` | Placeholder stem with embedded snippet |
| `choices` | 5 labeled placeholder choices |
| `correctAnswer` | `'A'` (always — placeholder) |
| `teachingPoint` | Placeholder quoting source snippet |
| `distractorRationales` | Per-label placeholder rationale strings |
| `sourceSnippet` | Raw representative snippet |
| `timestampRange` | Cluster timestamp span |
| `provenance` | See §13 |
| `warnings` | From cluster + scaffold-level warnings |

The scaffold is always preserved. If Gemini refinement is declined or fails, the scaffold remains available for approval as the `'original'` mode draft.

---

## 11. Gemini Refinement

**IPC channel:** `nbme:ai:refine-divine-draft` (Electron main process)  
**Model:** `gemini-2.5-flash`  
**Flow:** one draft at a time; no batch queue; no auto-retry

### Renderer payload (sent to Electron IPC)

| Field | Source | Clamped to |
|---|---|---|
| `clusterSummary` | `cluster.distilledObjective.clusterSummary` | ≤400 chars (already clamped at distillation) |
| `sourceContext` | `cluster.sourceSnippet` | ≤300 chars in main process |
| `conceptType` | `cluster.conceptType` | ≤80 chars in main process |
| `variantType` | `draft.variantType` | ≤60 chars in main process |
| `sourceMeta.draftId` | `draft.draftId` | required |
| `sourceMeta.clusterId` | `cluster.clusterId` | required |
| `sourceMeta.sourceName` | episode source name | optional |
| `provenance.sourceSegmentIds` | `cluster.sourceSegmentIds` | normalized array |
| `provenance.originalLineRanges` | `cluster.originalLineRanges` | array, ≤12 entries |
| `provenance.cleanedLineRanges` | `cluster.cleanedLineRanges` | array, ≤12 entries |
| `provenance.timestampRanges` | `cluster.timestampRanges` | array, ≤12 entries |

### Main process responsibilities

1. `sanitizeDivineDraftInput(payload)` — clamp, validate, reject null/malformed, reject `clusterSummary < 20 chars`
2. `buildDivineRefinementPrompt(input)` — prompt using `clusterSummary` as sole medical source; `sourceContext` labeled "do not copy"
3. Fetch Gemini with 30 s `AbortController` timeout
4. `extractGeminiJson(data)` — two-attempt JSON extraction (fence-strip + brace-depth scan)
5. `validateDivineRefinedDraft(parsed, input)` — full schema validation (see §12)
6. Return `{ ok: true, refinedDraft }` or `safeError(errorCode, message)`

### What Gemini is asked to determine

- `extractedTestableFact` — the specific medical fact Gemini identifies as testable from `clusterSummary`
- `questionType` — from the fixed enum: `timeline-criterion | diagnostic-distinction | mechanism | management | risk-factor | contraindication | clinical-application | other`
- Clinical vignette `stem`, five `choices`, `correctAnswer`, `teachingPoint`, `rationales` for all five choices
- `confidence`, `needsReview`, `warnings`

### Renderer-side refinement flow

```javascript
refineDivineDraft(draftId)
  → find draft in _divineImportPreview.drafts
  → verify window.nbmeDesktop?.ai?.refineDivineDraft is available
  → mark draft.refining = true, re-render
  → build payload from cluster + draft fields
  → await window.nbmeDesktop.ai.refineDivineDraft(payload)
  → on success: store draft.refinedDraft, mark draft.refining = false
  → on error:   store draft.refinementError, mark draft.refining = false
  → re-render draft card
```

---

## 12. Anti-Copy and Validation

All validation — including the anti-copy overlap detection — runs in `electron/main.js`. The renderer does not validate Gemini output.

### Schema validation sequence (validateDivineRefinedDraft)

| Step | Check |
|---|---|
| 1 | `extractedTestableFact`: string, trimmed, ≥10 chars |
| 2 | `questionType`: nonempty string, ≤80 chars |
| 3 | `stem`: string, ≥40 chars, ≤3000 |
| 4 | `choices`: exactly 5, labels A B C D E in order |
| 5 | Each choice text nonempty |
| 6 | `correctAnswer` ∈ {A, B, C, D, E} |
| 7 | `teachingPoint`: string, ≥20 chars, ≤1200 |
| 8 | `rationales`: all five labels present and nonempty |
| 9 | Anti-copy check: stem vs `sourceContext` |
| 10 | Anti-copy check: each choice vs `sourceContext` |
| 11 | Podcast-voice markers in stem |

Any failure returns `safeError('MODEL_RESPONSE_INVALID', message)`. The message identifies the specific failure but never includes API keys, prompt text, or source content.

### Anti-copy: 8-word verbatim overlap check (`divineCopyOverlapDetected`)

Slides an 8-word window across `sourceContext` (lowercase, whitespace-split). Checks whether any 8-word n-gram appears in the target text (stem or each choice text individually). A match causes hard rejection.

This prevents Gemini from lifting podcast transcript phrasing into the question, which would violate copyright and produce coaching-register stems.

### Podcast-voice marker rejection (`DIVINE_STEM_VOICE_MARKERS`)

```
/\byou need to\b/i       /\bI think\b/i          /\bremember\b/i
/\bdon'?t forget\b/i     /\bhigh[\s-]yield\b/i    /\bboards?\b/i
/\bpodcast\b/i           /\bI want you to\b/i     /\bthey give you\b/i
```

Any match in the Gemini-generated stem causes hard rejection.

### IPC error codes

| Code | Meaning |
|---|---|
| `NO_API_KEY` | `GEMINI_API_KEY` not set |
| `RATE_LIMITED` | HTTP 429 from Gemini |
| `NETWORK_ERROR` | Network failure or non-2xx non-429 response |
| `TIMEOUT` | AbortController fired at 30 s |
| `MODEL_RESPONSE_INVALID` | Parse failure, schema failure, or sanitization failure |

---

## 13. Review and Approval Workflow

After draft generation (deterministic or refined), the user reviews each draft individually.

### Per-draft review controls

| Action | Function | Effect |
|---|---|---|
| Approve (original scaffold) | `approveDivineOriginal(draftId)` | `reviewStatus = 'approved'`, `approvalMode = 'original'` |
| Approve (refined Gemini draft) | `approveDivineRefined(draftId)` | `reviewStatus = 'approved'`, `approvalMode = 'refined'` |
| Reject | `setDivineReviewStatus(draftId, 'rejected')` | `reviewStatus = 'rejected'` |
| Refine with Gemini | `refineDivineDraft(draftId)` | triggers IPC call; on success, refined option appears |

### Bulk review controls

- **Approve All** (`approveDivineAllDrafts`) — sets all drafts to approved in `'original'` mode (does not override per-draft refined approvals already set)
- **Reject All** (`rejectDivineAllDrafts`) — sets all drafts to rejected

### approvalMode

`approvalMode` tracks which version of each draft is approved:

- `'original'` — use the deterministic scaffold
- `'refined'` — use the Gemini-refined version

`convertApprovedDivineToQuizObject` branches on `approvalMode` to select which data to use for quiz-object assembly. If `approvalMode === 'refined'` but `refinedDraft` is absent, it falls back to `'original'`.

### Review state is session-local

`_divineImportPreview.reviewStatus` and `_divineImportPreview.approvalMode` are held in memory only. They are not persisted between sessions. Clearing or closing the import modal resets all state.

---

## 14. Controlled Save Workflow

**Function:** `createTestFromApprovedDivineDrafts()`

### Save gates (all must pass before save proceeds)

1. At least one approved draft in `reviewStatus`
2. All approved quiz-object previews pass `validateDivineQuizObject` (stem, choices, correctAnswer, teachingPoint, explanation, tags all required)
3. A valid Divine Podcasts subfolder target is selected (existing or new)
4. Test name is nonempty
5. Inline review-confirmed checkbox is checked

If any gate fails, the save button remains disabled and a diagnostic message explains the blocker. `safeError`-style error display — never exposes transcript content or internal state.

### Save flow

```
getApprovedDivineQuizObjectPreviewValidation()
  → convertApprovedDivineToQuizObject() for each approved draft
  → validateDivineQuizObject() for each quiz object
  → if errors: show diagnostics, block save

createTestFromApprovedDivineDrafts()
  → re-validate readiness
  → resolve or create target folder (DB.createFolder if '__new__')
  → pre-save validation sweep (validateDivineQuizObject per question)
  → DB.createTest(targetFolderId, testName, questions)
  → verify test was stored (count check before/after)
  → on success: clear error, refresh UI, log success
  → on failure: show error, log failure without transcript content
```

### Quiz object fields (per saved question)

| Field | Content |
|---|---|
| `stem` | From approved draft (scaffold placeholder or Gemini-generated) |
| `choices` | 5 labeled choices |
| `correctAnswer` | From approved draft |
| `explanation` | Built from `teachingPoint` + `rationales` |
| `tags` | `['Divine', 'Podcast', variantType, conceptType, 'AI-Refined']` (last tag only if refined) |
| `sourceType` | `'divine-podcast'` |
| `divineDraftProvenance` | Full provenance record (see §15) |
| `generationMethod` | `'electron-gemini-divine-cluster-v2'` (refined) or `'divine-deterministic-scaffold-v1'` (original) |

Browser `prompt()` and `confirm()` are not used anywhere in the save flow.

---

## 15. Provenance Guarantees

All provenance is constructed server-side (main process) from sanitized input. Gemini output is never trusted for provenance.

### Deterministic scaffold provenance (attached at draft generation)

```json
{
  "sourceType": "divine-podcast",
  "draftMethod": "divine-deterministic-scaffold-v1",
  "clusterId": "divine-cluster-00001",
  "conceptType": "mechanism",
  "sourceSegmentIds": ["divine-seg-0003", "divine-seg-0007"],
  "originalLineRanges": [[42, 58], [101, 115]],
  "cleanedLineRanges": [[38, 52], [93, 105]],
  "timestampRanges": [{"start": "00:03:12", "end": "00:04:05"}],
  "conceptIds": ["divine-concept-00012", "divine-concept-00019"],
  "createdAt": "2026-05-11T..."
}
```

### Gemini-refined provenance (added by main process at validation time)

```json
{
  "draftId": "divine-draft-00001",
  "clusterId": "divine-cluster-00001",
  "sourceName": "Divine Intervention Podcast, Season 5",
  "sourceHash": "...",
  "provenance": {
    "sourceSegmentIds": [...],
    "originalLineRanges": [...],
    "cleanedLineRanges": [...],
    "timestampRanges": [...],
    "timestampRange": {"start": "...", "end": "..."}
  },
  "generationMethod": "electron-gemini-divine-cluster-v2",
  "model": "gemini-2.5-flash",
  "createdAt": "2026-05-11T..."
}
```

### Provenance chain

```
originalLine (source) → cleanedLineNumber → segment → concept → cluster
                                         → clusterSummary → Gemini → validatedRefinedDraft
                                                                    → quiz question → test
```

Each step in the chain is recorded and carried forward. A saved question can be traced back to its source segment, original line range, and timestamp range.

---

## 16. Known Limitations and Current Weaknesses

### No audio transcription

The pipeline requires pre-transcribed text. Audio processing is out of scope. Transcript quality depends entirely on the transcription tool (e.g. OpenWhispr).

### Promo pattern coverage

`DIVINE_PROMO_PATTERNS` is a fixed regex list. Novel promo phrasing not covered by the list will not be detected. The elevated-exclusion-rate warning (>15%) helps surface this.

### Monolithic transcript handling is heuristic

`DIVINE_LONG_LINE_THRESHOLD` determines when a line is split. The split is sentence-boundary-based but the boundary detection is heuristic. Very long medical sentences may be split at suboptimal positions.

### Concept extraction uses pattern matching, not NLP

`_divineExtractConceptsFromSegment` uses regex patterns and keyword matching. It does not use a trained NLP model. Unusual phrasing or mixed-topic segments may produce `'unknown'` concept types or misclassifications.

### Jaccard clustering doesn't detect paraphrase similarity

Two concepts expressing the same medical fact in different words (one from early in the episode, one from a later summary) will have low Jaccard similarity and will not be clustered together.

### Quality scores are coarse

`testabilityScore` and `podcastVoiceScore` are computed signals, not semantic assessments. A cluster that narrowly passes the 0.25 testability threshold may still produce a poor Gemini refinement. The review step exists precisely to catch these cases.

### Gemini validation is deferred

Live Gemini validation has been intentionally deferred to conserve API credits. The validation logic in `validateDivineRefinedDraft` is fully implemented but untested against live Gemini responses in production volume.

### Scaffold placeholders are not usable as exam questions

Deterministic scaffold drafts contain `[PLACEHOLDER — ...]` choices and are intended only as a structural starting point. They must be refined by Gemini or manually edited before use. Saving a scaffold draft as `'original'` mode is permitted but should only be done after manual review and editing.

### approvalMode defaults to 'original'

`approveDivineAllDrafts()` approves all drafts in `'original'` (scaffold) mode. Per-draft refined approvals must be set individually. Bulk approval does not trigger Gemini refinement.

---

## Appendix: Pipeline State Object (_divineImportPreview)

The `_divineImportPreview` object is the module-level state container for the active import session. It is initialized to `null` and cleared by **Clear / Reset**.

| Field | Populated by | Content |
|---|---|---|
| `rawText` | file load or paste | Original transcript string |
| `sourceName` | file load | Filename or `'(pasted)'` |
| `cleanedLines` | `cleanDivineTranscript` | Array of cleaned line objects |
| `excludedSegments` | `cleanDivineTranscript` | Array of excluded segment objects |
| `segments` | `segmentDivineTranscript` | Array of segment objects |
| `concepts` | `extractDivineConceptsFromSegments` | Array of concept objects (typed + unknown) |
| `clusters` | `clusterDivineConcepts` | Array of cluster objects |
| `clusterSelection` | cluster UI | `{ [clusterId]: bool }` map |
| `drafts` | `generateDivineDraftScaffolds` | Array of scaffold draft objects |
| `skippedClusters` | `generateDivineDraftScaffolds` | Array of `{ cluster, reasons }` for gate-blocked clusters |
| `reviewStatus` | review controls | `{ [draftId]: 'approved' | 'rejected' }` |
| `approvalMode` | review controls | `{ [draftId]: 'original' | 'refined' }` |

All fields are session-local and are never written to persistent storage during the pipeline.
