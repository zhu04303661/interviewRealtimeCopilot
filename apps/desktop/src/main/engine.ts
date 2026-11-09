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
  log?: (line: string) => void;
}

export class Engine {
  readonly token = randomBytes(32).toString('base64url');
  private child: ChildProcess | null = null;
  private port: Promise<number>;
  private stopping = false;

  constructor(private readonly options: EngineOptions) {
    this.port = this.start();
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
      env: { ...process.env, FRLOCAL_TOKEN: this.token, PATH: `${process.env.HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${process.env.PATH ?? ''}` },
      stdio: ['pipe', 'pipe', 'pipe'],  // the engine exits when stdin closes, i.e. when this app does
    });
    this.child = child;
    createInterface({ input: child.stderr! }).on('line', (line) => log(`[engine] ${line}`));
    return new Promise((resolve, reject) => {
      createInterface({ input: child.stdout! }).on('line', (line) => {
        try {
          const event = JSON.parse(line);
          if (event.event === 'ready' && Number.isInteger(event.port)) resolve(event.port);
        } catch {
          log(`[engine] ${line}`);
        }
      });
      child.once('error', reject);
      child.once('exit', (code) => {
        reject(new Error(`The engine exited (${code}).`));
        if (!this.stopping) {
          log(`[engine] exited with ${code}; restarting`);
          this.port = this.start();
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

  stop(): void {
    this.stopping = true;
    this.child?.kill('SIGTERM');
  }
}
