const { callGemini, extractText, handleError, handleOptions, json, readJsonBody } = require('./_gemini');

exports.handler = async function(event) {
  if (event.httpMethod === 'OPTIONS') return handleOptions();
  if (event.httpMethod !== 'POST') return json(405, { error: 'Method not allowed.' });

  try {
    const body = await readJsonBody(event);
    const stem = String(body.stem || '').slice(0, 5000);
    const choices = String(body.choices || '').slice(0, 3000);
    const stemImage = body.stemImage && typeof body.stemImage === 'object' ? body.stemImage : null;

    const prompt =
      'You are a medical education tutor helping a student work through a multiple choice question. ' +
      'Read the question stem from the attached image when present. Give one direct, efficient hint that points to the key reasoning step without explicitly giving the answer or naming the correct choice.\n' +
      `Parsed stem fallback: ${stem}\n` +
      `Answer choices: ${choices}\n` +
      'Prefer one sentence. Use two sentences only if needed. No preamble.';

    const parts = [{ text: prompt }];
    if (stemImage?.mimeType && stemImage?.data) {
      parts.push({
        inlineData: {
          mimeType: String(stemImage.mimeType),
          data: String(stemImage.data)
        }
      });
    }

    const data = await callGemini({
      contents: [{ parts }],
      generationConfig: {
        temperature: 0.3,
        maxOutputTokens: 90,
        thinkingConfig: { thinkingBudget: 0 }
      }
    });

    return json(200, { hint: extractText(data) });
  } catch (error) {
    return handleError(error);
  }
};
