"""A scriptable stand-in for the OpenAI endpoints the backend uses.

* ``POST /v1/responses`` answers JSON or, when ``stream`` is set, server-sent
  events. Each request is routed by purpose (understanding, answer, mock
  interviewer, translation, Debrief, screenshot) to a handler a test can
  replace, and every request body is recorded.
* ``GET /v1/realtime`` speaks the transcription protocol: it acknowledges
  ``session.update``, collects appended audio and, on each commit, replies
  with ``committed``, a few ``delta`` events and ``completed`` using the next
  scripted transcript for that connection's lane.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from aiohttp import WSMsgType, web


def purpose_of(body: dict[str, Any]) -> str:
    name = (((body.get("text") or {}).get("format") or {}).get("name")) or ""
    if name == "interviewer_utterance":
        return "understanding"
    if name == "local_interview_debrief":
        return "debrief"
    if name == "screen_analysis":
        return "screen"
    if name in ("practice_topics", "practice_question_bank"):
        return "topics"
    instructions = body.get("instructions") or ""
    if instructions.startswith("You coach a job candidate"):
        return "answer"
    if instructions.startswith("Act as a mock job interviewer"):
        return "interviewer"
    if instructions.startswith("Translate the interviewer"):
        return "translate"
    return "other"


def understanding(question: str = "", *, translation: str = "翻译", language: str = "en", complete: bool = True,
                  question_translation: str = "问题的翻译", intent: str = "general") -> dict[str, Any]:
    return {"language": language, "translation": translation, "is_question": bool(question), "complete": complete and bool(question),
            "question": question, "question_translation": question_translation if question else "", "intent": intent}


@dataclass
class TranscriptionConnection:
    lane_prompt: str
    config: dict[str, Any]
    audio_bytes: int = 0
    commits: int = 0
    events: list[str] = field(default_factory=list)


class FakeOpenAI:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.request_times: list[tuple[str, float]] = []
        self.understanding_delay = 0.0
        self.answer_first_token_delay = 0.0
        self.answer_token_gap = 0.0
        self.answer_chunks = ["**EN**\n- I led ", "the migration.\n", "**中文**\n- 我负责了迁移。"]
        self.handlers: dict[str, Callable[[dict], Any]] = {
            "understanding": lambda body: understanding("Tell me about your migration project?"),
            "interviewer": lambda body: "What is your biggest project?",
            "translate": lambda body: "你最大的项目是什么？",
            "debrief": lambda body: None,
            "screen": lambda body: {"title": "Two sum", "content": "Use a hash map."},
            "topics": lambda body: {"questions": [
                {"topic": "PDSCH scheduling", "question": "How did you tune PDSCH scheduling?", "prepared_answer": "Proportional fair, cut latency 30%."},
                {"topic": "HARQ timing", "question": "How did you budget HARQ timing?", "prepared_answer": "8 ms RTT budget, split DSP/FPGA."}]},
            "other": lambda body: "ok",
        }
        self.fail_purposes: dict[str, int] = {}
        # Transcripts per lane, keyed by the language prompt's role ("interviewer"/"interviewee") or "any".
        self.transcripts: dict[str, deque[str]] = defaultdict(deque)
        self.transcription_connections: list[TranscriptionConnection] = []
        self.reject_hints_once = False
        # GPT-Live: interviewer turns spoken in order; one candidate answer transcript per turn.
        self.live_enabled = True
        self.live_reject = False
        self.live_turns: deque[str] = deque(["Hi, I'm your interviewer. Tell me how you tuned PDSCH scheduling?",
                                             "Thanks. How did you budget HARQ timing?"])
        self.live_answers: deque[str] = deque(["I tuned the proportional fair scheduler and cut latency by 30 percent."])
        self.live_delegate = False
        self.live_events: list[dict[str, Any]] = []
        self.realtime_events: list[dict[str, Any]] = []
        self.live_audio_nonzero = 0
        self.live_audio_zero = 0
        self.live_audio_chunks = 2
        self.app = web.Application()
        self.app.router.add_get("/v1/models", self._models)
        self.app.router.add_post("/v1/responses", self._responses)
        self.app.router.add_get("/v1/realtime", self._realtime)
        self.app.router.add_get("/v1/live/sessions", self._live)

    def live_of(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.live_events if event.get("type") == kind]

    # -- helpers for tests -----------------------------------------------------

    def bodies(self, purpose: str) -> list[dict[str, Any]]:
        return [body for body in self.requests if purpose_of(body) == purpose]

    def script_transcripts(self, *texts: str) -> None:
        self.transcripts["any"].extend(texts)

    # -- endpoints ---------------------------------------------------------------

    async def _models(self, request: web.Request) -> web.Response:
        return web.json_response({"data": []})

    async def _responses(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        self.requests.append(body)
        purpose = purpose_of(body)
        self.request_times.append((purpose, time.monotonic()))
        if request.headers.get("Authorization") != "Bearer test-key":
            return web.json_response({"error": {"code": "invalid_api_key"}}, status=401)
        if self.fail_purposes.get(purpose):
            self.fail_purposes[purpose] -= 1
            return web.json_response({"error": {"code": "server_error"}}, status=500)
        if body.get("stream"):
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            await asyncio.sleep(self.answer_first_token_delay)
            for index, chunk in enumerate(self.answer_chunks):
                if index:
                    await asyncio.sleep(self.answer_token_gap)
                event = json.dumps({"type": "response.output_text.delta", "delta": chunk}, ensure_ascii=False)
                await response.write(f"event: response.output_text.delta\ndata: {event}\n\n".encode())
            await response.write(b'event: response.completed\ndata: {"type":"response.completed"}\n\n')
            await response.write_eof()
            return response
        if purpose == "understanding":
            await asyncio.sleep(self.understanding_delay)
        value = self.handlers[purpose](body)
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return web.json_response({"output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}]})

    async def _live(self, request: web.Request) -> web.StreamResponse:
        if not self.live_enabled:
            return web.Response(status=404)
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        heard_bytes = 0  # candidate speech (non-silent audio) since the interviewer last spoke

        async def speak() -> None:
            if not self.live_turns:
                return
            text = self.live_turns.popleft()
            for _ in range(self.live_audio_chunks):
                await socket.send_json({"type": "session.output_audio.delta", "delta": base64.b64encode(bytes(4800)).decode()})
            words = text.split(" ")
            for index, word in enumerate(words):
                await socket.send_json({"type": "session.output_transcript.delta", "delta": (" " if index else "") + word})

        async for message in socket:
            if message.type != WSMsgType.TEXT:
                continue
            event = json.loads(message.data)
            kind = event.get("type")
            if kind != "session.input_audio.append":
                self.live_events.append(event)
            if kind == "session.start":
                if self.live_reject:
                    await socket.send_json({"type": "error", "error": {"code": "model_not_found", "message": "no access"}})
                    await socket.close()
                    break
                await socket.send_json({"type": "session.started", "session": {"id": "live_1"}})
                if self.live_delegate:
                    await socket.send_json({"type": "session.delegation.created", "delegation": {"id": "del_1", "target": "client"}})
            elif kind == "session.commentary.append":
                await speak()
            elif kind == "session.input_audio.append":
                audio = base64.b64decode(event["audio"])
                if any(audio):
                    self.live_audio_nonzero += len(audio)
                    heard_bytes += len(audio)
                else:
                    self.live_audio_zero += len(audio)
                if heard_bytes >= 9600 and self.live_answers:  # ~200 ms of speech
                    heard_bytes = 0
                    answer = self.live_answers.popleft()
                    for index, word in enumerate(answer.split(" ")):
                        await socket.send_json({"type": "session.input_transcript.delta", "delta": (" " if index else "") + word})
                    await asyncio.sleep(0.5)
                    await speak()
            elif kind == "session.close":
                await socket.send_json({"type": "session.closed", "usage": {}})
                await socket.close()
                break
        return socket

    async def _realtime_conversation(self, socket: web.WebSocketResponse) -> web.WebSocketResponse:
        """Speech-to-speech Realtime session: scripted interviewer turns, server-VAD-style candidate turns."""
        heard_bytes = 0
        turn = 0
        silent_bytes = 24000
        turn_reported = False

        async def respond() -> None:
            nonlocal turn
            if not self.live_turns:
                return
            turn += 1
            item_id = f"item_assistant_{turn}"
            text = self.live_turns.popleft()
            for _ in range(self.live_audio_chunks):
                await socket.send_json({"type": "response.output_audio.delta", "item_id": item_id,
                                        "delta": base64.b64encode(bytes(4800)).decode()})
            words = text.split(" ")
            for index, word in enumerate(words):
                await socket.send_json({"type": "response.output_audio_transcript.delta", "item_id": item_id,
                                        "delta": (" " if index else "") + word})
            await socket.send_json({"type": "response.output_audio_transcript.done", "item_id": item_id, "transcript": text})
            await socket.send_json({"type": "response.done", "response": {"status": "completed"}})

        async for message in socket:
            if message.type != WSMsgType.TEXT:
                continue
            event = json.loads(message.data)
            kind = event.get("type")
            if kind != "input_audio_buffer.append":
                self.realtime_events.append(event)
            if kind == "session.update":
                if self.live_reject:
                    await socket.send_json({"type": "error", "error": {"code": "model_not_found", "message": "no access"}})
                    continue
                await socket.send_json({"type": "session.updated", "session": event["session"]})
            elif kind == "response.create":
                await respond()
            elif kind == "input_audio_buffer.append":
                audio = base64.b64decode(event["audio"])
                if any(audio):
                    self.live_audio_nonzero += len(audio)
                    if silent_bytes >= 24000:  # like server VAD: a new turn needs 0.5 s of silence first
                        await socket.send_json({"type": "input_audio_buffer.speech_started"})
                    silent_bytes = 0
                    heard_bytes += 0 if turn_reported else len(audio)
                else:
                    silent_bytes += len(audio)
                    if silent_bytes >= 24000:
                        turn_reported = False  # one transcription per turn; the next starts after 0.5 s of silence
                    self.live_audio_zero += len(audio)
                if heard_bytes >= 9600 and self.live_answers:
                    heard_bytes, turn_reported = 0, True
                    answer = self.live_answers.popleft()
                    await socket.send_json({"type": "conversation.item.input_audio_transcription.completed",
                                            "item_id": "item_user", "transcript": answer})
                    # create_response is off: the backend decides when the interviewer replies.
        return socket

    def realtime_of(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.realtime_events if event.get("type") == kind]

    async def _realtime(self, request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        if request.query.get("model"):
            if request.headers.get("Authorization") != "Bearer test-key":
                await socket.close(code=4401)
                return socket
            return await self._realtime_conversation(socket)
        if request.headers.get("Authorization") != "Bearer test-key":
            await socket.close(code=4401)
            return socket
        connection = TranscriptionConnection(lane_prompt="", config={})
        self.transcription_connections.append(connection)
        item = 0
        async for message in socket:
            if message.type != WSMsgType.TEXT:
                continue
            event = json.loads(message.data)
            connection.events.append(event["type"])
            if event["type"] == "session.update":
                transcription = event["session"]["audio"]["input"]["transcription"]
                if self.reject_hints_once and "delay" in transcription:
                    self.reject_hints_once = False
                    await socket.send_json({"type": "error", "error": {"message": "unknown parameter delay"}})
                    continue
                connection.config = transcription
                await socket.send_json({"type": "session.updated"})
            elif event["type"] == "input_audio_buffer.append":
                connection.audio_bytes += len(base64.b64decode(event["audio"]))
            elif event["type"] == "input_audio_buffer.commit":
                item += 1
                connection.commits += 1
                item_id = f"item_{id(connection)}_{item}"
                await socket.send_json({"type": "input_audio_buffer.committed", "item_id": item_id})
                text = self.transcripts["any"].popleft() if self.transcripts["any"] else ""
                words = text.split(" ")
                for index in range(len(words)):
                    delta = (" " if index else "") + words[index]
                    await socket.send_json({"type": "conversation.item.input_audio_transcription.delta", "item_id": item_id, "delta": delta})
                await socket.send_json({"type": "conversation.item.input_audio_transcription.completed", "item_id": item_id, "transcript": text})
        return socket
