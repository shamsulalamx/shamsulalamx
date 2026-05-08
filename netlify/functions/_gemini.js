const GEMINI_MODEL = 'gemini-2.0-flash';
const GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models';

function json(statusCode, body) {
  return {
    statusCode,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store'
    },
    body: JSON.stringify(body)
  };
}

function getGeminiApiKey() {
  return (process.env.GEMINI_API_KEY || '').trim();
}

function requireGeminiApiKey() {
  const key = getGeminiApiKey();
  if (!key) {
    const err = new Error('Gemini is not configured. Set GEMINI_API_KEY in Netlify environment variables.');
    err.statusCode = 503;
    throw err;
  }
  return key;
}

async function readJsonBody(event) {
  if (!event.body) return {};
  try {
    return JSON.parse(event.body);
  } catch (_) {
    const err = new Error('Invalid JSON request body.');
    err.statusCode = 400;
    throw err;
  }
}

async function callGemini(requestBody) {
  const key = requireGeminiApiKey();
  const resp = await fetch(`${GEMINI_API_BASE}/${GEMINI_MODEL}:generateContent?key=${encodeURIComponent(key)}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(requestBody)
  });
  const data = await resp.json().catch(() => ({}));
if (!resp.ok) {
  console.error('Gemini API error status:', resp.status);
  console.error('Gemini API error response:', JSON.stringify(data, null, 2));

  const message = data?.error?.message || `Gemini API ${resp.status}`;
  const err = new Error(message);
  err.statusCode = resp.status;
  throw err;
}
  return data;
}
  return data;
}

function extractText(data) {
  return String(data?.candidates?.[0]?.content?.parts?.[0]?.text || '').trim();
}

function handleOptions() {
  return json(204, {});
}

function handleError(error) {
  const statusCode = error.statusCode || 500;
  return json(statusCode, { error: error.message || 'Gemini request failed.' });
}

module.exports = {
  GEMINI_MODEL,
  callGemini,
  extractText,
  getGeminiApiKey,
  handleError,
  handleOptions,
  json,
  readJsonBody
};
