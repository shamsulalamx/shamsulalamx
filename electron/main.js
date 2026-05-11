const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const http = require('http');
const fs = require('fs');

const DEFAULT_DEV_URL = 'http://localhost:8888';
const GEMINI_MODEL = 'gemini-2.5-flash';
const GEMINI_ENDPOINT = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`;
let resolvedDevUrl = null; // set at startup; see startEmbeddedServer / NBME_ELECTRON_URL override

ipcMain.handle('nbme:ai:get-status', async () => ({
  available: true,
  provider: 'gemini',
  model: GEMINI_MODEL,
  hasApiKey: !!process.env.GEMINI_API_KEY,
  desktopMode: true
}));

function safeError(errorCode, message) {
  return { ok: false, errorCode, message };
}

function clampText(value, maxLength) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, maxLength);
}

function normalizeStringArray(value, maxItems = 12) {
  if (!Array.isArray(value)) return [];
  return value.map(v => clampText(v, 160)).filter(Boolean).slice(0, maxItems);
}

function sanitizeDraftInput(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const draft = payload.draft && typeof payload.draft === 'object' ? payload.draft : null;
  const concept = payload.concept && typeof payload.concept === 'object' ? payload.concept : null;
  if (!draft || !concept) return null;

  const sourceBlockIds = normalizeStringArray(draft.sourceBlockIds || concept.sourceBlockIds, 20);
  return {
    draft: {
      draftId: clampText(draft.draftId, 80),
      stem: clampText(draft.stem, 1600),
      choices: Array.isArray(draft.choices) ? draft.choices.slice(0, 5).map(choice => ({
        label: clampText(choice.label || choice.l, 2),
        text: clampText(choice.text || choice.t, 320)
      })) : [],
      correctAnswer: clampText(draft.correctAnswer, 2),
      teachingPoint: clampText(draft.teachingPoint, 700),
      warnings: normalizeStringArray(draft.warnings, 12)
    },
    concept: {
      conceptId: clampText(concept.conceptId || draft.sourceConceptId || draft.conceptId, 80),
      topic: clampText(concept.topic, 220),
      testedFact: clampText(concept.testedFact, 1600),
      sourceSnippet: clampText(concept.sourceSnippet || payload.sourceSnippet, 1200),
      confidence: Number.isFinite(concept.confidence) ? concept.confidence : null,
      warnings: normalizeStringArray(concept.warnings, 12)
    },
    sourceMeta: {
      sourceName: clampText(payload.sourceMeta?.sourceName, 220),
      sourceHash: clampText(payload.sourceMeta?.sourceHash, 96)
    },
    sourceBlockIds
  };
}

function buildRefinementPrompt(input) {
  return [
    'You refine deterministic UWorld notes question scaffolds into Step 2/NBME-style multiple choice question drafts.',
    'Return strict JSON only. Do not include markdown fences or explanatory text outside JSON.',
    'Use only the supplied source note and concept. Do not invent unsupported facts. Do not copy commercial question-bank wording.',
    'If the source is insufficient, still return the JSON schema, set needsReview true, lower confidence, and explain the limitation in warnings.',
    'Produce exactly five answer choices labeled A, B, C, D, and E. Include one correct answer and concise rationales for all choices.',
    'This output is preview-only and requires review before use.',
    '',
    'Required JSON schema:',
    JSON.stringify({
      stem: 'string',
      choices: [
        { label: 'A', text: 'string' },
        { label: 'B', text: 'string' },
        { label: 'C', text: 'string' },
        { label: 'D', text: 'string' },
        { label: 'E', text: 'string' }
      ],
      correctAnswer: 'A',
      teachingPoint: 'string',
      rationales: { A: 'string', B: 'string', C: 'string', D: 'string', E: 'string' },
      confidence: 0.5,
      needsReview: true,
      warnings: ['string']
    }),
    '',
    'Input:',
    JSON.stringify(input)
  ].join('\n');
}

function extractGeminiJson(data) {
  const text = data?.candidates?.[0]?.content?.parts
    ?.map(part => part.text || '')
    .join('')
    .trim();
  if (!text) throw new SyntaxError('empty model response');

  // Attempt 1: strip leading/trailing markdown fences and parse directly.
  const fenceStripped = text
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/i, '')
    .trim();
  try {
    return JSON.parse(fenceStripped);
  } catch (_) {}

  // Attempt 2: locate the first top-level JSON object by brace scanning.
  // Tracks string/escape state so inner braces inside string values are ignored.
  const start = text.indexOf('{');
  if (start !== -1) {
    let depth = 0;
    let inString = false;
    let escape = false;
    for (let i = start; i < text.length; i++) {
      const ch = text[i];
      if (escape) { escape = false; continue; }
      if (ch === '\\' && inString) { escape = true; continue; }
      if (ch === '"') { inString = !inString; continue; }
      if (inString) continue;
      if (ch === '{') depth++;
      else if (ch === '}') {
        depth--;
        if (depth === 0) {
          return JSON.parse(text.slice(start, i + 1));
        }
      }
    }
  }

  throw new SyntaxError('no valid JSON object found in model response');
}

function validateRefinedDraft(raw, input) {
  if (!raw || typeof raw !== 'object') throw new Error('response is not an object');
  const labels = ['A', 'B', 'C', 'D', 'E'];
  const choices = Array.isArray(raw.choices) ? raw.choices : [];
  if (choices.length !== 5) throw new Error('expected exactly five choices');

  const normalizedChoices = choices.map((choice, idx) => {
    const label = clampText(choice?.label, 2).toUpperCase();
    const text = clampText(choice?.text, 600);
    if (label !== labels[idx]) throw new Error('choice labels must be A through E in order');
    if (!text) throw new Error('choice text cannot be empty');
    return { label, text };
  });

  const stem = clampText(raw.stem, 2800);
  const teachingPoint = clampText(raw.teachingPoint, 1000);
  const correctAnswer = clampText(raw.correctAnswer, 2).toUpperCase();
  const rationales = raw.rationales && typeof raw.rationales === 'object' ? raw.rationales : {};
  if (stem.length < 20) throw new Error('stem is too short');
  if (teachingPoint.length < 8) throw new Error('teaching point is too short');
  if (!labels.includes(correctAnswer)) throw new Error('correct answer must be A through E');

  const normalizedRationales = {};
  labels.forEach(label => {
    const rationale = clampText(rationales[label], 700);
    if (!rationale) throw new Error(`missing rationale ${label}`);
    normalizedRationales[label] = rationale;
  });

  const warnings = normalizeStringArray(raw.warnings, 12);
  if (!warnings.includes('requires review before use')) warnings.push('requires review before use');

  return {
    refinedDraftId: `refined-${input.draft.draftId || Date.now().toString(36)}`,
    sourceDraftId: input.draft.draftId,
    sourceConceptId: input.concept.conceptId,
    sourceBlockIds: input.sourceBlockIds.slice(),
    sourceName: input.sourceMeta.sourceName,
    sourceHash: input.sourceMeta.sourceHash,
    stem,
    choices: normalizedChoices,
    correctAnswer,
    teachingPoint,
    rationales: normalizedRationales,
    confidence: Math.max(0, Math.min(1, Number.isFinite(raw.confidence) ? raw.confidence : 0.35)),
    needsReview: raw.needsReview !== false || warnings.length > 0,
    warnings,
    model: GEMINI_MODEL,
    generationMethod: 'electron-gemini-uworld-draft-refinement-v1',
    createdAt: new Date().toISOString()
  };
}

ipcMain.handle('nbme:ai:refine-uworld-draft', async (_event, payload) => {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return safeError('NO_API_KEY', 'Gemini API key is not configured for Electron desktop refinement.');

  const input = sanitizeDraftInput(payload);
  if (!input || !input.draft.draftId || !input.concept.conceptId) {
    return safeError('MODEL_RESPONSE_INVALID', 'Draft refinement input is incomplete.');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const response = await fetch(GEMINI_ENDPOINT, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'x-goog-api-key': apiKey
      },
      body: JSON.stringify({
        contents: [{ role: 'user', parts: [{ text: buildRefinementPrompt(input) }] }],
        generationConfig: {
          responseMimeType: 'application/json',
          temperature: 0.25,
          maxOutputTokens: 2200
        }
      })
    });

    if (response.status === 429) return safeError('RATE_LIMITED', 'Gemini rate limit reached. Try again later.');
    if (!response.ok) return safeError('NETWORK_ERROR', 'Gemini request failed before a valid response was returned.');

    const data = await response.json();

    let parsed;
    try {
      parsed = extractGeminiJson(data);
    } catch (parseErr) {
      return safeError('MODEL_RESPONSE_INVALID', `Gemini response could not be parsed as JSON: ${parseErr.message}`);
    }

    let refinedDraft;
    try {
      refinedDraft = validateRefinedDraft(parsed, input);
    } catch (schemaErr) {
      return safeError('MODEL_RESPONSE_INVALID', `Gemini response failed schema validation: ${schemaErr.message}`);
    }

    return { ok: true, refinedDraft };
  } catch (err) {
    if (err?.name === 'AbortError') return safeError('TIMEOUT', 'Gemini request timed out.');
    if (err instanceof TypeError) return safeError('NETWORK_ERROR', 'Gemini request failed because the network request could not be completed.');
    return safeError('MODEL_RESPONSE_INVALID', 'Gemini response handling failed unexpectedly.');
  } finally {
    clearTimeout(timeout);
  }
});

// ── Divine draft refinement — Gemini IPC ─────────────────────────────────────
// Refines a deterministic Divine draft scaffold from its distilledObjective.
// Uses distilledObjective as the PRIMARY medical input — not raw transcript text.
// sourceContext is capped at 300 chars and used only for coherence/copy detection.

// Allowed variant types — must match DIVINE_DRAFT_VARIANT_MAP in the renderer.
const DIVINE_KNOWN_VARIANT_TYPES = new Set([
  'recognition/application',
  'mechanism/risk-factor',
  'diagnostic-distinction',
  'next-best-step',
  'management-exception',
  'clinical-reasoning-framework'
]);

// Podcast/coaching register patterns that must not appear in Gemini-generated stems.
// Reproduced here (cannot import from renderer) — kept in sync with renderer DIVINE_VOICE_MARKERS.
const DIVINE_STEM_VOICE_MARKERS = [
  /\byou need to\b/i,
  /\bI think\b/i,
  /\bremember\b/i,
  /\bdon'?t forget\b/i,
  /\bhigh[\s-]yield\b/i,
  /\bboards?\b/i,
  /\bpodcast\b/i,
  /\bI want you to\b/i,
  /\bthey give you\b/i
];

// Per-variant guidance injected into the Gemini prompt.
const DIVINE_STEM_TYPE_GUIDANCE = {
  'duration-determines-dx':
    'Write a vignette where the patient\'s symptom duration is the key differentiating detail. ' +
    'The stem must state a duration that matches the criterion. ' +
    'Wrong choices differ from the correct answer primarily by their required duration thresholds.',
  'age-threshold-determines-dx':
    'Write a vignette where the patient\'s age at presentation is the differentiating criterion. ' +
    'Make the patient\'s age central to the stem. Wrong choices apply to different age groups.',
  'next-best-step':
    'Write a clinical vignette ending with "What is the next best step in management?" ' +
    'The correct answer follows directly from the distilledObjective coreRule.',
  'diagnosis-requires-distinction':
    'Write a vignette where two clinically similar conditions are the top candidates. ' +
    'The criterion from distilledObjective is the single differentiating feature.',
  'most-likely-diagnosis':
    'Write a vignette ending with "Which of the following is the most likely diagnosis?" ' +
    'The correct answer is supported directly by the condition and criterion in distilledObjective.',
  'mechanism-explains-finding':
    'Write a vignette presenting a clinical finding that requires mechanistic explanation. ' +
    'The correct answer is the mechanism described in distilledObjective.',
  'contraindication-or-adverse-effect':
    'Write a vignette asking about a contraindication or adverse effect to monitor. ' +
    'The correct answer is directly supported by distilledObjective.',
  'exception-or-caveat':
    'Write a vignette where the key teaching point is an exception to a general clinical rule. ' +
    'distilledObjective defines the exception.',
  'clinical-reasoning-framework':
    'Write a vignette where the correct reasoning framework determines management. ' +
    'distilledObjective defines the framework to apply.',
  default:
    'Write a standard clinical vignette ending with "Which of the following is the most likely diagnosis?" ' +
    'Use only distilledObjective as the medical source.'
};

// Sanitize and clamp all renderer-supplied fields before they enter the prompt.
// Returns null on any structural failure — caller must treat null as invalid input.
function sanitizeDivineDraftInput(payload) {
  if (!payload || typeof payload !== 'object') return null;

  // distilledObjective is the primary medical source — required.
  const obj = payload.distilledObjective;
  if (!obj || typeof obj !== 'object') return null;
  const coreRule = clampText(obj.coreRule, 160);
  if (!coreRule) return null;

  const distilledObjective = {
    coreRule,
    condition:          clampText(obj.condition,          80),
    criterion:          clampText(obj.criterion,         100),
    criterionType:      clampText(obj.criterionType,      40),
    criterionPolarity:  clampText(obj.criterionPolarity,  20),
    suggestedStemType:  clampText(obj.suggestedStemType,  60),
    naturalDistracters: normalizeStringArray(obj.naturalDistracters, 4).map(d => clampText(d, 80))
  };

  // variantType must be a known value; fall back to safest default if unrecognised.
  const rawVariant = clampText(payload.variantType, 60);
  const variantType = DIVINE_KNOWN_VARIANT_TYPES.has(rawVariant)
    ? rawVariant
    : 'recognition/application';

  // sourceMeta — draftId and clusterId are required for provenance construction.
  const meta = (payload.sourceMeta && typeof payload.sourceMeta === 'object') ? payload.sourceMeta : {};
  const sourceMeta = {
    sourceName: clampText(meta.sourceName, 220),
    sourceHash: clampText(meta.sourceHash,  96),
    draftId:    clampText(meta.draftId || payload.draftId,     80),
    clusterId:  clampText(meta.clusterId || payload.clusterId, 80)
  };
  if (!sourceMeta.draftId || !sourceMeta.clusterId) return null;

  // provenance — sourceContext is hard-capped at 300 chars (context/coherence only, not for copying).
  const prov = (payload.provenance && typeof payload.provenance === 'object') ? payload.provenance : {};
  const tsRaw = prov.timestampRange;
  const lrRaw = prov.originalLineRange;
  const provenance = {
    sourceContext:    clampText(prov.sourceContext, 300),
    timestampRange:   (tsRaw && typeof tsRaw === 'object')
                      ? { start: clampText(tsRaw.start, 20), end: clampText(tsRaw.end, 20) }
                      : null,
    originalLineRange: (Array.isArray(lrRaw) && lrRaw.length >= 2)
                      ? [Number(lrRaw[0]) || 0, Number(lrRaw[1]) || 0]
                      : null,
    sourceSegmentIds: normalizeStringArray(prov.sourceSegmentIds, 12)
  };

  return { distilledObjective, variantType, sourceMeta, provenance };
}

// Build the Gemini prompt. distilledObjective is the sole medical source.
// sourceContext is appended last, labelled "do not copy", so Gemini can verify
// coherence without lifting transcript phrasing.
function buildDivineRefinementPrompt(input) {
  const obj      = input.distilledObjective;
  const guidance = DIVINE_STEM_TYPE_GUIDANCE[input.variantType] || DIVINE_STEM_TYPE_GUIDANCE.default;

  const lines = [
    'You refine structured medical learning objectives into Step 2/NBME-style clinical vignette questions.',
    'Return strict JSON only. Do not include markdown fences or explanatory text outside JSON.',
    '',
    'CRITICAL RULES — follow exactly:',
    '1. PRIMARY INPUT is distilledObjective below. Test ONLY the coreRule fact — do not invent other facts.',
    '2. sourceContext is provenance only. Do NOT copy, paraphrase, or echo its wording.',
    '3. Do NOT use podcast or coaching language in the stem: no "remember", "high yield", "boards",',
    '   "you need to know", "they give you", "I think", "I want you to", "don\'t forget".',
    '4. Write a clinical vignette: patient demographics, presenting symptoms, relevant history, then a question.',
    '5. All five answer choices must be clinically plausible and mutually exclusive.',
    '6. If naturalDistracters are provided, use them as seeds for wrong choices — do not copy verbatim.',
    '7. The correct answer must be the ONLY one supported by distilledObjective.coreRule.',
    '8. One best answer only. No "all of the above". No trick stems.',
    '9. If source is insufficient, set needsReview true and explain in warnings. Still produce all five choices.',
    '10. This output is preview-only and requires expert review before use.',
    '',
    `Stem type: ${input.variantType}`,
    `Guidance: ${guidance}`,
    '',
    'Required JSON schema:',
    JSON.stringify({
      stem: 'string (≥40 chars, clinical vignette style, no podcast/coaching voice)',
      choices: [
        { label: 'A', text: 'string' },
        { label: 'B', text: 'string' },
        { label: 'C', text: 'string' },
        { label: 'D', text: 'string' },
        { label: 'E', text: 'string' }
      ],
      correctAnswer: 'A',
      teachingPoint: 'string (≥20 chars, clinical declarative statement)',
      rationales: { A: 'string', B: 'string', C: 'string', D: 'string', E: 'string' },
      confidence: 0.85,
      needsReview: false,
      warnings: ['string']
    }),
    '',
    'Distilled Objective (primary medical input):',
    JSON.stringify(obj),
    '',
    'Source provenance — context only, do NOT copy or echo phrasing:',
    input.provenance.sourceContext || '(none)'
  ];

  return lines.join('\n');
}

// Detect verbatim overlap between Gemini output and the source context.
// Returns true if any 8-consecutive-word sequence from sourceContext appears in text.
// Prevents Gemini from lifting podcast transcript phrasing into the question stem or choices.
function divineCopyOverlapDetected(text, sourceContext) {
  if (!sourceContext || !text) return false;
  const srcWords  = sourceContext.toLowerCase().split(/\s+/).filter(Boolean);
  const testWords = text.toLowerCase().split(/\s+/).filter(Boolean);
  if (srcWords.length < 8 || testWords.length < 8) return false;
  const testStr = testWords.join(' ');
  const WINDOW  = 8;
  for (let i = 0; i <= srcWords.length - WINDOW; i++) {
    const ngram = srcWords.slice(i, i + WINDOW).join(' ');
    if (testStr.includes(ngram)) return true;
  }
  return false;
}

// Validate and normalize Gemini's raw JSON object.
// All provenance fields are constructed from sanitized input — nothing is trusted from Gemini.
// Throws with a specific human-readable message on any failure.
function validateDivineRefinedDraft(raw, input) {
  if (!raw || typeof raw !== 'object') throw new Error('response is not an object');

  const labels = ['A', 'B', 'C', 'D', 'E'];

  // 1. stem — clinical vignette; must be substantive.
  const stem = clampText(raw.stem, 3000);
  if (stem.length < 40) throw new Error(`stem too short (${stem.length} chars, need ≥ 40)`);

  // 2-3. choices — exactly 5, labels A through E in order.
  const rawChoices = Array.isArray(raw.choices) ? raw.choices : [];
  if (rawChoices.length !== 5) throw new Error(`expected exactly 5 choices, got ${rawChoices.length}`);
  const normalizedChoices = rawChoices.map((choice, idx) => {
    const label = clampText(choice?.label, 2).toUpperCase();
    const text  = clampText(choice?.text, 600);
    if (label !== labels[idx]) throw new Error(`choice label must be ${labels[idx]}, got "${label}"`);
    if (!text) throw new Error(`choice text is empty for label ${labels[idx]}`);
    return { label, text };
  });

  // 4. correctAnswer — must be one of A–E.
  const correctAnswer = clampText(raw.correctAnswer, 2).toUpperCase();
  if (!labels.includes(correctAnswer)) throw new Error('correctAnswer must be A through E');

  // 5. teachingPoint — must be a substantive clinical statement.
  const teachingPoint = clampText(raw.teachingPoint, 1200);
  if (teachingPoint.length < 20) throw new Error(`teachingPoint too short (${teachingPoint.length} chars, need ≥ 20)`);

  // 6. rationales — all five labels required and nonempty.
  const rawRationales = (raw.rationales && typeof raw.rationales === 'object') ? raw.rationales : {};
  const normalizedRationales = {};
  for (const label of labels) {
    const rationale = clampText(rawRationales[label], 700);
    if (!rationale) throw new Error(`missing rationale for choice ${label}`);
    normalizedRationales[label] = rationale;
  }

  // 7. anti-copy: no 8-word verbatim overlap between sourceContext and stem or any choice.
  const sourceContext = input.provenance.sourceContext || '';
  if (divineCopyOverlapDetected(stem, sourceContext)) {
    throw new Error('stem contains verbatim overlap with source context (≥8 consecutive words)');
  }
  for (const { label, text } of normalizedChoices) {
    if (divineCopyOverlapDetected(text, sourceContext)) {
      throw new Error(`choice ${label} contains verbatim overlap with source context (≥8 consecutive words)`);
    }
  }

  // 8. no podcast/coaching voice in the stem.
  for (const marker of DIVINE_STEM_VOICE_MARKERS) {
    if (marker.test(stem)) {
      throw new Error(`stem contains podcast/coaching language matching /${marker.source}/`);
    }
  }

  // 9. warnings — normalise; always append the review sentinel.
  const warnings = normalizeStringArray(raw.warnings, 12);
  if (!warnings.includes('requires review before use')) warnings.push('requires review before use');

  // 10. Assemble result. All provenance comes from sanitized input — never from Gemini output.
  return {
    refinedDraftId:       `divine-refined-${input.sourceMeta.draftId}-${Date.now().toString(36)}`,
    deterministicDraftId: input.sourceMeta.draftId,
    clusterId:            input.sourceMeta.clusterId,
    sourceName:           input.sourceMeta.sourceName,
    sourceHash:           input.sourceMeta.sourceHash,
    distilledObjective:   input.distilledObjective,
    provenance:           input.provenance,
    stem,
    choices:              normalizedChoices,
    correctAnswer,
    teachingPoint,
    rationales:           normalizedRationales,
    confidence:           Math.max(0, Math.min(1, Number.isFinite(raw.confidence) ? raw.confidence : 0.35)),
    needsReview:          raw.needsReview !== false || warnings.length > 1,
    warnings,
    model:                GEMINI_MODEL,
    generationMethod:     'electron-gemini-divine-distilled-objective-v1',
    createdAt:            new Date().toISOString()
  };
}

ipcMain.handle('nbme:ai:refine-divine-draft', async (_event, payload) => {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return safeError('NO_API_KEY', 'Gemini API key is not configured for Electron desktop refinement.');

  const input = sanitizeDivineDraftInput(payload);
  if (!input) {
    return safeError('MODEL_RESPONSE_INVALID', 'Divine draft refinement input is incomplete or malformed.');
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const response = await fetch(GEMINI_ENDPOINT, {
      method: 'POST',
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        'x-goog-api-key': apiKey
      },
      body: JSON.stringify({
        contents: [{ role: 'user', parts: [{ text: buildDivineRefinementPrompt(input) }] }],
        generationConfig: {
          responseMimeType: 'application/json',
          temperature: 0.30,
          maxOutputTokens: 2400
        }
      })
    });

    if (response.status === 429) return safeError('RATE_LIMITED', 'Gemini rate limit reached. Try again later.');
    if (!response.ok) return safeError('NETWORK_ERROR', 'Gemini request failed before a valid response was returned.');

    const data = await response.json();

    let parsed;
    try {
      parsed = extractGeminiJson(data);
    } catch (parseErr) {
      return safeError('MODEL_RESPONSE_INVALID', `Gemini response could not be parsed as JSON: ${parseErr.message}`);
    }

    let refinedDraft;
    try {
      refinedDraft = validateDivineRefinedDraft(parsed, input);
    } catch (schemaErr) {
      return safeError('MODEL_RESPONSE_INVALID', `Gemini response failed validation: ${schemaErr.message}`);
    }

    return { ok: true, refinedDraft };
  } catch (err) {
    if (err?.name === 'AbortError') return safeError('TIMEOUT', 'Gemini request timed out.');
    if (err instanceof TypeError) return safeError('NETWORK_ERROR', 'Gemini request failed because the network request could not be completed.');
    return safeError('MODEL_RESPONSE_INVALID', 'Gemini response handling failed unexpectedly.');
  } finally {
    clearTimeout(timeout);
  }
});

// ── Embedded static file server ──────────────────────────────────────────────
// Serves index.html (and local static assets) from the project root over HTTP so
// that Google Drive OAuth, PDF.js workers, and Tesseract workers can all use an
// approved HTTP/HTTPS origin. Binds to 127.0.0.1 only. Not used when
// NBME_ELECTRON_URL is set.

const PROJECT_ROOT = path.resolve(__dirname, '..');

const MIME = {
  '.html':  'text/html; charset=utf-8',
  '.js':    'application/javascript; charset=utf-8',
  '.css':   'text/css; charset=utf-8',
  '.json':  'application/json; charset=utf-8',
  '.png':   'image/png',
  '.jpg':   'image/jpeg',
  '.jpeg':  'image/jpeg',
  '.svg':   'image/svg+xml',
  '.pdf':   'application/pdf',
  '.woff':  'font/woff',
  '.woff2': 'font/woff2',
  '.wasm':  'application/wasm',
  '.txt':   'text/plain; charset=utf-8'
};

function resolveLocalPath(rawUrl) {
  try {
    const clean = decodeURIComponent((rawUrl || '/').split('?')[0].split('#')[0]) || '/';
    const rel = clean.startsWith('/') ? clean : '/' + clean;
    const abs = path.resolve(PROJECT_ROOT, '.' + rel);
    // Reject any path that escapes the project root (path traversal guard).
    if (abs !== PROJECT_ROOT && !abs.startsWith(PROJECT_ROOT + path.sep)) return null;
    return abs;
  } catch (_) {
    return null;
  }
}

function serveIndexHtml(res) {
  fs.readFile(path.join(PROJECT_ROOT, 'index.html'), (err, data) => {
    if (err) { res.writeHead(500); res.end(); return; }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-cache' });
    res.end(data);
  });
}

function createRequestHandler() {
  return function (req, res) {
    const localPath = resolveLocalPath(req.url);
    if (!localPath) return serveIndexHtml(res); // bad URL → SPA fallback

    fs.stat(localPath, (err, stat) => {
      if (err || !stat.isFile()) return serveIndexHtml(res); // not found → SPA fallback

      const ext = path.extname(localPath).toLowerCase();
      const contentType = MIME[ext];
      if (!contentType) { res.writeHead(403); res.end(); return; } // unknown type → deny

      fs.readFile(localPath, (readErr, data) => {
        if (readErr) { res.writeHead(500); res.end(); return; }
        res.writeHead(200, { 'Content-Type': contentType, 'Cache-Control': 'no-cache' });
        res.end(data);
      });
    });
  };
}

function tryListenOnPort(handler, port) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.once('error', () => { server.close(); resolve(null); });
    server.once('listening', () => resolve(server));
    server.listen(port, '127.0.0.1');
  });
}

async function startEmbeddedServer() {
  const handler = createRequestHandler();
  for (const port of [8888, 8080]) {
    const server = await tryListenOnPort(handler, port);
    if (server) return server;
  }
  // Fall back to an OS-assigned port (port 0).
  const server = await tryListenOnPort(handler, 0);
  if (!server) throw new Error('[NBME] Embedded HTTP server failed to bind on any port.');
  return server;
}

let _embeddedServer = null;

// ─────────────────────────────────────────────────────────────────────────────

// Main process boundary:
// Owns Electron window lifecycle and loading the existing HTTP-served app only.
// App logic, parser/OCR/render behavior, Drive, and storage remain in index.html.
// AI status is owned here so future Gemini calls can remain outside the renderer.
function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false
    }
  });

  win.once('ready-to-show', () => {
    win.show();
  });

  win.loadURL(resolvedDevUrl);
}

app.whenReady().then(async () => {
  if (process.env.NBME_ELECTRON_URL) {
    resolvedDevUrl = process.env.NBME_ELECTRON_URL;
    console.log('[NBME] Using external URL override:', resolvedDevUrl);
  } else {
    _embeddedServer = await startEmbeddedServer();
    const { port } = _embeddedServer.address();
    resolvedDevUrl = `http://localhost:${port}`;
    console.log('[NBME] Embedded server listening at:', resolvedDevUrl);
  }

  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (_embeddedServer) {
    _embeddedServer.close();
    _embeddedServer = null;
  }
});
