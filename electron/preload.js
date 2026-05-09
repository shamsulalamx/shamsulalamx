const { contextBridge } = require('electron');

const desktopInfo = Object.freeze({
  isElectron: true
});

// Preload boundary:
// Exposes only readonly desktop-mode detection for now.
// Future filesystem, app-data, debug export, or native dialog helpers should use narrow bridges here.
contextBridge.exposeInMainWorld('nbmeDesktop', desktopInfo);
