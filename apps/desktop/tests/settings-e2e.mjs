// End-to-end check of Settings (all six sections) in the built desktop app.
//
//   npm run build && IRC_SHOTS=/tmp/shots node tests/settings-e2e.mjs
//
// Media permission is denied (no microphone or computer audio). Changes are
// checked where they are stored: settings.json for device settings, the
// engine for account preferences and consents, and the cockpit's applied
// appearance during a practice session.
import { cloudEnv, signIn, startCloud } from './cloud.mjs';
import { spawn } from 'node:child_process';
import { mkdtempSync, openSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';

const here = import.meta.dirname;
const port = 19672;
const data = mkdtempSync(join(tmpdir(), 'irc-settings-e2e-'));
const logFile = join(data, 'app.log');
// The "screen" for Solve screen is a generated test page image, never the real screen.
const screenImage = join(data, 'screen.png');
const cloud = await startCloud();
process.on('exit', () => cloud.stop());
const env = { ...cloudEnv(process.env, cloud), IRC_E2E: '1', IRC_DENY_MEDIA: '1', IRC_DATA_DIR: data, IRC_TEST_SCREEN: screenImage };
delete env.ELECTRON_RUN_AS_NODE;
const out = openSync(logFile, 'a');
const app = spawn(join(here, '../node_modules/.bin/electron'), ['.', `--remote-debugging-port=${port}`], { cwd: join(here, '..'), env, stdio: ['ignore', out, out] });
const log = (...a) => console.log('·', ...a);
const check = (condition, message) => { if (!condition) throw new Error(message); };

async function find(match, timeout = 30000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try {
      const page = (await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json())).find((p) => p.type === 'page' && match(p.url));
      if (page) return connect(page.webSocketDebuggerUrl);
    } catch { /* not up yet */ }
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
  const call = (method, params = {}) => { const n = ++id; return new Promise((resolve) => { pending.set(n, resolve); ws.send(JSON.stringify({ id: n, method, params })); }); };
  const evaluate = async (expression) => {
    const m = await call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (m.result?.exceptionDetails) throw new Error(m.result.exceptionDetails.exception?.description ?? 'evaluation failed');
    return m.result.result.value;
  };
  const waitFor = async (expression, timeout = 15000, what = expression) => {
    const end = Date.now() + timeout;
    while (Date.now() < end) { const v = await evaluate(expression).catch(() => null); if (v) return v; await pause(200); }
    throw new Error(`Timed out waiting for ${what}`);
  };
  return { call, evaluate, waitFor };
}

async function shot(page, name) {
  if (!process.env.IRC_SHOTS) return;
  const result = await page.call('Page.captureScreenshot', { format: 'jpeg', quality: 75 });
  writeFileSync(join(process.env.IRC_SHOTS, `${name}.jpg`), Buffer.from(result.result.data, 'base64'));
}

const clickText = (text, scope = 'document') => `(() => { const b = [...${scope}.querySelectorAll('button')].find((x) => x.textContent.includes(${JSON.stringify(text)}) && !x.disabled); if (!b) return false; b.click(); return true; })()`;
const settingRow = (title) => `[...document.querySelectorAll('.setting')].find((r) => r.querySelector('b')?.textContent.startsWith(${JSON.stringify(title)}))`;
const stored = () => JSON.parse(readFileSync(join(data, 'settings.json'), 'utf8'));

let failed = false;
try {
  const main = await find((u) => u.endsWith('/index.html'));
  await main.waitFor(`document.body.innerText.includes('Sign in')`, 30000, 'sign-in');
  await signIn((e) => main.evaluate(e));
  await main.waitFor(`/getting started/i.test(document.body.innerText)`, 20000, 'workspace');
  await main.evaluate(`[...document.querySelectorAll('.side-nav button')].find((b) => b.textContent.startsWith('Settings')).click()`);
  await main.waitFor(`!!document.querySelector('.settings nav')`, 10000, 'settings');
  const open = async (label) => { check(await main.evaluate(clickText(label, "document.querySelector('.settings nav')")), `no ${label} section`); await pause(400); };

  // General
  await open('General');
  await shot(main, 's1-general');
  await main.evaluate(`${settingRow('Launch at login')}.querySelector('.switch').click()`);
  await pause(300);
  check(stored().launchAtLogin === true, 'launch at login not saved');
  await main.evaluate(`${settingRow('Launch at login')}.querySelector('.switch').click()`);
  await pause(300);
  check(stored().launchAtLogin === false, 'launch at login not cleared');
  log('General: launch-at-login toggles and persists; version shown:', await main.evaluate(`document.querySelector('.settings nav p').innerText.replace(/\\n/g, ' ')`));

  // Appearance
  await open('Appearance');
  await main.evaluate(`(() => { const r = document.querySelector('input[type=range]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(r, '60'); r.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await pause(300);
  check(stored().opacity === 0.7, `opacity floor not enforced (${stored().opacity})`);
  await main.evaluate(`(() => { const r = document.querySelector('input[type=range]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(r, '90'); r.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await pause(300);
  check(stored().opacity === 0.9, 'opacity not saved');
  await main.evaluate(`window.copilot.setSettings({ background: '#204060', text: '#2a3a4a' })`);
  await main.waitFor(`document.body.innerText.includes('Low contrast')`, 5000, 'contrast warning');
  const preview = await main.evaluate(`getComputedStyle(document.querySelector('.preview')).backgroundColor`);
  check(preview === 'rgba(32, 64, 96, 0.9)', `preview not painted with settings: ${preview}`);
  await shot(main, 's2-appearance-low-contrast');
  await main.evaluate(clickText('Use default'));
  await pause(300);
  await main.evaluate(clickText('Use default'));
  await pause(300);
  check(stored().background === '#0c0d10' && stored().text === '#e9eaec', 'Use default did not restore colours');
  await shot(main, 's2-appearance');
  log(`Appearance: opacity floor 70% enforced, 90% saved, preview painted ${preview}, low-contrast warning shown, defaults restored`);

  // Defaults
  await open('Defaults');
  const select = (title, value) => main.evaluate(`(() => { const s = ${settingRow(title)}.querySelector('select'); Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(s, ${JSON.stringify(value)}); s.dispatchEvent(new Event('change', { bubbles: true })); })()`);
  await select('Answer language', 'zh-CN');
  await select('Coding language', 'C++');
  await pause(500);
  const prefs = await main.evaluate(`window.copilot.request('GET', '/api/v3/me/prefs')`);
  check(prefs.default_language === 'zh-CN' && prefs.default_coding_language === 'C++', `prefs not saved: ${JSON.stringify(prefs)}`);
  await shot(main, 's3-defaults');
  log('Defaults: answer language zh-CN and coding language C++ saved in the engine');

  // Privacy & Stealth
  await open('Privacy');
  await shot(main, 's4-privacy');
  await main.evaluate(`${settingRow('Hide from screen sharing')}.querySelector('.switch').click()`);
  await main.waitFor(`document.body.innerText.includes('While this is off')`, 5000, 'stealth warning');
  check(stored().stealth === false, 'stealth off not saved');
  await shot(main, 's4-privacy-stealth-off');
  await main.evaluate(`${settingRow('Hide from screen sharing')}.querySelector('.switch').click()`);
  await pause(300);
  check(stored().stealth === true && !(await main.evaluate(`document.body.innerText.includes('While this is off')`)), 'stealth back on');
  const perms = await main.evaluate(`[...document.querySelectorAll('.setting')].filter((r) => /Microphone|Screen &/.test(r.innerText)).map((r) => r.querySelector('.badge').textContent).join(' | ')`);
  await main.evaluate(`${settingRow('Auto-capture')}.querySelector('.switch').click()`);
  await pause(300);
  check(stored().autoCapture === false, 'auto-capture off not saved');
  await main.evaluate(`${settingRow('AI training')}.querySelector('.switch').click()`);
  await pause(500);
  check((await main.evaluate(`window.copilot.request('GET', '/api/v3/me/consents')`)).ai_training === true, 'consent not saved');
  await main.evaluate(`window.confirm = () => true`);
  await main.evaluate(clickText('Erase everything'));
  await main.waitFor(`document.body.innerText.includes('Memory erased')`, 5000, 'memory erased');
  log(`Privacy: stealth warning appears only while off, permissions shown (${perms}), auto-capture and AI-training consent saved, memory erase works`);

  // Shortcuts
  await open('Shortcuts');
  await shot(main, 's5-shortcuts');
  await main.evaluate(`${settingRow('Solve screen')}.querySelector('.keys').focus()`);
  await main.evaluate(`${settingRow('Solve screen')}.querySelector('.keys').click()`);
  await main.waitFor(`document.body.innerText.includes('Press keys')`, 3000, 'recording state');
  for (const type of ['keyDown', 'keyUp']) {
    await main.call('Input.dispatchKeyEvent', { type, modifiers: 1 | 8, key: 'K', code: 'KeyK', windowsVirtualKeyCode: 75 }); // Alt+Shift+K
  }
  await pause(500);
  check(stored().shortcuts.solveScreen === 'Alt+Shift+K', `reassign failed: ${stored().shortcuts.solveScreen}`);
  await main.evaluate(clickText('Reset to defaults'));
  await pause(300);
  check(stored().shortcuts.solveScreen === 'Alt+S', 'reset failed');
  log('Shortcuts: nine bindings shown, Solve screen reassigned to Alt+Shift+K by key press, reset restores Alt+S');

  // Account
  await open('Account');
  await shot(main, 's6-account');
  check(await main.evaluate(`document.body.innerText.includes('tester') && document.body.innerText.includes('Sign out')`), 'account section');
  log('Account: user, sign out, local workspace and disabled delete shown');

  // A coding problem rendered by Chromium becomes the test "screen".
  await main.evaluate(`(() => { const d = document.createElement('div'); d.id = 'test-screen'; d.style.cssText = 'position:fixed;inset:0;z-index:9999;background:#fff;color:#111;font:20px monospace;padding:40px;white-space:pre';
    d.textContent = 'LeetCode 1. Two Sum\\n\\nGiven an array of integers nums and an integer target, return indices of the two numbers\\nsuch that they add up to target. Example: nums = [2,7,11,15], target = 9 -> [0,1]\\n\\ndef two_sum(nums, target):\\n    # your code here'; document.body.appendChild(d); })()`);
  await pause(300);
  writeFileSync(screenImage, Buffer.from((await main.call('Page.captureScreenshot', { format: 'png' })).result.data, 'base64'));
  await main.evaluate(`document.getElementById('test-screen').remove()`);

  // Cockpit applies the device appearance live.
  await main.evaluate(`window.copilot.setSettings({ opacity: 0.85, background: '#101820' })`);
  const goal = await main.evaluate(`window.copilot.request('POST', '/api/v3/goals', { role: 'Engineer', company: 'Example' })`);
  // Preflight: opened from the goal page, choices apply to this session only.
  await main.evaluate('location.reload()');
  await main.waitFor(`document.querySelectorAll('.side-goal').length > 0`, 15000, 'goal in sidebar');
  await main.evaluate(`document.querySelector('.side-goal').click()`);
  await main.waitFor(`document.body.innerText.includes('Goal context')`, 10000, 'goal page');
  check(await main.evaluate(clickText('Practice · 练习')), 'no Practice button');
  await main.waitFor(`!!document.querySelector('.preflight')`, 5000, 'preflight');
  const sections = await main.evaluate(`[...document.querySelectorAll('.preflight .setting-group')].map((h) => h.textContent.split(' · ')[0]).join(', ')`);
  check(sections === 'Practice scenario, Knowledge sources, Answers, Audio check', `practice preflight sections: ${sections}`);
  await main.evaluate(clickText('Live interview', "document.querySelector('.preflight')"));
  await pause(200);
  const liveSections = await main.evaluate(`[...document.querySelectorAll('.preflight .setting-group')].map((h) => h.textContent.split(' · ')[0]).join(', ')`);
  check(liveSections === 'Interview setup, Knowledge sources, Answers, Audio check', `live preflight sections: ${liveSections}`);
  check(await main.evaluate(`document.querySelector('.preflight').innerText.includes('Computer audio')`), 'no computer-audio check');
  await shot(main, 's8-preflight-live');
  await main.evaluate(clickText('Practice', "document.querySelector('.preflight .segmented')"));
  await main.evaluate(clickText('AI improvises'));
  await pause(200);
  await shot(main, 's8-preflight-practice');
  await main.waitFor(`![...document.querySelectorAll('.preflight button')].find((b) => b.textContent.startsWith('Start practice')).disabled`, 5000, 'start enabled');
  await main.evaluate(clickText('Start practice session'));
  const cockpit = await find((u) => u.endsWith('/cockpit.html'));
  const mode = await cockpit.waitFor(`document.querySelector('.c-modes button.active')?.textContent`, 30000, 'practice plan');
  check(mode.startsWith('AI'), `practice did not start in the chosen mode: ${mode}`);
  check(!(await main.evaluate(`!!document.querySelector('.preflight')`)), 'preflight stayed open');
  log(`Preflight: practice sections [${sections}], live sections [${liveSections}], started in "${mode}" mode`);
  const bg = await cockpit.waitFor(`(() => { const c = document.querySelector('.cockpit'); return c && getComputedStyle(c).backgroundColor !== 'rgba(12, 13, 16, 0.8)' && getComputedStyle(c).backgroundColor; })()`, 10000, 'cockpit appearance');
  check(bg === 'rgba(16, 24, 32, 0.85)', `cockpit background ${bg}`);
  await main.evaluate(`window.copilot.setSettings({ opacity: 0.75 })`);
  await cockpit.waitFor(`getComputedStyle(document.querySelector('.cockpit')).backgroundColor === 'rgba(16, 24, 32, 0.75)'`, 5000, 'live appearance update');
  check(await cockpit.evaluate(`[...document.querySelectorAll('button')].some((b) => b.textContent.startsWith('Solve screen'))`), 'no Solve screen button');
  await cockpit.evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.startsWith('Solve screen')).click()`);
  const notice = await cockpit.waitFor(`[...document.querySelectorAll('.c-banner')].map((b) => b.textContent).find((t) => /screen|屏幕/i.test(t))`, 15000, 'solve-screen feedback');
  const answer = await cockpit.waitFor(`(() => { const a = document.querySelector('.c-answer'); return a && a.innerText.length > 40 && !a.querySelector('.typing') && a.innerText; })()`, 90000, 'screen answer');
  check(/two ?sum|hash|O\(n\)/i.test(answer), `screen answer does not address the test problem: ${answer.slice(0, 200)}`);
  await shot(cockpit, 's7-cockpit');
  log(`Cockpit: background ${bg}, live update to 75%, Solve screen "${notice}" → answer "${answer.replace(/\n+/g, ' ').slice(0, 140)}"`);
  await main.evaluate('window.copilot.endSession()');
  log('PASS');
} catch (error) {
  failed = true;
  log('FAIL', error.message);
} finally {
  app.kill('SIGTERM');
  await pause(2000);
  console.log(readFileSync(logFile, 'utf8').split('\n').filter((l) => /error|Error|\[cockpit\]|\[main\]/.test(l) && !/_TIProperty|imkxpc/.test(l)).slice(-15).join('\n'));
  rmSync(data, { recursive: true, force: true });
  process.exit(failed ? 1 : 0);
}
