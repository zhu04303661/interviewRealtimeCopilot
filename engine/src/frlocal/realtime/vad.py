"""Per-lane speech gating with the Silero VAD model.

Replaces the desktop's energy-RMS turn detector, which cut sentences early:
its noise floor crept up into sustained speech, and one shared enter/exit
threshold let soft syllables count as silence. The design follows the proven
setup of the recovered Final Round app:

* ``silero_vad.onnx`` (MIT) scores 32 ms frames — the model keeps probability
  high through breaths, fricatives and clause pauses that read as "quiet" to
  an energy detector;
* hysteresis: ≥ 0.5 enters speech, < 0.35 counts toward ending it, and the
  0.35–0.5 band reaffirms speech (resets the countdown);
* 24 consecutive sub-negative frames (~0.77 s) end the turn — the engine then
  commits the lane's transcription;
* a 384 ms pre-roll of held audio flushes on each onset so word starts are
  not clipped, and non-speech audio never reaches transcription (which also
  saves billed minutes);
* inference failure fails open: the gate forwards everything, matching the
  pre-VAD pipeline.

``VadGate`` takes its probability probe as a constructor argument so tests can
drive it with scripted values — only ``SileroVad`` touches the ONNX model.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent.parent / "models" / "silero_vad.onnx"

FRAME_SAMPLES = 512            # Silero v5 consumes exactly 512 samples per inference frame (32 ms @ 16 kHz)
STATE_ELEMENTS = 2 * 1 * 128   # LSTM state [2, 1, 128]
CONTEXT_SAMPLES = 64           # the model sees [context(64), frame(512)]
CARRY_ELEMENTS = STATE_ELEMENTS + CONTEXT_SAMPLES

POSITIVE_THRESHOLD = 0.5       # probability at/above which a frame enters the speaking state
NEGATIVE_THRESHOLD = 0.35      # below this, a frame counts toward ending the segment
REDEMPTION_FRAMES = 24         # 24 x 32 ms ~= 0.77 s of sub-negative frames ends the turn
PRE_ROLL_SAMPLES = 6144        # 384 ms of audio retained while not speaking, flushed on onset

Probe = Callable[[np.ndarray, np.ndarray], tuple[float, np.ndarray]]


class SileroVad:
    """The shared ONNX session. One per app; each lane keeps its own recurrent carry."""

    def __init__(self, model_path: Path = MODEL_PATH) -> None:
        import onnxruntime as ort  # imported lazily: the engine still works without it

        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(model_path), sess_options=options, providers=["CPUExecutionProvider"])
        self._sr = np.array(16000, dtype=np.int64)
        self.process(np.zeros(FRAME_SAMPLES, dtype=np.float32), np.zeros(CARRY_ELEMENTS, dtype=np.float32))  # cold-start warm-up

    @staticmethod
    def initial_carry() -> np.ndarray:
        return np.zeros(CARRY_ELEMENTS, dtype=np.float32)

    def process(self, frame: np.ndarray, carry: np.ndarray) -> tuple[float, np.ndarray]:
        """One 512-sample frame plus this lane's carry → (speech probability, next carry)."""
        model_input = np.concatenate((carry[STATE_ELEMENTS:], frame))[None]
        output, next_state = self._session.run(
            ["output", "stateN"], {"input": model_input, "state": carry[:STATE_ELEMENTS].reshape(2, 1, 128), "sr": self._sr})
        next_carry = np.empty(CARRY_ELEMENTS, dtype=np.float32)
        next_carry[:STATE_ELEMENTS] = next_state.reshape(-1)[:STATE_ELEMENTS]
        next_carry[STATE_ELEMENTS:] = frame[-CONTEXT_SAMPLES:]
        return float(output.reshape(-1)[0]), next_carry


class VadGate:
    """One capture lane's gate: forwards audio to transcription only while speech is believed
    ongoing (plus the pre-roll), and calls ``on_speech_end`` when the turn is over."""

    def __init__(self, probe: Probe, on_send: Callable[[bytes], None], on_speech_end: Callable[[], None]) -> None:
        self._probe, self._on_send, self._on_speech_end = probe, on_send, on_speech_end
        self._carry = np.zeros(CARRY_ELEMENTS, dtype=np.float32)
        self._speaking = self._failed_open = False
        self._redemption = 0
        self._pre_roll: deque[bytes] = deque()
        self._pre_roll_samples = 0
        self._leftover = np.empty(0, dtype=np.float32)

    @property
    def failed_open(self) -> bool:
        return self._failed_open

    def feed(self, pcm: bytes) -> None:
        """A 16 kHz PCM16 chunk from the lane. Emission is decided by the current speaking flag,
        exactly as in the reference design; inference then updates it for the next chunks."""
        if self._failed_open or self._speaking:
            self._emit(pcm)
        else:
            self._pre_roll.append(pcm)
            self._pre_roll_samples += len(pcm) >> 1
            while len(self._pre_roll) > 1 and self._pre_roll_samples - (len(self._pre_roll[0]) >> 1) >= PRE_ROLL_SAMPLES:
                self._pre_roll_samples -= len(self._pre_roll.popleft()) >> 1
        self._infer(pcm)

    def _emit(self, pcm: bytes) -> None:
        self._on_send(pcm)

    def _flush_pre_roll(self) -> None:
        held, self._pre_roll, self._pre_roll_samples = self._pre_roll, deque(), 0
        for pcm in held:
            self._emit(pcm)

    def _fail_open(self) -> None:
        if not self._failed_open:
            log.warning("VAD inference failed; failing open (forwarding all audio)")
            self._failed_open = self._speaking = True
            self._redemption = 0
            self._flush_pre_roll()

    def _infer(self, pcm: bytes) -> None:
        if self._failed_open:
            return
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        combined = np.concatenate((self._leftover, samples)) if self._leftover.size else samples
        count = len(combined) // FRAME_SAMPLES
        for i in range(count):
            frame = combined[i * FRAME_SAMPLES:(i + 1) * FRAME_SAMPLES]
            try:
                probability, self._carry = self._probe(frame, self._carry)
            except Exception:
                self._fail_open()
                return
            self._on_probability(probability)
        self._leftover = combined[count * FRAME_SAMPLES:]

    def _on_probability(self, probability: float) -> None:
        if probability >= POSITIVE_THRESHOLD:
            if not self._speaking:
                self._speaking = True
                self._flush_pre_roll()
            self._redemption = 0
        elif probability < NEGATIVE_THRESHOLD:
            if self._speaking:
                self._redemption += 1
                if self._redemption >= REDEMPTION_FRAMES:
                    self._speaking = False
                    self._redemption = 0
                    self._on_speech_end()
        elif self._speaking:  # the 0.35–0.5 deadband reaffirms speech
            self._redemption = 0


def make_gate(on_send: Callable[[bytes], None], on_speech_end: Callable[[], None], vad: SileroVad | None) -> VadGate | None:
    """A gate when the model is available; ``None`` keeps the lane on plain forwarding."""
    if vad is None:
        return None
    return VadGate(vad.process, on_send, on_speech_end)
