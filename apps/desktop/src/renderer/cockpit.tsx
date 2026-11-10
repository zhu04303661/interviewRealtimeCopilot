// Cockpit: the window shown during an interview.
//
// Streams the microphone (and, in Live mode, computer audio) to the engine,
// plays the practice interviewer's voice, and shows the bilingual transcript,
// extracted questions, streamed answer hints and the practice question panel.
import type React from 'react';
import { useEffect, useReducer, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

type Entry =
  | { kind: 'line'; key: string; seq: number; who: 'me' | 'interviewer'; text: string; zh?: string }
  | { kind: 'question'; key: string; seq: number; text: string; zh?: string; decision: string }
  | { kind: 'answer'; key: string; turnId: string; text: string; done: boolean; superseded?: boolean };
type Plan = { mode: string; current: number | null; asked: number[]; questions: { index: number; topic: string; question: string }[] };
type State = { entries: Entry[]; translations: Record<string, string>; plan: Plan | null; status: string; ended: boolean };
type Frame = { type: string; seq: number; data: any };

function reduce(state: State, frame: Frame): State {
  const { type, seq, data } = frame;
  const entries = state.entries;
  switch (type) {
    case 'transcript': {
      if (!data.final || !data.text) return state;
      const who = data.role === 'interviewer' ? 'interviewer' : 'me';
      return { ...state, entries: [...entries, { kind: 'line', key: `t${data.segment_id}`, seq, who, text: data.text, zh: state.translations[data.segment_id] }] };
    }
    case 'say':
      return { ...state, entries: [...entries, { kind: 'line', key: `s${data.say_id}`, seq, who: 'interviewer', text: data.text, zh: state.translations[data.say_id] }] };
    case 'transcript.translation': {
      const translations = { ...state.translations, [data.segment_id]: data.text };
      return { ...state, translations, entries: entries.map((e) => e.kind === 'line' && (e.key === `t${data.segment_id}` || e.key === `s${data.segment_id}`) ? { ...e, zh: data.text } : e) };
    }
    case 'gate.verdict':
      if (data.decision !== 'respond' && data.decision !== 'await_more') return state;
      return { ...state, entries: [...entries, { kind: 'question', key: `q${seq}`, seq, text: data.utterance, zh: data.translation, decision: data.decision }] };
    case 'turn.started':
      return { ...state, entries: [...entries, { kind: 'answer', key: `a${data.turn_id}`, turnId: data.turn_id, text: '', done: false }] };
    case 'turn.token':
      return { ...state, entries: entries.map((e) => e.kind === 'answer' && e.turnId === data.turn_id ? { ...e, text: e.text + data.delta } : e) };
    case 'turn.done':
    case 'turn.superseded':
      return { ...state, entries: entries.map((e) => e.kind === 'answer' && e.turnId === data.turn_id ? { ...e, done: true, superseded: type === 'turn.superseded' } : e) };
    case 'practice.plan':
      return { ...state, plan: data };
    case 'transcription.state':
      return { ...state, status: data.state === 'degraded' ? (data.message ?? 'Audio degraded') : '' };
    case 'error':
      return { ...state, status: data.message ?? 'Something went wrong.' };
    case 'session.ended':
      return { ...state, ended: true, status: 'Session ended · 会话已结束' };
    default:
      return state;
  }
}

/** Minimal Markdown for answer hints: **bold** headings and "- " bullets. */
function Hint({ text }: { text: string }) {
  const blocks: React.ReactElement[] = [];
  let bullets: string[] = [];
  const flush = () => { if (bullets.length) blocks.push(<ul key={blocks.length}>{bullets.map((b, i) => <li key={i}>{b}</li>)}</ul>); bullets = []; };
  for (const line of text.split('\n')) {
    const bold = line.match(/^\*\*(.+)\*\*$/);
    if (bold) { flush(); blocks.push(<div className="lang" key={blocks.length}>{bold[1]}</div>); }
    else if (/^\s*[-*] /.test(line)) bullets.push(line.replace(/^\s*[-*] /, '').replace(/\*\*/g, ''));
    else if (line.trim()) { flush(); blocks.push(<p key={blocks.length} style={{ margin: '4px 0' }}>{line.replace(/\*\*/g, '')}</p>); }
  }
  flush();
  return <>{blocks}</>;
}

/** Gapless playback of the practice interviewer (24 kHz PCM16 base64 chunks). */
function createVoice() {
  let context: AudioContext | null = null;
  let next = 0;
  const playing = new Set<AudioBufferSourceNode>();
  return {
    play(base64: string) {
      context ??= new AudioContext({ sampleRate: 24000 });
      const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
      const samples = new Int16Array(bytes.buffer, 0, bytes.length >> 1);
      if (!samples.length) return;
      document.body.dataset.voiceChunks = String(Number(document.body.dataset.voiceChunks ?? 0) + 1);
      const buffer = context.createBuffer(1, samples.length, 24000);
      const channel = buffer.getChannelData(0);
      for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 32768;
      const source = context.createBufferSource();
      source.buffer = buffer;
      source.connect(context.destination);
      next = Math.max(next, context.currentTime + 0.04);
      source.start(next);
      next += buffer.duration;
      playing.add(source);
      source.onended = () => playing.delete(source);
    },
    stop() { for (const s of playing) { try { s.stop(); } catch { /* already stopped */ } } playing.clear(); next = 0; },
  };
}

/** Automated tests: plays a WAV (base64) into a stream, once, 2 s after it is requested. */
async function testAudioStream(base64: string): Promise<MediaStream> {
  const context = new AudioContext();
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const buffer = await context.decodeAudioData(bytes.buffer);
  const destination = context.createMediaStreamDestination();
  const source = context.createBufferSource();
  source.buffer = buffer;
  source.connect(destination);
  source.start(context.currentTime + 2);
  return destination.stream;
}

/** Streams a MediaStream's audio as 100 ms PCM16 frames on lane ``stream``. */
async function captureLane(stream: MediaStream, lane: number, send: (frame: ArrayBuffer) => void,
  onLevel: (lane: number, level: number) => void): Promise<() => void> {
  const context = new AudioContext();
  await context.audioWorklet.addModule('./pcm-worklet.js');
  const source = context.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(context, 'pcm-frames');
  let sequence = 0;
  node.port.onmessage = ({ data }: MessageEvent<ArrayBuffer>) => {
    const samples = new Int16Array(data);
    let sum = 0;
    for (let i = 0; i < samples.length; i += 4) sum += samples[i] * samples[i];
    onLevel(lane, Math.min(1, Math.sqrt(sum / (samples.length / 4)) / 6000));
    const frame = new Uint8Array(5 + data.byteLength);
    const view = new DataView(frame.buffer);
    view.setUint8(0, lane);
    view.setUint32(1, sequence++, true);
    frame.set(new Uint8Array(data), 5);
    send(frame.buffer);
  };
  source.connect(node);
  return () => { stream.getTracks().forEach((t) => t.stop()); void context.close(); };
}

function Cockpit() {
  const [state, dispatch] = useReducer(reduce, { entries: [], translations: {}, plan: null, status: 'Connecting… · 正在连接…', ended: false });
  const [started] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  const socket = useRef<WebSocket | null>(null);
  const [session, setSession] = useState<{ topology: string }>({ topology: 'mock' });
  // Live input levels per lane (0 = microphone, 1 = computer audio), so missing input is visible at once.
  const [levels, setLevels] = useState<number[]>([0, 0]);
  const levelRef = useRef<number[]>([0, 0]);
  useEffect(() => {
    const timer = setInterval(() => { setLevels([...levelRef.current]); levelRef.current = levelRef.current.map((l) => l * 0.6); }, 200);
    return () => clearInterval(timer);
  }, []);
  const onLevel = (lane: number, level: number) => { levelRef.current[lane] = Math.max(levelRef.current[lane], level); };
  const feed = useRef<HTMLDivElement>(null);
  const answering = state.entries.some((e) => e.kind === 'answer' && !e.done);

  useEffect(() => {
    const voice = createVoice();
    const stops: (() => void)[] = [];
    let closed = false;
    void (async () => {
      const session = await window.copilot.currentSession();
      if (!session) return dispatch({ type: 'error', seq: 0, data: { message: 'No active session.' } });
      setSession(session);
      const ws = new WebSocket(session.wsUrl);
      ws.binaryType = 'arraybuffer';
      socket.current = ws;
      const general = session.topology === 'general';
      ws.onopen = async () => {
        const streams = [{ stream_id: 'candidate', source: 'mic', role: 'interviewee', encoding: 'pcm16', sample_rate: 16000 }];
        if (general) streams.push({ stream_id: 'interviewer', source: 'system', role: 'interviewer', encoding: 'pcm16', sample_rate: 16000 });
        ws.send(JSON.stringify({ v: 1, type: 'hello', jwt: session.jwt, session_id: session.sessionId, streams }));
        const send = (frame: ArrayBuffer) => { if (ws.readyState === WebSocket.OPEN) ws.send(frame); };
        try {
          const mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
          stops.push(await captureLane(mic, 0, send, onLevel));
          if (general && session.testSystemAudio) {
            stops.push(await captureLane(await testAudioStream(session.testSystemAudio), 1, send, onLevel));
          } else if (general) {
            const display = await navigator.mediaDevices.getDisplayMedia({ audio: true, video: true });
            display.getVideoTracks().forEach((t) => t.stop());
            if (!display.getAudioTracks().length) throw new Error('No system audio. Allow Screen & System Audio Recording. · 无系统声音，请授权屏幕与系统录音。');
            stops.push(await captureLane(new MediaStream(display.getAudioTracks()), 1, send, onLevel));
          }
          dispatch({ type: 'transcription.state', seq: 0, data: { state: 'ok' } });
        } catch (error) {
          dispatch({ type: 'error', seq: 0, data: { message: (error as Error).message } });
        }
      };
      ws.onmessage = ({ data }) => {
        if (typeof data !== 'string') return;
        const frame: Frame = JSON.parse(data);
        if (frame.type === 'say.audio') return voice.play(frame.data.audio);
        if (frame.type === 'say.audio.clear' || frame.type === 'session.ended') voice.stop();
        dispatch(frame);
      };
      ws.onclose = () => { if (!closed) dispatch({ type: 'error', seq: 0, data: { message: 'Disconnected · 连接已断开' } }); };
    })();
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => { closed = true; clearInterval(timer); voice.stop(); stops.forEach((s) => s()); socket.current?.close(); };
  }, []);

  useEffect(() => { feed.current?.scrollTo({ top: feed.current.scrollHeight }); }, [state.entries]);

  const request = (utterance: string, intent: string, gateSeq?: number) =>
    socket.current?.send(JSON.stringify({ v: 1, type: 'answer_request', utterance, intent, ...(gateSeq !== undefined ? { gate_seq: gateSeq } : {}) }));
  const elapsed = Math.floor((now - started) / 1000);
  const asked = new Set(state.plan?.asked ?? []);

  const [planOpen, setPlanOpen] = useState(true);
  const live = !state.ended;
  return (
    <div className="cockpit">
      <header className="c-header">
        <span className={`dot ${live ? '' : 'off'}`} />
        <span className="c-status">{live ? (session.topology === 'mock' ? 'Practice' : 'Listening') : 'Ended'}</span>
        <span className="c-sub">{live ? (session.topology === 'mock' ? '语音练习' : '实时面试') : '已结束'}</span>
        <span className="spacer" />
        {(session.topology === 'mock' ? [[0, 'Mic · 麦克风']] : [[0, 'Mic · 麦克风'], [1, 'Computer · 电脑']]).map(([lane, label]) => (
          <span key={lane} className="meter" title={label as string}><span className="meter-label">{(label as string).split(' ')[0]}</span>
            <span className="meter-bar"><span style={{ width: `${Math.round(levels[lane as number] * 100)}%` }} /></span></span>))}
      </header>
      {state.status && <div className="c-banner">{state.status}</div>}
      {state.plan && (
        <div className="c-plan">
          <div className="head" onClick={() => setPlanOpen(!planOpen)}>
            <span>Practice questions · 练习题 {asked.size}/{state.plan.questions.length}</span><span>{planOpen ? '▾' : '▸'}</span>
          </div>
          {planOpen && <>
            <div className="c-modes">
              {[['sequential', 'Order · 顺序'], ['random', 'Random · 随机'], ['ai', 'AI · 临场']].map(([mode, label]) => (
                <button key={mode} className={state.plan!.mode === mode ? 'active' : ''} onClick={() => request(mode, 'practice.mode')}>{label}</button>))}
            </div>
            <ol>
              {state.plan.questions.map((q) => (
                <li key={q.index}>
                  <button title={q.question} className={state.plan!.current === q.index ? 'current' : asked.has(q.index) ? 'asked' : ''} onClick={() => request('', 'practice.goto', q.index)}>
                    <span className="n">{state.plan!.current === q.index ? '▶' : asked.has(q.index) ? '✓' : `${q.index + 1}.`}</span>{q.topic ? `${q.topic} — ` : ''}{q.question}
                  </button>
                </li>))}
            </ol>
          </>}
        </div>
      )}
      <div className="c-feed" ref={feed}>
        {state.entries.length === 0 && <div className="c-empty"><b>You're covered.</b><br />Listening for the interviewer's first question. · 正在聆听面试官的第一个问题。</div>}
        {state.entries.map((e) => {
          if (e.kind === 'line') {
            const voice = e.who === 'interviewer' && e.key.startsWith('s');
            return (
              <div className={`c-entry ${e.who === 'me' ? 'me' : ''} ${voice ? 'c-voice' : ''}`} key={e.key}>
                <span className={`stamp ${e.who === 'me' ? 'me' : ''}`}>{e.who === 'me' ? 'You · 我' : 'Interviewer · 面试官'}</span>
                <div className="text">{e.text}</div>
                {e.zh && <div className="zh">{e.zh}</div>}
                <button className="c-action" disabled={answering} onClick={() => e.who === 'me' ? request(e.text, 'continue', e.seq) : request(e.text, 'general', e.seq)}>
                  {e.who === 'me' ? 'Expand answer · 补充回答' : 'Suggest answer · 生成回答'}</button>
              </div>
            );
          }
          if (e.kind === 'question') return (
            <div className="c-question" key={e.key}>
              <span className="stamp">{e.decision === 'await_more' ? 'Question · 问题 (listening…)' : 'Question · 问题'}</span>
              <div className="text" style={{ marginTop: 6 }}>{e.text}</div>
              {e.zh && <div className="zh" style={{ marginTop: 4, color: 'var(--c-text-2)' }}>{e.zh}</div>}
            </div>
          );
          return (
            <div className={`c-answer ${e.superseded ? 'superseded' : ''}`} key={e.key}>
              <Hint text={e.text} />
              {!e.done && <span className="typing" />}
              {e.done && !e.superseded && <div className="source">From your materials · 基于你的资料</div>}
            </div>
          );
        })}
      </div>
      <footer className="c-footer">
        <span className="spacer" />
        <span className="timer">{String(Math.floor(elapsed / 60)).padStart(2, '0')}:{String(elapsed % 60).padStart(2, '0')}</span>
        <button className="c-btn end" onClick={() => window.copilot.endSession()}>End · 结束</button>
      </footer>
    </div>
  );
}

document.body.classList.add('cockpit-body');
createRoot(document.getElementById('root')!).render(<Cockpit />);
