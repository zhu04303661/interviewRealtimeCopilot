"""Spoken practice with the speech-to-speech Realtime interviewer (the default practice mode)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from frlocal.config import Limits

from .test_practice_live import practice, silence_for, speak_for


@pytest.fixture
def limits() -> Limits:
    return replace(Limits(), live_silence_interval_s=0.05, live_echo_margin_s=0.2)


async def test_session_is_configured_for_speech_to_speech_with_prepared_topics(signed_in, fake_openai, tmp_path):
    _, client = await practice(signed_in, tmp_path)
    await client.wait_type("say")
    session = fake_openai.realtime_of("session.update")[0]["session"]
    assert session["type"] == "realtime" and session["model"] == "gpt-realtime-2.1"
    assert session["output_modalities"] == ["audio"]
    audio = session["audio"]
    assert audio["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert audio["input"]["turn_detection"] == {"type": "semantic_vad", "eagerness": "low", "create_response": False,
                                                    "interrupt_response": False}
    assert audio["input"]["transcription"] == {"model": "gpt-live-transcribe"}
    assert audio["output"] == {"format": {"type": "audio/pcm", "rate": 24000}, "voice": "marin"}
    assert "1. PDSCH scheduling" in session["instructions"] and "Tuned the LTE PDSCH scheduler" in session["instructions"]
    greeting = fake_openai.realtime_of("response.create")[0]["response"]["instructions"]
    assert "first question about: PDSCH scheduling" in greeting
    await client.close()


async def test_interviewer_turn_is_spoken_captioned_translated_and_hinted(signed_in, fake_openai, tmp_path):
    _, client = await practice(signed_in, tmp_path)
    await client.wait_type("say.audio")
    caption = await client.wait_for(lambda f: f["type"] == "transcript" and f["data"]["source"] == "live")
    assert caption["data"]["role"] == "interviewer" and not caption["data"]["final"]
    say = await client.wait_type("say")
    assert say["data"]["text"] == "Hi, I'm your interviewer. Tell me how you tuned PDSCH scheduling?"
    assert (await client.wait_type("transcript.translation"))["data"]["segment_id"] == say["data"]["say_id"]
    started = await client.wait_type("turn.started")
    assert started["data"]["gate_seq"] == say["seq"]
    await client.wait_type("turn.done")
    assert len(client.of("say")) == 1  # the done event ends the turn; no duplicate from the gap timer
    await client.close()


async def test_candidate_answer_then_follow_up_question(signed_in, fake_openai, tmp_path):
    _, client = await practice(signed_in, tmp_path)
    first = await client.wait_type("say")
    await asyncio.sleep(0.5)
    await speak_for(client, 0.5)
    answer = await client.wait_for(lambda f: f["type"] == "transcript" and f["data"]["role"] == "interviewee" and f["data"]["final"])
    assert answer["data"]["text"].startswith("I tuned the proportional fair scheduler")
    follow_up = await client.wait_for(lambda f: f["type"] == "say" and f["seq"] > first["seq"], timeout=6)
    assert follow_up["data"]["text"] == "Thanks. How did you budget HARQ timing?"
    await client.wait_for(lambda f: f["type"] == "turn.started" and f["data"].get("gate_seq") == follow_up["seq"])
    await client.close()


async def test_echo_gate_silences_the_microphone_while_the_interviewer_plays(signed_in, fake_openai, tmp_path):
    fake_openai.live_audio_chunks = 40  # 4 s of interviewer audio
    _, client = await practice(signed_in, tmp_path, documents=False)
    await client.wait_type("say.audio")
    await speak_for(client, 1.0)
    assert fake_openai.live_audio_nonzero == 0 and fake_openai.live_audio_zero > 0
    assert fake_openai.realtime_of("conversation.item.truncate") == []
    await client.close()


class TestBargeIn:
    @pytest.fixture
    def barge_in(self) -> bool:
        return True

    async def test_interrupting_stops_playback_and_truncates_the_unheard_part(self, signed_in, fake_openai, tmp_path):
        fake_openai.live_audio_chunks = 40
        _, client = await practice(signed_in, tmp_path, documents=False)
        await client.wait_type("say.audio")
        await speak_for(client, 0.3)
        await client.wait_type("say.audio.clear")
        truncate = fake_openai.realtime_of("conversation.item.truncate")[0]
        assert truncate["item_id"] == "item_assistant_1" and truncate["content_index"] == 0
        assert 0 <= truncate["audio_end_ms"] < 4000
        assert fake_openai.live_audio_nonzero > 0
        await client.close()


async def test_silence_keeps_server_vad_fed(signed_in, fake_openai, tmp_path):
    _, client = await practice(signed_in, tmp_path, documents=False)
    await client.wait_type("say")
    before = fake_openai.live_audio_zero
    await asyncio.sleep(0.5)
    assert fake_openai.live_audio_zero - before >= 4 * 2400
    await client.close()


async def test_rejected_model_falls_back_to_the_text_interviewer(signed_in, fake_openai, tmp_path):
    fake_openai.live_reject = True
    _, client = await practice(signed_in, tmp_path, documents=False)
    degraded = await client.wait_type("transcription.state", stream_id="live")
    assert "no access" in degraded["data"]["message"]
    assert (await client.wait_type("say"))["data"]["text"] == "How did you tune PDSCH scheduling?"
    await client.close()


async def test_end_of_session_keeps_the_spoken_transcript(signed_in, fake_openai, tmp_path):
    session_id, client = await practice(signed_in, tmp_path, documents=False)
    await client.wait_type("say")
    await asyncio.sleep(0.5)
    await speak_for(client, 0.5)
    await client.wait_for(lambda f: f["type"] == "transcript" and f["data"]["role"] == "interviewee" and f["data"]["final"])
    await signed_in.call("POST", f"/api/v3/sessions/{session_id}/end")
    transcript = await signed_in.call("GET", f"/api/v3/sessions/{session_id}/transcript")
    assert [s["role"] for s in transcript["segments"]][:2] == ["interviewer", "interviewee"]
    topics = json.loads(fake_openai.bodies("topics")[0]["input"])
    assert topics["goal"]["company"] == "AccelerComm"


def test_hesitation_sounds_are_not_answers_and_echoed_translations_are_hidden():
    from frlocal.realtime.session import is_filler, useful_translation
    assert all(is_filler(t) for t in ("Uh,", "呃", "嗯。", "Hmm...", " um "))
    assert not is_filler("I will explain the scheduler.")
    assert not useful_translation("To start, tell me about it?", "To start, tell me about it?")
    assert not useful_translation("  ", "anything")
    assert useful_translation("首先，请谈谈它。", "To start, tell me about it?")


async def test_interviewer_waits_until_the_candidate_has_finished(signed_in, fake_openai, tmp_path):
    """Regression: a pause mid-answer used to trigger the next question immediately."""
    fake_openai.live_answers.extend(["and then we measured it on hardware."])
    _, client = await practice(signed_in, tmp_path, documents=False)
    first = await client.wait_type("say")
    before = len(fake_openai.realtime_of("response.create"))
    await asyncio.sleep(2.0)                # after the echo gate has reopened
    await speak_for(client, 0.5)            # first part of the answer
    await client.wait_for(lambda f: f["type"] == "transcript" and f["data"]["role"] == "interviewee" and f["data"]["final"])
    await silence_for(client, 1.0)          # a thinking pause, shorter than the reply pause
    assert len(fake_openai.realtime_of("response.create")) == before
    await speak_for(client, 0.5)            # the answer continues
    await silence_for(client, 1.0)
    assert len(fake_openai.realtime_of("response.create")) == before
    await client.wait_for(lambda f: f["type"] == "say" and f["seq"] > first["seq"], timeout=8)
    assert len(fake_openai.realtime_of("response.create")) == before + 1
    await client.close()


async def test_practice_sidebar_lists_questions_tracks_progress_and_jumps(signed_in, fake_openai, tmp_path):
    fake_openai.live_turns.extend(["Let's move on. How did you budget HARQ timing?"])
    _, client = await practice(signed_in, tmp_path, documents=False)
    plan = await client.wait_type("practice.plan")
    assert [q["question"] for q in plan["data"]["questions"]] == ["How did you tune PDSCH scheduling?", "How did you budget HARQ timing?"]
    assert plan["data"]["mode"] == "sequential" and plan["data"]["current"] == 0 and plan["data"]["asked"] == [0]
    await client.wait_type("say")
    await client.send("answer_request", utterance="", intent="practice.goto", gate_seq=1)
    jumped = await client.wait_for(lambda f: f["type"] == "practice.plan" and f["data"]["current"] == 1)
    assert jumped["data"]["asked"] == [0, 1]
    await client.wait_for(lambda f: f["type"] == "say" and "HARQ" in f["data"]["text"], timeout=5)
    assert "How did you budget HARQ timing?" in fake_openai.realtime_of("response.create")[-1]["response"]["instructions"]
    await client.close()


def test_practice_modes_pick_unasked_questions_or_improvise_without_repeats():
    from frlocal.realtime.session import InterviewSession
    session = InterviewSession.__new__(InterviewSession)
    session.config, session.questions, session.emit = {"language": "en-US"}, [{"text": "How did you tune PDSCH scheduling?"}], lambda *a: 0
    session._bank = [{"topic": t, "question": f"Q{t}?", "prepared_answer": ""} for t in "abcd"]
    session._asked, session._bank_index, session._follow_up_next = {0}, 0, False
    session._practice_mode = "sequential"
    assert session._pick_next() == 1
    session._practice_mode = "random"
    assert {session._pick_next() for _ in range(40)} == {1, 2, 3}
    session._practice_mode = "ai"
    turn = session._next_turn()
    assert "different point from every question already asked" in turn and "How did you tune PDSCH scheduling?" in turn
    session._practice_mode, session._asked = "sequential", {0, 1, 2, 3}
    assert "completes the practice questions" in session._next_turn()


def test_every_prepared_question_is_read_in_parts_without_a_cap():
    from frlocal.realtime import coach
    document = "\n\n".join(f"## Q{i}. How does feature {i} work?\nPrepared answer {i}. " + "detail " * 300 for i in range(60))
    parts = coach.question_chunks(document, size=24_000)
    assert len(parts) > 3 and len(parts[0]) <= 6_000 and all(len(p) <= 24_000 for p in parts)
    assert "".join(parts).count("How does feature") == 60          # nothing dropped at part boundaries
    many = json.dumps({"questions": [{"topic": "t", "question": f"Question {i}?", "prepared_answer": "a"} for i in range(40)]})
    assert len(coach.parse_question_bank(many)) == 40               # no 15-question cap


async def test_question_parts_are_appended_in_order_and_cached(signed_in, fake_openai, tmp_path):
    long_prep = "\n\n".join(f"## Q{i}. Question {i}?\n" + "answer " * 4000 for i in range(3))  # three parts
    calls = []

    def bank(body):
        text = json.loads(body["input"])["document"]["text"]
        calls.append(text[:12])
        return {"questions": [{"topic": "t", "question": q, "prepared_answer": "a"}
                              for q in (f"Question {i}?" for i in range(3)) if q in text]}

    fake_openai.handlers["topics"] = bank
    _, client = await practice(signed_in, tmp_path, documents=False, material=long_prep)
    full = await client.wait_for(lambda f: f["type"] == "practice.plan" and len(f["data"]["questions"]) == 3, timeout=10)
    assert [q["question"] for q in full["data"]["questions"]] == ["Question 0?", "Question 1?", "Question 2?"]
    await client.close()
    first_calls = len(calls)
    _, client = await practice(signed_in, tmp_path, documents=False, material=long_prep)
    await client.wait_for(lambda f: f["type"] == "practice.plan" and len(f["data"]["questions"]) == 3, timeout=10)
    assert len(calls) == first_calls                                   # second session reads the disk cache
    await client.close()


def test_parallel_chinese_titles_are_not_spoken():
    from frlocal.realtime.coach import spoken_question
    assert spoken_question("Dealing with an under-performer / 如何处理绩效差的工程师") == "Dealing with an under-performer"
    assert spoken_question("请介绍一下你自己 / Tell me about yourself") == "请介绍一下你自己 / Tell me about yourself"
    assert spoken_question("TDD / FDD trade-offs?") == "TDD / FDD trade-offs?"


def test_translations_must_be_in_the_other_language():
    from frlocal.realtime.session import useful_translation
    question = "How did CFO estimation work, and what are its limits?"
    assert not useful_translation("CFO estimation worked how, and what were its limits?", question)  # reworded English
    assert useful_translation("CFO 估计是如何工作的？它有哪些局限？", question)
    assert useful_translation("How does the scheduler work?", "调度器是如何工作的？")
    assert not useful_translation("调度器怎么工作？", "调度器是如何工作的？")


async def test_slow_question_extraction_does_not_delay_the_greeting(signed_in, fake_openai, tmp_path):
    fake_openai.topics_delay = 4.0  # first-time extraction of a large document
    _, client = await practice(signed_in, tmp_path, documents=False)
    await client.wait_type("say", timeout=4)  # greeted before the plan exists
    greeting = fake_openai.realtime_of("response.create")[0]["response"]["instructions"]
    assert "introduce themselves" in greeting
    plan = await client.wait_for(lambda f: f["type"] == "practice.plan" and f["data"]["questions"], timeout=6)
    assert all(f["data"]["questions"] for f in client.of("practice.plan"))  # no empty plan first
    assert plan["data"]["asked"] == [] and len(plan["data"]["questions"]) == 2
    await asyncio.sleep(0.5)
    await speak_for(client, 0.5)  # the self-introduction
    await client.wait_for(lambda f: f["type"] == "practice.plan" and f["data"]["current"] == 0, timeout=8)
    assert "How did you tune PDSCH scheduling?" in fake_openai.realtime_of("response.create")[-1]["response"]["instructions"]
    await client.close()


def test_self_introduction_pattern():
    from frlocal.realtime.session import SELF_INTRODUCTION
    assert all(SELF_INTRODUCTION.search(q) for q in ("Tell me about yourself.", "Could you introduce yourself?", "请做一下自我介绍",
                                                      "Can you walk me through your one-line career story?"))
    assert not SELF_INTRODUCTION.search("Why do you want to work at AccelerComm?")


async def test_preflight_chooses_the_starting_practice_mode(signed_in, fake_openai):
    from .conftest import connect, start_interview
    session_id, ws_url = await start_interview(signed_in, topology="mock", config={"language": "en-US", "practice_mode": "ai"})
    client = await connect(signed_in, session_id, ws_url, topology="mock")
    plan = await client.wait_type("practice.plan", timeout=8)
    assert plan["data"]["mode"] == "ai"
    await client.close()


def test_candidate_turn_does_not_split_the_interviewers_line():
    """Regression: a candidate turn while the interviewer was still speaking cut the spoken line in two."""
    from frlocal.realtime import session as session_module
    from frlocal.realtime.voice_agent import RealtimeVoiceAgent

    finished = []
    agent = RealtimeVoiceAgent.__new__(RealtimeVoiceAgent)
    interview = session_module.InterviewSession.__new__(session_module.InterviewSession)
    interview._live, interview._live_answer = agent, None
    interview._finish_live_say = lambda: finished.append("say")
    interview._finish_live_answer = lambda: None
    interview._cancel_reply = lambda: None
    for speaking, expected in ((True, []), (False, ["say"])):
        finished.clear()
        type(agent).interviewer_speaking = property(lambda self, value=speaking: value)
        try:
            interview._realtime_candidate_done("Uh")  # a filler, so no reply is scheduled
        finally:
            del type(agent).interviewer_speaking
        assert finished == expected
