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
  const apiKey = ((payload?.apiKey || '').trim()) || process.env.GEMINI_API_KEY || '';
  if (!apiKey) return safeError('NO_API_KEY', 'Gemini API key is not configured. Enter it in Settings.');

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
// Refines a teaching cluster into a Step 2/NBME-style clinical vignette question.
// Gemini identifies the testable medical fact from clusterSummary.
// The app sends cleaned teaching clusters only; Gemini extracts the medical fact itself.
// sourceContext is capped at 300 chars and used only for coherence/copy detection.

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

// Sanitize and clamp all renderer-supplied fields before they enter the prompt.
// Returns null on any structural failure — caller must treat null as invalid input.
function sanitizeDivineDraftInput(payload) {
  if (!payload || typeof payload !== 'object') return null;

  // clusterSummary is the primary medical source — required, trimmed, clamped ≤400 chars.
  const clusterSummary = clampText(payload.clusterSummary, 400);
  if (clusterSummary.length < 20) return null;

  const conceptType = clampText(payload.conceptType, 80);

  // variantType is optional; accepted as-is if present.
  const variantType = (payload.variantType != null) ? clampText(payload.variantType, 60) : null;

  // sourceContext is optional, hard-capped at 300 chars (coherence/copy detection only).
  const sourceContext = clampText(payload.sourceContext, 300);

  // sourceMeta — draftId and clusterId are required for provenance construction.
  const meta = (payload.sourceMeta && typeof payload.sourceMeta === 'object') ? payload.sourceMeta : {};
  const sourceMeta = {
    draftId:    clampText(meta.draftId,    80),
    clusterId:  clampText(meta.clusterId,  80),
    sourceName: clampText(meta.sourceName, 220),
    sourceHash: clampText(meta.sourceHash,  96)
  };
  if (!sourceMeta.draftId || !sourceMeta.clusterId) return null;

  // provenance — build from renderer-supplied fields; none are trusted blindly.
  const prov = (payload.provenance && typeof payload.provenance === 'object') ? payload.provenance : {};
  const tsRaw = prov.timestampRange;
  const provenance = {
    sourceSegmentIds:   normalizeStringArray(prov.sourceSegmentIds, 12),
    originalLineRanges: Array.isArray(prov.originalLineRanges) ? prov.originalLineRanges.slice(0, 12) : [],
    cleanedLineRanges:  Array.isArray(prov.cleanedLineRanges)  ? prov.cleanedLineRanges.slice(0, 12)  : [],
    timestampRanges:    Array.isArray(prov.timestampRanges)    ? prov.timestampRanges.slice(0, 12)    : [],
    timestampRange:     (tsRaw && typeof tsRaw === 'object')
                        ? { start: clampText(tsRaw.start, 20), end: clampText(tsRaw.end, 20) }
                        : null
  };

  return { conceptType, clusterSummary, sourceContext, variantType, sourceMeta, provenance };
}

// Build the Gemini prompt. clusterSummary is the sole medical source.
// Gemini extracts the testable fact itself — no hardcoded diagnostic criteria.
// sourceContext is appended last, labelled "do not copy", for coherence verification only.
function buildDivineRefinementPrompt(input) {
  const lines = [
    'You are a medical education question writer. Generate a Step 2/NBME-style clinical vignette multiple-choice question.',
    'Return strict JSON only. Do not include markdown fences or explanatory text outside JSON.',
    '',
    'CRITICAL RULES — follow exactly:',
    '1. PRIMARY INPUT is the clusterSummary below. First identify the single most testable medical fact it contains.',
    '   Record that fact as extractedTestableFact in your response.',
    '2. Choose the most accurate questionType from this exact list:',
    '   timeline-criterion | diagnostic-distinction | mechanism | management |',
    '   risk-factor | contraindication | clinical-application | other',
    '3. sourceContext is provenance only — do NOT copy, paraphrase, or echo any of its wording into the question.',
    '4. Forbidden podcast/coaching language in stem and choices:',
    '   remember, high yield, boards, you need to know, they give you,',
    '   I think, I want you to, don\'t forget, podcast voice.',
    '5. Write a concise but realistic clinical vignette: patient demographics, presenting symptoms,',
    '   relevant history, labs or imaging if needed, then the question.',
    '6. Generate exactly five answer choices labeled A through E. One best answer only.',
    '7. Choices must be clinically plausible, mutually exclusive, and not lifted from sourceContext.',
    '8. No transcript phrasing reuse. No coaching language. No "all of the above".',
    '9. If source material is insufficient, still produce all five choices, set needsReview true,',
    '   lower confidence, and explain in warnings.',
    '10. This output is preview-only and requires expert review before clinical use.',
    '',
    'Required JSON schema (return exactly this structure):',
    JSON.stringify({
      extractedTestableFact: 'string — the specific medical fact identified as testable',
      questionType: 'timeline-criterion | diagnostic-distinction | mechanism | management | risk-factor | contraindication | clinical-application | other',
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
      confidence: 0.85,
      needsReview: false,
      warnings: []
    }),
    ''
  ];

  if (input.conceptType) lines.push(`Concept type: ${input.conceptType}`);
  if (input.variantType) lines.push(`Variant hint: ${input.variantType}`);

  lines.push(
    '',
    'Teaching cluster (primary medical input — extract the testable fact from this):',
    input.clusterSummary,
    '',
    'Source context — provenance only, do NOT copy or echo any phrasing:',
    input.sourceContext || '(none)'
  );

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

  // 1. extractedTestableFact — Gemini-identified testable fact; must be substantive.
  const extractedTestableFact = clampText(raw.extractedTestableFact, 600).trim();
  if (extractedTestableFact.length < 10) {
    throw new Error(`extractedTestableFact too short (${extractedTestableFact.length} chars, need ≥10)`);
  }

  // 2. questionType — must be nonempty; clamped to 80 chars.
  const questionType = clampText(raw.questionType, 80);
  if (!questionType) throw new Error('questionType is missing or empty');

  // 3. stem — clinical vignette; must be substantive.
  const stem = clampText(raw.stem, 3000);
  if (stem.length < 40) throw new Error(`stem too short (${stem.length} chars, need ≥40)`);

  // 4-5. choices — exactly 5, labels A through E in order.
  const rawChoices = Array.isArray(raw.choices) ? raw.choices : [];
  if (rawChoices.length !== 5) throw new Error(`expected exactly 5 choices, got ${rawChoices.length}`);
  const normalizedChoices = rawChoices.map((choice, idx) => {
    const label = clampText(choice?.label, 2).toUpperCase();
    const text  = clampText(choice?.text, 600);
    if (label !== labels[idx]) throw new Error(`choice label must be ${labels[idx]}, got "${label}"`);
    if (!text) throw new Error(`choice text is empty for label ${labels[idx]}`);
    return { label, text };
  });

  // 6. correctAnswer — must be one of A–E.
  const correctAnswer = clampText(raw.correctAnswer, 2).toUpperCase();
  if (!labels.includes(correctAnswer)) throw new Error('correctAnswer must be A through E');

  // 7. teachingPoint — must be a substantive clinical statement.
  const teachingPoint = clampText(raw.teachingPoint, 1200);
  if (teachingPoint.length < 20) throw new Error(`teachingPoint too short (${teachingPoint.length} chars, need ≥20)`);

  // 8. rationales — all five labels required and nonempty.
  const rawRationales = (raw.rationales && typeof raw.rationales === 'object') ? raw.rationales : {};
  const normalizedRationales = {};
  for (const label of labels) {
    const rationale = clampText(rawRationales[label], 700);
    if (!rationale) throw new Error(`missing rationale for choice ${label}`);
    normalizedRationales[label] = rationale;
  }

  // 9. anti-copy: no 8-word verbatim overlap between sourceContext and stem or any choice.
  const sourceContext = input.sourceContext || '';
  if (divineCopyOverlapDetected(stem, sourceContext)) {
    throw new Error('stem contains verbatim overlap with source context (≥8 consecutive words)');
  }
  for (const { label, text } of normalizedChoices) {
    if (divineCopyOverlapDetected(text, sourceContext)) {
      throw new Error(`choice ${label} contains verbatim overlap with source context (≥8 consecutive words)`);
    }
  }

  // 10. no podcast/coaching voice in the stem.
  for (const marker of DIVINE_STEM_VOICE_MARKERS) {
    if (marker.test(stem)) {
      throw new Error(`stem contains podcast/coaching language matching /${marker.source}/`);
    }
  }

  // 11. warnings — normalise; always append the review sentinel.
  const warnings = normalizeStringArray(raw.warnings, 12);
  if (!warnings.includes('requires review before use')) warnings.push('requires review before use');

  // 12. Assemble result. All provenance comes from sanitized input — never from Gemini output.
  return {
    extractedTestableFact,
    questionType,
    refinedDraftId: `divine-refined-${input.sourceMeta.draftId}-${Date.now().toString(36)}`,
    draftId:        input.sourceMeta.draftId,
    clusterId:      input.sourceMeta.clusterId,
    sourceName:     input.sourceMeta.sourceName,
    sourceHash:     input.sourceMeta.sourceHash,
    provenance:     input.provenance,
    stem,
    choices:        normalizedChoices,
    correctAnswer,
    teachingPoint,
    rationales:     normalizedRationales,
    confidence:     Math.max(0, Math.min(1, Number.isFinite(raw.confidence) ? raw.confidence : 0.35)),
    needsReview:    raw.needsReview !== false || warnings.length > 1,
    warnings,
    model:             GEMINI_MODEL,
    generationMethod:  'electron-gemini-divine-cluster-v2',
    createdAt:         new Date().toISOString()
  };
}

ipcMain.handle('nbme:ai:refine-divine-draft', async (_event, payload) => {
  const apiKey = ((payload?.apiKey || '').trim()) || process.env.GEMINI_API_KEY || '';
  if (!apiKey) return safeError('NO_API_KEY', 'Gemini API key is not configured. Enter it in Settings.');

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

function serveIndexHtml(res, reason) {
  const indexPath = path.join(PROJECT_ROOT, 'index.html');
  console.log('[NBME ROUTE /] Serving index from:', indexPath, reason ? `(reason: ${reason})` : '');
  try {
    const indexHtml = fs.readFileSync(indexPath, 'utf8');
    console.log('[NBME INDEX MARKER PRESENT]', indexHtml.includes('APP_BUILD_MARKER'));
  } catch(e) {
    console.log('[NBME INDEX MARKER PRESENT] error reading file synchronously:', e.message);
  }
  fs.readFile(indexPath, (err, data) => {
    if (err) { res.writeHead(500); res.end(); return; }
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-cache' });
    res.end(data);
  });
}

function createRequestHandler() {
  return function (req, res) {
    console.log('[NBME REQUEST]', req.method, req.url);
    const localPath = resolveLocalPath(req.url);
    if (!localPath) return serveIndexHtml(res, 'bad URL'); // bad URL → SPA fallback

    fs.stat(localPath, (err, stat) => {
      if (err || !stat.isFile()) return serveIndexHtml(res, `not found: ${localPath}`); // not found → SPA fallback

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
