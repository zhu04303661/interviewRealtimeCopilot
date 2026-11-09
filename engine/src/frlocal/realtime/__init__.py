"""The live interview engine.

The app's realtime client (the original ``RealtimeBackend`` in the Electron
main process) opens one WebSocket per interview to this engine. It sends a
``hello`` with the audio streams it captures and then binary PCM frames; the
engine sends back JSON frames that the cockpit window renders.

Speakers are told apart by capture lane: the microphone is the candidate
(``interviewee``) and the computer's audio is the ``interviewer``. Practice
sessions have only the microphone; the AI interviewer speaks through ``say``
frames.

Pipeline for each interviewer utterance::

    PCM ─▶ asr.TranscriptionStream ─▶ transcript (interim, then final)
                                         │
                                         ▼
                      understanding.analyze ─▶ transcript.translation (中↔英)
                                         │      gate.verdict (extracted question)
                                         ▼
                      coach.answer (streamed) ─▶ turn.started / turn.token… / turn.done

Modules: ``protocol`` (frames and audio), ``asr`` (OpenAI transcription
socket per lane), ``understanding`` (translation + question extraction),
``coach`` (prompts for answers, the mock interviewer and Debrief),
``session`` (one interview's state machine) and ``engine`` (the registry and
the WebSocket endpoint).
"""
