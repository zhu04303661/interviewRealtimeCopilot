"""A speech-to-speech practice interviewer on the OpenAI Realtime API.

One Realtime session (``gpt-realtime-2.1``) hears the candidate, decides when
they have finished (semantic voice-activity detection) and answers in speech.
Compared with GPT-Live it has explicit turn boundaries, which keep the
transcript, questions and hints aligned:

* ``response.output_audio.delta``             interviewer audio (24 kHz PCM16)
* ``response.output_audio_transcript.delta``  interviewer caption while speaking
* ``response.output_audio_transcript.done``   the interviewer's complete turn
* ``conversation.item.input_audio_transcription.completed``
                                              the candidate's complete answer
* ``input_audio_buffer.speech_started``       the candidate started talking

Echo handling: by default the microphone is replaced by silence while the
interviewer is audible (plus a short margin), so on laptop speakers the model
never hears itself; the candidate then speaks after the interviewer finishes.
With ``barge_in`` (headphones) the microphone is always forwarded and, when
the candidate interrupts, playback stops and the unplayed part of the
interviewer's turn is truncated from the conversation, as the Realtime guide
describes for WebSocket clients.
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


class RealtimeVoiceAgent:
    def __init__(self, openai: OpenAI, key: str, *, model: str, voice: str, transcription_model: str, instructions: str,
                 greeting: str, limits: Limits, barge_in: bool, on_audio: Callable[[str], None],
                 on_audio_cleared: Callable[[], None], on_interviewer_text: Callable[[str], None],
                 on_interviewer_done: Callable[[str], None], on_candidate_done: Callable[[str], None],
                 on_closed: Callable[[str | None], None], on_candidate_started: Callable[[], None] = lambda: None) -> None:
        self._openai, self._key, self._model, self._limits, self._barge_in = openai, key, model, limits, barge_in
        self._session = {
            "type": "realtime",
            "model": model,
            "output_modalities": ["audio"],
            "instructions": instructions,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": OUTPUT_RATE},
                    "transcription": {"model": transcription_model},
                    "noise_reduction": {"type": "far_field"},
                    # Interview answers contain thinking pauses; wait for the whole thought.
                    # The backend decides each interviewer turn (next prepared question
                    # or one follow-up), so VAD only detects turns and never replies by itself.
                    # Without barge-in the candidate cannot cut the interviewer off,
                    # so speech must not cancel a reply that is still being generated.
                    "turn_detection": {"type": "semantic_vad", "eagerness": "low", "create_response": False,
                                       "interrupt_response": barge_in},
                },
                "output": {"format": {"type": "audio/pcm", "rate": OUTPUT_RATE}, "voice": voice},
            },
        }
        self._greeting = greeting
        self._on_audio, self._on_audio_cleared = on_audio, on_audio_cleared
        self._on_interviewer, self._on_interviewer_done = on_interviewer_text, on_interviewer_done
        self._on_candidate_done, self._on_closed = on_candidate_done, on_closed
        self._on_candidate_started = on_candidate_started
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._tasks: list[asyncio.Task] = []
        self._send_lock = asyncio.Lock()
        self._event = 0
        self._playing_until = 0.0
        self._last_audio_sent = 0.0
        # The interviewer item being played, for truncation on interruption.
        self._item_id: str | None = None
        self._item_started = 0.0
        self._item_bytes = 0
        self.started = asyncio.Event()
        self.closed = False

    @property
    def interviewer_speaking(self) -> bool:
        return time.monotonic() < self._playing_until

    # ── lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect, configure the session and ask the interviewer to open."""
        self._socket = await self._openai.realtime_socket(self._key, self._model)
        loop = asyncio.get_running_loop()
        self._tasks.append(loop.create_task(self._receive()))
        await self._send({"type": "session.update", "session": self._session})
        try:
            await asyncio.wait_for(self.started.wait(), self._limits.live_start_timeout_s)
        except TimeoutError:
            await self.close()
            raise ProviderError("The OpenAI Realtime API did not start the practice session in time.") from None
        if self.closed:
            raise ProviderError(self._failure or "The OpenAI Realtime API rejected the practice session.")
        self._tasks.append(loop.create_task(self._keep_stream_alive()))
        await self._send({"type": "response.create", "response": {"instructions": self._greeting}})

    _failure: str | None = None

    async def respond(self, instructions: str) -> None:
        """Have the interviewer speak one turn following ``instructions``."""
        if not self.closed:
            await self._send({"type": "response.create", "response": {"instructions": instructions}})

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._socket and not self._socket.closed:
            await self._socket.close()
        for task in self._tasks:
            if task is not asyncio.current_task():
                task.cancel()

    # ── audio in ────────────────────────────────────────────────────────────

    def append(self, pcm16k: bytes) -> None:
        if self.closed or not self.started.is_set():
            return
        audio = resample_16k_to_24k(pcm16k)
        if not self._barge_in and time.monotonic() < self._playing_until + self._limits.live_echo_margin_s:
            audio = bytes(len(audio))
        self._send_audio(audio)

    def _send_audio(self, audio: bytes) -> None:
        self._last_audio_sent = time.monotonic()
        task = asyncio.get_running_loop().create_task(
            self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(audio).decode()}))
        task.add_done_callback(lambda done: done.exception() and log.debug("audio send failed: %s", done.exception()))

    async def _keep_stream_alive(self) -> None:
        """Server VAD needs a continuous stream; fill microphone gaps with silence."""
        interval = self._limits.live_silence_interval_s
        silence = bytes(int(BYTES_PER_SECOND * interval) & ~1)
        while not self.closed:
            await asyncio.sleep(interval)
            if time.monotonic() - self._last_audio_sent >= interval:
                self._send_audio(silence)

    # ── events ──────────────────────────────────────────────────────────────

    async def _send(self, event: dict[str, Any]) -> None:
        if not self._socket or self._socket.closed:
            return
        self._event += 1
        async with self._send_lock:
            await self._socket.send_str(json.dumps({"event_id": f"frlocal_{self._event}", **event}, ensure_ascii=False))

    async def _receive(self) -> None:
        reason = None
        try:
            async for message in self._socket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    self._handle(json.loads(message.data))
                    if self._failure and not self.started.is_set():
                        reason = self._failure
                        break
                elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except (aiohttp.ClientError, ValueError) as error:
            reason = str(error)
        finally:
            was_closed = self.closed
            self.closed = True
            self.started.set()
            if not was_closed:
                self._on_closed(reason or "The OpenAI Realtime connection closed.")

    def _handle(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "session.updated":
            self.started.set()
        elif kind == "response.output_audio.delta" and isinstance(event.get("delta"), str):
            if event.get("item_id") != self._item_id:
                self._item_id, self._item_started, self._item_bytes = event.get("item_id"), time.monotonic(), 0
            size = len(event["delta"]) * 3 // 4
            self._item_bytes += size
            self._playing_until = max(self._playing_until, time.monotonic()) + size / BYTES_PER_SECOND
            self._on_audio(event["delta"])
        elif kind == "response.output_audio_transcript.delta" and isinstance(event.get("delta"), str):
            self._on_interviewer(event["delta"])
        elif kind == "response.output_audio_transcript.done":
            self._on_interviewer_done(event.get("transcript") or "")
        elif kind == "conversation.item.input_audio_transcription.completed":
            transcript = (event.get("transcript") or "").strip()
            if transcript:
                self._on_candidate_done(transcript)
        elif kind == "input_audio_buffer.speech_started":
            self._on_candidate_started()
            if self._barge_in and self.interviewer_speaking:
                self._interrupt()
        elif kind == "error":
            error = event.get("error") or {}
            log.warning("Realtime voice agent error: %s %s", error.get("code"), error.get("message"))
            if not self.started.is_set():
                self._failure = error.get("message") or "The OpenAI Realtime API rejected the practice session."

    def _interrupt(self) -> None:
        """The candidate talked over the interviewer: stop playback and drop what they did not hear."""
        played_ms = int(min(time.monotonic() - self._item_started, self._item_bytes / BYTES_PER_SECOND) * 1000)
        self._playing_until = 0.0
        self._on_audio_cleared()
        if self._item_id:
            asyncio.get_running_loop().create_task(self._send({
                "type": "conversation.item.truncate", "item_id": self._item_id, "content_index": 0, "audio_end_ms": max(0, played_ms)}))
