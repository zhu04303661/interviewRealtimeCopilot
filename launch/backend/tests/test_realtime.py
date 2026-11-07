"""The live interview engine, end to end over its WebSocket with a fake OpenAI."""

from __future__ import annotations

import asyncio
import itertools
import json

import aiohttp

from .conftest import LiveClient, connect, start_interview
from .fakes import understanding

CANDIDATE, INTERVIEWER = 0, 1


async def interview(b, **kwargs) -> tuple[str, LiveClient]:
    session_id, ws_url = await start_interview(b, **kwargs)
    client = await connect(b, session_id, ws_url, topology=kwargs.get("topology", "general"))
    await client.wait_type("session.state")
    return session_id, client


# ── connection and authorisation ─────────────────────────────────────────────


async def test_hello_requires_the_session_token_and_matching_streams(signed_in):
    session_id, ws_url = await start_interview(signed_in)
    bad = await connect(signed_in, session_id, ws_url, jwt="wrong")
    await bad._reader
    assert bad.socket.close_code == 4401
    socket = await signed_in.session.ws_connect(ws_url)
    await socket.send_str(json.dumps({"v": 1, "type": "hello", "jwt": signed_in.session_token, "session_id": session_id,
                                      "streams": [{"role": "interviewer", "encoding": "pcm16", "sample_rate": 16000}]}))
    message = await socket.receive()
    assert message.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED) and socket.close_code == 4401
    good = await connect(signed_in, session_id, ws_url)
    state = await good.wait_type("session.state")
    assert state["data"]["config"]["goal"] == {"company": "Example", "role": "Software Engineer"}
    assert state["data"]["config"]["interviewer_source"] == "external_audio"
    await good.close()


async def test_signing_out_ends_live_interviews(signed_in):
    _, client = await interview(signed_in)
    await signed_in.call("POST", "/local/auth/sign-out", json={})
    await asyncio.wait_for(client._reader, 5)
    assert signed_in.engine.sessions == {}


# ── speakers, translation and question extraction ───────────────────────────


async def test_interviewer_question_is_translated_extracted_and_answered_with_materials(signed_in, fake_openai, tmp_path):
    b = signed_in
    (tmp_path / "cv.txt").write_text("Jane Doe. Led the payments migration that cut latency by 40%.")
    resume = await b.documents.import_file("admin", "resume", str(tmp_path / "cv.txt"), "cv.txt", "text/plain")
    await b.documents.wait_idle()
    fake_openai.script_transcripts("Tell me about your migration project?")
    fake_openai.handlers["understanding"] = lambda body: understanding(
        "Tell me about your migration project?", translation="跟我讲讲你的迁移项目？", question_translation="请介绍你的迁移项目。")
    _, client = await interview(b, config={"language": "en-US", "document_ids": [resume["document_id"]]},
                                goal={"role": "Engineer", "company": "Example", "job_description": "Own LTE L1 and 5G NR."})
    await client.speak(INTERVIEWER)

    interim = await client.wait_for(lambda f: f["type"] == "transcript" and not f["data"]["final"])
    assert interim["data"]["role"] == "interviewer" and interim["data"]["source"] == "system"
    final = await client.wait_type("transcript", final=True)
    translation = await client.wait_type("transcript.translation")
    assert translation["data"] == {"segment_id": final["data"]["segment_id"], "text": "跟我讲讲你的迁移项目？",
                                   "language": "en", "target_language": "zh"}
    verdict = await client.wait_type("gate.verdict")
    assert verdict["data"]["decision"] == "respond"
    assert verdict["data"]["utterance"] == "Tell me about your migration project?"
    assert verdict["data"]["translation"] == "请介绍你的迁移项目。"
    started = await client.wait_type("turn.started")
    assert started["data"]["gate_seq"] == verdict["seq"]
    done = await client.wait_type("turn.done")
    tokens = [f["data"]["delta"] for f in client.of("turn.token")]
    assert "".join(tokens) == "".join(fake_openai.answer_chunks) and len(tokens) == 3
    assert done["data"]["rag"]["outcome"] == "none"  # a short resume is sent whole, not as matched passages

    answer_body = fake_openai.bodies("answer")[0]
    assert "**EN**" in answer_body["instructions"] and "**中文**" in answer_body["instructions"]
    payload = json.loads(answer_body["input"])
    assert payload["question"] == "Tell me about your migration project?"
    assert payload["goal"]["job_description"] == "Own LTE L1 and 5G NR."
    assert payload["documents"][0]["text"].startswith("Jane Doe")
    assert payload["recent_transcript"][-1] == {"speaker": "interviewer", "text": "Tell me about your migration project?"}
    assert answer_body["stream"] is True and answer_body["store"] is False
    await client.close()


async def test_candidate_speech_is_labelled_and_not_translated(signed_in, fake_openai):
    fake_openai.script_transcripts("I worked on the payments team.")
    _, client = await interview(signed_in)
    await client.speak(CANDIDATE)
    final = await client.wait_type("transcript", final=True)
    assert final["data"]["role"] == "interviewee" and final["data"]["source"] == "mic"
    await asyncio.sleep(0.2)
    assert fake_openai.bodies("understanding") == [] and client.of("transcript.translation") == []
    await client.close()


async def test_split_question_waits_then_answers_the_whole_question(signed_in, fake_openai):
    fake_openai.script_transcripts("So the next thing I want to ask is", "how would you scale this to a million users?")
    answers = iter([
        understanding("So the next thing I want to ask is", complete=False),
        understanding("How would you scale this to a million users?", intent="system_design"),
    ])
    fake_openai.handlers["understanding"] = lambda body: next(answers)
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    first = await client.wait_type("gate.verdict", decision="await_more")
    assert client.of("turn.started") == []
    await client.speak(INTERVIEWER)
    second = await client.wait_type("gate.verdict", decision="respond")
    assert second["data"]["intent"] == "system_design" and second["seq"] > first["seq"]
    pending = json.loads(fake_openai.bodies("understanding")[1]["input"])["pending_interviewer_speech"]
    assert pending == "So the next thing I want to ask is how would you scale this to a million users?"
    await client.wait_type("turn.done")
    await client.close()


async def test_small_talk_is_ignored(signed_in, fake_openai):
    fake_openai.script_transcripts("Great, thanks for joining today.")
    fake_openai.handlers["understanding"] = lambda body: understanding("", translation="好的，感谢你今天参加。")
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    verdict = await client.wait_type("gate.verdict")
    assert verdict["data"]["decision"] == "ignore"
    assert (await client.wait_type("transcript.translation"))["data"]["text"] == "好的，感谢你今天参加。"
    await asyncio.sleep(0.2)
    assert client.of("turn.started") == []
    await client.close()


async def test_model_failure_falls_back_to_the_heuristic(signed_in, fake_openai):
    fake_openai.fail_purposes["understanding"] = 1
    fake_openai.script_transcripts("Why do you want this job?")
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    verdict = await client.wait_type("gate.verdict")
    assert verdict["data"]["decision"] == "respond" and verdict["data"]["utterance"] == "Why do you want this job?"
    await client.wait_type("turn.done")
    assert client.of("transcript.translation") == []
    await client.close()


async def test_newer_question_supersedes_an_unfinished_answer(signed_in, fake_openai):
    fake_openai.answer_token_gap = 0.4
    fake_openai.script_transcripts("What is your biggest strength?", "Actually, tell me about a failure instead?")
    questions = iter([understanding("What is your biggest strength?"), understanding("Tell me about a failure.")])
    fake_openai.handlers["understanding"] = lambda body: next(questions)
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    first = await client.wait_type("turn.started")
    await client.wait_type("turn.token")
    await client.speak(INTERVIEWER)
    superseded = await client.wait_type("turn.superseded")
    assert superseded["data"]["turn_id"] == first["data"]["turn_id"]
    done = await client.wait_type("turn.done", timeout=8)
    assert done["data"]["turn_id"] != first["data"]["turn_id"]
    await client.close()


async def test_answer_request_from_the_app(signed_in, fake_openai):
    _, client = await interview(signed_in)
    await client.send("answer_request", utterance="Explain HARQ in LTE", gate_seq=7)
    started = await client.wait_type("turn.started")
    assert started["data"]["gate_seq"] == 7
    await client.wait_type("turn.done")
    assert json.loads(fake_openai.bodies("answer")[0]["input"])["question"] == "Explain HARQ in LTE"
    await client.close()


async def test_answer_failure_is_reported_on_the_turn(signed_in, fake_openai):
    fake_openai.fail_purposes["other"] = 0
    _, client = await interview(signed_in)
    original = fake_openai.answer_chunks
    fake_openai.answer_chunks = []
    await client.send("answer_request", utterance="Explain HARQ")
    error = await client.wait_type("error", code="turn_failed")
    assert error["data"]["turn_id"] == (await client.wait_type("turn.started"))["data"]["turn_id"]
    fake_openai.answer_chunks = original
    await client.close()


# ── transcription configuration ─────────────────────────────────────────────


async def test_transcription_is_configured_for_low_delay_bilingual_speech(signed_in, fake_openai):
    fake_openai.script_transcripts("hello")
    _, client = await interview(signed_in, goal={"role": "LTE L1 Engineer", "company": "AccelerComm",
                                                 "job_description": "Work on PDSCH, HARQ and 5G NR in C++."})
    await client.speak(CANDIDATE)
    await client.wait_type("transcript", final=True)
    config = fake_openai.transcription_connections[0].config
    assert config["model"] == "gpt-live-transcribe" and config["delay"] == "low"
    assert config["languages"][:2] == ["en", "zh"]
    assert "LTE L1 Engineer" in config["prompt"] and "AccelerComm" in config["prompt"]
    assert {"AccelerComm", "PDSCH", "HARQ", "5G"} <= set(config["keywords"])
    assert fake_openai.transcription_connections[0].audio_bytes == 3 * 3200 * 3 // 2  # resampled to 24 kHz
    await client.close()


async def test_rejected_hints_fall_back_to_the_minimal_configuration(signed_in, fake_openai):
    fake_openai.reject_hints_once = True
    fake_openai.script_transcripts("hello there")
    _, client = await interview(signed_in)
    await client.speak(CANDIDATE)
    final = await client.wait_type("transcript", final=True)
    assert final["data"]["text"] == "hello there"
    assert fake_openai.transcription_connections[0].config == {"model": "gpt-live-transcribe"}
    await client.close()


async def test_duplicate_audio_frames_are_ignored(signed_in, fake_openai):
    fake_openai.script_transcripts("one")
    _, client = await interview(signed_in)
    await client.speak(CANDIDATE, frames=2)
    client.sequence[CANDIDATE] = 0
    await client.speak(CANDIDATE, frames=2)  # replayed sequence numbers
    await client.wait_type("transcript", final=True)
    await asyncio.sleep(0.2)
    assert fake_openai.transcription_connections[0].audio_bytes == 2 * 3200 * 3 // 2
    await client.close()


# ── practice mode ───────────────────────────────────────────────────────────


async def test_without_a_voice_model_the_text_interviewer_asks_translates_and_follows_up(signed_in, fake_openai):
    fake_openai.live_reject = True  # the account has no access to the speech-to-speech model
    fake_openai.script_transcripts("My biggest project was a payments migration.")
    _, client = await interview(signed_in, topology="mock")
    say = await client.wait_type("say")
    assert say["data"]["text"] == "How did you tune PDSCH scheduling?"  # the first prepared question
    translation = await client.wait_type("transcript.translation")
    assert translation["data"]["segment_id"] == say["data"]["say_id"] and translation["data"]["text"] == "你最大的项目是什么？"
    await client.speak(CANDIDATE)
    await client.wait_type("transcript", final=True)
    await client.wait_for(lambda f: f["type"] == "say" and f["seq"] > say["seq"], timeout=5)
    assert fake_openai.bodies("interviewer") == []  # both turns are prepared questions, no invented ones
    await client.close()


# ── reconnect, end of session and Debrief ───────────────────────────────────


async def test_reconnect_replays_missed_frames(signed_in, fake_openai):
    fake_openai.script_transcripts("Why this company?")
    session_id, ws_url = await start_interview(signed_in)
    client = await connect(signed_in, session_id, ws_url)
    await client.wait_type("session.state")
    await client.speak(INTERVIEWER)
    done = await client.wait_type("turn.done")
    await client.close()
    again = await connect(signed_in, session_id, ws_url, last_seen_seq=2)
    await again.wait_type("session.state")
    replayed = await again.wait_for(lambda f: f["type"] == "turn.done" and f["seq"] == done["seq"])
    assert replayed["data"] == done["data"]
    assert all(f["seq"] > 2 for f in again.frames if f["type"] != "session.state")
    await again.close()


async def test_ending_saves_transcript_and_debrief(signed_in, fake_openai):
    fake_openai.script_transcripts("Tell me about a project?", "I migrated payments and cut latency by forty percent.")
    report = {
        "overall": {"headline": "Quantify more", "summary": "Good example.", "confidence": "medium"},
        "action_plan": [], "strengths": [], "improvements": [], "dimensions": [],
        "questions": [{"question_id": "QID", "quality": "on_track", "answer_summary": "Payments", "feedback": "Add scale.",
                       "evidence": ["cut latency by forty percent", "invented quote"], "stronger_version": "", "follow_up": ""}],
    }

    def debrief(body):
        question_id = json.loads(body["input"])["questions"][0]["id"]
        return json.loads(json.dumps(report).replace("QID", question_id))

    fake_openai.handlers["debrief"] = debrief
    session_id, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    await client.wait_type("turn.done")
    await client.speak(CANDIDATE)
    await client.wait_for(lambda f: f["type"] == "transcript" and f["data"]["final"] and f["data"]["role"] == "interviewee")
    await signed_in.call("POST", f"/api/v3/sessions/{session_id}/end")
    await client.wait_type("session.ended")
    for _ in range(50):
        saved = await signed_in.call("GET", f"/api/v3/sessions/{session_id}/report")
        if saved["status"] == "ready":
            break
        await asyncio.sleep(0.1)
    assert saved["status"] == "ready" and saved["question_count"] == 1
    assert saved["report"]["questions"][0]["evidence"] == ["cut latency by forty percent"]
    transcript = await signed_in.call("GET", f"/api/v3/sessions/{session_id}/transcript")
    assert [s["role"] for s in transcript["segments"]] == ["interviewer", "interviewee"]


async def test_screen_solve_is_published_as_an_answer(signed_in, fake_openai):
    session_id, client = await interview(signed_in)
    form = aiohttp.FormData()
    form.add_field("purpose", "solve")
    form.add_field("file", b"\x89PNG fake", filename="s.png", content_type="image/png")
    result = await signed_in.call("POST", f"/api/v3/sessions/{session_id}/screen", data=form)
    assert result["status"] == "ok" and result["solve"] == "solving"
    started = await client.wait_type("turn.started", source="screen")
    assert started["data"]["analysis_id"] == result["analysisId"]
    assert (await client.wait_type("turn.token"))["data"]["delta"] == "Use a hash map."
    await client.close()


# ── latency ──────────────────────────────────────────────────────────────────


async def test_answer_starts_within_one_round_trip_of_the_final_transcript(signed_in, fake_openai):
    """Pipeline overhead on top of model time stays small, and tokens stream as produced."""
    fake_openai.understanding_delay = 0.30
    fake_openai.answer_first_token_delay = 0.20
    fake_openai.answer_token_gap = 0.15
    fake_openai.script_transcripts("How do you handle on-call incidents?")
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    final = await client.wait_type("transcript", final=True)
    verdict = await client.wait_type("gate.verdict")
    first_token = await client.wait_type("turn.token")
    done = await client.wait_type("turn.done")
    to_verdict = verdict["received_at"] - final["received_at"]
    to_first_token = first_token["received_at"] - final["received_at"]
    assert to_verdict < 0.30 + 0.25, to_verdict
    assert to_first_token < 0.30 + 0.20 + 0.35, to_first_token
    tokens = client.of("turn.token")
    gaps = [later["received_at"] - earlier["received_at"] for earlier, later in itertools.pairwise(tokens)]
    assert all(gap > 0.1 for gap in gaps), gaps   # forwarded one by one, not buffered
    assert done["received_at"] - tokens[-1]["received_at"] < 0.2
    await client.close()


async def test_interim_text_is_forwarded_word_by_word(signed_in, fake_openai):
    fake_openai.script_transcripts("one two three four five")
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    await client.wait_type("transcript", final=True)
    interim = [f["data"]["text"] for f in client.of("transcript") if not f["data"]["final"]]
    assert interim == ["one", "one two", "one two three", "one two three four", "one two three four five"]
    await client.close()


async def test_candidate_speech_does_not_cancel_a_running_question_decision(signed_in, fake_openai):
    """Regression: a microphone line during analysis used to drop the verdict, so no hint appeared."""
    fake_openai.understanding_delay = 0.5
    fake_openai.script_transcripts("How did Fosso estimation work, and what are its limits?", "Let me think about that.")
    fake_openai.handlers["understanding"] = lambda body: understanding("How did Fosso estimation work, and what are its limits?")
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    await client.wait_type("transcript", final=True, role="interviewer")
    await client.speak(CANDIDATE)
    await client.wait_type("transcript", final=True, role="interviewee")
    verdict = await client.wait_type("gate.verdict")
    assert verdict["data"]["decision"] == "respond"
    await client.wait_type("turn.done")
    await client.close()


async def test_microphone_echo_of_the_interviewer_is_ignored(signed_in, fake_openai):
    fake_openai.script_transcripts("How did Fosso estimation work and what are its limits?",
                                   "How did both estimation work and what are its limits", "Uh,")
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    await client.wait_type("transcript", final=True, role="interviewer")
    await client.speak(CANDIDATE)
    await client.speak(CANDIDATE)
    await asyncio.sleep(0.5)
    assert [f for f in client.of("transcript") if f["data"]["role"] == "interviewee" and f["data"]["final"]] == []
    await client.close()


async def test_unfinished_question_is_answered_after_a_short_pause(signed_in, fake_openai, monkeypatch):
    from frlocal.realtime import session as session_module
    monkeypatch.setattr(session_module, "AUTO_ANSWER_WAIT_S", 0.3)
    fake_openai.script_transcripts("And how would you scale the scheduler")
    fake_openai.handlers["understanding"] = lambda body: understanding("How would you scale the scheduler?", complete=False)
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    verdict = await client.wait_type("gate.verdict", decision="await_more")
    started = await client.wait_type("turn.started", timeout=3)
    assert started["data"]["gate_seq"] == verdict["seq"]
    await client.close()


async def test_obvious_question_missed_by_the_model_is_still_answered(signed_in, fake_openai):
    fake_openai.script_transcripts("How did Fosso estimation work, and what are its limits?")
    fake_openai.handlers["understanding"] = lambda body: understanding("")  # model says "not a question"
    _, client = await interview(signed_in)
    await client.speak(INTERVIEWER)
    await client.wait_type("gate.verdict", decision="respond")
    await client.wait_type("turn.done")
    answer = fake_openai.bodies("answer")[0]
    assert "under one minute" in answer["instructions"] and answer["max_output_tokens"] == 700
    await client.close()
