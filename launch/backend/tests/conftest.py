"""Shared fixtures: a fake OpenAI, the backend app on a real loopback port, and a signed-in client."""

from __future__ import annotations

import asyncio
import json
import os
import struct
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import aiohttp
import pytest
from aiohttp.test_utils import TestServer

from frlocal.accounts import FIRST_LOGIN_FILE, provision_admin
from frlocal.app import DOCUMENTS_KEY, ENGINE_KEY, build_app
from frlocal.config import Limits, Settings

from .fakes import FakeOpenAI

TOKEN = "t" * 40
ADMIN_PASSWORD = "integration-admin-password"


@pytest.fixture
def fake_openai_app():
    return FakeOpenAI()


@pytest.fixture
async def fake_openai(fake_openai_app):
    server = TestServer(fake_openai_app.app)
    await server.start_server()
    fake_openai_app.base = str(server.make_url("")).rstrip("/")
    yield fake_openai_app
    await server.close()


@pytest.fixture(autouse=True)
def openai_key(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


@dataclass
class Backend:
    base: str
    settings: Settings
    app: Any
    session: aiohttp.ClientSession
    owner: str = "1"
    session_token: str | None = None

    def url(self, path: str) -> str:
        return self.base + path

    async def call(self, method: str, path: str, *, expect: int | None = 200, **kwargs) -> Any:
        async with self.session.request(method, self.url(path), **kwargs) as response:
            text = await response.text()
            if expect is not None:
                assert response.status == expect, f"{method} {path}: {response.status} {text}"
            return json.loads(text) if text and response.content_type == "application/json" else text

    async def auth(self, action: str, **body) -> Any:
        result = await self.call("POST", f"/local/auth/{action}", json={"owner": self.owner, **body})
        assert result["ok"], result
        return result["value"]

    async def sign_in_admin(self) -> None:
        code = (self.settings.accounts_dir / FIRST_LOGIN_FILE).read_text().strip()
        value = await self.auth("activate", code=code, newPassword=ADMIN_PASSWORD)
        self.session_token = value["token"]

    @property
    def documents(self):
        return self.app[DOCUMENTS_KEY]

    @property
    def engine(self):
        return self.app[ENGINE_KEY]


def make_settings(tmp_path: Path, base: str = "http://127.0.0.1:9", limits: Limits | None = None, **extra) -> Settings:
    accounts, workspace = tmp_path / "accounts", tmp_path / "workspace"
    provision_admin(accounts)
    return Settings(accounts_dir=accounts, workspace_dir=workspace, token=TOKEN, openai_base=base,
                    env_file=tmp_path / "missing.env", limits=limits or Limits(), **extra)


@pytest.fixture
def limits() -> Limits:
    return Limits()


@pytest.fixture
def practice_voice() -> str:
    """The practice interviewer under test; modules override this fixture."""
    return "realtime"


@pytest.fixture
def barge_in() -> bool:
    return False


@pytest.fixture
async def backend(tmp_path, fake_openai, limits, practice_voice, barge_in):
    settings = make_settings(tmp_path, fake_openai.base, limits, practice_voice=practice_voice, practice_barge_in=barge_in)
    app = build_app(settings)
    server = TestServer(app)
    await server.start_server()
    session = aiohttp.ClientSession(headers={"Authorization": f"Bearer {TOKEN}"})
    yield Backend(str(server.make_url("")).rstrip("/"), settings, app, session)
    await session.close()
    await server.close()


@pytest.fixture
async def signed_in(backend):
    await backend.sign_in_admin()
    return backend


# ── realtime helpers ─────────────────────────────────────────────────────────

GENERAL_STREAMS = [
    {"stream_id": "candidate", "source": "mic", "role": "interviewee", "encoding": "pcm16", "sample_rate": 16000},
    {"stream_id": "interviewer", "source": "system", "role": "interviewer", "encoding": "pcm16", "sample_rate": 16000},
]
MOCK_STREAMS = [{"stream_id": "mic", "source": "mic", "role": "interviewee", "encoding": "pcm16", "sample_rate": 16000}]


def audio_frame(stream: int, sequence: int, samples: int = 1600, value: int = 100) -> bytes:
    """One binary frame: 100 ms of a constant tone by default."""
    return struct.pack("<BI", stream, sequence) + struct.pack(f"<{samples}h", *([value] * samples))


class LiveClient:
    """The app's realtime client, reduced to what tests need."""

    def __init__(self, socket: aiohttp.ClientWebSocketResponse) -> None:
        self.socket = socket
        self.frames: list[dict[str, Any]] = []
        self._new = asyncio.Event()
        self._reader = asyncio.get_running_loop().create_task(self._read())
        self.sequence = [0, 0]

    async def _read(self) -> None:
        async for message in self.socket:
            if message.type == aiohttp.WSMsgType.TEXT:
                frame = json.loads(message.data)
                frame["received_at"] = asyncio.get_running_loop().time()
                self.frames.append(frame)
                self._new.set()

    async def send(self, kind: str, **fields) -> None:
        await self.socket.send_str(json.dumps({"v": 1, "type": kind, **fields}))

    async def speak(self, stream: int, frames: int = 3) -> None:
        """Send audio on one lane, then mark the end of the turn."""
        for _ in range(frames):
            await self.socket.send_bytes(audio_frame(stream, self.sequence[stream]))
            self.sequence[stream] += 1
        await self.send("finalize", stream=stream)

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [frame for frame in self.frames if frame["type"] == kind]

    async def wait_for(self, predicate, timeout: float = 5.0) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            for frame in self.frames:
                if predicate(frame):
                    return frame
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise AssertionError("Frame did not arrive; got: " + ", ".join(f["type"] for f in self.frames))
            self._new.clear()
            try:
                await asyncio.wait_for(self._new.wait(), remaining)
            except TimeoutError:
                pass

    async def wait_type(self, kind: str, timeout: float = 5.0, **data) -> dict[str, Any]:
        return await self.wait_for(lambda f: f["type"] == kind and all(f["data"].get(k) == v for k, v in data.items()), timeout)

    async def close(self) -> None:
        await self.socket.close()
        await self._reader


async def start_interview(backend: Backend, *, topology: str = "general", config: dict | None = None,
                          goal: dict | None = None) -> tuple[str, str]:
    goal = await backend.call("POST", "/api/v3/goals", json=goal or {"role": "Software Engineer", "company": "Example"})
    started = await backend.call("POST", "/api/v3/sessions", json={"topology": topology, "goal_id": goal["goal_id"],
                                                                   "config": config or {"language": "en-US"}})
    return started["session_id"], started["ws_url"]


async def connect(backend: Backend, session_id: str, ws_url: str, *, topology: str = "general", jwt: str | None = None,
                  last_seen_seq: int | None = None) -> LiveClient:
    socket = await backend.session.ws_connect(ws_url)
    client = LiveClient(socket)
    hello = {"jwt": jwt or backend.session_token, "session_id": session_id,
             "streams": GENERAL_STREAMS if topology == "general" else MOCK_STREAMS}
    if last_seen_seq is not None:
        hello["last_seen_seq"] = last_seen_seq
    await client.send("hello", **hello)
    return client


@pytest.fixture
def fast_limits() -> Limits:
    return replace(Limits(), asr_drain_timeout_s=1.0)


def write_env(path: Path, **values: str) -> None:
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    os.chmod(path, 0o600)
