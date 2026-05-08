const { callGemini, extractText, getGeminiApiKey, handleError, handleOptions, json, readJsonBody } = require('./_gemini');

exports.handler = async function(event) {
  if (event.httpMethod === 'OPTIONS') return handleOptions();

  if (event.httpMethod === 'GET') {
    return json(200, { configured: !!getGeminiApiKey() });
  }

  if (event.httpMethod !== 'POST') return json(405, { error: 'Method not allowed.' });

  try {
    const body = await readJsonBody(event);
    const prompt = String(body.prompt || '').trim();
    if (!prompt) return json(400, { error: 'Missing prompt.' });

    const data = await callGemini({
      contents: [{ parts: [{ text: prompt.slice(0, 12000) }] }],
      generationConfig: {
        temperature: Number.isFinite(body.temperature) ? body.temperature : 0.2,
        maxOutputTokens: Number.isFinite(body.maxOutputTokens) ? body.maxOutputTokens : 1024,
        thinkingConfig: { thinkingBudget: 0 }
      }
    });

    return json(200, { text: extractText(data) });
  } catch (error) {
    return handleError(error);
  }
};
