// Build the app archive for Final Round Recovered.
//
//   node launch/build/repack.mjs <recovered-root> <path to @electron/asar/lib/asar.js>
//
// Starts from the original app.asar (files from asar-exact/, unpacked natives
// from package/) and changes as little as possible:
//
//   main process   replace vendor services with the Python backend bridge
//                  (app/python-backend.mjs) and local accounts (app/local-auth-ipc.mjs);
//                  turn off telemetry, auto-update and deep links; block every
//                  network request from web contents.
//   preload        expose window.localAuth to the main window.
//   main window    local sign-in, local plan panel, 500 MB upload limit.
//   cockpit        speaker-labelled transcript lines with Chinese↔English
//                  translations, translated extracted questions and AI
//                  interviewer lines.
//
// Every textual patch must match exactly once (replaceOne throws otherwise), so
// a different upstream build fails loudly instead of being patched wrongly.
// Writes launch/build/out/local-workspace.asar and launch/reports/repack.json.
import { createHash } from 'node:crypto';
import { createReadStream, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { Readable } from 'node:stream';
import { pathToFileURL } from 'node:url';

const [root, asarModule] = process.argv.slice(2);
if (!root || !asarModule) throw Error('Usage: node repack.mjs <recovered-root> <@electron/asar/lib/asar.js>');
const { createPackageFromStreams, extractFile, getRawHeader } = await import(pathToFileURL(asarModule));

const launch = join(root, 'launch');
const appSources = join(launch, 'app');
const original = join(root, 'package/Resources/app.asar');
const exact = join(root, 'asar-exact');
const outputDirectory = join(launch, 'build/out');
const destination = join(outputDirectory, 'local-workspace.asar');

function replaceOne(source, anchor, replacement) {
  if (source.split(anchor).length !== 2) throw Error('Expected one source anchor: ' + anchor.slice(0, 160));
  return source.replace(anchor, () => replacement);
}

function patcher(source) {
  const file = { text: source };
  file.replace = (anchor, replacement) => { file.text = replaceOne(file.text, anchor, replacement); };
  file.cut = (startAnchor, endAnchor, replacement = '') => {
    const start = file.text.indexOf(startAnchor);
    const end = file.text.indexOf(endAnchor, start);
    if (start < 0 || end < 0) throw Error('Missing range: ' + startAnchor.slice(0, 80));
    file.text = file.text.slice(0, start) + replacement + file.text.slice(end);
  };
  return file;
}

const lines = (...parts) => parts.join('\n');

// ── package.json: start through the bootstrap that isolates the profile ────
const packageJson = JSON.parse(readFileSync(join(exact, 'package.json'), 'utf8'));
const entry = packageJson.main.replace(/^\.\//, '');
packageJson.main = './recovered-bootstrap.mjs';

// ── main process ─────────────────────────────────────────────────────────────
const main = patcher(lines(
  'import { registerLocalAuth } from "../../local/local-auth-ipc.mjs";',
  'import { startPythonBackend } from "../../local/python-backend.mjs";',
  '',
) + readFileSync(join(exact, entry), 'utf8'));

// Identity, telemetry and local preference stores.
main.replace('app.name = Branding.productName;', 'app.name = "Final Round Recovered";');
main.replace('  initializeSentry();\n', '');
main.replace('  analyticsService.initialize();\n', '');
main.replace('const store = new EncryptedStorage("device");', lines(
  'function localPreferenceStore(name) {',
  '  const store = new Store({ name });',
  '  return { getJSON: (key) => store.get(key), setJSON: (key, value) => store.set(key, value) };',
  '}',
  'const store = new Store({ name: "local-device" });',
));
main.replace('new EncryptedStorage("audio-indicator")', 'localPreferenceStore("local-audio-indicator")');
main.replace('new EncryptedStorage("shortcut-state")', 'localPreferenceStore("local-shortcut-state")');
main.cut('  if (Env.isPackaged) {', '  const meetingAppMonitorService = ');   // auto-updater
main.replace('  const oauthSession = new OAuthSession();\n', '');

// Start the Python backend and the local account service in place of vendor auth.
main.replace('  const authStorage = new EncryptedStorage(AuthConfig.storage.namespace);\n  const authService = new AuthService(authStorage);', lines(
  // Data lives in a stable folder outside the app bundle and its profile, so
  // rebuilding or reinstalling the app never loses it. FRLOCAL_DATA_DIR
  // redirects everything (tests use a temporary folder).
  '  const localData = process.env.FRLOCAL_DATA_DIR || join(app.getPath("appData"), "Final Round Recovered Local Data");',
  '  workspaceBackend = startPythonBackend({',
  '    app, session,',
  '    accountsDir: process.env.FINAL_ROUND_LOCAL_AUTH_DIR || (process.env.FRLOCAL_DATA_DIR ? join(localData, "accounts")',
  '      : join(app.getPath("appData"), "Final Round Recovered Local Accounts")),',
  '    workspaceDir: join(localData, "workspace"),',
  '    legacyWorkspaceDir: process.env.FRLOCAL_DATA_DIR ? undefined : join(app.getPath("userData"), "workspace"),',
  '  });',
  '  const { auth: authService } = registerLocalAuth({',
  '    app, ipcMain, backend: workspaceBackend,',
  '    onSignedIn: () => windowManager.restoreWindow("workspace"),',
  '  });',
));

// Every vendor HTTP client sends its requests to the bridge.
main.replace('function createKyClient(options, authProvider) {', lines(
  'let workspaceBackend;',
  'async function localWorkspaceFetch(input, init) {',
  '  return workspaceBackend.fetch(new Request(input, init));',
  '}',
  'function createKyClient(options, authProvider) {',
));
main.replace('    fetch: (input, init) => net.fetch(input instanceof URL ? input.href : input, init),\n    // exactOptionalPropertyTypes',
  '    fetch: localWorkspaceFetch,\n    // exactOptionalPropertyTypes');
main.replace('"https://prod-finalroundai.frai.pro/api"', '"https://final-round-recovered.invalid/api"');
main.replace('"https://prod-finalroundai.frai.pro"', '"https://final-round-recovered.invalid"');
main.replace('await net.fetch(signedUrlData.signedUrl, {', 'await localWorkspaceFetch(signedUrlData.signedUrl, {');
main.replace('await net.fetch(uploadUrl, {', 'await localWorkspaceFetch(uploadUrl, {');
main.replace('constructor(fetchFn = (url, init) => net.fetch(url, init))', 'constructor(fetchFn = localWorkspaceFetch)');

// The interview socket goes to the Python realtime engine.
main.replace('  const realtimeBackend = new RealtimeBackend(analyticsService);',
  '  const realtimeBackend = new RealtimeBackend(analyticsService, (url) => workspaceBackend.openSocket(url));');

// Show the backend's reason when a session cannot start.
main.replace('return new ProceduralError("Could not start the interview session", {',
  'return new ProceduralError((await readErrorDetail(error.response)) || "Could not start the interview session", {');
main.replace('          ...toastForLaunchErrorKind(kind),', lines(
  '          ...toastForLaunchErrorKind(kind),',
  '          ...(kind === "SESSION_CREATE_FAILED" && snapshot.context.error?.message ? { description: snapshot.context.error.message } : {}),',
));

// Library uploads: import by path (files up to 500 MB never pass through memory).
main.replace(lines(
  '    const data = await readFile(request.filePath);',
  '    const filename = basename(request.filePath);',
  '    const mime = MIME_BY_EXT$1[extname(filename).toLowerCase()] ?? "application/octet-stream";',
  '    const form = new FormData();',
  '    form.append("kind", request.kind);',
  '    form.append("file", new Blob([new Uint8Array(data)], { type: mime }), filename);',
  '    const response = await this.httpClient.post("v3/documents", { body: form });',
  '    return unwrapRaw(response);',
), lines(
  '    const filename = basename(request.filePath);',
  '    const mime = MIME_BY_EXT$1[extname(filename).toLowerCase()] ?? "application/octet-stream";',
  '    return workspaceBackend.importDocument({ kind: request.kind, filePath: request.filePath, filename, contentType: mime });',
));
// The original pre-upload check parses PDFs in the main process (where pdf.js
// cannot load) and caps text at 100,000 characters; the backend prepares and
// validates documents itself.
main.replace(lines(
  '  const ext = getExtension(params.fileName);',
  '  if (ext === "pdf") return validatePdfText(params.filePath);',
  '  if (ext === "docx") return validateDocxText(params.filePath);',
  '  return { valid: true };',
), '  return { valid: true };');

// Vendor OAuth sign-in and deep links are replaced by the local account dialog.
main.cut('  const initiateLoginUseCase = new InitiateLoginUseCase(', '  new WindowController(ipcGateway, windowManager).register();', lines(
  '  new AuthController(ipcGateway, authService, logoutUseCase, { execute: async () => {',
  '    throw new ProceduralError("Sign in from the local account dialog.");',
  '  } }, null).register();',
  '',
));
main.replace('    windowManager.onReadyToShow(() => {\n      deepLinkHandler.processPendingDeepLink();\n    });\n', '');
main.replace('    deepLinkHandler.checkLaunchUrl();\n', '');
// Web contents may not reach the network at all; the backend is reached from the main process.
main.replace('    setupCspHandler();', lines(
  '    setupCspHandler();',
  '    session.defaultSession.webRequest.onBeforeRequest({ urls: ["http://*/*", "https://*/*", "ws://*/*", "wss://*/*"] }, (_details, callback) => callback({ cancel: true }));',
));

// ── preload: window.localAuth for the account dialog ────────────────────────
const preloadPath = 'out/preload/index.cjs';
const preload = readFileSync(join(exact, preloadPath), 'utf8') + `
async function invokeLocalAuth(method, payload) {
  const result = await electron.ipcRenderer.invoke("local-auth:" + method, payload);
  if (!result.ok) throw new Error(result.error);
  return result.value;
}
electron.contextBridge.exposeInMainWorld("localAuth", {
  status: () => invokeLocalAuth("status"),
  session: () => invokeLocalAuth("session"),
  signIn: (input) => invokeLocalAuth("signIn", input),
  register: (input) => invokeLocalAuth("register", input),
  activate: (input) => invokeLocalAuth("activate", input),
  listAccounts: () => invokeLocalAuth("listAccounts"),
});
`;

// ── main window renderer ────────────────────────────────────────────────────
const rendererPath = 'out/renderer/assets/index-CQEWRyAV.js';
const renderer = patcher('import { createLocalAuthUi } from "./local-auth-ui.mjs";\n' + readFileSync(join(exact, rendererPath), 'utf8'));
renderer.replace('  const checkSession = reactExports.useCallback(async () => {\n    try {', lines(
  '  const checkSession = reactExports.useCallback(async () => {',
  '    try {',
  '      if (await window.localAuth.session()) {',
  '        void navigate("/app/goals", { replace: true });',
  '        return;',
  '      }',
));
{
  // Swap the vendor "Sign in" button for the local account entry.
  const text = renderer.text;
  const start = text.indexOf('const SignInPage = () => {');
  const end = text.indexOf('const ConfirmDeleteModal$1', start);
  if (start < 0 || end < 0) throw Error('Missing original sign-in page');
  let page = text.slice(start, end);
  const buttonStart = page.lastIndexOf('/* @__PURE__ */ jsxRuntimeExports.jsxs(Button, {', page.indexOf('onClick: handleSignIn'));
  const buttonEnd = page.indexOf('/* @__PURE__ */ jsxRuntimeExports.jsx(\n            DocsLink,', buttonStart);
  if (buttonStart < 0 || buttonEnd < 0) throw Error('Missing original sign-in button');
  page = page.slice(0, buttonStart) + lines(
    '/* @__PURE__ */ jsxRuntimeExports.jsx(LocalSignInEntry, { onSignedIn: () => {',
    '            queryClient.clear();',
    '            void navigate("/app/goals", { replace: true });',
    '          } }),',
    '          ',
  ) + page.slice(buttonEnd);
  const markup = page.indexOf('  return /* @__PURE__ */ jsxRuntimeExports.jsxs(');
  if (markup < 0) throw Error('Missing original sign-in layout');
  renderer.text = text.slice(0, start) + 'const SignInPage = () => {\n  const navigate = useNavigate();\n' + page.slice(markup) + text.slice(end);
}
renderer.replace('const router = createHashRouter([', lines(
  'const { LocalSignInEntry, LocalAccountPanel } = createLocalAuthUi({',
  '  React: reactExports, Button, Input, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,',
  '});',
  'const AccountRoute = () => {',
  '  const [account, setAccount] = reactExports.useState(null);',
  '  reactExports.useEffect(() => { void window.localAuth.session().then(setAccount); }, []);',
  '  return jsxRuntimeExports.jsxs("div", { className: "space-y-6", children: [',
  '    jsxRuntimeExports.jsx(AccountPanel, {}),',
  '    account && jsxRuntimeExports.jsx(LocalAccountPanel, { account }),',
  '  ] });',
  '};',
  'const router = createHashRouter([',
));
renderer.replace('path: "account", element: /* @__PURE__ */ jsxRuntimeExports.jsx(AccountPanel, {})',
  'path: "account", element: /* @__PURE__ */ jsxRuntimeExports.jsx(AccountRoute, {})');
// Plan and account pages describe the local workspace instead of subscriptions.
renderer.replace('Your FinalRound account is closed and your interview data is permanently deleted: Sessions, Debriefs, documents, playbooks, coaching memory, recordings, and your voice sample. Any subscription is canceled. There is no undo.',
  'Permanently delete this local account and its interview data. There is no undo.');
renderer.replace('const showUpgradeCard = knownFreePaymentStatus && subscriptionInfo?.has_subscription === false;', 'const showUpgradeCard = false;');
renderer.replace('children: isPaid ? "PRO" : "FREE"', 'children: "LOCAL"');
renderer.replace('jsxRuntimeExports.jsx(SubscriptionsPanel, { userId: userInfo.id })', 'jsxRuntimeExports.jsx(LocalPlanPanel, {})');
renderer.replace('const PlanPage = () => {', lines(
  'const LocalPlanPanel = () => jsxRuntimeExports.jsxs("section", { className: "space-y-2", children: [',
  '  jsxRuntimeExports.jsx("h3", { className: "text-body text-text-1 font-semibold", children: "Local workspace" }),',
  '  jsxRuntimeExports.jsx("p", { className: "text-body-sm text-text-2", children: "This Mac stores your workspace. Live AI uses the OpenAI project configured in the local backend." }),',
  '] });',
  'const OnlinePlanPage = () => {',
));
renderer.replace('const PlanPageHeader = ({', lines(
  'const PlanPage = () => jsxRuntimeExports.jsx("div", { className: "mx-auto w-full max-w-5xl px-7 py-6", children: jsxRuntimeExports.jsx(LocalPlanPanel, {}) });',
  'const PlanPageHeader = ({',
));
renderer.replace('disabled: deleteAccount.isPending,\n          onClick:', 'disabled: true,\n          onClick:');
renderer.replace('Permanently deletes your account and its data.', 'Account deletion is unavailable in this local build.');
// Library upload limit.
renderer.replace('const MAX_BYTES = 10 * 1024 * 1024;', 'const MAX_BYTES = 500 * 1024 * 1024;');
renderer.replace('message: `Up to 10 MB. Yours is ${mb} MB. Try compressing the file.`', 'message: `Up to 500 MB. Yours is ${mb} MB.`');
renderer.replace('PDF, DOCX, TXT, or MD, up to 10 MB.', 'PDF, DOCX, TXT, or MD, up to 500 MB.');
renderer.replace('PDF or DOCX, up to 10 MB.', 'PDF or DOCX, up to 500 MB.');

// ── cockpit (the in-interview window) ───────────────────────────────────────
const cockpitPath = 'out/renderer/assets/cockpit-TfUMhx0o.js';
const cockpit = patcher(readFileSync(join(exact, cockpitPath), 'utf8'));
// Store: transcript lines ("utterance" entries) and their translations.
cockpit.replace('        candidateSegments: {},\n        setInterviewerSource:', lines(
  '        candidateSegments: {},',
  '        translations: {},',
  '        appendUtterance: (segmentId, speaker, text2, seq) => set2((draft) => {',
  '          if (!segmentId || !text2) return;',
  '          if (draft.entries.some((e) => e.kind === "utterance" && e.segmentId === segmentId)) return;',
  '          draft.entries.push({ kind: "utterance", key: `u:${segmentId}`, segmentId, speaker, text: text2, seq, translation: draft.translations[segmentId] ?? "" });',
  '        }),',
  '        setTranslation: (segmentId, text2) => set2((draft) => {',
  '          if (!segmentId || !text2) return;',
  '          draft.translations[segmentId] = text2;',
  '          const entry = draft.entries.find((e) => e.kind === "utterance" && e.segmentId === segmentId || e.kind === "say" && e.sayId === segmentId);',
  '          if (entry) entry.translation = text2;',
  '        }),',
  '        setInterviewerSource:',
));
cockpit.replace('          draft.candidateSegments = {};\n        })', '          draft.candidateSegments = {};\n          draft.translations = {};\n          draft.practicePlan = null;\n        })');
cockpit.replace('          draft.entries.push({ kind: "say", key: key2, sayId, text: text2, seq });',
  '          draft.entries.push({ kind: "say", key: key2, sayId, text: text2, seq, translation: draft.translations[sayId] ?? "" });');
// Feed: final transcripts become speaker-labelled lines; translations attach to them.
cockpit.replace(lines(
  '        if (role === "interviewer") {',
  '          if (data?.["final"] === true) store.pushFinal(str(data, "text"));',
  '          else store.setInterim(str(data, "text"));',
  '          return;',
  '        }',
), lines(
  '        if (role === "interviewer") {',
  '          if (data?.["final"] === true) {',
  '            store.appendUtterance(str(data, "segment_id"), "interviewer", str(data, "text"), frame.seq);',
  '            store.clearInterim();',
  '          } else store.setInterim(str(data, "text"));',
  '          return;',
  '        }',
));
cockpit.replace(lines(
  '        if (role === "unknown" && data?.["final"] === true) {',
  '          store.holdUnknownFinal(str(data, "segment_id"), str(data, "text"));',
  '        }',
  '        return;',
  '      }',
), lines(
  '        if (role === "interviewee" && data?.["final"] === true) {',
  '          store.appendUtterance(str(data, "segment_id"), "me", str(data, "text"));',
  '          return;',
  '        }',
  '        if (role === "unknown" && data?.["final"] === true) {',
  '          store.holdUnknownFinal(str(data, "segment_id"), str(data, "text"));',
  '        }',
  '        return;',
  '      }',
  '      case "transcript.translation":',
  '        store.setTranslation(str(data, "segment_id"), str(data, "text"));',
  '        return;',
));
// Practice: play the GPT-Live interviewer's voice (24 kHz PCM16 chunks) gaplessly.
cockpit.replace('function useConversationFeed(activeSessionId) {', lines(
  'const localInterviewerVoice = (() => {',
  '  let context = null;',
  '  let nextStart = 0;',
  '  const playing = new Set();',
  '  return {',
  '    play(base64) {',
  '      if (!base64) return;',
  '      context ??= new AudioContext({ sampleRate: 24000 });',
  '      if (context.state === "suspended") void context.resume();',
  '      const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));',
  '      const samples = new Int16Array(bytes.buffer, 0, bytes.length >> 1);',
  '      if (samples.length === 0) return;',
  '      const buffer = context.createBuffer(1, samples.length, 24000);',
  '      const channel = buffer.getChannelData(0);',
  '      for (let index = 0; index < samples.length; index++) channel[index] = samples[index] / 32768;',
  '      const source = context.createBufferSource();',
  '      source.buffer = buffer;',
  '      source.connect(context.destination);',
  '      nextStart = Math.max(nextStart, context.currentTime + 0.04);',
  '      source.start(nextStart);',
  '      nextStart += buffer.duration;',
  '      playing.add(source);',
  '      source.onended = () => playing.delete(source);',
  '    },',
  '    stop() {',
  '      for (const source of playing) {',
  '        try { source.stop(); } catch {}',
  '      }',
  '      playing.clear();',
  '      nextStart = 0;',
  '    },',
  '  };',
  '})();',
  'function useConversationFeed(activeSessionId) {',
));
cockpit.replace('      case "say": {\n        const say = parseSay(data);', lines(
  '      case "say.audio":',
  '        localInterviewerVoice.play(str(data, "audio"));',
  '        return;',
  '      case "say.audio.clear":',
  '        localInterviewerVoice.stop();',
  '        return;',
  '      case "say": {\n        const say = parseSay(data);',
));
cockpit.replace('      case "session.ended":\n        store.setEndReason(str(data, "reason"));',
  '      case "session.ended":\n        localInterviewerVoice.stop();\n        store.setEndReason(str(data, "reason"));');
cockpit.replace('    text: str(data, "utterance"),\n    decision: str(data, "decision"),',
  '    text: str(data, "utterance"),\n    translation: str(data, "translation"),\n    decision: str(data, "decision"),');
// Components: a translation line under interviewer text, and the transcript line itself.
const translationLine = 'translation && /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "text-body-sm text-text-3 mt-1 break-words whitespace-pre-wrap", lang: "zh", children: translation })';
cockpit.replace('const SayBubble = ({ text: text2, personaName, onSuggestAnswer, busy }) =>', 'const SayBubble = ({ text: text2, translation, personaName, onSuggestAnswer, busy }) =>');
cockpit.replace('  /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "text-question text-text-2 mt-1.5 break-words whitespace-pre-wrap", children: text2 || "(no transcript)" }),\n  onSuggestAnswer &&',
  '  /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "text-question text-text-2 mt-1.5 break-words whitespace-pre-wrap", children: text2 || "(no transcript)" }),\n  ' + translationLine + ',\n  onSuggestAnswer &&');
cockpit.replace('const NoticeLine = ({ text: text2 }) =>', lines(
  'const UtteranceBubble = ({ speaker, text: text2, translation, onSuggestAnswer, busy }) => speaker === "interviewer" ? /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "px-4 py-3", children: /* @__PURE__ */ jsxRuntimeExports.jsxs(InterviewerVoice, { children: [',
  '  /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex items-center gap-2", children: /* @__PURE__ */ jsxRuntimeExports.jsx(TaxonomyStamp, { children: "Interviewer · 面试官" }) }),',
  '  /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "text-question text-text-2 mt-1.5 break-words whitespace-pre-wrap", children: text2 }),',
  '  ' + translationLine + ',',
  // Ask for a hint on any interviewer line, e.g. when it was not recognised as a question.
  '  onSuggestAnswer && /* @__PURE__ */ jsxRuntimeExports.jsx(Button, { variant: "ghost", disabled: busy, onClick: onSuggestAnswer, className: "text-status mt-2 h-7 rounded-md px-2 font-mono font-medium", children: "Suggest answer · 生成回答" })',
  '] }) }) : /* @__PURE__ */ jsxRuntimeExports.jsxs("div", { className: "px-4 py-3", children: [',
  '  /* @__PURE__ */ jsxRuntimeExports.jsx("div", { className: "flex items-center gap-2", children: /* @__PURE__ */ jsxRuntimeExports.jsx(TaxonomyStamp, { children: "You · 我" }) }),',
  '  /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "text-question text-text-3 mt-1.5 break-words whitespace-pre-wrap", children: text2 })',
  '] });',
  'const NoticeLine = ({ text: text2 }) =>',
));
// The extracted question card shows its translation and a clearer label.
cockpit.replace('      /* @__PURE__ */ jsxRuntimeExports.jsx(TaxonomyStamp, { children: "Interviewer" }),\n      !isIgnore',
  '      /* @__PURE__ */ jsxRuntimeExports.jsx(TaxonomyStamp, { children: "Question · 问题" }),\n      !isIgnore');
cockpit.replace('    /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "text-question text-text-2 mt-1.5 break-words whitespace-pre-wrap", children: verdict.text || "(no transcript)" }),\n    decision === "await_more"',
  '    /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "text-question text-text-2 mt-1.5 break-words whitespace-pre-wrap", children: verdict.text || "(no transcript)" }),\n    verdict.translation && /* @__PURE__ */ jsxRuntimeExports.jsx("p", { className: "text-body-sm text-text-3 mt-1 break-words whitespace-pre-wrap", children: verdict.translation }),\n    decision === "await_more"');
// Timeline rendering and state derivation know the new entry kind.
cockpit.replace('            text: entry.text,\n            personaName,', '            text: entry.text,\n            translation: entry.translation,\n            personaName,');
cockpit.replace('      if (entry.kind === "notice") {\n        return /* @__PURE__ */ jsxRuntimeExports.jsx(NoticeLine', lines(
  '      if (entry.kind === "utterance") {',
  '        return /* @__PURE__ */ jsxRuntimeExports.jsx(UtteranceBubble, { speaker: entry.speaker, text: entry.text, translation: entry.translation, busy: answerStreaming,',
  '          ...entry.speaker === "interviewer" && entry.seq !== void 0 && !attemptedGateSeqs.has(entry.seq) ? { onSuggestAnswer: () => onSuggestAnswer(entry) } : {} }, entry.key);',
  '      }',
  '      if (entry.kind === "notice") {\n        return /* @__PURE__ */ jsxRuntimeExports.jsx(NoticeLine',
));
cockpit.replace('lastEntry.kind === "say" || lastEntry.kind === "candidate" || lastEntry.kind === "solve" ?',
  'lastEntry.kind === "say" || lastEntry.kind === "candidate" || lastEntry.kind === "utterance" || lastEntry.kind === "solve" ?');
// Practice question panel: the prepared questions, which were asked, the
// current one, a mode switch (sequential / random / AI) and click-to-jump.
// Commands travel on the answer-request channel with a "practice.*" intent.
cockpit.replace('        unknownFinals: {},\n        interviewerSource: null,', lines(
  '        unknownFinals: {},',
  '        practicePlan: null,',
  '        setPracticePlan: (plan) => set2((draft) => { draft.practicePlan = plan; }),',
  '        interviewerSource: null,',
));
cockpit.replace('      case "transcript.translation":', lines(
  '      case "practice.plan":',
  '        if (data && Array.isArray(data.questions)) store.setPracticePlan(data);',
  '        return;',
  '      case "transcript.translation":',
));
cockpit.replace('const CockpitConversationFeed = ({', lines(
  'const PRACTICE_MODES = [["sequential", "Order · 顺序"], ["random", "Random · 随机"], ["ai", "AI · 临场"]];',
  'const PracticePanel = () => {',
  '  const plan = useConversationStore((s) => s.practicePlan);',
  '  const [open, setOpen] = reactExports.useState(true);',
  '  if (!plan) return null;',
  '  const asked = new Set(plan.asked ?? []);',
  '  const jsx = jsxRuntimeExports.jsx, jsxs = jsxRuntimeExports.jsxs;',
  '  const send = (intent, utterance, gateSeq) => void requestAnswer({ utterance, intent, ...(gateSeq !== void 0 ? { gateSeq } : {}) });',
  '  return jsxs("div", { className: "no-drag border-hairline bg-bg shrink-0 border-b px-4 py-2", children: [',
  '    jsxs("button", { type: "button", onClick: () => setOpen(!open), className: "text-text-2 flex w-full items-center justify-between font-mono text-xs", children: [',
  '      jsx("span", { children: `Practice questions · 练习题  ${asked.size}/${plan.questions.length}` }),',
  '      jsx("span", { children: open ? "▾" : "▸" }),',
  '    ] }),',
  '    open && jsx("div", { className: "mt-2 flex gap-1", children: PRACTICE_MODES.map(([mode, label]) => jsx(Button, { variant: plan.mode === mode ? "secondary" : "ghost", size: "xs", onClick: () => send("practice.mode", mode), className: "font-mono", children: label }, mode)) }),',
  // Inline sizing: the app's stylesheet only ships the utility classes the original UI uses.
  '    open && jsx("ol", { className: "mt-2", style: { maxHeight: "28vh", overflowY: "auto" }, children: plan.questions.map((q) => jsx("li", { children: jsxs("button", {',
  '      type: "button", title: q.question, onClick: () => send("practice.goto", "", q.index),',
  '      className: `w-full truncate rounded px-1.5 py-1 text-left text-xs ${plan.current === q.index ? "bg-surface-2 text-text-1" : asked.has(q.index) ? "text-text-3" : "text-text-2"} hover:bg-surface-2`,',
  '      children: [jsx("span", { className: "mr-1 font-mono", children: plan.current === q.index ? "▶" : asked.has(q.index) ? "✓" : `${q.index + 1}.` }), q.topic ? `${q.topic} — ${q.question}` : q.question],',
  '    }) }, q.index)) }),',
  '  ] });',
  '};',
  'const CockpitConversationFeed = ({',
));
// Rendered in the window's fixed area between the header and the scrolling feed.
cockpit.replace('          headerContent,\n          guideContent,\n          singlePane ?',
  '          headerContent,\n          /* @__PURE__ */ jsxRuntimeExports.jsx(PracticePanel, {}),\n          guideContent,\n          singlePane ?');

// ── assemble the archive ────────────────────────────────────────────────────
const patched = new Map([
  ['package.json', Buffer.from(JSON.stringify(packageJson, null, 2) + '\n')],
  [entry, Buffer.from(main.text)],
  [preloadPath, Buffer.from(preload)],
  [rendererPath, Buffer.from(renderer.text)],
  [cockpitPath, Buffer.from(cockpit.text)],
]);
const additions = new Map([
  ['recovered-bootstrap.mjs', readFileSync(join(appSources, 'bootstrap.mjs'))],
  ['out/renderer/assets/local-auth-ui.mjs', readFileSync(join(appSources, 'local-auth-ui.mjs'))],
  ['local/local-auth-ipc.mjs', readFileSync(join(appSources, 'local-auth-ipc.mjs'))],
  ['local/python-backend.mjs', readFileSync(join(appSources, 'python-backend.mjs'))],
]);
const vendor = join(appSources, 'vendor/undici');
for (const file of readdirSync(vendor, { recursive: true })) {
  const path = join(vendor, file);
  if (statSync(path).isFile()) additions.set('local/' + relative(appSources, path), readFileSync(path));
}

const streams = [];
const copied = [];
const missing = [];
function addFile(path, contents, unpacked, mode, size) {
  streams.push({ path, type: 'file', unpacked, stat: { size, mode }, streamGenerator: contents });
}
function addOriginal(entries, prefix = '') {
  for (const [name, item] of Object.entries(entries)) {
    const path = prefix + name;
    if (item.files) {
      streams.push({ path, type: 'directory', unpacked: Boolean(item.unpacked) });
      addOriginal(item.files, path + '/');
      continue;
    }
    if (item.link) throw Error('Unexpected ASAR symlink: ' + path);
    const unpacked = Boolean(item.unpacked);
    const source = join(unpacked ? original + '.unpacked' : exact, path);
    const stat = statSync(source, { throwIfNoEntry: false });
    if (!stat) {
      // Natives for other platforms are absent from the macOS DMG.
      if (!unpacked) throw Error('Missing archived file: ' + path);
      missing.push(path);
      continue;
    }
    const replacement = patched.get(path);
    addFile(path, () => replacement ? Readable.from([replacement]) : createReadStream(source),
      unpacked, item.executable ? stat.mode | 0o100 : stat.mode, replacement?.length ?? stat.size);
    copied.push({ path, source, replacement });
  }
}
addOriginal(getRawHeader(original).header.files);
for (const [path, bytes] of additions) addFile(path, () => Readable.from([bytes]), false, 0o644, bytes.length);
mkdirSync(outputDirectory, { recursive: true });
await createPackageFromStreams(destination, streams);

// Verify every file in the new archive byte for byte.
for (const { path, source, replacement } of copied) {
  if (!extractFile(destination, path).equals(replacement ?? readFileSync(source))) throw Error('Repacked content mismatch: ' + path);
}
for (const [path, bytes] of additions) {
  if (!extractFile(destination, path).equals(bytes)) throw Error('New file mismatch: ' + path);
}
const report = {
  archive: relative(root, destination),
  headerSha256: createHash('sha256').update(getRawHeader(destination).headerString).digest('hex'),
  unchangedOriginalFiles: copied.length - patched.size,
  patched: [...patched.keys()],
  added: [...additions.keys()].filter((path) => !path.startsWith('local/vendor/')),
  vendored: 'undici (' + [...additions.keys()].filter((path) => path.startsWith('local/vendor/')).length + ' files)',
  missingOtherPlatformNatives: missing.length,
};
mkdirSync(join(launch, 'reports'), { recursive: true });
writeFileSync(join(launch, 'reports/repack.json'), JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report));
