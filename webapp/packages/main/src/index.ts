import {app, Menu, Tray, BrowserWindow, ipcMain, globalShortcut, Notification, nativeImage} from 'electron';
import {URL} from 'url';
import {PyShell} from '/@/pyshell';
import {webuiArgs, webuiPath, dpiScaling, autoStart} from '/@/config';

const path = require('path');

const isSingleInstance = app.requestSingleInstanceLock();

if (!isSingleInstance) {
  app.quit();
  process.exit(0);
}

app.disableHardwareAcceleration();
// Needed on Windows so tray status notifications show "Alas", not "Electron".
app.setAppUserModelId('Alas');

// Install "Vue.js devtools"
if (import.meta.env.MODE === 'development') {
  app.whenReady()
    .then(() => import('electron-devtools-installer'))
    .then(({default: installExtension, VUEJS3_DEVTOOLS}) => installExtension(VUEJS3_DEVTOOLS, {
      loadExtensionOptions: {
        allowFileAccess: true,
      },
    }))
    .catch(e => console.error('Failed install extension:', e));
}

/**
 * Load deploy settings and start Alas web server.
 */
const alas = new PyShell(webuiPath, webuiArgs);
alas.end(function () {
  // if (err) throw err;
});


let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;

// Window state tracking for shrink functionality
let isShrunk = false;
let positionToRestore: { x: number; y: number } | null = null;
let shrinkPosition: { x: number; y: number } | null = null;
let originalSize: { width: number; height: number } | null = null;

// Tray status indicator: module/webui/app.py pushes a status line over stdout
// (the same pipe PyShell already reads to detect webui startup) whenever a config's
// ProcessManager state changes (1 running, 2 stopped, 3 error, 4 updating) - no
// REST API and no polling, so the tray only does work when something actually changed.
const GUI_STATUS_PREFIX = 'ALAS_GUI_STATUS::';

interface GuiStatusEntry {
  state: number;
  reason?: string;
}

type GuiStatus = Record<string, GuiStatusEntry>;

// Tracks whether each config was already in error last update, so a notification
// only fires once per new crash, not repeatedly while it stays crashed.
const previousErrorState: Record<string, boolean> = {};

function stateLabel(state: number): string {
  switch (state) {
    case 1:
      return 'Running';
    case 2:
      return 'Stopped';
    case 3:
      return 'Error';
    case 4:
      return 'Updating';
    default:
      return 'Unknown';
  }
}

function updateTrayStatus(status: GuiStatus) {
  if (!tray) return;
  const entries = Object.entries(status);

  let level: 'green' | 'gray' | 'red' = 'gray';
  if (entries.some(([, e]) => e.state === 3)) {
    level = 'red';
  } else if (entries.some(([, e]) => e.state === 1)) {
    level = 'green';
  }
  // Multi-resolution .ico (like buildResources/icon.ico for the window/taskbar icon):
  // Windows reads the exact pixel size it needs natively instead of scaling one bitmap.
  tray.setImage(nativeImage.createFromPath(path.join(__dirname, `icon-${level}.ico`)));

  const tooltip = entries.length
    ? 'Alas\n' + entries.map(([name, e]) => `${name}: ${stateLabel(e.state)}`).join('\n')
    : 'Alas';
  tray.setToolTip(tooltip);

  for (const [name, e] of entries) {
    const isError = e.state === 3;
    if (isError && !previousErrorState[name]) {
      new Notification({
        title: `Alas <${name}> stopped with an error`,
        body: e.reason || 'Check the logs for details.',
      }).show();
    }
    previousErrorState[name] = isError;
  }
}

const createWindow = async () => {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 880,
    show: false, // Use 'ready-to-show' event to show window
    frame: false,
    icon: path.join(__dirname, './buildResources/icon.ico'),
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,   // Spectron tests can't work with contextIsolation: true
      nativeWindowOpen: true,
      // preload: join(__dirname, '../../preload/dist/index.cjs'),
    },
  });

  /**
   * If you install `show: true` then it can cause issues when trying to close the window.
   * Use `show: false` and listener events `ready-to-show` to fix these issues.
   *
   * @see https://github.com/electron/electron/issues/25012
   */
  mainWindow.on('ready-to-show', () => {
    // Webui.Run auto-starts configs on launch; start minimized to tray instead
    // of popping the window up every time. Use the tray icon to show it.
    if (!autoStart) {
      mainWindow?.show();
    }

    // Hide menu
    const {Menu} = require('electron');
    Menu.setApplicationMenu(null);

    if (import.meta.env.MODE === 'development') {
      mainWindow?.webContents.openDevTools();
    }
  });

  mainWindow.on('focus', function () {
    // Dev tools
    globalShortcut.register('Ctrl+Shift+I', function () {
      if (mainWindow?.webContents.isDevToolsOpened()) {
        mainWindow?.webContents.closeDevTools();
      } else {
        mainWindow?.webContents.openDevTools();
      }
    });
    // Refresh
    globalShortcut.register('Ctrl+R', function () {
      mainWindow?.reload();
    });
    globalShortcut.register('Ctrl+Shift+R', function () {
      mainWindow?.reload();
    });
  });
  mainWindow.on('blur', function () {
    globalShortcut.unregisterAll();
  });

  // Minimize, maximize, close window.
  ipcMain.on('window-tray', function () {
    mainWindow?.hide();
  });
  ipcMain.on('window-min', function () {
    mainWindow?.minimize();
  });
  ipcMain.on('window-max', function () {
    mainWindow?.isMaximized() ? mainWindow?.restore() : mainWindow?.maximize();
  });
  ipcMain.on('window-close', function () {
    alas.kill(function () {
      mainWindow?.close();
    });
  });
  ipcMain.on('window-shrink', function () {
    if (!mainWindow) return;

    if (isShrunk) {
      // Unshrinking: restore to previous unshrunk state and save current shrink position
      const [currentX, currentY] = mainWindow.getPosition();
      shrinkPosition = { x: currentX, y: currentY };

      if (originalSize) {
        mainWindow.setSize(originalSize.width, originalSize.height);
        originalSize = null;
      }
      if (positionToRestore) {
        mainWindow.setPosition(positionToRestore.x, positionToRestore.y);
        // Keep positionToRestore for next shrink cycle
      }

      isShrunk = false;
      mainWindow.setAlwaysOnTop(false);
      mainWindow?.webContents.send('window-shrink-state', false);
    } else {
      // Shrinking: save current position first, then use saved shrink position if available
      const [originalWidth, originalHeight] = mainWindow.getSize();
      originalSize = { width: originalWidth, height: originalHeight };

      const [originalX, originalY] = mainWindow.getPosition();
      positionToRestore = { x: originalX, y: originalY };

      if (shrinkPosition) {
        mainWindow.setPosition(shrinkPosition.x, shrinkPosition.y);
        shrinkPosition = null;
      }

      isShrunk = true;
      mainWindow.setSize(350, 51);
      mainWindow.setAlwaysOnTop(true);
      mainWindow?.webContents.send('window-shrink-state', true);
    }
  });
  // Tray
  tray = new Tray(nativeImage.createFromPath(path.join(__dirname, 'icon-gray.ico')));
  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show',
      click: function () {
        mainWindow?.show();
      },
    },
    {
      label: 'Hide',
      click: function () {
        mainWindow?.hide();
      },
    },
    {
      label: 'Exit',
      click: function () {
        alas.kill(function () {
          mainWindow?.close();
        });
      },
    },
  ]);
  tray.setToolTip('Alas');
  tray.setContextMenu(contextMenu);
  tray.on('click', () => {
    mainWindow?.isVisible() ? mainWindow?.hide() : mainWindow?.show();
  });
  tray.on('right-click', () => {
    tray?.popUpContextMenu(contextMenu);
  });

};


// No DPI scaling
if (!dpiScaling) {
  app.commandLine.appendSwitch('high-dpi-support', '1');
  app.commandLine.appendSwitch('force-device-scale-factor', '1');
}


function loadURL() {
  /**
   * URL for main window.
   * Vite dev server for development.
   * `file://../renderer/index.html` for production and test
   */
  const pageUrl = import.meta.env.MODE === 'development' && import.meta.env.VITE_DEV_SERVER_URL !== undefined
    ? import.meta.env.VITE_DEV_SERVER_URL
    : new URL('../renderer/dist/index.html', 'file://' + __dirname).toString();

  mainWindow?.loadURL(pageUrl);
}


alas.on('stderr', function (message: string) {
  /**
   * Receive logs, judge if Alas is ready
   * For starlette backend, there will have:
   * `INFO:     Uvicorn running on http://0.0.0.0:22267 (Press CTRL+C to quit)`
   * Or backend has started already
   * `[Errno 10048] error while attempting to bind on address ('0.0.0.0', 22267): `
   */
  if (message.includes('Application startup complete') || message.includes('bind on address')) {
    alas.removeAllListeners('stderr');
    loadURL();
  }
});


alas.on('message', function (message: string) {
  // module/webui/app.py's push_gui_status() prints this line only when a config's
  // state actually changes, so this fires on real transitions, not on a timer.
  if (typeof message === 'string' && message.startsWith(GUI_STATUS_PREFIX)) {
    try {
      const status: GuiStatus = JSON.parse(message.slice(GUI_STATUS_PREFIX.length));
      updateTrayStatus(status);
    } catch (e) {
      console.error('Failed to parse gui status:', e);
    }
  }
});


app.on('second-instance', () => {
  // Someone tried to run a second instance, we should focus our window.
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    if (!mainWindow.isVisible()) mainWindow.show();
    mainWindow.focus();
  }
});


app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});


app.whenReady()
  .then(createWindow)
  .catch((e) => console.error('Failed create window:', e));


// Auto-updates
if (import.meta.env.PROD) {
  app.whenReady()
    .then(() => import('electron-updater'))
    .then(({autoUpdater}) => autoUpdater.checkForUpdatesAndNotify())
    .catch((e) => console.error('Failed check updates:', e));
}

