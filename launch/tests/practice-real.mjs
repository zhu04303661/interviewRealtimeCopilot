// Real (non-mocked) spoken practice interview in the packaged app.
//
//   node launch/tests/practice-real.mjs <devtools port> <accounts dir> <material file>
//
// Uses the real OpenAI project from ~/.env. Activates a fresh local admin,
// uploads the material, starts a practice session and watches the cockpit:
// the interviewer's spoken question, its translation and the live hint. It then
// answers out loud with macOS `say` (played on the speakers, heard by the
// microphone) and waits for the interviewer's follow-up. Prints timings.
import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';

const [port, accounts, material] = process.argv.slice(2);
const devtools = `http://127.0.0.1:${port}`;
const t0 = Date.now();
const log = (step, extra = '') => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s] ${step}${extra ? ' — ' + extra : ''}`);

async function page(match, tries = 150) {
  for (let i = 0; i < tries; i++) {
    try {
      const found = (await fetch(devtools + '/json/list').then((r) => r.json())).find((p) => match(p.url));
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
  socket.onmessage = ({ data }) => { const m = JSON.parse(data); pending.get(m.id)?.(m); pending.delete(m.id); };
  const evaluate = async (expression) => {
    const messageId = ++id;
    const m = await new Promise((resolve) => {
      pending.set(messageId, resolve);
      socket.send(JSON.stringify({ id: messageId, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } }));
    });
    if (m.result?.exceptionDetails) throw Error(m.result.exceptionDetails.exception?.description ?? 'evaluation failed');
    return m.result.result.value;
  };
  const waitFor = async (expression, timeout = 60000) => {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const value = await evaluate(expression).catch(() => null);
      if (value) return value;
      await pause(250);
    }
    throw Error('Timed out waiting for: ' + expression);
  };
  return { evaluate, waitFor, close: () => socket.close() };
}

const main = await page((url) => url.includes('/main-window/'));
await main.waitFor('Boolean(window.localAuth)');
const code = (await readFile(join(accounts, 'admin-first-login.txt'), 'utf8')).trim();
await main.evaluate(`window.localAuth.activate({ code: ${JSON.stringify(code)}, newPassword: "real-practice-test-password" })`);
await main.evaluate('location.hash = "#/app/goals"');
log('signed in');
const goal = await main.evaluate(`window.api.goal.create({ position: "Software Engineering Manager", company: "AccelerComm",
  company_detail: "5G/LTE physical-layer IP", job_description: "Lead L1 software teams for 5G NR and LTE baseband IP." })`);
const doc = await main.evaluate(`window.api.document.upload({ kind: "material", filePath: ${JSON.stringify(material)} })`);
await main.waitFor(`window.api.document.list().then((d) => d.find((x) => x.document_id === ${JSON.stringify(doc.document_id)})?.status === "ready")`);
log('material prepared', doc.filename);
await main.evaluate(`window.api.session.start({ source: "copilot_home", mock: true, setup: { interviewEnvironment: "current_computer",
  materialDocumentIds: [${JSON.stringify(doc.document_id)}], playbookId: null, goalId: ${JSON.stringify(goal.id)}, language: "en-US" } })`);
log('practice session started');

const cockpit = await page((url) => url.includes('cockpit-widget'));
const bodyText = 'document.body.innerText';
const firstQuestion = await cockpit.waitFor(`(() => { const m = ${bodyText}.match(/Interviewer\\n+(?!Hearing)([^\\n]{12,})/i); return m && m[1]; })()`, 90000);
log('interviewer asked (spoken)', firstQuestion);
const translation = await cockpit.waitFor(`(() => { const p = [...document.querySelectorAll('p[lang="zh"]')].map((e) => e.textContent); return p[0]; })()`, 30000);
log('translation shown', translation);
const hint = await cockpit.waitFor(`(() => { const t = ${bodyText}; return /\\nEN\\n[\\s\\S]+\\n中文\\n/.test(t) && t.length; })()`, 45000);
log('bilingual hint streamed', `${hint} chars on screen`);

await pause(3000); // let the interviewer's voice finish before answering
const answer = 'In my last role I led about twenty engineers building the LTE layer one software. ' +
  'I introduced continuous integration on the target hardware and we cut the release cycle from three months to four weeks.';
log('answering out loud with macOS say');
await new Promise((resolve) => execFile('say', ['-v', 'Samantha', '-r', '175', answer], resolve));
const heard = await cockpit.waitFor(`(() => { const m = ${bodyText}.match(/You · 我\\n+([^\\n]{12,})/i); return m && m[1]; })()`, 45000);
log('candidate transcript', heard);
const followUp = await cockpit.waitFor(`(() => { const all = [...${bodyText}.matchAll(/Interviewer\\n+([^\\n]{12,})/gi)].map((m) => m[1]); return all.length >= 2 && all.at(-1); })()`, 60000);
log('interviewer follow-up (spoken)', followUp);
await main.evaluate('window.api.session.end({ trigger: "user" })');
log('session ended');
cockpit.close();
main.close();
