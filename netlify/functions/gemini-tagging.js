const { callGemini, extractText, handleError, handleOptions, json, readJsonBody } = require('./_gemini');

exports.handler = async function(event) {
  if (event.httpMethod === 'OPTIONS') return handleOptions();
  if (event.httpMethod !== 'POST') return json(405, { error: 'Method not allowed.' });

  try {
    const body = await readJsonBody(event);
    const questions = Array.isArray(body.questions) ? body.questions : [];
    if (!questions.length) return json(200, { tags: [] });

    const compactQuestions = questions.map(q => ({
      item: Number(q.item),
      stem: String(q.stem || '').slice(0, 1600),
      choices: String(q.choices || '').slice(0, 1200),
      answer: String(q.answer || '').slice(0, 20),
      explanation: String(q.explanation || '').slice(0, 1200)
    }));

    const prompt =
      'Create exactly one hyperspecific USMLE topic tag for each item.\n' +
      'Each tag must name the exact diagnosis, drug, adverse effect, mechanism, management step, or tested association.\n' +
      'Avoid broad labels like Pharmacology, Neurology, Alzheimer disease, or Cardiology.\n' +
      'Good examples: "Alzheimer treatment: cholinesterase inhibitor first line", "Pramipexole adverse effect: impulse control disorder", "Myasthenia gravis: anti-AChR antibody postsynaptic blockade".\n' +
      'Return ONLY valid JSON array in this exact shape: [{"item":1,"tag":"specific tag"}].\n' +
      'Use 6-12 words per tag when possible.\n' +
      JSON.stringify(compactQuestions);

    const data = await callGemini({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: {
        temperature: 0.2,
        maxOutputTokens: Math.max(512, compactQuestions.length * 24),
        thinkingConfig: { thinkingBudget: 0 }
      }
    });

    const raw = extractText(data);
    const match = raw.match(/\[[\s\S]*\]/);
    const parsed = match ? JSON.parse(match[0]) : [];
    const tags = Array.isArray(parsed)
      ? parsed.map(row => ({ item: Number(row.item), tag: String(row.tag || '').trim() })).filter(row => row.item && row.tag)
      : [];
    return json(200, { tags });
  } catch (error) {
    return handleError(error);
  }
};
