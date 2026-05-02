/* ============================================================
   APP.JS — Main controller
   Handles UI, routing, sidebar, modals, highlights
============================================================ */

const App = (() => {

  // ── State ──────────────────────────────────────────────────
  let _currentFolder = null;
  let _currentView   = 'home'; // 'home'|'quiz'|'results'|'flagged'|'trash'
  let _genQBFile = null, _genAKFile = null;
  let _genParsed = null;
  let _hlSelection = null;

  // ── Init ───────────────────────────────────────────────────
  function init() {
    window.toast = toast;
    renderSidebar();
    showHome();
    checkSetupWizard();
    checkGoogleToken();

    // Close modals on overlay click
    document.querySelectorAll('.modal-overlay').forEach(m => {
      m.addEventListener('click', e => { if (e.target === m) m.style.display = 'none'; });
    });

    // Hide highlight toolbar on outside click
    document.addEventListener('mousedown', e => {
      if (!document.getElementById('hl-toolbar').contains(e.target) &&
          !document.getElementById('q-stem')?.contains(e.target)) {
        hideHlToolbar();
      }
    });

    // Auto-save on visibility change (tab switch / close)
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        const st = Quiz.getState();
        if (st) {
          st.results[st.qIdx].time = st.qSecs || 0;
          DB.saveAttempt(st.testId, {
            mode: st.mode, qIdx: st.qIdx, results: st.results,
            marks: [...st.marks], totSecs: st.totSecs
          });
        }
      }
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', onKeydown);
  }

  function onKeydown(e) {
    if (document.querySelector('.modal-overlay[style*="flex"]')) return; // modal open
    const st = Quiz.getState();
    if (!st) return;
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    const q = DB.getTest(st.testId)?.questions[st.qIdx];
    if (!q) return;

    // A–I select answer choices
    const letter = e.key.toUpperCase();
    if (/^[A-I]$/.test(letter) && q.o.find(o => o.l === letter)) {
      if (!st.results[st.qIdx].answered) Quiz.selectAnswer ? Quiz.selectAnswer(letter) : null;
      // selectAnswer is called via the module but exposed via closure; trigger click
      const opts = document.querySelectorAll('.opt-selector');
      opts.forEach(el => { if (el.dataset.letter === letter) el.click(); });
      return;
    }

    switch(e.key) {
      case 'ArrowRight': case 'Enter': Quiz.nextQ(); break;
      case 'ArrowLeft':                Quiz.prevQ(); break;
      case 'p': case 'P':              Quiz.pauseTest(); break;
      case 'f': case 'F':              Quiz.toggleFlag(st.qIdx); break;
      case 'm': case 'M':              Quiz.toggleMark(st.qIdx); break;
    }
  }

  // ── Toast ──────────────────────────────────────────────────
  function toast(msg, ms = 2500) {
    const t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), ms);
  }

  // ── Sidebar ────────────────────────────────────────────────
  function renderSidebar() {
    const container = document.getElementById('folder-list');
    const folders = DB.getFolders();
    container.innerHTML = '';

    folders.forEach(folder => {
      const tests = DB.getTests(folder.id);
      const wrap = document.createElement('div');
      wrap.className = 'sidebar-folder';

      const header = document.createElement('div');
      header.className = 'sidebar-folder-header' + (_currentFolder === folder.id ? ' open' : '');
      header.innerHTML = `
        <span class="folder-arrow">▶</span>
        <span class="item-icon">📁</span>
        <span class="item-label" id="folder-label-${folder.id}" style="flex:1;">${folder.name}</span>
        <span class="item-count">${tests.length}</span>`;

      header.addEventListener('click', e => {
        if (e.target.classList.contains('item-label') && e.detail === 2) {
          startRenameFolder(folder.id); return;
        }
        toggleFolder(folder.id, header, testsDiv);
        if (_currentFolder !== folder.id) showFolderHome(folder.id);
      });

      header.addEventListener('contextmenu', e => {
        e.preventDefault();
        showFolderContextMenu(e, folder);
      });

      const testsDiv = document.createElement('div');
      testsDiv.className = 'sidebar-folder-tests' + (_currentFolder === folder.id ? ' open' : '');

      tests.forEach(test => {
        const item = document.createElement('div');
        item.className = 'sidebar-test-item' + (isCurrentTest(test.id) ? ' active' : '');
        const dotClass = { not_started: 'dot-not-started', in_progress: 'dot-in-progress', completed: 'dot-completed' }[test.status] || 'dot-not-started';
        item.innerHTML = `<div class="test-status-dot ${dotClass}"></div>
          <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${test.name}</span>`;
        item.addEventListener('click', () => showFolderHome(folder.id, test.id));
        item.addEventListener('contextmenu', e => { e.preventDefault(); showTestContextMenu(e, test); });
        item.addEventListener('dblclick', () => startRenameTest(test.id));
        testsDiv.appendChild(item);
      });

      // Flagged tab for folder
      const flagItem = document.createElement('div');
      flagItem.className = 'sidebar-test-item';
      const flagCount = DB.getFlags(folder.id).length;
      flagItem.innerHTML = `<span>🚩</span><span style="flex:1;">Flagged (${flagCount})</span>`;
      flagItem.addEventListener('click', () => showFlagged(folder.id));
      testsDiv.appendChild(flagItem);

      wrap.appendChild(header); wrap.appendChild(testsDiv);
      container.appendChild(wrap);
    });
  }

  function toggleFolder(folderId, header, testsDiv) {
    const isOpen = testsDiv.classList.contains('open');
    testsDiv.classList.toggle('open', !isOpen);
    header.classList.toggle('open', !isOpen);
  }

  function isCurrentTest(testId) {
    const st = Quiz.getState();
    return st && st.testId === testId;
  }

  // ── Context menus ──────────────────────────────────────────
  function showFolderContextMenu(e, folder) {
    removeContextMenus();
    const menu = document.createElement('div');
    menu.id = 'ctx-menu';
    menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;background:white;border:1px solid #c8d0da;border-radius:4px;box-shadow:0 4px 16px rgba(0,0,0,.15);z-index:9000;min-width:150px;`;
    menu.innerHTML = `
      <div class="ctx-item" onclick="App.startRenameFolder('${folder.id}')">✏️ Rename</div>
      <div class="ctx-item" onclick="App.generateInFolder('${folder.id}')">＋ New Test</div>
      <div class="ctx-item ctx-danger" onclick="App.deleteFolder('${folder.id}')">🗑 Delete Folder</div>`;
    styleContextMenu(menu);
    document.body.appendChild(menu);
    setTimeout(() => document.addEventListener('click', removeContextMenus, { once: true }), 10);
  }

  function showTestContextMenu(e, test) {
    removeContextMenus();
    const menu = document.createElement('div');
    menu.id = 'ctx-menu';
    menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;background:white;border:1px solid #c8d0da;border-radius:4px;box-shadow:0 4px 16px rgba(0,0,0,.15);z-index:9000;min-width:160px;`;
    menu.innerHTML = `
      <div class="ctx-item" onclick="Quiz.startTest('${test.id}')">▶ Start / Resume</div>
      <div class="ctx-item" onclick="App.startRenameTest('${test.id}')">✏️ Rename</div>
      <div class="ctx-item" onclick="App.viewHistory('${test.id}')">📊 History</div>
      <div class="ctx-item ctx-danger" onclick="App.trashTest('${test.id}')">🗑 Move to Trash</div>`;
    styleContextMenu(menu);
    document.body.appendChild(menu);
    setTimeout(() => document.addEventListener('click', removeContextMenus, { once: true }), 10);
  }

  function styleContextMenu(menu) {
    const style = document.createElement('style');
    style.textContent = `.ctx-item{padding:8px 14px;font-size:12px;cursor:pointer;color:#1a1a2e;}.ctx-item:hover{background:#f0f2f5;}.ctx-danger{color:#c0392b;}`;
    menu.prepend(style);
  }

  function removeContextMenus() {
    document.getElementById('ctx-menu')?.remove();
  }

  // ── Views ──────────────────────────────────────────────────
  function showHome(folderId) {
    _currentView = 'home';
    if (folderId) _currentFolder = folderId;
    document.getElementById('screen-home').style.display    = 'flex';
    document.getElementById('screen-quiz').style.display    = 'none';
    document.getElementById('screen-results').style.display = 'none';
    renderSidebar();
    renderHomeGrid();
    setActiveNav('nav-home');
  }

  function showFolderHome(folderId, highlightTestId) {
    _currentFolder = folderId;
    showHome(folderId);
    if (highlightTestId) {
      // Scroll to card
      setTimeout(() => {
        document.getElementById(`card-${highlightTestId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 100);
    }
  }

  function renderHomeGrid() {
    const titleEl = document.getElementById('home-title');
    const contentEl = document.getElementById('home-content');

    if (!_currentFolder) {
      titleEl.textContent = 'Welcome';
      contentEl.innerHTML = '<div class="no-tests">Select a folder from the sidebar, or create a new one to get started.</div>';
      return;
    }

    const db = DB.get();
    const folder = db.folders.find(f => f.id === _currentFolder);
    if (!folder) return;

    titleEl.textContent = folder.name;
    const tests = DB.getTests(_currentFolder);

    if (!tests.length) {
      contentEl.innerHTML = `<div class="no-tests">No tests in this folder yet.<br><br>
        <button class="btn-generate" onclick="App.generateInFolder('${_currentFolder}')">＋ Generate Test</button></div>`;
      return;
    }

    let html = '<div class="test-grid">';
    tests.forEach(test => {
      const history = DB.getHistory(test.id);
      const latest  = history[0];
      const prog    = test.currentAttempt
        ? Math.round(((test.currentAttempt.qIdx || 0) / test.questions.length) * 100)
        : latest ? 100 : 0;
      const statusClass = { not_started: 'status-not-started', in_progress: 'status-in-progress', completed: 'status-completed' }[test.status] || 'status-not-started';
      const statusText  = { not_started: 'Not Started', in_progress: `Q${(test.currentAttempt?.qIdx||0)+1}/${test.questions.length}`, completed: `${latest ? Math.round(latest.score/latest.total*100)+'%' : ''}` }[test.status] || 'Not Started';
      const scoreLabel  = latest ? `Best: ${latest.score}/${latest.total}` : '';

      html += `<div class="test-card" id="card-${test.id}">
        <div class="test-card-status ${statusClass}">${statusText}</div>
        <div class="test-card-name">${test.name}</div>
        <div class="test-card-meta">${test.questions.length} questions · ${test.attempts} attempt${test.attempts!==1?'s':''}</div>
        <div class="test-card-progress"><div class="test-card-progress-fill" style="width:${prog}%"></div></div>
        <div class="test-card-footer">
          <span class="test-card-prog-label">${test.status==='in_progress'?'In progress':'Progress'}: ${prog}%</span>
          <span class="test-card-score">${scoreLabel}</span>
        </div>
        <div class="test-card-actions">
          <button class="btn-card primary" onclick="Quiz.startTest('${test.id}')">▶ ${test.status==='in_progress'?'Resume':'Start'}</button>
          <button class="btn-card" onclick="App.viewHistory('${test.id}')">📊</button>
          <button class="btn-card" onclick="App.startRenameTest('${test.id}')">✏️</button>
          <button class="btn-card danger" onclick="App.trashTest('${test.id}')">🗑</button>
        </div>
      </div>`;
    });
    html += '</div>';
    contentEl.innerHTML = html;
  }

  function showFlagged(folderId) {
    _currentView = 'flagged';
    document.getElementById('screen-home').style.display    = 'flex';
    document.getElementById('screen-quiz').style.display    = 'none';
    document.getElementById('screen-results').style.display = 'none';

    document.getElementById('home-title').textContent = folderId
      ? `Flagged — ${DB.getFolders().find(f=>f.id===folderId)?.name || ''}`
      : 'All Flagged Questions';

    const flags = folderId ? DB.getFlags(folderId) : DB.get().flags;
    const content = document.getElementById('home-content');

    if (!flags.length) {
      content.innerHTML = '<div class="no-tests">No flagged questions yet.</div>';
      return;
    }

    let html = '';
    flags.forEach(flag => {
      const test = DB.getTest(flag.testId);
      if (!test) return;
      const q = test.questions.find(q => q.n === flag.questionId);
      if (!q) return;
      const history = DB.getHistory(flag.testId);
      // Find last answer for this question
      let lastAnswer = null;
      for (const h of history) {
        const r = h.results?.find(r => r.qNum === q.n || h.results?.indexOf(r) === q.n - 1);
        if (r) { lastAnswer = r; break; }
      }
      const correctOpt = q.o.find(o => o.l === q.c);

      html += `<div class="flagged-item">
        <div class="flagged-item-source">📋 ${test.name}</div>
        <div class="flagged-item-q">${q.t.slice(0, 200)}${q.t.length > 200 ? '…' : ''}</div>
        ${lastAnswer ? `<div class="flagged-item-answer">
          <strong>Your Answer:</strong> ${lastAnswer.chosen || 'Skipped'}
          ${lastAnswer.correct ? ' <span style="color:#27ae60">✓</span>' : ' <span style="color:#c0392b">✗</span>'}
          &nbsp;|&nbsp; <strong>Correct:</strong> ${q.c}) ${correctOpt?.t || ''}
        </div>` : ''}
        ${q.e && q.e[q.c] ? `<div class="flagged-item-exp"><strong>${q.c}) </strong>${q.e[q.c]}</div>` : ''}
        <div class="flagged-item-footer">
          <button class="btn-unflag" onclick="App.unflag('${flag.testId}',${flag.questionId})">Remove Flag</button>
        </div>
      </div>`;
    });
    content.innerHTML = html;
    setActiveNav('nav-flagged');
  }

  function unflag(testId, questionId) {
    DB.removeFlag(testId, questionId);
    renderSidebar();
    showFlagged(_currentFolder);
    toast('Flag removed.');
  }

  function showTrash() {
    _currentView = 'trash';
    document.getElementById('home-title').textContent = '🗑 Trash';
    const db = DB.get();
    const content = document.getElementById('home-content');
    if (!db.trash.length) {
      content.innerHTML = '<div class="no-tests">Trash is empty.</div>';
      return;
    }
    let html = `<div style="margin-bottom:12px;display:flex;justify-content:flex-end;">
      <button class="btn-card danger" onclick="if(confirm('Permanently delete all?')){DB.emptyTrash();App.showTrash();}">Empty Trash</button>
    </div>`;
    db.trash.forEach(t => {
      html += `<div class="trash-item">
        <div class="trash-item-info">
          <div class="trash-name">${t.name}</div>
          <div class="trash-meta">${t.questions?.length||0} questions · Deleted ${new Date(t.deletedAt).toLocaleDateString()}</div>
        </div>
        <div class="trash-item-actions">
          <button class="btn-card" onclick="DB.restoreTest('${t.id}');App.showHome();App.renderSidebar();toast('Restored!')">↩ Restore</button>
          <button class="btn-card danger" onclick="if(confirm('Permanently delete?')){DB.permanentDelete('${t.id}');App.showTrash();}">✕ Delete</button>
        </div>
      </div>`;
    });
    content.innerHTML = html;
    setActiveNav('nav-trash');
  }

  function setActiveNav(id) {
    document.querySelectorAll('.sidebar-item').forEach(el => el.classList.remove('active'));
    document.getElementById(id)?.classList.add('active');
  }

  // ── Folders & Tests management ─────────────────────────────
  function promptNewFolder() {
    document.getElementById('new-folder-name').value = '';
    document.getElementById('modal-new-folder').style.display = 'flex';
    setTimeout(() => document.getElementById('new-folder-name').focus(), 100);
  }

  function createFolder() {
    const name = document.getElementById('new-folder-name').value.trim();
    if (!name) { toast('Please enter a folder name.'); return; }
    DB.createFolder(name);
    document.getElementById('modal-new-folder').style.display = 'none';
    renderSidebar();
    toast(`Folder "${name}" created.`);
  }

  function startRenameFolder(id) {
    const label = document.getElementById(`folder-label-${id}`);
    if (!label) return;
    const folder = DB.getFolders().find(f => f.id === id);
    const input = document.createElement('input');
    input.className = 'rename-input';
    input.value = folder.name;
    label.replaceWith(input);
    input.focus(); input.select();
    const done = () => {
      const name = input.value.trim() || folder.name;
      DB.renameFolder(id, name);
      renderSidebar();
      if (_currentFolder === id) document.getElementById('home-title').textContent = name;
    };
    input.addEventListener('blur', done);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') { done(); } if (e.key === 'Escape') renderSidebar(); });
  }

  function startRenameTest(id) {
    const test = DB.getTest(id);
    if (!test) return;
    const name = prompt('Rename test:', test.name);
    if (name && name.trim()) { DB.renameTest(id, name.trim()); renderSidebar(); renderHomeGrid(); toast('Renamed.'); }
  }

  function deleteFolder(id) {
    if (!confirm('Delete folder and move all tests to Trash?')) return;
    DB.deleteFolder(id);
    _currentFolder = null;
    renderSidebar(); showHome(); toast('Folder deleted.');
  }

  function trashTest(id) {
    if (!confirm('Move this test to Trash?')) return;
    DB.trashTest(id);
    renderSidebar(); renderHomeGrid(); toast('Moved to Trash.');
  }

  function generateInFolder(folderId) {
    _currentFolder = folderId;
    openGenerateModal();
  }

  function viewHistory(testId) {
    const test = DB.getTest(testId);
    const history = DB.getHistory(testId);
    const content = document.getElementById('home-content');
    const titleEl  = document.getElementById('home-title');
    titleEl.textContent = `History — ${test.name}`;
    if (!history.length) { content.innerHTML = '<div class="no-tests">No attempts yet.</div>'; return; }
    let html = `<button class="btn-card" onclick="App.showFolderHome('${test.folderId}')" style="margin-bottom:12px;">← Back</button>`;
    history.forEach(h => {
      const pct = Math.round(h.score/h.total*100);
      html += `<div class="test-card" style="cursor:default;">
        <div class="test-card-name">Attempt #${h.attemptNum} · ${new Date(h.date).toLocaleString()}</div>
        <div class="test-card-meta">${h.mode==='tutor'?'📖 Tutor':'📝 Exam'} · ${Quiz.fmtTime(h.totSecs)} total</div>
        <div class="test-card-score" style="font-size:20px;margin:8px 0;">${h.score}/${h.total} <span style="font-size:14px;color:${pct>=80?'#27ae60':pct>=70?'#2980b9':'#c0392b'};">(${pct}%)</span></div>
      </div>`;
    });
    content.innerHTML = html;
  }

  // ── Generate Test Modal ────────────────────────────────────
  function openGenerateModal() {
    _genQBFile = null; _genAKFile = null; _genParsed = null;
    ['inp-qb','inp-ak'].forEach(id => document.getElementById(id).value = '');
    ['nm-qb','nm-ak'].forEach(id => document.getElementById(id).textContent = '');
    ['uz-qb','uz-ak'].forEach(id => document.getElementById(id).classList.remove('loaded','dragover'));
    document.getElementById('ocr-status-area').style.display = 'none';
    document.getElementById('gen-parse-note').style.display  = 'none';
    document.getElementById('btn-gen-start').textContent = 'Extract & Generate →';
    document.getElementById('btn-gen-start').disabled = false;

    // Populate folder select
    const sel = document.getElementById('gen-folder-select');
    sel.innerHTML = '';
    const folders = DB.getFolders();
    if (_currentFolder) {
      const f = folders.find(f => f.id === _currentFolder);
      if (f) sel.innerHTML += `<option value="${f.id}" selected>${f.name}</option>`;
    }
    folders.filter(f => f.id !== _currentFolder).forEach(f => {
      sel.innerHTML += `<option value="${f.id}">${f.name}</option>`;
    });
    if (!sel.options.length) sel.innerHTML = '<option value="">— No folders yet —</option>';

    document.getElementById('modal-generate').style.display = 'flex';
    document.getElementById('gen-test-name').focus();
  }

  function closeGenerateModal() {
    document.getElementById('modal-generate').style.display = 'none';
  }

  function onDrag(e, id)  { e.preventDefault(); document.getElementById('uz-'+id).classList.add('dragover'); }
  function offDrag(id)    { document.getElementById('uz-'+id).classList.remove('dragover'); }
  function onDrop(e, id)  { e.preventDefault(); offDrag(id); const f = e.dataTransfer.files[0]; if (f) processFileDrop(id, f); }
  function onFile(id, inp) { const f = inp.files[0]; if (f) processFileDrop(id, f); }

  function processFileDrop(id, file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) { toast('Please upload a PDF file.'); return; }
    if (id === 'qb') _genQBFile = file; else _genAKFile = file;
    document.getElementById('nm-'+id).textContent = '📄 ' + file.name;
    document.getElementById('uz-'+id).classList.add('loaded');
    document.getElementById('gen-parse-note').style.display = 'none';
    _genParsed = null;
  }

  async function startOCR() {
    const name     = document.getElementById('gen-test-name').value.trim();
    const folderId = document.getElementById('gen-folder-select').value;

    if (!name)       { toast('Please enter a test name.'); return; }
    if (!folderId)   { toast('Please create a folder first.'); return; }
    if (!_genQBFile) { toast('Please upload the Question Bank PDF.'); return; }
    if (!_genAKFile) { toast('Please upload the Answer Key PDF.'); return; }

    document.getElementById('ocr-status-area').style.display = 'block';
    document.getElementById('btn-gen-start').disabled = true;
    document.getElementById('btn-gen-start').textContent = 'Processing…';

    try {
      const questions = await OCR.processTestPDFs(_genQBFile, _genAKFile, (pct, total, msg) => {
        document.getElementById('ocr-status-msg').textContent = msg;
        document.getElementById('ocr-progress-fill').style.width = pct + '%';
      });

      if (!questions.length) throw new Error('No questions found. Try the manual paste option.');

      _genParsed = { name, folderId, questions };
      document.getElementById('ocr-status-msg').textContent = `✓ Extracted ${questions.length} questions!`;
      document.getElementById('ocr-progress-fill').style.width = '100%';
      document.getElementById('gen-parse-note').textContent   = `✓ ${questions.length} questions ready. Click Save to create the test.`;
      document.getElementById('gen-parse-note').style.display = 'block';
      document.getElementById('btn-gen-start').textContent    = '💾 Save Test';
      document.getElementById('btn-gen-start').disabled       = false;
      document.getElementById('btn-gen-start').onclick        = saveGeneratedTest;
    } catch(err) {
      document.getElementById('ocr-status-msg').textContent = '✗ Error: ' + err.message;
      document.getElementById('btn-gen-start').disabled     = false;
      document.getElementById('btn-gen-start').textContent  = 'Try Again →';
      toast('OCR failed. Try manual text entry if the PDF is still unreadable.', 4000);
    }
  }

  function saveGeneratedTest() {
    if (!_genParsed) return;
    const test = DB.createTest(_genParsed.folderId, _genParsed.name, _genParsed.questions);
    document.getElementById('modal-generate').style.display = 'none';
    _currentFolder = _genParsed.folderId;
    renderSidebar(); renderHomeGrid();
    toast(`✓ "${test.name}" created with ${test.questions.length} questions!`);
    _genParsed = null;
  }

  // ── Mode toggle ────────────────────────────────────────────
  function toggleMode() {
    const st = Quiz.getState();
    if (!st) return;
    const newMode = st.mode === 'tutor' ? 'exam' : 'tutor';
    Quiz.setMode(newMode);
    document.getElementById('btn-mode-toggle').textContent = newMode === 'tutor' ? '📖 Tutor' : '📝 Exam';
    document.getElementById('btn-mode-toggle').classList.toggle('mode-exam', newMode === 'exam');
    toast(newMode === 'tutor' ? 'Switched to Tutor Mode — explanations visible' : 'Switched to Exam Mode — explanations hidden', 2000);
  }

  // ── Finish ─────────────────────────────────────────────────
  function confirmFinish() {
    const st = Quiz.getState();
    if (!st) return;
    const test = DB.getTest(st.testId);
    const answered = st.results.filter(r => r.answered).length;
    const unanswered = test.questions.length - answered;
    document.getElementById('confirm-finish-info').textContent =
      `${answered} of ${test.questions.length} answered.${unanswered > 0 ? ` ${unanswered} unanswered questions will be marked as skipped.` : ''}`;
    document.getElementById('modal-confirm-finish').style.display = 'flex';
  }

  function confirmFinishFromPause() {
    document.getElementById('overlay-pause').style.display = 'none';
    document.getElementById('modal-confirm-finish').style.display = 'flex';
  }

  function doFinish() {
    document.getElementById('modal-confirm-finish').style.display = 'none';
    Quiz.finishTest();
  }

  function retakeTest() {
    // Called from results screen
    const st = Quiz.getState(); // may be null
    // Find last viewed test from results
    const resTitle = document.getElementById('res-test-name').textContent.replace(' — Score Report','');
    const db = DB.get();
    const test = db.tests.find(t => t.name === resTitle) || db.tests[db.tests.length - 1];
    if (test) {
      document.getElementById('screen-results').style.display = 'none';
      Quiz.startTest(test.id);
    }
  }

  // ── Edit question ──────────────────────────────────────────
  function openEditCurrentQuestion() {
    const st = Quiz.getState();
    if (!st) return;
    const test = DB.getTest(st.testId);
    const q = test.questions[st.qIdx];
    Results.openEditQuestion(st.testId, q.n, st.qIdx);
  }

  // ── Highlighting ───────────────────────────────────────────
  let _hlSel = null;

  function onStemSelect(e) {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) { hideHlToolbar(); return; }
    _hlSel = sel.getRangeAt(0).cloneRange();
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    const tb = document.getElementById('hl-toolbar');
    tb.style.left = Math.max(0, rect.left + rect.width/2 - 65) + 'px';
    tb.style.top  = (rect.top + window.scrollY - 44) + 'px';
    tb.classList.add('show');
  }

  function hideHlToolbar() {
    document.getElementById('hl-toolbar')?.classList.remove('show');
    _hlSel = null;
  }

  function applyHighlight(cls) {
    if (!_hlSel) { hideHlToolbar(); return; }
    try {
      const mark = document.createElement('mark');
      mark.className = cls; mark.setAttribute('data-hl', cls);
      _hlSel.surroundContents(mark);
    } catch(e) {
      try {
        const frag = _hlSel.extractContents();
        const mark = document.createElement('mark');
        mark.className = cls; mark.setAttribute('data-hl', cls);
        mark.appendChild(frag); _hlSel.insertNode(mark);
      } catch(_) {}
    }
    const stemEl = document.getElementById('q-stem');
    const st = Quiz.getState();
    if (st) Quiz.saveHighlight(st.qIdx, stemEl.innerHTML);
    hideHlToolbar();
    window.getSelection()?.removeAllRanges();
  }

  function eraseHighlight() {
    const stemEl = document.getElementById('q-stem');
    stemEl.querySelectorAll('mark[data-hl]').forEach(mark => {
      const sel = window.getSelection();
      const range = sel?.rangeCount ? sel.getRangeAt(0) : null;
      if (!range || range.intersectsNode(mark)) {
        const parent = mark.parentNode;
        while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
        parent.removeChild(mark);
      }
    });
    const st = Quiz.getState();
    if (st) Quiz.saveHighlight(st.qIdx, stemEl.innerHTML);
    hideHlToolbar();
  }

  // ── Settings & Google Drive ────────────────────────────────
  function openSettings() {
    const db = DB.get();
    const statusEl = document.getElementById('gdrive-status');
    if (db.settings.setupComplete && db.settings.googleClientId) {
      statusEl.innerHTML = `<span style="color:#27ae60;">✓ Configured</span> · Client ID: ${db.settings.googleClientId.slice(0,20)}…`;
    } else {
      statusEl.innerHTML = '<span style="color:#f0a500;">Not configured</span>';
    }
    document.getElementById('modal-settings').style.display = 'flex';
  }

  async function googleSignIn() {
    const success = await DB.googleSignIn();
    if (success) {
      toast('✓ Signed in to Google Drive!');
      const db = DB.get();
      await DB.loadFromDrive(db.settings.googleAccessToken);
      renderSidebar(); renderHomeGrid();
      DB.updateSyncIndicator('synced');
    } else {
      toast('Sign-in failed or cancelled.');
    }
  }

  function checkGoogleToken() {
    const db = DB.get();
    if (db.settings.googleAccessToken && Date.now() < (db.settings.googleTokenExpiry || 0)) {
      DB.updateSyncIndicator('synced');
      DB.loadFromDrive(db.settings.googleAccessToken).then(remote => {
        if (remote) { renderSidebar(); renderHomeGrid(); }
      });
    } else {
      DB.updateSyncIndicator('offline');
    }
  }

  // ── Setup Wizard ───────────────────────────────────────────
  function checkSetupWizard() {
    const db = DB.get();
    if (!db.settings.setupComplete) {
      // Show welcome hint in home
      const content = document.getElementById('home-content');
      content.innerHTML = `<div style="background:#e3f2fd;border:1px solid #90caf9;border-radius:4px;padding:16px 20px;max-width:500px;">
        <div style="font-size:13px;font-weight:700;color:#0d47a1;margin-bottom:6px;">👋 Welcome to NBME Self-Assessment Suite</div>
        <div style="font-size:12px;color:#1565c0;margin-bottom:12px;line-height:1.6;">
          To sync across devices, set up Google Drive in <strong>⚙ Settings</strong> above.<br>
          To get started, create a folder in the sidebar, then click <strong>+ Generate Test</strong>.
        </div>
        <button class="btn-generate" onclick="App.openSetupWizard()">Set Up Google Drive →</button>
      </div>`;
    }
  }

  const WIZARD_STEPS = [
    {
      title: 'Create a Google Cloud Project',
      content: `<div class="wizard-instruction">
        <ol>
          <li>Go to <a href="https://console.cloud.google.com" target="_blank">console.cloud.google.com</a></li>
          <li>Click <strong>"Select a project"</strong> → <strong>"New Project"</strong></li>
          <li>Name it <code>NBME Quiz App</code> → click <strong>Create</strong></li>
          <li>Make sure the new project is selected in the top bar</li>
        </ol>
      </div>
      <div class="wizard-note">💡 This is completely free. Google Cloud has no cost for this usage.</div>`
    },
    {
      title: 'Enable Google Drive API',
      content: `<div class="wizard-instruction">
        <ol>
          <li>In the left menu, go to <strong>APIs & Services → Library</strong></li>
          <li>Search for <strong>"Google Drive API"</strong></li>
          <li>Click it, then click <strong>Enable</strong></li>
        </ol>
      </div>`
    },
    {
      title: 'Create OAuth Credentials',
      content: `<div class="wizard-instruction">
        <ol>
          <li>Go to <strong>APIs & Services → Credentials</strong></li>
          <li>Click <strong>+ Create Credentials → OAuth client ID</strong></li>
          <li>If prompted, configure the consent screen first:
            <ul>
              <li>Choose <strong>External</strong> → Create</li>
              <li>Fill in App name: <code>NBME Quiz</code>, support email: your email</li>
              <li>Click Save and Continue through all steps</li>
            </ul>
          </li>
          <li>Back on Create OAuth client ID:
            <ul>
              <li>Application type: <strong>Web application</strong></li>
              <li>Name: <code>NBME Quiz</code></li>
              <li>Authorized JavaScript origins: add <code>${window.location.origin}</code></li>
              <li>Click <strong>Create</strong></li>
            </ul>
          </li>
        </ol>
      </div>`
    },
    {
      title: 'Add Test User',
      content: `<div class="wizard-instruction">
        <ol>
          <li>Go to <strong>APIs & Services → OAuth consent screen</strong></li>
          <li>Scroll to <strong>Test users</strong> → click <strong>+ Add users</strong></li>
          <li>Add: <code>shuvoli8@gmail.com</code></li>
          <li>Click Save</li>
        </ol>
      </div>
      <div class="wizard-note">This lets your account use the app while it's in development mode.</div>`
    },
    {
      title: 'Enter Your Client ID',
      content: `<div class="wizard-instruction">
        <p>Copy your <strong>Client ID</strong> (looks like: <code>123456789-abc.apps.googleusercontent.com</code>) and paste it below.</p>
      </div>
      <div class="form-group">
        <label class="form-label">Client ID</label>
        <input type="text" class="form-input" id="wizard-client-id" placeholder="123…apps.googleusercontent.com">
      </div>`
    }
  ];

  let _wizardStep = 0;

  function openSetupWizard() {
    _wizardStep = 0;
    document.getElementById('modal-settings').style.display = 'none';
    renderWizard();
    document.getElementById('modal-wizard').style.display = 'flex';
  }

  function renderWizard() {
    const steps = WIZARD_STEPS;
    // Progress indicator
    document.getElementById('wizard-steps').innerHTML =
      steps.map((_, i) => `<div class="wstep ${i < _wizardStep ? 'done' : i === _wizardStep ? 'active' : ''}"></div>`).join('');

    const step = steps[_wizardStep];
    const isLast = _wizardStep === steps.length - 1;
    document.getElementById('wizard-content').innerHTML = `
      <div class="wizard-step-title">Step ${_wizardStep + 1} of ${steps.length}: ${step.title}</div>
      ${step.content}
      <div class="modal-actions">
        ${_wizardStep > 0 ? '<button class="btn-modal" onclick="App.wizardBack()">← Back</button>' : ''}
        <button class="btn-modal" onclick="document.getElementById(\'modal-wizard\').style.display=\'none\'">Skip</button>
        <button class="btn-modal primary" onclick="App.wizardNext()">${isLast ? 'Finish Setup' : 'Next →'}</button>
      </div>`;
  }

  function wizardNext() {
    if (_wizardStep === WIZARD_STEPS.length - 1) {
      const clientId = document.getElementById('wizard-client-id')?.value?.trim();
      if (!clientId || !clientId.includes('.apps.googleusercontent.com')) {
        toast('Please enter a valid Client ID.'); return;
      }
      const db = DB.get();
      db.settings.googleClientId = clientId;
      db.settings.setupComplete  = true;
      DB.save();
      document.getElementById('modal-wizard').style.display = 'none';
      toast('✓ Google Drive configured! Click Settings → Sign In to connect.', 4000);
      return;
    }
    _wizardStep++;
    renderWizard();
  }

  function wizardBack() {
    if (_wizardStep > 0) { _wizardStep--; renderWizard(); }
  }

  // ── Backup ─────────────────────────────────────────────────
  function exportBackup() { DB.exportBackup(); toast('Backup exported to Downloads.'); }
  function importBackup(inp) {
    const file = inp.files[0];
    if (!file) return;
    DB.importBackup(file).then(() => {
      renderSidebar(); showHome(); toast('✓ Backup imported!');
    }).catch(() => toast('Import failed — invalid file.'));
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    init,
    toast,
    renderSidebar,
    showHome,
    showFolderHome,
    showFlagged,
    showTrash,
    unflag,
    promptNewFolder,
    createFolder,
    startRenameFolder,
    startRenameTest,
    deleteFolder,
    trashTest,
    generateInFolder,
    viewHistory,
    retakeTest,
    openGenerateModal,
    closeGenerateModal,
    onDrag, offDrag, onDrop, onFile,
    startOCR,
    toggleMode,
    confirmFinish,
    confirmFinishFromPause,
    doFinish,
    openEditCurrentQuestion,
    onStemSelect,
    applyHighlight,
    eraseHighlight,
    openSettings,
    googleSignIn,
    openSetupWizard,
    wizardNext,
    wizardBack,
    exportBackup,
    importBackup
  };
})();

// ── Bootstrap ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => App.init());
