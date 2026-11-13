"""One live interview: audio lanes, transcript, questions and answer hints.

An :class:`InterviewSession` is created when the app starts a session and
lives until the session ends. The app's realtime client may connect, drop and
reconnect several times in between; frames are numbered and the most recent
ones are kept so a reconnecting client can ask for what it missed.

Timing goals (each step starts as soon as the previous one finishes):

* interim transcript text is forwarded as each delta arrives;
* the translation and question decision come from one short model call made
  when an interviewer utterance is final;
* answer hints are streamed token by token; a newer question supersedes an
  unfinished answer instead of waiting behind it.
"""

from __future__ import annotations

import asyncio
import json
import hashlib
import logging
import random
import re
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import Settings
from ..openai import OpenAI, ProviderError
from ..retrieval import Source, build_context_documents, prepare_sources
from . import coach, understanding
from .asr import TranscriptionHints, TranscriptionStream
from .live import LiveConversation
from .voice_agent import RealtimeVoiceAgent
from .protocol import STREAM_ROLES, encode_frame, valid_stream_declarations

log = logging.getLogger(__name__)

# Reads prepared documents: (username, document_id) -> (metadata, text|None) | None
DocumentReader = Callable[[str, str], Awaitable[tuple[dict, str | None] | None]]

# Lone hesitation sounds (often room noise or speaker echo) are not answers.
FILLER = re.compile(r"^\W*(?:uh+|um+|erm+|hmm+|mm+|ah+|oh+|呃+|嗯+|啊+|额+|哦+)\W*$", re.I)


def is_filler(text: str) -> bool:
    return bool(FILLER.match(text.strip()))


CJK = re.compile(r"[\u4e00-\u9fff]")


def useful_translation(translation: str, original: str) -> bool:
    """A translation worth showing: present, not the original repeated, and in the other language
    (English and other Latin-script speech → Chinese, Chinese → English)."""
    def squash(value: str) -> str:
        return re.sub(r"\W+", "", value).lower()
    if not translation.strip() or squash(translation) == squash(original):
        return False
    source_is_chinese = len(CJK.findall(original)) > len(re.findall(r"[A-Za-z]", original)) / 4
    return not CJK.search(translation) if source_is_chinese else bool(CJK.search(translation))


# Share of a microphone line's words that, when all heard from the interviewer
# just before, marks it as the speakers' echo rather than the candidate.
ECHO_OVERLAP = 0.7

SELF_INTRODUCTION = re.compile(r"tell me about yourself|introduce yourself|walk me through your (?:background|cv|resume|career)|"
                               r"(?:one-line |your )?career story|自我介绍|介绍一下(?:你)?自己", re.I)

# How long the Realtime practice interviewer waits for the question plan before greeting anyway.
PLAN_WAIT_S = 2.5

# How long an unfinished-sounding question waits for more before it is answered anyway.
AUTO_ANSWER_WAIT_S = 2.0

MOCK_REPLY_PAUSE_S = 1.5   # silence after the candidate's last final before the AI interviewer asks again


@dataclass
class Lane:
    """One capture lane (microphone or computer audio) and its transcription."""

    role: str
    source: str
    stream_id: str
    asr: TranscriptionStream
    last_sequence: int = -1
    retry_at: float = 0.0


@dataclass
class Turn:
    turn_id: str
    task: asyncio.Task


@dataclass
class Segment:
    seq: int
    role: str
    text: str
    segment_id: str

    def as_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "role": self.role, "text": self.text, "segment_id": self.segment_id}


@dataclass
class _Pending:
    """Interviewer speech since the last question decision."""

    texts: list[str] = field(default_factory=list)
    analysis: int = 0          # number of the newest analysis; older results do not decide

    @property
    def text(self) -> str:
        return " ".join(self.texts)


class InterviewSession:
    def __init__(self, *, session_id: str, username: str, key: str, topology: str, config: dict[str, Any],
                 goal: dict[str, Any] | None, settings: Settings, openai: OpenAI, read_document: DocumentReader) -> None:
        if topology not in STREAM_ROLES:
            raise ProviderError("External-audio interviews require speaker separation, which is unavailable in the local backend.")
        self.id = session_id
        self.username = username
        self.key = key
        self.topology = topology
        self.settings = settings
        self.openai = openai
        self._read_document = read_document
        self.config = {
            **config, "goal": coach.goal_brief(goal),
            "interviewer_source": "backend_driven" if topology == "mock" else "external_audio",
        }
        self._goal = goal or {}
        self.ended = False
        self.segments: list[Segment] = []
        self.questions: list[dict[str, Any]] = []
        self._seq = 0
        self._replay: deque[tuple[int, str]] = deque(maxlen=settings.limits.replay_frames)
        self._outbox: asyncio.Queue[str] | None = None
        self.lanes: list[Lane] = []
        self._draining: set[asyncio.Task] = set()
        self._tasks: set[asyncio.Task] = set()
        self._turn: Turn | None = None
        self._interviewer_task: asyncio.Task | None = None
        self._mock_started = False
        self._mock_timer: asyncio.TimerHandle | None = None
        self._pending = _Pending()
        self._sources: asyncio.Task | None = None
        # Spoken practice: the GPT-Live interviewer and the turns being assembled from its transcripts.
        self._live: RealtimeVoiceAgent | LiveConversation | None = None
        self._live_say: dict[str, str] | None = None        # {"say_id", "text"} while the interviewer speaks
        self._live_answer: dict[str, str] | None = None     # {"segment_id", "text"} while the candidate speaks
        self._live_timer: asyncio.TimerHandle | None = None
        # Practice plan: questions prepared in the materials, asked in order without repeats.
        self._bank: list[dict[str, str]] | None = None
        self._bank_keys: set[str] = set()
        self._bank_index = 0          # the prepared question being discussed
        self._follow_up_next = False  # the next interviewer turn is this question's one follow-up
        self._asked: set[int] = set()  # prepared questions already asked
        # sequential | random | ai (improvised, never repeating); Preflight may choose the starting mode.
        mode = self.config.get("practice_mode")
        self._practice_mode = mode if mode in ("sequential", "random", "ai") else "sequential"
        self._reply_timer: asyncio.TimerHandle | None = None
        self._plan_task: asyncio.Task | None = None

    # ── frames ──────────────────────────────────────────────────────────────

    def emit(self, kind: str, data: dict[str, Any]) -> int:
        """Number a frame, remember it for replay and send it if connected."""
        self._seq += 1
        frame = encode_frame(kind, self._seq, data)
        if kind not in ("pong", "say.audio"):  # audio is not replayed after a reconnect
            self._replay.append((self._seq, frame))
        if self._outbox is not None:
            self._outbox.put_nowait(frame)
        return self._seq

    def attach(self, outbox: asyncio.Queue[str], streams: Any, last_seen_seq: Any) -> bool:
        """Accept a (re)connected client; ``False`` if its stream layout is wrong."""
        if not valid_stream_declarations(self.topology, streams):
            return False
        self.detach()
        self._outbox = outbox
        self._start_lanes(streams)
        self.emit("session.state", {"config": self.config, "capabilities": []})
        if isinstance(last_seen_seq, int):
            for seq, frame in list(self._replay):
                if seq > last_seen_seq and '"type":"session.state"' not in frame:
                    outbox.put_nowait(frame)
        self._spawn(self.openai.warm_up())
        if self.topology == "mock":
            self._spawn(self._start_live())
        return True

    def detach(self) -> None:
        """The client disconnected: finish transcribing buffered audio, stop work."""
        if self._outbox is None:
            return
        self._outbox = None
        for lane in self.lanes:
            self._drain(lane.asr)
        self.lanes = []
        self._cancel_turn(announce=False)
        if self._interviewer_task:
            self._interviewer_task.cancel()
        if self._mock_timer:
            self._mock_timer.cancel()
        self._close_live()

    @property
    def connected(self) -> bool:
        return self._outbox is not None

    def uses(self, outbox: asyncio.Queue[str]) -> bool:
        """Whether ``outbox`` belongs to the currently attached connection."""
        return self._outbox is outbox

    # ── audio lanes ─────────────────────────────────────────────────────────

    def _hints(self) -> TranscriptionHints:
        languages = ["en", "zh"]
        configured = str(self.config.get("language") or "").split("-")[0].lower()
        if configured and configured not in languages and configured.isalpha() and len(configured) == 2:
            languages.append(configured)
        goal = self.config["goal"]
        prompt = "A job interview" + (f" for {goal['role']}" if goal.get("role") else "") + (
            f" at {goal['company']}" if goal.get("company") else "") + ". Speech may mix English and Chinese."
        return TranscriptionHints(languages=languages, prompt=prompt[:400], keywords=coach.transcription_keywords(self._goal))

    def _new_asr(self, role: str) -> TranscriptionStream:
        return TranscriptionStream(
            self.openai, self.key, self.settings.models.transcription, self._hints(), self.settings.limits,
            on_text=lambda item, text, final, role=role: self._on_text(role, item, text, final),
            on_drop=lambda role=role: self.emit("transcript.dropped", {"role": role}),
            on_status=lambda state, message, role=role: self._on_status(role, state, message),
        )

    def _start_lanes(self, streams: list[dict]) -> None:
        roles = STREAM_ROLES[self.topology]
        self.lanes = [Lane(role=role, source=str(declared.get("source") or ""), stream_id=str(declared.get("stream_id") or role),
                           asr=self._new_asr(role)) for role, declared in zip(roles, streams, strict=True)]

    def _on_status(self, role: str, state: str, message: str | None) -> None:
        lane = next((lane for lane in self.lanes if lane.role == role), None)
        if lane and state == "degraded":
            lane.retry_at = time.monotonic() + self.settings.limits.asr_retry_after_s
        self.emit("transcription.state", {"state": state, "stream_id": lane.stream_id if lane else role, "message": message})

    def audio(self, stream_index: int, sequence: int, pcm: bytes) -> None:
        if not 0 <= stream_index < len(self.lanes) or self.ended:
            return
        lane = self.lanes[stream_index]
        if sequence <= lane.last_sequence:
            return  # duplicate after a reconnect replay
        lane.last_sequence = sequence
        if self._live is not None:
            self._live.append(pcm)
            return
        if lane.asr.closed and time.monotonic() >= lane.retry_at:
            lane.asr = self._new_asr(lane.role)
        lane.asr.append(pcm)

    def end_of_turn(self, stream_index: Any) -> None:
        if self._live is not None:
            return  # GPT-Live detects turns itself
        if isinstance(stream_index, int) and 0 <= stream_index < len(self.lanes):
            self.lanes[stream_index].asr.end_turn()

    def _drain(self, asr: TranscriptionStream) -> None:
        task = asyncio.get_running_loop().create_task(asr.drain())
        self._draining.add(task)
        task.add_done_callback(self._draining.discard)

    # ── transcript ──────────────────────────────────────────────────────────

    def _echoes(self, text: str, other: str) -> bool:
        """Whether ``text`` is mostly words the ``other`` speaker just said (audio leaking between lanes)."""
        words = re.findall(r"\w+", text.lower())
        if not words:
            return False
        now = self._seq
        recent = {w for s in self.segments[-6:] if s.role == other and now - s.seq < 400
                  for w in re.findall(r"\w+", s.text.lower())}
        return bool(recent) and sum(w in recent for w in words) / len(words) >= ECHO_OVERLAP

    def _on_text(self, role: str, item_id: str, text: str, final: bool) -> None:
        if self.topology == "general" and role in ("interviewer", "interviewee"):
            # The microphone hears the speakers, and calls can loop the candidate's
            # voice back into computer audio; drop a lane's copy of the other's words.
            other = "interviewer" if role == "interviewee" else "interviewee"
            if (role == "interviewee" and is_filler(text)) or (final and self._echoes(text, other)):
                if final:
                    log.info("Ignored %s text that echoes the %s or is a filler: %r", role, other, text[:80])
                return
        lane = next((lane for lane in self.lanes if lane.role == role), None)
        seq = self.emit("transcript", {"segment_id": item_id, "role": role, "text": text, "final": final,
                                       "source": lane.source if lane else ""})
        if not final:
            return
        segment = Segment(seq, role, text, item_id)
        self.segments.append(segment)
        if self.ended or not self.connected:
            return
        if self.topology == "mock":
            if role == "interviewee":
                self._ask_soon(MOCK_REPLY_PAUSE_S)
        elif role == "interviewer":
            self._understand(segment)
        elif self._pending.texts:
            # The candidate started answering: later interviewer speech starts a
            # new question. An analysis already running still decides.
            self._pending.texts = []

    # ── interviewer understanding ───────────────────────────────────────────

    def _understand(self, segment: Segment) -> None:
        self._pending.texts.append(segment.text)
        self._pending.analysis += 1
        number, pending_text = self._pending.analysis, self._pending.text
        recent = coach.recent_transcript([s.as_dict() for s in self.segments[:-1]], count=8)
        started = time.monotonic()

        async def run() -> None:
            try:
                result = await understanding.analyze(
                    self.openai, self.settings.models.understanding, latest=segment.text, pending=pending_text,
                    recent=recent, goal=self.config["goal"], timeout=self.settings.limits.understanding_timeout_s)
            except (TimeoutError, ProviderError, ValueError) as error:
                log.info("Interviewer understanding failed, using the heuristic: %s", error)
                result = None
            if result and useful_translation(result.translation, segment.text):
                self.emit("transcript.translation", {
                    "segment_id": segment.segment_id, "text": result.translation, "language": result.language,
                    "target_language": "en" if result.language == "zh" else "zh"})
            elif result:  # the combined call sometimes rewords instead of translating
                self._spawn(self._translate_say(segment.segment_id, segment.text))
            if number != self._pending.analysis or self.ended:
                return  # a newer utterance arrived; its analysis decides
            self._decide(result or understanding.heuristic(pending_text), pending_text, started)

        self._spawn(run())

    def _decide(self, result: understanding.Understanding, pending_text: str, started: float) -> None:
        decision = result.decision
        if decision == "ignore" and understanding.heuristic(pending_text).is_question:
            # The model missed an obvious question ("…?", "How did…"); answer rather than stay silent.
            decision = "respond"
        utterance = result.question or pending_text
        gate_seq = self.emit("gate.verdict", {
            "utterance": utterance, "decision": decision, "intent": result.intent, "source": "local",
            "translation": result.question_translation, "latency_ms": round((time.monotonic() - started) * 1000),
        })
        if decision == "await_more":
            # The question may be unfinished. If the interviewer adds nothing
            # within a short pause, answer what was asked so far.
            number = self._pending.analysis

            def answer_if_still_waiting() -> None:
                if self._pending.analysis == number and not self.ended and self.connected:
                    self._pending = _Pending(analysis=number + 1)
                    self.questions.append({"seq": gate_seq, "text": utterance})
                    self.answer(utterance, gate_seq)

            asyncio.get_running_loop().call_later(AUTO_ANSWER_WAIT_S, answer_if_still_waiting)
            return
        self._pending = _Pending(analysis=self._pending.analysis + 1)
        if decision == "respond":
            self.questions.append({"seq": gate_seq, "text": utterance})
            self.answer(utterance, gate_seq)

    # ── answer hints ────────────────────────────────────────────────────────

    async def _context(self, query: str) -> tuple[dict[str, Any], list[dict]]:
        if self._sources is None:
            self._sources = asyncio.get_running_loop().create_task(self._load_sources())
        sources = await self._sources
        documents, refs = build_context_documents(sources, query, self.settings.limits)
        return {
            "goal": self.config["goal"], "language": self.config.get("language"), "documents": documents,
            "recent_transcript": coach.recent_transcript([s.as_dict() for s in self.segments]),
        }, refs

    async def _load_sources(self) -> list[Source]:
        ids = self.config.get("document_ids")
        if not isinstance(ids, list):
            return []
        unique = list(dict.fromkeys(i for i in ids if isinstance(i, str)))[:self.settings.limits.max_source_documents]
        loaded = await asyncio.gather(*(self._read_document(self.username, i) for i in unique), return_exceptions=True)
        documents = [item for item in loaded if isinstance(item, tuple) and isinstance(item[1], str)]
        return prepare_sources(documents, self.settings.limits)

    def continue_answer(self, said: str, gate_seq: int | None) -> None:
        """Hint for what the candidate can add to what they just said (the "Expand answer" button)."""
        question = self.questions[-1]["text"] if self.questions else ""
        self.answer(question or said, gate_seq, said=said, source="manual")

    def answer(self, question: str, gate_seq: int | None, *, source: str = "spoken", said: str | None = None) -> None:
        """Stream an answer hint (or, with ``said``, a continuation); supersedes any unfinished one."""
        if self.ended or not question.strip():
            return
        self._cancel_turn(announce=True)
        turn_id = str(uuid.uuid4())
        self.emit("turn.started", {"turn_id": turn_id, **({"gate_seq": gate_seq} if gate_seq is not None else {}), "source": source})

        async def run() -> None:
            try:
                context, refs = await self._context(f"{question} {said}" if said else question)
                if self._prepared_answer:
                    context["prepared_answer_for_current_question"] = self._prepared_answer
                body = coach.answer_request(self.settings.models.coaching, context, question, self.settings.limits, said=said)
                produced = False
                async for delta in self.openai.stream(body, timeout=self.settings.limits.answer_timeout_s, key=self.key):
                    produced = True
                    self.emit("turn.token", {"turn_id": turn_id, "delta": delta})
                if not produced:
                    raise ProviderError("OpenAI returned no text for this request.")
                self.emit("turn.done", {"turn_id": turn_id, "rag": {"outcome": "used" if refs else "none", "refs": refs[:8]}})
            except asyncio.CancelledError:
                raise
            except ProviderError as error:
                self.emit("error", {"code": "turn_failed", "turn_id": turn_id, "message": str(error)})
            except Exception:
                log.exception("Answer generation failed")
                self.emit("error", {"code": "turn_failed", "turn_id": turn_id, "message": "The answer could not be generated."})
            finally:
                if self._turn and self._turn.turn_id == turn_id:
                    self._turn = None

        self._turn = Turn(turn_id, self._spawn(run()))

    def _cancel_turn(self, *, announce: bool) -> None:
        turn, self._turn = self._turn, None
        if turn and not turn.task.done():
            turn.task.cancel()
            if announce:
                self.emit("turn.superseded", {"turn_id": turn.turn_id})

    def publish_screen_answer(self, analysis_id: str, text: str) -> bool:
        """Show a screenshot explanation as an answer card."""
        if not self.connected or self.ended or not text.strip():
            return False
        turn_id = str(uuid.uuid4())
        self.emit("turn.started", {"turn_id": turn_id, "source": "screen", "analysis_id": analysis_id})
        self.emit("turn.token", {"turn_id": turn_id, "delta": text})
        self.emit("turn.done", {"turn_id": turn_id})
        return True

    # ── mock interviewer ────────────────────────────────────────────────────

    def _ask_soon(self, delay: float) -> None:
        if self._mock_timer:
            self._mock_timer.cancel()
        self._mock_timer = asyncio.get_running_loop().call_later(delay, self._ask)

    def _ask(self) -> None:
        if self.ended or not self.connected or (self._interviewer_task and not self._interviewer_task.done()):
            return

        async def run() -> None:
            try:
                bank, _ = await self._practice_plan()
                index = self._pick_next()
                if index is not None:
                    # Ask the prepared questions (order per the practice mode), one each turn.
                    self._mark_asked(index)
                    text = bank[index]["question"]
                else:
                    query = " ".join(filter(None, [self.config["goal"].get("role"), *(s.text for s in self.segments[-3:])]))
                    context, _ = await self._context(query)
                    body = coach.interviewer_request(self.settings.models.understanding, context, self.config.get("persona"))
                    text = await self.openai.respond(body, timeout=self.settings.limits.answer_timeout_s, key=self.key)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.info("Mock interviewer failed: %s", error)
                # Provider messages (allowance used up, key rejected) are written for the user; show them as they are.
                message = str(error) if isinstance(error, ProviderError) else "interviewer generation failed"
                self.emit("error", {"code": "provider" if isinstance(error, ProviderError) else "internal", "message": message,
                                    "retry": {"state": "exhausted"}})
                return
            if self.ended or not self.connected:
                return
            self._say_text(text)

        self._interviewer_task = self._spawn(run())

    def _say_text(self, text: str, planned: bool = False) -> None:
        """Show a text interviewer question (no voice) and translate it."""
        say_id = str(uuid.uuid4())
        seq = self.emit("say", {"say_id": say_id, "text": text})
        self._mock_started = True
        self.segments.append(Segment(seq, "interviewer", text, say_id))
        self.questions.append({"seq": seq, "text": text})
        self._spawn(self._translate_say(say_id, text))

    # ── spoken practice (GPT-Live) ──────────────────────────────────────────

    async def _practice_plan(self) -> tuple[list[dict[str, str]], str]:
        """The questions prepared in the knowledge sources, plus resume text for follow-ups.

        Every material is read in parts, extracted in parallel and cached on disk
        per part. The plan is returned once the first part is ready; later parts
        are appended in document order as they finish (indices never shift).
        """
        sources = await (self._sources or asyncio.get_running_loop().create_task(self._load_sources()))
        resume = next((s.text for s in sources if s.kind == "resume"), "")
        if self._bank is not None:
            return self._bank, resume
        materials = [s for s in sources if s.kind != "resume"]
        generate = not materials
        jobs = [(s.filename, part) for s in (materials or sources[:1]) for part in coach.question_chunks(s.text)]
        if not jobs:  # no documents at all: questions from the goal and job description
            jobs = [("goal", json.dumps(self.config["goal"], ensure_ascii=False))]
        limit = asyncio.Semaphore(4)
        tasks = [asyncio.get_running_loop().create_task(self._extract_part(name, part, generate, limit)) for name, part in jobs]
        self._bank, self._bank_keys = [], set()
        self._add_questions(await tasks[0])
        if len(tasks) > 1:
            self._spawn(self._append_parts(tasks[1:]))
        return self._bank, resume

    async def _extract_part(self, filename: str, text: str, generate: bool, limit: asyncio.Semaphore) -> list[dict[str, str]]:
        model = self.settings.models.understanding
        digest = hashlib.sha256(json.dumps([model, coach.QUESTION_BANK_INSTRUCTIONS, generate, text]).encode()).hexdigest()
        cache = self.settings.workspace_dir / self.username / "practice-questions" / f"{digest}.json"
        try:
            return [dict(q, question=coach.spoken_question(q["question"])) for q in json.loads(cache.read_text())]
        except (OSError, ValueError, TypeError, KeyError):
            pass
        body = coach.question_bank_request(model, self.config["goal"], {"filename": filename, "text": text}, generate=generate)
        async with limit:
            for attempt in (1, 2):  # one retry: long extractions occasionally drop on the network
                try:
                    questions = coach.parse_question_bank(await self.openai.respond(
                        body, timeout=self.settings.limits.understanding_timeout_s * 8, key=self.key))
                    break
                except (ProviderError, TimeoutError) as error:
                    log.info("Could not read prepared questions from %s (attempt %d): %s", filename, attempt, error)
            else:
                return []
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(questions, ensure_ascii=False))
        except OSError as error:
            log.info("Could not cache prepared questions: %s", error)
        return questions

    def _add_questions(self, questions: list[dict[str, str]]) -> bool:
        added = False
        for question in questions:
            key = coach.question_key(question["question"])
            if key not in self._bank_keys:
                self._bank_keys.add(key)
                self._bank.append(question)
                added = True
        return added

    async def _append_parts(self, tasks: list[asyncio.Task]) -> None:
        for task in tasks:  # in document order
            if self._add_questions(await task) and not self.ended:
                self._emit_plan()

    @property
    def _prepared_answer(self) -> str | None:
        if self._bank and self._bank_index < len(self._bank):
            return self._bank[self._bank_index]["prepared_answer"] or None
        return None

    def _emit_plan(self) -> None:
        """Send the question list, the mode and progress to the practice sidebar."""
        if self._bank is None:
            return
        current = self._bank_index if self._bank_index in self._asked else None
        self.emit("practice.plan", {
            "mode": self._practice_mode, "current": current, "asked": sorted(self._asked),
            "questions": [{"index": i, "topic": q["topic"], "question": q["question"]} for i, q in enumerate(self._bank)],
        })

    def _pick_next(self) -> int | None:
        """The next prepared question for the current mode, or None (improvised or finished)."""
        remaining = [i for i in range(len(self._bank or [])) if i not in self._asked]
        if self._practice_mode == "ai" or not remaining:
            return None
        return random.choice(remaining) if self._practice_mode == "random" else remaining[0]

    def _mark_asked(self, index: int) -> None:
        self._bank_index, self._follow_up_next = index, True
        self._asked.add(index)
        self._emit_plan()

    def _next_turn(self) -> str:
        """Instructions for the interviewer's next spoken turn, advancing the plan."""
        language = coach.spoken_language(self.config.get("language"))
        if self._follow_up_next and self._bank and self._bank_index < len(self._bank):
            self._follow_up_next = False
            return coach.next_turn_instructions(self._bank, self._bank_index, follow_up=True, language=language)
        index = self._pick_next()
        if index is not None:
            self._mark_asked(index)
            return coach.next_turn_instructions(self._bank, index, follow_up=False, language=language)
        if self._practice_mode == "ai" or not self._bank:
            self._emit_plan()
            asked = [q["text"] for q in self.questions][-20:]
            return coach.improvised_turn(language, asked)
        return coach.next_turn_instructions(self._bank, len(self._bank), follow_up=False, language=language)

    def practice_control(self, action: str, value: Any) -> None:
        """Sidebar commands: jump to a prepared question or change the mode."""
        if action == "practice.mode" and value in ("sequential", "random", "ai"):
            self._practice_mode = value
            self._emit_plan()
        elif action == "practice.goto" and isinstance(value, int) and self._bank and 0 <= value < len(self._bank):
            self._cancel_reply()
            self._mark_asked(value)
            language = coach.spoken_language(self.config.get("language"))
            instructions = coach.jump_to_question(self._bank[value]["question"], language)
            if isinstance(self._live, RealtimeVoiceAgent):
                self._spawn(self._live.respond(instructions))
            elif self._live is None:
                self._say_text(self._bank[value]["question"], planned=True)

    async def _start_live(self) -> None:
        """Start the spoken interviewer; fall back to the text interviewer if voice is unavailable."""
        mode = self.settings.practice_voice
        if mode not in ("realtime", "live"):
            self._ask_soon(0)
            return
        if self._sources is None:
            self._sources = asyncio.get_running_loop().create_task(self._load_sources())
        self._plan_task = self._spawn(self._practice_plan())
        # The Realtime interviewer does not wait for question extraction (seconds on first use):
        # it greets and asks for a short self-introduction, then continues with the plan.
        await asyncio.wait({self._plan_task}, timeout=None if mode == "live" else PLAN_WAIT_S)
        if self.ended or not self.connected:
            return
        ready = self._plan_task.done() and not self._plan_task.cancelled()
        bank, resume = self._plan_task.result() if ready else ([], next((s.text for s in await self._sources if s.kind == "resume"), ""))
        language = coach.spoken_language(self.config.get("language"))
        goal = self.config["goal"]
        topics = [{"title": q["topic"] or q["question"][:60], "focus": q["question"]} for q in bank]
        instructions = coach.live_instructions(goal, topics, resume, language, self.config.get("persona"))
        greeting = coach.live_greeting(goal, topics, language)
        first = self._pick_next() if ready else None
        if first is not None:
            greeting += coach.first_question_line(bank[first]["question"])
        elif not ready:
            greeting = coach.introduction_greeting(goal, language)

            def plan_ready(_task: asyncio.Task) -> None:
                # The greeting already asked for a self-introduction: do not ask it again.
                self._asked.update(i for i, q in enumerate(self._bank or []) if SELF_INTRODUCTION.search(q["question"]))
                self._emit_plan()

            self._plan_task.add_done_callback(plan_ready)
        on_audio = lambda audio: self.emit("say.audio", {"audio": audio})  # noqa: E731
        if mode == "realtime":
            live = RealtimeVoiceAgent(
                self.openai, self.key, model=self.settings.models.realtime_voice_agent, voice=self.settings.models.live_voice,
                transcription_model=self.settings.models.transcription, instructions=instructions, greeting=greeting,
                limits=self.settings.limits, barge_in=self.settings.practice_barge_in, on_audio=on_audio,
                on_audio_cleared=lambda: self.emit("say.audio.clear", {}),
                on_interviewer_text=self._live_interviewer_text,
                on_interviewer_done=lambda _text: self._finish_live_say(),
                on_candidate_done=self._realtime_candidate_done, on_closed=self._live_closed,
                on_candidate_started=self._cancel_reply)
        else:
            live = LiveConversation(
                self.openai, self.key, model=self.settings.models.live, voice=self.settings.models.live_voice,
                instructions=instructions, greeting=greeting, limits=self.settings.limits, on_audio=on_audio,
                on_interviewer_text=self._live_interviewer_text, on_candidate_text=self._live_candidate_text,
                on_closed=self._live_closed)
        self._live = live
        try:
            await live.start()
        except ProviderError as error:
            log.warning("GPT-Live unavailable, using the text interviewer: %s", error)
            if self._live is live:
                self._live = None
            if self.connected and not self.ended:
                self.emit("transcription.state", {"state": "degraded", "stream_id": "live", "message": str(error)})
                self._ask_soon(0)
            return
        self._mock_started = True
        self.config["practice_topics"] = topics
        # Marked only now: if voice failed, the text interviewer asks this question instead.
        if first is not None:
            self._mark_asked(first)
        elif ready:  # otherwise the plan is sent when extraction finishes
            self._emit_plan()

    def _live_closed(self, reason: str | None) -> None:
        if reason and self.connected and not self.ended:
            self.emit("transcription.state", {"state": "degraded", "stream_id": "live", "message": reason})

    def _close_live(self) -> None:
        live, self._live = self._live, None
        if self._live_timer:
            self._live_timer.cancel()
        self._finish_live_say()
        self._finish_live_answer()
        if live:
            asyncio.get_running_loop().create_task(live.close())

    def _arm_live_timer(self, delay: float, callback) -> None:
        if self._live_timer:
            self._live_timer.cancel()
        self._live_timer = asyncio.get_running_loop().call_later(delay, callback)

    def _live_interviewer_text(self, delta: str) -> None:
        self._finish_live_answer()
        if self._live_say is None:
            self._live_say = {"say_id": str(uuid.uuid4()), "text": ""}
        self._live_say["text"] += delta
        # Live caption while the interviewer is talking.
        self.emit("transcript", {"segment_id": self._live_say["say_id"], "role": "interviewer",
                                 "text": self._live_say["text"].strip(), "final": False, "source": "live"})
        if self.settings.practice_voice != "realtime":
            # GPT-Live has no end-of-turn event; a pause in its transcript ends the turn.
            # The Realtime API reports the end explicitly (output_audio_transcript.done).
            self._arm_live_timer(self.settings.limits.live_say_gap_s, self._finish_live_say)

    def _finish_live_say(self) -> None:
        say, self._live_say = self._live_say, None
        if not say or not say["text"].strip() or self.ended:
            return
        text = say["text"].strip()
        self.emit("transcript.dropped", {"role": "interviewer"})  # clears the live caption
        seq = self.emit("say", {"say_id": say["say_id"], "text": text})
        self.segments.append(Segment(seq, "interviewer", text, say["say_id"]))
        self._spawn(self._understand_say(say["say_id"], text, seq))

    def _live_candidate_text(self, delta: str) -> None:
        self._finish_live_say()
        if self._live_answer is None:
            self._live_answer = {"segment_id": str(uuid.uuid4()), "text": ""}
        self._live_answer["text"] += delta
        self._arm_live_timer(self.settings.limits.live_candidate_gap_s, self._finish_live_answer)

    def _realtime_candidate_done(self, text: str) -> None:
        """The Realtime API reports each finished candidate turn in one piece; the plan picks the reply."""
        if not (isinstance(self._live, RealtimeVoiceAgent) and self._live.interviewer_speaking):
            # Never cut the interviewer's line in two because a noise or the candidate overlapped it;
            # its own end-of-turn event finishes it.
            self._finish_live_say()
        self._live_answer = {"segment_id": str(uuid.uuid4()), "text": text}
        self._finish_live_answer()
        if is_filler(text) or not isinstance(self._live, RealtimeVoiceAgent):
            return
        # Voice activity detection ends a turn at every short pause; reply only
        # after the candidate has been quiet for a while (speaking again cancels).
        self._cancel_reply()
        self._reply_timer = asyncio.get_running_loop().call_later(self.settings.limits.practice_reply_pause_s, self._reply)

    def _cancel_reply(self) -> None:
        if self._reply_timer:
            self._reply_timer.cancel()
            self._reply_timer = None

    def _reply(self) -> None:
        self._reply_timer = None
        if self.ended or not isinstance(self._live, RealtimeVoiceAgent):
            return

        async def reply() -> None:
            if self._plan_task and not self._plan_task.done():
                await asyncio.wait({self._plan_task})  # the plan is still being extracted
            if isinstance(self._live, RealtimeVoiceAgent) and not self.ended:
                await self._live.respond(self._next_turn())

        self._spawn(reply())

    def _finish_live_answer(self) -> None:
        answer, self._live_answer = self._live_answer, None
        if not answer or not answer["text"].strip() or self.ended or is_filler(answer["text"]):
            return
        text = answer["text"].strip()
        seq = self.emit("transcript", {"segment_id": answer["segment_id"], "role": "interviewee", "text": text,
                                       "final": True, "source": "mic"})
        self.segments.append(Segment(seq, "interviewee", text, answer["segment_id"]))

    async def _understand_say(self, say_id: str, text: str, seq: int) -> None:
        """Translate the interviewer's turn and, if it asks something, start a hint right away."""
        recent = coach.recent_transcript([s.as_dict() for s in self.segments[:-1]], count=8)
        try:
            result = await understanding.analyze(
                self.openai, self.settings.models.understanding, latest=text, pending=text, recent=recent,
                goal=self.config["goal"], timeout=self.settings.limits.understanding_timeout_s)
        except (ProviderError, ValueError, TimeoutError) as error:
            log.info("Interviewer understanding failed, using the heuristic: %s", error)
            result = understanding.heuristic(text)
        if useful_translation(result.translation, text):
            self.emit("transcript.translation", {"segment_id": say_id, "text": result.translation, "language": result.language,
                                                 "target_language": "en" if result.language == "zh" else "zh"})
        else:
            # The combined call sometimes echoes the original; a dedicated call translates reliably.
            self._spawn(self._translate_say(say_id, text))
        if result.is_question and not self.ended:
            question = result.question or text
            self.questions.append({"seq": seq, "text": question})
            self.answer(question, seq)

    async def _translate_say(self, say_id: str, text: str) -> None:
        try:
            translation = await understanding.translate(self.openai, self.settings.models.understanding, text,
                                                        timeout=self.settings.limits.understanding_timeout_s)
        except Exception as error:
            log.info("Could not translate the interviewer's question: %s", error)
            return
        if not useful_translation(translation, text):
            return
        self.emit("transcript.translation", {"segment_id": say_id, "text": translation, "language": "", "target_language": ""})

    # ── lifecycle ───────────────────────────────────────────────────────────

    def _spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def finish(self) -> None:
        """End the interview: tell the client, transcribe buffered audio, stop all work."""
        if self.ended:
            return
        self.ended = True
        self.emit("session.ended", {"reason": "completed"})
        outbox = self._outbox
        self.detach()
        if outbox is not None:
            outbox.put_nowait("")  # tells the connection writer to close
        if self._draining:
            await asyncio.gather(*list(self._draining), return_exceptions=True)
        for task in list(self._tasks):
            task.cancel()

    def stop_now(self) -> None:
        """Sign-out: drop everything immediately."""
        self.ended = True
        outbox = self._outbox
        self.detach()
        if outbox is not None:
            outbox.put_nowait("")
        for task in list(self._tasks) + list(self._draining):
            task.cancel()

    async def debrief(self, created_at: str | None, ended_at: str | None, duration_seconds: int | None) -> dict | None:
        data = coach.debrief_input([s.as_dict() for s in self.segments], self.questions, self.config, created_at, ended_at,
                                   duration_seconds)
        if not data:
            return None
        text = await self.openai.respond(coach.debrief_request(self.settings.models.coaching, data),
                                         timeout=300, key=self.key)
        return coach.finish_report(text, data)
