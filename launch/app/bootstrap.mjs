import { app } from 'electron';
import { appendFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';

const profile = resolve(process.resourcesPath, '../../..', 'profile');
const logPath = join(profile, 'launch-events.jsonl');
function record(event, properties = {}) {
  appendFileSync(logPath, JSON.stringify({
    time: new Date().toISOString(), pid: process.pid, event, ...properties,
  }) + '\n');
}
mkdirSync(profile, { recursive: true });
for (const [name, path] of [
  ['userData', profile],
  ['sessionData', join(profile, 'chromium')],
  ['logs', join(profile, 'logs')],
]) {
  mkdirSync(path, { recursive: true });
  app.setPath(name, path);
}
record('recovered-entry', { archive: app.getAppPath() });
app.on('browser-window-created', (_, window) => {
  record('browser-window-created', { id: window.id });
  window.webContents.on('did-finish-load', () => {
    const url = new URL(window.webContents.getURL());
    record('renderer-loaded', { id: window.id, source: url.protocol === 'file:' ? url.pathname : url.origin });
  });
  window.on('show', () => record('window-shown', { id: window.id }));
  window.webContents.on('render-process-gone', (_, { reason, exitCode }) => {
    record('renderer-exited', { id: window.id, reason, exitCode });
  });
});
try {
  await import('./out/main/index.mjs');
  record('main-imported');
} catch (error) {
  record('main-import-error', { error: String(error?.stack ?? error) });
  throw error;
}
