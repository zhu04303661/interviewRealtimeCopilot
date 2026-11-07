// Electron-side bridge to the Python backend (launch/backend, package `frlocal`).
//
// The Electron main process starts `python -m frlocal serve` on a free loopback
// port, waits for its `{"event":"ready","port":N}` line and then:
//   * forwards the app's vendor API requests (fetch) to it,
//   * imports picked files by path (no copies through memory),
//   * opens the realtime interview WebSocket for the original RealtimeBackend,
//   * calls the local account endpoints for the sign-in dialog.
// Every request carries a random bearer token generated here, so no other local
// program can use the backend. The child exits when its stdin closes, i.e. when
// this app quits or crashes; unexpected exits are restarted with backoff.
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import undici from './vendor/undici/index.js';

const PUBLIC_ORIGIN = 'https://final-round-recovered.invalid';
const READY_TIMEOUT_MS = 30_000;
const RESTART_DELAYS_MS = [500, 1_000, 2_000, 5_000, 10_000];
const PROXY_REFRESH_MS = 60_000;

/** Turn an Electron/PAC proxy rule list ("PROXY host:port; DIRECT") into a URL or null. */
export function proxyUrlFromRules(rules) {
  const rule = String(rules).split(';').map((value) => value.trim())
    .find((value) => /^(DIRECT$|(?:PROXY|HTTP|HTTPS|SOCKS5|SOCKS)\s+\S+$)/i.test(value));
  if (!rule || /^DIRECT$/i.test(rule)) return null;
  const [kind, address] = rule.split(/\s+/);
  const scheme = { PROXY: 'http', HTTP: 'http', HTTPS: 'https', SOCKS5: 'socks5', SOCKS: 'socks5' }[kind.toUpperCase()];
  return new URL(`${scheme}://${address}`).href.replace(/\/$/, '');
}

/** Where the Python project lives: next to the app bundle, or FRLOCAL_BACKEND_DIR. */
export function backendDirectory() {
  return process.env.FRLOCAL_BACKEND_DIR || resolve(process.resourcesPath, '../../..', 'backend');
}

export function startPythonBackend({ app, session, accountsDir, workspaceDir, legacyWorkspaceDir, log = console }) {
  const token = randomBytes(32).toString('base64url');
  const directory = backendDirectory();
  const python = join(directory, '.venv', 'bin', 'python');
  let child = null;
  let base = null;
  let ready = null;
  let stopping = false;
  let restarts = 0;
  let proxy = null;

  async function currentProxy() {
    try {
      return proxyUrlFromRules(await session.defaultSession.resolveProxy('https://api.openai.com'));
    } catch {
      return null;
    }
  }

  function launch() {
    ready = new Promise((resolveReady, rejectReady) => {
      if (!existsSync(python)) {
        rejectReady(Error(`The Python backend is not installed. Run "uv sync" in ${directory}.`));
        return;
      }
      const env = { ...process.env, FRLOCAL_TOKEN: token, PYTHONUNBUFFERED: '1' };
      delete env.ELECTRON_RUN_AS_NODE;
      if (proxy) env.FRLOCAL_OPENAI_PROXY = proxy;
      const args = ['-m', 'frlocal', 'serve', '--accounts', accountsDir, '--workspace', workspaceDir];
      if (legacyWorkspaceDir) args.push('--legacy-workspace', legacyWorkspaceDir);
      const started = spawn(python, args, {
        cwd: directory, env, stdio: ['pipe', 'pipe', 'pipe'],
      });
      child = started;
      const timer = setTimeout(() => rejectReady(Error('The Python backend did not start in time.')), READY_TIMEOUT_MS);
      let buffered = '';
      started.stdout.setEncoding('utf8');
      started.stdout.on('data', (chunk) => {
        buffered += chunk;
        let newline;
        while ((newline = buffered.indexOf('\n')) >= 0) {
          const line = buffered.slice(0, newline).trim();
          buffered = buffered.slice(newline + 1);
          try {
            const message = JSON.parse(line);
            if (message.event === 'ready' && Number.isInteger(message.port)) {
              clearTimeout(timer);
              base = `http://127.0.0.1:${message.port}`;
              restarts = 0;
              resolveReady(base);
            }
          } catch {
            log.info('[frlocal]', line);
          }
        }
      });
      started.stderr.setEncoding('utf8');
      started.stderr.on('data', (chunk) => {
        for (const line of chunk.split('\n')) if (line.trim()) log.info(line);
      });
      started.on('error', (error) => {
        clearTimeout(timer);
        rejectReady(error);
      });
      started.on('exit', (code, signal) => {
        clearTimeout(timer);
        if (child === started) child = null;
        base = null;
        rejectReady(Error(`The Python backend exited (${signal ?? code}).`));
        if (stopping) return;
        const delay = RESTART_DELAYS_MS[Math.min(restarts++, RESTART_DELAYS_MS.length - 1)];
        log.warn(`[frlocal] backend exited (${signal ?? code}); restarting in ${delay} ms`);
        setTimeout(() => { if (!stopping) launch(); }, delay).unref();
      });
    });
    ready.catch((error) => log.error('[frlocal]', error.message));
  }

  async function origin() {
    if (base) return base;
    return ready;
  }

  const headers = (extra = {}) => ({ ...extra, Authorization: `Bearer ${token}` });

  async function call(method, path, body) {
    const response = await fetch(await origin() + path, {
      method, headers: headers(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return response.json();
  }

  /** Forward one app request for PUBLIC_ORIGIN to the backend, streaming the body both ways. */
  async function forward(request) {
    const url = new URL(request.url);
    if (url.origin !== PUBLIC_ORIGIN) {
      return Response.json({ detail: 'This endpoint is outside the local workspace.' }, { status: 403 });
    }
    let target;
    try {
      target = await origin() + url.pathname + url.search;
    } catch (error) {
      return Response.json({ detail: error.message }, { status: 503 });
    }
    const forwardedHeaders = new Headers(request.headers);
    forwardedHeaders.set('Authorization', `Bearer ${token}`);
    const hasBody = !['GET', 'HEAD'].includes(request.method);
    return fetch(target, {
      method: request.method, headers: forwardedHeaders, signal: request.signal, redirect: 'manual',
      ...(hasBody ? { body: request.body, duplex: 'half' } : {}),
    });
  }

  async function importDocument({ kind, filePath, filename, contentType }) {
    const result = await call('POST', '/local/documents/import', { kind, filePath, filename, contentType });
    if (result?.detail) throw Error(result.detail);
    return result;
  }

  /** WebSocket factory for the original RealtimeBackend (it sets on* handlers itself). */
  function openSocket(url) {
    if (!base || !url.startsWith(base.replace(/^http/, 'ws') + '/realtime/')) {
      throw Error('The local realtime address is unavailable.');
    }
    return new undici.WebSocket(url, { headers: { Authorization: `Bearer ${token}` } });
  }

  async function refreshProxy() {
    const next = await currentProxy();
    if (next === proxy) return;
    proxy = next;
    if (base) await call('POST', '/local/network', { proxy }).catch(() => {});
  }

  function stop() {
    stopping = true;
    const running = child;
    if (!running) return;
    running.stdin.end();
    running.kill('SIGTERM');
    setTimeout(() => { if (running.exitCode === null) running.kill('SIGKILL'); }, 3_000).unref();
  }

  // Requests made before the first launch wait on this promise.
  ready = currentProxy().then((value) => {
    proxy = value;
    launch();
    return ready;
  });
  setInterval(() => void refreshProxy(), PROXY_REFRESH_MS).unref();
  app.on('will-quit', stop);

  return { call, fetch: forward, importDocument, openSocket, stop, ready: () => origin() };
}
