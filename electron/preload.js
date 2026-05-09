const { contextBridge } = require('electron');

const desktopInfo = Object.freeze({
  isElectron: true
});

// Preload boundary:
// Exposes only readonly desktop-mode detection for now.
// Future local helpers should be narrow methods only:
// app-data path lookup, open debug folder, save debug export, and native file dialogs.
// Do not expose direct filesystem access, raw IPC wrappers, or broad Node APIs.
contextBridge.exposeInMainWorld('nbmeDesktop', desktopInfo);
