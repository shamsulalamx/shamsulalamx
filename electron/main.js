const { app, BrowserWindow } = require('electron');
const path = require('path');

const DEFAULT_DEV_URL = 'http://localhost:8888';
const devUrl = process.env.NBME_ELECTRON_URL || DEFAULT_DEV_URL;

// Main process boundary:
// Owns Electron window lifecycle and loading the existing HTTP-served app only.
// App logic, parser/OCR/render behavior, Gemini, Drive, and storage remain in index.html.
function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 1100,
    minHeight: 700,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false
    }
  });

  win.once('ready-to-show', () => {
    win.show();
  });

  win.loadURL(devUrl);
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
