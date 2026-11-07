"""Command line entry points.

``python -m frlocal serve --accounts DIR --workspace DIR [--legacy-workspace DIR]``
    Start the backend on a free loopback port. Prints one JSON line
    ``{"event": "ready", "port": N}`` once it accepts connections, and exits
    when standard input closes (that is, when the Electron app that started it
    goes away, even if it crashed).

``python -m frlocal provision-admin DIR``
    Create the administrator account with a one-time setup code (idempotent)
    and print where the code was written.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

from aiohttp import web

from .accounts import FIRST_LOGIN_FILE, provision_admin
from .app import build_app
from .config import settings_from_environment
from .workspace.store import migrate_legacy_workspaces


async def serve(accounts: Path, workspace: Path, legacy_workspace: Path | None = None) -> None:
    copied = migrate_legacy_workspaces(legacy_workspace, workspace)
    if copied:
        logging.getLogger("frlocal").info("Copied workspaces from %s: %s", legacy_workspace, ", ".join(copied))
    settings = settings_from_environment(accounts, workspace)
    runner = web.AppRunner(build_app(settings), access_log=None, shutdown_timeout=3)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # aiohttp has no public accessor for the bound port
    sys.stdout.write(json.dumps({"event": "ready", "port": port}) + "\n")
    sys.stdout.flush()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        loop.add_signal_handler(getattr(signal, name), stop.set)
    # Standard input is a pipe from the Electron app; EOF means it is gone.
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)

    async def watch_parent() -> None:
        while await reader.read(1024):
            pass
        stop.set()

    watcher = loop.create_task(watch_parent())
    await stop.wait()
    watcher.cancel()
    await runner.cleanup()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frlocal")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="run the backend")
    serve_parser.add_argument("--accounts", required=True, type=Path)
    serve_parser.add_argument("--workspace", required=True, type=Path)
    serve_parser.add_argument("--legacy-workspace", type=Path, help="older workspace folder to copy accounts from once")
    provision = commands.add_parser("provision-admin", help="create the administrator with a setup code")
    provision.add_argument("directory", type=Path)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[frlocal] %(levelname)s %(name)s: %(message)s")
    if args.command == "serve":
        asyncio.run(serve(args.accounts, args.workspace, args.legacy_workspace))
    else:
        code = provision_admin(args.directory)
        print(f"Administrator setup code: {args.directory / FIRST_LOGIN_FILE}" if code else "The administrator is already active.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
