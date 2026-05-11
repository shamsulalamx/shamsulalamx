const { contextBridge, ipcRenderer } = require('electron');

const desktopInfo = Object.freeze({
  isElectron: true,
  ai: Object.freeze({
    getStatus:         ()      => ipcRenderer.invoke('nbme:ai:get-status'),
    refineUWorldDraft: payload => ipcRenderer.invoke('nbme:ai:refine-uworld-draft', payload),
    refineDivineDraft: payload => ipcRenderer.invoke('nbme:ai:refine-divine-draft',  payload)
  })
});

// Preload boundary:
// Exposes readonly desktop-mode detection and a narrow AI status method.
// Future local helpers should be narrow methods only:
// app-data path lookup, open debug folder, save debug export, and native file dialogs.
// Do not expose direct filesystem access, raw IPC wrappers, broad Node APIs, or API keys.
contextBridge.exposeInMainWorld('nbmeDesktop', desktopInfo);
