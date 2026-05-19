#!/usr/bin/env node
/**
 * backfill-pearls.js
 *
 * One-time script: adds/replaces retrievalTag and reviewPearl on every
 * question in the validated Psych Shelf fixture files.
 *
 * Calls Gemini API directly — no Netlify, no Electron required.
 * Requires: GEMINI_API_KEY in environment.
 *
 * Usage:
 *   node backfill-pearls.js
 *
 * Safe to re-run: only overwrites retrievalTag and reviewPearl.
 * All other fields (stem, choices, correctAnswer, explanations, etc.) untouched.
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const https = require('https');

// ── Config ──────────────────────────────────────────────────────────────────

const GEMINI_MODEL    = 'gemini-2.5-flash';
const GEMINI_ENDPOINT = `https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent`;
const BATCH_SIZE      = 8;    // questions per Gemini call
const DELAY_MS        = 1200; // ms between batches (rate-limit guard)

const FIXTURE_DIR = path.join(__dirname, 'test-data');
const FILES = [
  'Psych_Shelf_3_app_ready.json',
  'Psych_Shelf_4_app_ready.json',
  'Psych_Shelf_5_app_ready.json',
  'Psych_Shelf_6_app_ready.json',
  'Psych_Shelf_7_repaired_app_ready.json',
  'Psych_Shelf_8_full_app_ready.json',
];

// ── Gemini helpers ───────────────────────────────────────────────────────────

function geminiPost(apiKey, body) {
  return new Promise((resolve, reject) => {
    const payload = JSON.stringify(body);
    const url = new URL(GEMINI_ENDPOINT);
    const options = {
      hostname: url.hostname,
      path: url.pathname + url.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(payload),
        'x-goog-api-key': apiKey,
      },
    };
    const req = https.request(options, res => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => {
        if (res.statusCode === 429) return reject(new Error('RATE_LIMITED'));
        if (res.statusCode >= 400) return reject(new Error(`HTTP ${res.statusCode}: ${data.slice(0, 200)}`));
        try { resolve(JSON.parse(data)); }
        catch (e) { reject(new Error('JSON parse failed: ' + data.slice(0, 200))); }
      });
    });
    req.on('error', reject);
    req.setTimeout(45000, () => { req.destroy(); reject(new Error('TIMEOUT')); });
    req.write(payload);
    req.end();
  });
}

function extractText(data) {
  return (data?.candidates?.[0]?.content?.parts || [])
    .map(p => p.text || '').join('').trim();
}

function extractJson(raw) {
  // Try to find a JSON array in the response
  const m = raw.match(/\[[\s\S]*\]/);
  if (!m) throw new Error('No JSON array found in response');
  return JSON.parse(m[0]);
}

// ── Prompt builder ───────────────────────────────────────────────────────────

function buildPrompt(batch) {
  const items = batch.map(q => {
    const choicesText = (q.answerChoices || [])
      .map(c => `${c.label}) ${String(c.text || '').replace(/\s+/g,' ').trim()}`)
      .join('\n');
    const correctOpt = (q.answerChoices || []).find(c => c.label === q.correctAnswer);
    const correctText = correctOpt ? `${q.correctAnswer}) ${correctOpt.text}` : q.correctAnswer;
    const expText = (q.explanationSections || [])
      .flatMap(s => Array.isArray(s.body) ? s.body : [s.body || ''])
      .join(' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 800);
    return {
      item: q.questionNumber,
      stem: String(q.stem || '').replace(/\s+/g,' ').trim().slice(0, 600),
      choices: choicesText.slice(0, 500),
      correct: correctText.slice(0, 120),
      explanation: expText,
    };
  });

  return [
    'You are a Step 2 CK / NBME shelf exam expert generating high-yield study metadata.',
    '',
    'For each item, generate EXACTLY:',
    '  retrievalTag: 3-8 words encoding the SPECIFIC tested concept — not just the diagnosis name.',
    '    Encode thresholds, timelines, drug mechanisms, adverse effects, or classic differentiators.',
    '    Good: "PTSD duration threshold" | "Clozapine ANC monitoring" | "NMS elevated CK" | "Bulimia hypokalemic metabolic alkalosis"',
    '    Avoid: broad labels like "Schizophrenia" or "Antidepressants" alone.',
    '',
    '  reviewPearl: ONE complete, clinically precise sentence for last-minute review.',
    '    Include the key threshold, first-line treatment, classic finding, or distinguishing feature.',
    '    Write as a memory anchor, not a definition.',
    '    Good: "PTSD requires symptoms lasting >1 month after trauma; <1 month is acute stress disorder."',
    '    Good: "Clozapine causes agranulocytosis and requires routine ANC monitoring before each refill."',
    '',
    'Return ONLY a valid JSON array — no markdown, no extra text:',
    '[{"item":1,"retrievalTag":"...","reviewPearl":"..."},...]',
    '',
    'Items:',
    JSON.stringify(items),
  ].join('\n');
}

// ── Sleep ────────────────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Per-file processing ──────────────────────────────────────────────────────

async function processFile(apiKey, filePath) {
  const fileName = path.basename(filePath);
  console.log(`\n── ${fileName} ──`);

  const raw  = fs.readFileSync(filePath, 'utf8');
  const data = JSON.parse(raw);
  const questions = data.questions || [];

  if (!questions.length) {
    console.log('  (no questions — skipping)');
    return;
  }

  // Build lookup for later merge
  const byNum = new Map(questions.map(q => [q.questionNumber, q]));

  // Slice into batches
  const batches = [];
  for (let i = 0; i < questions.length; i += BATCH_SIZE) {
    batches.push(questions.slice(i, i + BATCH_SIZE));
  }

  let generated = 0;
  let failed = 0;

  for (let bi = 0; bi < batches.length; bi++) {
    const batch = batches[bi];
    const nums  = batch.map(q => q.questionNumber).join(',');
    process.stdout.write(`  Batch ${bi+1}/${batches.length} (Q${nums})... `);

    let retries = 2;
    let success = false;

    while (retries >= 0 && !success) {
      try {
        const response = await geminiPost(apiKey, {
          contents: [{ role: 'user', parts: [{ text: buildPrompt(batch) }] }],
          generationConfig: {
            temperature: 0.2,
            maxOutputTokens: BATCH_SIZE * 120,
            thinkingConfig: { thinkingBudget: 0 },
          },
        });

        const text   = extractText(response);
        const parsed = extractJson(text);

        if (!Array.isArray(parsed)) throw new Error('Response is not an array');

        parsed.forEach(row => {
          const q = byNum.get(Number(row.item));
          if (!q) return;
          const rt = String(row.retrievalTag || '').trim();
          const rp = String(row.reviewPearl  || '').trim();
          if (rt) { q.retrievalTag = rt; generated++; }
          if (rp)   q.reviewPearl  = rp;
        });

        console.log('ok');
        success = true;
      } catch (err) {
        if (retries > 0 && err.message === 'RATE_LIMITED') {
          console.log(`rate-limited, waiting 5s...`);
          await sleep(5000);
        } else if (retries > 0) {
          console.log(`error (${err.message.slice(0,60)}), retrying...`);
          await sleep(2000);
        } else {
          console.log(`FAILED (${err.message.slice(0,80)})`);
          failed += batch.length;
        }
        retries--;
      }
    }

    if (bi < batches.length - 1) await sleep(DELAY_MS);
  }

  // Write back
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8');
  console.log(`  Saved. Generated: ${generated} tags, Failed: ${failed} questions.`);
}

// ── Validation report ────────────────────────────────────────────────────────

function validateAll() {
  console.log('\n── Validation ──');
  let allOk = true;
  FILES.forEach(f => {
    const filePath = path.join(FIXTURE_DIR, f);
    const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
    const qs = data.questions || [];
    const missingTag   = qs.filter(q => !q.retrievalTag || !q.retrievalTag.trim());
    const missingPearl = qs.filter(q => !q.reviewPearl  || !q.reviewPearl.trim());
    const ok = missingTag.length === 0 && missingPearl.length === 0;
    if (!ok) allOk = false;
    console.log(
      `  ${f}: ${qs.length} q` +
      (missingTag.length   ? ` | MISSING TAG: Q${missingTag.map(q=>q.questionNumber).join(',')}` : ' | tags ✓') +
      (missingPearl.length ? ` | MISSING PEARL: Q${missingPearl.map(q=>q.questionNumber).join(',')}` : ' | pearls ✓')
    );
  });
  return allOk;
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) {
    console.error('ERROR: GEMINI_API_KEY is not set in environment.');
    console.error('Run with: GEMINI_API_KEY=your-key node backfill-pearls.js');
    process.exit(1);
  }

  console.log(`Backfilling retrievalTag + reviewPearl for ${FILES.length} fixture files`);
  console.log(`Model: ${GEMINI_MODEL} | Batch size: ${BATCH_SIZE} | Delay: ${DELAY_MS}ms`);

  for (const f of FILES) {
    const filePath = path.join(FIXTURE_DIR, f);
    if (!fs.existsSync(filePath)) {
      console.log(`\nSkipping ${f} (file not found)`);
      continue;
    }
    await processFile(apiKey, filePath);
  }

  const allOk = validateAll();
  if (allOk) {
    console.log('\nAll 300 questions have retrievalTag and reviewPearl. Ready to commit.');
  } else {
    console.log('\nSome questions are still missing metadata — re-run to fill gaps.');
    process.exit(1);
  }
}

main().catch(err => {
  console.error('Unexpected error:', err);
  process.exit(1);
});
