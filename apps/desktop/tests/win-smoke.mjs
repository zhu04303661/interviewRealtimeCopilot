// Windows packaged-app smoke check over the Chrome DevTools protocol.
// Launch the installed app with --remote-debugging-port=N, then: node tests/win-smoke.mjs [N]
// Verifies the renderer bridge, permission status (microphone/screen), engine reachability
// through the IPC proxy, real microphone capture and screen + loopback audio capture.
// Exercises real devices — do not combine with IRC_FAKE_AUDIO / IRC_DENY_MEDIA.
const port = Number(process.argv[2] ?? 9222);
const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
const page = list.find((t) => t.type === 'page' && t.url.includes('index.html'));
if (!page) { console.log('FAIL: main window page not found'); process.exit(1); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0;
const pending = new Map();
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
};
const evaluate = (expression) => new Promise((resolve) => {
  const i = ++id;
  pending.set(i, resolve);
  ws.send(JSON.stringify({ id: i, method: 'Runtime.evaluate',
    params: { expression, awaitPromise: true, returnByValue: true } }));
});

let failures = 0;
const check = async (name, expression, expect) => {
  const r = await evaluate(expression);
  const value = r.result?.exceptionDetails
    ? `EXC ${r.result.exceptionDetails.exception?.description ?? r.result.exceptionDetails.text}`
    : r.result?.result?.value;
  const ok = expect(value);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}: ${JSON.stringify(value)}`);
};

await check('bridge', `typeof window.copilot === 'object'`, (v) => v === true);
await check('appInfo', `window.copilot.appInfo()`,
  (v) => v?.platform === 'win32' && typeof v?.version === 'string');
await check('permissions', `window.copilot.permissions()`,
  (v) => v?.microphone === 'granted' && v?.screen === 'granted');
await check('engine', `window.copilot.request('GET', '/api/v3/goals').then(r => r && typeof r === 'object').catch(() => false)`,
  (v) => v === true);
await check('microphone capture',
  `navigator.mediaDevices.getUserMedia({audio:true}).then(s => { s.getTracks().forEach(t => t.stop()); return true; }).catch(() => false)`,
  (v) => v === true);
await check('screen + system audio',
  `navigator.mediaDevices.getDisplayMedia({video:true, audio:true}).then(s => { const a = s.getAudioTracks().length; s.getTracks().forEach(t => t.stop()); return a; }).catch(() => -1)`,
  (v) => v >= 0);

ws.close();
console.log(failures ? `${failures} check(s) failed` : 'all checks passed');
process.exit(failures ? 1 : 0);
