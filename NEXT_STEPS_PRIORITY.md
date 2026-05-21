# Next Steps Priority

Last updated: 2026-05-21

This roadmap prioritizes convergence while protecting validated behavior.

## 1. Divine Transcript/Audio Profile Or UWorld Notes

Rationale: OME now has a validated dry-run BIC profile. The next broad architecture step should move to Divine transcript/audio or UWorld notes after the roadmap choice is made.

Risk: Medium-high. Both candidates have source-sensitive semantics and save/import boundaries that should be validated narrowly.

Architectural impact: Extends profile architecture beyond the newly validated OME PDF dry-run path.

Validation requirements: Choose one candidate and validate a small source sample through normalized artifacts, downstream output, import, quiz, score, and reload.

## 2. OME Live Policy Or Writable Output Migration

Rationale: OME dry-run orchestration is validated. Further OME work should either define a live-generation policy and semantic review bar or move generated packaged output to a writable app-data location.

Risk: Medium-high. Dry-run proof does not validate live generation quality, and packaged resource writes may fail in a non-writable distribution.

Architectural impact: Keeps the validated OME dry-run boundary intact while addressing the next real OME risk.

Validation requirements: For live work, review real generated OME content and packaged import behavior. For output migration, prove packaged BIC discovery and reload persistence from a writable destination.

## 3. Divine Transcript/Audio Profile

Rationale: Divine already has transcript/audio workflows and can test transcript chunk types in shared ingestion.

Risk: Medium-high. Transcript cleaning and semantic refinement are source-sensitive.

Architectural impact: Brings transcript/audio modality toward profile architecture.

Validation requirements: transcript chunk emission, draft generation/refinement path, save gates, import, score, reload. Avoid broad prompt rewrites.

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
