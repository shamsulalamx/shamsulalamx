# Next Steps Priority

Last updated: 2026-05-23

Current stable tag: `v4.48-lecture-explanation-tables-stable`.

This roadmap prioritizes convergence while protecting validated behavior. The new top item is the lecture-slide chunk-planning fix surfaced during the v4.48 validation pass.

## 0. Lecture-Slide Chunk-Planning Quota-Aware Recovery (fix landed, live validation pending)

Status: Implementation landed in HEAD on 2026-05-23. Two complementary changes in `tools/lecture-slide-question-generator/generate_lecture_slide_questions.py`:

1. **Quota-aware retry stop.** `is_quota_failure(error)` detects HTTP 429 / `RESOURCE_EXHAUSTED` / prepayment-depleted text. A module-level `_QUOTA_EXHAUSTED` latch is set on first occurrence. Every retry boundary in `generate_question_chunk_with_retries` and the cross-chunk loop in `generate_questions` checks the latch and bails to `[]`. Protects whatever was already generated; no further budget burn.

2. **Targeted missing-slide retry.** The chunk loop still uses partial-accept (`require_exact_count=False`) to preserve the historical behavior that prevents unbounded sub-chunking. After all chunks complete, `generate_questions` now computes per-slide deficit and calls `retry_missing_slide_questions()` for each under-delivered slide. That function makes up to `MAX_RECOVERY_ATTEMPTS_PER_SLIDE` (=2) focused single-slide attempts with `require_exact_count=True`. Bounded worst-case extra API calls: `len(work) * 2`. Quota-aware.

Offline tests pass (predicate classification, latch idempotency, constant value). Packaged app rebuilt.

Live validation pending: requires Gemini credits. Once topped up, run the same Test_Emma fixture through BIC and verify:

- allocated count ≈ generated count (parity restored),
- if a 429 lands mid-run, the run terminates cleanly with all questions generated before the 429 preserved (not 0),
- the total Gemini call count is bounded by `chunks + len(missing_slides) * 2`,
- the run report should include warnings naming each recovered or unrecovered slide.

Tag candidate once live validation passes: `v4.49-lecture-chunk-recovery-stable`.

Risk going forward:

- If Gemini consistently short-returns even at single-slide scope (e.g. a slide whose content fundamentally fails the prompt's constraints), the recovery loop will give up cleanly after 2 attempts with a clear warning. That's the right behavior — better than silent loss and better than runaway retries.
- The 2-attempt cap can be tuned via `MAX_RECOVERY_ATTEMPTS_PER_SLIDE` if needed. Default deliberately small to keep cost predictable.

## 1. Controlled Divine Audio Operationalization

Rationale: Divine Transcript now has a validated transcript-first dry-run BIC milestone. If Divine work is pursued next, the next step is controlled audio and `.mp3` operationalization through the existing Divine generator, not a new architecture branch.

Risk: Medium-high. Audio input and live generation add source-sensitive operational and semantic risk that the dry-run transcript proof does not cover.

Architectural impact: Extends the existing Divine generator boundary carefully while preserving the validated transcript dry-run path.

Validation requirements: Start with a controlled audio sample, keep the existing generator boundary, prove output location and import behavior, and separate transcription from live question quality claims.

## 2. Broader Fast Facts Validation

Rationale: Fast Facts now has a narrow screening stabilization pass with diagnostic reporting, a capped live BIC validation path, and one observed Turner Syndrome screening ontology failure fixed. The next Fast Facts step is to widen evidence without turning that pass into a broad stability claim.

Risk: High. One small PPTX and one final app-ready question do not establish broad semantic stability.

Architectural impact: Extends validation of the existing path while preserving the current capped stabilization registry mode.

Validation requirements: Add controlled Fast Facts deck coverage, run packaged validation for the screening fix before packaged claims, review diagnostic reports, and keep importer, render, score, and reload evidence tied to each claim. Track the global Gemini alert mismatch separately as a UI consistency issue.

## 3. OME Live Policy Or Writable Output Migration

Rationale: OME dry-run orchestration is validated. Further OME work should either define a live-generation policy and semantic review bar or move generated packaged output to a writable app-data location.

Risk: Medium-high. Dry-run proof does not validate live generation quality, and packaged resource writes may fail in a non-writable distribution.

Architectural impact: Keeps the validated OME dry-run boundary intact while addressing the next real OME risk.

Validation requirements: For live work, review real generated OME content and packaged import behavior. For output migration, prove packaged BIC discovery and reload persistence from a writable destination.

## 4. Anki Live Generation And Semantic Hardening

Rationale: The Anki dry-run BIC profile is validated. The next Anki work is live generation and semantic hardening only if that direction is desired.

Risk: Medium-high. Dry-run import proof does not establish semantic question quality, export variation coverage, or non-Anki regression safety.

Architectural impact: Extends the validated text/card-style dry-run profile into a live semantic path without weakening the existing wrapper boundary.

Validation requirements: live Gemini generation, semantic review on real Anki samples, export variation coverage, app-ready import, score, reload, packaged validation, and non-Anki regression checks after UI changes.

## 5. UWorld Notes

Rationale: UWorld notes are important and already have deterministic save discipline.

Risk: Medium-high. Concept clustering can overmerge distinct facts.

Architectural impact: Tests shared profile architecture on note-derived concepts and approved draft workflows.

Validation requirements: raw concepts, deduped representatives, clusters, approved drafts, app-ready output, deterministic save, score/reload.

## 6. Shared Downstream Reuse

Rationale: Current profiles still reuse source-specific downstream generators.

Risk: High. Premature abstraction could destabilize validated generators.

Architectural impact: Moves the project closer to true profile convergence.

Validation requirements: one source at a time. Prove output equivalence or improvement before switching a source.

## 7. Semantic Validator Hardening

Rationale: Validators are blocking legitimate content, as seen with Emma `dystocia`.

Risk: High. Loosening validators globally can let hallucinated or unsupported content pass.

Architectural impact: Improves live generation reliability if done source-aware.

Validation requirements: source-specific failing examples, negative controls, no global loosening without tests.

## 8. Multimodal Grounding Improvements

Rationale: Images & Tables currently preserves assets but does not deeply understand them.

Risk: High. Visual semantic generation can hallucinate.

Architectural impact: Adds richer image/table reasoning above the attachment-first baseline.

Validation requirements: small curated set, visual inspection, OCR/asset provenance, generated question review, packaged rendering.

## 9. Scalable Asset Caching

Rationale: Multimodal and large-source workflows need cache discipline.

Risk: Medium. Cache invalidation bugs can silently reuse stale assets.

Architectural impact: Adds source-hash-backed asset cache indexes to shared ingestion.

Validation requirements: cache hit/miss reports, changed-file invalidation, packaged resource path checks.

## 10. Deeper Table Parsing

Rationale: Table images currently remain images with OCR text. Structured rows/columns would support better downstream questions.

Risk: High. Poor OCR can corrupt table semantics.

Architectural impact: Adds structured table refs and possibly table-specific validation.

Validation requirements: small table set with known expected rows, OCR confidence, visual review, import/render.

## 11. Full Profile Architecture Convergence

Rationale: Long-term maintainability improves if each source becomes a descriptor plus adapter plus validated downstream path.

Risk: High. Full convergence should not override source-specific validated behavior.

Architectural impact: Completes the profiles-not-pipelines transition.

Validation requirements: migrate one source at a time, preserve rollback tags, require source-level and packaged validation for each.
