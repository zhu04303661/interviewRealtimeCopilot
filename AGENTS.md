# Interview Realtime Copilot — working notes

## Layout
- `engine/` — local Python 3.12 engine (package `frlocal`, uv): accounts, goals, document preparation, retrieval,
  realtime interview (transcription, translation, question extraction, answer hints, speech-to-speech practice).
- `apps/desktop/` — Electron 45 + React 19 + TypeScript desktop app. `src/main` starts the engine and owns windows/IPC,
  `src/preload` is the only renderer bridge (`window.copilot`), `src/renderer` has the main window and the cockpit.
- `web/` — website + cloud service (`web/server/irc_web`): accounts, Stripe, device tokens, metered OpenAI relay
  (`relay.py`), allowances/credit/usage/prices and the encrypted OpenAI key (`billing.py`), admin CLI (`admin.py`).
  The app signs in with the website account; AI goes through the relay unless the user set their own key in Settings.

## Commands
- Engine tests: `cd engine && uv run pytest -q` (fake OpenAI, no network); lint: `uvx ruff check src tests`.
- Desktop: `cd apps/desktop && npm run typecheck && npm run build`; run for real use: `npm run app` (opens Electron.app via
  LaunchServices so macOS asks for microphone/screen permission for Electron itself; `npx electron .` from a terminal
  inherits the terminal's permissions instead). Unset `ELECTRON_RUN_AS_NODE` in agent shells.
- Desktop e2e (real OpenAI from `~/.env`, never the real microphone; fixtures replace mic and computer audio):
  `node tests/app-e2e.mjs <resume> <material…>` — account, goal, documents, practice, Live, history/Debrief.
  `node tests/practice-e2e.mjs` is the quick practice-only check (media denied).
  `node tests/settings-e2e.mjs` checks all six Settings sections and the cockpit appearance/Solve screen.
- Audio corpus (Live mode, real OpenAI): `node tests/audio/build-corpus.mjs && node tests/audio/run-corpus.mjs [id…]`.
  Scenarios and expectations are in `tests/audio/corpus.json`; the report goes to `tests/reports/audio-corpus.json`.
- In tests (`IRC_E2E=1`) Solve screen never captures the real screen: it uses `IRC_TEST_SCREEN` (an image) or fails.
- Electron binary download: GitHub may time out via the proxy; `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ node node_modules/electron/install.js`.

- macOS package (Apple Silicon, ad-hoc signed, not notarised): `cd apps/desktop && node scripts/package-mac.mjs` → `dist-mac/*.dmg`
  and `latest.json`. Bundles a uv-managed CPython 3.12 (`uv python install 3.12`) with the engine's locked deps and `engine/src`.
  Publish: copy both files to `/opt/irc-web/static/downloads/` on the web server (deploy.sh keeps that folder).
- Website: `python3 web/build_site.py` (all text, EN+ZH) → `web/static`; tests `cd web/server && uv run pytest -q`;
  deploy `sh web/deploy/deploy.sh ubuntu@<host> <key.pem> copilot.xichiuk.com`.

- E2E tests start a local test cloud (`tests/cloud.mjs`: web/server on a free port, temp DB, real OpenAI via ~/.env and the
  macOS proxy) and sign in there; `node tests/quota-e2e.mjs` checks the used-up-allowance path.

## Gotchas
- The engine watches stdin to detect the parent exiting; spawn it with a stdin pipe, not `ignore`.
- Never run tests that open the real microphone: use `IRC_FAKE_AUDIO` or `IRC_DENY_MEDIA=1`.
- `IRC_DATA_DIR` must point at a temporary folder in tests; the default is the user's real data.
- The packaged app keeps Electron's executable name, so `app.isPackaged` is false; main.ts detects `Resources/engine` instead.
- The packaged engine reads OPENAI_API_KEY from `<data dir>/openai.env` (Settings → Account), then `~/.env`.
- User-facing wording never names the AI provider or models (say "realtime AI engine"); the privacy text says audio is processed
  by our AI engine and trusted AI processing partners. Code, comments and logs may name OpenAI.
