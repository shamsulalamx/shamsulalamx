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
    getQueue: () => ipcRenderer.invoke('nbme:batch-import:get-queue'),
    readQueueJobLogs: payload => ipcRenderer.invoke('nbme:batch-import:read-queue-job-logs', payload),
    readReviewDraft: payload => ipcRenderer.invoke('nbme:batch-import:read-review-draft', payload),
    saveReviewDecisions: payload => ipcRenderer.invoke('nbme:batch-import:save-review-decisions', payload),
    writeAcceptedReviewSurvivors: payload => ipcRenderer.invoke('nbme:batch-import:write-accepted-review-survivors', payload),
    openQueueJobArtifacts: payload => ipcRenderer.invoke('nbme:batch-import:open-queue-job-artifacts', payload),
    removeQueueJob: payload => ipcRenderer.invoke('nbme:batch-import:remove-queue-job', payload),
    selectFiles: payload => ipcRenderer.invoke('nbme:batch-import:select-files', payload),
    enqueueJobs: payload => ipcRenderer.invoke('nbme:batch-import:enqueue-jobs', payload),
    launchJob: payload => ipcRenderer.invoke('nbme:batch-import:launch-job', payload),
    cancelJob: payload => ipcRenderer.invoke('nbme:batch-import:cancel-job', payload),
    retryQueueJob: payload => ipcRenderer.invoke('nbme:batch-import:retry-queue-job', payload),
    updateJobReport: payload => ipcRenderer.invoke('nbme:batch-import:update-job-report', payload),
    readOutputJson: outputPath => ipcRenderer.invoke('nbme:batch-import:read-output-json', outputPath),
    onProgress: callback => {
      if (typeof callback !== 'function') return () => {};
      const handler = (_event, payload) => callback(payload);
      ipcRenderer.on('nbme:batch-import:progress', handler);
      return () => ipcRenderer.removeListener('nbme:batch-import:progress', handler);
    },
    onQueueChanged: callback => {
      if (typeof callback !== 'function') return () => {};
      const handler = (_event, payload) => callback(payload);
      ipcRenderer.on('nbme:batch-import:queue-changed', handler);
      return () => ipcRenderer.removeListener('nbme:batch-import:queue-changed', handler);
    }
  })
});

// Preload boundary:
// Exposes readonly desktop-mode detection and a narrow AI status method.
// Future local helpers should be narrow methods only:
// app-data path lookup, open debug folder, save debug export, and native file dialogs.
// Do not expose direct filesystem access, raw IPC wrappers, broad Node APIs, or API keys.
contextBridge.exposeInMainWorld('nbmeDesktop', desktopInfo);
