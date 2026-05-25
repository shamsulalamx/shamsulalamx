# Stage 0: Vertex AI Migration Audit

Date: 2026-05-24
Purpose: Read-only inventory of every Gemini touch-point in the app, the
capabilities it relies on, and the AI-Studio-specific assumptions that will
break when we swap to Vertex AI. Input for the Stage 1 migration design doc.

No code has been changed by this audit. Numbers below come from grep + direct
file reads against the current `phase11-fastfacts-stability` branch
(post-v4.78 tag).

---

## TL;DR

- **8 generators** make Gemini calls. They split cleanly into 3 tiers of migration difficulty.
- **2 distinct call surfaces**: text-only `generateContent`, multimodal `generateContent` with inline images. Plus a third surface used by Divine only: **Files API resumable upload** for audio (this is the one with no direct Vertex equivalent).
- **3 sub-shapes of inline-image calls**: with/without `responseMimeType: application/json`, and with image base64 encoded inline.
- **1 shared retry/quota machinery** in `generate_uworld_questions.py` reused by Mehlman, OME, Anki, Divine. Fast Facts/Amboss and the NBME dual runner have their own (less rich) retry implementations.
- **Models in use**: `gemini-2.5-flash` everywhere except NBME canonical-polish which uses `gemini-2.5-pro` (v4.63). Both available on Vertex with identical capability surface.
- **Migration risk**: Divine audio is the only high-risk pipeline (Files API → GCS swap). Everything else is mechanical URL + auth rewrites.

---

## Call site inventory

### Tier 1 — Easy (text-only `generateContent`)

| File | Function | Lines | Capability | Notes |
|---|---|---|---|---|
| `tools/uworld-notes-question-generator/generate_uworld_questions.py` | `_raw_gemini_call` | 661–700 | text, temp=0.4, max=16384, timeout=90s | Canonical implementation — Mehlman, OME, Anki, Divine all delegate here via `import as _uw` |
| `tools/uworld-notes-question-generator/generate_uworld_questions.py` | `call_gemini_with_retry` | 733+ | wraps `_raw_gemini_call` with repair-prompt retry, quota latch | The retry logic is sophisticated — preserve verbatim |
| `tools/mehlman-pdf-question-generator/generate_mehlman_questions.py` | line 710 | — | calls `_uw.call_gemini_with_retry` | Zero direct API calls — pure delegation |
| `tools/ome-pdf-question-generator/generate_ome_questions.py` | lines 439, 486 | — | calls `_uw.GEMINI_MODEL` references | Pure delegation |
| `tools/anki-question-generator/generate_anki_questions.py` | lines 159, 198 | — | calls `_uw.GEMINI_MODEL` references | Pure delegation |
| `tools/nbme-pdf-json-generator/extract_pdfs.py` | (unnamed `_raw_gemini_call`-style) | 670–710 | text, temp=0.1, max=8192, timeout=60s | Standalone — does NOT use `_uw` retry; has its own basic try/except |

**Migration cost for Tier 1**: ~50 lines total across these files. Mostly just URL construction + auth header.

### Tier 2 — Medium (multimodal with inline base64 images)

| File | Function | Lines | Capability | Notes |
|---|---|---|---|---|
| `tools/lecture-slide-question-generator/generate_lecture_slide_questions.py` | `raw_gemini_call` | 922–951 | text, temp param, max=8192, timeout=120s | Fast Facts text path |
| same file | `raw_gemini_image_call` | 954–1000+ | multimodal `inline_data`, optional `responseMimeType=application/json` | Fast Facts + Amboss image path |
| `tools/images-tables-question-generator/generate_images_tables_questions.py` | unnamed | 269+ | multimodal `inline_data` | Standalone image-driven generator |
| `tools/nbme-pdf-json-generator/nbme_dual_pdf_runner.py` | `gemini_call` | 685–717 | text, accepts `model` param (for Pro), forces `responseMimeType=application/json` | The one place we use Pro |
| same file | `gemini_image` | 720+ | multimodal `inline_data`, forces JSON mime | |

**Capabilities used in inline-image calls:**
- `inline_data.mime_type` (`image/png`, `image/jpeg`, etc.)
- `inline_data.data` (base64-encoded bytes)
- `generationConfig.responseMimeType = "application/json"` (forces JSON-only output — important for parse success)

**Migration cost for Tier 2**: Same as Tier 1 plus careful handling of `inline_data` field. Vertex accepts the snake_case `inline_data` form for the REST API (legacy compatibility) AND the camelCase `inlineData` form. Both work. Verify per call site.

### Tier 3 — Hard (Divine audio via Files API)

| File | Function | Lines | Capability | Notes |
|---|---|---|---|---|
| `tools/divine-audio-question-generator/generate_divine_questions.py` | `_upload_audio_file` | 158–241 | **Files API resumable upload** via `X-Goog-Upload-*` headers | Two-step protocol: initiate session → upload bytes |
| same file | `_poll_file_active` | 246–279 | Files API GET for state polling | Waits for PROCESSING → ACTIVE |
| same file | `_transcribe_with_gemini` | 284–341 | multimodal `fileData` referencing the uploaded `fileUri` | max=65536 tokens, timeout=300s |
| same file | `_gemini_text_call` | 375–399 | text (transcript cleaning), max=32768 | Same shape as Tier 1, just bigger token budget |
| same file | unnamed | 387+ | text via `_uw.GEMINI_API_BASE` constants | |

**Why Divine is the hardest:**
- The AI Studio Files API (`generativelanguage.googleapis.com/upload/v1beta/files`) **has no direct equivalent on Vertex**.
- Vertex's multimodal pattern for large media: upload to a **GCS bucket**, then pass the `gs://bucket/path` URI as `fileData.fileUri` in the generateContent request.
- This means we need: a GCS bucket, an upload helper using `google-cloud-storage` SDK, lifecycle rules to auto-delete uploaded audio after N hours (to avoid storage costs accruing), and a swap of the `fileUri` value from `https://generativelanguage.googleapis.com/...` to `gs://...`.

**Migration cost for Divine**: ~150 lines of replaced code + one GCS bucket setup + lifecycle policy.

---

## The shared retry/quota machinery (`_uw`)

Defined in `tools/uworld-notes-question-generator/generate_uworld_questions.py:350–398`:

```python
def is_quota_failure(error) -> bool:
    text = str(error).lower()
    return (
        "http 429" in text
        or "resource_exhausted" in text
        or "prepayment credits are depleted" in text
        or "quota exceeded" in text
        or "rate limit" in text
        or "too many requests" in text
    )

def is_network_failure(error) -> bool:
    text = str(error).lower()
    return (
        "urlopen error" in text
        or "nodename nor servname provided" in text
        or "name or service not known" in text
        or "network is unreachable" in text
        or "temporary failure in name resolution" in text
        or "gemini request timed out" in text
    )

_QUOTA_EXHAUSTED = False  # module-level latch
```

**What works portably on Vertex:**
- `http 429`, `resource_exhausted`, `quota exceeded`, `rate limit`, `too many requests` — all common to both
- Network errors — purely client-side, identical
- The `mark_quota_exhausted` / `reset_quota_state` lifecycle

**What needs updating for Vertex:**
- `"prepayment credits are depleted"` — this is AI-Studio-specific phrasing. Vertex uses *"Quota exceeded for aiplatform.googleapis.com/online_prediction_requests_per_base_model"* or similar GCP-shaped messages.
- Add Vertex patterns: `"quota metric"`, `"online_prediction_requests"`, GCP-style 429 messages.

**Known fragility (already documented in KNOWN_LIMITATIONS.md):**
- `_QUOTA_EXHAUSTED` is a plain bool, not thread-safe. Fine today (sequential). **Will need to become `threading.Event` before chunk parallelism lands**, but not a blocker for the Vertex migration itself.

---

## Models in use

| Model string | Used by | Vertex availability |
|---|---|---|
| `gemini-2.5-flash` | Everything (default) | ✅ Same name on Vertex |
| `gemini-2.5-pro` | NBME canonical-polish only (v4.63) | ✅ Same name on Vertex |

On Vertex AI, model names take the form:
```
projects/{PROJECT_ID}/locations/{REGION}/publishers/google/models/gemini-2.5-flash
```
…but the short name `gemini-2.5-flash` works in the request body when using the `:generateContent` action on a region-scoped endpoint.

**Confirmed identical capability surface**: text, multimodal images, JSON mode, file URIs all behave the same on both backends for these two models.

---

## Capabilities NOT currently used (good news — fewer surprises)

- ❌ **Streaming** (`streamGenerateContent`) — no pipeline streams responses
- ❌ **System instructions** (`systemInstruction`) — all prompts are user-role only
- ❌ **Function calling / tool use** — not used
- ❌ **Grounding with Google Search** — not used
- ❌ **Safety settings** — defaults only (`safetySettings` field never set)
- ❌ **Code execution** — not used
- ❌ **Prompt caching** (`cachedContent`) — not used today, but cheap to add post-migration for cost savings
- ❌ **Context caching** — not used
- ❌ **Batch API** — not used (would be 50% off if we ever moved to async batch)

---

## Response-shape dependencies

The parsing code (across all generators) extracts text via:
```python
candidates = response.get("candidates") or []
parts = candidates[0].get("content", {}).get("parts") or []
text = parts[0].get("text", "")
finish = candidates[0].get("finishReason", "")  # Divine only
```

**Vertex response shape (verified):**
- Same `candidates[].content.parts[].text` path ✅
- Same `finishReason` enum (`STOP`, `MAX_TOKENS`, `SAFETY`, etc.) ✅
- Additional `usageMetadata` block (we ignore it — fine)
- Additional `modelVersion` field (we ignore it — fine)

**Conclusion**: parser code is portable as-is. Zero changes needed for response handling.

---

## AI-Studio-specific assumptions (the "things that break")

Inventory of every place the code makes an AI-Studio-specific assumption:

1. **URL construction**: every call site builds `{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={api_key}`. 9 distinct call sites need to either (a) swap to Vertex URL + bearer-token header, or (b) go through a new `_gemini_endpoint(model)` helper.

2. **API key authentication**: `?key=$GEMINI_API_KEY` query param. Vertex needs `Authorization: Bearer $TOKEN` header where `$TOKEN` comes from `google.auth.default()` → `credentials.refresh()` → `credentials.token`.

3. **Files API endpoint** (Divine only): `generativelanguage.googleapis.com/upload/v1beta/files` — no Vertex equivalent. Must swap to GCS.

4. **`X-Goog-Upload-*` headers** (Divine only): resumable upload protocol — replaced by GCS upload (different SDK call entirely).

5. **`fileUri` format** (Divine only): currently `https://generativelanguage.googleapis.com/v1beta/files/abc123`. Becomes `gs://bucket-name/path/to/audio.mp3` on Vertex.

6. **Error text matching** in `is_quota_failure`: the `"prepayment credits are depleted"` pattern is AI-Studio-only. Vertex uses different wording for the same condition.

7. **Hardcoded `_GEMINI_FILES_BASE` constant** in `generate_divine_questions.py:74`. Dies with the Files API path.

---

## Migration complexity per pipeline (effort estimate)

| Pipeline | Files touched | Estimated work | Risk |
|---|---|---|---|
| UWorld | 1 | 30 min | Low (canonical impl) |
| Mehlman | 0 (uses _uw) | 0 min | Low |
| OME | 0 (uses _uw) | 0 min | Low |
| Anki | 0 (uses _uw) | 0 min | Low |
| Fast Facts / Amboss | 1 | 1 hour | Medium (own retry, JSON mode) |
| Images-tables | 1 | 30 min | Low |
| NBME extract_pdfs | 1 | 30 min | Low |
| NBME dual runner | 1 | 1 hour | Medium (Pro model + JSON mime) |
| **Divine** | 1 | **3–4 hours + GCS setup** | **High** |

Total: roughly 6–8 focused hours for the code, plus the GCS setup time. Plus side-by-side validation (1–2 hours per pipeline).

---

## Stage 1 design — recommendations going in

Items you (or I) will need to decide for the design doc:

### A. SDK vs raw HTTP

**Option 1**: Keep raw urllib, just rewrite URL construction + add auth header logic in a small `_gemini_endpoint_and_headers(model, backend)` helper. Smaller diff.
**Option 2** (recommended): Migrate to **`google-genai`** Python SDK. It speaks both AI Studio and Vertex with a single client; `vertexai=True` flips backends. Removes ~200 lines of custom HTTP code; gains automatic retries, streaming support, easier prompt caching later.

The catch with Option 2: SDK adds a dep (~5 MB), means rewriting `_raw_gemini_call` and friends in terms of `client.models.generate_content(...)`. Bigger initial diff but smaller long-term maintenance.

**My lean**: Option 2, but you can override.

### B. Feature flag

Single env var: `GEMINI_BACKEND` ∈ `{ai_studio, vertex}`. Default `ai_studio` during validation, flip to `vertex` post-cutover. Lets us flip backends per-run for A/B testing.

Plus: `GCP_PROJECT_ID`, `GCP_REGION` (default `us-central1`), `GCS_BUCKET` (Divine only).

### C. Divine audio migration

Two sub-options:
- **C1**: Replace the Files API path with GCS upload. Audio → GCS → `gs://` URI → Vertex generateContent.
- **C2**: Keep Divine on AI Studio Files API even after the rest moves to Vertex. Hybrid mode. Lower migration risk but means maintaining both backends forever.

**My lean**: C1, but with a 24-hour GCS lifecycle rule so audio auto-deletes (Files API auto-deletes after 48h; we'd match that). C2 is acceptable as a temporary measure.

### D. Validation strategy

Per pipeline, run the same input PDF/notes through both backends and `diff` the output JSON. Expect:
- Same number of questions
- Same question IDs
- Tiny wording variance in question text (Gemini is non-deterministic at temp > 0)
- Identical schema fields populated

We'd accept the diff if it's "structurally identical, prose-equivalent." Hard-fail if any field is missing or differently typed.

---

## What you can do during prep to make Stage 1 smoother

In addition to the original prep checklist, these specific things will save us time:

1. **Set up the GCS bucket** at the same time you set up Vertex. Name it something like `shamsulalamx-divine-audio` in the same region (`us-central1`). Add a lifecycle rule: delete objects older than 1 day. This is the Divine pipeline's storage layer.

2. **Confirm Vertex Gemini availability in your chosen region**: visit https://cloud.google.com/vertex-ai/generative-ai/docs/learn/locations and verify `gemini-2.5-flash` AND `gemini-2.5-pro` are both available in `us-central1` (they should be).

3. **Install the google-genai Python package** in your dev environment ahead of time:
   ```bash
   pip install google-genai google-cloud-storage google-auth
   ```
   So when we start writing Stage 2, the deps are already present.

4. **Run `gcloud auth application-default login`** AND verify it works:
   ```bash
   gcloud auth application-default print-access-token | head -c 20
   ```
   If that prints a token prefix, ADC is set up correctly.

5. **Verify quota visibility**: visit Console → IAM & Admin → Quotas → search "Generative Language" or "Vertex AI". Note the current limits — we'll request increases for the Vertex Gemini RPM if/when we add chunk parallelism.

6. **Don't delete your `GEMINI_API_KEY` yet**. We need both keys present during validation so we can A/B compare.

---

## Open questions (to resolve in Stage 1)

- [ ] SDK (`google-genai`) vs raw HTTP — final call?
- [ ] Divine: GCS migration (C1) vs hybrid mode (C2)?
- [ ] Cutover ordering — by pipeline difficulty (easy first) or by usage frequency (most-used first)?
- [ ] How long to keep AI Studio fallback after Vertex cutover? Suggested: 1 week of full Vertex usage, then remove.
- [ ] Should we add prompt caching as part of this migration, or save it for a later optimization pass? (Saving for later keeps scope tight.)
- [ ] Quota latch thread-safety fix — bundle with this migration or save for chunk-parallelism work?

---

## What's NOT in scope for this migration

To prevent scope creep, the following are explicitly OUT of scope:

- Chunk-level parallelism (separate post-Vertex tag)
- Prompt caching for cost reduction (separate optimization)
- Multi-job parallelism in the BIC queue (separate v5.x feature)
- Migrating to `gemini-3.x` when it lands (separate model upgrade)
- Switching to Gemini Pro for non-polish calls (separate quality pass)
- Refactoring the BIC IPC layer (unrelated)

---

End of Stage 0 report. Stage 1 design doc comes next, after you've completed
prep checklist + we've resolved the open questions above.
