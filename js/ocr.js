/* ============================================================
   OCR.JS v2 — Robust NBME PDF extraction engine
   - Uses "Exam Section: Item X of 50" as primary Q anchor
   - Multi-page explanation merging
   - NBME UI noise filtering
   - Correct answer + per-choice explanation parser
   - Educational Objective extraction
   - Auto-tagging
============================================================ */
const OCR = (() => {

  // ── NBME UI Noise patterns to strip ───────────────────────
  const NOISE_PATTERNS = [
    /exam\s+section\s*:\s*item\s+\d+\s+of\s+\d+/gi,
    /national\s+board\s+of\s+medical\s+examiners®?/gi,
    /psychiatry\s+self-?assessment/gi,
    /time\s+remaining\s*:\s*\d+\s*hr?\s*\d+\s*min\s*\d+\s*sec/gi,
    /time\s+remaining\s*:\s*[\d:]+/gi,
    /\d+\s*hr?\s*\d+\s*min\s*\d+\s*sec/gi,
    /https?:\/\/[^\s]+/gi,          // any URL
    /t\.me\/[^\s]+/gi,
    /www\.[^\s]+/gi,
    /^mark$/gim,
    /^previous$/gim,
    /^next$/gim,
    /^pause$/gim,
    /^help$/gim,
    /^review$/gim,
    /^calculator$/gim,
    /^lab\s+values$/gim,
    /^score\s+report$/gim,
    /^please\s+wait$/gim,
    /waiting\s+for\s+www\.[^\s]*/gi,
    /starttest\.com[^\s]*/gi,
    /usmle[^\s]*/gi,
    /nbme[^\s]*/gi,
    /□\s*mark/gi,
    /☐\s*mark/gi,
    /▶|◀|⏸|①|②|③/g,
    /item\s+\d+\s+of\s+\d+/gi,
  ];

  function cleanText(text) {
    let t = text;
    for (const pat of NOISE_PATTERNS) {
      t = t.replace(pat, ' ');
    }
    // Collapse multiple spaces/newlines
    t = t.replace(/[ \t]{2,}/g, ' ');
    t = t.replace(/\n{3,}/g, '\n\n');
    return t.trim();
  }

  // ── PDF → Images ──────────────────────────────────────────
  async function pdfToImages(file, onProgress) {
    const buf = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
    const images = [];
    for (let i = 1; i <= pdf.numPages; i++) {
      const page = await pdf.getPage(i);
      const scale = 2.2;
      const viewport = page.getViewport({ scale });
      const canvas = document.createElement('canvas');
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise;
      images.push({ pageNum: i, dataUrl: canvas.toDataURL('image/png'), total: pdf.numPages });
      if (onProgress) onProgress(i, pdf.numPages);
    }
    return images;
  }

  // ── OCR all pages ─────────────────────────────────────────
  async function ocrAllPages(images, worker, onProgress) {
    const pages = [];
    for (let i = 0; i < images.length; i++) {
      if (onProgress) onProgress(i + 1, images.length);
      const result = await worker.recognize(images[i].dataUrl);
      const rawText = result.data.text;
      const cleaned = cleanText(rawText);
      // Extract item number from NBME header
      const itemMatch = rawText.match(/(?:exam\s+section\s*:\s*)?item\s+(\d+)\s+of\s+(\d+)/i);
      pages.push({
        pageNum: images[i].pageNum,
        text: cleaned,
        rawText,
        itemNum: itemMatch ? parseInt(itemMatch[1]) : null,
        totalItems: itemMatch ? parseInt(itemMatch[2]) : null
      });
    }
    return pages;
  }

  // ── Merge multi-page content ──────────────────────────────
  // Pages with no itemNum header = continuation of previous question
  function mergePagesByItem(pages) {
    const itemPages = {}; // itemNum → array of text blocks

    let lastItemNum = null;
    for (const page of pages) {
      if (page.itemNum !== null) {
        lastItemNum = page.itemNum;
        if (!itemPages[lastItemNum]) itemPages[lastItemNum] = [];
        itemPages[lastItemNum].push(page.text);
      } else if (lastItemNum !== null) {
        // Continuation page — append to last known item
        itemPages[lastItemNum].push(page.text);
      }
    }

    // Merge text blocks per item
    const merged = {};
    for (const [num, blocks] of Object.entries(itemPages)) {
      merged[parseInt(num)] = blocks.join('\n\n');
    }
    return merged;
  }

  // ── Parse Question Bank ───────────────────────────────────
  // Input: merged page map {itemNum → fullText}
  function parseQuestionBank(mergedPages) {
    const questions = [];

    for (const [itemNum, text] of Object.entries(mergedPages)) {
      const q = parseOneQuestion(parseInt(itemNum), text);
      if (q) questions.push(q);
    }

    return questions.sort((a, b) => a.n - b.n);
  }

  function parseOneQuestion(num, text) {
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
    const optPattern = /^([A-Ia-i])\s*[)\.]\s+(.+)/;

    let stemLines = [];
    let options = [];
    let inOptions = false;

    for (const line of lines) {
      // Stop collecting if we hit answer-key-style content
      if (/correct\s+answer/i.test(line)) break;
      if (/incorrect\s+answers?/i.test(line)) break;
      if (/educational\s+objective/i.test(line)) break;

      const optMatch = line.match(optPattern);
      if (optMatch) {
        inOptions = true;
        options.push({ l: optMatch[1].toUpperCase(), t: optMatch[2].trim() });
      } else if (!inOptions) {
        // Part of stem — skip if it looks like a question number label
        if (/^\d+\.\s/.test(line)) {
          stemLines.push(line.replace(/^\d+\.\s*/, '').trim());
        } else {
          stemLines.push(line);
        }
      } else if (options.length > 0 && line.length > 3) {
        // Continuation of last option
        options[options.length - 1].t += ' ' + line;
      }
    }

    if (!options.length) return null;

    // Clean up stem
    const stem = stemLines
      .join(' ')
      .replace(/\s{2,}/g, ' ')
      .replace(/^\d+[.)]\s*/, '')
      .trim();

    if (stem.length < 20) return null; // too short to be a real question

    return {
      n: num,
      t: stem,
      o: options,
      c: '',      // filled from answer key
      e: {},      // per-choice explanations
      correctBlurb: '',
      incorrectSummary: '',
      educationalObjective: '',
      tags: [],
      highlights: {},
      strikethrough: []
    };
  }

  // ── Parse Answer Key ──────────────────────────────────────
  function parseAnswerKey(mergedPages) {
    const answers = {};

    for (const [itemNum, text] of Object.entries(mergedPages)) {
      const parsed = parseOneAnswer(parseInt(itemNum), text);
      if (parsed) answers[parseInt(itemNum)] = parsed;
    }

    return answers;
  }

  function parseOneAnswer(num, text) {
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);

    let correct = null;
    let correctBlurb = '';
    let incorrectSummary = '';
    let educationalObjective = '';
    const choiceExplanations = {}; // letter → explanation text

    // ── Step 1: Find "Correct Answer: X" ──────────────────
    let correctAnswerLineIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      const m = lines[i].match(/correct\s+answer\s*[:\-]\s*([A-Ia-i])/i);
      if (m) {
        correct = m[1].toUpperCase();
        correctAnswerLineIdx = i;
        break;
      }
    }

    if (!correct || correctAnswerLineIdx === -1) {
      // Fallback: look for highlighted answer pattern in options area
      for (const line of lines) {
        const m = line.match(/^([A-Ia-i])\s*[)\.]\s+.{5,}/);
        if (m && lines.join(' ').toLowerCase().includes('correct')) {
          // Can't determine reliably without highlight data
        }
      }
      if (!correct) return null;
    }

    // ── Step 2: Extract explanation block (after "Correct Answer:") ──
    const explanationLines = lines.slice(correctAnswerLineIdx + 1);
    const fullExplanation = explanationLines.join('\n');

    // ── Step 3: Find Educational Objective ────────────────
    const eoMatch = fullExplanation.match(/educational\s+objective\s*[:\-]\s*([\s\S]+?)(?:\n\n|$)/i);
    if (eoMatch) {
      educationalObjective = eoMatch[1].replace(/\n/g, ' ').trim();
    }

    // Remove Educational Objective from main explanation
    const withoutEO = fullExplanation
      .replace(/educational\s+objective\s*[:\-]\s*[\s\S]+?(?:\n\n|$)/gi, '')
      .trim();

    // ── Step 4: Find "Incorrect Answers: A, B, C" summary line ──
    const incorrectSummaryMatch = withoutEO.match(/incorrect\s+answers?\s*[:\-]\s*([A-I,\s\.and]+)/i);
    if (incorrectSummaryMatch) {
      incorrectSummary = 'Incorrect Answers: ' + incorrectSummaryMatch[1].trim().replace(/\.$/, '');
    }

    // ── Step 5: Split before/after "Incorrect Answers:" ──
    const incorrectIdx = withoutEO.search(/incorrect\s+answers?/i);
    let correctSection = incorrectIdx > -1 ? withoutEO.slice(0, incorrectIdx).trim() : withoutEO.trim();
    let incorrectSection = incorrectIdx > -1 ? withoutEO.slice(incorrectIdx).trim() : '';

    // correctBlurb = everything before "Incorrect Answers:"
    correctBlurb = correctSection.replace(/\n/g, ' ').replace(/\s{2,}/g, ' ').trim();

    // ── Step 6: Parse individual incorrect choice explanations ──
    // Pattern: "Buspirone (Choice A) is..." or "Choice A) is..." or "A) ..."
    // Split incorrectSection into paragraphs and attribute each to a letter
    const paragraphs = incorrectSection
      .split(/\n\s*\n/)
      .map(p => p.replace(/\n/g, ' ').replace(/\s{2,}/g, ' ').trim())
      .filter(p => p.length > 10);

    for (const para of paragraphs) {
      // Skip the summary line itself
      if (/^incorrect\s+answers?\s*[:\-]/i.test(para)) continue;
      if (/^educational\s+objective/i.test(para)) continue;

      // Match letter attribution patterns:
      // "Buspirone (Choice A)" | "Choice A)" | "Choice A is" | "(Choice A)"
      const letterMatch =
        para.match(/\(choice\s+([A-Ia-i])\)/i) ||
        para.match(/^choice\s+([A-Ia-i])\s*[)\.:\-]/i) ||
        para.match(/^([A-Ia-i])\s*\)\s+\S/i) ||
        para.match(/\bchoice\s+([A-Ia-i])\b/i);

      if (letterMatch) {
        const letter = letterMatch[1].toUpperCase();
        choiceExplanations[letter] = (choiceExplanations[letter]
          ? choiceExplanations[letter] + ' ' + para
          : para).trim();
      }
    }

    return {
      correct,
      correctBlurb,
      incorrectSummary,
      educationalObjective,
      choiceExplanations
    };
  }

  // ── Match questions to answers ────────────────────────────
  function matchAndMerge(questions, answerMap) {
    return questions.map(q => {
      const ak = answerMap[q.n];
      if (!ak) return { ...q, c: q.o[0]?.l || 'A', _noAnswer: true };

      return {
        ...q,
        c: ak.correct || q.o[0]?.l || 'A',
        e: ak.choiceExplanations || {},
        correctBlurb: ak.correctBlurb || '',
        incorrectSummary: ak.incorrectSummary || '',
        educationalObjective: ak.educationalObjective || '',
        tags: autoTag(q.t, q.o)
      };
    });
  }

  // ── Auto-tagging ──────────────────────────────────────────
  const TAG_RULES = [
    { tag: 'Mood Disorders',           keywords: ['depressive disorder','major depressive','depression','dysthymi','bipolar','manic','hypomania','cyclothymi','adjustment disorder','bereavement','anhedonia'] },
    { tag: 'Psychotic Disorders',      keywords: ['schizophrenia','schizophreniform','schizoaffective','delusional disorder','brief psychotic','psychosis','hallucination','delusion','disorganized speech'] },
    { tag: 'Anxiety Disorders',        keywords: ['anxiety','panic disorder','panic attack','generalized anxiety','social anxiety','phobia','agoraphobia','obsessive','compulsive','PTSD','post-traumatic','acute stress disorder'] },
    { tag: 'Somatic Disorders',        keywords: ['somatic','somatization','hypochondria','illness anxiety','conversion disorder','functional neurologic','factitious','malingering','body dysmorphic'] },
    { tag: 'Substance Use',            keywords: ['alcohol','substance','withdrawal','intoxication','opioid','heroin','cocaine','amphetamine','methamphetamine','benzodiazepine','marijuana','cannabis','PCP','LSD','naltrexone','disulfiram','methadone','buprenorphine'] },
    { tag: 'Personality Disorders',    keywords: ['personality disorder','borderline','antisocial','narcissistic','histrionic','paranoid personality','schizoid','schizotypal','avoidant','dependent'] },
    { tag: 'Neurocognitive Disorders', keywords: ['dementia','delirium','alzheimer','vascular dementia','frontotemporal','lewy body','normal pressure hydrocephalus','cognitive impairment','korsakoff','wernicke'] },
    { tag: 'Pediatric & Developmental',keywords: ['child','adolescent','autism','ADHD','attention deficit','intellectual disability','conduct disorder','oppositional','separation anxiety','fragile X','developmental'] },
    { tag: 'Sleep Disorders',          keywords: ['insomnia','sleep apnea','narcolepsy','polysomnography','REM sleep','nightmare disorder','sleepwalking','parasomnia','circadian'] },
    { tag: 'Sexual Disorders',         keywords: ['sexual dysfunction','erectile','premature ejaculation','vaginismus','vulvodynia','paraphilia','gender dysphoria','libido'] },
    { tag: 'Pharmacology',             keywords: ['SSRI','SNRI','TCA','tricyclic','MAOI','antidepressant','antipsychotic','haloperidol','risperidone','olanzapine','clozapine','quetiapine','aripiprazole','lithium','valproate','carbamazepine','benzodiazepine','lorazepam','diazepam','buspirone','sertraline','fluoxetine','paroxetine','bupropion','mirtazapine','venlafaxine','duloxetine','naltrexone','disulfiram','methylphenidate'] },
    { tag: 'Mechanisms & Neuroscience',keywords: ['dopamine','serotonin','norepinephrine','GABA','glutamate','receptor','reuptake','monoamine','limbic','neurotransmitter','synapse','D2','serotonin syndrome'] },
    { tag: 'Ethics & Legal',           keywords: ['capacity','competence','informed consent','autonomy','confidentiality','tarasoff','duty to warn','involuntary','power of attorney','advance directive','ethics','beneficence','mandatory report','decisional'] },
    { tag: 'Eating Disorders',         keywords: ['anorexia','bulimia','binge eating','purging','laxative','eating disorder'] },
  ];

  function autoTag(questionText, options) {
    const text = (questionText + ' ' + (options||[]).map(o => o.t).join(' ')).toLowerCase();
    const tags = [];
    for (const rule of TAG_RULES) {
      if (rule.keywords.some(kw => text.includes(kw.toLowerCase()))) tags.push(rule.tag);
    }
    return [...new Set(tags)];
  }

  // ── Main pipeline ─────────────────────────────────────────
  async function processTestPDFs(questionFile, answerFile, onProgress) {
    const report = (pct, msg) => onProgress && onProgress(pct, 100, msg);

    // Init Tesseract
    report(2, 'Initializing OCR engine…');
    const worker = await Tesseract.createWorker('eng', 1, {
      logger: () => {} // suppress internal logs
    });

    try {
      // ── OCR Question Bank ──────────────────────────────
      report(5, 'Rendering Question Bank pages…');
      const qImages = await pdfToImages(questionFile, (i, total) => {
        report(5 + Math.round((i/total) * 20), `Rendering Q page ${i}/${total}…`);
      });

      report(26, 'Running OCR on Question Bank…');
      const qPages = await ocrAllPages(qImages, worker, (i, total) => {
        report(26 + Math.round((i/total) * 20), `OCR Q page ${i}/${total}…`);
      });

      // ── OCR Answer Key ────────────────────────────────
      report(47, 'Rendering Answer Key pages…');
      const aImages = await pdfToImages(answerFile, (i, total) => {
        report(47 + Math.round((i/total) * 10), `Rendering AK page ${i}/${total}…`);
      });

      report(58, 'Running OCR on Answer Key…');
      const aPages = await ocrAllPages(aImages, worker, (i, total) => {
        report(58 + Math.round((i/total) * 22), `OCR AK page ${i}/${total}…`);
      });

      // ── Parse ─────────────────────────────────────────
      report(81, 'Merging multi-page content…');
      const qMerged = mergePagesByItem(qPages);
      const aMerged = mergePagesByItem(aPages);

      report(85, 'Parsing questions…');
      const questions = parseQuestionBank(qMerged);

      report(90, 'Parsing answer key…');
      const answerMap = parseAnswerKey(aMerged);

      report(94, 'Matching questions to answers…');
      const matched = matchAndMerge(questions, answerMap);

      report(98, 'Auto-tagging topics…');
      // tags already applied in matchAndMerge

      report(100, `Done! Extracted ${matched.length} questions.`);
      return matched;

    } finally {
      await worker.terminate();
    }
  }

  return { processTestPDFs, autoTag };
})();
window.OCR = OCR;

