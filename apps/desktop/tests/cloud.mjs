// Test cloud: runs the website service (web/server) on a free port with a temporary database, so the app signs in
// and its AI calls go through the real metered relay. Upstream is real OpenAI with the key from ~/.env (or
// IRC_TEST_OPENAI_UPSTREAM, e.g. a fake). The key is passed to the server process only; it is never logged.
import { execFileSync, spawn } from 'node:child_process';
import { mkdtempSync, openSync, readFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';

const here = import.meta.dirname;
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const freePort = () => new Promise((resolve) => { const s = createServer().listen(0, () => { const { port } = s.address(); s.close(() => resolve(port)); }); });

function keyFromDotenv() {
  if (process.env.OPENAI_API_KEY) return process.env.OPENAI_API_KEY;
  try { return readFileSync(join(homedir(), '.env'), 'utf8').match(/^\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*["']?([^"'\s#]+)/m)?.[1]; } catch { return undefined; }
}

/** The macOS HTTPS proxy, so the local test cloud can reach OpenAI the way the app would. */
function systemProxy() {
  try {
    const out = execFileSync('scutil', ['--proxy']).toString();
    const host = out.match(/HTTPSProxy : (\S+)/)?.[1], port = out.match(/HTTPSPort : (\d+)/)?.[1];
    return /HTTPSEnable : 1/.test(out) && host && port ? `http://${host}:${port}` : undefined;
  } catch { return undefined; }
}

/** Starts the cloud. `freeAllowanceUsd` sets the free plan's monthly allowance. Returns { url, stop }. */
export async function startCloud({ freeAllowanceUsd = 5 } = {}) {
  const port = await freePort();
  const dir = mkdtempSync(join(tmpdir(), 'irc-cloud-'));
  const url = `http://127.0.0.1:${port}`;
  const out = openSync(join(dir, 'cloud.log'), 'a');
  const server = spawn('uv', ['run', '--project', join(here, '../../../web/server'), 'python', '-m', 'irc_web.app'], {
    cwd: join(here, '../../../web/server'), stdio: ['ignore', out, out],
    env: { ...process.env, PATH: `${homedir()}/.local/bin:/opt/homebrew/bin:${process.env.PATH}`, IRC_WEB_DB: join(dir, 'site.sqlite3'),
      IRC_WEB_PORT: String(port), IRC_WEB_ORIGIN: url, IRC_FREE_ALLOWANCE_USD: String(freeAllowanceUsd), OPENAI_API_KEY: keyFromDotenv() ?? '', ...(systemProxy() ? { IRC_OPENAI_PROXY: systemProxy() } : {}),
      ...(process.env.IRC_TEST_OPENAI_UPSTREAM ? { IRC_OPENAI_UPSTREAM: process.env.IRC_TEST_OPENAI_UPSTREAM } : {}) },
  });
  for (let i = 0; i < 100; i++) {
    if (await fetch(`${url}/api/me`).then((r) => r.ok, () => false)) return { url, dir, stop: () => server.kill() };
    await pause(200);
  }
  server.kill();
  throw new Error(`cloud did not start (log: ${join(dir, 'cloud.log')})`);
}

/** App environment pointing at the test cloud; the app must not see an OpenAI key of its own. */
export function cloudEnv(env, cloud) {
  const next = { ...env, IRC_CLOUD_URL: cloud.url };
  delete next.OPENAI_API_KEY;
  return next;
}

/** Registers a cloud account from the page, opens its local workspace and reloads into the signed-in app. */
export async function signIn(evaluate, email = 'tester@example.com', password = 'irc-test-password-1') {
  const result = await evaluate(`window.copilot.cloudAuth('register', ${JSON.stringify(email)}, ${JSON.stringify(password)})
    .then(async ({ local }) => { await window.copilot.request('POST', '/local/auth/register', { owner: 'main', ...local }); return { ok: true }; },
          (e) => ({ ok: false, error: e.message }))`);
  if (!result.ok) throw new Error(`cloud sign-in failed: ${result.error}`);
  await evaluate('location.reload()');
}
