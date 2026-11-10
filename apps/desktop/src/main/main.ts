// Interview Realtime Copilot — Electron main process.
//
// Owns the local engine, the main window (goals, materials, account) and the
// cockpit window shown during an interview. Renderers reach the engine only
// through the narrow IPC surface in ../preload/preload.ts.
import { app, BrowserWindow, desktopCapturer, dialog, globalShortcut, ipcMain, screen, session, shell, systemPreferences } from 'electron';
import { spawn, type ChildProcess } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { basename, join, resolve } from 'node:path';
import { Engine } from './engine';
import { DEFAULTS, type Settings, SettingsStore, type ShortcutId } from './settings';

// Automated tests: a WAV file stands in for the microphone (no real device).
if (process.env.IRC_FAKE_AUDIO) {
  app.commandLine.appendSwitch('use-fake-device-for-media-stream');
  app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
  app.commandLine.appendSwitch('use-file-for-fake-audio-capture', process.env.IRC_FAKE_AUDIO);
  app.commandLine.appendSwitch('disable-features', 'AudioServiceSandbox');  // lets the audio service read the file
}


const engineDir = process.env.IRC_ENGINE_DIR ?? resolve(__dirname, '../../../../engine');
const dataDir = process.env.IRC_DATA_DIR ?? join(app.getPath('appData'), 'Interview Realtime Copilot');
let engine: Engine;
let mainWindow: BrowserWindow | null = null;
let cockpit: BrowserWindow | null = null;
let current: { sessionId: string; wsUrl: string; topology: string } | null = null;
let settings: SettingsStore;
let systemAudio: ChildProcess | null = null;
let testSystemAudioPath = process.env.IRC_TEST_SYSTEM_AUDIO;  // tests only (IRC_E2E=1)

/** macOS: computer audio comes from our Core Audio tap helper (Electron's loopback is Windows-only). */
const systemAudioHelper = process.env.IRC_SYSTEM_AUDIO_HELPER ?? join(__dirname, '../../native/bin/irc-system-audio');

function startSystemAudio(): boolean {
  stopSystemAudio();
  if (process.platform !== 'darwin' || !existsSync(systemAudioHelper)) return false;
  const child = spawn(systemAudioHelper, [], { stdio: ['pipe', 'pipe', 'pipe'] });
  systemAudio = child;
  let carry = Buffer.alloc(0);
  child.stdout!.on('data', (chunk: Buffer) => {
    carry = Buffer.concat([carry, chunk]);
    while (carry.length >= 3_200) {  // 100 ms of 16 kHz PCM16
      cockpit?.webContents.send('system-audio:frame', new Uint8Array(carry.subarray(0, 3_200)));
      carry = carry.subarray(3_200);
    }
  });
  child.stderr!.on('data', (line: Buffer) => {
    const text = line.toString().trim();
    console.log(`[system-audio] ${text}`);
    if (text.startsWith('error:')) cockpit?.webContents.send('cockpit:command', `error:${text.slice(7)} · 无法采集电脑声音，请在“录屏与系统录音”中允许本应用。`);
  });
  child.on('exit', () => { if (systemAudio === child) systemAudio = null; });
  return true;
}

function stopSystemAudio(): void {
  systemAudio?.stdin?.end();  // the helper exits when stdin closes
  systemAudio = null;
}

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
  // Frameless and transparent: the renderer paints the panel with the configured
  // background opacity, so the meeting behind it shows through.
  cockpit = new BrowserWindow({
    width: 460, height: 760, alwaysOnTop: true, title: 'Copilot', frame: false, transparent: true, hasShadow: true,
    webPreferences: { ...secure, backgroundThrottling: false },
  });
  cockpit.setAlwaysOnTop(true, 'floating');
  void cockpit.loadFile(renderer('cockpit.html'));
  watch(cockpit, 'cockpit');
  cockpit.on('closed', () => { cockpit = null; globalShortcut.unregisterAll(); stopSystemAudio(); });
  applySettings(settings.value);
}

/** Apply device settings to the OS and the open windows. */
function applySettings(value: Settings): void {
  if ((process.platform === 'darwin' || process.platform === 'win32') && app.getLoginItemSettings().openAtLogin !== value.launchAtLogin) {
    app.setLoginItemSettings({ openAtLogin: value.launchAtLogin });
  }
  cockpit?.setContentProtection(value.stealth);
  registerShortcuts(value);
  for (const window of BrowserWindow.getAllWindows()) window.webContents.send('settings:changed', value);
}

/** Session shortcuts: active only while the cockpit is open. */
function registerShortcuts(value: Settings): void {
  globalShortcut.unregisterAll();
  if (!cockpit) return;
  const move = (dx: number, dy: number) => { const [x, y] = cockpit!.getPosition(); cockpit!.setPosition(x + dx, y + dy); };
  const resize = (dw: number) => { const [w, h] = cockpit!.getSize(); cockpit!.setSize(Math.min(900, Math.max(340, w + dw)), h); };
  const actions: Record<ShortcutId, () => void> = {
    toggleResults: () => cockpit?.webContents.send('cockpit:command', 'toggle-results'),
    solveScreen: () => void solveScreen('manual').catch((e) => cockpit?.webContents.send('cockpit:command', `error:${(e as Error).message}`)),
    toggleAssistant: () => (cockpit?.isVisible() ? cockpit.hide() : cockpit?.showInactive()),
    moveUp: () => move(0, -40), moveDown: () => move(0, 40), moveLeft: () => move(-40, 0), moveRight: () => move(40, 0),
    grow: () => resize(40), shrink: () => resize(-40),
  };
  for (const [id, key] of Object.entries(value.shortcuts) as [ShortcutId, string][]) {
    try { globalShortcut.register(key, actions[id]); } catch { console.error(`Shortcut ${key} could not be registered.`); }
  }
}

/** Capture the primary screen (the cockpit itself is excluded under stealth) and have the engine answer it. */
async function solveScreen(origin: 'manual' | 'automatic'): Promise<void> {
  if (!current) throw new Error('No active session.');
  // Automated tests: a fixed image instead of the real screen (never capture a developer's screen).
  if (process.env.IRC_E2E === '1') {
    if (!process.env.IRC_TEST_SCREEN) throw new Error('Screen capture is disabled in tests.');
    const form = new FormData();
    form.append('purpose', 'solve');
    form.append('origin', origin);
    form.append('image', new Blob([new Uint8Array(readFileSync(process.env.IRC_TEST_SCREEN))], { type: 'image/png' }), 'screen.png');
    cockpit?.webContents.send('cockpit:command', 'solving');
    await engine.upload(`/api/v3/sessions/${current.sessionId}/screen`, form);
    return;
  }
  const display = screen.getPrimaryDisplay();
  const size = { width: Math.round(display.size.width * display.scaleFactor), height: Math.round(display.size.height * display.scaleFactor) };
  const [source] = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: size });
  if (!source || source.thumbnail.isEmpty()) throw new Error('Screen capture is not allowed. Allow Screen & System Audio Recording.');
  let image = source.thumbnail.toJPEG(85);
  if (image.length > 9_500_000) image = source.thumbnail.resize({ width: Math.round(size.width / 2) }).toJPEG(80);
  const form = new FormData();
  form.append('purpose', 'solve');
  form.append('origin', origin);
  form.append('image', new Blob([new Uint8Array(image)], { type: 'image/jpeg' }), 'screen.jpg');
  cockpit?.webContents.send('cockpit:command', 'solving');
  await engine.upload(`/api/v3/sessions/${current.sessionId}/screen`, form);
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
  // Automated tests only (IRC_E2E=1): import files without the file dialog.
  ipcMain.handle('test:import-paths', async (_event, kind: 'resume' | 'material', paths: string[]) => {
    if (process.env.IRC_E2E !== '1') throw new Error('Unavailable.');
    return Promise.all(paths.map((filePath) => engine.request('POST', '/local/documents/import', { kind, filePath, filename: basename(filePath) })));
  });
  ipcMain.handle('test:set-system-audio', (_event, path: string) => {
    if (process.env.IRC_E2E !== '1') throw new Error('Unavailable.');
    testSystemAudioPath = path;
  });
  ipcMain.handle('session:start', async (_event, request: { topology: 'general' | 'mock'; goalId: string; documentIds: string[]; language: string;
    codingLanguage?: string | null; playbookId?: string | null; practiceMode?: string }) => {
    const config: Record<string, unknown> = { language: request.language, document_ids: request.documentIds };
    if (request.codingLanguage) config.coding_language = request.codingLanguage;
    if (request.playbookId) config.playbook_id = request.playbookId;
    if (request.practiceMode) config.practice_mode = request.practiceMode;
    const started = await engine.request('POST', '/api/v3/sessions', { topology: request.topology, goal_id: request.goalId, config }) as { session_id: string; ws_url: string };
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
    // Automated tests: a WAV file replaces the computer-audio capture in Live mode.
    const testAudio = process.env.IRC_E2E === '1' && testSystemAudioPath;
    const testSystemAudio = testAudio ? readFileSync(testAudio).toString('base64') : undefined;
    return { ...current, wsUrl: url.toString(), jwt: signedIn?.value?.token ?? '', testSystemAudio };
  });
  ipcMain.handle('session:end', async () => {
    if (current) await engine.request('POST', `/api/v3/sessions/${current.sessionId}/end`, {}).catch(() => undefined);
    current = null;
    cockpit?.close();
  });
  // Session recording: the cockpit records microphone + interviewer audio and hands it over at the end.
  ipcMain.handle('recording:save', async (_event, sessionId: string, bytes: Uint8Array, contentType: string, durationMs: number) => {
    if (!/^[\w-]{8,64}$/.test(sessionId) || !bytes?.length || !/^audio\//.test(contentType)) throw new Error('Invalid recording.');
    const created = await engine.request('POST', `/api/v3/sessions/${sessionId}/recordings`, { kind: 'audio', content_type: contentType }) as { recording_id: string; upload_url: string };
    const path = new URL(created.upload_url).pathname;
    await engine.raw('PUT', path, bytes, { 'Content-Type': contentType, 'Content-Range': `bytes 0-${bytes.length - 1}/${bytes.length}` });
    await engine.request('POST', `/api/v3/sessions/${sessionId}/recordings/${created.recording_id}/complete`, { duration_ms: Math.round(durationMs) });
    return created.recording_id;
  });
  ipcMain.handle('recording:load', async (_event, sessionId: string) => {
    const { recordings } = await engine.request('GET', `/api/v3/sessions/${sessionId}/recordings`) as { recordings: { recording_id: string; content_type: string; duration_ms?: number }[] };
    const latest = recordings.at(-1);
    if (!latest) return null;
    const response = await engine.raw('GET', `/local-recordings/${latest.recording_id}`);
    return { contentType: latest.content_type, durationMs: latest.duration_ms ?? null, data: new Uint8Array(await response.arrayBuffer()) };
  });
  ipcMain.handle('system-audio:start', () => startSystemAudio());
  ipcMain.handle('system-audio:stop', () => stopSystemAudio());
  ipcMain.handle('settings:get', () => settings.value);
  ipcMain.handle('settings:defaults', () => DEFAULTS);
  ipcMain.handle('settings:set', (_event, patch: unknown) => { const value = settings.update(patch); applySettings(value); return value; });
  ipcMain.handle('screen:solve', (_event, origin: 'manual' | 'automatic') => solveScreen(origin === 'automatic' ? 'automatic' : 'manual'));
  ipcMain.handle('app:info', () => ({ version: app.getVersion(), electron: process.versions.electron, platform: process.platform,
    systemAudio: process.platform === 'darwin' ? existsSync(systemAudioHelper) : process.platform === 'win32' }));
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
  engine = new Engine({ engineDir, dataDir, resolveProxy: (url) => session.defaultSession.resolveProxy(url) });
  settings = new SettingsStore(dataDir);
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
app.on('will-quit', () => { stopSystemAudio(); engine?.stop(); });
