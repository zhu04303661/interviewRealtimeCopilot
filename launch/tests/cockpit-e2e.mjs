// End-to-end check of a live practice interview in the packaged app.
//
//   node launch/tests/cockpit-e2e.mjs <devtools port> <accounts dir>
//
// Expects the app to run against the fake OpenAI (backend/tests/fake_openai_server.py)
// with a fresh accounts directory. Drives the real main window, then watches the
// cockpit window: the AI interviewer's question with its Chinese translation, a
// streamed bilingual answer hint after "Suggest answer", and a clean end.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';

const [port, accounts] = process.argv.slice(2);
const devtools = `http://127.0.0.1:${port}`;

async function page(match, tries = 100) {
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      const pages = await fetch(devtools + '/json/list', { signal: AbortSignal.timeout(1500) }).then((r) => r.json());
      const found = pages.find((p) => match(p.url));
      if (found) return connect(found.webSocketDebuggerUrl);
    } catch {}
    await pause(300);
  }
  throw Error('Window did not open');
}

async function connect(url) {
  const socket = new WebSocket(url);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let id = 0;
  const pending = new Map();
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    pending.get(message.id)?.(message);
    pending.delete(message.id);
  };
  async function evaluate(expression) {
    const messageId = ++id;
    const message = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Timed out evaluating: ' + expression.slice(0, 80))), 15000);
      pending.set(messageId, (value) => { clearTimeout(timer); resolve(value); });
      socket.send(JSON.stringify({ id: messageId, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } }));
    });
    if (message.result?.exceptionDetails) throw Error(message.result.exceptionDetails.exception?.description ?? 'Evaluation failed');
    return message.result.result.value;
  }
  async function waitFor(expression, timeout = 15000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (await evaluate(expression).catch(() => false)) return;
      await pause(200);
    }
    throw Error('Expected state did not appear: ' + expression);
  }
  return { evaluate, waitFor, close: () => socket.close() };
}

const main = await page((url) => url.includes('/out/renderer/main-window/') && url.includes('#/auth/'));
await main.waitFor('Boolean(window.localAuth)');
const code = (await readFile(join(accounts, 'admin-first-login.txt'), 'utf8')).trim();
const account = await main.evaluate(`window.localAuth.activate({ code: ${JSON.stringify(code)}, newPassword: "cockpit-e2e-admin-password" })`);
assert.deepEqual(account, { username: 'admin', role: 'admin' });
await main.evaluate('location.hash = "#/app/goals"');
await main.waitFor('location.hash.startsWith("#/app/")');
const goal = await main.evaluate('window.api.goal.create({ position: "LTE L1 Engineer", company: "AccelerComm", company_detail: "", job_description: "PDSCH and HARQ" })');
const started = Date.now();
await main.evaluate(`window.api.session.start({ source: "copilot_home", mock: true, setup: {
  interviewEnvironment: "current_computer", materialDocumentIds: [], playbookId: null, goalId: ${JSON.stringify(goal.id)}, language: "en-US" } })`);

const cockpit = await page((url) => url.includes('cockpit-widget'));
const text = (needle) => `document.body.innerText.includes(${JSON.stringify(needle)})`;
await cockpit.waitFor(text('What is your biggest project?'));
const questionShownMs = Date.now() - started;
await cockpit.waitFor(text('你最大的项目是什么？'));
await cockpit.evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Suggest answer').click()`);
await cockpit.waitFor(text('I led the migration.'));
await cockpit.waitFor(text('我负责了迁移。'));
assert.equal(await cockpit.evaluate(`[...document.querySelectorAll('strong')].map((s) => s.textContent).filter((t) => t === 'EN' || t === '中文').length`), 2);
await main.evaluate('window.api.session.end({ trigger: "user" })');
await cockpit.close();
main.close();
console.log(JSON.stringify({ practiceSessionStarted: true, aiInterviewerQuestion: true, questionTranslation: true,
  streamedBilingualHint: true, markdownHeadings: true, sessionEnded: true, firstQuestionMs: questionShownMs }));
