# Stage 1: Vertex AI Migration Design

Date: 2026-05-25
Branch: `phase12-vertex-migration`
Previous: [`STAGE0_VERTEX_AUDIT.md`](STAGE0_VERTEX_AUDIT.md)
Project: `shamsulalamx`
Region: `us-central1`

This doc describes HOW the migration works architecturally, before any code
ships. Read this first; if anything looks wrong, push back here rather than
catching it in code review.

---

## Decisions locked

From the Stage 0 open questions:

| Decision | Choice | Rationale |
|---|---|---|
| SDK vs raw HTTP | **`google-genai` SDK** | One client handles both backends via `vertexai=True` flag; eliminates ~200 lines of custom urllib code; gains auto-retry + future prompt caching for free |
| Feature flag | `GEMINI_BACKEND` env var, values `ai_studio` / `vertex` | Per-run override, easy A/B testing, default stays `ai_studio` until cutover |
| Cutover order | UWorld first (cascades to Mehlman/OME/Anki/Divine-text-path via `_uw`), then Fast Facts/Amboss, then NBME pair, then images-tables | Maximum coverage per hour of work |
| Divine audio (Files API) | **Defer to tomorrow** — needs GCS bucket setup with user's credentials | Out of scope for today's work |
| AI Studio fallback retention | Keep both paths working ~1 week post-cutover | Safety net |
| Prompt caching | Out of scope | Separate optimization pass after migration stabilizes |
| Quota latch thread-safety fix | Out of scope | Save for chunk-parallelism work |

---

## Architecture

### Where the SDK client lives

One place: `tools/uworld-notes-question-generator/generate_uworld_questions.py`,
in a new function `_gemini_client()`.

```python
# New in phase12-vertex-migration
from google import genai  # google-genai SDK
import os

_GEMINI_BACKEND = os.environ.get("GEMINI_BACKEND", "ai_studio").strip().lower()
_GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "shamsulalamx").strip()
_GCP_REGION = os.environ.get("GCP_REGION", "us-central1").strip()

_gemini_client_singleton = None

def _gemini_client():
    """Return a singleton google-genai client configured for the current backend.

    GEMINI_BACKEND=ai_studio  → uses GEMINI_API_KEY (current behavior)
    GEMINI_BACKEND=vertex     → uses ADC + GCP_PROJECT_ID + GCP_REGION

    Idempotent — first call constructs, subsequent calls return cached client.
    """
    global _gemini_client_singleton
    if _gemini_client_singleton is not None:
        return _gemini_client_singleton

    if _GEMINI_BACKEND == "vertex":
        _gemini_client_singleton = genai.Client(
            vertexai=True,
            project=_GCP_PROJECT,
            location=_GCP_REGION,
        )
    elif _GEMINI_BACKEND == "ai_studio":
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise EnvironmentError(
                "GEMINI_BACKEND=ai_studio requires GEMINI_API_KEY env var"
            )
        _gemini_client_singleton = genai.Client(api_key=api_key)
    else:
        raise ValueError(
            f"GEMINI_BACKEND must be 'ai_studio' or 'vertex', got: {_GEMINI_BACKEND!r}"
        )

    return _gemini_client_singleton
```

### How calls change

**Before** (current `_raw_gemini_call` — raw urllib):
```python
def _raw_gemini_call(api_key: str, prompt: str) -> str:
    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 16384},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST",
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        raise ValueError(f"Gemini HTTP {e.code}: {body_text[:400]}")
    candidates = raw.get("candidates", [])
    if not candidates:
        raise ValueError(f"Gemini returned no candidates: {json.dumps(raw)[:300]}")
    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise ValueError("Gemini returned empty parts in candidate")
    return parts[0].get("text", "")
```

**After** (SDK-based, backend-agnostic):
```python
def _raw_gemini_call(api_key: str, prompt: str) -> str:
    """Single Gemini call. api_key arg kept for signature compat with callers;
    actual auth now flows through _gemini_client() based on GEMINI_BACKEND."""
    client = _gemini_client()
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,  # "gemini-2.5-flash" works on both backends
            contents=prompt,
            config={
                "temperature": 0.4,
                "max_output_tokens": 16384,
            },
        )
    except Exception as exc:
        # Re-raise with a string format compatible with is_quota_failure /
        # is_network_failure text matching in the calling retry layer.
        raise ValueError(f"Gemini call failed: {exc}") from exc

    if not response.text:
        raise ValueError(f"Gemini returned empty text: candidates={response.candidates!r}")
    return response.text
```

Net diff per call site: ~30 lines deleted, ~15 lines added. Across 9 call
sites: ~270 lines deleted, ~135 added.

### Multimodal calls (`raw_gemini_image_call` and friends)

**Before** (current — inline base64):
```python
parts = [{"text": prompt}]
for image_path in image_paths:
    parts.append({
        "inline_data": {
            "mime_type": mime_for(image_path),
            "data": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        }
    })
# ... urllib POST ...
```

**After** (SDK — `Part.from_bytes` helper):
```python
from google.genai import types

contents = [prompt]
for image_path in image_paths:
    contents.append(types.Part.from_bytes(
        data=image_path.read_bytes(),
        mime_type=mime_for(image_path),
    ))

response = client.models.generate_content(
    model=GEMINI_MODEL,
    contents=contents,
    config={
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "response_mime_type": response_mime_type,  # if set, "application/json"
    },
)
```

The SDK handles base64 encoding internally. Works identically on both backends.

### Files API (Divine — DEFERRED to tomorrow)

Today's branch does NOT touch the Divine audio Files API path. Reason:
migrating it requires (a) a GCS bucket created with user's auth, (b) lifecycle
rules to auto-delete uploaded audio, (c) swap from `_GEMINI_FILES_BASE`
resumable upload to `google-cloud-storage` SDK upload. Owner needs to be
present.

When Divine migration happens (tomorrow), the pattern will be:
```python
from google.cloud import storage

def _upload_audio_to_gcs(filepath: Path) -> str:
    """Upload to gs://{GCS_BUCKET}/divine-audio/{filename}; return gs:// URI."""
    client = storage.Client(project=_GCP_PROJECT)
    bucket = client.bucket(os.environ["GCS_BUCKET"])
    blob_name = f"divine-audio/{filepath.name}"
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(filepath))
    return f"gs://{os.environ['GCS_BUCKET']}/{blob_name}"

# In _transcribe_with_gemini, swap fileData.fileUri:
file_uri = _upload_audio_to_gcs(filepath)
# Vertex accepts gs:// URIs in fileData
contents = [
    types.Part.from_uri(file_uri=file_uri, mime_type=mime_type),
    prompt,
]
```

For TODAY: Divine's text path (transcript cleaning, question generation)
DOES get migrated since those just use `_uw.call_gemini_with_retry` and other
shared helpers. The audio upload path stays on AI Studio Files API until
tomorrow.

---

## Per-pipeline migration recipe

### Tier 1: Pure delegation (zero code changes)

These pipelines reference `_uw.GEMINI_MODEL`, `_uw.call_gemini_with_retry`,
etc. They migrate automatically when `generate_uworld_questions.py` changes:

- `tools/mehlman-pdf-question-generator/generate_mehlman_questions.py`
- `tools/ome-pdf-question-generator/generate_ome_questions.py`
- `tools/anki-question-generator/generate_anki_questions.py`
- `tools/divine-audio-question-generator/generate_divine_questions.py` (text path)

**Action**: none. Verify by running each in dry-run mode post-migration.

### Tier 2: Direct call site rewrite

These have their own `_raw_gemini_call` or equivalent:

- `tools/uworld-notes-question-generator/generate_uworld_questions.py`
  - `_raw_gemini_call` (text) → rewrite using `_gemini_client()`
- `tools/lecture-slide-question-generator/generate_lecture_slide_questions.py`
  - `raw_gemini_call` (text) → rewrite
  - `raw_gemini_image_call` (multimodal) → rewrite with `types.Part.from_bytes`
- `tools/nbme-pdf-json-generator/extract_pdfs.py`
  - Unnamed call at line 670 → rewrite
- `tools/nbme-pdf-json-generator/nbme_dual_pdf_runner.py`
  - `gemini_call` (text, supports Pro model param) → rewrite preserving model arg
  - `gemini_image` (multimodal with JSON mime) → rewrite
- `tools/images-tables-question-generator/generate_images_tables_questions.py`
  - Unnamed multimodal at line 269 → rewrite

Each: ~30-line replacement. Identical pattern.

### Tier 3: Files API (Divine audio) — DEFERRED

Skipped today. Documented above.

---

## Error mapping (Vertex-specific quota phrases)

Update `is_quota_failure` in `generate_uworld_questions.py:350`:

```python
def is_quota_failure(error) -> bool:
    text = str(error).lower()
    return (
        # Existing AI Studio patterns
        "http 429" in text
        or "resource_exhausted" in text
        or "prepayment credits are depleted" in text
        or "quota exceeded" in text
        or "rate limit" in text
        or "too many requests" in text
        # NEW: Vertex-specific patterns (v4.79)
        or "quota metric" in text
        or "online_prediction_requests" in text
        or "generate_content_requests" in text
        or "exhausted the quota" in text
        or "quota_exceeded" in text
    )
```

These come from observed Vertex error messages and the Google Cloud quota docs.
Conservative — if any new pattern emerges in production, easy to add later.

---

## Validation harness

New file: `tools/vertex_migration_validation.py` (~150 lines)

Purpose: run the same prompt through both backends, diff the outputs, report.

Usage:
```bash
# Smoke test: tiny prompt both ways
python3 tools/vertex_migration_validation.py --smoke

# Full validation: pick a small PDF, run Fast Facts on both backends
python3 tools/vertex_migration_validation.py \
  --pipeline fast_facts \
  --input /path/to/small_test.pdf

# Compare JSON outputs (structural + semantic diff)
python3 tools/vertex_migration_validation.py --diff a.json b.json
```

What it does:
1. Smoke test: simple prompt ("Reply with exactly: OK"), both backends, verify
   both return "OK"-ish text. ~2 second test, costs <$0.001.
2. Full validation: invokes the pipeline twice, once with
   `GEMINI_BACKEND=ai_studio`, once with `vertex`. Saves both outputs.
3. Diff: structural comparison (same question count? same schema fields
   populated?) and prose-similarity check. Acceptable diff: question text
   varies (Gemini is non-deterministic at temp>0), all schema fields present
   in both, no field missing or differently typed.

This is the safety net before flipping the default.

---

## Rollback plan

Three rollback levels, increasing scope:

1. **Per-call rollback**: `GEMINI_BACKEND=ai_studio python3 your_command.py`
   overrides for one run. No code change needed.

2. **Default rollback**: change one line in
   `generate_uworld_questions.py` from `_GEMINI_BACKEND = os.environ.get(..., "vertex")`
   back to `..., "ai_studio")`. All future runs revert. One-line revert.

3. **Full rollback**: `git revert <vertex-migration-commit>` on the
   `phase12-vertex-migration` branch. Restores pre-migration state entirely.
   Tag will be removed by `git tag -d`.

The AI Studio code path is NEVER removed in this phase — it stays as the
fallback. Removing it is a separate post-stabilization commit, no sooner than
1 week after cutover.

---

## Cutover plan

Phased — NOT a single switch.

### Phase A: Code complete, default still AI Studio (TODAY)
- All non-Divine pipelines support both backends
- `GEMINI_BACKEND` defaults to `ai_studio` — zero behavior change for the user
- Branch `phase12-vertex-migration` is committed locally
- User can run validation harness whenever ready

### Phase B: Per-pipeline validation (USER, evening/tomorrow)
- Run validation harness for each pipeline
- Compare outputs side-by-side
- Sign off pipeline-by-pipeline

### Phase C: Default flip + tag (USER, when satisfied)
- Change default to `vertex`
- Commit + tag `v4.79-vertex-migration-pending-validation`
- Run a real full-size Fast Facts test on Vertex
- If clean: tag `v4.79-vertex-migration-stable`

### Phase D: Divine GCS migration (TOMORROW, with user)
- Set up GCS bucket
- Migrate Divine Files API path
- Validate audio transcription end-to-end
- Tag `v4.80-divine-vertex-stable`

### Phase E: Remove AI Studio code paths (~1 week later)
- After a week of clean Vertex usage with no fallbacks needed
- Delete the `GEMINI_BACKEND=ai_studio` branches
- Single backend, cleaner code

---

## What's NOT in scope for this branch

Explicitly excluded to prevent scope creep:

- Divine audio Files API → GCS migration (Phase D)
- Chunk-level parallelism (separate post-Vertex work)
- Prompt caching (separate optimization)
- Multi-job parallel queue (separate v5.x)
- New model upgrades (e.g., Gemini 3 when it lands)
- Switching non-polish calls to Pro (separate quality pass)
- Front-matter detector for Mehlman (separate bug fix per user observation)
- OAuth refresh token flow (separate Drive sync improvement)

---

## Dependencies

New Python packages needed (user will run `pip install` before validation):

```
google-genai>=0.3.0       # the unified SDK
google-cloud-storage>=2.0  # for Divine GCS (Phase D)
google-auth>=2.0           # transitive but worth pinning
```

Existing deps (no change): `striprtf`, `python-docx`, `requests`, standard
library.

---

## Open questions for user (review when home)

None blocking. All decisions locked above. Three things to confirm at
review time:

1. **Project ID**: confirmed as `shamsulalamx` ✓
2. **Region**: confirmed as `us-central1` ✓
3. **Branch name**: `phase12-vertex-migration` — acceptable?

---

End of Stage 1 design. Stage 2 (implementation) begins after user sends
the ADC token prefix verification (step 5 from prep checklist).
