"""Spoken practice with the speech-to-speech Realtime interviewer (the default practice mode)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import pytest

from frlocal.config import Limits

from .test_practice_live import practice, speak_for


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
    assert audio["input"]["turn_detection"] == {"type": "semantic_vad", "eagerness": "low", "create_response": False}
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
