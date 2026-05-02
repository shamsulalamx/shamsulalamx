/* ============================================================
   DB.JS — Storage Layer
   Handles localStorage (primary) + Google Drive (sync)
============================================================ */
const DB = (() => {
  const LOCAL_KEY = 'nbme_app_v1';

  function defaultDB() {
    return {
      version: 1,
      settings: {
        googleClientId: null,
        googleAccessToken: null,
        googleTokenExpiry: null,
        driveFileId: null,
        setupComplete: false
      },
      folders: [],
      tests: [],
      trash: [],
      flags: [],
      history: []
    };
  }

  function loadLocal() {
    try {
      const raw = localStorage.getItem(LOCAL_KEY);
      if (!raw) return defaultDB();
      return Object.assign(defaultDB(), JSON.parse(raw));
    } catch(e) { return defaultDB(); }
  }

  function saveLocal(db) {
    try { localStorage.setItem(LOCAL_KEY, JSON.stringify(db)); }
    catch(e) {
      if (e.name === 'QuotaExceededError' && typeof window.toast === 'function')
        window.toast('⚠️ Storage almost full. Please export a backup.', 5000);
    }
  }

  let _db = null;
  function get() { if (!_db) _db = loadLocal(); return _db; }
  function save() { if (_db) { saveLocal(_db); scheduleDriveSync(); } }

  // ── Drive sync ─────────────────────────────────────────────
  let _syncTimer = null;
  function scheduleDriveSync() {
    if (_syncTimer) clearTimeout(_syncTimer);
    _syncTimer = setTimeout(() => syncToDrive(), 3000);
  }

  async function syncToDrive() {
    const db = get();
    if (!db.settings.setupComplete || !db.settings.googleAccessToken) return;
    if (Date.now() > (db.settings.googleTokenExpiry || 0)) { updateSyncIndicator('offline'); return; }
    try {
      updateSyncIndicator('syncing');
      const content = JSON.stringify(db);
      if (db.settings.driveFileId) {
        await fetch(`https://www.googleapis.com/upload/drive/v3/files/${db.settings.driveFileId}?uploadType=media`,
          { method: 'PATCH', headers: { Authorization: `Bearer ${db.settings.googleAccessToken}`, 'Content-Type': 'application/json' }, body: content });
      } else {
        const form = new FormData();
        form.append('metadata', new Blob([JSON.stringify({ name: 'nbme_quiz_data.json', mimeType: 'application/json' })], { type: 'application/json' }));
        form.append('file', new Blob([content], { type: 'application/json' }));
        const resp = await fetch('https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart',
          { method: 'POST', headers: { Authorization: `Bearer ${db.settings.googleAccessToken}` }, body: form });
        const data = await resp.json();
        db.settings.driveFileId = data.id;
        saveLocal(db);
      }
      updateSyncIndicator('synced');
    } catch(e) { updateSyncIndicator('error'); }
  }

  async function loadFromDrive(accessToken) {
    const db = get();
    if (!db.settings.driveFileId) return null;
    try {
      const resp = await fetch(`https://www.googleapis.com/drive/v3/files/${db.settings.driveFileId}?alt=media`,
        { headers: { Authorization: `Bearer ${accessToken}` } });
      if (!resp.ok) return null;
      const remote = await resp.json();
      const localSettings = Object.assign({}, db.settings);
      _db = Object.assign(defaultDB(), remote);
      _db.settings = Object.assign(_db.settings, localSettings);
      saveLocal(_db);
      return _db;
    } catch(e) { return null; }
  }

  async function googleSignIn() {
    const db = get();
    const clientId = db.settings.googleClientId;
    if (!clientId) return false;
    return new Promise(resolve => {
      const redirectUri = window.location.href.split('?')[0].split('#')[0];
      const authUrl = `https://accounts.google.com/o/oauth2/v2/auth?client_id=${encodeURIComponent(clientId)}&redirect_uri=${encodeURIComponent(redirectUri)}&response_type=token&scope=${encodeURIComponent('https://www.googleapis.com/auth/drive.file')}&prompt=consent`;
      const popup = window.open(authUrl, 'google_auth', 'width=500,height=600');
      const iv = setInterval(() => {
        try {
          if (!popup || popup.closed) { clearInterval(iv); resolve(false); return; }
          const hash = popup.location.hash;
          if (hash && hash.includes('access_token')) {
            popup.close(); clearInterval(iv);
            const p = new URLSearchParams(hash.substring(1));
            const token = p.get('access_token');
            db.settings.googleAccessToken = token;
            db.settings.googleTokenExpiry = Date.now() + parseInt(p.get('expires_in') || '3600') * 1000;
            save(); resolve(true);
          }
        } catch(e) {}
      }, 500);
    });
  }

  function updateSyncIndicator(state) {
    const el = document.getElementById('sync-indicator');
    if (!el) return;
    const s = { syncing: ['↻ Syncing…','#f0a500'], synced: ['✓ Synced','#27ae60'], error: ['⚠ Sync error','#e74c3c'], offline: ['● Local','#95a5a6'] }[state] || ['● Local','#95a5a6'];
    el.textContent = s[0]; el.style.color = s[1];
  }

  function exportBackup() {
    const blob = new Blob([JSON.stringify(get(), null, 2)], { type: 'application/json' });
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: `nbme_backup_${new Date().toISOString().slice(0,10)}.json` });
    a.click();
  }

  function importBackup(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = e => {
        try { _db = Object.assign(defaultDB(), JSON.parse(e.target.result)); saveLocal(_db); resolve(_db); }
        catch(err) { reject(err); }
      };
      reader.readAsText(file);
    });
  }

  function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2,7); }

  // ── Folders ─────────────────────────────────────────────────
  function getFolders() { return get().folders.sort((a,b) => (a.order||0) - (b.order||0)); }
  function createFolder(name) {
    const db = get();
    const f = { id: uid(), name, createdAt: Date.now(), order: db.folders.length };
    db.folders.push(f); save(); return f;
  }
  function renameFolder(id, name) { const f = get().folders.find(f=>f.id===id); if(f){f.name=name;save();} }
  function deleteFolder(id) {
    const db = get();
    db.tests.filter(t=>t.folderId===id).forEach(t=>trashTest(t.id));
    db.folders = db.folders.filter(f=>f.id!==id); save();
  }

  // ── Tests ────────────────────────────────────────────────────
  function getTests(folderId) { return get().tests.filter(t=>t.folderId===folderId); }
  function getTest(id) { return get().tests.find(t=>t.id===id) || null; }
  function createTest(folderId, name, questions) {
    const db = get();
    const test = { id: uid(), folderId, name, status: 'not_started', questions, attempts: 0, currentAttempt: null, createdAt: Date.now() };
    db.tests.push(test); save(); return test;
  }
  function updateTest(id, updates) {
    const db = get(); const idx = db.tests.findIndex(t=>t.id===id);
    if(idx>=0) { Object.assign(db.tests[idx], updates); save(); }
  }
  function renameTest(id, name) { updateTest(id, {name}); }
  function trashTest(id) {
    const db = get(); const idx = db.tests.findIndex(t=>t.id===id);
    if(idx<0) return;
    const test = db.tests.splice(idx,1)[0];
    test.deletedAt = Date.now(); db.trash.push(test);
    db.flags = db.flags.filter(f=>f.testId!==id); save();
  }
  function restoreTest(id) {
    const db = get(); const idx = db.trash.findIndex(t=>t.id===id);
    if(idx<0) return;
    const test = db.trash.splice(idx,1)[0]; delete test.deletedAt;
    if(!db.folders.find(f=>f.id===test.folderId) && db.folders.length) test.folderId = db.folders[0].id;
    db.tests.push(test); save();
  }
  function emptyTrash() { get().trash = []; save(); }
  function permanentDelete(id) { const db=get(); db.trash=db.trash.filter(t=>t.id!==id); save(); }

  // ── Attempts ─────────────────────────────────────────────────
  function saveAttempt(testId, attempt) {
    const db = get(); const test = db.tests.find(t=>t.id===testId);
    if(!test) return;
    test.currentAttempt = attempt;
    test.status = attempt ? 'in_progress' : 'not_started'; save();
  }
  function finishAttempt(testId, results, totSecs, mode) {
    const db = get(); const test = db.tests.find(t=>t.id===testId);
    if(!test) return;
    test.attempts = (test.attempts||0)+1; test.status = 'completed'; test.currentAttempt = null;
    const score = results.filter(r=>r.correct).length;
    const entry = { id:uid(), testId, attemptNum:test.attempts, date:Date.now(), mode, score, total:test.questions.length, totSecs, results };
    db.history.push(entry); save(); return entry;
  }
  function getHistory(testId) { return get().history.filter(h=>h.testId===testId).sort((a,b)=>b.date-a.date); }

  // ── Flags ─────────────────────────────────────────────────────
  function getFlags(folderId) {
    const db=get(); const ids=db.tests.filter(t=>t.folderId===folderId).map(t=>t.id);
    return db.flags.filter(f=>ids.includes(f.testId));
  }
  function addFlag(testId, questionId) {
    const db=get();
    if(db.flags.find(f=>f.testId===testId&&f.questionId===questionId)) return;
    db.flags.push({id:uid(),testId,questionId,createdAt:Date.now()}); save();
  }
  function removeFlag(testId, questionId) { const db=get(); db.flags=db.flags.filter(f=>!(f.testId===testId&&f.questionId===questionId)); save(); }
  function isFlagged(testId, questionId) { return !!get().flags.find(f=>f.testId===testId&&f.questionId===questionId); }

  return { get, save, uid, googleSignIn, loadFromDrive, syncToDrive, updateSyncIndicator,
    exportBackup, importBackup, getFolders, createFolder, renameFolder, deleteFolder,
    getTests, getTest, createTest, updateTest, renameTest, trashTest, restoreTest, emptyTrash, permanentDelete,
    saveAttempt, finishAttempt, getHistory, getFlags, addFlag, removeFlag, isFlagged };
})();
window.DB = DB;
