// End-to-end practice interview in the built desktop app, against real OpenAI.
//
//   npm run build && node tests/practice-e2e.mjs
//
// Starts Electron with a temporary data folder and media permission denied
// (no real microphone or computer audio is ever opened), registers an account,
// creates a goal, starts a practice session and checks the cockpit: question
// panel, the spoken interviewer's text, its translation, and that the
// connection stays up. Prints the app log and removes the folder afterwards.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';

const port = 19670;
const data = mkdtempSync(join(tmpdir(), 'irc-e2e-'));
const logFile = join(data, 'app.log');
// IRC_FAKE_AUDIO=<wav>: the answer is "spoken" from this file instead of the microphone.
const fakeAudio = process.env.IRC_FAKE_AUDIO;
const env = { ...process.env, IRC_DATA_DIR: data, ...(fakeAudio ? {} : { IRC_DENY_MEDIA: '1' }) };
delete env.ELECTRON_RUN_AS_NODE;
const { openSync } = await import('node:fs');
const out = openSync(logFile, 'a');
const app = spawn(join(import.meta.dirname, '../node_modules/.bin/electron'), ['.', `--remote-debugging-port=${port}`],
  { cwd: join(import.meta.dirname, '..'), env, stdio: ['ignore', out, out] });
const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);

async function find(match, timeout = 30000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try {
      const page = (await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json())).find((p) => p.type === 'page' && match(p.url));
      if (page) return connect(page.webSocketDebuggerUrl);
    } catch { /* not listening yet */ }
    await pause(200);
  }
  throw new Error('Window did not open');
}

async function connect(url) {
  const ws = new WebSocket(url);
  await new Promise((resolve) => { ws.onopen = resolve; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = ({ data: raw }) => { const m = JSON.parse(raw); pending.get(m.id)?.(m); };
  const evaluate = async (expression) => {
    const n = ++id;
    const m = await new Promise((resolve) => { pending.set(n, resolve); ws.send(JSON.stringify({ id: n, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } })); });
    if (m.result?.exceptionDetails) throw new Error(m.result.exceptionDetails.exception?.description ?? 'evaluation failed');
    return m.result.result.value;
  };
  const waitFor = async (expression, timeout = 60000) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const value = await evaluate(expression).catch(() => null);
      if (value) return value;
      await pause(300);
    }
    throw new Error(`Timed out: ${expression}`);
  };
  return { evaluate, waitFor };
}

let failed = false;
try {
  const main = await find((u) => u.endsWith('/index.html'));
  await main.waitFor(`document.body.innerText.includes('Sign in')`);
  log('sign-in screen');
  const registered = await main.evaluate(`window.copilot.request('POST', '/local/auth/register', { owner: 'main', username: 'tester', password: 'irc-test-password-1' })`);
  if (!registered.ok) throw new Error(registered.error);
  const goal = await main.evaluate(`window.copilot.request('POST', '/api/v3/goals', { role: 'Software Engineering Manager', company: 'AccelerComm', job_description: 'Lead L1 software teams for 5G NR and NTN PHY IP.' })`);
  log('account and goal created');
  await main.evaluate(`window.copilot.startSession({ topology: 'mock', goalId: ${JSON.stringify(goal.goal_id)}, documentIds: [], language: 'en-US' })`);
  const cockpit = await find((u) => u.endsWith('/cockpit.html'));
  log('cockpit opened');
  log('practice questions:', await cockpit.waitFor(`(document.body.innerText.match(/练习题 \\d+\\/(\\d+)/) || [])[1]`, 90000));
  log('interviewer:', await cockpit.waitFor(`(() => { const e = [...document.querySelectorAll('.entry')].find((x) => x.querySelector('.who')?.textContent.startsWith('Interviewer')); return e?.querySelector('.text')?.textContent; })()`, 60000));
  log('translation:', await cockpit.waitFor(`document.querySelector('.entry .zh')?.textContent`, 30000));
  if (fakeAudio) {
    log('candidate (from file):', await cockpit.waitFor(`(() => { const e = [...document.querySelectorAll('.entry')].find((x) => x.querySelector('.who')?.textContent.startsWith('You')); return e?.querySelector('.text')?.textContent; })()`, 60000));
    log('interviewer next turn:', await cockpit.waitFor(`(() => { const t = [...document.querySelectorAll('.entry')].filter((x) => x.querySelector('.who')?.textContent.startsWith('Interviewer')); return t.length >= 2 && t.at(-1).querySelector('.text').textContent; })()`, 60000));
  }
  await pause(20000);
  const status = await cockpit.evaluate(`document.querySelector('.status')?.textContent ?? ''`);
  log('status after 20 s:', status || '(none)');
  if (/Disconnected|断开/.test(status)) throw new Error('The cockpit lost its connection.');
  await main.evaluate('window.copilot.endSession()');
  log('PASS');
} catch (error) {
  failed = true;
  log('FAIL', error.message);
} finally {
  app.kill('SIGTERM');
  await pause(2000);
  console.log('--- app log (filtered) ---');
  console.log(readFileSync(logFile, 'utf8').split('\n').filter((l) => l.trim() && !/_TIProperty|imkxpc|aiohttp\.access/.test(l)).slice(-25).join('\n'));
  rmSync(data, { recursive: true, force: true });
  process.exit(failed ? 1 : 0);
}
