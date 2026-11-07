"""Spoken practice with the full-duplex GPT-Live interviewer (FRLOCAL_PRACTICE_VOICE=live)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from frlocal.config import Limits

from .conftest import LiveClient, audio_frame, connect, start_interview

CANDIDATE = 0


@pytest.fixture
def practice_voice() -> str:
    return "live"


@pytest.fixture
def limits() -> Limits:
    return replace(Limits(), live_say_gap_s=0.25, live_candidate_gap_s=0.25, live_silence_interval_s=0.05, live_echo_margin_s=0.2)


async def practice(b, tmp_path, *, documents: bool = True) -> tuple[str, LiveClient]:
    ids = []
    if documents:
        (tmp_path / "cv.txt").write_text("Jane Doe. Tuned the LTE PDSCH scheduler, cutting latency by 30%.")
        (tmp_path / "prep.md").write_text("# Prepared topics\n1. PDSCH scheduling\n2. HARQ timing\n")
        ids = [(await b.documents.import_file("admin", kind, str(tmp_path / name), name, None))["document_id"]
               for kind, name in (("resume", "cv.txt"), ("material", "prep.md"))]
        await b.documents.wait_idle()
    session_id, ws_url = await start_interview(b, topology="mock", config={"language": "en-US", "document_ids": ids},
                                               goal={"role": "LTE L1 Engineer", "company": "AccelerComm", "job_description": "Own PDSCH and HARQ."})
    client = await connect(b, session_id, ws_url, topology="mock")
    await client.wait_type("session.state")
    return session_id, client


async def speak_for(client: LiveClient, seconds: float) -> None:
    """Stream microphone audio in real time (100 ms frames)."""
    for _ in range(round(seconds / 0.1)):
        await client.socket.send_bytes(audio_frame(CANDIDATE, client.sequence[CANDIDATE]))
        client.sequence[CANDIDATE] += 1
        await asyncio.sleep(0.1)


async def silence_for(client: LiveClient, seconds: float) -> None:
    """Stream silent microphone frames, as the app does while the candidate pauses."""
    for _ in range(round(seconds / 0.1)):
        await client.socket.send_bytes(audio_frame(CANDIDATE, client.sequence[CANDIDATE], value=0))
        client.sequence[CANDIDATE] += 1
        await asyncio.sleep(0.1)


async def test_session_starts_with_topics_from_the_materials(signed_in, fake_openai, tmp_path):
    _, client = await practice(signed_in, tmp_path)
    await client.wait_type("say")
    start = fake_openai.live_of("session.start")[0]["session"]
    assert start["model"] == "gpt-live-1" and start["audio"] == {"format": {"type": "audio/pcm", "rate": 24000}, "output": {"voice": "marin"}}
    assert start["delegation"] is None
    instructions = start["instructions"]
    assert "AccelerComm" in instructions and "LTE L1 Engineer" in instructions and "Speak English" in instructions
    assert "1. PDSCH scheduling" in instructions and "2. HARQ timing" in instructions
    assert "Tuned the LTE PDSCH scheduler" in instructions and "Own PDSCH and HARQ." in instructions
    greeting = fake_openai.live_of("session.commentary.append")[0]["content"]
    assert "first question about: PDSCH scheduling" in greeting
    topic_input = json.loads(fake_openai.bodies("topics")[0]["input"])
    assert {d["filename"] for d in topic_input["documents"]} == {"cv.txt", "prep.md"}
    await client.close()


async def test_interviewer_voice_captions_question_translation_and_live_hint(signed_in, fake_openai, tmp_path):
    _, client = await practice(signed_in, tmp_path)
    audio = await client.wait_type("say.audio")
    assert len(audio["data"]["audio"]) == len("A" * 6400)  # 4800 bytes of PCM, base64-encoded
    caption = await client.wait_for(lambda f: f["type"] == "transcript" and f["data"]["source"] == "live")
    assert caption["data"]["role"] == "interviewer" and caption["data"]["final"] is False
    say = await client.wait_type("say")
    assert say["data"]["text"] == "Hi, I'm your interviewer. Tell me how you tuned PDSCH scheduling?"
    assert client.of("transcript.dropped")[-1]["seq"] < say["seq"]       # the live caption is cleared first
    translation = await client.wait_type("transcript.translation")
    assert translation["data"]["segment_id"] == say["data"]["say_id"]
    started = await client.wait_type("turn.started")
    assert started["data"]["gate_seq"] == say["seq"]                     # the hint is attached to the spoken question
    await client.wait_type("turn.done")
    hint = json.loads(fake_openai.bodies("answer")[0]["input"])
    assert hint["question"] == "Tell me about your migration project?"   # the extracted question
    assert any(d["filename"] == "cv.txt" for d in hint["documents"])
    await client.close()


async def test_candidate_answer_is_transcribed_and_the_interviewer_follows_up(signed_in, fake_openai, tmp_path):
    _, client = await practice(signed_in, tmp_path)
    first = await client.wait_type("say")
    await asyncio.sleep(0.5)  # let the interviewer's audio finish playing
    await speak_for(client, 0.5)
    answer = await client.wait_for(lambda f: f["type"] == "transcript" and f["data"]["role"] == "interviewee" and f["data"]["final"])
    assert answer["data"]["text"] == "I tuned the proportional fair scheduler and cut latency by 30 percent."
    follow_up = await client.wait_for(lambda f: f["type"] == "say" and f["seq"] > first["seq"], timeout=6)
    assert follow_up["data"]["text"] == "Thanks. How did you budget HARQ timing?"
    assert fake_openai.live_audio_nonzero > 0
    await client.close()


async def test_microphone_is_silenced_while_the_interviewer_is_audible(signed_in, fake_openai, tmp_path):
    fake_openai.live_audio_chunks = 40  # 4 s of interviewer speech
    _, client = await practice(signed_in, tmp_path, documents=False)
    await client.wait_type("say.audio")
    await speak_for(client, 1.0)
    assert fake_openai.live_audio_nonzero == 0
    assert fake_openai.live_audio_zero > 0
    await client.close()


async def test_silence_keeps_the_stream_alive_when_the_microphone_is_quiet(signed_in, fake_openai, tmp_path):
    _, client = await practice(signed_in, tmp_path, documents=False)
    await client.wait_type("say")
    before = fake_openai.live_audio_zero
    await asyncio.sleep(0.5)
    assert fake_openai.live_audio_zero - before >= 4 * 2400  # several 50 ms silence chunks at 24 kHz
    await client.close()


async def test_delegation_requests_are_answered_so_the_model_carries_on(signed_in, fake_openai, tmp_path):
    fake_openai.live_delegate = True
    _, client = await practice(signed_in, tmp_path, documents=False)
    await client.wait_type("say")
    thinking = fake_openai.live_of("session.thinking.append")
    assert thinking and thinking[0]["delegation_id"] == "del_1"
    await client.close()


async def test_rejected_gpt_live_falls_back_to_the_text_interviewer(signed_in, fake_openai, tmp_path):
    fake_openai.live_reject = True
    _, client = await practice(signed_in, tmp_path, documents=False)
    degraded = await client.wait_type("transcription.state", stream_id="live")
    assert degraded["data"]["state"] == "degraded"
    say = await client.wait_type("say")
    assert say["data"]["text"] == "How did you tune PDSCH scheduling?"  # the first prepared question
    assert client.of("say.audio") == []
    await client.close()


async def test_ending_closes_the_voice_session_and_keeps_the_transcript(signed_in, fake_openai, tmp_path):
    session_id, client = await practice(signed_in, tmp_path, documents=False)
    await client.wait_type("say")
    await asyncio.sleep(0.5)
    await speak_for(client, 0.5)
    await client.wait_for(lambda f: f["type"] == "transcript" and f["data"]["role"] == "interviewee" and f["data"]["final"])
    await signed_in.call("POST", f"/api/v3/sessions/{session_id}/end")
    for _ in range(40):
        if fake_openai.live_of("session.close"):
            break
        await asyncio.sleep(0.05)
    assert fake_openai.live_of("session.close")
    transcript = await signed_in.call("GET", f"/api/v3/sessions/{session_id}/transcript")
    assert [s["role"] for s in transcript["segments"]][:2] == ["interviewer", "interviewee"]
    report = await signed_in.call("GET", f"/api/v3/sessions/{session_id}/report")
    assert report["question_count"] >= 1
