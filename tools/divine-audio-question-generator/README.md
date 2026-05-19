# Divine Intervention Podcast Audio → Step 2 Question Generator

External tool pipeline that converts Divine Intervention podcast audio into
`nbme-gemini-json-v3` app-ready JSON, ready for import into the NBME Self-Assessment app.

---

## Pipeline

```
Audio file (input_audio/)
  │
  ▼ Stage 2: Gemini File API upload + generateContent
  │   transcripts/raw/<stem>_raw.txt          ← verbatim transcript
  │
  ▼ Stage 3: Gemini transcript cleanup
  │   transcripts/cleaned/<stem>_cleaned.txt  ← ads/intros removed, clinical content preserved
  │
  ▼ Stage 4: split_into_chunks()              (reused from UWorld generator)
  │   output_json/chunks/<stem>_chunks.json
  │
  ▼ Stage 5: Gemini question generation + validation + retry/repair
  │   Prompt: prompts/divine_audio_to_questions_prompt.txt
  │   Schema: nbme-gemini-json-v3, sourceFormat: divine-audio
  │   Validation + retry: reused from UWorld generator
  │
  ▼ output_json/app_ready/<stem>_app_ready.json
  │
  ▼ Import via: App → NBME Gemini JSON importer
```

---

## Usage

### Dry-run (no API key required)

```bash
cd tools/divine-audio-question-generator
python3 generate_divine_questions.py --dry-run
python3 generate_divine_questions.py --dry-run --questions-per-file 10
```

Operates on existing cleaned transcripts in `transcripts/cleaned/`. A synthetic test
fixture is committed: `test_divine_heart_failure_cleaned.txt`.

### Stage-by-stage (incremental, recommended for large episodes)

```bash
export GEMINI_API_KEY='your-api-key-here'

# Stage 2: Transcribe audio → raw transcripts
python3 generate_divine_questions.py --transcribe-only

# Stage 3: Clean raw transcripts → cleaned transcripts
python3 generate_divine_questions.py --clean-only

# Preview chunking (optional, no API call)
python3 generate_divine_questions.py --chunk-only

# Stage 5: Generate questions from existing cleaned transcripts
python3 generate_divine_questions.py --generate
```

### Full pipeline in one command

```bash
export GEMINI_API_KEY='your-api-key-here'
python3 generate_divine_questions.py --generate
python3 generate_divine_questions.py --generate --questions-per-file 15
```

**Incremental run behavior:** `--generate` automatically reuses existing raw and cleaned
transcripts. If `transcripts/raw/<stem>_raw.txt` exists, transcription is skipped.
If `transcripts/cleaned/<stem>_cleaned.txt` exists, cleaning is also skipped.
Delete those files to force re-transcription or re-cleaning.

---

## Input

Drop audio files into `input_audio/`. Supported formats:

| Format | MIME type |
|---|---|
| `.mp3` | `audio/mpeg` |
| `.m4a` | `audio/mp4` |
| `.wav` | `audio/wav` |

---

## Output

`output_json/app_ready/<stem>_app_ready.json`

Import via: **App → Import → NBME Gemini JSON → select file → validate → preview → save**

---

## Dependencies

| Package | Required | Notes |
|---|---|---|
| Python ≥ 3.9 | Required | `str.removesuffix()` used |
| Gemini API key | Required for all except `--dry-run`, `--chunk-only` | `export GEMINI_API_KEY=...` |

No additional pip packages required. All Gemini infrastructure is inherited from the
UWorld generator (raw `urllib.request` — no SDK).

---

## Stage Details

### Stage 2: Transcription

- Uploads audio to Gemini File API (multipart/related POST)
- Polls until file state is `ACTIVE` (exponential backoff: 5s, 10s, 15s … 30s)
- Calls `generateContent` with the audio file reference + transcription prompt
- Upload timeout: 600 seconds (10 minutes) for large files
- Transcription timeout: 300 seconds (5 minutes)
- Max output: 65,536 tokens (~3 hours of audio) — warns if truncated

### Stage 3: Transcript cleaning

- Removes advertisements, intros, housekeeping, repetitive content
- Preserves all clinical teaching, algorithms, pearls, management logic
- Groups content by topic with clear headings
- Input cap: 120,000 chars (~90 min episode) — warns if exceeded
- Output: up to 32,768 tokens

### Stage 4: Chunking

- Reuses `split_into_chunks()` from UWorld generator
- Heading-based splits at UPPERCASE topic headers
- Paragraph fallback when headings are absent
- Max chunk size: 3,000 chars

### Stage 5: Question generation

- NBME/Step 2 CK clinical vignette style
- Avoids podcast-dependent phrasing ("according to the podcast")
- Prioritizes management, diagnosis, complications, contraindications
- Validation + 1 automatic repair retry per chunk
- `sourceFormat: "divine-audio"` in output

---

## Report fields

Each run produces a report in `reports/divine_generation_report_<timestamp>.json`.

Per-file fields (`files.<stem>.*`):

| Field | Description |
|---|---|
| `cleanedChars` | Character count of cleaned transcript |
| `chunksProcessed` | Number of chunks sent to Gemini |
| `questionsGenerated` | Questions produced for this file |
| `validationFailures` | Questions that failed initial validation |
| `repairsSucceeded` | Questions successfully repaired on retry |
| `repairFailures` | Questions that failed both attempts |
| `warnings` | Per-chunk warnings and errors |
| `chunkStats` | Per-chunk status, requested, generated |

---

## Known Limitations

| Limitation | Details |
|---|---|
| No progress bar during upload | urllib.request blocks synchronously; upload can take 1-10 min for 100 MB files |
| Transcription may be truncated | Episodes > ~3 hours may exceed 65,536 output tokens; a warning is logged |
| Cleaning cap at 120,000 chars | Episodes > ~90 min may exceed the cleaning prompt cap; first 120K chars cleaned |
| No automatic file deletion | Uploaded files remain on Gemini servers for 48 hours (auto-deleted by Gemini) |
| No resumable upload protocol | Files > 100 MB use simple multipart upload; may fail on very slow connections |
| Real audio not testable in dry-run | `--dry-run` uses the committed test transcript, not actual audio transcription |

---

## Test Fixtures

| File | Purpose |
|---|---|
| `transcripts/cleaned/test_divine_heart_failure_cleaned.txt` | Synthetic cleaned transcript for `--dry-run`. ~5,000 chars of HFrEF/HFpEF content. |

---

## Infrastructure Reuse

This tool is a standalone pipeline that imports specific functions from
`tools/uworld-notes-question-generator/generate_uworld_questions.py`.

Reused without modification:

- `_raw_gemini_call()` — Gemini HTTP client (no SDK)
- `_clean_llm_json()`, `_extract_json_payload()`, `_parse_gemini_json()` — JSON cleaning
- `validate_question()` — schema enforcement
- `call_gemini_with_retry()`, `_build_repair_prompt()` — retry/repair flow
- `split_into_chunks()` — heading-based chunker
- `build_app_ready_json()` — produces `nbme-gemini-json-v3`
- `write_report()` — consistent report format
- `_placeholder_question()` — dry-run placeholders
- `check_duplicate_stems()`, `renumber_questions()`

Divine-specific components:

1. Gemini File API upload (`_upload_audio_file()`)
2. File state polling (`_poll_file_active()`)
3. Audio-aware `generateContent` call (`_transcribe_with_gemini()`)
4. Transcript cleaning with high-token output (`_gemini_text_call()`, `clean_transcript()`)
5. Multi-stage CLI with incremental run support
6. `prompts/transcribe_audio_prompt.txt` — verbatim transcription prompt
7. `prompts/clean_transcript_prompt.txt` — structured cleaning prompt
8. `prompts/divine_audio_to_questions_prompt.txt` — board-style question generation

---

## Verification Checklist

Before declaring a run successful:

- [ ] `schemaVersion` is `"nbme-gemini-json-v3"` in output
- [ ] `sourceFormat` is `"divine-audio"` in output
- [ ] All questions have 4 answerChoices (A-D)
- [ ] All questions have non-empty `retrievalTag` and `reviewPearl`
- [ ] No "according to the podcast" wording in any question
- [ ] App import: validation modal shows ≥ 90% pass rate
- [ ] App import: preview shows full stems without truncation
- [ ] App import: quiz runs correctly on imported test
