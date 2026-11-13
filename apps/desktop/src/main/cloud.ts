// Cloud account: sign-in/registration against the website, subscription and usage, and the provider file the engine reads.
//
// <data>/cloud.json     — email, device token and the generated local workspace credentials (owner-only)
// <data>/provider.env   — OPENAI_API_KEY=<device token> + FRLOCAL_OPENAI_BASE=<cloud relay>, written while signed in
// <data>/openai.env     — the user's own OpenAI key (Settings); searched first, so it bypasses the cloud allowance
import { net, shell } from 'electron';
import { createHash, randomBytes } from 'node:crypto';
import { chmodSync, existsSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { hostname } from 'node:os';
import { join } from 'node:path';

export interface CloudUsage { month: string; allowance_usd: number; used_usd: number; credit_usd: number; balance_usd: number; used_percent: number }
export interface CloudUser { email: string; plan: 'free' | 'monthly' | 'yearly'; status: string; current_period_end: number | null; usage: CloudUsage }
interface Saved { email: string; token: string; local: Record<string, { username: string; password: string }> }

export class Cloud {
  readonly origin = (process.env.IRC_CLOUD_URL ?? 'https://copilot.xichiuk.com').replace(/\/$/, '');
  private readonly file: string;
  readonly providerFile: string;

  constructor(private readonly dataDir: string) {
    this.file = join(dataDir, 'cloud.json');
    this.providerFile = join(dataDir, 'provider.env');
    if (this.saved()?.token) this.writeProvider(this.saved()!.token);
  }

  private saved(): Saved | null {
    try { return JSON.parse(readFileSync(this.file, 'utf8')) as Saved; } catch { return null; }
  }

  private save(value: Saved): void {
    writeFileSync(this.file, JSON.stringify(value), { mode: 0o600 });
    chmodSync(this.file, 0o600);
  }

  private writeProvider(token: string): void {
    writeFileSync(this.providerFile, `OPENAI_API_KEY=${token}\nFRLOCAL_OPENAI_BASE=${this.origin}/api/v1/openai\n`, { mode: 0o600 });
    chmodSync(this.providerFile, 0o600);
  }

  private async call(method: string, path: string, body?: unknown, token?: string): Promise<any> {
    const response = await net.fetch(`${this.origin}${path}`, {
      method, body: body === undefined ? undefined : JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    }).catch(() => { throw new Error(`Cannot reach ${this.origin}. Check your internet connection.`); });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw Object.assign(new Error(typeof data.error === 'string' ? data.error : data.error?.message ?? `Request failed (${response.status})`), { status: response.status });
    return data;
  }

  /** Local workspace credentials for an email: one local account per cloud account, created on first sign-in. */
  private local(saved: Saved | null, email: string) {
    const existing = saved?.local?.[email];
    return existing ?? { username: `u${createHash('sha256').update(email).digest('hex').slice(0, 12)}`, password: randomBytes(24).toString('base64url') };
  }

  async authenticate(mode: 'register' | 'login', email: string, password: string) {
    const data = await this.call('POST', `/api/v1/auth/${mode}`, { email, password, device: hostname() });
    const saved = this.saved();
    const local = this.local(saved, data.user.email);
    this.save({ email: data.user.email, token: data.token, local: { ...(saved?.local ?? {}), [data.user.email]: local } });
    this.writeProvider(data.token);
    return { user: data.user as CloudUser, local };
  }

  /** Signed-in state with fresh plan and usage; offline keeps the session (the relay will tell when it is reachable). */
  async status(): Promise<{ signedIn: boolean; email?: string; user?: CloudUser; offline?: boolean; local?: { username: string; password: string } }> {
    const saved = this.saved();
    if (!saved?.token) return { signedIn: false };
    try {
      const { user } = await this.call('GET', '/api/v1/me', undefined, saved.token);
      return { signedIn: true, email: saved.email, user, local: this.local(saved, saved.email) };
    } catch (error) {
      if ((error as { status?: number }).status === 401) { this.forget(); return { signedIn: false }; }
      return { signedIn: true, email: saved.email, offline: true, local: this.local(saved, saved.email) };
    }
  }

  async signOut(): Promise<void> {
    const saved = this.saved();
    if (saved?.token) await this.call('POST', '/api/v1/auth/logout', {}, saved.token).catch(() => undefined);
    this.forget();
  }

  private forget(): void {
    const saved = this.saved();
    if (saved) this.save({ ...saved, email: '', token: '' });
    rmSync(this.providerFile, { force: true });
  }

  /** Opens the website signed in (one-time link), e.g. /pricing.html to subscribe. */
  async open(next: string): Promise<void> {
    const saved = this.saved();
    const url = saved?.token ? (await this.call('POST', '/api/v1/auth/web-link', { next }, saved.token)).url : `${this.origin}${next}`;
    await shell.openExternal(url);
  }

  exists(): boolean { return existsSync(this.file); }
}
