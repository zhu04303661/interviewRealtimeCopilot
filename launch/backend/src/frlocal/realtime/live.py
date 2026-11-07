"""A spoken practice interviewer on OpenAI GPT-Live.

GPT-Live is a full-duplex voice model: it listens to a continuous audio stream
and decides itself when to speak. This class owns one GPT-Live session:

* ``session.start`` carries the interviewer instructions (goal, prepared
  topics, resume), the voice and 24 kHz PCM16 for both directions;
* microphone audio is resampled and appended as it arrives; when the
  microphone is quiet the class keeps the stream going with silence, as the
  model expects a continuous timeline;
* while the interviewer's voice is still playing on the speakers the
  microphone is replaced by silence ("echo gate"), so the model does not hear
  itself through the laptop speakers. The trade-off is that the candidate
  cannot interrupt the interviewer mid-sentence;
* output audio, the interviewer's transcript and the candidate's transcript
  are handed to callbacks; the session groups them into turns.

Client delegation is selected (no backend tools). If the model still asks for
delegated work, it is told to carry on by itself.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from ..config import Limits
from ..openai import OpenAI, ProviderError
from .protocol import OUTPUT_RATE, resample_16k_to_24k

log = logging.getLogger(__name__)

BYTES_PER_SECOND = OUTPUT_RATE * 2


class LiveConversation:
    def __init__(self, openai: OpenAI, key: str, *, model: str, voice: str, instructions: str, greeting: str,
                 limits: Limits, on_audio: Callable[[str], None], on_interviewer_text: Callable[[str], None],
                 on_candidate_text: Callable[[str], None], on_closed: Callable[[str | None], None]) -> None:
        self._openai, self._key, self._limits = openai, key, limits
        self._config = {
            "model": model,
            "instructions": instructions,
            "input": [{"type": "message", "role": "developer", "content": [{"type": "input_text", "text": greeting}]}],
            "audio": {"format": {"type": "audio/pcm", "rate": OUTPUT_RATE}, "output": {"voice": voice}},
            "delegation": None,
        }
        self._greeting = greeting
        self._on_audio, self._on_interviewer, self._on_candidate, self._on_closed = on_audio, on_interviewer_text, on_candidate_text, on_closed
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._tasks: list[asyncio.Task] = []
        self._send_lock = asyncio.Lock()
        self._playing_until = 0.0
        self._last_audio_sent = 0.0
        self._event = 0
        self.started = asyncio.Event()
        self.closed = False

    @property
    def interviewer_speaking(self) -> bool:
        """Whether interviewer audio is (estimated to be) still playing."""
        return time.monotonic() < self._playing_until

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect and start the session; raises ``ProviderError`` on failure."""
        self._socket = await self._openai.live_socket(self._key)
        await self._send({"type": "session.start", "session": self._config})
        loop = asyncio.get_running_loop()
        self._tasks.append(loop.create_task(self._receive()))
        try:
            await asyncio.wait_for(self.started.wait(), self._limits.live_start_timeout_s)
        except TimeoutError:
            await self.close()
            raise ProviderError("OpenAI GPT-Live did not start the session in time.") from None
        if self.closed:
            raise ProviderError("OpenAI GPT-Live rejected the practice session.")
        self._tasks.append(loop.create_task(self._keep_stream_alive()))
        # The startup developer message makes the greeting likely; this asks for it explicitly.
        await self._send({"type": "session.commentary.append", "delegation_id": None, "content": self._greeting})

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        socket = self._socket
        if socket and not socket.closed:
            try:
                await self._send({"type": "session.close"})
                await asyncio.wait_for(self._wait_closed(), 5)
            except (TimeoutError, aiohttp.ClientError, ConnectionError, RuntimeError):
                pass
            await socket.close()
        for task in self._tasks:
            if task is not asyncio.current_task():
                task.cancel()

    async def _wait_closed(self) -> None:
        while self._socket and not self._socket.closed:
            await asyncio.sleep(0.05)

    # ── audio in ────────────────────────────────────────────────────────────

    def append(self, pcm16k: bytes) -> None:
        """Forward microphone audio (silenced while the interviewer is audible)."""
        if self.closed or not self.started.is_set():
            return
        audio = resample_16k_to_24k(pcm16k)
        if time.monotonic() < self._playing_until + self._limits.live_echo_margin_s:
            audio = bytes(len(audio))
        self._spawn_send(audio)

    def _spawn_send(self, audio: bytes) -> None:
        self._last_audio_sent = time.monotonic()
        task = asyncio.get_running_loop().create_task(
            self._send({"type": "session.input_audio.append", "audio": base64.b64encode(audio).decode()}))
        task.add_done_callback(lambda done: done.exception() and log.debug("audio send failed: %s", done.exception()))

    async def _keep_stream_alive(self) -> None:
        interval = self._limits.live_silence_interval_s
        silence = bytes(int(BYTES_PER_SECOND * interval) & ~1)
        while not self.closed:
            await asyncio.sleep(interval)
            if time.monotonic() - self._last_audio_sent >= interval:
                self._spawn_send(silence)

    # ── events ──────────────────────────────────────────────────────────────

    async def _send(self, event: dict[str, Any]) -> None:
        if not self._socket or self._socket.closed:
            return
        self._event += 1
        event = {"event_id": f"frlocal_{self._event}", **event}
        async with self._send_lock:
            await self._socket.send_str(json.dumps(event, ensure_ascii=False))

    async def _receive(self) -> None:
        reason = None
        try:
            async for message in self._socket:
                if message.type != aiohttp.WSMsgType.TEXT:
                    if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    continue
                reason = self._handle(json.loads(message.data)) or reason
                if reason == "closed" or (reason and not self.started.is_set()):
                    break
        except (aiohttp.ClientError, ValueError) as error:
            reason = str(error)
        finally:
            was_closed = self.closed
            self.closed = True
            self.started.set()
            if not was_closed:
                self._on_closed(None if reason == "closed" else reason or "The GPT-Live connection closed.")

    def _handle(self, event: dict[str, Any]) -> str | None:
        kind = event.get("type")
        if kind == "session.started":
            self.started.set()
        elif kind == "session.output_audio.delta" and isinstance(event.get("delta"), str):
            seconds = len(event["delta"]) * 3 / 4 / BYTES_PER_SECOND
            self._playing_until = max(self._playing_until, time.monotonic()) + seconds
            self._on_audio(event["delta"])
        elif kind == "session.output_transcript.delta" and isinstance(event.get("delta"), str):
            self._on_interviewer(event["delta"])
        elif kind == "session.input_transcript.delta" and isinstance(event.get("delta"), str):
            self._on_candidate(event["delta"])
        elif kind == "session.delegation.created":
            delegation_id = (event.get("delegation") or {}).get("id")
            if delegation_id:
                asyncio.get_running_loop().create_task(self._send({
                    "type": "session.thinking.append", "delegation_id": delegation_id,
                    "content": "No backend or tools are available. Continue the interview yourself."}))
        elif kind == "error":
            error = event.get("error") or {}
            log.warning("GPT-Live error: %s %s", error.get("code"), error.get("message"))
            if not self.started.is_set():
                return error.get("message") or "OpenAI GPT-Live rejected the practice session."
        elif kind == "session.closed":
            return "closed"
        return None
