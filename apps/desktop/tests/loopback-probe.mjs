// Diagnostic: does Live mode hear computer audio? Uses an app already started with
// --remote-debugging-port=<port> (IRC_E2E=1, IRC_FAKE_AUDIO for the microphone), starts
// a Live session, plays <wav> on the speakers with afplay, and prints the
// computer-audio level meter and the interviewer transcript.
//
//   node tests/loopback-probe.mjs <port> tests/fixtures/question.wav
import { execFile } from 'node:child_process';
import { setTimeout as pause } from 'node:timers/promises';

const [port, wav] = process.argv.slice(2);
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
  ws.onmessage = ({ data }) => { const m = JSON.parse(data); pending.get(m.id)?.(m); };
  const ev = async (expression) => {
    const n = ++id;
    const m = await new Promise((resolve) => { pending.set(n, resolve); ws.send(JSON.stringify({ id: n, method: 'Runtime.evaluate', params: { expression, awaitPromise: true, returnByValue: true } })); });
    return m.result?.result?.value;
  };
  return { ev };
}

const main = await find((u) => u.endsWith('index.html'));
for (let i = 0; i < 50 && !(await main.ev(`document.body.innerText.includes('Sign in') || document.body.innerText.includes('Goals')`)); i++) await pause(300);
await main.ev(`window.copilot.request('POST', '/local/auth/register', { owner: 'main', username: 'tester', password: 'irc-test-password-1' })`);
const goal = await main.ev(`window.copilot.request('POST', '/api/v3/goals', { role: 'Engineer', company: 'Example' })`);
await main.ev(`window.copilot.startSession({ topology: 'general', goalId: ${JSON.stringify(goal.goal_id)}, documentIds: [], language: 'en-US' })`);
const cockpit = await find((u) => u.endsWith('cockpit.html'));
await pause(4000);
console.log('banner:', await cockpit.ev(`[...document.querySelectorAll('.c-banner')].map((b) => b.textContent).join(' | ') || '(none)'`));
const levels = [];
const player = new Promise((resolve) => execFile('afplay', [wav], resolve));
for (let i = 0; i < 12; i++) {
  levels.push(await cockpit.ev(`[...document.querySelectorAll('.meter-bar span')].map((s) => s.style.width).join('/')`));
  await pause(500);
}
await player;
console.log('meters mic/computer while playing:', levels.join('  '));
for (let i = 0; i < 40 && !(await cockpit.ev(`[...document.querySelectorAll('.c-entry')].some((e) => e.querySelector('.stamp')?.textContent.startsWith('Interviewer'))`)); i++) await pause(500);
console.log('interviewer lines:', await cockpit.ev(`[...document.querySelectorAll('.c-entry')].filter((e) => e.querySelector('.stamp')?.textContent.startsWith('Interviewer')).map((e) => e.querySelector('.text').textContent).join(' | ') || '(none)'`));
await main.ev('window.copilot.endSession()');
process.exit(0);
