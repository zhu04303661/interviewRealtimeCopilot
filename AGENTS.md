# Interview Realtime Copilot — working notes

## Layout
- `engine/` — local Python 3.12 engine (package `frlocal`, uv): accounts, goals, document preparation, retrieval,
  realtime interview (transcription, translation, question extraction, answer hints, speech-to-speech practice).
- `apps/desktop/` — Electron 45 + React 19 + TypeScript desktop app. `src/main` starts the engine and owns windows/IPC,
  `src/preload` is the only renderer bridge (`window.copilot`), `src/renderer` has the main window and the cockpit.
- Planned: `cloud/` (accounts, Stripe subscriptions, OpenAI relay), `web/` (site, bilingual manual, downloads).

## Commands
- Engine tests: `cd engine && uv run pytest -q` (fake OpenAI, no network); lint: `uvx ruff check src tests`.
- Desktop: `cd apps/desktop && npm run typecheck && npm run build`; run for real use: `npm run app` (opens Electron.app via
  LaunchServices so macOS asks for microphone/screen permission for Electron itself; `npx electron .` from a terminal
  inherits the terminal's permissions instead). Unset `ELECTRON_RUN_AS_NODE` in agent shells.
- Desktop e2e (real OpenAI from `~/.env`, never the real microphone; fixtures replace mic and computer audio):
  `node tests/app-e2e.mjs <resume> <material…>` — account, goal, documents, practice, Live, history/Debrief.
  `node tests/practice-e2e.mjs` is the quick practice-only check (media denied).
  `node tests/settings-e2e.mjs` checks all six Settings sections and the cockpit appearance/Solve screen.
- In tests (`IRC_E2E=1`) Solve screen never captures the real screen: it uses `IRC_TEST_SCREEN` (an image) or fails.
- Electron binary download: GitHub may time out via the proxy; `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ node node_modules/electron/install.js`.

## Gotchas
- The engine watches stdin to detect the parent exiting; spawn it with a stdin pipe, not `ignore`.
- Never run tests that open the real microphone: use `IRC_FAKE_AUDIO` or `IRC_DENY_MEDIA=1`.
- `IRC_DATA_DIR` must point at a temporary folder in tests; the default is the user's real data.
