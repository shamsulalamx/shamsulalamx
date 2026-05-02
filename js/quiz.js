/* ============================================================
   QUIZ.JS — Test-taking engine
   Handles state, timers, mode switching, navigation
============================================================ */
const Quiz = (() => {

  // ── State ──────────────────────────────────────────────────
  let state = null;
  /*
  state = {
    testId, mode ('tutor'|'exam'), qIdx,
    results: [{answered, correct, chosen, time, highlights, strikethrough}],
    marks: Set of indices,
    totSecs, qSecs, paused,
    totTimerRef, qTimerRef
  }
  */

  // ── Timer helpers ──────────────────────────────────────────
  function startTotalTimer() {
    if (state.totTimerRef) clearInterval(state.totTimerRef);
    const base = Date.now() - state.totSecs * 1000;
    state.totTimerRef = setInterval(() => {
      state.totSecs = Math.floor((Date.now() - base) / 1000);
      renderTotalTimer();
    }, 500);
  }

  function startQTimer() {
    stopQTimer();
    state.qSecs = 0;
    const start = Date.now();
    state.qTimerRef = setInterval(() => {
      state.qSecs = Math.floor((Date.now() - start) / 1000);
      renderQTimer();
    }, 500);
  }

  function stopQTimer() {
    if (state.qTimerRef) { clearInterval(state.qTimerRef); state.qTimerRef = null; }
    return state.qSecs || 0;
  }

  function stopAllTimers() {
    if (state.totTimerRef) { clearInterval(state.totTimerRef); state.totTimerRef = null; }
    stopQTimer();
  }

  function renderTotalTimer() {
    const el = document.getElementById('timer-total');
    if (el) el.textContent = fmtTime(state.totSecs);
  }

  function renderQTimer() {
    const el = document.getElementById('timer-q');
    if (!el) return;
    const s = state.qSecs || 0;
    el.textContent = fmtTime(s);
    el.classList.toggle('timer-warn', s >= 90);
    el.classList.toggle('timer-red', s >= 120);
  }

  function fmtTime(s) {
    const m = Math.floor(s / 60);
    return `${String(m).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`;
  }

  // ── Start / Resume ─────────────────────────────────────────
  function startTest(testId) {
    const test = DB.getTest(testId);
    if (!test) return;

    // Check if there's a saved in-progress attempt
    if (test.status === 'in_progress' && test.currentAttempt) {
      showResumeDialog(testId, test.currentAttempt);
      return;
    }

    initState(testId, test.questions, 'tutor');
  }

  function showResumeDialog(testId, saved) {
    const test = DB.getTest(testId);
    const modal = document.getElementById('modal-resume');
    if (modal) {
      modal.querySelector('.resume-test-name').textContent = test.name;
      modal.querySelector('.resume-q-info').textContent =
        `Question ${saved.qIdx + 1} of ${test.questions.length} · ${fmtTime(saved.totSecs || 0)} elapsed`;
      modal.style.display = 'flex';
      modal.querySelector('.btn-resume').onclick = () => { modal.style.display = 'none'; resumeTest(testId, saved); };
      modal.querySelector('.btn-restart').onclick = () => { modal.style.display = 'none'; initState(testId, test.questions, saved.mode || 'tutor'); };
    } else {
      if (confirm(`Resume from Question ${saved.qIdx + 1}?`)) resumeTest(testId, saved);
      else initState(testId, test.questions, saved.mode || 'tutor');
    }
  }

  function initState(testId, questions, mode) {
    state = {
      testId, mode, qIdx: 0,
      results: questions.map(() => ({ answered: false, correct: false, chosen: null, time: 0, highlights: {}, strikethrough: [] })),
      marks: new Set(),
      totSecs: 0, qSecs: 0,
      totTimerRef: null, qTimerRef: null,
      paused: false
    };
    startTotalTimer();
    renderQuiz();
  }

  function resumeTest(testId, saved) {
    const test = DB.getTest(testId);
    state = {
      testId, mode: saved.mode || 'tutor', qIdx: saved.qIdx || 0,
      results: saved.results || test.questions.map(() => ({ answered: false, correct: false, chosen: null, time: 0, highlights: {}, strikethrough: [] })),
      marks: new Set(saved.marks || []),
      totSecs: saved.totSecs || 0, qSecs: 0,
      totTimerRef: null, qTimerRef: null,
      paused: false
    };
    startTotalTimer();
    renderQuiz();
    window.toast('Test resumed ✓', 2000);
  }

  // ── Persist current state ──────────────────────────────────
  function persistState() {
    if (!state) return;
    DB.saveAttempt(state.testId, {
      mode: state.mode, qIdx: state.qIdx,
      results: state.results,
      marks: [...state.marks],
      totSecs: state.totSecs
    });
  }

  // ── Pause ──────────────────────────────────────────────────
  function pauseTest() {
    if (!state) return;
    stopAllTimers();
    state.paused = true;
    persistState();
    document.getElementById('overlay-pause').style.display = 'flex';
    document.getElementById('pause-info').textContent =
      `Q${state.qIdx + 1} of ${getTest().questions.length} · Score: ${getScore()}/${getAnswered()} · ${fmtTime(state.totSecs)}`;
  }

  function unpauseTest() {
    if (!state) return;
    document.getElementById('overlay-pause').style.display = 'none';
    state.paused = false;
    startTotalTimer();
    if (!state.results[state.qIdx].answered) startQTimer();
    else stopQTimer();
  }

  // ── Answer selection ───────────────────────────────────────
  function selectAnswer(letter) {
    if (!state) return;
    const r = state.results[state.qIdx];
    if (r.answered) return;
    const elapsed = stopQTimer();
    const q = getQuestion();
    const ok = letter === q.c;
    r.answered = true; r.correct = ok; r.chosen = letter; r.time = elapsed;
    persistState();

    if (state.mode === 'tutor') {
      renderOptions(); renderExplanation();
    } else {
      renderOptions(); // show selection + right/wrong in nav
    }
    updateNavPanel();
    renderScoreLive();
  }

  // ── Navigation ─────────────────────────────────────────────
  function goTo(idx) {
    if (!state) return;
    const q_count = getTest().questions.length;
    if (idx < 0 || idx >= q_count) return;
    // Save time for current if unanswered
    if (!state.results[state.qIdx].answered) {
      state.results[state.qIdx].time = state.qSecs;
    }
    stopQTimer();
    state.qIdx = idx;
    renderQuestion();
    persistState();
  }

  function nextQ() { goTo(state.qIdx + 1); }
  function prevQ() { goTo(state.qIdx - 1); }

  // ── Mode toggle ────────────────────────────────────────────
  function setMode(newMode) {
    if (!state || state.mode === newMode) return;
    state.mode = newMode;
    // If switching Exam→Tutor and current Q is answered → show explanation
    // If switching Tutor→Exam → hide explanations (renderExplanation handles this)
    renderQuestion();
    persistState();
  }

  // ── Finish test ────────────────────────────────────────────
  function finishTest() {
    if (!state) return;
    stopAllTimers();
    const entry = DB.finishAttempt(state.testId, state.results, state.totSecs, state.mode);
    window.Results && window.Results.show(state.testId, entry, state.results, getTest().questions);
    state = null;
  }

  // ── Flag / Mark ────────────────────────────────────────────
  function toggleFlag(qIdx) {
    if (!state) return;
    const q = getTest().questions[qIdx];
    if (DB.isFlagged(state.testId, q.n)) DB.removeFlag(state.testId, q.n);
    else DB.addFlag(state.testId, q.n);
    updateNavPanel();
    renderFlagButton();
  }

  function toggleMark(qIdx) {
    if (!state) return;
    if (state.marks.has(qIdx)) state.marks.delete(qIdx);
    else state.marks.add(qIdx);
    updateNavPanel();
    persistState();
  }

  // ── Strikethrough ──────────────────────────────────────────
  function toggleStrike(qIdx, letter) {
    if (!state) return;
    const st = state.results[qIdx].strikethrough;
    const i = st.indexOf(letter);
    if (i >= 0) st.splice(i, 1); else st.push(letter);
    persistState();
    renderOptions();
  }

  // ── Highlight ──────────────────────────────────────────────
  function saveHighlight(qIdx, htmlContent) {
    if (!state) return;
    state.results[qIdx].highlights = { html: htmlContent };
    persistState();
  }

  // ── Helpers ────────────────────────────────────────────────
  function getTest()     { return DB.getTest(state.testId); }
  function getQuestion() { return getTest().questions[state.qIdx]; }
  function getScore()    { return state.results.filter(r => r.correct).length; }
  function getAnswered() { return state.results.filter(r => r.answered).length; }

  // ── Render: full question screen ───────────────────────────
  function renderQuiz() {
    const screen = document.getElementById('screen-quiz');
    if (!screen) return;
    screen.style.display = 'flex';
    document.getElementById('screen-home').style.display = 'none';
    document.getElementById('screen-results') && (document.getElementById('screen-results').style.display = 'none');

    updateTestHeader();
    renderQuestion();
    updateNavPanel();
    startQTimer();
  }

  function renderQuestion() {
    const q = getQuestion();
    const r = state.results[state.qIdx];
    const test = getTest();

    // Header info
    document.getElementById('quiz-test-name').textContent = test.name;
    document.getElementById('quiz-q-num').textContent = `Item ${state.qIdx + 1} of ${test.questions.length}`;

    // Stem
    const stemEl = document.getElementById('q-stem');
    if (r.highlights && r.highlights.html) {
      stemEl.innerHTML = r.highlights.html;
    } else {
      stemEl.textContent = q.t;
    }

    // Tags
    const tagEl = document.getElementById('q-tags');
    if (tagEl && q.tags && q.tags.length) {
      tagEl.innerHTML = q.tags.map(t => `<span class="q-tag">${t}</span>`).join('');
      tagEl.style.display = 'flex';
    } else if (tagEl) {
      tagEl.style.display = 'none';
    }

    renderOptions();
    renderExplanation();
    renderFlagButton();
    updateModeToggle();

    // Restart Q timer only if unanswered
    if (!r.answered) {
      startQTimer();
    } else {
      stopQTimer();
      renderQTimer();
    }

    // Prev/Next buttons
    const prevBtn = document.getElementById('btn-prev');
    const nextBtn = document.getElementById('btn-next');
    const finBtn  = document.getElementById('btn-finish');
    if (prevBtn) prevBtn.disabled = state.qIdx === 0;
    if (nextBtn) nextBtn.style.display = state.qIdx < test.questions.length - 1 ? 'inline-flex' : 'none';
    if (finBtn)  finBtn.style.display  = state.qIdx === test.questions.length - 1 ? 'inline-flex' : 'none';

    renderScoreLive();
  }

  function renderOptions() {
    if (!state) return;
    const q = getQuestion();
    const r = state.results[state.qIdx];
    const container = document.getElementById('options-list');
    if (!container) return;
    container.innerHTML = '';

    q.o.forEach(opt => {
      const isChosen  = r.chosen === opt.l;
      const isCorrect = q.c === opt.l;
      const isStriken = r.strikethrough.includes(opt.l);

      const div = document.createElement('div');
      div.className = 'opt-row';
      div.dataset.letter = opt.l;

      // State classes
      if (r.answered) {
        if (isCorrect)         div.classList.add('opt-correct');
        else if (isChosen)     div.classList.add('opt-wrong');
      } else if (isChosen)     div.classList.add('opt-selected');
      if (isStriken)           div.classList.add('opt-striken');

      div.innerHTML = `
        <div class="opt-selector" data-letter="${opt.l}">
          <div class="opt-radio">${isChosen || (r.answered && isCorrect) ? '<div class="opt-radio-dot"></div>' : ''}</div>
          <span class="opt-letter">${opt.l})</span>
        </div>
        <div class="opt-text" data-letter="${opt.l}">${opt.t}</div>
        <div class="opt-indicator">
          ${r.answered && isCorrect ? '<span class="ind-correct">✓</span>' : ''}
          ${r.answered && isChosen && !isCorrect ? '<span class="ind-wrong">✗</span>' : ''}
        </div>`;

      // Click selector (radio + letter) → select answer
      div.querySelector('.opt-selector').addEventListener('click', () => {
        if (!r.answered) selectAnswer(opt.l);
      });

      // Right-click or click text body → strikethrough
      div.querySelector('.opt-text').addEventListener('click', e => {
        e.preventDefault();
        toggleStrike(state.qIdx, opt.l);
      });
      div.querySelector('.opt-text').addEventListener('contextmenu', e => {
        e.preventDefault();
        toggleStrike(state.qIdx, opt.l);
      });

      container.appendChild(div);
    });
  }

  function renderExplanation() {
    if (!state) return;
    const panel = document.getElementById('exp-panel');
    if (!panel) return;
    const q = getQuestion();
    const r = state.results[state.qIdx];
    const showExp = state.mode === 'tutor' && r.answered;
    panel.style.display = showExp ? 'block' : 'none';
    if (!showExp) return;
    buildExplanationHTML(q, r, document.getElementById('exp-body'));
  }

  function buildExplanationHTML(q, r, container) {
    container.innerHTML = '';

    // Correct answer block
    const correctOpt = q.o ? q.o.find(o => o.l === q.c) : null;
    const chosenCorrect = r && r.chosen === q.c;
    const correctDiv = document.createElement('div');
    correctDiv.className = 'exp-item exp-correct';
    correctDiv.innerHTML =
      '<div class="exp-header">' +
        '<strong>' + q.c + ') ' + (correctOpt ? correctOpt.t : '') + '</strong>' +
        '<span class="exp-badge-correct">&#10003; Correct Answer</span>' +
        (chosenCorrect ? '<span class="exp-badge-chosen">&#8592; Your Answer</span>' : '') +
      '</div>' +
      (q.correctBlurb ? '<div class="exp-text exp-blurb">' + q.correctBlurb + '</div>' : '');
    container.appendChild(correctDiv);

    // Incorrect summary line
    if (q.incorrectSummary) {
      const sumDiv = document.createElement('div');
      sumDiv.className = 'exp-incorrect-summary';
      sumDiv.textContent = q.incorrectSummary;
      container.appendChild(sumDiv);
    }

    // Per-choice wrong answer explanations
    if (q.o) {
      q.o.forEach(function(opt) {
        if (opt.l === q.c) return;
        const chosen  = r && r.chosen === opt.l;
        const expText = (q.e && q.e[opt.l]) ? q.e[opt.l] : '';
        const div = document.createElement('div');
        div.className = 'exp-item' + (chosen ? ' exp-wrong-chosen' : ' exp-wrong');
        div.innerHTML =
          '<div class="exp-header">' +
            '<strong>' + opt.l + ') ' + opt.t + '</strong>' +
            (chosen ? '<span class="exp-badge-wrong">&#10007; Your Answer</span>' : '') +
          '</div>' +
          (expText ? '<div class="exp-text">' + expText + '</div>' : '<div class="exp-text exp-no-exp">No explanation available.</div>');
        container.appendChild(div);
      });
    }

    // Educational Objective at the bottom
    if (q.educationalObjective) {
      const eoDiv = document.createElement('div');
      eoDiv.className = 'exp-educational-objective';
      eoDiv.innerHTML = '<strong>Educational Objective:</strong> ' + q.educationalObjective;
      container.appendChild(eoDiv);
    }
  }

  function renderFlagButton() {
    if (!state) return;
    const btn = document.getElementById('btn-flag');
    if (!btn) return;
    const q = getQuestion();
    const flagged = DB.isFlagged(state.testId, q.n);
    btn.classList.toggle('flagged', flagged);
    btn.title = flagged ? 'Remove flag' : 'Flag for review';
    btn.textContent = flagged ? '🚩 Flagged' : '🏳 Flag';
  }

  function updateNavPanel() {
    if (!state) return;
    const panel = document.getElementById('nav-panel');
    if (!panel) return;
    const test = getTest();
    panel.innerHTML = '';
    test.questions.forEach((q, i) => {
      const r = state.results[i];
      const div = document.createElement('div');
      div.className = 'nav-dot';
      div.textContent = i + 1;
      div.title = `Q${i+1}`;
      if (i === state.qIdx) div.classList.add('nav-current');
      if (r.answered) {
        div.classList.add(r.correct ? 'nav-correct' : 'nav-wrong');
      }
      if (state.marks.has(i)) div.classList.add('nav-marked');
      if (DB.isFlagged(state.testId, q.n)) div.classList.add('nav-flagged');
      div.addEventListener('click', () => goTo(i));
      panel.appendChild(div);
    });
  }

  function renderScoreLive() {
    const el = document.getElementById('score-live');
    if (!el || !state) return;
    const ans = getAnswered(), sc = getScore();
    const pct = ans > 0 ? Math.round(sc/ans*100) : 0;
    el.textContent = `${sc}/${ans} (${pct}%)`;
  }

  function updateTestHeader() {
    const test = getTest();
    const el = document.getElementById('quiz-test-name');
    if (el) el.textContent = test.name;
  }

  function updateModeToggle() {
    const btn = document.getElementById('btn-mode-toggle');
    if (!btn || !state) return;
    btn.textContent = state.mode === 'tutor' ? '📖 Tutor' : '📝 Exam';
    btn.classList.toggle('mode-exam', state.mode === 'exam');
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    startTest, pauseTest, unpauseTest, finishTest,
    goTo, nextQ, prevQ, setMode,
    toggleFlag, toggleMark, toggleStrike, saveHighlight,
    renderQuestion, renderOptions, renderExplanation,
    updateNavPanel, renderScoreLive,
    getState: () => state,
    getScore, getAnswered, fmtTime
  };
})();
window.Quiz = Quiz;
// Expose explanation builder globally for use by Results review screen
window.buildExplanationHTML = function(q, r, container) {
  // Reconstruct inline since it's in Quiz closure
  container.innerHTML = '';
  var correctOpt = q.o ? q.o.find(function(o){return o.l===q.c;}) : null;
  var chosenCorrect = r && r.chosen === q.c;
  var correctDiv = document.createElement('div');
  correctDiv.className = 'exp-item exp-correct';
  correctDiv.innerHTML =
    '<div class="exp-header">' +
      '<strong>' + q.c + ') ' + (correctOpt ? correctOpt.t : '') + '</strong>' +
      '<span class="exp-badge-correct">&#10003; Correct Answer</span>' +
      (chosenCorrect ? '<span class="exp-badge-chosen">&#8592; Your Answer</span>' : '') +
    '</div>' +
    (q.correctBlurb ? '<div class="exp-text exp-blurb">' + q.correctBlurb + '</div>' : '');
  container.appendChild(correctDiv);

  if (q.incorrectSummary) {
    var sumDiv = document.createElement('div');
    sumDiv.className = 'exp-incorrect-summary';
    sumDiv.textContent = q.incorrectSummary;
    container.appendChild(sumDiv);
  }

  if (q.o) {
    q.o.forEach(function(opt) {
      if (opt.l === q.c) return;
      var chosen  = r && r.chosen === opt.l;
      var expText = (q.e && q.e[opt.l]) ? q.e[opt.l] : '';
      var div = document.createElement('div');
      div.className = 'exp-item' + (chosen ? ' exp-wrong-chosen' : ' exp-wrong');
      div.innerHTML =
        '<div class="exp-header">' +
          '<strong>' + opt.l + ') ' + opt.t + '</strong>' +
          (chosen ? '<span class="exp-badge-wrong">&#10007; Your Answer</span>' : '') +
        '</div>' +
        (expText ? '<div class="exp-text">' + expText + '</div>' :
          '<div class="exp-text exp-no-exp">No explanation available.</div>');
      container.appendChild(div);
    });
  }

  if (q.educationalObjective) {
    var eoDiv = document.createElement('div');
    eoDiv.className = 'exp-educational-objective';
    eoDiv.innerHTML = '<strong>Educational Objective:</strong> ' + q.educationalObjective;
    container.appendChild(eoDiv);
  }
};

