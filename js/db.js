/* ============================================================
   DB.JS — Storage Layer
   Handles IndexedDB (primary) + localStorage (flags/migration) + Google Drive (sync)
============================================================ */
const DB = (() => {
  const LOCAL_KEY = 'nbme_app_v1';
  const DEFAULT_SOURCE_ID = 'src-nbme';
  const DEFAULT_SOURCE_FOLDERS = [
    { id: 'src-nbme', name: 'NBME', order: 0, sourceType: 'nbme', workflows: ['pdf-test-import'] },
    { id: 'src-uworld', name: 'UWorld', order: 1, sourceType: 'uworld-notes', workflows: ['docx-notes-preview'] },
    { id: 'src-anki', name: 'Anki', order: 2, sourceType: 'anki', workflows: ['anki-text-preview'] },
    { id: 'src-ome', name: 'OME', order: 3, sourceType: 'ome', workflows: ['ome-pdf-preview'] },
    { id: 'src-divine-podcasts', name: 'Divine Podcasts', order: 4, sourceType: 'divine', workflows: ['divine-transcript-preview'] },
    { id: 'src-mehlman', name: 'Mehlman', order: 5, sourceType: 'mehlman', workflows: ['mehlman-pdf-preview'] },
    { id: 'src-images-and-tables', name: 'Images and Tables', order: 6, sourceType: 'images-tables', workflows: [] },
    { id: 'src-amboss', name: 'Amboss', order: 7, sourceType: 'amboss', workflows: [] },
    { id: 'src-emma-holiday', name: 'Emma Holiday', order: 8, sourceType: 'nbme', workflows: ['pdf-test-import'] },
    { id: 'src-fast-facts', name: 'Fast Facts', order: 9, sourceType: 'nbme', workflows: ['pdf-test-import'] }
  ];

  function cloneSourceFolder(source) {
    return Object.assign({}, source, { workflows: Array.isArray(source.workflows) ? source.workflows.slice() : [] });
  }

  function defaultDB() {
    return {
      version: 1,
      settings: {},
      sourceFolders: DEFAULT_SOURCE_FOLDERS.map(cloneSourceFolder),
      folders: [],
      tests: [],
      trash: [],
      flags: [],
      marks: [],
      notes: [],
      history: []
    };
  }

  function ensureSourceFolders(db) {
    if (!Array.isArray(db.sourceFolders)) db.sourceFolders = [];
    DEFAULT_SOURCE_FOLDERS.forEach(src => {
      const existing = db.sourceFolders.find(s => s.id === src.id);
      if (!existing) db.sourceFolders.push(cloneSourceFolder(src));
      else {
        if (!existing.name) existing.name = src.name;
        if (existing.order == null) existing.order = src.order;
        if (!existing.sourceType) existing.sourceType = src.sourceType;
        if (!Array.isArray(existing.workflows)) existing.workflows = src.workflows.slice();
        src.workflows.forEach(workflow => {
          if (!existing.workflows.includes(workflow)) existing.workflows.push(workflow);
        });
      }
    });
    db.sourceFolders.forEach(source => {
      if (!source.sourceType) source.sourceType = 'custom';
      if (!Array.isArray(source.workflows)) source.workflows = [];
    });
    if (!Array.isArray(db.folders)) db.folders = [];
    db.folders.forEach(folder => {
      if (!folder.sourceId) folder.sourceId = DEFAULT_SOURCE_ID;
    });
    return db;
  }

  function isUnsafeStorageValue(key, value) {
    if (key === 'dataUrl' || key === '_figureData') return true;
    if (key === 'highlights') return true;
    if (key === '_range') return true;
    if (key === 'blob' || key === 'base64') return true;
    if (key === 'src' && typeof value === 'string' && /^data:image\//i.test(value)) return true;
    if (typeof value === 'string' && /^data:image\/[^;]+;base64,/i.test(value)) return true;
    return false;
  }

  function storagePayload(db) {
    return JSON.parse(JSON.stringify(db, (key, value) => {
      if (isUnsafeStorageValue(key, value)) return undefined;
      return value;
    }));
  }

  // ── AppStateStore: IndexedDB for full app state ──────────────
  const AppStateStore = (() => {
    const IDB_NAME   = 'nbme-main-db';
    const STORE_NAME = 'appState';
    const STATE_KEY  = 'main';
    let _idb = null;

    function open() {
      if (_idb) return Promise.resolve(_idb);
      return new Promise((resolve, reject) => {
        const req = indexedDB.open(IDB_NAME, 1);
        req.onupgradeneeded = e => { e.target.result.createObjectStore(STORE_NAME); };
        req.onsuccess = e => { _idb = e.target.result; resolve(_idb); };
        req.onerror   = e => reject(e.target.error);
      });
    }

    async function save(state) {
      const db = await open();
      return new Promise((resolve, reject) => {
        const tx  = db.transaction(STORE_NAME, 'readwrite');
        const st  = tx.objectStore(STORE_NAME);
        const req = st.put(state, STATE_KEY);
        req.onsuccess = () => resolve();
        req.onerror   = e => reject(e.target.error);
      });
    }

    async function load() {
      const db = await open();
      return new Promise((resolve, reject) => {
        const tx  = db.transaction(STORE_NAME, 'readonly');
        const st  = tx.objectStore(STORE_NAME);
        const req = st.get(STATE_KEY);
        req.onsuccess = e => resolve(e.target.result || null);
        req.onerror   = e => reject(e.target.error);
      });
    }

    return { save, load };
  })();

  // Only used for migration — reads legacy localStorage payload.
  function loadLocal() {
    try {
      const raw = localStorage.getItem(LOCAL_KEY);
      if (!raw) return null;
      return ensureSourceFolders(Object.assign(defaultDB(), JSON.parse(raw)));
    } catch(e) { return null; }
  }

  // Fallback localStorage write — used only when IndexedDB is unavailable.
  function saveLocal(db) {
    const histByCap = {};
    db.history = (db.history || []).filter(h => {
      histByCap[h.testId] = (histByCap[h.testId] || 0) + 1;
      return histByCap[h.testId] <= 3;
    });
    const WEEK = 7 * 24 * 60 * 60 * 1000;
    db.trash = (db.trash || []).filter(t => (Date.now() - (t.deletedAt || 0)) < WEEK);
    const payload = storagePayload(db);
    try {
      localStorage.setItem(LOCAL_KEY, JSON.stringify(payload));
      return true;
    } catch(e) {
      if (e.name === 'QuotaExceededError') {
        try {
          localStorage.removeItem(LOCAL_KEY);
          localStorage.setItem(LOCAL_KEY, JSON.stringify(payload));
          return true;
        } catch(e2) {
          const lean = storagePayload(Object.assign({}, db, { history: [], trash: [] }));
          try {
            localStorage.setItem(LOCAL_KEY, JSON.stringify(lean));
            db.history = []; db.trash = [];
            if (typeof window.toast === 'function')
              window.toast('Storage was full, so old history and trash were cleared. Your active tests were kept.', 8000);
            return true;
          } catch(e3) {
            if (typeof window.toast === 'function')
              window.toast('Storage full. Delete older tests, then try saving again.', 8000);
            return false;
          }
        }
      }
      return false;
    }
  }

  async function saveAppState(state) {
    // Apply housekeeping before persisting (mirrors saveLocal rules)
    const histByCap = {};
    state.history = (state.history || []).filter(h => {
      histByCap[h.testId] = (histByCap[h.testId] || 0) + 1;
      return histByCap[h.testId] <= 3;
    });
    const WEEK = 7 * 24 * 60 * 60 * 1000;
    state.trash = (state.trash || []).filter(t => (Date.now() - (t.deletedAt || 0)) < WEEK);

    const payload = storagePayload(state);
    try {
      await AppStateStore.save(payload);
      console.log('Saved app state to IndexedDB');
    } catch(e) {
      // Fallback: write to localStorage if IndexedDB is unavailable
      saveLocal(state);
    }
  }

  // Called once at startup (DOMContentLoaded) before App.init().
  // Loads _db from IndexedDB; migrates from localStorage if IndexedDB is empty.
  async function initAsync() {
    try {
      const idbState = await AppStateStore.load();
      if (idbState) {
        _db = ensureSourceFolders(Object.assign(defaultDB(), idbState));
        console.log('Loaded app state from IndexedDB');
        return;
      }
    } catch(e) { /* fall through to localStorage migration */ }

    const localState = loadLocal();
    if (localState) {
      _db = localState;
      try {
        await AppStateStore.save(storagePayload(_db));
        localStorage.removeItem(LOCAL_KEY);
        console.log('Migrated legacy localStorage DB');
      } catch(e) {
        // IndexedDB unavailable — localStorage remains as fallback
      }
    } else {
      _db = defaultDB();
    }
  }

  // Awaitable flush — call before page reload to guarantee the write completes.
  async function flushAppState() {
    if (_db) await saveAppState(_db);
  }

  let _db = null;
  function get() {
    // sync fallback if initAsync() wasn't awaited (shouldn't happen in normal flow)
    if (!_db) _db = loadLocal() || defaultDB();
    return ensureSourceFolders(_db);
  }
  function save() {
    if (_db) {
      saveAppState(_db); // async, fire-and-forget — IndexedDB has no quota limit
      if (typeof window.scheduleGoogleDriveSave === 'function') window.scheduleGoogleDriveSave();
      return true;
    }
    return false;
  }

  function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2,7); }

  // ── Source Folders ───────────────────────────────────────────
  function getSourceFolders() { return get().sourceFolders.sort((a,b) => (a.order||0) - (b.order||0)); }
  function getSourceFolder(id) { return get().sourceFolders.find(s => s.id === id) || null; }
  function getDefaultSourceFolderWorkflows(id) {
    const def = DEFAULT_SOURCE_FOLDERS.find(s => s.id === id);
    return Array.isArray(def && def.workflows) ? def.workflows.slice() : [];
  }
  function createSourceFolder(name) {
    const db = get();
    const f = { id: uid(), name, sourceType: 'custom', workflows: [], createdAt: Date.now(), order: db.sourceFolders.length };
    db.sourceFolders.push(f); save(); return f;
  }
  function renameSourceFolder(id, name) { const f = get().sourceFolders.find(f=>f.id===id); if(f){f.name=name;save();} }

  // ── Folders ─────────────────────────────────────────────────
  function getFolders(sourceId) {
    const folders = get().folders.sort((a,b) => (a.order||0) - (b.order||0));
    return sourceId ? folders.filter(f => (f.sourceId || DEFAULT_SOURCE_ID) === sourceId) : folders;
  }
  function createFolder(name, sourceId = DEFAULT_SOURCE_ID) {
    const db = get();
    const sourceFolder = getSourceFolder(sourceId) || getSourceFolder(DEFAULT_SOURCE_ID);
    const f = { id: uid(), name, sourceId: sourceFolder?.id || DEFAULT_SOURCE_ID, createdAt: Date.now(), order: db.folders.length };
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
    db.tests.push(test);
    if (!save()) { db.tests = db.tests.filter(t => t.id !== test.id); return null; }
    return test;
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
  function emptyTrash() {
    const db = get();
    if (window.FigureStore) db.trash.forEach(t => window.FigureStore.deleteByPrefix(t.id + ':').catch(()=>{}));
    db.trash = []; save();
  }
  function permanentDelete(id) {
    const db = get();
    db.trash = db.trash.filter(t => t.id !== id);
    if (window.FigureStore) window.FigureStore.deleteByPrefix(id + ':').catch(()=>{});
    save();
  }

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

  // ── Marks ─────────────────────────────────────────────────────
  function getMarks(folderId) {
    const db = get(); if (!db.marks) db.marks = [];
    if (folderId) { const ids = db.tests.filter(t=>t.folderId===folderId).map(t=>t.id); return db.marks.filter(m=>ids.includes(m.testId)); }
    return [...db.marks];
  }
  function addMark(testId, questionIdx, questionNum) {
    const db = get(); if (!db.marks) db.marks = [];
    if (db.marks.find(m=>m.testId===testId&&m.questionIdx===questionIdx)) return;
    db.marks.push({ id:uid(), testId, questionIdx, questionNum, createdAt:Date.now() }); save();
  }
  function removeMark(testId, questionIdx) {
    const db = get(); if (!db.marks) db.marks = [];
    db.marks = db.marks.filter(m=>!(m.testId===testId&&m.questionIdx===questionIdx)); save();
  }
  function isMarked(testId, questionIdx) { const db = get(); if (!db.marks) return false; return !!db.marks.find(m=>m.testId===testId&&m.questionIdx===questionIdx); }
  function syncMarks(testId, marksSet) {
    const db = get(); if (!db.marks) db.marks = [];
    db.marks = db.marks.filter(m=>m.testId!==testId);
    const test = db.tests.find(t=>t.id===testId);
    if (test) { marksSet.forEach(idx => { const q = test.questions[idx]; if (q) db.marks.push({ id:uid(), testId, questionIdx:idx, questionNum:q.n, createdAt:Date.now() }); }); }
    save();
  }

  // ── Notes ─────────────────────────────────────────────────────
  function getNotes() { const db = get(); if (!db.notes) db.notes = []; return [...db.notes].sort((a,b) => (b.createdAt||0) - (a.createdAt||0)); }
  function addNote(note) { const db = get(); if (!db.notes) db.notes = []; db.notes.push(Object.assign({ id: uid(), createdAt: Date.now() }, note)); save(); }
  function deleteNote(id) { const db = get(); if (!db.notes) db.notes = []; db.notes = db.notes.filter(n => n.id !== id); save(); }

  return { get, save, initAsync, flushAppState, saveAppState, uid,
    getSourceFolders, getSourceFolder, getDefaultSourceFolderWorkflows, createSourceFolder, renameSourceFolder,
    getFolders, createFolder, renameFolder, deleteFolder,
    getTests, getTest, createTest, updateTest, renameTest, trashTest, restoreTest, emptyTrash, permanentDelete,
    saveAttempt, finishAttempt, getHistory, getFlags, addFlag, removeFlag, isFlagged,
    getMarks, addMark, removeMark, isMarked, syncMarks,
    getNotes, addNote, deleteNote };
})();
window.DB = DB;
