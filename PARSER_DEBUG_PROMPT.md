# Parser Debug Prompt

Parser/debugging workflow only. Prefer the smallest safe correction point.

Do not commit, push, deploy, or silently mutate saved quizzes unless explicitly approved.

## Layer Separation

Keep these concerns separate:

- OCR repair
- normalization
- semantic parsing
- rendering
- persistence

Do not mix fixes across layers unless evidence shows the boundary is wrong.

## Integrity Checks

Verify count and numbering integrity at each stage:

- raw OCR item count
- normalized item count
- parsed question count
- post-merge count
- final rendered count
- expected source count parity
- missing source numbers
- duplicate source numbers
- duplicate final/displayed numbers
- grouped range integrity

## Diagnostics To Preserve

- parser debug exports
- focused item exports
- `parseSkippedItems` diagnostics
- source-number audits
- grouped range audits
- final rendered array audits
- fixture runs
- syntax checks

Parser debug artifacts may contain copyrighted/private exam content and should remain local/private.

## Correction Rules

- Prefer conservative OCR normalization.
- Avoid broad spacing/token cleanup.
- Avoid destructive regex replacements.
- Every OCR cleanup should be traceable.
- Parser changes should be fixture-backed when possible.
- Avoid broad parser rewrites when a narrow normalization or parsing correction is sufficient.
- Identify the earliest safe correction point and the smallest safe correction point.

## Stored Quiz Caveat

Saved/generated quizzes may be stale after parser/render changes.

Do not silently mutate stored quizzes. Prefer:

- regeneration
- explicit reparse
- version-aware migration
