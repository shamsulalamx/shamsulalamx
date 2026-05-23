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

## 0b. OME (and other generators) — chunk-planning silent-loss audit (still open)

Rationale: The v4.49 chunk-planning fix lives in `generate_lecture_slide_questions.py` (Emma, Fast Facts, AMBOSS share this binary). Other source-specific generators have their own retry paths:

- `tools/ome-pdf-question-generator/generate_ome_questions.py` (wraps UWorld machinery)
- `tools/mehlman-pdf-question-generator/generate_mehlman_questions.py` (wraps UWorld machinery)
- `tools/nbme-pdf-json-generator/` (uses Gemini through its own normalization stage)
- `tools/divine-audio-question-generator/generate_divine_questions.py` (wraps UWorld machinery)
- `tools/anki-question-generator/generate_anki_questions.py` (wraps UWorld machinery)

Each should be checked for the same pattern: does the generator silently accept short Gemini returns at the chunk boundary? If yes, port the v4.49 quota-aware retry stop + targeted missing-slide recovery pattern.

Note: the v4.51 stem-quality validator catches a DIFFERENT class of bug (well-formed questions whose stem doesn't end with '?') — it does NOT catch chunk-level under-delivery. Both audits are still needed.

Validation: compare `allocated vs generated` from the first live BIC run of each source. Mismatch with no surfaced error → port the fix.

Risk: Medium. The four UWorld-wrapping generators share machinery, so the fix may port cleanly to UWorld's own loop and benefit all four at once. NBME's separate normalization path needs its own audit.

## 0c-anki. UWorld-family review-survivor flow (new gap surfaced at v4.52)

Rationale: The v4.50 review-survivor flow that lets the user manually accept / reject / edit questions that failed validation only exists in the lecture-slide generator (Fast Facts / Emma / AMBOSS). The UWorld-family wrappers (Anki, OME, Mehlman, Divine, UWorld) fall back to the in-band repair retry path inside `validate_question()`/`call_gemini_with_retry()`; if repair still fails, the question is kept with `extractionWarnings` rather than surfaced for human review.

This is fine when most questions pass validation cleanly (the v4.52 Anki run was 15/15). It becomes a gap when a chunk's parse fails or a non-trivial fraction of questions need review.

Approach: extend the v4.50 review-draft writer pattern to the UWorld wrappers. Each wrapper's wrapper-level `process_file()` would also emit a `review_draft.json` to the BIC job's `review/` directory when one or more questions land in the "kept with warnings" bucket instead of the clean output. The renderer review UI already exists and is generator-agnostic.

Risk: Medium. The validation-loop refactor in UWorld touches every wrapping generator; need to make sure dry-run mode does not produce review drafts and that the wrapper path stays compatible with non-BIC standalone CLI usage.

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
