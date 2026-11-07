"""Run the fake OpenAI from ``fakes.py`` as a standalone server for app-level tests.

    uv run python -m tests.fake_openai_server

Prints ``{"port": N}`` once listening and serves until interrupted. The app is
pointed at it with ``FRLOCAL_OPENAI_BASE=http://127.0.0.1:N`` and
``OPENAI_API_KEY=test-key``.
"""

from __future__ import annotations

import asyncio
import json
import sys

from aiohttp import web

from .fakes import FakeOpenAI


async def main() -> None:
    fake = FakeOpenAI()
    fake.answer_token_gap = 0.05
    runner = web.AppRunner(fake.app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    sys.stdout.write(json.dumps({"port": port}) + "\n")
    sys.stdout.flush()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
