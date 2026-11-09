// Interview Realtime Copilot — Electron main process.
//
// Owns the local engine, the main window (goals, materials, account) and the
// cockpit window shown during an interview. Renderers reach the engine only
// through the narrow IPC surface in ../preload/preload.ts.
import { app, BrowserWindow, desktopCapturer, dialog, ipcMain, session, shell, systemPreferences } from 'electron';
import { basename, join, resolve } from 'node:path';
import { Engine } from './engine';

// Automated tests: a WAV file stands in for the microphone (no real device).
if (process.env.IRC_FAKE_AUDIO) {
  app.commandLine.appendSwitch('use-fake-device-for-media-stream');
  app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
  app.commandLine.appendSwitch('use-file-for-fake-audio-capture', process.env.IRC_FAKE_AUDIO);
  app.commandLine.appendSwitch('disable-features', 'AudioServiceSandbox');  // lets the audio service read the file
}

// macOS system-audio loopback for getDisplayMedia (ScreenCaptureKit).
app.commandLine.appendSwitch('enable-features', 'MacLoopbackAudioForScreenShare,MacSckSystemAudioLoopbackOverride');

const engineDir = process.env.IRC_ENGINE_DIR ?? resolve(__dirname, '../../../../engine');
const dataDir = process.env.IRC_DATA_DIR ?? join(app.getPath('appData'), 'Interview Realtime Copilot');
let engine: Engine;
let mainWindow: BrowserWindow | null = null;
let cockpit: BrowserWindow | null = null;
let current: { sessionId: string; wsUrl: string; topology: string } | null = null;

const renderer = (page: string) => join(__dirname, '../renderer', page);
const preload = join(__dirname, '../preload/preload.js');
const secure = { preload, contextIsolation: true, nodeIntegration: false, sandbox: true } as const;

/** Log renderer crashes and console errors (the only trace of renderer failures). */
function watch(window: BrowserWindow, name: string): void {
  window.webContents.on('render-process-gone', (_event, details) => console.error(`[${name}] renderer gone: ${details.reason} (${details.exitCode})`));
  window.webContents.on('console-message', (event) => {
    if (event.level === 'error' || event.level === 'warning') console.error(`[${name}] ${event.message}`);
  });
}

function openMainWindow(): void {
  mainWindow = new BrowserWindow({ width: 1100, height: 760, title: 'Interview Realtime Copilot', webPreferences: secure });
  void mainWindow.loadFile(renderer('index.html'));
  watch(mainWindow, 'main');
  mainWindow.on('closed', () => { mainWindow = null; });
}

function openCockpit(): void {
  cockpit?.close();
  cockpit = new BrowserWindow({
    width: 460, height: 760, alwaysOnTop: true, title: 'Copilot', backgroundColor: '#111316',
    webPreferences: { ...secure, backgroundThrottling: false },
  });
  void cockpit.loadFile(renderer('cockpit.html'));
  watch(cockpit, 'cockpit');
  cockpit.on('closed', () => { cockpit = null; });
}

/** Typed IPC handlers: every renderer call goes through one of these. */
function registerIpc(): void {
  ipcMain.handle('engine:request', (_event, method: string, path: string, body?: unknown) => {
    if (!/^\/(api\/v3|local\/auth)\//.test(path)) throw new Error('Unsupported engine path.');
    return engine.request(method, path, body);
  });
  ipcMain.handle('documents:pick-and-import', async (_event, kind: 'resume' | 'material') => {
    const picked = await dialog.showOpenDialog({ properties: ['openFile', 'multiSelections'], filters: [{ name: 'Documents', extensions: ['pdf', 'docx', 'txt', 'md'] }] });
    const imported = [];
    for (const filePath of picked.filePaths) {
      imported.push(await engine.request('POST', '/local/documents/import', { kind, filePath, filename: basename(filePath) }));
    }
    return imported;
  });
  ipcMain.handle('session:start', async (_event, request: { topology: 'general' | 'mock'; goalId: string; documentIds: string[]; language: string }) => {
    const started = await engine.request('POST', '/api/v3/sessions', {
      topology: request.topology, goal_id: request.goalId, config: { language: request.language, document_ids: request.documentIds },
    }) as { session_id: string; ws_url: string };
    current = { sessionId: started.session_id, wsUrl: started.ws_url, topology: request.topology };
    openCockpit();
    return current;
  });
  ipcMain.handle('session:current', async () => {
    if (!current) return null;
    const signedIn = await engine.request('GET', '/local/auth/session?owner=main') as { value?: { token: string } } | null;
    const url = new URL(current.wsUrl, await engine.baseUrl());
    url.protocol = 'ws:';
    url.searchParams.set('token', engine.token);
    return { ...current, wsUrl: url.toString(), jwt: signedIn?.value?.token ?? '' };
  });
  ipcMain.handle('session:end', async () => {
    if (current) await engine.request('POST', `/api/v3/sessions/${current.sessionId}/end`, {}).catch(() => undefined);
    current = null;
    cockpit?.close();
  });
  ipcMain.handle('permissions:status', () => ({
    microphone: systemPreferences.getMediaAccessStatus('microphone'),
    screen: process.platform === 'darwin' ? systemPreferences.getMediaAccessStatus('screen') : 'granted',
  }));
  ipcMain.handle('permissions:request-microphone', () =>
    process.platform === 'darwin' ? systemPreferences.askForMediaAccess('microphone') : true);
  ipcMain.handle('permissions:open-screen-settings', () =>
    shell.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'));
}

app.whenReady().then(() => {
  engine = new Engine({ engineDir, dataDir });
  // getDisplayMedia from the cockpit gets the primary screen with system audio
  // (loopback); the video track is discarded by the renderer.
  session.defaultSession.setDisplayMediaRequestHandler((_request, callback) => {
    void desktopCapturer.getSources({ types: ['screen'] }).then((sources) => callback({ video: sources[0], audio: 'loopback' }));
  });
  if (process.env.IRC_DENY_MEDIA === '1') {
    // Automated tests: never open the real microphone or computer audio.
    session.defaultSession.setPermissionCheckHandler((_wc, permission) => permission !== 'media');
    session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => callback(permission !== 'media'));
  }
  registerIpc();
  openMainWindow();
  app.on('activate', () => { if (!mainWindow) openMainWindow(); });
});

app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('will-quit', () => engine?.stop());
