"""The lane gate: scripted-probability tests — only SileroVad touches the ONNX model."""

from __future__ import annotations

import numpy as np
import pytest

from frlocal.realtime import vad
from frlocal.realtime.vad import CARRY_ELEMENTS, FRAME_SAMPLES, PRE_ROLL_SAMPLES, VadGate

CHUNK = np.zeros(1600, dtype=np.int16).tobytes()  # one 100 ms capture chunk, like the app sends


def gate(probabilities: list[float]) -> tuple[VadGate, list[bytes], list[str]]:
    """A gate whose probe replays ``probabilities`` per 32 ms frame; returns (gate, emitted, events)."""
    emitted, events = [], []
    probs = iter(probabilities)

    def probe(frame: np.ndarray, carry: np.ndarray) -> tuple[float, np.ndarray]:
        assert frame.shape == (FRAME_SAMPLES,)
        return next(probs, 0.0), carry

    return VadGate(probe, emitted.append, lambda: events.append("end")), emitted, events


def test_silence_is_gated_and_never_emitted():
    g, emitted, events = gate([0.01] * 100)
    for _ in range(10):
        g.feed(CHUNK)
    assert emitted == [] and events == []


def test_onset_flushes_pre_roll_and_then_forwards():
    # Chunks carry 3.125 inference frames each (1600 samples, 512-frame + leftover), so after
    # two chunks exactly 6 quiet frames ran; the 7th — first speech frame — lands in chunk 3.
    g, emitted, _ = gate([0.01] * 6 + [0.9] * 94)
    g.feed(CHUNK)
    g.feed(CHUNK)
    assert emitted == []  # still quiet: everything is held in pre-roll
    g.feed(CHUNK)
    assert len(emitted) == 3  # onset inside chunk 3 flushed the whole pre-roll, onset chunk included
    g.feed(CHUNK)
    assert len(emitted) == 4  # and from here audio forwards as it arrives


def test_pre_roll_is_bounded_to_384_ms():
    g, _, _ = gate([0.01] * 200)
    for _ in range(10):
        g.feed(CHUNK)
    assert sum(len(c) >> 1 for c in g._pre_roll) < PRE_ROLL_SAMPLES + 1600  # never holds much more than the pad


def test_23_sub_negative_frames_do_not_end_the_turn():
    # A 23-frame pause (~0.74 s) stays inside the hangover — speech + pause + speech is one turn.
    g, emitted, events = gate([0.9] * 10 + [0.1] * 23 + [0.9] * 10 + [0.1] * 60)
    for _ in range(35):
        g.feed(CHUNK)
    assert emitted and events == ["end"]  # the only end is the final run of quiet


def test_24_sub_negative_frames_end_the_turn():
    # Same script with 24 low frames (~0.77 s): the pause ends turn one and the second
    # speech run becomes its own turn — two ends, and none early.
    g, emitted, events = gate([0.9] * 10 + [0.1] * 24 + [0.9] * 10 + [0.1] * 60)
    for _ in range(35):
        g.feed(CHUNK)
    assert emitted and events == ["end", "end"]


def test_deadband_reaffirms_speech_and_does_not_count_down():
    # Frames between 0.35 and 0.5 while speaking reset the redemption countdown.
    g, _, events = gate([0.9] * 10 + [0.1] * 20 + [0.45] * 2 + [0.1] * 20 + [0.9] * 5 + [0.1] * 60)
    for _ in range(40):
        g.feed(CHUNK)
    # The first 20 low frames never reach 24 thanks to the deadband; the turn ends in the final run.
    assert events == ["end"]


def test_short_pause_inside_speech_does_not_end_the_turn():
    # A 0.5 s pause (16 frames) mid-sentence is well inside the 24-frame hangover.
    g, _, events = gate([0.9] * 20 + [0.1] * 16 + [0.9] * 20 + [0.1] * 60)
    for _ in range(40):
        g.feed(CHUNK)
    assert events == ["end"]  # one turn, one end — not two


def test_probe_failure_fails_open():
    def broken(frame: np.ndarray, carry: np.ndarray) -> tuple[float, np.ndarray]:
        raise RuntimeError("model wedged")

    emitted = []
    g = VadGate(broken, emitted.append, lambda: None)
    g.feed(CHUNK)   # the failing inference flips the gate into fail-open
    assert g.failed_open
    g.feed(CHUNK)
    assert len(emitted) >= 1  # audio now forwards unconditionally


def test_carry_layout_is_stable():
    assert CARRY_ELEMENTS == 256 + 64


@pytest.mark.skipif(not vad.MODEL_PATH.is_file(), reason="model asset not present")
def test_real_model_scores_silence_low():
    """Sanity: the bundled ONNX model rates silence far below the negative threshold."""
    real = vad.SileroVad()
    carry = real.initial_carry()
    prob, _ = real.process(np.zeros(FRAME_SAMPLES, dtype=np.float32), carry)
    assert prob < 0.1
