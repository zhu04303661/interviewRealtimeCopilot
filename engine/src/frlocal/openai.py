"""The only module that talks to OpenAI.

* The API key comes from ``OPENAI_API_KEY`` in the environment or, if unset,
  from ``~/.env``; it is re-read on every call so a changed key applies
  without a restart.
* Requests go through the macOS system proxy that the Electron main process
  resolves for ``api.openai.com`` and passes in (HTTP, HTTPS or SOCKS5).
* One pooled HTTP session keeps TLS connections warm between calls, which
  saves a round trip on every answer during an interview.
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from .sse import SseParser

RESPONSES_PATH = "/v1/responses"
TRANSCRIPTION_PATH = "/v1/realtime?intent=transcription"
LIVE_PATH = "/v1/live/sessions"


class ProviderError(Exception):
    """An OpenAI failure, phrased for the person using the app."""


def describe_failure(status: int | None = None, code: str | None = None) -> str:
    if status == 402 or code == "quota_exceeded":
        return "Your monthly AI allowance is used up. Subscribe in Settings → Account to continue."
    if status == 401 or code == "invalid_api_key":
        return "OpenAI rejected the configured API key."
    if status in (403, 404) or code == "model_not_found":
        return "This OpenAI project does not have access to the requested model."
    if status == 429 or code in ("insufficient_quota", "rate_limit_exceeded"):
        return "The OpenAI project is over its rate or usage limit."
    return "The local backend could not complete the OpenAI request."


_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def read_env_file(path: Path) -> dict[str, str]:
    """Parse the simple ``KEY=value`` dotenv format (quotes and comments allowed)."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, UnicodeDecodeError):
        return values
    for line in lines:
        match = _ENV_LINE.match(line)
        if not match or line.lstrip().startswith("#"):
            continue
        name, value = match.groups()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        values[name] = value
    return values


class OpenAI:
    def __init__(self, base: str, ws_base: str, env_file: Path | tuple[Path, ...], proxy: str | None = None) -> None:
        self._base = base
        self._ws_base = ws_base
        self.env_file = env_file
        self._proxy = proxy
        self._session: aiohttp.ClientSession | None = None

    # -- configuration -------------------------------------------------------

    def _provider(self) -> tuple[str | None, str]:
        """(key, base URL), re-read on every call: OPENAI_API_KEY from the environment, else the first env file
        with a key. That file may also set FRLOCAL_OPENAI_BASE, e.g. the cloud relay with a device token as key."""
        if key := (os.environ.get("OPENAI_API_KEY") or "").strip():
            return key, self._base
        for path in self.env_file if isinstance(self.env_file, tuple) else (self.env_file,):
            values = read_env_file(path)
            if key := (values.get("OPENAI_API_KEY") or "").strip():
                return key, (values.get("FRLOCAL_OPENAI_BASE") or "").strip().rstrip("/") or self._base
        return None, self._base

    @property
    def base(self) -> str:
        return self._provider()[1]

    @property
    def ws_base(self) -> str:
        base = self._provider()[1]
        if base == self._base:
            return self._ws_base
        return "wss://" + base[8:] if base.startswith("https://") else "ws://" + base[7:] if base.startswith("http://") else base

    def api_key(self) -> str | None:
        return self._provider()[0]

    def require_key(self) -> str:
        key = self.api_key()
        if not key:
            raise ProviderError("Set OPENAI_API_KEY in the local backend to use live transcription and AI coaching.")
        return key

    async def set_proxy(self, proxy: str | None) -> None:
        """Switch proxies (the bridge calls this when macOS settings change)."""
        if proxy == self._proxy:
            return
        self._proxy = proxy
        old, self._session = self._session, None
        if old:
            await old.close()

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector: aiohttp.BaseConnector
            if self._proxy and self._proxy.startswith("socks"):
                from aiohttp_socks import ProxyConnector
                connector = ProxyConnector.from_url(self._proxy, limit=16, keepalive_timeout=120)
            else:
                connector = aiohttp.TCPConnector(limit=16, keepalive_timeout=120)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    def _proxy_kwargs(self) -> dict[str, Any]:
        """Proxy for OpenAI requests: the bridge's choice, else the macOS system proxy.

        aiohttp only applies environment/system proxies to plain HTTP(S), not to
        WebSockets, so the system setting is resolved here and passed
        explicitly to every call. Loopback hosts (tests) always connect directly.
        """
        if self._proxy:
            return {} if self._proxy.startswith("socks") else {"proxy": self._proxy}
        host = urlsplit(self.base).hostname or ""
        if host in ("127.0.0.1", "localhost", "::1") or urllib.request.proxy_bypass(host):
            return {}
        system = urllib.request.getproxies()
        proxy = system.get("https") or system.get("http")
        return {"proxy": proxy} if proxy and proxy.startswith("http") else {}

    def _headers(self, key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async def close(self) -> None:
        if self._session:
            await self._session.close()

    # -- calls -----------------------------------------------------------------

    async def warm_up(self) -> None:
        """Open a pooled TLS connection before the first latency-critical call."""
        key = self.api_key()
        if not key:
            return
        try:
            async with self._http().get(self.base + "/v1/models", headers=self._headers(key),
                                        timeout=aiohttp.ClientTimeout(total=10), **self._proxy_kwargs()) as response:
                await response.read()
        except (TimeoutError, aiohttp.ClientError):
            pass

    async def respond(self, body: dict[str, Any], *, timeout: float, key: str | None = None) -> str:
        """Run one Responses request and return its output text."""
        key = key or self.require_key()
        try:
            async with self._http().post(self.base + RESPONSES_PATH, headers=self._headers(key),
                                         json={**body, "store": False}, allow_redirects=False,
                                         timeout=aiohttp.ClientTimeout(total=timeout), **self._proxy_kwargs()) as response:
                if response.status != 200:
                    raise ProviderError(describe_failure(response.status))
                payload = await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as error:
            raise ProviderError(describe_failure()) from error
        text = output_text(payload)
        if not text:
            raise ProviderError("OpenAI returned no text for this request.")
        return text

    async def stream(self, body: dict[str, Any], *, timeout: float, key: str | None = None) -> AsyncIterator[str]:
        """Run one streamed Responses request, yielding text deltas as they arrive."""
        key = key or self.require_key()
        parser = SseParser()
        try:
            async with self._http().post(self.base + RESPONSES_PATH, headers=self._headers(key),
                                         json={**body, "store": False, "stream": True}, allow_redirects=False,
                                         timeout=aiohttp.ClientTimeout(total=timeout, sock_read=20), **self._proxy_kwargs()) as response:
                if response.status != 200:
                    raise ProviderError(describe_failure(response.status))
                async for chunk in response.content.iter_any():
                    for event in parser.feed(chunk):
                        delta = _stream_delta(event.data)
                        if delta:
                            yield delta
                for event in parser.close():
                    delta = _stream_delta(event.data)
                    if delta:
                        yield delta
        except (TimeoutError, aiohttp.ClientError) as error:
            raise ProviderError(describe_failure()) from error

    async def diarize(self, wav: bytes, *, model: str, known: list[tuple[str, bytes]], key: str, timeout: float) -> list[dict]:
        """Speaker-labelled segments for one utterance (``diarized_json``).

        ``known`` holds up to four (name, WAV clip of 2–10 s) references; matching
        segments are labelled with those names, others with generic labels.
        """
        form = aiohttp.FormData()
        form.add_field("model", model)
        form.add_field("response_format", "diarized_json")
        form.add_field("chunking_strategy", "auto")
        form.add_field("file", wav, filename="utterance.wav", content_type="audio/wav")
        for name, clip in known[:4]:
            form.add_field("known_speaker_names[]", name)
            form.add_field("known_speaker_references[]", "data:audio/wav;base64," + base64.b64encode(clip).decode())
        try:
            async with self._http().post(self.base + "/v1/audio/transcriptions", headers={"Authorization": f"Bearer {key}"},
                                         data=form, timeout=aiohttp.ClientTimeout(total=timeout), **self._proxy_kwargs()) as response:
                if response.status != 200:
                    raise ProviderError(describe_failure(response.status))
                payload = await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError) as error:
            raise ProviderError(describe_failure()) from error
        return [s for s in payload.get("segments") or [] if isinstance(s, dict)]

    async def realtime_socket(self, key: str, model: str) -> aiohttp.ClientWebSocketResponse:
        """Open a Realtime API speech-to-speech conversation WebSocket."""
        try:
            return await self._http().ws_connect(
                f"{self.ws_base}/v1/realtime?model={model}", headers={"Authorization": f"Bearer {key}"},
                heartbeat=20, max_msg_size=8 * 1024 * 1024, timeout=aiohttp.ClientWSTimeout(ws_close=5),
                **self._proxy_kwargs())
        except aiohttp.WSServerHandshakeError as error:
            raise ProviderError(describe_failure(error.status)) from error
        except (TimeoutError, aiohttp.ClientError) as error:
            raise ProviderError("Could not connect to the OpenAI Realtime API.") from error

    async def live_socket(self, key: str) -> aiohttp.ClientWebSocketResponse:
        """Open a GPT-Live voice session WebSocket (``session.start`` is sent by the caller)."""
        try:
            return await self._http().ws_connect(
                self.ws_base + LIVE_PATH, headers={"Authorization": f"Bearer {key}"},
                heartbeat=20, max_msg_size=8 * 1024 * 1024, timeout=aiohttp.ClientWSTimeout(ws_close=5),
                **self._proxy_kwargs())
        except aiohttp.WSServerHandshakeError as error:
            raise ProviderError(describe_failure(error.status)) from error
        except (TimeoutError, aiohttp.ClientError) as error:
            raise ProviderError("Could not connect to OpenAI GPT-Live.") from error

    async def transcription_socket(self, key: str) -> aiohttp.ClientWebSocketResponse:
        """Open a realtime transcription WebSocket."""
        try:
            return await self._http().ws_connect(
                self.ws_base + TRANSCRIPTION_PATH, headers={"Authorization": f"Bearer {key}"},
                heartbeat=20, max_msg_size=4 * 1024 * 1024, timeout=aiohttp.ClientWSTimeout(ws_close=5),
                **self._proxy_kwargs())
        except aiohttp.WSServerHandshakeError as error:
            raise ProviderError(describe_failure(error.status)) from error
        except (TimeoutError, aiohttp.ClientError) as error:
            raise ProviderError("Could not connect to OpenAI transcription.") from error


def output_text(payload: Any) -> str:
    """Concatenate the ``output_text`` parts of a Responses result."""
    parts = []
    for item in (payload or {}).get("output") or []:
        if item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                parts.append(part["text"])
    return "".join(parts).strip()


def _stream_delta(data: str) -> str | None:
    try:
        event = json.loads(data)
    except ValueError:
        return None
    kind = event.get("type")
    if kind == "response.output_text.delta" and isinstance(event.get("delta"), str):
        return event["delta"]
    if kind in ("response.failed", "error"):
        error = event.get("error") or (event.get("response") or {}).get("error") or {}
        raise ProviderError(describe_failure(code=error.get("code")))
    return None
