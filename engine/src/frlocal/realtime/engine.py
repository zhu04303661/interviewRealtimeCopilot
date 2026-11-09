"""Registry of live interviews and the WebSocket endpoint the app connects to.

``GET /realtime/{session_id}`` upgrades to a WebSocket. The first text frame
must be a ``hello`` carrying the signed-in account's session token; the engine
then streams frames for that interview until the client disconnects or the
interview ends. Only the account that created an interview can connect to it,
and signing out closes every interview of that account.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from aiohttp import WSMsgType, web

from ..config import Settings
from ..openai import OpenAI, ProviderError
from .protocol import decode_text, parse_audio_frame
from .session import DocumentReader, InterviewSession

log = logging.getLogger(__name__)

CLOSE_UNAUTHORIZED = 4401


class RealtimeEngine:
    def __init__(self, settings: Settings, openai: OpenAI, read_document: DocumentReader,
                 current: Callable[[], tuple[str, str] | None]) -> None:
        """``current`` returns ``(username, session_token)`` for the signed-in account."""
        self.settings = settings
        self.openai = openai
        self.read_document = read_document
        self.current = current
        self.sessions: dict[str, InterviewSession] = {}

    def _owned(self, session_id: str) -> InterviewSession | None:
        session = self.sessions.get(session_id)
        account = self.current()
        return session if session and account and session.username == account[0] else None

    # ── lifecycle used by the workspace API ─────────────────────────────────

    def create(self, *, username: str, session: dict[str, Any], goal: dict[str, Any] | None, ws_base: str) -> dict[str, str]:
        """Register a new interview and return the address the app connects to."""
        account = self.current()
        if not account or account[0] != username:
            raise ProviderError("Sign in to the local backend first.")
        key = self.openai.require_key()
        interview = InterviewSession(
            session_id=session["session_id"], username=username, key=key, topology=session["topology"],
            config=session.get("config") or {}, goal=goal, settings=self.settings, openai=self.openai,
            read_document=self.read_document)
        self.sessions[interview.id] = interview
        return {"ws_url": f"{ws_base}/realtime/{interview.id}"}

    async def end(self, username: str, session: dict[str, Any]) -> dict[str, Any]:
        """Finish an interview and hand back what the workspace saves.

        Returns ``segments`` and ``questions`` and, when the candidate spoke,
        a ``report_task`` that resolves to the Debrief (or ``None``).
        """
        interview = self.sessions.get(session["session_id"])
        if not interview or interview.username != username:
            return {"segments": [], "questions": []}
        await interview.finish()
        self.sessions.pop(interview.id, None)
        segments = [s.as_dict() for s in interview.segments]
        result: dict[str, Any] = {"segments": segments, "questions": interview.questions}
        account = self.current()
        if any(s["role"] == "interviewee" for s in segments) and account and account[0] == username:
            async def report() -> dict | None:
                try:
                    from ..workspace.records import parse_time
                    created, ended = parse_time(session.get("created_at")), parse_time(session.get("ended_at"))
                    duration = max(0, round((ended - created).total_seconds())) if created and ended else None
                    return await interview.debrief(session.get("created_at"), session.get("ended_at"), duration)
                except Exception as error:
                    log.warning("Debrief failed: %s", error)
                    return None
            result["report_task"] = asyncio.get_running_loop().create_task(report())
        return result

    def publish_screen_answer(self, username: str, session_id: str, analysis_id: str, text: str) -> bool:
        interview = self.sessions.get(session_id)
        return bool(interview and interview.username == username and interview.publish_screen_answer(analysis_id, text))

    def clear_account(self, username: str | None) -> None:
        """Signing out stops every interview of that account."""
        for session_id, interview in list(self.sessions.items()):
            if interview.username == username:
                interview.stop_now()
                self.sessions.pop(session_id, None)

    async def close(self) -> None:
        for interview in list(self.sessions.values()):
            interview.stop_now()
        self.sessions.clear()

    # ── WebSocket endpoint ──────────────────────────────────────────────────

    async def handle_socket(self, request: web.Request) -> web.WebSocketResponse:
        session_id = request.match_info["session_id"]
        socket = web.WebSocketResponse(max_msg_size=64 * 1024, heartbeat=None)
        await socket.prepare(request)
        interview = self._owned(session_id)
        if not interview or interview.ended:
            await socket.close(code=CLOSE_UNAUTHORIZED)
            return socket
        outbox: asyncio.Queue[str] = asyncio.Queue()
        writer = asyncio.get_running_loop().create_task(self._write(socket, outbox))
        accepted = False
        try:
            async for message in socket:
                if self._owned(session_id) is not interview:
                    await socket.close(code=CLOSE_UNAUTHORIZED)
                    break
                if message.type == WSMsgType.TEXT:
                    frame = decode_text(message.data)
                    kind = frame.get("type")
                    if not accepted:
                        account = self.current()
                        if (kind != "hello" or frame.get("v") != 1 or frame.get("session_id") != session_id
                                or not account or frame.get("jwt") != account[1]
                                or not interview.attach(outbox, frame.get("streams"), frame.get("last_seen_seq"))):
                            await socket.close(code=CLOSE_UNAUTHORIZED)
                            break
                        accepted = True
                    elif kind == "ping":
                        interview.emit("pong", {})
                    elif kind == "finalize":
                        interview.end_of_turn(frame.get("stream"))
                    elif kind == "answer_request" and str(frame.get("intent", "")).startswith("practice."):
                        # The practice sidebar reuses the answer-request channel: the
                        # intent names the command, utterance/gate_seq carry its value.
                        value = frame.get("gate_seq") if frame["intent"] == "practice.goto" else frame.get("utterance")
                        interview.practice_control(frame["intent"], value)
                    elif kind == "answer_request" and isinstance(frame.get("utterance"), str):
                        gate_seq = frame.get("gate_seq")
                        gate_seq = gate_seq if isinstance(gate_seq, int) else None
                        if frame.get("intent") == "continue":  # "Expand answer" on the candidate's own line
                            interview.continue_answer(frame["utterance"], gate_seq)
                        else:
                            interview.answer(frame["utterance"], gate_seq)
                elif message.type == WSMsgType.BINARY and accepted:
                    audio = parse_audio_frame(message.data)
                    if audio:
                        interview.audio(audio.stream, audio.sequence, audio.pcm)
                elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            if accepted and interview.uses(outbox):
                interview.detach()
            outbox.put_nowait("")
            await writer
        return socket

    @staticmethod
    async def _write(socket: web.WebSocketResponse, outbox: asyncio.Queue[str]) -> None:
        """Send queued frames in order; an empty string closes the socket."""
        try:
            while True:
                frame = await outbox.get()
                if frame == "":
                    break
                await socket.send_str(frame)
        except (ConnectionResetError, RuntimeError):
            pass
        finally:
            if not socket.closed:
                await socket.close()
