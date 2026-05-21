const { contextBridge, ipcRenderer } = require('electron');

const desktopInfo = Object.freeze({
  isElectron: true,
  ai: Object.freeze({
    getStatus:         ()      => ipcRenderer.invoke('nbme:ai:get-status'),
    refineUWorldDraft: payload => ipcRenderer.invoke('nbme:ai:refine-uworld-draft', payload),
    refineDivineDraft: payload => ipcRenderer.invoke('nbme:ai:refine-divine-draft',  payload)
  }),
  batchImport: Object.freeze({
    getRegistry: () => ipcRenderer.invoke('nbme:batch-import:get-registry'),
    getHistory: () => ipcRenderer.invoke('nbme:batch-import:get-history'),
    selectFiles: payload => ipcRenderer.invoke('nbme:batch-import:select-files', payload),
    launchJob: payload => ipcRenderer.invoke('nbme:batch-import:launch-job', payload),
    cancelJob: payload => ipcRenderer.invoke('nbme:batch-import:cancel-job', payload),
    updateJobReport: payload => ipcRenderer.invoke('nbme:batch-import:update-job-report', payload),
    readOutputJson: outputPath => ipcRenderer.invoke('nbme:batch-import:read-output-json', outputPath),
    onProgress: callback => {
      if (typeof callback !== 'function') return () => {};
      const handler = (_event, payload) => callback(payload);
      ipcRenderer.on('nbme:batch-import:progress', handler);
      return () => ipcRenderer.removeListener('nbme:batch-import:progress', handler);
    }
  })
});

// Preload boundary:
// Exposes readonly desktop-mode detection and a narrow AI status method.
// Future local helpers should be narrow methods only:
// app-data path lookup, open debug folder, save debug export, and native file dialogs.
// Do not expose direct filesystem access, raw IPC wrappers, broad Node APIs, or API keys.
contextBridge.exposeInMainWorld('nbmeDesktop', desktopInfo);
