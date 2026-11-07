import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';
import { pdfFixture } from './fixtures.mjs';

const [port, directory] = process.argv.slice(2);
const setupCode = (await readFile(join(directory, 'admin-first-login.txt'), 'utf8')).trim();
const documentPath = join(directory, 'workspace-smoke-material.txt');
await writeFile(documentPath, 'A local document for the integration check.\n');
const resumePath = join(directory, 'workspace-smoke-resume.pdf');
await writeFile(resumePath, pdfFixture(['Integration Resume', 'Led a local payments migration']));
const specPath = join(directory, 'workspace-smoke-spec.pdf');
await writeFile(specPath, pdfFixture(Array.from({ length: 2000 }, (_, index) => 'Line ' + index + ' of the physical downlink shared channel specification text'),
  { padBytes: 12 * 1024 * 1024 }));
const adminPassword = 'integration-test-only-admin-password';
const memberPassword = 'integration-test-only-member-password';
let target;
for (let attempt = 0; attempt < 75 && !target; attempt++) {
  try {
    const pages = await fetch('http://127.0.0.1:' + port + '/json/list', { signal: AbortSignal.timeout(1500) }).then((r) => r.json());
    target = pages.find((page) => page.url.includes('/out/renderer/main-window/') && page.url.includes('#/auth/'));
  } catch {}
  if (!target) await pause(400);
}
assert(target, 'The sign-in screen did not open.');

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.onopen = resolve;
  socket.onerror = reject;
});
let lastId = 0;

async function evaluate(expression) {
  const id = ++lastId;
  return new Promise((resolve, reject) => {
    const timer = globalThis.setTimeout(() => reject(Error('Timed out waiting for the renderer.')), 5000);
    socket.onmessage = ({ data }) => {
      const message = JSON.parse(data);
      if (message.id !== id) return;
      clearTimeout(timer);
      if (message.error || message.result.exceptionDetails) {
        reject(Error(message.result?.exceptionDetails?.exception?.description ?? 'Renderer evaluation failed.'));
      } else {
        resolve(message.result.result.value);
      }
    };
    socket.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, returnByValue: true, awaitPromise: true } }));
  });
}

async function waitFor(expression) {
  for (let tries = 0; tries < 20; tries++) {
    const result = await evaluate(expression);
    if (result) return result;
    await pause(250);
  }
  throw Error('Expected UI state did not appear: ' + expression);
}

async function click(label, selector = 'button') {
  await waitFor(`(() => {
    const button = [...document.querySelectorAll(${JSON.stringify(selector)})]
      .find((item) => item.textContent.trim() === ${JSON.stringify(label)} && !item.disabled);
    if (!button) return false;
    button.click();
    return true;
  })()`);
}

async function submit(mode, fields) {
  await waitFor(`document.querySelector('[data-local-auth-form="${mode}"]') !== null`);
  assert(await evaluate(`(() => {
    const form = document.querySelector('[data-local-auth-form="${mode}"]');
    for (const [name, value] of Object.entries(${JSON.stringify(fields)})) form.elements.namedItem(name).value = value;
    form.requestSubmit();
    return [...form.querySelectorAll('input[type=password]')].every(input => !input.value);
  })()`));
}

async function navigate(path, expected) {
  await evaluate(`location.hash = ${JSON.stringify('#' + path)}`);
  await waitFor(`location.hash === ${JSON.stringify('#' + path)} &&
    document.body.innerText.includes(${JSON.stringify(expected)}) &&
    !document.body.innerText.includes("This feature uses your Final Round account")`);
}

async function signOut() {
  await evaluate('window.api.auth.deleteToken().then(() => { location.hash = "#/auth/signin"; })');
  await waitFor('location.hash === "#/auth/signin"');
  assert.equal(await evaluate('window.localAuth.session()'), null);
}

try {
  if (target.url.endsWith('#/auth/minimized')) await evaluate('window.api.window.restore()');
  await waitFor('document.body.innerText.includes("Welcome to Final Round AI")');
  assert.equal(await evaluate('window.localAuth.session()'), null);
  await click('Sign in locally');
  await click('Activate admin');
  await submit('activate', { code: setupCode, newPassword: adminPassword });
  await waitFor('location.hash === "#/app/goals" && Boolean(document.querySelector("[aria-label=Workspace]"))');
  assert.deepEqual(await evaluate('window.localAuth.session()'), { username: 'admin', role: 'admin' });
  assert.equal(await evaluate('window.api.auth.hasRefreshToken()'), true);
  await assert.rejects(readFile(join(directory, 'admin-first-login.txt')), { code: 'ENOENT' });
  assert.equal(await evaluate('window.api.goal.list().then(x => x.list.length)'), 0);

  await navigate('/app/goals/new', 'Create goal');
  await evaluate(`(() => {
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    for (const [id, value] of [['goal-form-role', 'Software Engineer'], ['goal-form-company', 'Local Test Company']]) {
      const field = document.getElementById(id);
      setValue.call(field, value);
      field.dispatchEvent(new Event('input', { bubbles: true }));
    }
  })()`);
  await click('Create goal');
  const goal = await waitFor('window.api.goal.list().then(x => x.list.find(item => item.company === "Local Test Company"))');
  assert.equal(goal.position, 'Software Engineer');
  await waitFor('document.body.innerText.includes("Local Test Company")');

  const document = await evaluate(`window.api.document.upload({kind: "material", filePath: ${JSON.stringify(documentPath)}})`);
  assert.equal(document.filename, 'workspace-smoke-material.txt');
  await evaluate(`window.api.goal.attachDocument({goalId: ${JSON.stringify(goal.id)}, documentId: ${JSON.stringify(document.document_id)}})`);
  assert.equal(await evaluate('window.api.document.list().then(x => x.length)'), 1);
  const resume = await evaluate(`window.api.document.upload({kind: "resume", filePath: ${JSON.stringify(resumePath)}})`);
  assert.deepEqual(await evaluate(`window.api.file.checkUploadContent({filePath: ${JSON.stringify(specPath)}, fileName: "workspace-smoke-spec.pdf"})`), { valid: true });
  const spec = await evaluate(`window.api.document.upload({kind: "material", filePath: ${JSON.stringify(specPath)}})`);
  assert(spec.byte_size > 12 * 1024 * 1024);
  await waitFor('window.api.document.list().then(x => x.length === 3 && x.every(d => d.status === "ready" && d.text_chars > 0))');
  assert(await evaluate(`window.api.document.list().then(x => x.find(d => d.document_id === ${JSON.stringify(spec.document_id)}).text_chars > 100000)`));
  await evaluate(`window.api.goal.setResume({goalId: ${JSON.stringify(goal.id)}, documentId: ${JSON.stringify(resume.document_id)}})`);
  await evaluate('location.reload()');
  await waitFor('Boolean(window.localAuth)');
  await navigate('/app/goals/' + goal.id + '/prep', 'Knowledge sources');
  await waitFor('document.body.innerText.includes("1 Goal-specific") && document.body.innerText.includes("workspace-smoke-material.txt") && document.body.innerText.includes("Pinned to this Goal.")');
  await navigate('/app/library', 'Library');
  await waitFor('document.body.innerText.includes("workspace-smoke-material.txt")');
  await navigate('/app/history', 'History');
  await navigate('/app/settings/defaults', 'Defaults');
  await navigate('/app/settings/privacy', 'Privacy & Stealth');
  assert.equal(await evaluate('window.api.consent.get().then(x => x.share_data)'), false);
  await navigate('/app/settings/account', 'admin · admin');
  await signOut();

  await click('Sign in locally');
  await click('Create account');
  await submit('register', { username: 'test-member', password: memberPassword });
  await waitFor('location.hash === "#/app/goals"');
  assert.deepEqual(await evaluate('window.localAuth.session()'), { username: 'test-member', role: 'member' });
  assert.equal(await evaluate('window.localAuth.listAccounts().then(() => "allowed", () => "denied")'), 'denied');
  assert.equal(await evaluate('window.api.goal.list().then(x => x.list.length)'), 0);
  assert.equal(await evaluate('window.api.document.list().then(x => x.length)'), 0);
  await signOut();
  await click('Sign in locally');
  await submit('signIn', { username: 'admin', password: adminPassword });
  await waitFor('location.hash === "#/app/goals" && document.body.innerText.includes("Local Test Company")');
  console.log(JSON.stringify({ adminActivated: true, adminSignedInAgain: true, originalGoalEditor: true,
    originalLibrary: true, originalHistory: true, originalDefaults: true, originalPrivacy: true,
    localDocumentUpload: true, localDocumentPrepared: true, largePdfOver10MBAnd100kChars: true, goalKnowledgeSources: true,
    accountIsolation: true, memberCannotListAccounts: true }));
} finally {
  socket.close();
}
