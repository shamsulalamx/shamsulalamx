# Next Steps Priority

Last updated: 2026-05-23

Current stable tag: `v4.48-lecture-explanation-tables-stable`.

This roadmap prioritizes convergence while protecting validated behavior. The new top item is the lecture-slide chunk-planning fix surfaced during the v4.48 validation pass.

## 0. Lecture-Slide Chunk-Planning Quota-Aware Recovery — DONE (tagged v4.49)

Resolved 2026-05-23. Tagged `v4.49-lecture-chunk-recovery-stable` covering commits `1c1f744` + `6c0ce4f`.

Field validation evidence (BIC job `batch-mpis1xxn-c0i3id` on Test_Emma):

- 18 allocated → 17 generated (94.4%).
- 5 slides initially short-returned (s0001, s0002, s0004, s0007, s0008).
- Recovery loop fired for each; 4 successfully recovered.
- 1 (s0008) stopped cleanly after a Gemini network timeout via the existing `is_network_failure` check (attempt 1/2 of recovery).
- Runtime 369.8s for the full deck (vs the prior naive-fix run that ended with 0 questions and depleted the budget).
- 4 questions carry inline tables (v4.48 rendering also exercised end-to-end).
- BIC auto-imported as "Test Emma Lecture Questions" with no errors.

Earlier field validation of the defensive half (quota-aware retry stop only) on the depleted-credits run (job `batch-mpirtu3n-1cfsur`): 1 HTTP 429 caught on chunk1 attempt0, all subsequent retries skipped, runtime 10.5s vs the prior 148s naive-cascade run.

If the 2-attempt cap proves insufficient on a specific deck, tune `MAX_RECOVERY_ATTEMPTS_PER_SLIDE` upward. Default is deliberately small to keep worst-case cost predictable.

## 0b. Chunk-planning silent-loss audit — UWorld family DONE (tagged v4.54), NBME still open

UWorld-family resolution: tagged `v4.54-uworld-chunk-planning-recovery-stable` (commit `0c3e389`). Single source change in `tools/uworld-notes-question-generator/generate_uworld_questions.py` ports the v4.49 quota-aware retry stop + per-chunk shortfall recovery pattern. Applies automatically to all five UWorld-wrapping generators (Anki, OME, Mehlman, Divine, UWorld) since they reuse the machinery via `import generate_uworld_questions as _uw`.

Still open: NBME PDF generator (`tools/nbme-pdf-json-generator/`). It has its own normalization stage and does not wrap the UWorld machinery, so the v4.54 fix does not apply to it. Audit: run a live NBME BIC job, check whether the BIC report's question count matches what the normalization stage allocated. If mismatched silently, port the same predicate + latch + recovery pattern to that generator.

Risk: Medium. NBME's separate normalization path needs its own audit and possibly its own version of the recovery loop.

## 0c-anki. UWorld-family review-survivor flow — DONE (tagged v4.53)

Resolved 2026-05-23. Tagged `v4.53-uworld-family-review-survivor-stable` (commit `8f213d5`).

A single source change in `tools/uworld-notes-question-generator/generate_uworld_questions.py` adds a `write_uworld_family_review_draft()` helper, a `needs_review_collector` opt-in parameter on `call_gemini_with_retry()`, and the `process_file()` integration that writes a `uworld_family_review_draft.json` matching the schema BIC's `discover_review_draft()` and the renderer's existing review modal expect. Because OME, Mehlman, Divine, Anki, and UWorld all reuse this machinery via `import generate_uworld_questions as _uw`, the fix took effect for all 5 wrappers in one commit.

Offline-validated; not field-validated by this milestone because the failure path requires Gemini to fail both initial validation and repair on a live run. User chose to wait for that to happen organically.

## 0c. OME live-generation broader validation

Rationale: v4.51 validated OME live generation on a single small user-supplied PDF. Before claiming broad OME stability:

- Run a varied set of OME PDFs (different lecture lengths, different chapters, different visual density).
- Audit figure/table extraction quality on PDFs that have them.
- Confirm packaged-vs-dev parity on a signed or notarized build if distribution matters.
- Confirm allocated-vs-generated parity (see 0b).

Risk: Medium. The plumbing is field-validated; semantic and edge-case coverage is not.

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
