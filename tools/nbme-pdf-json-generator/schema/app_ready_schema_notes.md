# Normalized → App-Ready Field Mapping

How each field in `normalized_question_schema.json` maps into the app's internal
quiz schema (the format stored in localStorage and described in `NBME_JSON_IMPORT.md`).

---

## Direct field mappings

| Normalized field | App field | Notes |
|---|---|---|
| `stem` | `q.t` | Primary stem field used by the quiz renderer. Must be the full untruncated text. |
| `choices` (array of `{label, text}`) | `q.o` (array of `{l, t}`) | Rename `label` → `l`, `text` → `t`. |
| `correctAnswer` | `q.c` | Single letter string. |
| `educationalObjective` | `q.educationalObjective` | Plain text, rendered via `textContent`. |
| `retrievalTag` | `q.retrievalTag` + `q.metadata.retrievalTag` | Stored at both top-level and metadata for lookup compatibility. Also copied to `q.tags[0]` for backward compatibility. |
| `tags` | `q.tags` | Array of strings. `retrievalTag` is always prepended as `tags[0]` if non-empty. |

---

## Composite field mappings

### `correctExplanation` + `incorrectExplanations` + `reviewPearl` → `q.correctBlurb`

`q.correctBlurb` is pre-escaped HTML built by `_ngjBuildCorrectBlurb()`. The mapping is:

1. Wrap `correctExplanation` in `<strong>Correct Answer</strong><br><br>` + body text.
2. Append each `incorrectExplanations` entry as a per-choice block.
3. If `reviewPearl` is non-empty, append a **Clinical Pearl** section.
4. Result is assigned via `innerHTML` (HTML is pre-escaped by the builder).

### `incorrectExplanations` → `q.e`

`q.e` is a letter-keyed map of per-choice explanation strings used by `buildExplanationHTML`:

```json
{
  "A": "Adjustment disorder features...",
  "B": "Bereavement is defined as..."
}
```

Built from `incorrectExplanations` by mapping `label` → letter key, `explanation` → value.

---

## Metadata mappings

| Normalized field | App metadata field | Notes |
|---|---|---|
| `figures` (array) | `q.metadata.figureRefs` | Copied verbatim. Same schema: `{figureId, location, visibleText[]}`. |
| `tables` (array) | `q.metadata.tables` | Copied verbatim. Not auto-rendered inline; preserved for future rendering. |
| `warnings` (array) | `q.metadata.extractionWarnings` | All per-question warnings carried through. |
| `retrievalTag` | `q.metadata.retrievalTag` | Mirrored from top-level. |
| `reviewPearl` | `q.metadata.reviewPearl` | Mirrored from top-level (top-level is read by `getReviewPearl(q)`). |
| `sourceQuestionNumber` | `q.metadata.questionNumber` + `q.n` | `q.n` is the integer used by the quiz renderer. |
| (import timestamp) | `q.metadata.importedAt` | Set at import time, not in normalized output. |
| (schema version) | `q.metadata.schemaVersion` | Set to `"nbme-gemini-json-v2"` at import time. |

---

## Fields not in normalized schema (set at import time)

These are added by the importer (`createTestFromNbmeGeminiJsonImport`) and are not
part of the normalized question object:

| App field | Source |
|---|---|
| `q.metadata.importedAt` | Current timestamp at import |
| `q.metadata.schemaVersion` | Hardcoded `"nbme-gemini-json-v2"` |
| `q.metadata.figureAttachments` | User-uploaded images via the import modal |
| `q.metadata.sourceType` | `"nbme-gemini-json"` |

---

## Figure rendering flow (for reference)

When a question has figures, the stem text contains `[FIGURE: figureId]` markers.
The quiz renderer:

1. Calls `window.buildStemHTML(q.t)` → HTML
2. Calls `window._replaceFigureMarkersInStemHtml(html, q)`
3. For each `[FIGURE: figureId]`, calls `window._ngjFigureToHTML(figureId, q)`:
   - If `q.metadata.figureAttachments[figureId]` → renders `<img src="data:...">`
   - Else if `figureRef.visibleText` is non-empty → renders lab-values table
   - Else → renders placeholder box

The normalized `figures` array feeds `figureRefs` in metadata, and `visibleText`
allows table-style rendering without an image attachment.

---

## Validation at import time

The app importer (`validateNbmeGeminiJsonImport`) enforces:
- `stem` required and non-empty
- `choices` array with ≥ 2 items, each with `label`/`text`
- `correctAnswer` matches one of the choice labels
- Missing `educationalObjective` or `explanationSections` → warning (not blocking)

These match the `required` constraints in `normalized_question_schema.json`, ensuring
a cleanly normalized question will always pass app-side validation.
