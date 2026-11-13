// Quota: with the free allowance used up, starting a practice session shows "allowance is used up" in the cockpit,
// and Settings → Account shows the plan, the full usage bar and a Subscribe button. Media is denied; no OpenAI
// request is made (the cloud refuses before forwarding).
// Usage: node tests/quota-e2e.mjs
import { spawn } from 'node:child_process';
import { mkdtempSync, openSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { cloudEnv, signIn, startCloud } from './cloud.mjs';

const here = import.meta.dirname;
const port = 9400 + Math.floor(Math.random() * 300);
const pause = (ms) => new Promise((r) => setTimeout(r, ms));
const data = mkdtempSync(join(tmpdir(), 'irc-quota-'));
const cloud = await startCloud({ freeAllowanceUsd: 0 });
const env = { ...cloudEnv(process.env, cloud), IRC_E2E: '1', IRC_DATA_DIR: data, IRC_DENY_MEDIA: '1' };
delete env.ELECTRON_RUN_AS_NODE;
const app = spawn(join(here, '../node_modules/.bin/electron'), ['.', `--remote-debugging-port=${port}`], { cwd: join(here, '..'), env, stdio: ['ignore', openSync('/tmp/irc-quota-app.log', 'w'), openSync('/tmp/irc-quota-app.log', 'a')] });
let failed = false;
try {
  let page;
  for (let i = 0; i < 100 && !page; i++) {
    page = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json()).then((l) => l.find((p) => p.type === 'page' && p.url.endsWith('/index.html')), () => null);
    if (!page) await pause(200);
  }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => { ws.onopen = r; });
  let id = 0; const pending = new Map();
  ws.onmessage = ({ data: raw }) => { const m = JSON.parse(raw); pending.get(m.id)?.(m); };
  const evaluate = async (expression) => {
    const n = ++id;
    const m = await new Promise((r) => { pending.set(n, r); ws.send(JSON.stringify({ id: n, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } })); });
    if (m.result?.exceptionDetails) throw new Error(m.result.exceptionDetails.exception?.description);
    return m.result.result.value;
  };
  const waitFor = async (expression, timeout, what) => { const end = Date.now() + timeout;
    while (Date.now() < end) { const v = await evaluate(expression).catch(() => null); if (v) return v; await pause(300); } throw new Error(`timed out: ${what}`); };
  await waitFor(`document.body.innerText.includes('Welcome back')`, 30000, 'sign-in screen');
  await signIn(evaluate, 'quota@example.com');
  await waitFor(`/getting started/i.test(document.body.innerText)`, 30000, 'workspace');
  const goal = await evaluate(`window.copilot.request('POST', '/api/v3/goals', { role: 'Software Engineer', company: 'Acme' })`);
  await evaluate(`window.copilot.startSession({ topology: 'mock', goalId: ${JSON.stringify(goal.goal_id)}, documentIds: [], language: 'en-US' })`);
  let cockpitPage;
  for (let i = 0; i < 100 && !cockpitPage; i++) {
    cockpitPage = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json()).then((l) => l.find((p) => p.url.endsWith('/cockpit.html')), () => null);
    if (!cockpitPage) await pause(200);
  }
  const cws = new WebSocket(cockpitPage.webSocketDebuggerUrl);
  await new Promise((r) => { cws.onopen = r; });
  const cpending = new Map(); let cid = 0;
  cws.onmessage = ({ data: raw }) => { const m = JSON.parse(raw); cpending.get(m.id)?.(m); };
  const cockpitText = () => new Promise((r) => { const n = ++cid; cpending.set(n, (m) => r(m.result?.result?.value ?? ''));
    cws.send(JSON.stringify({ id: n, method: 'Runtime.evaluate', params: { expression: 'document.body.innerText', returnByValue: true } })); });
  let shown = '';
  for (let i = 0; i < 100 && !/allowance is used up/i.test(shown); i++) { shown = await cockpitText(); await pause(300); }
  if (!/allowance is used up/i.test(shown)) throw new Error(`the quota message was not shown; cockpit: ${shown.slice(0, 300)}`);
  console.log('cockpit:', shown.split('\n').find((l) => /allowance is used up/i.test(l)));
  await evaluate(`window.copilot.endSession?.()`).catch(() => undefined);
  await evaluate(`[...document.querySelectorAll('.side-nav button')].find((b) => b.textContent.startsWith('Settings')).click()`);
  await pause(500);
  await evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.startsWith('Account')).click()`);
  const panel = await waitFor(`(() => { const t = document.querySelector('.content')?.innerText ?? ''; return t.includes('Plan & AI allowance') && t.includes('used up') && t; })()`, 15000, 'plan panel');
  if (!/Subscribe/.test(panel)) throw new Error('no Subscribe button');
  console.log('settings:', panel.split('\n').filter((l) => /Free|used|Subscribe/.test(l)).slice(0, 4).join(' | '));
  console.log('PASS');
} catch (error) {
  failed = true;
  console.log('FAIL', error.message);
} finally {
  app.kill('SIGTERM');
  cloud.stop();
  await pause(1500);
  rmSync(data, { recursive: true, force: true });
  process.exit(failed ? 1 : 0);
}
