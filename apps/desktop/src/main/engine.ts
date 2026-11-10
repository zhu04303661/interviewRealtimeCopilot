// Starts the local Python engine (../../engine) and talks to it over HTTP.
//
// The engine listens on a random loopback port and only accepts requests that
// carry the random token generated here, so other local programs cannot use it.
// It prints {"event": "ready", "port": N} on stdout once it accepts connections.
import { spawn, type ChildProcess } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

export interface EngineOptions {
  engineDir: string;
  dataDir: string;
  /** Electron's proxy resolution for a URL (handles PAC files and system settings). */
  resolveProxy?: (url: string) => Promise<string>;
  log?: (line: string) => void;
}

const RESTART_DELAYS_MS = [500, 1_000, 2_000, 5_000, 10_000];
const PROXY_REFRESH_MS = 60_000;

/** Turn an Electron/PAC proxy rule list ("PROXY host:port; DIRECT") into a URL, or null for a direct connection. */
export function proxyUrlFromRules(rules: string): string | null {
  const rule = rules.split(';').map((value) => value.trim())
    .find((value) => /^(DIRECT$|(?:PROXY|HTTP|HTTPS|SOCKS5|SOCKS)\s+\S+$)/i.test(value));
  if (!rule || /^DIRECT$/i.test(rule)) return null;
  const [kind, address] = rule.split(/\s+/);
  const scheme = ({ PROXY: 'http', HTTP: 'http', HTTPS: 'https', SOCKS5: 'socks5', SOCKS: 'socks5' } as Record<string, string>)[kind.toUpperCase()];
  return new URL(`${scheme}://${address}`).href.replace(/\/$/, '');
}

export class Engine {
  readonly token = randomBytes(32).toString('base64url');
  private child: ChildProcess | null = null;
  private port: Promise<number>;
  private stopping = false;
  private restarts = 0;
  private proxy: string | null = null;

  constructor(private readonly options: EngineOptions) {
    this.port = this.currentProxy().then((proxy) => { this.proxy = proxy; return this.start(); });
    // Proxy settings can change while the app runs (VPN on/off): keep the engine in step.
    setInterval(() => void this.refreshProxy(), PROXY_REFRESH_MS).unref();
  }

  private async currentProxy(): Promise<string | null> {
    try {
      return this.options.resolveProxy ? proxyUrlFromRules(await this.options.resolveProxy('https://api.openai.com')) : null;
    } catch {
      return null;
    }
  }

  private async refreshProxy(): Promise<void> {
    const next = await this.currentProxy();
    if (next === this.proxy) return;
    this.proxy = next;
    await this.request('POST', '/local/network', { proxy: next }).catch(() => undefined);
  }

  private start(): Promise<number> {
    const { engineDir, dataDir, log = console.log } = this.options;
    const accounts = join(dataDir, 'accounts');
    const workspace = join(dataDir, 'workspace');
    mkdirSync(accounts, { recursive: true, mode: 0o700 });
    mkdirSync(workspace, { recursive: true, mode: 0o700 });
    const uv = process.env.IRC_UV ?? 'uv';
    const child = spawn(uv, ['run', '--project', engineDir, 'python', '-m', 'frlocal', 'serve', '--accounts', accounts, '--workspace', workspace], {
      cwd: engineDir,
      env: { ...process.env, FRLOCAL_TOKEN: this.token, ...(this.proxy ? { FRLOCAL_OPENAI_PROXY: this.proxy } : {}), PATH: `${process.env.HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${process.env.PATH ?? ''}` },
      stdio: ['pipe', 'pipe', 'pipe'],  // the engine exits when stdin closes, i.e. when this app does
    });
    this.child = child;
    createInterface({ input: child.stderr! }).on('line', (line) => log(`[engine] ${line}`));
    return new Promise((resolve, reject) => {
      createInterface({ input: child.stdout! }).on('line', (line) => {
        try {
          const event = JSON.parse(line);
          if (event.event === 'ready' && Number.isInteger(event.port)) { this.restarts = 0; resolve(event.port); }
        } catch {
          log(`[engine] ${line}`);
        }
      });
      child.once('error', reject);
      child.once('exit', (code) => {
        reject(new Error(`The engine exited (${code}).`));
        if (!this.stopping) {
          const delay = RESTART_DELAYS_MS[Math.min(this.restarts++, RESTART_DELAYS_MS.length - 1)];
          log(`[engine] exited with ${code}; restarting in ${delay} ms`);
          this.port = new Promise((r) => setTimeout(r, delay)).then(() => this.start());
        }
      });
    });
  }

  async baseUrl(): Promise<string> {
    return `http://127.0.0.1:${await this.port}`;
  }

  /** One JSON request to the engine; resolves with the parsed body. */
  async request(method: string, path: string, body?: unknown): Promise<unknown> {
    const response = await fetch(`${await this.baseUrl()}${path}`, {
      method,
      headers: { Authorization: `Bearer ${this.token}`, ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await response.text();
    const value = text ? JSON.parse(text) : null;
    if (!response.ok) throw new Error(value?.detail ?? value?.error ?? `Request failed (${response.status}).`);
    return value;
  }

  /** A multipart upload (e.g. a screenshot) to the engine. */
  async upload(path: string, form: FormData): Promise<unknown> {
    const response = await fetch(`${await this.baseUrl()}${path}`, { method: 'POST', headers: { Authorization: `Bearer ${this.token}` }, body: form });
    const value = await response.json().catch(() => null);
    if (!response.ok) throw new Error(value?.detail ?? `Upload failed (${response.status}).`);
    return value;
  }

  stop(): void {
    this.stopping = true;
    this.child?.kill('SIGTERM');
  }
}
