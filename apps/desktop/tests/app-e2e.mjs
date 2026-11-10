// Full end-to-end check of the built desktop app against real OpenAI.
//
//   npm run build && node tests/app-e2e.mjs [resume] [material ...]
//
// Never opens the real microphone or computer audio: the microphone is
// tests/fixtures/answer.wav (Chromium's fake device, looped) and Live-mode
// computer audio is tests/fixtures/question.wav. Uses a temporary data folder
// that is deleted afterwards. Each step prints what it observed; the first
// failing step stops the run.
import { spawn } from 'node:child_process';
import { mkdtempSync, openSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';

const here = import.meta.dirname;
let [resume, ...materials] = process.argv.slice(2);
const port = 19671;
const data = mkdtempSync(join(tmpdir(), 'irc-app-e2e-'));
const logFile = join(data, 'app.log');
if (!resume) {
  // No documents given: generate a PDF resume and a Markdown Q&A material (no personal files needed).
  const { pdfFixture } = await import('./fixtures.mjs');
  const { writeFileSync } = await import('node:fs');
  resume = join(data, 'resume.pdf');
  writeFileSync(resume, pdfFixture(['Jane Doe - Software Engineering Manager', 'Led 40 engineers building LTE and 5G NR layer-1 software.',
    'Built a bit-exact C++ uplink receiver model used as the golden reference for DSP and FPGA teams.',
    'Introduced hardware-in-the-loop CI and cut the release cycle from three months to four weeks.']));
  materials = [join(data, 'prep.md')];
  writeFileSync(materials[0], ['# Interview preparation', '', '## How did CFO estimation work in the uplink receiver you modelled, and what are its limits?',
    'De-rotate with the previous TTI estimate, estimate the residual from the phase between the two DMRS symbols, smooth it per UE. Limits: large CFO and sparse allocations.', '',
    '## How do you build a high-performance team?', 'Clear ownership, design reviews, CI on target hardware, and coaching team leads.', '',
    '## Why do you want to work at AccelerComm?', 'Their 5G NR and NTN physical-layer IP sits where real-time PHY and rigorous software meet.'].join('\n'));
}
const env = { ...process.env, IRC_E2E: '1', IRC_DATA_DIR: data, IRC_FAKE_AUDIO: join(here, 'fixtures/answer.wav'),
  IRC_TEST_SYSTEM_AUDIO: join(here, 'fixtures/question.wav') };
delete env.ELECTRON_RUN_AS_NODE;
const out = openSync(logFile, 'a');
const app = spawn(join(here, '../node_modules/.bin/electron'), ['.', `--remote-debugging-port=${port}`], { cwd: join(here, '..'), env, stdio: ['ignore', out, out] });
const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1).padStart(5)}s]`, ...a);
const check = (condition, message) => { if (!condition) throw new Error(message); };

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
  const waitFor = async (expression, timeout = 60000, what = expression) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
      const value = await evaluate(expression).catch(() => null);
      if (value) return value;
      await pause(300);
    }
    throw new Error(`Timed out waiting for ${what}`);
  };
  const call = (method, params = {}) => { const n = ++id; return new Promise((resolve) => { pending.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params })); }); };
  return { evaluate, waitFor, call, close: () => ws.close() };
}

// Cockpit helpers (evaluated in the page).
// Final lines only (the live caption has a typing cursor).
const entries = (who) => `[...document.querySelectorAll('.c-entry')].filter((e) => e.querySelector('.stamp')?.textContent.startsWith('${who}') && !e.querySelector('.typing'))`;
const answers = `[...document.querySelectorAll('.c-answer')]`;
const clickButton = (selector, label) => `(() => { const b = [...${selector}].flatMap((e) => [...e.querySelectorAll('button')]).find((x) => x.textContent.includes('${label}') && !x.disabled); if (!b) return false; b.click(); return true; })()`;
const finishedAnswers = `${answers}.filter((a) => a.innerText.includes('中文') && a.innerText.length > 60).length`;

// Screenshots of each screen go to IRC_SHOTS (if set), for visual review.
async function shot(page, name) {
  if (!process.env.IRC_SHOTS) return;
  const { writeFileSync } = await import('node:fs');
  const result = await page.call('Page.captureScreenshot', { format: 'jpeg', quality: 75 });
  writeFileSync(join(process.env.IRC_SHOTS, `${name}.jpg`), Buffer.from(result.result.data, 'base64'));
}

let failed = false;
try {
  const main = await find((u) => u.endsWith('/index.html'));

  // ── account ───────────────────────────────────────────────────────────
  await main.waitFor(`document.body.innerText.includes('Sign in')`, 30000, 'sign-in screen');
  await shot(main, '0-sign-in');
  const auth = (path, body) => main.evaluate(`window.copilot.request('POST', '/local/auth/${path}', ${JSON.stringify({ owner: 'main', ...body })})`);
  check((await auth('register', { username: 'tester', password: 'irc-test-password-1' })).ok, 'register failed');
  check((await auth('register', { username: 'tester', password: 'irc-test-password-1' })).error?.includes('already'), 'duplicate username accepted');
  await auth('sign-out', {});
  await pause(2100); // the engine pauses briefly after a failed attempt
  const wrong = await auth('sign-in', { username: 'tester', password: 'wrong-password-123' });
  check(!wrong.ok && /incorrect/.test(wrong.error), 'wrong password accepted');
  await pause(2100);
  check((await auth('sign-in', { username: 'tester', password: 'irc-test-password-1' })).ok, 'sign-in failed');
  await main.evaluate('location.reload()');
  await pause(1500);
  await main.waitFor(`/getting started/i.test(document.body.innerText)`, 20000, 'workspace screen');
  log('account: register, duplicate rejected, sign out, wrong password rejected, sign in, workspace shown');

  // ── goal and knowledge sources ────────────────────────────────────────
  const goal = await main.evaluate(`window.copilot.request('POST', '/api/v3/goals', { role: 'Software Engineering Manager', company: 'AccelerComm',
    job_description: 'Lead L1 software teams building 5G NR and NTN physical-layer IP.' })`);
  const imported = [
    ...(resume ? await main.evaluate(`window.copilot.testImportPaths('resume', ${JSON.stringify([resume])})`) : []),
    ...(materials.length ? await main.evaluate(`window.copilot.testImportPaths('material', ${JSON.stringify(materials)})`) : []),
  ];
  const ids = imported.map((d) => d.document_id);
  const docs = await main.waitFor(`window.copilot.request('GET', '/api/v3/documents').then((r) => r.documents.every((d) => d.status !== 'preparing') && r.documents)`, 180000, 'document preparation');
  for (const d of docs) log(`document: ${d.filename} → ${d.status}${d.text_chars ? ` (${d.text_chars} chars)` : ''}${d.failure_reason ? ` ${d.failure_reason}` : ''}`);
  check(docs.length === ids.length && docs.every((d) => d.status === 'ready'), 'a document did not prepare');
  await main.evaluate('location.reload()');
  await pause(1500);
  await main.evaluate(`[...document.querySelectorAll('.side-nav button')].find((b) => b.textContent.startsWith('Library')).click()`);
  await main.evaluate(`[...document.querySelectorAll('.tab')].find((b) => b.textContent.startsWith('Materials')).click()`);
  check(await main.waitFor(`document.body.innerText.includes(${JSON.stringify(docs.find((d) => d.kind === 'material')?.filename ?? '')})`, 10000, 'documents listed'), 'documents not listed');
  await shot(main, '1-library');
  await main.evaluate(`[...document.querySelectorAll('.side-goal')][0].click()`);
  await main.waitFor(`document.body.innerText.includes('Goal context')`, 10000, 'goal page');
  await shot(main, '2-goal');
  log('goal created; documents imported, prepared and listed');
  await shot(main, '0-goals');

  // ── practice ──────────────────────────────────────────────────────────
  await main.evaluate(`window.copilot.startSession({ topology: 'mock', goalId: ${JSON.stringify(goal.goal_id)}, documentIds: ${JSON.stringify(ids)}, language: 'en-US' })`);
  let cockpit = await find((u) => u.endsWith('/cockpit.html'));
  const sessionStarted = Date.now();
  const total = Number(await cockpit.waitFor(`(document.body.innerText.match(/练习题 \\d+\\/(\\d+)/) || [])[1]`, 120000, 'practice question panel'));
  const first = await cockpit.waitFor(`${entries('Interviewer')}[0]?.querySelector('.text')?.textContent`, 60000, 'first spoken question');
  log(`practice: first question after ${((Date.now() - sessionStarted) / 1000).toFixed(1)} s; ${total} prepared questions so far; interviewer: "${first.slice(0, 120)}"`);
  check(Number(await cockpit.waitFor(`Number(document.body.dataset.voiceChunks ?? 0) > 3 && document.body.dataset.voiceChunks`, 20000, 'interviewer voice')) > 3, 'no voice');
  log(`practice: interviewer voice played (${await cockpit.evaluate('document.body.dataset.voiceChunks')} audio chunks)`);
  const practiceZh = await cockpit.waitFor(`${entries('Interviewer')}[0]?.querySelector('.zh')?.textContent`, 30000, 'translation');
  check(/[\u4e00-\u9fff]/.test(practiceZh), `practice translation is not Chinese: ${practiceZh}`);
  log(`practice: translation "${practiceZh.slice(0, 80)}"`);
  const heard = await cockpit.waitFor(`${entries('You')}[0]?.querySelector('.text')?.textContent`, 60000, 'candidate answer');
  log(`practice: candidate heard "${heard.slice(0, 100)}"`);
  const followUp = await cockpit.waitFor(`${entries('Interviewer')}.length >= 2 && ${entries('Interviewer')}.at(-1).querySelector('.text').textContent`, 60000, 'follow-up');
  log(`practice: follow-up "${followUp.slice(0, 120)}"`);
  // Buttons are disabled while a hint streams; wait for each click to be possible and for its hint.
  const answeredBefore = await cockpit.waitFor(`!document.querySelector('.c-feed button:disabled') && String(${finishedAnswers})`, 60000, 'idle hints');
  check(await cockpit.evaluate(clickButton(entries('You'), 'Expand answer')), 'no Expand answer button');
  await cockpit.waitFor(`${finishedAnswers} > ${answeredBefore} && !document.querySelector('.c-feed button:disabled')`, 60000, 'expand-answer hint');
  log(`practice: Expand answer → hint "${(await cockpit.evaluate(`${answers}.at(-1).innerText`)).replace(/\n+/g, ' ').slice(0, 140)}"`);
  const before = await cockpit.evaluate(finishedAnswers);
  check(await cockpit.evaluate(clickButton(entries('Interviewer'), 'Suggest answer')), 'no Suggest answer button');
  await cockpit.waitFor(`${finishedAnswers} > ${before} && !document.querySelector('.c-feed button:disabled')`, 60000, 'suggested answer');
  log('practice: Suggest answer → bilingual hint');
  const target = Math.min(5, total - 1);
  await cockpit.evaluate(`document.querySelectorAll('.c-plan li button')[${target}].click()`);
  await cockpit.waitFor(`document.querySelectorAll('.c-plan li button')[${target}].classList.contains('current')`, 10000, 'jump marker');
  const title = await cockpit.evaluate(`document.querySelectorAll('.c-plan li button')[${target}].title`);
  const jumped = await cockpit.waitFor(`(() => { const t = ${entries('Interviewer')}.at(-1).querySelector('.text').textContent; return /move on|next|let's/i.test(t) && t; })()`, 40000, 'jumped question');
  log(`practice: jumped to #${target + 1} "${title.slice(0, 80)}" → interviewer "${jumped.slice(0, 120)}"`);
  for (const mode of ['random', 'ai', 'sequential']) {
    await cockpit.evaluate(`[...document.querySelectorAll('.c-modes button')].find((b) => b.textContent.toLowerCase().startsWith(${JSON.stringify(mode === 'sequential' ? 'order' : mode)}))?.click()`);
    await cockpit.waitFor(`[...document.querySelectorAll('.c-modes button.active')].some((b) => b.textContent.toLowerCase().startsWith(${JSON.stringify(mode === 'sequential' ? 'order' : mode)}))`, 10000, `${mode} mode`);
  }
  log('practice: random, AI and order modes switch');
  await shot(cockpit, '3-practice-cockpit');
  check(!/Disconnected|断开/.test(await cockpit.evaluate(`document.querySelector('.c-banner')?.textContent ?? ''`)), 'practice disconnected');
  await main.evaluate('window.copilot.endSession()');
  cockpit.close();
  log('practice: ended');

  // ── Live ──────────────────────────────────────────────────────────────
  await pause(1000);
  await main.evaluate(`window.copilot.startSession({ topology: 'general', goalId: ${JSON.stringify(goal.goal_id)}, documentIds: ${JSON.stringify(ids)}, language: 'en-US' })`);
  cockpit = await find((u) => u.endsWith('/cockpit.html'));
  const said = await cockpit.waitFor(`${entries('Interviewer')}[0]?.querySelector('.text')?.textContent`, 60000, 'interviewer transcript');
  log(`live: interviewer transcript "${said}"`);
  const question = await cockpit.waitFor(`document.querySelector('.c-question .text')?.textContent`, 30000, 'question card');
  log(`live: question card "${question}"`);
  await cockpit.waitFor(`${finishedAnswers} >= 1`, 60000, 'automatic hint');
  log(`live: automatic hint "${(await cockpit.evaluate(`${answers}[0].innerText`)).replace(/\n+/g, ' ').slice(0, 160)}"`);
  const liveZh = await cockpit.waitFor(`${entries('Interviewer')}[0]?.querySelector('.zh')?.textContent`, 30000, 'live translation');
  check(/[\u4e00-\u9fff]/.test(liveZh), `live translation is not Chinese: ${liveZh}`);
  log(`live: translation "${liveZh.slice(0, 80)}"`);
  const mine = await cockpit.waitFor(`${entries('You')}[0]?.querySelector('.text')?.textContent`, 60000, 'candidate line');
  log(`live: candidate line "${mine.slice(0, 100)}"`);
  await shot(cockpit, '6-live-cockpit');
  check(await cockpit.evaluate(`${entries('Interviewer')}.every((e) => e.querySelector('.text').textContent !== ${JSON.stringify(mine)})`), 'candidate echoed as interviewer');
  check(!/Disconnected|断开/.test(await cockpit.evaluate(`document.querySelector('.c-banner')?.textContent ?? ''`)), 'live disconnected');
  // End from the cockpit so the recording is saved first.
  await cockpit.evaluate(`[...document.querySelectorAll('.c-footer button')].find((b) => b.textContent.startsWith('End')).click()`);
  const liveId = await main.evaluate(`window.copilot.request('GET', '/api/v3/sessions').then((r) => r.sessions[0].session_id)`);
  const recording = await main.waitFor(`window.copilot.loadRecording(${JSON.stringify(liveId)}).then((r) => r && { bytes: r.data.length, ms: r.durationMs, type: r.contentType })`, 20000, 'live recording');
  check(recording.bytes > 20000 && recording.ms > 5000, `recording too small: ${JSON.stringify(recording)}`);
  log(`live: recording saved (${(recording.bytes / 1024).toFixed(0)} KB, ${(recording.ms / 1000).toFixed(0)} s, ${recording.type})`);
  // The recording must contain the interviewer's speech, not silence: decode it and measure the loudest second.
  const peak = await main.evaluate(`window.copilot.loadRecording(${JSON.stringify(liveId)}).then(async (r) => {
    const audio = await new AudioContext().decodeAudioData(new Uint8Array(r.data).buffer);
    const data = audio.getChannelData(0); let best = 0;
    for (let start = 0; start < data.length; start += audio.sampleRate) {
      let sum = 0; const end = Math.min(data.length, start + audio.sampleRate);
      for (let i = start; i < end; i++) sum += data[i] * data[i];
      best = Math.max(best, Math.sqrt(sum / (end - start)));
    }
    return { seconds: audio.duration, rms: best };
  })`);
  check(peak.rms > 0.01, `recording is silent: ${JSON.stringify(peak)}`);
  log(`live: recording decodes to ${peak.seconds.toFixed(1)} s, loudest second RMS ${peak.rms.toFixed(3)}`);
  cockpit.close();
  log('live: ended');

  // ── history and Debrief ───────────────────────────────────────────────
  const sessions = await main.waitFor(`window.copilot.request('GET', '/api/v3/sessions').then((r) => r.sessions.length === 2 && r.sessions.every((s) => s.ended_at && s.status !== 'preparing') && r.sessions)`, 180000, 'reports');
  for (const s of sessions) log(`history: ${s.topology} → ${s.status}${s.headline ? ` "${s.headline}"` : ''}${s.failure_reason ? ` (${s.failure_reason})` : ''}`);
  check(sessions.every((s) => s.status === 'ready'), 'a Debrief was not generated');
  await main.evaluate(`[...document.querySelectorAll('.side-nav button')].find((b) => b.textContent.startsWith('History')).click()`);
  await main.waitFor(`document.querySelectorAll('.list-row').length === 2`, 10000, 'history list');
  await shot(main, '4-history');
  await main.evaluate(`document.querySelector('.list-row').click()`);
  check(await main.waitFor(`!!document.querySelector('.content audio')`, 10000, 'recording player'), 'no recording player');
  log(`history: report shown "${(await main.waitFor(`(() => { const t = document.querySelector('.content').innerText; return t.includes('Strengths') && t; })()`, 10000, 'report view')).replace(/\n+/g, ' ').slice(0, 160)}"`);
  await shot(main, '5-debrief');
  log('PASS');
} catch (error) {
  failed = true;
  log('FAIL', error.message);
} finally {
  app.kill('SIGTERM');
  await pause(2000);
  console.log('--- app log (filtered) ---');
  console.log(readFileSync(logFile, 'utf8').split('\n').filter((l) => l.trim() && !/_TIProperty|imkxpc|aiohttp\.access|TSM Adjust|DevTools listening/.test(l)).slice(-25).join('\n'));
  rmSync(data, { recursive: true, force: true });
  process.exit(failed ? 1 : 0);
}
