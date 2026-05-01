/* ============================================================
   OCR.JS — Tesseract-based PDF extraction + question parser
   Handles image-based PDFs, fuzzy matching, auto-tagging
============================================================ */
const OCR = (() => {

  // ── PDF → Images using PDF.js ───────────────────────────────
  async function pdfToImages(file, onProgress) {
    const buf = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
    const images = [];
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const scale = 2.0; // higher = better OCR accuracy
      const viewport = page.getViewport({ scale });
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      const ctx = canvas.getContext('2d');
      await page.render({ canvasContext: ctx, viewport }).promise;
      images.push({ pageNum: i, dataUrl: canvas.toDataURL('image/png') });
      if (onProgress) onProgress(i, pdf.numPages, 'Rendering PDF pages');
    }
    return images;
  }

  // ── OCR a single image with Tesseract ──────────────────────
  async function ocrImage(dataUrl, worker) {
    const result = await worker.recognize(dataUrl);
    return result.data.text;
  }

  // ── Full PDF OCR pipeline ───────────────────────────────────
  async function extractTextFromPDF(file, onProgress) {
    if (onProgress) onProgress(0, 100, 'Loading PDF…');
    const images = await pdfToImages(file, (i, total) => {
      if (onProgress) onProgress(Math.round((i/total)*40), 100, `Rendering page ${i}/${total}…`);
    });

    // Init Tesseract worker
    if (onProgress) onProgress(42, 100, 'Initializing OCR engine…');
    const worker = await Tesseract.createWorker('eng', 1, {
      logger: m => {
        if (onProgress && m.status === 'recognizing text') {
          // m.progress is 0-1 per page; we scale to remaining 50%
        }
      }
    });

    const pages = [];
    for (let i = 0; i < images.length; i++) {
      if (onProgress) onProgress(42 + Math.round((i/images.length)*50), 100, `OCR page ${i+1}/${images.length}…`);
      const text = await ocrImage(images[i].dataUrl, worker);
      pages.push({ pageNum: images[i].pageNum, text });
    }

    await worker.terminate();
    if (onProgress) onProgress(95, 100, 'Parsing questions…');
    return pages;
  }

  // ── Parse question bank pages ──────────────────────────────
  function parseQuestionBank(pages) {
    const fullText = pages.map(p => p.text).join('\n\n--- PAGE BREAK ---\n\n');
    const questions = [];

    // Split on question number patterns: "1.", "1)", "Question 1", etc.
    const qPattern = /(?:^|\n)\s*(\d{1,3})[.)]\s+([\s\S]*?)(?=\n\s*\d{1,3}[.)]\s+|\n\s*(?:Question\s+\d)|$)/gi;
    const optPattern = /^\s*([A-Ga-g])[.)]\s+(.+)/;

    let match;
    while ((match = qPattern.exec(fullText)) !== null) {
      const num = parseInt(match[1]);
      const block = match[2].trim();
      const lines = block.split('\n').map(l => l.trim()).filter(Boolean);

      let stemLines = [];
      let options = [];
      let inOptions = false;

      for (const line of lines) {
        const optMatch = line.match(optPattern);
        if (optMatch) {
          inOptions = true;
          options.push({ l: optMatch[1].toUpperCase(), t: optMatch[2].trim() });
        } else if (!inOptions) {
          stemLines.push(line);
        } else if (options.length > 0) {
          // Continuation of previous option
          options[options.length - 1].t += ' ' + line;
        }
      }

      if (options.length >= 2) {
        questions.push({
          n: num,
          t: stemLines.join(' ').replace(/^\d+[.)]\s*/, '').trim(),
          o: options,
          c: '', // filled by answer key
          e: {},
          tags: [],
          highlights: {},
          strikethrough: []
        });
      }
    }

    return questions.sort((a, b) => a.n - b.n);
  }

  // ── Parse answer key pages ─────────────────────────────────
  function parseAnswerKey(pages) {
    const fullText = pages.map(p => p.text).join('\n\n--- PAGE BREAK ---\n\n');
    const answers = {};

    // Pattern: question block with "Correct Answer: X" or highlighted answer
    const qPattern = /(?:^|\n)\s*(\d{1,3})[.)]\s+([\s\S]*?)(?=\n\s*\d{1,3}[.)]\s+|$)/gi;
    const optPattern = /^\s*([A-Ga-g])[.)]\s+(.+)/;
    const correctPattern = /correct\s+answer[:\s]+([A-Ga-g])/i;
    const expPattern = /^\s*([A-Ga-g])[.)]\s*[-–:]\s*(.+)/;

    let match;
    while ((match = qPattern.exec(fullText)) !== null) {
      const num = parseInt(match[1]);
      const block = match[2];
      const lines = block.split('\n').map(l => l.trim()).filter(Boolean);

      let correct = null;
      const explanations = {};
      const options = [];

      // Find explicit "Correct Answer: X"
      const caMatch = block.match(correctPattern);
      if (caMatch) correct = caMatch[1].toUpperCase();

      let inExplanations = false;
      let lastOptLetter = null;

      for (const line of lines) {
        // Skip "Correct Answer: X" lines
        if (/correct\s+answer/i.test(line)) continue;

        const optMatch = line.match(optPattern);
        const expMatch = line.match(expPattern);

        if (optMatch) {
          const letter = optMatch[1].toUpperCase();
          options.push({ l: letter, t: optMatch[2].trim() });
          lastOptLetter = letter;
          inExplanations = true;
        } else if (expMatch && inExplanations) {
          const letter = expMatch[1].toUpperCase();
          explanations[letter] = expMatch[2].trim();
          lastOptLetter = letter;
        } else if (inExplanations && lastOptLetter && line.length > 5) {
          // Continuation of last explanation
          explanations[lastOptLetter] = ((explanations[lastOptLetter] || '') + ' ' + line).trim();
        }
      }

      // Strategy to find correct answer if not explicit
      if (!correct) {
        // S1: Check for "This is correct" / "Correct." in explanations
        for (const [letter, exp] of Object.entries(explanations)) {
          if (/^(correct[.!]|this is (the )?correct|right[.!]|yes[.!])/i.test(exp.trim())) {
            correct = letter; break;
          }
        }
      }
      if (!correct) {
        // S2: Longest explanation heuristic
        let maxLen = -1;
        for (const [letter, exp] of Object.entries(explanations)) {
          if (exp.length > maxLen) { maxLen = exp.length; correct = letter; }
        }
      }
      if (!correct && options.length > 0) correct = options[0].l;

      answers[num] = { correct, explanations };
    }

    return answers;
  }

  // ── Fuzzy string similarity ────────────────────────────────
  function similarity(a, b) {
    a = a.toLowerCase().replace(/\s+/g, ' ').trim().slice(0, 100);
    b = b.toLowerCase().replace(/\s+/g, ' ').trim().slice(0, 100);
    if (a === b) return 1;
    if (a.length === 0 || b.length === 0) return 0;

    // Levenshtein distance
    const m = a.length, n = b.length;
    const dp = Array.from({length: m+1}, (_, i) => Array.from({length: n+1}, (_, j) => i === 0 ? j : j === 0 ? i : 0));
    for (let i = 1; i <= m; i++)
      for (let j = 1; j <= n; j++)
        dp[i][j] = a[i-1] === b[j-1] ? dp[i-1][j-1] : 1 + Math.min(dp[i-1][j], dp[i][j-1], dp[i-1][j-1]);

    return 1 - dp[m][n] / Math.max(m, n);
  }

  // ── Match questions to answers ─────────────────────────────
  function matchQuestionsToAnswers(questions, answerMap) {
    const matched = [];

    for (const q of questions) {
      // Primary: exact number match
      if (answerMap[q.n]) {
        matched.push({ ...q, c: answerMap[q.n].correct || q.o[0].l, e: answerMap[q.n].explanations || {} });
        continue;
      }

      // Fallback: find best matching answer by question stem similarity
      let best = null, bestScore = 0;
      for (const [num, ans] of Object.entries(answerMap)) {
        // We don't have the Q text in answerMap, so skip fuzzy for now
        // Just use the number
      }

      // No match found — use first option as correct placeholder
      matched.push({ ...q, c: q.o[0]?.l || 'A', e: {}, _needsReview: true });
    }

    return matched;
  }

  // ── Auto-tagging ───────────────────────────────────────────
  const TAG_RULES = [
    // Mood Disorders
    { tag: 'Mood Disorders', keywords: ['depressive disorder', 'major depressive', 'depression', 'dysthymi', 'bipolar', 'manic', 'hypomania', 'cyclothymi', 'adjustment disorder', 'bereavement'] },
    // Psychotic Disorders
    { tag: 'Psychotic Disorders', keywords: ['schizophrenia', 'schizophreniform', 'schizoaffective', 'delusional disorder', 'brief psychotic', 'psychosis', 'hallucination', 'delusion', 'disorganized'] },
    // Anxiety Disorders
    { tag: 'Anxiety Disorders', keywords: ['anxiety', 'panic disorder', 'panic attack', 'generalized anxiety', 'social anxiety', 'phobia', 'agoraphobia', 'OCD', 'obsessive', 'compulsive', 'PTSD', 'post-traumatic', 'acute stress'] },
    // Somatic / Functional
    { tag: 'Somatic Disorders', keywords: ['somatic', 'somatization', 'hypochondria', 'illness anxiety', 'conversion disorder', 'functional neurologic', 'factitious', 'malingering', 'body dysmorphic'] },
    // Substance Use
    { tag: 'Substance Use', keywords: ['alcohol', 'substance', 'withdrawal', 'intoxication', 'opioid', 'heroin', 'cocaine', 'amphetamine', 'methamphetamine', 'benzodiazepine', 'marijuana', 'cannabis', 'PCP', 'LSD', 'naltrexone', 'disulfiram', 'methadone', 'buprenorphine'] },
    // Personality Disorders
    { tag: 'Personality Disorders', keywords: ['personality disorder', 'borderline', 'antisocial', 'narcissistic', 'histrionic', 'paranoid personality', 'schizoid', 'schizotypal', 'avoidant', 'dependent', 'obsessive-compulsive personality'] },
    // Neurocognitive
    { tag: 'Neurocognitive Disorders', keywords: ['dementia', 'delirium', 'alzheimer', 'vascular dementia', 'frontotemporal', 'lewy body', 'normal pressure hydrocephalus', 'cognitive impairment', 'memory loss', 'confabulation', 'korsakoff', 'wernicke'] },
    // Pediatric / Developmental
    { tag: 'Pediatric & Developmental', keywords: ['child', 'adolescent', 'autism', 'ADHD', 'attention deficit', 'intellectual disability', 'conduct disorder', 'oppositional', 'separation anxiety', 'enuresis', 'tic', 'Tourette', 'fragile X', 'down syndrome', 'developmental'] },
    // Sleep Disorders
    { tag: 'Sleep Disorders', keywords: ['insomnia', 'sleep apnea', 'narcolepsy', 'polysomnography', 'REM sleep', 'nightmare disorder', 'sleepwalking', 'parasomnia', 'circadian'] },
    // Sexual & Gender
    { tag: 'Sexual Disorders', keywords: ['sexual dysfunction', 'erectile', 'premature ejaculation', 'vaginismus', 'vulvodynia', 'paraphilia', 'gender dysphoria', 'libido'] },
    // Pharmacology
    { tag: 'Pharmacology', keywords: ['SSRI', 'SNRI', 'TCA', 'tricyclic', 'MAOI', 'antidepressant', 'antipsychotic', 'haloperidol', 'risperidone', 'olanzapine', 'clozapine', 'quetiapine', 'aripiprazole', 'lithium', 'valproate', 'carbamazepine', 'benzodiazepine', 'lorazepam', 'diazepam', 'buspirone', 'sertraline', 'fluoxetine', 'paroxetine', 'bupropion', 'mirtazapine', 'venlafaxine', 'duloxetine', 'naltrexone', 'disulfiram', 'methadone', 'methylphenidate', 'amphetamine salts'] },
    // Mechanisms
    { tag: 'Mechanisms & Neuroscience', keywords: ['dopamine', 'serotonin', 'norepinephrine', 'GABA', 'glutamate', 'receptor', 'reuptake', 'monoamine', 'limbic', 'prefrontal', 'neurotransmitter', 'synapse', 'pharmacokinetic'] },
    // Ethics & Legal
    { tag: 'Ethics & Legal', keywords: ['capacity', 'competence', 'informed consent', 'autonomy', 'confidentiality', 'tarasoff', 'duty to warn', 'involuntary', 'power of attorney', 'advance directive', 'ethics', 'beneficence', 'maleficence', 'justice', 'mandatory report'] },
    // Eating Disorders
    { tag: 'Eating Disorders', keywords: ['anorexia', 'bulimia', 'binge eating', 'purging', 'laxative', 'BMI', 'eating disorder', 'amenorrhea secondary to'] },
  ];

  function autoTag(questionText, options) {
    const text = (questionText + ' ' + options.map(o => o.t).join(' ')).toLowerCase();
    const tags = [];
    for (const rule of TAG_RULES) {
      if (rule.keywords.some(kw => text.includes(kw.toLowerCase()))) {
        tags.push(rule.tag);
      }
    }
    return [...new Set(tags)]; // deduplicate
  }

  // ── Main pipeline entry point ──────────────────────────────
  async function processTestPDFs(questionFile, answerFile, onProgress) {
    // Step 1: OCR both PDFs
    onProgress && onProgress(0, 100, 'Reading Question Bank…');
    const qPages = await extractTextFromPDF(questionFile, (p, t, msg) => {
      onProgress && onProgress(Math.round(p * 0.45), 100, msg);
    });

    onProgress && onProgress(45, 100, 'Reading Answer Key…');
    const aPages = await extractTextFromPDF(answerFile, (p, t, msg) => {
      onProgress && onProgress(45 + Math.round(p * 0.45), 100, msg);
    });

    // Step 2: Parse
    onProgress && onProgress(91, 100, 'Parsing questions…');
    const questions = parseQuestionBank(qPages);

    onProgress && onProgress(93, 100, 'Parsing answer key…');
    const answerMap = parseAnswerKey(aPages);

    // Step 3: Match
    onProgress && onProgress(95, 100, 'Matching questions to answers…');
    const matched = matchQuestionsToAnswers(questions, answerMap);

    // Step 4: Auto-tag
    onProgress && onProgress(97, 100, 'Auto-tagging topics…');
    matched.forEach(q => { q.tags = autoTag(q.t, q.o); });

    onProgress && onProgress(100, 100, 'Done!');
    return matched;
  }

  return { processTestPDFs, autoTag, similarity };
})();
window.OCR = OCR;
