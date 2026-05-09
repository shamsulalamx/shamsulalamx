# Grouped Question Debug Prompt

Grouped-question debugging only. Do not generalize historical question numbers into active logic.

## sharedGroup Invariants

Grouped questions must:

- remain separate quiz questions
- remain separate scored items
- retain independent selected-answer state
- retain independent explanations
- retain independent sidebar/navigation entries
- preserve source question numbers separately from displayed indexes
- preserve `sharedGroup` metadata
- preserve grouped ranges and linked question IDs

## Carry-Forward Behavior

Grouped carry-forward should:

- start from explicit grouped language or conservative shared-answer-bank evidence
- keep the active group through the expected item count
- attach shared metadata to each linked item
- not require the trigger sentence to repeat on every linked item
- not overwrite independent patient/question stems

## Shared Choices

- `sharedGroup.sharedChoices` is authoritative when grouped metadata exists.
- Shared answer banks render once.
- Shared choices must not be replaced by stale local `q.o` values.
- Shared choices must remain independently selectable/scored per linked question.

## Rendering Order

Grouped rendering order:

1. shared instruction
2. shared stem
3. individual patient/question stem
4. one selectable answer bank

Structured text may be preferred when crops duplicate answer banks, misorder grouped content, or contain layout contamination.

## Debugging Checklist

- inspect `sharedGroup` metadata
- inspect carry-forward state
- inspect authoritative choice source
- inspect grouped range integrity
- inspect render ordering
- inspect crop/image contamination
- inspect stored-vs-regenerated quiz differences
- verify count/source-number parity

## Stored Quiz Caveat

Previously generated quizzes may remain stale after parser/render fixes.

Do not silently mutate saved quizzes. Prefer regeneration, explicit reparse, or version-aware migration.
