# Final Round Recovered — working notes

## Layout
- `launch/backend/` — Python 3.12 backend (`frlocal`, managed by uv). All vendor-server behaviour lives here.
- `launch/app/` — Electron-side JS packed into the ASAR (bridge to the backend, local-account IPC/UI, bootstrap).
- `launch/build/repack.mjs` — patches the original bundle (`asar-exact/`, `package/`); every anchor must match exactly once.
- `launch/tests/` — packaged-app end-to-end tests (Chrome DevTools protocol).
- `launch/legacy/` — superseded code and logs; do not build from it.
- Never edit `asar-exact/`, `package/`, `readable-js/`, `evidence/` (recovered originals).

## Commands
- Backend tests: `cd launch/backend && uv run pytest -q` (uses a fake OpenAI; no network).
- Lint: `cd launch/backend && uvx ruff check src tests`.
- Build: `sh launch/build/build.sh` (needs `@electron/asar` 4.2.0 in the npx cache or `ASAR_MODULE`).
- Stage into a scratch copy: `sh launch/build/stage.sh "<copy>/Final Round Recovered.app"`.
- Install into the real app (quits it, backs up to `launch/pre-<name>/`): `sh launch/build/install.sh <name>`.
- Desktop e2e on a scratch copy: launch it with `--remote-debugging-port=N`,
  `FRLOCAL_BACKEND_DIR=<launch/backend>`, `FINAL_ROUND_LOCAL_AUTH_DIR=<fresh dir provisioned by
  uv run python -m frlocal provision-admin DIR>`, then `node launch/tests/app-e2e.mjs N DIR`.
- Cockpit e2e additionally needs `uv run python -m tests.fake_openai_server`, `FRLOCAL_OPENAI_BASE`,
  `OPENAI_API_KEY=test-key`, microphone permission for the current signature, and launching via
  `open -n --env …` so macOS attributes permissions to the app.

## Gotchas
- The Devin shell sets `ELECTRON_RUN_AS_NODE=1`; unset it before launching the app.
- Sign with the keychain identity "Final Round Recovered Local Signing" (stage.sh does) so macOS permissions survive rebuilds.
- Always set `FRLOCAL_DATA_DIR` to a temp dir for scratch/e2e runs; the default is the user's real data in
  `~/Library/Application Support/Final Round Recovered Local Data`.
- `quit-recovered.sh` quits every recorded instance; never overwrite `app.asar` of a running app.
