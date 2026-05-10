const { contextBridge, ipcRenderer } = require('electron');

const desktopInfo = Object.freeze({
  isElectron: true,
  ai: Object.freeze({
    getStatus: () => ipcRenderer.invoke('nbme:ai:get-status')
  })
});

// Preload boundary:
// Exposes readonly desktop-mode detection and a narrow AI status method.
// Future local helpers should be narrow methods only:
// app-data path lookup, open debug folder, save debug export, and native file dialogs.
// Do not expose direct filesystem access, raw IPC wrappers, broad Node APIs, or API keys.
contextBridge.exposeInMainWorld('nbmeDesktop', desktopInfo);
