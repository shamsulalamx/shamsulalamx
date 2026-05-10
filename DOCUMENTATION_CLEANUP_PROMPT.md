# Documentation Cleanup Prompt

Documentation cleanup only. Do not modify app logic.

Ownership: this prompt governs documentation cleanup tasks only. Durable architecture rules, current project status, and staged Electron roadmap details belong in their dedicated project documents.

## Scope

- Update only relevant documentation/prompt files.
- Do not create new docs unless explicitly requested.
- Do not rename files.
- Do not commit, push, deploy, or modify application code.

## Documentation Governance

- Distinguish active architecture from historical debugging notes.
- Do not frame resolved issues as assumptions or unresolved hypotheses.
- Do not encode historical question numbers as active architecture or future logic.
- Preserve verified stable-state language.
- Keep docs concise, technical, and non-redundant.
- Avoid generic tutorials and broad explanatory filler.
- Do not turn every insight into duplicated text across all docs.
- If exact function/file details are uncertain, state uncertainty instead of inventing details.

## Required Warnings To Preserve

- Gemini API keys must not be exposed client-side.
- Electron-local Gemini must run through Electron main/preload only. `GEMINI_API_KEY` is read from `process.env` only and must not be stored in localStorage, frontend code, Drive backups, debug exports, or packaged assets.
- Supabase is inactive and should not be reintroduced unless explicitly requested.
- Local-only debug tooling should stay hidden/disabled in production unless intentionally exposed.
- Parser debug artifacts may contain copyrighted/private exam content and should remain local/private.
- Drive/Gemini should not be tested from `file://`.
- `.DS_Store` should not be reintroduced or edited intentionally.
- `deno.lock` remains untracked and should not be touched unless explicitly requested.
- Saved/generated quizzes may be stale after parser/render changes and should be regenerated or explicitly reparsed, not silently mutated.

## Stable Architecture Language To Preserve

- Browser app remains stable baseline/fallback until Electron migration proves equivalent behavior.
- Electron migration should wrap the current app first and avoid rewrites initially.
- Future importer architecture should normalize all modalities through adapters into a common intermediate format.
- Future rendering should support text, image, and hybrid render modes with user review/override.
- Historical debugging notes remain historical only.

## Current Feature State To Preserve

- Electron desktop is the long-term primary platform.
- Browser and Netlify remain transitional/rollback layers only.
- UWorld DOCX pipeline exists: DOCX import, normalized blocks, concept extraction, deterministic clustering/deduplication, selected clusters, deterministic draft scaffolds, Electron-local Gemini refinement, review controls, approved JSON export, quiz-object preview, and controlled save into real tests.
- UWorld saves require approved refined drafts, valid quiz-object preview, explicit save target, nonempty inline test name, and inline review confirmation.
- Batch refinement is not implemented. Pending design is selected clusters → deterministic drafts → one-at-a-time queue → cache by draft hash → pause/cancel/retry → review-gated save.
- NBME PDF parser/render/grouped-question pipeline remains isolated from UWorld work.
