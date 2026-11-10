// Plays every scenario of tests/audio/corpus.json as Live-mode computer audio
// (real OpenAI, silent microphone, temporary data folder) and checks what the
// cockpit shows against the scenario's expectations. Writes a JSON report.
//
//   npm run build && node tests/audio/build-corpus.mjs && node tests/audio/run-corpus.mjs [id ...]
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, openSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';

const here = import.meta.dirname;
const only = process.argv.slice(2);
const { scenarios } = JSON.parse(readFileSync(join(here, 'corpus.json'), 'utf8'));
const selected = scenarios.filter((s) => !only.length || only.includes(s.id));
const port = 19674;
const data = mkdtempSync(join(tmpdir(), 'irc-corpus-'));
const env = { ...process.env, IRC_E2E: '1', IRC_DATA_DIR: data, IRC_FAKE_AUDIO: join(here, 'wav/silence.wav') };
delete env.ELECTRON_RUN_AS_NODE;
const logFd = openSync(join(data, 'app.log'), 'a');
const app = spawn(join(here, '../../node_modules/.bin/electron'), ['.', `--remote-debugging-port=${port}`], { cwd: join(here, '../..'), env, stdio: ['ignore', logFd, logFd] });

async function find(match) {
  for (let i = 0; i < 150; i++) {
    try {
      const page = (await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json())).find((p) => p.type === 'page' && match(p.url));
      if (page) return connect(page.webSocketDebuggerUrl);
    } catch { /* not up yet */ }
    await pause(200);
  }
  throw new Error('window did not open');
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
  return { ev, close: () => ws.close() };
}
const wavSeconds = (file) => (readFileSync(file).length - 44) / 32_000;

/** What the cockpit shows: final interviewer lines, question cards and answer hints. */
const SNAPSHOT = `(() => {
  const lines = [...document.querySelectorAll('.c-entry')].filter((e) => e.querySelector('.stamp')?.textContent.startsWith('Interviewer') && !e.querySelector('.typing'));
  return {
    lines: lines.map((e) => ({ text: e.querySelector('.text').textContent, zh: e.querySelector('.zh')?.textContent ?? '' })),
    questions: [...document.querySelectorAll('.c-question')].map((q) => ({ text: q.querySelector('.text').textContent, intent: q.dataset.intent, decision: q.dataset.decision })),
    hints: [...document.querySelectorAll('.c-answer')].map((a) => ({ text: a.innerText, done: !a.querySelector('.typing'), superseded: a.classList.contains('superseded') })),
    banners: [...document.querySelectorAll('.c-banner')].map((b) => b.textContent),
  };
})()`;

function judge(scenario, seen) {
  const e = scenario.expect;
  const problems = [];
  const answered = seen.questions.filter((q) => q.decision === 'respond');
  const within = (n, [min, max]) => n >= min && n <= max;
  if (!within(seen.lines.length, e.lines)) problems.push(`lines ${seen.lines.length}, expected ${e.lines.join('–')}`);
  if (!within(answered.length, e.questions)) problems.push(`answered questions ${answered.length}, expected ${e.questions.join('–')}`);
  const bilingual = seen.hints.filter((h) => h.done && /\bEN\b/.test(h.text) && /中文/.test(h.text));
  if (e.hint && bilingual.length === 0) problems.push('no finished bilingual hint');
  if (e.hint === false && seen.hints.length) problems.push(`unexpected hint`);
  if (e.translation) {
    const wanted = e.translation === 'zh' ? /[\u4e00-\u9fff]/ : /[A-Za-z]{3}/;
    const missing = seen.lines.filter((l) => !wanted.test(l.zh));
    if (missing.length) problems.push(`${missing.length} line(s) without a ${e.translation} translation`);
  }
  const all = seen.lines.map((l) => l.text).join(' ');
  for (const keyword of e.keywords ?? []) if (!all.toLowerCase().includes(keyword.toLowerCase())) problems.push(`transcript lacks "${keyword}"`);
  if (e.intent && !answered.some((q) => q.intent === e.intent)) problems.push(`intent ${answered.map((q) => q.intent).join(',') || 'none'}, expected ${e.intent}`);
  return problems;
}

const results = [];
try {
  const main = await find((u) => u.endsWith('index.html'));
  for (let i = 0; i < 50 && !(await main.ev(`document.body.innerText.includes('Sign in')`)); i++) await pause(300);
  await main.ev(`window.copilot.request('POST', '/local/auth/register', { owner: 'main', username: 'tester', password: 'irc-test-password-1' })`);
  const goal = await main.ev(`window.copilot.request('POST', '/api/v3/goals', { role: 'Software Engineering Manager', company: 'AccelerComm',
    job_description: 'Lead L1 software teams building 5G NR and NTN physical-layer IP.' })`);
  for (const scenario of selected) {
    const wav = join(here, `wav/${scenario.id}.wav`);
    await main.ev(`window.copilot.testSetSystemAudio(${JSON.stringify(wav)})`);
    await main.ev(`window.copilot.startSession({ topology: 'general', goalId: ${JSON.stringify(goal.goal_id)}, documentIds: [], language: ${JSON.stringify(scenario.language ?? 'en-US')} })`);
    const cockpit = await find((u) => u.endsWith('cockpit.html'));
    const started = Date.now();
    // Audio starts ~2 s after capture begins; allow transcription, analysis and the hint to finish.
    const budget = (wavSeconds(wav) + 22) * 1000;
    let seen;
    while (Date.now() - started < budget) {
      await pause(1000);
      seen = await cockpit.ev(SNAPSHOT);
    }
    const problems = judge(scenario, seen);
    results.push({ id: scenario.id, pass: problems.length === 0, problems, seen });
    console.log(`${problems.length ? 'FAIL' : 'pass'}  ${scenario.id.padEnd(24)} lines ${seen.lines.length}, questions ${seen.questions.filter((q) => q.decision === 'respond').length}${problems.length ? '  — ' + problems.join('; ') : ''}`);
    for (const line of seen.lines) console.log(`        "${line.text.slice(0, 110)}"  → ${line.zh.slice(0, 60)}`);
    await main.ev('window.copilot.endSession()');
    cockpit.close();
    await pause(1500);
  }
} catch (error) {
  console.log('ERROR', error.message);
  results.push({ id: 'runner', pass: false, problems: [error.message] });
} finally {
  app.kill('SIGTERM');
  await pause(2000);
  const reports = join(here, '../../tests/reports');
  mkdirSync(reports, { recursive: true });
  writeFileSync(join(reports, 'audio-corpus.json'), JSON.stringify({ at: new Date().toISOString(), results }, null, 2));
  rmSync(data, { recursive: true, force: true });
  const failed = results.filter((r) => !r.pass).length;
  console.log(`\n${results.length - failed}/${results.length} scenarios passed`);
  process.exit(failed ? 1 : 0);
}
