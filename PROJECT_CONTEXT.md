# NBME Self-Assessment Suite — Current Project Context

Last verified: 2026-05-11. Cross-referenced with `PROJECT_STATUS_2026-05-08.md` and Divine Gemini Step 3 IPC implementation.

Ownership: this file records durable architecture rules and long-lived constraints. Runtime snapshot details belong in `PROJECT_STATUS_2026-05-08.md`; staged Electron decisions belong in `ELECTRON_MIGRATION_PLAN.md`; operational prompts should stay in the prompt files.

## Core Rules

- `index.html` is the authoritative working app.
- Keep active app edits inside `index.html`.
- Do not split the current browser app into external CSS or JavaScript files.
- **Always use `npm run electron:dev` for development and testing.** The packaged `.app` at `dist/mac-arm64/` contains its own stale copy of `index.html` and will not reflect edits to the project root. Running the packaged app caused multiple failed debugging sessions on 2026-05-12. If you must test the packaged app, sync the bundle first: `cp index.html dist/mac-arm64/"NBME Self-Assessment Suite.app"/Contents/Resources/app/index.html`
- **Current platform:** Electron desktop is the primary and active platform. New pipeline work (Divine Gemini, UWorld Gemini) is implemented through Electron main/preload IPC. Browser mode and Netlify remain available as compatibility/rollback layers but are no longer the intended workflow for AI refinement.
- The Electron migration may add Electron-specific scaffolding such as `package.json`, `electron/main.js`, and `electron/preload.js`. That does not change `index.html` being the current authoritative app during the transition.
- Old split files may exist, but they are not the active implementation.
- Keep the Gemini model string exactly `gemini-2.5-flash`.
- Netlify Functions still exist in the codebase as a rollback path but Divine Gemini refinement does not depend on Netlify. All active Gemini work (UWorld and Divine) runs through Electron main/preload IPC using `gemini-2.5-flash`. `GEMINI_API_KEY` must be read from `process.env` only in `electron/main.js`. Do not put Gemini API keys in frontend JavaScript, renderer code, localStorage, Google Drive backups, debug exports, or packaged assets.
- Supabase is not active. Do not reintroduce Supabase unless explicitly requested.
- Keep full-quality question stems, figures, and exhibits in IndexedDB via `FigureStore` or in Google Drive. Do not store large image data in localStorage.
- Google Drive OAuth currently depends on an approved HTTP/HTTPS origin. Local development should use `http://localhost:8888` as the primary origin, or `http://localhost:8080` as a secondary/fallback origin, only if those origins are added in Google Cloud Console. `file://` is not supported for current Drive or Gemini workflows.
- The app is currently private/personal use only. Electron security decisions, including local user-provided API keys or OAuth token storage, should be evaluated in that context and revisited if public distribution is ever planned.

## Active App

The project is a single-page browser app written in plain HTML, CSS, and JavaScript inside `index.html`.

Main inline modules:

- `DB`: localStorage metadata, source folders, subfolders, tests, marks, flags, notes, history, and settings.
- `FigureStore`: IndexedDB image storage for question stems, figures, exhibits, and restored Drive images.
- Google Drive backup: Drive folder, manifest, image upload, and restore.
- Netlify Functions: secure Gemini tagging, hint, and analysis requests.
- `OCR`: PDF extraction, OCR fallback, parsing, stem crop generation, and answer parsing.
- `Quiz`: test-taking engine, timers, answer selection, hints, stem-image rendering, highlighting, and navigation.
- `Results`: score report, review mode, analytics, and PDF report generation.
- `App`: study library landing page, source-folder routing, sidebar navigation, modals, search, notes, incorrect, marked, flagged, trash, and test generation.
- OME PDF pipeline: short high-quality PDF import only, PDF.js text-layer extraction, structure/block preview, concept extraction, concept clustering, selected clusters, deterministic draft preview, review controls, approved-draft JSON export, quiz-object preview, and controlled save into real tests.
- Anki text-import pipeline: plain-text `.txt` import only, no `.apkg` support, normalized card preview, cloze/basic concept extraction, tag-first clustering, deterministic variant draft preview, review controls, approved-variant JSON export, quiz-object preview, and controlled save into real tests.
- UWorld DOCX pipeline: DOCX import, normalized blocks, concept extraction, deterministic clustering/deduplication, selected clusters, deterministic draft scaffolds, one-at-a-time Electron-local Gemini refinement, live batch queue controls, review controls, duplicate warnings, coverage summaries, preflight safeguards, approved draft JSON export, quiz-object preview, and controlled save into real tests.
- Divine Podcasts pipeline: transcript text import, cleaning, segmentation, concept extraction, teaching-cluster construction, deterministic draft scaffolds, one-at-a-time Electron-local Gemini refinement (`nbme:ai:refine-divine-draft`), review controls, approved-draft JSON export, quiz-object preview, and controlled save into real tests. Gemini identifies the testable medical fact from each teaching cluster; the deterministic layer manages structure, provenance, and validation.
- **NBME Gemini JSON pipeline (added 2026-05-12):** JSON import of pre-structured NBME exam data. The user runs a full NBME exam through Gemini externally (outside this app) with a structured extraction prompt, receiving a JSON file with all stems, choices, answer keys, educational objectives, explanation sections, and figure references. The app validates the JSON schema, normalizes it into the internal quiz schema, provides an import preview with full stems, optionally accepts user-uploaded figure images for inline rendering, and saves into a real test. No in-app Gemini call is made. Source type: `nbme-gemini-json`. Full spec: `NBME_JSON_IMPORT.md`. Known issue: quiz stem truncation for long stems is **unresolved** as of 2026-05-12 (see `BUGS_AND_NEXT_STEPS.md`).

## Current Stable Parser And Rendering State

The local grouped-question pipeline is stable and verified locally. The current confirmed behavior is:

- OCR, normalization, parsing, answer merge, final quiz construction, and rendering preserve the expected source question count.
- Source-number recovery is functioning, including fallback recovery when OCR page headers miss an item number but the item number appears in the normalized paragraph text.
- Source-number audits, final-count integrity checks, focused parser exports, grouped range audits, and `parseSkippedItems` diagnostics are available through local-only parser debug tooling.
- Local-only debug tooling should stay hidden or disabled in production unless intentionally exposed.
- Parser debug artifacts may contain copyrighted or private exam content and should remain local/private.
- Quoted answer-choice parsing is functioning.
- Grouped item carry-forward is functioning for shared instructions, shared stems, and shared answer banks.
- Grouped shared instructions and shared stems render correctly.
- Grouped answer banks render once, use `sharedGroup.sharedChoices` as the authoritative choice source, and remain independently selectable and independently scored for each linked question.
- Grouped rendering prioritizes structured parsed text over cropped stem-image layout when the crop would duplicate or misorder grouped content.
- Duplicate lab/table fragments that are already present in the parsed stem are suppressed in grouped rendering.
- OCR normalization fixes for damaged screenshot-based text are active and should remain conservative.
- Temporary question-specific debugging instrumentation has been removed.
- Saved/generated quizzes created before parser or render fixes may be stale. Do not silently mutate existing saved quizzes; regenerate or explicitly reparse them.
- Fixture and debug infrastructure is part of the parser/render safety net and should be preserved.

## Future Importer And Render Direction

The current migration direction is staged Electron adoption with desktop as the long-term primary platform. Early Electron work should keep wrapping the current app without changing app behavior. Browser and Netlify paths should remain working until Electron-native Gemini, storage, backup/restore, and packaging paths are implemented and verified. Avoid rewrites during initial migration.

Future importer and render work should preserve the current stable browser behavior while moving toward a clearer architecture:

- All source types should normalize into a common intermediate format before quiz generation.
- The intermediate format should preserve both parsed text and available stem/image crops.
- Do not overfit importers to NBME. Use adapters for multiple modalities, including PDFs, DOCX, pasted text, Anki, audio/podcast transcripts, video transcripts, and lecture notes.
- Rendering should support per-question text, image, and hybrid render modes.
- Render mode should be reviewable and editable by the user before final quiz save when confidence is low.
- Render behavior should be driven by metadata, confidence, and content type, not by historical question numbers.
- Future architecture is moving toward a canonical intermediate question schema that separates OCR repair, normalization, semantic parsing, rendering, and persistence.
- Future architecture may further separate OCR cleanup, semantic parsing, and render adaptation to reduce coupling and regression risk.
- Render-mode policy:
  - Text mode for clean structured stems and grouped questions.
  - Image mode for figure-heavy, layout-sensitive, or OCR-corrupted stems.
  - Hybrid mode for usable text plus figures, tables, or images.
  - User override per question.
- Netlify Functions remain available as a transitional/rollback path only. All active Gemini refinement (UWorld and Divine) now runs through Electron main/preload IPC. Future Gemini pipeline additions should follow the same narrow main/preload API pattern. Netlify support should not be removed until a tested rollback plan is in place, but new features should not depend on it.
- Browser-only storage assumptions should eventually be replaced by Electron app-data persistence, but `localStorage`, IndexedDB, `FigureStore`, Google Drive backup, and Netlify support must not be removed until desktop replacements are verified and rollback is available.

## UWorld Notes Pipeline

The UWorld DOCX importer is separate from the NBME PDF parser/OCR/render path. UWorld work must not modify NBME parser logic, OCR normalization, grouped-question handling, or existing rendering invariants.

Status: UWorld v1 implementation complete. Electron Gemini JSON extraction hardened (tagged uworld-gemini-v1-stable). Pending real-world validation.

Current UWorld flow:

```text
DOCX import
→ normalized blocks
→ concept extraction
→ deterministic clustering/deduplication
→ selected clusters
→ deterministic draft scaffolds
→ one-at-a-time Electron-local Gemini refinement
→ review controls
→ duplicate warnings and coverage summaries
→ approved draft JSON export
→ quiz-object preview
→ controlled save into real tests
```

UWorld saves require approved AI-refined drafts, valid quiz-object previews, an explicit save target, a nonempty test name, and an inline review confirmation. Browser `prompt()`/`confirm()` must not be used for this Electron save flow.

Live batch refinement is implemented as a conservative one-at-a-time Electron main Gemini queue using the existing `window.nbmeDesktop.ai.refineUWorldDraft(...)` bridge. The queue includes draft-hash caching, duplicate skipping, pause/cancel/retry controls, failure stopping, visible progress, preflight confirmation, duplicate refined-question warnings, and section/topic coverage summaries. Live Gemini validation/testing is intentionally deferred to conserve API credits. Netlify Functions remain transitional/rollback support, and no app-data storage migration has been performed.

## OME Notes Pipeline

Status: OME v1 implementation complete. Cluster index provenance bug fixed (tagged ome-v1-stable). Pending real-world validation.

Current OME flow:

```text
short high-quality PDF
→ PDF.js text-layer extraction only
→ structure/block preview
→ concept extraction
→ concept clustering
→ selected clusters
→ deterministic draft preview
→ review controls
→ approved-draft JSON export
→ quiz-object preview
→ controlled save into real tests
```

Current OME safeguards:

- OME accepts short high-quality PDFs and intentionally does not add OCR fallback in v1.
- OME preview uses PDF.js text-layer extraction only.
- `.apkg` is not relevant to OME and remains unsupported only in Anki.
- OME structure, concept, cluster, draft, review, export, preview, and save logic stay isolated from the NBME PDF parser/OCR/render path, the UWorld DOCX path, and the Anki path.
- Approved OME drafts only are eligible for export, quiz-object preview, and controlled save.
- The OME save path requires an explicit OME subfolder target, a nonempty test name, and an inline review confirmation.
- OME provenance stays separate from UWorld provenance and Anki provenance.
- No Gemini is used in the OME v1 path yet.
- OME v1 does not mutate NBME parser/OCR/render behavior.

## Anki Notes Pipeline

Status: Anki v1 implementation complete. Approval-state and save-path bugs fixed (tagged anki-v1-stable). Pending real-world validation.

Current Anki flow:

```text
plain-text Anki export (.txt only)
→ normalized cards
→ cloze/basic concept extraction
→ tag-first clustering
→ deterministic variant draft preview
→ review controls
→ approved-variant JSON export
→ quiz-object preview
→ controlled save into real tests
```

Current Anki safeguards:

- `.apkg` is intentionally unsupported in Anki v1.
- Anki v1 uses deterministic preview and save logic only. No Gemini is used in the Anki path yet.
- Approved variants only are eligible for export, quiz-object preview, and controlled save.
- The Anki save path requires an explicit Anki subfolder target, a nonempty test name, and an inline review confirmation.
- Anki provenance is preserved separately from quiz-object preview data.
- Anki and UWorld pipelines remain isolated.
- OME and the other source pipelines remain isolated.

## Divine Podcasts Pipeline

Status: Divine v1 deterministic layer complete (tagged `divine-v1-stable`). Divine Gemini refinement via Electron IPC complete (tagged `divine-gemini-v1-stable`). Pending real-world validation.

Current Divine flow:

```text
transcript text import
→ cleaning
→ segmentation
→ concept extraction
→ teaching-cluster construction
→ deterministic draft scaffolds  ← fallback if Gemini unavailable
→ one-at-a-time Electron-local Gemini refinement (nbme:ai:refine-divine-draft)
→ review controls
→ approved-draft JSON export
→ quiz-object preview
→ controlled save into real tests
```

Divine Gemini refinement architecture:

- IPC channel: `nbme:ai:refine-divine-draft` in `electron/main.js`
- Model: `gemini-2.5-flash`
- Input schema (teaching-cluster architecture): `conceptType`, `clusterSummary` (primary medical source, ≤400 chars), `sourceContext` (provenance/copy-detection only, ≤300 chars), `sourceMeta` (requires `draftId` + `clusterId`), `provenance` (arrays: `sourceSegmentIds`, `originalLineRanges`, `cleanedLineRanges`, `timestampRanges`), optional `variantType`
- Gemini responsibility: extract the testable medical fact (`extractedTestableFact`), determine `questionType`, generate clinical vignette stem and five answer choices
- Deterministic layer responsibility: structural validation, provenance construction, anti-copy detection (8-word overlap), podcast-voice rejection, result assembly — nothing from Gemini output is trusted for provenance
- Deterministic draft scaffold is preserved as a fallback if Gemini is unavailable or refinement is declined
- App does not hardcode diagnostic criteria or disease-specific rules; Gemini identifies the medical fact itself
- `generationMethod`: `electron-gemini-divine-cluster-v2`

Current Divine safeguards:

- `clusterSummary` is the sole medical input to Gemini; raw transcript text is not sent
- `sourceContext` is hard-capped at 300 chars and labeled "do not copy" in the prompt
- All provenance (draftId, clusterId, sourceName, sourceHash, provenance arrays) is assembled server-side from sanitized input; Gemini output is never trusted for provenance
- Anti-copy: 8-consecutive-word overlap between Gemini stem/choices and sourceContext causes hard rejection
- Podcast/coaching voice markers (`remember`, `high yield`, `boards`, `you need to know`, `they give you`, etc.) in the stem cause hard rejection
- `extractedTestableFact` ≥10 chars and `questionType` nonempty are required in every valid response
- Approved drafts only are eligible for quiz-object preview and controlled save
- Divine pipeline remains isolated from NBME, UWorld, OME, Anki, and Mehlman pipelines
- No auto-retry, auto-save, or batch queue in the Divine Gemini path (one-at-a-time, same pattern as UWorld)

## Mehlman Notes Pipeline

Status: Mehlman v1 implementation complete (tagged `mehlman-v1-stable`). Pending real-world validation.

The Mehlman pipeline handles structured text notes (not transcripts). It is separate from all other source pipelines. No Gemini is used in the Mehlman v1 path yet.

## Stable Tags and Milestones

The following tags represent verified implementation milestones. Do not silently revert behavior that was part of a tagged milestone without recording the reason.

| Tag | Pipeline | Notes |
|---|---|---|
| `mehlman-v1-stable` | Mehlman | Deterministic notes pipeline complete |
| `divine-v1-stable` | Divine Podcasts | Deterministic draft layer complete |
| `divine-gemini-v1-stable` | Divine Podcasts | Electron IPC Gemini refinement with teaching-cluster schema complete |
| `uworld-gemini-v1-stable` | UWorld | Electron IPC Gemini refinement, JSON extraction hardened |
| `ome-v1-stable` | OME | Cluster index provenance bug fixed, pipeline complete |
| `anki-v1-stable` | Anki | Approval-state and save-path bugs fixed, pipeline complete |

## Current Architecture Philosophy

The app uses a two-layer architecture for AI-assisted question generation:

**Deterministic layer** (renderer + `electron/main.js` sanitization/validation):
- Manages structure, schema, provenance, and integrity
- Constructs all provenance fields server-side from sanitized input
- Enforces anti-copy, anti-podcast-voice, and schema validation gates
- Produces deterministic draft scaffolds that are usable without Gemini

**Gemini layer** (`electron/main.js` prompt + Gemini API):
- Handles clinical reasoning and vignette generation
- Extracts the testable medical fact from teaching clusters (Divine) or refines draft scaffolds (UWorld)
- Receives only sanitized, clamped inputs — never raw transcript text or unclamped renderer data
- Output is validated and normalized by the deterministic layer before use

This split means Gemini does not manage provenance, save targets, or structural decisions. The deterministic layer can stand alone; Gemini refinement is an enhancement, not a dependency.

## Historical Debugging Notes

The following are historical implementation/debugging findings only. They should not be treated as permanent architecture assumptions or active question-number-specific logic:

- Grouped-question rendering previously duplicated shared answer banks when stem crops preserved the original source layout and selectable choices rendered again below.
- Shared answer-bank ordering issues were traced to downstream render/layout selection after parser grouping was already correct.
- Grouped carry-forward debugging showed that a shared group must remain active for the expected item count even if later items repeat only the shared stem or answer bank.
- Dropped-question recovery debugging showed that missing OCR header item numbers should not cause item loss when paragraph-level item numbers are available.
- OCR damage recovery examples included damaged age text, quoted answer choices, and duplicate lab/table fragments extracted from text already present in the patient stem.

## Current Project Direction

The app now has a top-level study library layer above the old subfolder system.

Default library folders:

- NBME
- UWorld
- Anki
- OME
- Divine Podcasts
- Mehlman
- Images and Tables
- Amboss

Existing old folders are migrated under NBME by default. Subfolders should appear only after entering a top-level library folder.

## High-Risk Areas

Use extra caution around:

- `DB.save()` and `storagePayload()`, because they protect localStorage from large image payloads.
- `FigureStore`, because it owns large local images.
- Google Drive backup and restore, because it is the durable cross-device image path.
- OCR parsing and stem crop logic, because previous broad spacing fixes became unstable.
- Avoid broad OCR normalization rules. OCR fixes should be conservative, traceable, and covered by fixtures because broad spacing/token cleanup previously caused instability.
- PDF report generation, because jsPDF layout is sensitive to font state, page breaks, and text normalization.
- Landing/source-folder routing, because it determines which subfolders are visible and where new tests are created.
- UWorld selected-cluster and save-target routing, because it determines which draft candidates are generated and where approved refined drafts are saved.
- Anki controlled-save routing, because it determines which approved variant quiz objects are exported, previewed, and saved into a real test.
- `deno.lock` is currently untracked and should not be touched unless explicitly requested.

## Current Handoff

For detailed current status, use `PROJECT_STATUS_2026-05-08.md`. It supersedes older status files where they conflict.

Architecture as of 2026-05-11: all six source pipelines (NBME, UWorld, OME, Anki, Mehlman, Divine Podcasts) are implemented. UWorld and Divine Gemini refinement run through Electron IPC. The deterministic layer manages provenance and validation for all pipelines. Netlify exists as rollback only.
