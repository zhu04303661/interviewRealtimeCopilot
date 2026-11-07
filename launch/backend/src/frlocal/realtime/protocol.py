"""Wire format between the app's realtime client and the engine.

Client → engine
    text   ``{"v": 1, "type": "hello", "jwt", "session_id", "streams": [...], "last_seen_seq"?}``
           ``{"v": 1, "type": "ping"}``
           ``{"v": 1, "type": "finalize", "stream": <index>}``   end of a spoken turn (client VAD)
           ``{"v": 1, "type": "answer_request", "utterance", "gate_seq"?}``
    binary ``[u8 stream index][u32 LE sequence][PCM16 mono 16 kHz …]``

Engine → client
    text   ``{"v": 1, "type", "seq", "data"}`` where ``seq`` increases by one per frame.
"""

from __future__ import annotations

import json
import struct
from array import array
from dataclasses import dataclass
from typing import Any

# Capture lanes per interview mode, in the order the client declares them.
STREAM_ROLES: dict[str, tuple[str, ...]] = {
    "general": ("interviewee", "interviewer"),  # microphone, computer audio
    "mock": ("interviewee",),                   # microphone only; AI interviewer
}
SPEAKER_LABELS = {"interviewee": "me", "interviewer": "interviewer"}

MAX_AUDIO_FRAME_BYTES = 32_005
INPUT_RATE = 16_000
OUTPUT_RATE = 24_000


@dataclass(frozen=True)
class AudioFrame:
    stream: int
    sequence: int
    pcm: bytes


def parse_audio_frame(payload: bytes) -> AudioFrame | None:
    """Decode one binary audio frame; ``None`` if it is malformed."""
    if len(payload) < 7 or (len(payload) - 5) % 2 or len(payload) > MAX_AUDIO_FRAME_BYTES:
        return None
    stream, sequence = struct.unpack_from("<BI", payload)
    return AudioFrame(stream, sequence, payload[5:])


def valid_stream_declarations(topology: str, declarations: Any) -> bool:
    """Whether the client's ``hello.streams`` match what this mode captures."""
    roles = STREAM_ROLES.get(topology)
    if roles is None or not isinstance(declarations, list) or len(declarations) != len(roles):
        return False
    return all(
        isinstance(stream, dict) and stream.get("role") == role
        and stream.get("encoding") == "pcm16" and stream.get("sample_rate") == INPUT_RATE
        for stream, role in zip(declarations, roles, strict=True)
    )


def resample_16k_to_24k(pcm: bytes) -> bytes:
    """Linear-interpolate 16 kHz PCM16 to the 24 kHz OpenAI transcription expects."""
    samples = array("h")
    samples.frombytes(pcm)
    count = len(samples)
    if count == 0:
        return b""
    out = array("h", bytes(2 * round(count * 1.5)))
    last = count - 1
    for index in range(len(out)):
        position = index * 2 / 3
        left = int(position)
        start = samples[left]
        end = samples[left + 1 if left < last else last]
        out[index] = round(start + (end - start) * (position - left))
    return out.tobytes()


def encode_frame(kind: str, seq: int, data: dict[str, Any]) -> str:
    return json.dumps({"v": 1, "type": kind, "seq": seq, "data": data}, ensure_ascii=False, separators=(",", ":"))


def decode_text(value: str) -> dict[str, Any]:
    """Parse a client text frame; anything malformed becomes an empty dict."""
    try:
        frame = json.loads(value)
    except ValueError:
        return {}
    return frame if isinstance(frame, dict) else {}
