// Checks that one spoken question with mid-sentence pauses becomes one
// interviewer line and one question card (not several fragments).
//
//   npm run build && node tests/segmentation-e2e.mjs
//
// Computer audio is tests/fixtures/question-long.wav (pauses of 0.4–0.6 s
// inside the sentence); the microphone is the answer fixture. Real OpenAI.
import { spawn } from 'node:child_process';
import { mkdtempSync, openSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';

const here = import.meta.dirname;
const port = 19673;
const data = mkdtempSync(join(tmpdir(), 'irc-segmentation-'));
const env = { ...process.env, IRC_E2E: '1', IRC_DATA_DIR: data, IRC_FAKE_AUDIO: join(here, 'fixtures/answer.wav'),
  IRC_TEST_SYSTEM_AUDIO: join(here, 'fixtures/question-long.wav') };
delete env.ELECTRON_RUN_AS_NODE;
const app = spawn(join(here, '../node_modules/.bin/electron'), ['.', `--remote-debugging-port=${port}`],
  { cwd: join(here, '..'), env, stdio: ['ignore', openSync(join(data, 'app.log'), 'a'), openSync(join(data, 'app.log'), 'a')] });

async function find(match) {
  for (let i = 0; i < 150; i++) {
    try {
      const page = (await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json())).find((p) => p.type === 'page' && match(p.url));
      if (page) return connect(page.webSocketDebuggerUrl);
    } catch { /* not up yet */ }
    await pause(200);
  }
  throw new Error('no window');
}
async function connect(url) {
  const ws = new WebSocket(url);
  await new Promise((resolve) => { ws.onopen = resolve; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = ({ data: raw }) => { const m = JSON.parse(raw); pending.get(m.id)?.(m); };
  const ev = async (expression) => {
    const n = ++id;
    const m = await new Promise((resolve) => { pending.set(n, resolve); ws.send(JSON.stringify({ id: n, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } })); });
    return m.result?.result?.value;
  };
  return { ev };
}

let failed = false;
try {
  const main = await find((u) => u.endsWith('index.html'));
  for (let i = 0; i < 50 && !(await main.ev(`document.body.innerText.includes('Sign in')`)); i++) await pause(300);
  await main.ev(`window.copilot.request('POST', '/local/auth/register', { owner: 'main', username: 'tester', password: 'irc-test-password-1' })`);
  const goal = await main.ev(`window.copilot.request('POST', '/api/v3/goals', { role: 'Engineer', company: 'Example' })`);
  await main.ev(`window.copilot.startSession({ topology: 'general', goalId: ${JSON.stringify(goal.goal_id)}, documentIds: [], language: 'en-US' })`);
  const t0 = Date.now();
  const cockpit = await find((u) => u.endsWith('cockpit.html'));
  const finals = `[...document.querySelectorAll('.c-entry')].filter((e) => e.querySelector('.stamp')?.textContent.startsWith('Interviewer') && !e.querySelector('.typing'))`;
  let first = null;
  for (let i = 0; i < 50; i++) {
    if (!first && await cockpit.ev(`${finals}.length`)) first = ((Date.now() - t0) / 1000).toFixed(1);
    await pause(500);
  }
  const lines = await cockpit.ev(`${finals}.map((e) => e.querySelector('.text').textContent)`);
  const questions = await cockpit.ev(`[...document.querySelectorAll('.c-question .text')].map((e) => e.textContent)`);
  console.log(`first interviewer line after ${first} s (audio starts at ~2 s, ~9 s of speech)`);
  lines.forEach((l) => console.log('  line:', l));
  questions.forEach((q) => console.log('  question:', q));
  if (lines.length !== 1 || questions.length !== 1) throw new Error(`expected 1 line and 1 question, got ${lines.length} and ${questions.length}`);
  if (!/trade-?offs.*make/i.test(lines[0])) throw new Error('the line is missing the end of the question');
  await main.ev('window.copilot.endSession()');
  console.log('PASS');
} catch (error) {
  failed = true;
  console.log('FAIL', error.message);
} finally {
  app.kill('SIGTERM');
  await pause(2000);
  rmSync(data, { recursive: true, force: true });
  process.exit(failed ? 1 : 0);
}
