"""One OpenAI realtime transcription socket per capture lane.

Audio arrives as 16 kHz PCM16 chunks plus "end of turn" markers (sent when the
app's voice-activity detector hears silence). This class

1. connects lazily on the first chunk and configures ``gpt-live-transcribe``
   for low delay, with the interview's languages, a short prompt and
   vocabulary keywords;
2. resamples to 24 kHz and appends audio, committing a turn at each marker or
   after 15 s of continuous speech so long answers still produce text;
3. reports interim text (``final=False``) as deltas arrive and the final text
   when a committed turn completes;
4. keeps the amount of unsent audio bounded and reports ``degraded`` if
   OpenAI cannot keep up or the connection fails.

At most eight committed turns may be awaiting transcription at once; further
audio waits in the queue, which is itself limited to about ten seconds.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

import aiohttp

from ..config import Limits
from ..openai import OpenAI, ProviderError, describe_failure
from .protocol import resample_16k_to_24k

log = logging.getLogger(__name__)

_END_OF_TURN = None  # queue marker
MAX_TRACKED_ITEMS = 16
MAX_TRANSCRIPT_CHARS = 12_000


@dataclass
class TranscriptionHints:
    """Context that improves recognition of the interview's vocabulary."""

    languages: list[str] = field(default_factory=lambda: ["en", "zh"])
    prompt: str = ""
    keywords: list[str] = field(default_factory=list)

    def session_config(self, model: str, *, minimal: bool = False) -> dict:
        transcription: dict = {"model": model}
        if not minimal:
            transcription["delay"] = "low"
            if self.languages:
                transcription["languages"] = self.languages
            if self.prompt:
                transcription["prompt"] = self.prompt
            if self.keywords:
                transcription["keywords"] = self.keywords
        return {"type": "transcription", "audio": {"input": {
            "format": {"type": "audio/pcm", "rate": 24000},
            "transcription": transcription,
            "turn_detection": None,
        }}}


TextCallback = Callable[[str, str, bool], None]      # (item_id, text, final)


class TranscriptionStream:
    def __init__(self, openai: OpenAI, key: str, model: str, hints: TranscriptionHints, limits: Limits, *,
                 on_text: TextCallback, on_drop: Callable[[], None],
                 on_status: Callable[[str, str | None], None]) -> None:
        self._openai, self._key, self._model, self._hints, self._limits = openai, key, model, hints, limits
        self._on_text, self._on_drop, self._on_status = on_text, on_drop, on_status
        self.state = "new"                     # new → connecting → ready → closed
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._queue: deque[bytes | None] = deque()
        self._queued_bytes = 0
        self._turn_bytes = 0
        self._commit_pending = False
        self._awaiting: set[str] = set()       # committed items without a final transcript
        self._interim: dict[str, str] = {}
        self._wake = asyncio.Event()
        self._finished = asyncio.Event()
        self._finishing = False
        self._minimal_config = False
        self._tasks: list[asyncio.Task] = []

    @property
    def closed(self) -> bool:
        return self.state == "closed"

    # -- input -----------------------------------------------------------------

    def append(self, pcm: bytes) -> None:
        if self.state == "closed" or self._finishing:
            return
        if self._queued_bytes + len(pcm) > self._limits.max_queued_audio_bytes:
            self.stop("OpenAI transcription could not keep up with the audio stream.")
            return
        self._queue.append(pcm)
        self._queued_bytes += len(pcm)
        self._start()
        self._wake.set()

    def end_turn(self) -> None:
        """Mark the end of a spoken turn so the buffered audio is transcribed now."""
        if self.state in ("closed", "new") or (self._queue and self._queue[-1] is _END_OF_TURN):
            return
        self._queue.append(_END_OF_TURN)
        self._wake.set()

    async def drain(self) -> None:
        """Transcribe what is already buffered, then close (bounded by a timeout)."""
        if self.state in ("closed", "new"):
            self.stop()
            return
        self._finishing = True
        self.end_turn()
        self._wake.set()
        try:
            await asyncio.wait_for(self._finished.wait(), self._limits.asr_drain_timeout_s)
        except TimeoutError:
            pass
        self.stop()

    def stop(self, message: str | None = None) -> None:
        if self.state == "closed":
            return
        self.state = "closed"
        if message:
            self._on_status("degraded", message)
        if self._interim or self._turn_bytes or self._awaiting:
            self._on_drop()
        self._queue.clear()
        self._queued_bytes = 0
        self._interim.clear()
        self._awaiting.clear()
        self._finished.set()
        self._wake.set()
        current = asyncio.current_task()
        for task in self._tasks:
            if task is not current:
                task.cancel()
        if self._socket and not self._socket.closed:
            asyncio.get_running_loop().create_task(self._socket.close())

    # -- connection --------------------------------------------------------------

    def _start(self) -> None:
        if self.state != "new":
            return
        self.state = "connecting"
        self._tasks.append(asyncio.get_running_loop().create_task(self._run()))

    async def _run(self) -> None:
        try:
            self._socket = await asyncio.wait_for(self._openai.transcription_socket(self._key),
                                                  self._limits.asr_connect_timeout_s)
        except TimeoutError:
            self.stop("Timed out connecting to OpenAI transcription.")
            return
        except ProviderError as error:
            self.stop(str(error))
            return
        if self.state == "closed":
            await self._socket.close()
            return
        await self._configure()
        ready = asyncio.get_running_loop().call_later(self._limits.asr_connect_timeout_s, self._connect_timed_out)
        self._tasks.append(asyncio.get_running_loop().create_task(self._pump()))
        try:
            async for message in self._socket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    self._handle(json.loads(message.data))
                elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
                if self.state == "ready":
                    ready.cancel()
        except (aiohttp.ClientError, ValueError):
            pass
        finally:
            ready.cancel()
        self.stop("The OpenAI transcription connection closed.")

    async def _configure(self) -> None:
        config = self._hints.session_config(self._model, minimal=self._minimal_config)
        await self._socket.send_str(json.dumps({"type": "session.update", "session": config}))

    def _connect_timed_out(self) -> None:
        if self.state == "connecting":
            self.stop("Timed out connecting to OpenAI transcription.")

    def _handle(self, event: dict) -> None:
        kind = event.get("type")
        item = event.get("item_id")
        if kind in ("session.updated", "transcription_session.updated"):
            if self.state == "connecting":
                self.state = "ready"
                self._on_status("live", None)
                self._wake.set()
        elif kind == "input_audio_buffer.committed" and isinstance(item, str):
            self._commit_pending = False
            self._awaiting.add(item)
            self._wake.set()
        elif kind == "conversation.item.input_audio_transcription.delta" and isinstance(item, str):
            if item not in self._interim and len(self._interim) >= MAX_TRACKED_ITEMS:
                return
            text = (self._interim.get(item, "") + (event.get("delta") or ""))[:MAX_TRANSCRIPT_CHARS]
            self._interim[item] = text
            self._on_text(item, text, False)
        elif kind == "conversation.item.input_audio_transcription.completed" and isinstance(item, str):
            self._interim.pop(item, None)
            self._awaiting.discard(item)
            transcript = (event.get("transcript") or "").strip()
            if transcript:
                self._on_text(item, transcript[:MAX_TRANSCRIPT_CHARS], True)
            else:
                self._on_drop()
            self._wake.set()
        elif kind == "error" and self.state == "connecting" and not self._minimal_config:
            # An older model revision may reject an optional hint; retry once
            # with only the required configuration rather than failing.
            log.warning("Transcription configuration rejected; retrying without hints: %s", (event.get("error") or {}).get("message"))
            self._minimal_config = True
            asyncio.get_running_loop().create_task(self._configure())
        elif kind in ("conversation.item.input_audio_transcription.failed", "error"):
            error = event.get("error") or {}
            self.stop(describe_failure(error.get("status"), error.get("code")))

    # -- output ------------------------------------------------------------------

    async def _pump(self) -> None:
        """Send queued audio whenever the socket is ready and turns are not backed up."""
        try:
            while self.state != "closed":
                await self._wake.wait()
                self._wake.clear()
                while (self.state == "ready" and self._queue and not self._commit_pending
                       and len(self._awaiting) < self._limits.max_pending_commits):
                    chunk = self._queue.popleft()
                    if chunk is _END_OF_TURN:
                        await self._commit()
                        continue
                    self._queued_bytes -= len(chunk)
                    audio = base64.b64encode(resample_16k_to_24k(chunk)).decode()
                    await self._socket.send_str(json.dumps({"type": "input_audio_buffer.append", "audio": audio}))
                    self._turn_bytes += len(chunk)
                    if self._turn_bytes >= self._limits.max_turn_bytes:
                        await self._commit()
                if self._finishing and not self._queue and not self._commit_pending and not self._awaiting:
                    self._finished.set()
        except (aiohttp.ClientError, ConnectionError, RuntimeError):
            self.stop("Could not send audio to OpenAI transcription.")

    async def _commit(self) -> None:
        if self._turn_bytes >= self._limits.min_turn_bytes:
            await self._socket.send_str(json.dumps({"type": "input_audio_buffer.commit"}))
            self._commit_pending = True
        elif self._turn_bytes:
            await self._socket.send_str(json.dumps({"type": "input_audio_buffer.clear"}))
            self._on_drop()
        self._turn_bytes = 0
