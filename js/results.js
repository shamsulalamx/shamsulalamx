/* ============================================================
   RESULTS.JS — Score report, analytics, review mode
============================================================ */
const Results = (() => {

  let _testId = null;
  let _entry  = null;
  let _results = null;
  let _questions = null;
  let _reviewIdx = 0;
  let _inReview  = false;

  function show(testId, entry, results, questions) {
    _testId = testId; _entry = entry; _results = results; _questions = questions;
    _inReview = false;
    document.getElementById('screen-quiz').style.display    = 'none';
    document.getElementById('screen-home').style.display    = 'none';
    const s = document.getElementById('screen-results');
    s.style.display = 'flex';
    buildReport();
  }

  function buildReport() {
    const total   = _questions.length;
    const score   = _entry.score;
    const pct     = Math.round(score / total * 100);
    const skipped = _results.filter(r => r.chosen === null).length;
    const wrong   = _results.filter(r => r.answered && !r.correct).length;
    const avgTime = Math.round(_results.reduce((a,r) => a + r.time, 0) / total);
    const test    = DB.getTest(_testId);

    // Header
    document.getElementById('res-test-name').textContent = test.name;
    document.getElementById('res-attempt').textContent =
      `Attempt ${_entry.attemptNum} · ${new Date(_entry.date).toLocaleString()} · ${Quiz.fmtTime(_entry.totSecs)}`;
    document.getElementById('res-score-num').textContent  = score;
    document.getElementById('res-score-den').textContent  = `/ ${total}`;
    document.getElementById('res-score-pct').textContent  = `${pct}%`;
    document.getElementById('res-score-pct').style.color  = pct>=80?'#27ae60':pct>=70?'#2980b9':pct>=60?'#f0a500':'#e74c3c';
    document.getElementById('res-grade').textContent      = grade(pct);
    document.getElementById('res-grade-desc').textContent = gradeDesc(pct);

    // Stats grid
    document.getElementById('res-stats').innerHTML = [
      {v:`${pct}%`,         l:'Accuracy'},
      {v:Quiz.fmtTime(_entry.totSecs), l:'Total Time'},
      {v:`${avgTime}s`,     l:'Avg / Question'},
      {v:score,             l:'Correct'},
      {v:wrong,             l:'Incorrect'},
      {v:skipped,           l:'Skipped'}
    ].map(s => `<div class="res-stat"><span class="res-stat-val">${s.v}</span><span class="res-stat-lbl">${s.l}</span></div>`).join('');

    // Topic breakdown
    buildTopicAnalysis();

    // Navigation dots
    buildNavDots();

    // Review table
    buildReviewTable();
  }

  function buildTopicAnalysis() {
    const tagStats = {};
    _questions.forEach((q, i) => {
      const r = _results[i];
      (q.tags || []).forEach(tag => {
        if (!tagStats[tag]) tagStats[tag] = { correct: 0, total: 0 };
        tagStats[tag].total++;
        if (r.correct) tagStats[tag].correct++;
      });
    });

    const sorted = Object.entries(tagStats)
      .map(([tag, s]) => ({ tag, pct: Math.round(s.correct/s.total*100), correct: s.correct, total: s.total }))
      .sort((a,b) => a.pct - b.pct);

    const strengths = sorted.filter(s => s.pct >= 70).reverse().slice(0, 5);
    const weaknesses = sorted.filter(s => s.pct < 70).slice(0, 5);

    document.getElementById('res-strengths').innerHTML =
      strengths.length ? strengths.map(s =>
        `<div class="topic-row"><span class="topic-name">${s.tag}</span><span class="topic-pct good">${s.pct}% (${s.correct}/${s.total})</span></div>`
      ).join('') : '<div class="topic-empty">No data yet</div>';

    document.getElementById('res-weaknesses').innerHTML =
      weaknesses.length ? weaknesses.map(s =>
        `<div class="topic-row"><span class="topic-name">${s.tag}</span><span class="topic-pct bad">${s.pct}% (${s.correct}/${s.total})</span></div>`
      ).join('') : '<div class="topic-empty">No weaknesses identified 🎉</div>';
  }

  function buildNavDots() {
    const nav = document.getElementById('res-nav-dots');
    if (!nav) return;
    nav.innerHTML = '';
    _questions.forEach((q, i) => {
      const r = _results[i];
      const d = document.createElement('div');
      d.className = 'res-dot ' + (r.chosen===null ? '' : r.correct ? 'dot-c' : 'dot-w');
      d.textContent = i + 1;
      d.title = `Q${i+1}: ${r.correct ? '✓ Correct' : r.chosen ? '✗ Wrong' : 'Skipped'}`;
      d.addEventListener('click', () => openReview(i));
      nav.appendChild(d);
    });
  }

  function buildReviewTable() {
    const tbody = document.getElementById('res-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    _questions.forEach((q, i) => {
      const r = _results[i];
      const tr = document.createElement('tr');
      tr.className = r.chosen===null ? '' : r.correct ? 'tr-c' : 'tr-w';
      tr.id = `res-row-${i}`;
      const tag = r.chosen===null
        ? '<span class="tag-skip">SKIP</span>'
        : r.correct ? '<span class="tag-ok">✓</span>' : '<span class="tag-bad">✗</span>';
      const chosen = r.chosen ? `${r.chosen}) ${q.o.find(o=>o.l===r.chosen)?.t?.slice(0,40)||''}…` : '—';
      const correct = `${q.c}) ${q.o.find(o=>o.l===q.c)?.t?.slice(0,40)||''}…`;
      const flagBtn = `<button class="btn-flag-review ${DB.isFlagged(_testId,q.n)?'flagged':''}"
        onclick="toggleFlagReview(${i})" title="Flag for review">🏳</button>`;
      tr.innerHTML = `
        <td>${i+1}</td>
        <td>${tag}</td>
        <td class="td-text">${chosen}</td>
        <td class="td-text">${correct}</td>
        <td class="td-time">${r.time}s</td>
        <td>${flagBtn}</td>
        <td><button class="btn-review-item" onclick="openReview(${i})">Review</button></td>`;
      tbody.appendChild(tr);
    });
  }

  // ── Review mode ────────────────────────────────────────────
  function openReview(idx) {
    _reviewIdx = idx;
    _inReview = true;
    document.getElementById('panel-report').style.display    = 'none';
    document.getElementById('panel-review').style.display    = 'flex';
    renderReviewQuestion();
  }

  function renderReviewQuestion() {
    const q = _questions[_reviewIdx];
    const r = _results[_reviewIdx];
    const test = DB.getTest(_testId);

    document.getElementById('rev-counter').textContent = `Item ${_reviewIdx+1} of ${_questions.length}`;
    document.getElementById('rev-test-name').textContent = test.name;

    // Stem with saved highlights
    const stemEl = document.getElementById('rev-stem');
    if (r.highlights && r.highlights.html) stemEl.innerHTML = r.highlights.html;
    else stemEl.textContent = q.t;

    // Tags
    const tagEl = document.getElementById('rev-tags');
    if (tagEl) {
      tagEl.innerHTML = (q.tags||[]).map(t=>`<span class="q-tag">${t}</span>`).join('');
      tagEl.style.display = q.tags && q.tags.length ? 'flex' : 'none';
    }

    // Options
    const optContainer = document.getElementById('rev-options');
    optContainer.innerHTML = '';
    q.o.forEach(opt => {
      const isCorrect = q.c === opt.l;
      const isChosen  = r.chosen === opt.l;
      const isStriken = r.strikethrough && r.strikethrough.includes(opt.l);
      const div = document.createElement('div');
      div.className = 'opt-row opt-row-review' +
        (isCorrect ? ' opt-correct' : '') +
        (isChosen && !isCorrect ? ' opt-wrong' : '') +
        (isStriken ? ' opt-striken' : '');
      div.innerHTML = `
        <div class="opt-selector">
          <div class="opt-radio">${isChosen || isCorrect ? '<div class="opt-radio-dot"></div>':''}</div>
          <span class="opt-letter">${opt.l})</span>
        </div>
        <div class="opt-text">${opt.t}</div>
        <div class="opt-indicator">
          ${isCorrect ? '<span class="ind-correct">✓ Correct</span>' : ''}
          ${isChosen && !isCorrect ? '<span class="ind-wrong">✗ Your Answer</span>' : ''}
        </div>`;
      optContainer.appendChild(div);
    });

    // Always show explanations in review using shared builder
    const expBody = document.getElementById('rev-exp-body');
    if (typeof buildExplanationHTML === 'function') {
      buildExplanationHTML(q, r, expBody);
    } else {
      // fallback
      expBody.innerHTML = '';
      q.o.forEach(opt => {
        const isCorrect = q.c === opt.l;
        const div = document.createElement('div');
        div.className = 'exp-item' + (isCorrect ? ' exp-correct' : '');
        div.innerHTML = '<div class="exp-header"><strong>' + opt.l + ') ' + opt.t + '</strong>' +
          (isCorrect ? '<span class="exp-badge-correct">&#10003; Correct</span>' : '') + '</div>' +
          (q.e && q.e[opt.l] ? '<div class="exp-text">' + q.e[opt.l] + '</div>' : '');
        expBody.appendChild(div);
      });
    }

    // Flag button
    const flagBtn = document.getElementById('rev-btn-flag');
    if (flagBtn) {
      const flagged = DB.isFlagged(_testId, q.n);
      flagBtn.textContent = flagged ? '🚩 Flagged' : '🏳 Flag';
      flagBtn.classList.toggle('flagged', flagged);
    }

    // Edit button
    const editBtn = document.getElementById('rev-btn-edit');
    if (editBtn) editBtn.onclick = () => openEditQuestion(_testId, q.n, _reviewIdx);

    // Prev/Next
    document.getElementById('rev-btn-prev').disabled = _reviewIdx === 0;
    document.getElementById('rev-btn-next').disabled = _reviewIdx === _questions.length - 1;
  }

  function reviewPrev() { if (_reviewIdx > 0) { _reviewIdx--; renderReviewQuestion(); } }
  function reviewNext() { if (_reviewIdx < _questions.length-1) { _reviewIdx++; renderReviewQuestion(); } }
  function closeReview() {
    document.getElementById('panel-report').style.display = 'flex';
    document.getElementById('panel-review').style.display = 'none';
    _inReview = false;
    // Scroll to row
    const row = document.getElementById(`res-row-${_reviewIdx}`);
    if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  function toggleFlagReview(idx) {
    const q = _questions[idx];
    if (DB.isFlagged(_testId, q.n)) DB.removeFlag(_testId, q.n);
    else DB.addFlag(_testId, q.n);
    buildReviewTable();
    buildNavDots();
    if (_inReview && _reviewIdx === idx) {
      const flagBtn = document.getElementById('rev-btn-flag');
      if (flagBtn) {
        const flagged = DB.isFlagged(_testId, q.n);
        flagBtn.textContent = flagged ? '🚩 Flagged' : '🏳 Flag';
        flagBtn.classList.toggle('flagged', flagged);
      }
    }
  }

  // ── Edit question ──────────────────────────────────────────
  function openEditQuestion(testId, qNum, displayIdx) {
    const test = DB.getTest(testId);
    const q = test.questions.find(q => q.n === qNum);
    if (!q) return;
    const modal = document.getElementById('modal-edit');
    if (!modal) return;

    modal.querySelector('#edit-stem').value = q.t;
    const optContainer = modal.querySelector('#edit-options');
    optContainer.innerHTML = '';
    q.o.forEach(opt => {
      const row = document.createElement('div');
      row.className = 'edit-opt-row';
      row.innerHTML = `
        <span class="edit-opt-letter">${opt.l})</span>
        <input type="text" class="edit-opt-text" data-letter="${opt.l}" value="${opt.t.replace(/"/g,'&quot;')}">
        <label class="edit-correct-lbl">
          <input type="radio" name="correct-ans" value="${opt.l}" ${q.c===opt.l?'checked':''}> Correct
        </label>`;
      optContainer.appendChild(row);
    });

    // Explanations
    const expContainer = modal.querySelector('#edit-explanations');
    expContainer.innerHTML = '';
    q.o.forEach(opt => {
      const row = document.createElement('div');
      row.className = 'edit-exp-row';
      row.innerHTML = `<label class="edit-exp-label">${opt.l}) Explanation:</label>
        <textarea class="edit-exp-text" data-letter="${opt.l}" rows="2">${(q.e && q.e[opt.l])||''}</textarea>`;
      expContainer.appendChild(row);
    });

    modal.style.display = 'flex';
    modal.dataset.testId = testId;
    modal.dataset.qNum   = qNum;
    modal.dataset.displayIdx = displayIdx || '';
  }

  function saveEditQuestion() {
    const modal = document.getElementById('modal-edit');
    const testId = modal.dataset.testId;
    const qNum   = parseInt(modal.dataset.qNum);
    const test   = DB.getTest(testId);
    const q      = test.questions.find(q => q.n === qNum);
    if (!q) return;

    q.t = modal.querySelector('#edit-stem').value.trim();
    modal.querySelectorAll('.edit-opt-text').forEach(inp => {
      const opt = q.o.find(o => o.l === inp.dataset.letter);
      if (opt) opt.t = inp.value.trim();
    });
    const correctInput = modal.querySelector('input[name="correct-ans"]:checked');
    if (correctInput) q.c = correctInput.value;
    modal.querySelectorAll('.edit-exp-text').forEach(ta => {
      q.e = q.e || {};
      q.e[ta.dataset.letter] = ta.value.trim();
    });
    q.tags = OCR.autoTag(q.t, q.o);
    DB.updateTest(testId, { questions: test.questions });
    window.toast('Question saved ✓', 2000);
    // Re-render if in review
    if (_inReview) renderReviewQuestion();
    const qst = Quiz.getState(); if (qst) { Quiz.renderQuestion(); Quiz.renderOptions(); }
  }

  function grade(p)     { return p>=90?'Excellent':p>=80?'Proficient':p>=70?'Satisfactory':p>=60?'Borderline Pass':'Below Passing'; }
  function gradeDesc(p) { return p>=90?'Outstanding performance.':p>=80?'Strong command of material.':p>=70?'Passing — targeted review recommended.':p>=60?'Marginal — additional study required.':'Comprehensive review needed.'; }

  function toggleCurrentFlag() { toggleFlagReview(_reviewIdx); }
  function openEditFromReview() { const q = _questions[_reviewIdx]; Results.openEditQuestion(_testId, q.n, _reviewIdx); }
  return { show, openReview, reviewPrev, reviewNext, closeReview, toggleFlagReview, toggleCurrentFlag, openEditFromReview, openEditQuestion, saveEditQuestion };
})();
window.Results = Results;
window.openReview        = Results.openReview;
window.toggleFlagReview  = Results.toggleFlagReview;

