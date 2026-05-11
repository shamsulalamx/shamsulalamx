const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');

const DEFAULT_DEV_URL = 'http://localhost:8888';
const GEMINI_MODEL = 'gemini-2.5-flash';
const GEMINI_ENDPOINT = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`;
const devUrl = process.env.NBME_ELECTRON_URL || DEFAULT_DEV_URL;

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

  win.loadURL(devUrl);
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
