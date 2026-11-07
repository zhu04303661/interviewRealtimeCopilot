// IPC for the local account dialog (window.localAuth in the main window).
//
// Accounts and sessions live in the Python backend; this module only checks
// that requests come from the main window, forwards them, and keeps a cached
// copy of the signed-in account and its session token. The cache backs the
// synchronous auth adapter the original app expects (hasRefreshToken,
// getCachedUser, getValidAccessToken), and the token is what the realtime
// interview socket presents in its hello.
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';

const STARTING = 'The local backend is starting. Try again in a moment.';

export function registerLocalAuth({ app, ipcMain, backend, onSignedIn, onSignedOut = () => {} }) {
  let current = null; // { account: { username, role }, token }
  const account = () => current?.account ?? null;

  async function ask(method, path, body) {
    try {
      return await backend.call(method, path, body);
    } catch {
      return { ok: false, error: STARTING };
    }
  }

  async function clearSession() {
    const previous = account();
    current = null;
    await ask('POST', '/local/auth/sign-out', {});
    if (previous) onSignedOut(previous);
  }

  function cachedUser() {
    const user = account();
    return user && { id: 'local:' + user.username, firstName: user.username, lastName: '', email: '', imageUrl: '' };
  }

  // The adapter the original AuthController and HTTP clients use.
  const auth = {
    init: async () => {},
    hasRefreshToken: () => Boolean(account()),
    getValidAccessToken: async () => current?.token ?? null,
    getCachedUser: cachedUser,
    refreshUserInfo: async () => {
      const user = cachedUser();
      if (!user) throw Error('Sign in to your local account first.');
      return user;
    },
    cacheUser: () => {},
    clearSession: () => { void clearSession(); },
    onUserInfoChanged: () => {},
    onSessionExpired: () => {},
  };

  const mainPage = join(app.getAppPath(), 'out/renderer/main-window/index.html');
  const watched = new WeakSet();

  function fromMainWindow(event) {
    const frame = event.senderFrame;
    const url = frame?.url ? URL.parse(frame.url) : null;
    return frame && !frame.parent && url?.protocol === 'file:' && fileURLToPath(url) === mainPage;
  }

  function watch(contents) {
    if (watched.has(contents)) return;
    watched.add(contents);
    // A closed or crashed window must not stay signed in.
    const release = () => {
      if (current) void clearSession();
    };
    contents.once('destroyed', release);
    contents.on('render-process-gone', release);
  }

  function handle(method, action, { signIn = false } = {}) {
    ipcMain.handle('local-auth:' + method, async (event, payload) => {
      if (!fromMainWindow(event)) return { ok: false, error: 'Local accounts are only available in the main window.' };
      const contents = event.sender;
      watch(contents);
      if (signIn && account()) return { ok: false, error: 'Sign out before switching local accounts.' };
      const owner = String(contents.id);
      const result = await action(owner, payload ?? {});
      if (!result?.ok) return { ok: false, error: result?.error ?? 'Local authentication failed.' };
      if (!signIn) return result;
      if (contents.isDestroyed()) {
        await ask('POST', '/local/auth/sign-out', { owner });
        return { ok: false, error: 'The sign-in window closed.' };
      }
      current = result.value;
      onSignedIn();
      return { ok: true, value: current.account };
    });
  }

  handle('status', () => ask('GET', '/local/auth/status'));
  handle('session', async (owner) => {
    const result = await ask('GET', `/local/auth/session?owner=${encodeURIComponent(owner)}`);
    return result.ok ? { ok: true, value: result.value?.account ?? null } : result;
  });
  handle('signIn', (owner, { username, password }) => ask('POST', '/local/auth/sign-in', { owner, username, password }), { signIn: true });
  handle('register', (owner, { username, password }) => ask('POST', '/local/auth/register', { owner, username, password }), { signIn: true });
  handle('activate', (owner, { code, newPassword }) => ask('POST', '/local/auth/activate', { owner, code, newPassword }), { signIn: true });
  handle('listAccounts', (owner) => ask('GET', `/local/auth/accounts?owner=${encodeURIComponent(owner)}`));
  return { account, auth };
}
