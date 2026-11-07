"""Runtime settings shared by every module.

All tunables live here so limits, model names and timing budgets are easy to
find and to override from tests. Values are read once at start-up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MB = 1024 * 1024


@dataclass(frozen=True)
class Models:
    """OpenAI models used by the backend."""

    transcription: str = "gpt-live-transcribe"
    # Short, latency-critical calls: interviewer translation, question
    # extraction and the mock interviewer's next question.
    understanding: str = "gpt-5.4-mini"
    # Speaker labels for each finished utterance (file transcription with diarization).
    diarization: str = "gpt-4o-transcribe-diarize"
    # Streamed answer hints, Debrief and screenshot analysis.
    coaching: str = "gpt-5.4-mini"
    # Spoken practice interviewer: speech-to-speech Realtime model (default) or full-duplex GPT-Live.
    realtime_voice_agent: str = "gpt-realtime-2.1"
    live: str = "gpt-live-1"
    live_voice: str = "marin"


@dataclass(frozen=True)
class Limits:
    """Size and time limits. Each one protects memory, disk or the UI."""

    max_document_bytes: int = 500 * MB
    max_document_text_chars: int = 20_000_000
    document_prepare_timeout_s: float = 600.0
    max_recording_bytes: int = 256 * MB
    max_screenshot_bytes: int = 10 * MB
    max_voice_sample_bytes: int = 4 * MB

    # Session context sent with each answer request.
    max_source_documents: int = 8
    max_resume_chars: int = 8_000
    max_material_chars: int = 5_000
    max_source_chars: int = 24_000
    passage_chars: int = 1_500
    max_query_terms: int = 16

    # Live audio: 16 kHz mono PCM16 from the app, 24 kHz to OpenAI.
    min_turn_bytes: int = 3_200          # 100 ms; shorter turns are discarded
    max_turn_bytes: int = 480_000        # 15 s; longer speech is committed early
    max_queued_audio_bytes: int = 320_000
    max_pending_commits: int = 8
    asr_connect_timeout_s: float = 12.0
    asr_drain_timeout_s: float = 5.0
    asr_retry_after_s: float = 5.0

    # Model calls.
    understanding_timeout_s: float = 8.0
    answer_timeout_s: float = 45.0
    answer_max_output_tokens: int = 700   # about one minute of speech in English plus the Chinese version
    replay_frames: int = 512             # frames kept for reconnect replay

    # Spoken practice (GPT-Live).
    live_start_timeout_s: float = 15.0
    live_say_gap_s: float = 0.9          # interviewer silence that ends one spoken turn
    live_candidate_gap_s: float = 1.2    # candidate silence that ends one answer segment
    live_silence_interval_s: float = 0.1 # send silence when the microphone is quiet this long
    practice_reply_pause_s: float = 2.5  # candidate silence before the practice interviewer replies
    live_echo_margin_s: float = 0.8      # keep the microphone muted this long after playback ends (covers playback lag)


@dataclass(frozen=True)
class Settings:
    """Everything the backend needs to start."""

    accounts_dir: Path
    workspace_dir: Path
    # Shared secret the Electron main process sends with every request.
    token: str
    openai_base: str = "https://api.openai.com"
    openai_proxy: str | None = None
    env_file: Path = field(default_factory=lambda: Path.home() / ".env")
    # Practice interviewer: "realtime" (speech-to-speech), "live" (GPT-Live) or "text" (no voice).
    practice_voice: str = "realtime"
    # Let the candidate interrupt the spoken interviewer. Needs headphones: on
    # laptop speakers the model would hear (and interrupt) itself.
    practice_barge_in: bool = False
    models: Models = field(default_factory=Models)
    limits: Limits = field(default_factory=Limits)

    @property
    def openai_ws_base(self) -> str:
        """WebSocket origin matching :attr:`openai_base`."""
        if self.openai_base.startswith("https://"):
            return "wss://" + self.openai_base[len("https://"):]
        if self.openai_base.startswith("http://"):
            return "ws://" + self.openai_base[len("http://"):]
        return self.openai_base


def settings_from_environment(accounts_dir: Path, workspace_dir: Path) -> Settings:
    """Build settings from the variables the Electron bridge passes in."""
    token = os.environ.get("FRLOCAL_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("FRLOCAL_TOKEN must be set to a random secret of at least 32 characters.")
    return Settings(
        accounts_dir=accounts_dir,
        workspace_dir=workspace_dir,
        token=token,
        openai_base=os.environ.get("FRLOCAL_OPENAI_BASE", "https://api.openai.com").rstrip("/"),
        openai_proxy=os.environ.get("FRLOCAL_OPENAI_PROXY") or None,
        practice_voice=os.environ.get("FRLOCAL_PRACTICE_VOICE", "realtime").strip().lower(),
        practice_barge_in=os.environ.get("FRLOCAL_PRACTICE_BARGE_IN", "").strip() in ("1", "true", "yes"),
    )
