// Main window: account, goals, library, history and settings.
import { BookOpen, CircleHelp, FileText, Flag, History as HistoryIcon, Mic, Monitor, Plus, Radio, Search, Settings as SettingsIcon, Upload } from 'lucide-react';
import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const OWNER = 'main';
type Goal = { goal_id: string; role: string; company: string; job_description?: string; company_detail?: string; created_at: string };
type Doc = { document_id: string; filename: string; kind: 'resume' | 'material'; status: string; text_chars?: number; byte_size?: number; created_at?: string; failure_reason?: string };
type SessionRow = { session_id: string; goal_id: string; role: string; company: string; topology: string; created_at: string;
  duration_seconds: number | null; status: string; headline?: string; failure_reason?: string | null };
type Route = { page: 'goals' } | { page: 'goal'; goalId: string } | { page: 'library' } | { page: 'history'; sessionId?: string } | { page: 'settings' };

async function auth(path: string, body?: Record<string, unknown>) {
  const result = body
    ? await window.copilot.request('POST', `/local/auth/${path}`, { owner: OWNER, ...body })
    : await window.copilot.request('GET', `/local/auth/${path}?owner=${OWNER}`);
  if (!result.ok) throw new Error(result.error);
  return result.value;
}

const when = (iso?: string) => (iso ? new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '');
const minutes = (s: number | null) => (s == null ? '' : `${Math.max(1, Math.round(s / 60))} min`);
const docStatus = (d: Doc) => d.status === 'ready' ? <span className="badge good">Ready · 就绪</span>
  : d.status === 'preparing' ? <span className="badge warn">Preparing · 准备中</span> : <span className="badge bad">Couldn't prepare · 失败</span>;
/** Knowledge sources chosen for a goal (default: every ready document). */
const sourcesKey = (goalId: string) => `sources:${goalId}`;
const chosenSources = (goalId: string, docs: Doc[]) => {
  const saved = localStorage.getItem(sourcesKey(goalId));
  const ready = docs.filter((d) => d.status === 'ready').map((d) => d.document_id);
  return saved ? (JSON.parse(saved) as string[]).filter((id) => ready.includes(id)) : ready;
};

// ── sign in ───────────────────────────────────────────────────────────────
function SignIn({ onSignedIn }: { onSignedIn: (name: string) => void }) {
  const [mode, setMode] = useState<'sign-in' | 'register'>('sign-in');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  // Same rules as the engine (accounts.py): checked here so mistakes show before submitting.
  const nameProblem = !/^[a-z][a-z0-9._-]{2,31}$/i.test(username.trim())
    ? 'Username: 3–32 letters, numbers, . _ or -, starting with a letter (no email or Chinese). · 用户名：3–32 位字母、数字或 . _ -，以字母开头（不能用邮箱或中文）。' : '';
  const passwordProblem = password.length < 15 ? 'Password: at least 15 characters. · 密码：至少 15 个字符。' : '';
  const submit = async () => {
    setError('');
    if (mode === 'register' && (nameProblem || passwordProblem)) return setError(nameProblem || passwordProblem);
    try { onSignedIn((await auth(mode, { username, password })).account.username); } catch (e) { setError((e as Error).message); }
  };
  return (
    <div className="auth">
      <div className="card">
        <div className="logo">IR</div>
        <h1>{mode === 'sign-in' ? 'Welcome back · 欢迎回来' : 'Create your account · 注册'}</h1>
        <p className="muted small" style={{ marginTop: 0 }}>Interview Realtime Copilot</p>
        <label className="field"><span>Username · 用户名</span><input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus /></label>
        <label className="field"><span>Password · 密码</span>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()} /></label>
        {mode === 'register' && (
          <ul className="small muted" style={{ margin: '-4px 0 14px', paddingLeft: 18 }}>
            <li style={{ color: username && nameProblem ? 'var(--bad)' : undefined }}>Username: 3–32 letters/numbers/. _ -, starts with a letter · 用户名 3–32 位，以字母开头</li>
            <li style={{ color: password && passwordProblem ? 'var(--bad)' : undefined }}>Password: at least 15 characters ({password.length}/15) · 密码至少 15 位</li>
          </ul>
        )}
        {error && <p className="error">{error}</p>}
        <button className="btn primary" style={{ width: '100%', justifyContent: 'center' }} onClick={submit}>{mode === 'sign-in' ? 'Sign in · 登录' : 'Create account · 注册'}</button>
        <p className="small muted" style={{ textAlign: 'center', marginBottom: 0 }}>
          <button className="link" onClick={() => setMode(mode === 'sign-in' ? 'register' : 'sign-in')}>
            {mode === 'sign-in' ? 'New here? Create an account · 注册新账号' : 'Already registered? Sign in · 已有账号'}</button>
        </p>
      </div>
    </div>
  );
}

// ── shared pieces ─────────────────────────────────────────────────────────
function Empty({ icon, title, children }: { icon: React.ReactNode; title: string; children?: React.ReactNode }) {
  return <div className="empty"><div className="art">{icon}</div><h3>{title}</h3>{children}</div>;
}

function NewGoal({ onClose, onCreated }: { onClose: () => void; onCreated: (goal: Goal) => void }) {
  const [draft, setDraft] = useState({ role: '', company: '', job_description: '' });
  const [error, setError] = useState('');
  const create = async () => {
    try { onCreated(await window.copilot.request('POST', '/api/v3/goals', draft)); } catch (e) { setError((e as Error).message); }
  };
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>New goal · 新目标</h2>
        <p className="muted small" style={{ marginTop: -10 }}>One role at one company. Two fields are enough. · 一个公司的一个职位，填两项即可。</p>
        <label className="field"><span>Role · 职位</span><input className="input" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })} autoFocus /></label>
        <label className="field"><span>Company · 公司</span><input className="input" value={draft.company} onChange={(e) => setDraft({ ...draft, company: e.target.value })} /></label>
        <label className="field"><span>Job description (optional) · 职位描述（可选）</span>
          <textarea className="textarea" value={draft.job_description} onChange={(e) => setDraft({ ...draft, job_description: e.target.value })} /></label>
        {error && <p className="error">{error}</p>}
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button className="btn ghost" onClick={onClose}>Cancel · 取消</button>
          <button className="btn primary" disabled={!draft.role.trim() || !draft.company.trim()} onClick={create}>Create goal · 创建</button>
        </div>
      </div>
    </div>
  );
}

// ── pages ─────────────────────────────────────────────────────────────────
function GoalsPage({ goals, docs, sessions, open, newGoal }: { goals: Goal[]; docs: Doc[]; sessions: SessionRow[]; open: (id: string) => void; newGoal: () => void }) {
  const [query, setQuery] = useState('');
  const [hideGuide, setHideGuide] = useState(localStorage.getItem('guide:hidden') === '1');
  const shown = goals.filter((g) => `${g.role} ${g.company}`.toLowerCase().includes(query.toLowerCase()));
  const steps = [goals.length > 0, docs.some((d) => d.kind === 'resume'), sessions.some((s) => s.topology === 'mock'), sessions.some((s) => s.status === 'ready')];
  const current = steps.indexOf(false);
  return (
    <div className="page">
      <div className="page-head">
        <div><div className="eyebrow">Interview plan · 面试计划</div><h1>Goals · 目标</h1>
          <p>{goals.length} current goal{goals.length === 1 ? '' : 's'} · {sessions.length} session{sessions.length === 1 ? '' : 's'}</p></div>
        <button className="btn" onClick={newGoal}>New goal · 新目标</button>
      </div>
      {!hideGuide && current !== -1 && (
        <div className="hero" style={{ marginTop: 28 }}>
          <div className="row"><div className="eyebrow">Getting started · 快速开始</div><span className="spacer" />
            <button className="link small" onClick={() => { localStorage.setItem('guide:hidden', '1'); setHideGuide(true); }}>Dismiss · 关闭</button></div>
          <h2 style={{ margin: '10px 0 0', fontSize: 22 }}>Four steps to your first debrief · 四步完成第一次复盘</h2>
          <ol className="steps">
            {['Create a goal · 创建目标', 'Add your resume · 添加简历', 'Run a practice session · 进行一次语音练习', 'Read your debrief · 查看复盘'].map((label, i) => (
              <li key={label} className={steps[i] ? 'done' : i === current ? 'current' : ''}>{label}</li>))}
          </ol>
        </div>
      )}
      <div className="row" style={{ margin: '26px 0 4px' }}>
        <div className="segmented"><button className="active">Current · {goals.length}</button></div><span className="spacer" />
        <div style={{ position: 'relative', width: 240 }}>
          <Search size={15} style={{ position: 'absolute', left: 11, top: 10, color: 'var(--text-3)' }} />
          <input className="input" style={{ paddingLeft: 32 }} placeholder="Search goals · 搜索" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>
      {shown.length === 0 ? (
        <Empty icon={<Flag />} title="Give one role its own preparation room · 为一个职位建立专属准备空间">
          <p>Questions, hints and debriefs are tailored to the goal. · 出题、提示和复盘都会针对这个目标。</p>
          <button className="btn primary" onClick={newGoal}><Plus /> New goal · 新目标</button>
        </Empty>
      ) : shown.map((g) => {
        const count = sessions.filter((s) => s.goal_id === g.goal_id).length;
        return (
          <div key={g.goal_id} className="list-row clickable" onClick={() => open(g.goal_id)}>
            <div className="icon-tile"><Flag /></div>
            <div className="spacer"><div className="title">{g.company} · {g.role}</div><div className="meta">Created {when(g.created_at)} · {count} session{count === 1 ? '' : 's'}</div></div>
            <span className="faint">›</span>
          </div>
        );
      })}
    </div>
  );
}

function GoalPage({ goal, docs, sessions, start, openSession, refresh }: { goal: Goal; docs: Doc[]; sessions: SessionRow[];
  start: (topology: 'general' | 'mock') => void; openSession: (id: string) => void; refresh: () => void }) {
  const [tab, setTab] = useState<'overview' | 'prep' | 'sessions'>('overview');
  const [chosen, setChosen] = useState<string[]>(() => chosenSources(goal.goal_id, docs));
  useEffect(() => setChosen(chosenSources(goal.goal_id, docs)), [goal.goal_id, docs]);
  const toggle = (id: string) => {
    const next = chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id];
    setChosen(next);
    localStorage.setItem(sourcesKey(goal.goal_id), JSON.stringify(next));
  };
  const mine = sessions.filter((s) => s.goal_id === goal.goal_id);
  const latest = mine.find((s) => s.status === 'ready');
  const resume = docs.find((d) => d.kind === 'resume' && chosen.includes(d.document_id));
  const materials = docs.filter((d) => d.kind === 'material' && chosen.includes(d.document_id));
  const importDocs = async (kind: 'resume' | 'material') => {
    const imported = await window.copilot.importDocuments(kind);
    const next = [...chosen, ...imported.map((d) => d.document_id)];
    setChosen(next);
    localStorage.setItem(sourcesKey(goal.goal_id), JSON.stringify(next));
    refresh();
  };
  const sessionList = (rows: SessionRow[]) => rows.length === 0 ? <p className="muted" style={{ padding: '14px 4px' }}>No sessions yet · 还没有会话</p>
    : rows.map((s) => (
      <div key={s.session_id} className="list-row clickable" onClick={() => openSession(s.session_id)}>
        <div className="icon-tile">{s.topology === 'mock' ? <Mic /> : <Radio />}</div>
        <div className="spacer"><div className="title">{s.headline ?? (s.topology === 'mock' ? 'Practice · 练习' : 'Live interview · 实时面试')}</div>
          <div className="meta">{when(s.created_at)}{s.duration_seconds != null ? ` · ${minutes(s.duration_seconds)}` : ''}</div></div>
        {s.status === 'ready' ? <span className="badge good">Debrief · 复盘</span> : s.status === 'preparing' ? <span className="badge warn">Preparing · 生成中</span> : <span className="badge">No report</span>}
      </div>
    ));
  return (
    <div className="page">
      <div className="page-head">
        <div><h1 className={`${goal.company} ${goal.role}`.length > 34 ? 'long' : ''} style={{ marginTop: 0 }}>{goal.company} · {goal.role}</h1>
          <p className="small">{goal.job_description ? goal.job_description.slice(0, 160) + (goal.job_description.length > 160 ? '…' : '') : 'No job description · 未填写职位描述'}</p></div>
        <div className="row"><button className="btn" onClick={() => start('mock')}><Mic /> Practice · 练习</button>
          <button className="btn primary" onClick={() => start('general')}><Radio /> Go Live · 实时面试</button></div>
      </div>
      <div className="tabs">
        {(['overview', 'prep', 'sessions'] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {{ overview: 'Overview · 概览', prep: 'Prep · 准备', sessions: 'Sessions · 会话' }[t]}{t === 'sessions' && <span className="count">{mine.length}</span>}</button>))}
      </div>
      {tab === 'overview' && (
        <div className="two-col">
          <div className="stack">
            <div className="hero">
              <div className="eyebrow">Next focus · 下一步重点</div>
              <p style={{ fontSize: 16, margin: '12px 0 16px' }}>{latest?.headline ?? 'Run a practice session to get your first debrief. · 先做一次语音练习，生成第一份复盘。'}</p>
              <div className="row">
                <button className="btn" onClick={() => start('mock')}><Mic /> Continue prep · 继续练习</button>
                {latest && <button className="link small" onClick={() => openSession(latest.session_id)}>Read the debrief · 查看复盘</button>}
              </div>
            </div>
            <div className="card"><div className="card-head"><h3>Recent sessions · 最近会话</h3>
              <button className="link small" onClick={() => setTab('sessions')}>All sessions · {mine.length}</button></div>
              <div className="card-body">{sessionList(mine.slice(0, 3))}</div></div>
          </div>
          <div className="card">
            <div className="card-head" style={{ paddingBottom: 14 }}><h3>Goal context · 目标资料</h3><button className="link small" onClick={() => setTab('prep')}>Edit · 编辑</button></div>
            <div className="kv"><span>Resume · 简历</span><span>{resume ? resume.filename : 'Not attached · 未添加'}</span></div>
            <div className="kv"><span>Materials · 资料</span><span>{materials.length} attached · 已添加</span></div>
            <div className="kv"><span>Job description · 职位描述</span><span>{goal.job_description ? 'Added · 已填写' : 'None · 无'}</span></div>
          </div>
        </div>
      )}
      {tab === 'prep' && (
        <div className="card">
          <div className="card-head"><h3>Knowledge sources · 知识来源</h3>
            <div className="row"><button className="btn sm" onClick={() => importDocs('resume')}><Upload /> Resume · 简历</button>
              <button className="btn sm" onClick={() => importDocs('material')}><Upload /> Materials · 资料</button></div></div>
          <div className="card-body">
            <p className="muted small">Checked sources ground the practice questions and answer hints for this goal. · 勾选的资料用于这个目标的练习出题和回答提示。</p>
            {docs.length === 0 && <p className="muted">No documents yet · 还没有资料</p>}
            {docs.map((d) => (
              <label key={d.document_id} className="check-row">
                <input type="checkbox" disabled={d.status !== 'ready'} checked={chosen.includes(d.document_id)} onChange={() => toggle(d.document_id)} />
                <FileText size={16} className="faint" /><span className="spacer">{d.filename}</span>
                <span className="badge">{d.kind === 'resume' ? 'Resume' : 'Material'}</span>{docStatus(d)}
              </label>))}
          </div>
        </div>
      )}
      {tab === 'sessions' && <div>{sessionList(mine)}</div>}
    </div>
  );
}

function LibraryPage({ docs, refresh }: { docs: Doc[]; refresh: () => void }) {
  const [tab, setTab] = useState<'resume' | 'material'>('resume');
  const shown = docs.filter((d) => d.kind === tab);
  const upload = async () => { await window.copilot.importDocuments(tab); refresh(); };
  return (
    <div className="page">
      <div className="page-head"><div><h1 style={{ marginTop: 0 }}>Library · 资料库</h1>
        <p>The copilot draws on your resumes and materials. One pool, reused across every goal. · 简历和资料统一管理，每个目标都可以使用。</p></div></div>
      <div className="tabs" style={{ alignItems: 'flex-end' }}>
        <button className={`tab ${tab === 'resume' ? 'active' : ''}`} onClick={() => setTab('resume')}>Resumes · 简历<span className="count">{docs.filter((d) => d.kind === 'resume').length}</span></button>
        <button className={`tab ${tab === 'material' ? 'active' : ''}`} onClick={() => setTab('material')}>Materials · 资料<span className="count">{docs.filter((d) => d.kind === 'material').length}</span></button>
        <span className="spacer" /><button className="btn sm" style={{ marginBottom: 8 }} onClick={upload}><Upload /> Upload a file · 上传</button>
      </div>
      {shown.length === 0 ? (
        <Empty icon={<BookOpen />} title={tab === 'resume' ? 'Add a resume. · 添加简历' : 'Add a material. · 添加资料'}>
          <p>{tab === 'resume' ? 'Answers use only experience from your resume. · 回答只引用简历中的真实经历。'
            : 'Notes, briefs or Q&A docs the copilot uses while you answer. PDF, DOCX, TXT or MD, up to 500 MB. · 笔记、问答准备等，支持 PDF、DOCX、TXT、MD，最大 500 MB。'}</p>
          <button className="btn" onClick={upload}><Upload /> Upload a file · 上传</button>
        </Empty>
      ) : shown.map((d) => (
        <div key={d.document_id} className="list-row">
          <div className="icon-tile"><FileText /></div>
          <div className="spacer"><div className="title">{d.filename}</div>
            <div className="meta">{when(d.created_at)}{d.text_chars ? ` · ${d.text_chars.toLocaleString()} characters` : ''}{d.failure_reason ? ` · ${d.failure_reason}` : ''}</div></div>
          {docStatus(d)}
        </div>))}
    </div>
  );
}

function HistoryPage({ sessions, sessionId, open }: { sessions: SessionRow[]; sessionId?: string; open: (id?: string) => void }) {
  const [report, setReport] = useState<any>(null);
  const [audio, setAudio] = useState<string | null>(null);
  useEffect(() => {
    setReport(null);
    if (sessionId) void window.copilot.request('GET', `/api/v3/sessions/${sessionId}/report`).then((r) => setReport(r.report ?? false));
  }, [sessionId, sessions]);
  useEffect(() => {  // the session recording, played from memory
    setAudio(null);
    if (!sessionId) return;
    let url: string | null = null;
    void window.copilot.loadRecording(sessionId).then((rec) => {
      if (!rec) return;
      url = URL.createObjectURL(new Blob([new Uint8Array(rec.data)], { type: rec.contentType }));
      setAudio(url);
    }).catch(() => undefined);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [sessionId]);
  const row = sessions.find((s) => s.session_id === sessionId);
  if (sessionId && row) {
    return (
      <div className="page">
        <button className="link small" onClick={() => open()}>← History · 历史</button>
        <div className="page-head" style={{ marginTop: 16 }}><div><div className="eyebrow">{row.topology === 'mock' ? 'Practice · 练习' : 'Live · 实时面试'} · {when(row.created_at)}</div>
          <h1 className="long">{report?.overall?.headline ?? `${row.company} · ${row.role}`}</h1><p>{report?.overall?.summary ?? (row.status === 'preparing' ? 'Preparing the debrief… · 正在生成复盘…' : 'No debrief for this session. · 这个会话没有复盘。')}</p></div></div>
        <div className="card" style={{ marginTop: 20, padding: '14px 18px' }}>
          <div className="row"><b>Recording · 录音</b><span className="spacer" />
            {audio ? <audio controls src={audio} style={{ width: 420 }} /> : <span className="muted small">No recording for this session. · 这个会话没有录音。</span>}</div>
        </div>
        {report && (
          <div className="two-col" style={{ marginTop: 24 }}>
            <div className="stack">
              {report.questions?.length > 0 && <div className="card"><div className="card-head"><h3>Questions · 逐题点评</h3></div><div className="card-body prose">
                {report.questions.map((q: any, i: number) => (<div key={i} style={{ padding: '12px 0', borderBottom: '1px solid var(--line)' }}>
                  <span className="badge">{q.quality}</span><p><b>{q.answer_summary}</b></p><p className="muted">{q.feedback}</p>
                  {q.stronger_version && <p><span className="eyebrow">Stronger · 更好的回答</span><br />{q.stronger_version}</p>}</div>))}</div></div>}
              {report.action_plan?.length > 0 && <div className="card"><div className="card-head"><h3>Action plan · 行动计划</h3></div><div className="card-body prose"><ul>
                {report.action_plan.map((x: any, i: number) => <li key={i}><b>{x.title}</b> — {x.how}</li>)}</ul></div></div>}
            </div>
            <div className="stack">
              <div className="card"><div className="card-head"><h3>Strengths · 优势</h3></div><div className="card-body prose"><ul>
                {(report.strengths ?? []).map((x: any, i: number) => <li key={i}><b>{x.label}</b><br /><span className="muted small">{x.evidence}</span></li>)}</ul></div></div>
              <div className="card"><div className="card-head"><h3>To improve · 待改进</h3></div><div className="card-body prose"><ul>
                {(report.improvements ?? []).map((x: any, i: number) => <li key={i}><b>{x.label}</b><br /><span className="muted small">{x.practice_action}</span></li>)}</ul></div></div>
            </div>
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="page">
      <div className="page-head"><div><h1 style={{ marginTop: 0 }}>History · 历史</h1><p>Every practice and live session, with its debrief. · 每次练习和实时面试及其复盘。</p></div></div>
      <div style={{ marginTop: 20 }}>
        {sessions.length === 0 ? <Empty icon={<HistoryIcon />} title="No sessions yet · 还没有会话"><p>Your debriefs appear here after each session. · 每次会话结束后，复盘会显示在这里。</p></Empty>
          : sessions.map((s) => (
            <div key={s.session_id} className="list-row clickable" onClick={() => open(s.session_id)}>
              <div className="icon-tile">{s.topology === 'mock' ? <Mic /> : <Radio />}</div>
              <div className="spacer"><div className="title">{s.company} · {s.role}</div>
                <div className="meta">{s.topology === 'mock' ? 'Practice · 练习' : 'Live · 实时'} · {when(s.created_at)}{s.duration_seconds != null ? ` · ${minutes(s.duration_seconds)}` : ''}{s.headline ? ` · ${s.headline}` : ''}</div></div>
              {s.status === 'ready' ? <span className="badge good">Debrief</span> : s.status === 'preparing' ? <span className="badge warn">Preparing</span>
                : <span className="badge">{s.failure_reason === 'no_content' ? 'No answers' : 'No report'}</span>}
            </div>))}
      </div>
    </div>
  );
}

const SHORTCUT_ROWS: { group: string; hint: string; rows: { ids: (keyof DeviceSettings['shortcuts'])[]; label: string; what: string }[] }[] = [
  { group: 'Interview actions · 面试操作', hint: 'Trigger these during an active session · 会话进行中使用', rows: [
    { ids: ['toggleResults'], label: 'Toggle results panel · 显示/隐藏结果', what: 'Show or hide the answers in the cockpit' },
    { ids: ['solveScreen'], label: 'Solve screen · 截屏解答', what: 'Capture the screen and answer what is on it' },
  ] },
  { group: 'Assistant window · 助手窗口', hint: "Control the assistant window's position and visibility · 控制助手窗口的位置和显示", rows: [
    { ids: ['toggleAssistant'], label: 'Show or hide assistant · 显示/隐藏助手', what: 'Show or hide the cockpit window' },
    { ids: ['moveUp', 'moveDown', 'moveLeft', 'moveRight'], label: 'Move assistant · 移动助手', what: 'Move the cockpit in any direction' },
    { ids: ['grow'], label: 'Grow assistant · 加宽', what: 'Make the cockpit wider' },
    { ids: ['shrink'], label: 'Shrink assistant · 变窄', what: 'Make the cockpit narrower' },
  ] },
];
const keyGlyphs = (accelerator: string) => accelerator.split('+').map((k) => ({ Alt: '⌥', Option: '⌥', Shift: '⇧', Control: '⌃', Ctrl: '⌃', Command: '⌘', Cmd: '⌘',
  CommandOrControl: '⌘', Up: '↑', Down: '↓', Left: '←', Right: '→' } as Record<string, string>)[k] ?? k);
/** Turn a keydown into an Electron accelerator; null until a non-modifier key with a modifier is pressed. */
function accelerator(e: React.KeyboardEvent): string | null {
  const key = { ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right', ' ': 'Space' }[e.key] ?? (e.key.length === 1 ? e.key.toUpperCase() : null);
  if (!key || ['Meta', 'Alt', 'Shift', 'Control'].includes(e.key)) return null;
  const mods = [e.metaKey && 'Command', e.ctrlKey && 'Control', e.altKey && 'Alt', e.shiftKey && 'Shift'].filter(Boolean);
  const code = e.code.startsWith('Key') ? e.code.slice(3) : e.code.startsWith('Digit') ? e.code.slice(5) : key;  // Option changes e.key on macOS
  return mods.length ? [...mods, { Equal: '=', Minus: '-' }[e.code] ?? code].join('+') : null;
}
function contrast(a: string, b: string): number {
  const lum = (hex: string) => {
    const n = Number.parseInt(hex.slice(1), 16);
    const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => { const x = v / 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const [l1, l2] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}
const rgba = (hex: string, alpha: number) => { const n = Number.parseInt(hex.slice(1), 16); return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`; };

function Setting({ title, children, what, icon }: { title: string; what?: React.ReactNode; children?: React.ReactNode; icon?: React.ReactNode }) {
  return <div className="setting">{icon && <div className="icon-tile">{icon}</div>}<div className="what"><b>{title}</b>{what && <span>{what}</span>}</div>{children}</div>;
}
function Switch({ on, onChange, label }: { on: boolean; onChange: (on: boolean) => void; label: string }) {
  return <button className={`switch ${on ? 'on' : ''}`} role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)} />;
}

function SettingsPage({ username, role, signOut }: { username: string; role: string; signOut: () => void }) {
  type Section = 'general' | 'appearance' | 'defaults' | 'privacy' | 'shortcuts' | 'account';
  const [section, setSection] = useState<Section>('general');
  const [device, setDevice] = useState<DeviceSettings | null>(null);
  const [defaults, setDefaults] = useState<DeviceSettings | null>(null);
  const [prefs, setPrefs] = useState<Record<string, any>>({});
  const [consents, setConsents] = useState<{ share_data?: boolean; ai_training?: boolean }>({});
  const [playbooks, setPlaybooks] = useState<{ playbook_id: string; name: string }[]>([]);
  const [permissions, setPermissions] = useState({ microphone: '', screen: '' });
  const [voice, setVoice] = useState<any>(undefined);
  const [accounts, setAccounts] = useState<{ username: string; role: string }[]>([]);
  const [info, setInfo] = useState({ version: '', electron: '', platform: '' });
  const [recording, setRecording] = useState<string | null>(null);
  const [message, setMessage] = useState('');
  useEffect(() => {
    void window.copilot.getSettings().then(setDevice);
    window.copilot.onSettings(setDevice);  // changed elsewhere (another window, a shortcut)
    void window.copilot.defaultSettings().then(setDefaults);
    void window.copilot.appInfo().then(setInfo);
    void window.copilot.request('GET', '/api/v3/me/prefs').then(setPrefs);
    void window.copilot.request('GET', '/api/v3/me/consents').then(setConsents);
    void window.copilot.request('GET', '/api/v3/playbooks').then((r) => setPlaybooks(r.playbooks ?? []));
    void window.copilot.request('GET', '/api/v3/voice-sample').then((r) => setVoice(r.sample ?? null)).catch(() => setVoice(null));
    if (role === 'admin') void auth('accounts').then(setAccounts).catch(() => undefined);
  }, [role]);
  useEffect(() => { void window.copilot.permissions().then(setPermissions); }, [section]);
  const update = async (patch: Partial<DeviceSettings>) => setDevice(await window.copilot.setSettings(patch));
  const savePrefs = async (patch: Record<string, unknown>) => setPrefs(await window.copilot.request('PUT', '/api/v3/me/prefs', patch));
  const saveConsents = async (patch: Record<string, unknown>) => setConsents(await window.copilot.request('PUT', '/api/v3/me/consents', patch));
  const permission = (value: string) => value === 'granted' ? <span className="badge good">✓ Granted · 已授权</span> : <span className="badge warn">{value === 'denied' ? 'Denied · 已拒绝' : 'Not set · 未设置'}</span>;
  const sections: [Section, string][] = [['general', 'General · 通用'], ['appearance', 'Appearance · 外观'], ['defaults', 'Defaults · 默认'],
    ['privacy', 'Privacy & Stealth · 隐私与隐身'], ['shortcuts', 'Shortcuts · 快捷键'], ['account', 'Account · 账号']];
  if (!device || !defaults) return null;
  const ratio = contrast(device.text, device.background);
  return (
    <div className="page settings">
      <nav>
        {sections.map(([s, label]) => <button key={s} className={section === s ? 'active' : ''} onClick={() => setSection(s)}>{label}</button>)}
        <p className="faint" style={{ font: '11px var(--mono)', marginTop: 24 }}>Interview Realtime Copilot v{info.version}<br />Electron {info.electron}</p>
      </nav>
      <div>
        {section === 'general' && <>
          <h2>General · 通用</h2>
          <h4 className="setting-group">Startup · 启动</h4>
          <Setting title="Launch at login · 开机启动" what="Open the app automatically when you sign in to this computer. · 登录电脑时自动打开。">
            <Switch label="Launch at login" on={device.launchAtLogin} onChange={(on) => update({ launchAtLogin: on })} /></Setting>
          <h4 className="setting-group">App updates · 应用更新</h4>
          <Setting title={`Interview Realtime Copilot ${info.version}`} what="Updates ship with packaged builds and are not available in development. · 打包发布版才会提供更新，开发版不可用。">
            <button className="btn sm" disabled>Check for updates · 检查更新</button></Setting>
        </>}
        {section === 'appearance' && <>
          <h2>Appearance · 外观</h2>
          <h4 className="setting-group">Cockpit · 面试窗口</h4>
          <p className="muted small">How the assistant panel looks during a live session. These settings stay on this device and never change on their own. · 只影响面试窗口，只保存在本机。</p>
          <div className="checker">
            <div className="preview" style={{ background: rgba(device.background, device.opacity), color: device.text }}>
              <div className="preview-head"><span className="dot" /> <b style={{ font: '600 12px var(--mono)' }}>Listening</b></div>
              <div style={{ padding: '12px 14px' }}><div>Start with the outcome, then the two decisions that got you there.</div>
                <div style={{ opacity: .62, marginTop: 8, fontSize: 13 }}>Secondary detail sits at this weight.</div></div>
              <div className="preview-foot"><span>Solve screen</span><span>00:07</span></div>
            </div>
          </div>
          <Setting title="Opacity · 不透明度" what="How much of the meeting behind the panel shows through. Ships at 80%; below 70% the answer text stops surviving real meeting content, so that is the floor. · 默认 80%，最低 70%。">
            <input type="range" min={70} max={100} value={Math.round(device.opacity * 100)} onChange={(e) => update({ opacity: Number(e.target.value) / 100 })} style={{ width: 180 }} />
            <span className="faint" style={{ font: '12px var(--mono)', width: 40 }}>{Math.round(device.opacity * 100)}%</span></Setting>
          {(['background', 'text'] as const).map((key) => (
            <Setting key={key} title={key === 'background' ? 'Background · 背景色' : 'Text · 文字颜色'}
              what={key === 'background' ? "The panel's base colour. · 面板底色。" : 'The base colour for text; the three text weights are derived from it. · 文字基色，三级文字层次由它派生。'}>
              <input type="color" value={device[key]} onChange={(e) => update({ [key]: e.target.value })} style={{ width: 36, height: 32, border: 0, background: 'none' }} />
              <input className="input" style={{ width: 110, fontFamily: 'var(--mono)' }} defaultValue={device[key]} key={device[key]}
                onBlur={(e) => /^#[0-9a-f]{6}$/i.test(e.target.value) && update({ [key]: e.target.value })} />
              <button className="btn ghost sm" disabled={device[key] === defaults[key]} onClick={() => update({ [key]: defaults[key] })}>Use default · 恢复默认</button>
            </Setting>))}
          {ratio < 4.5 && <p className="error">Low contrast ({ratio.toFixed(1)}:1). Text may be hard to read during a session; aim for at least 4.5:1. · 对比度过低，面试时可能看不清。</p>}
        </>}
        {section === 'defaults' && <>
          <h2>Defaults · 默认设置</h2>
          <h4 className="setting-group">Launch defaults · 启动默认值</h4>
          <p className="muted small">What a fresh session starts from. · 新会话使用的默认值。</p>
          <Setting title="Answer language · 回答语言" what="The language the copilot answers in and transcribes. · 转写和回答使用的语言。">
            <select className="select" style={{ width: 190 }} value={prefs.default_language ?? ''} onChange={(e) => savePrefs({ default_language: e.target.value || null })}>
              <option value="">System default · 跟随系统</option><option value="en-US">English</option><option value="zh-CN">中文（普通话）</option>
              <option value="ja-JP">日本語</option><option value="ko-KR">한국어</option><option value="de-DE">Deutsch</option><option value="fr-FR">Français</option><option value="es-ES">Español</option>
            </select></Setting>
          <Setting title="Coding language · 编程语言" what="The default language for code the copilot writes. · 生成代码时默认使用的语言。">
            <select className="select" style={{ width: 190 }} value={prefs.default_coding_language ?? ''} onChange={(e) => savePrefs({ default_coding_language: e.target.value || null })}>
              <option value="">Any · 不限</option>{['Python', 'C++', 'C', 'Java', 'JavaScript', 'TypeScript', 'Go', 'Rust', 'MATLAB'].map((l) => <option key={l}>{l}</option>)}
            </select></Setting>
          <Setting title="Default playbook · 默认回答风格" what="How the copilot shows up when a goal has no choice yet. · 目标未单独设置时使用的回答风格。">
            <select className="select" style={{ width: 190 }} value={prefs.default_playbook_id ?? ''} onChange={(e) => savePrefs({ default_playbook_id: e.target.value || null })}>
              <option value="">Platform default · 默认</option>{playbooks.map((p) => <option key={p.playbook_id} value={p.playbook_id}>{p.name}</option>)}
            </select></Setting>
        </>}
        {section === 'privacy' && <>
          <h2>Privacy &amp; Stealth · 隐私与隐身</h2>
          <h4 className="setting-group">Stealth · 隐身</h4>
          <p className="muted small">Keep the cockpit out of view while you interview. · 面试时不让别人看到面试窗口。</p>
          <Setting title="Hide from screen sharing · 共享屏幕时隐藏" what="The cockpit never appears in a shared screen or recording. · 共享屏幕或录屏中都不会出现面试窗口。">
            <Switch label="Hide from screen sharing" on={device.stealth} onChange={(on) => update({ stealth: on })} /></Setting>
          {!device.stealth && <p className="error">While this is off, anyone you share your screen with can see the cockpit, and recordings will include it. · 关闭后，你共享屏幕时对方能看到面试窗口，录屏也会录进去。</p>}
          <h4 className="setting-group">System access · 系统权限</h4>
          <p className="muted small">Needed to hear the interview and read the shared screen. Capture runs only during an active session. · 只在会话进行中采集。</p>
          <Setting icon={<Mic />} title="Microphone · 麦克风" what="Required for hearing your voice during interviews. · 用于识别你的回答。">{permission(permissions.microphone)}
            <button className="btn sm" disabled={permissions.microphone === 'granted'} onClick={() => window.copilot.requestMicrophone().then(() => window.copilot.permissions().then(setPermissions))}>
              {permissions.microphone === 'granted' ? 'Granted' : 'Grant · 授权'}</button></Setting>
          <Setting icon={<Monitor />} title="Screen & System Audio · 屏幕与系统录音" what="Required to hear the interviewer in Live mode and for screen capture. · Live 模式听面试官、截屏解答都需要。">{permission(permissions.screen)}
            <button className="btn sm" disabled={permissions.screen === 'granted'} onClick={() => window.copilot.openScreenSettings()}>{permissions.screen === 'granted' ? 'Granted' : 'Open settings · 打开设置'}</button></Setting>
          <h4 className="setting-group">Screen capture · 屏幕读取</h4>
          <Setting title="Auto-capture · 自动截屏" what="When a coding or system-design question needs what is on your screen, capture it to read the content. Captures stay hidden from the interviewer and only happen during an active session. · 遇到编程或系统设计题时自动读取屏幕，只在会话中进行。">
            <Switch label="Auto-capture" on={device.autoCapture} onChange={(on) => update({ autoCapture: on })} /></Setting>
          <h4 className="setting-group">Voice &amp; memory · 声音与记忆</h4>
          <Setting title="Voice sample · 声音样本" what={voice ? `Saved ${new Date(voice.created_at ?? voice.updated_at ?? Date.now()).toLocaleDateString()} · 已保存` : 'No voice sample is saved. · 尚未保存声音样本。'}>
            {voice && <button className="btn sm" onClick={() => window.copilot.request('DELETE', '/api/v3/voice-sample').then(() => setVoice(null))}>Delete · 删除</button>}</Setting>
          <Setting title="Erase its memory · 清除记忆" what="Deletes learned facts, preferences, strengths and weaknesses across every goal. Sessions, debriefs and documents stay. · 清除学到的偏好和优劣势，会话、复盘和资料保留。">
            <button className="btn sm" onClick={async () => { if (confirm('Erase everything the coach has learned? · 确定清除全部记忆？')) { await window.copilot.request('DELETE', '/api/v3/memory'); setMessage('Memory erased. · 已清除。'); } }}>Erase everything… · 全部清除…</button></Setting>
          <h4 className="setting-group">Data authorization · 数据授权</h4>
          <Setting title="Share data · 共享数据" what="Allow sharing your data with service providers that help operate and improve the product. · 允许与协助运营和改进产品的服务商共享数据。">
            <Switch label="Share data" on={!!consents.share_data} onChange={(on) => saveConsents({ share_data: on })} /></Setting>
          <Setting title="AI training · AI 训练" what="Allow your data to be used to improve the AI. · 允许用你的数据改进 AI。">
            <Switch label="AI training" on={!!consents.ai_training} onChange={(on) => saveConsents({ ai_training: on })} /></Setting>
          <p className="faint small">Turning a switch off applies to new data from that point on. · 关闭后只影响之后的新数据。</p>
          {message && <p className="small">{message}</p>}
        </>}
        {section === 'shortcuts' && <>
          <h2>Shortcuts · 快捷键</h2>
          <p className="muted small">These shortcuts are active during a session. No window-switching needed. Click any shortcut to reassign it. · 会话进行中有效，点击按键可重新设置。</p>
          {SHORTCUT_ROWS.map((group) => (<div key={group.group}>
            <h4 className="setting-group">{group.group}</h4><p className="muted small" style={{ marginTop: -4 }}>{group.hint}</p>
            {group.rows.map((row) => (
              <Setting key={row.label} title={row.label} what={row.what}>
                <span className="row" style={{ gap: 6 }}>{row.ids.map((id) => (
                  <button key={id} className={`keys ${recording === id ? 'recording' : ''}`} onClick={() => setRecording(id)}
                    onKeyDown={(e) => { if (recording !== id) return; e.preventDefault(); if (e.key === 'Escape') return setRecording(null);
                      const key = accelerator(e); if (key) { void update({ shortcuts: { ...device.shortcuts, [id]: key } }); setRecording(null); } }}
                    onBlur={() => recording === id && setRecording(null)}>
                    {recording === id ? 'Press keys… · 按下新组合' : keyGlyphs(device.shortcuts[id]).map((k, i) => <kbd key={i}>{k}</kbd>)}
                  </button>))}</span>
              </Setting>))}
          </div>))}
          <div style={{ marginTop: 18 }}><button className="btn sm" onClick={() => update({ shortcuts: defaults.shortcuts })}>Reset to defaults · 恢复默认</button></div>
        </>}
        {section === 'account' && <>
          <h2>Account · 账号</h2>
          <h4 className="setting-group">Account · 账号</h4>
          <Setting title={username} what={role === 'admin' ? 'Local administrator · 本机管理员' : 'Local account · 本机账号'}>
            <button className="btn sm" onClick={signOut}>Sign out · 退出登录</button></Setting>
          <h4 className="setting-group">Local workspace · 本地工作区</h4>
          <p className="muted small">This computer stores your workspace: goals, documents, sessions and debriefs. Live AI uses the OpenAI project configured for the engine. · 目标、资料、会话和复盘都保存在本机。</p>
          <Setting title="Delete account · 删除账号" what="Account deletion is unavailable in this local build. · 本地版暂不支持删除账号。"><button className="btn sm" disabled>Delete account… · 删除账号…</button></Setting>
          {role === 'admin' && accounts.length > 0 && <>
            <h4 className="setting-group">Local accounts · 本机账号</h4>
            {accounts.map((a) => <div key={a.username} className="list-row"><div className="avatar">{a.username[0]?.toUpperCase()}</div><span className="spacer">{a.username}</span><span className="badge">{a.role}</span></div>)}
          </>}
        </>}
      </div>
    </div>
  );
}

// ── preflight ─────────────────────────────────────────────────────────────
const LANGUAGES: [string, string][] = [['en-US', 'English'], ['zh-CN', '中文（普通话）'], ['ja-JP', '日本語'], ['ko-KR', '한국어'], ['de-DE', 'Deutsch'], ['fr-FR', 'Français'], ['es-ES', 'Español']];
const CODING = ['Python', 'C++', 'C', 'Java', 'JavaScript', 'TypeScript', 'Go', 'Rust', 'MATLAB'];

/** Microphone level test, only while the user asks for it. */
function MicTest() {
  const [level, setLevel] = useState<number | null>(null);
  const [error, setError] = useState('');
  const stop = useMemo(() => ({ current: () => {} }), []);
  useEffect(() => () => stop.current(), [stop]);
  const start = async () => {
    setError('');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      context.createMediaStreamSource(stream).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      let frame = 0;
      const tick = () => { analyser.getByteTimeDomainData(data); let peak = 0; for (const v of data) peak = Math.max(peak, Math.abs(v - 128)); setLevel(Math.min(1, peak / 64)); frame = requestAnimationFrame(tick); };
      tick();
      stop.current = () => { cancelAnimationFrame(frame); stream.getTracks().forEach((t) => t.stop()); void context.close(); setLevel(null); };
    } catch (e) { setError((e as Error).message); }
  };
  return (
    <span className="row" style={{ gap: 8 }}>
      {level === null ? <button className="btn sm" onClick={start}>Test microphone · 测试麦克风</button>
        : <><span className="level"><span style={{ width: `${Math.round(level * 100)}%` }} /></span><button className="btn ghost sm" onClick={() => stop.current()}>Stop · 停止</button></>}
      {error && <span className="error">{error}</span>}
    </span>
  );
}

function Preflight({ goal, docs, initial, onClose, onStarted }: { goal: Goal; docs: Doc[]; initial: 'general' | 'mock'; onClose: () => void; onStarted: () => void }) {
  const [topology, setTopology] = useState(initial);
  const [setup, setSetup] = useState<'computer' | 'room'>('computer');
  const [practiceMode, setPracticeMode] = useState('sequential');
  const [chosen, setChosen] = useState(() => chosenSources(goal.goal_id, docs));
  const [prefs, setPrefs] = useState<Record<string, any> | null>(null);
  const [language, setLanguage] = useState('');
  const [coding, setCoding] = useState('');
  const [playbook, setPlaybook] = useState('');
  const [playbooks, setPlaybooks] = useState<{ playbook_id: string; name: string }[]>([]);
  const [permissions, setPermissions] = useState({ microphone: '', screen: '' });
  const [systemAudio, setSystemAudio] = useState(true);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  useEffect(() => {
    void window.copilot.request('GET', '/api/v3/me/prefs').then(setPrefs);
    void window.copilot.request('GET', '/api/v3/playbooks').then((r) => setPlaybooks(r.playbooks ?? []));
    void window.copilot.permissions().then(setPermissions);
    void window.copilot.appInfo().then((i) => setSystemAudio(i.systemAudio));
  }, []);
  const ready = docs.filter((d) => d.status === 'ready');
  const toggle = (id: string) => setChosen((c) => c.includes(id) ? c.filter((x) => x !== id) : [...c, id]);
  const defaultLanguage = prefs?.default_language || (navigator.language.startsWith('zh') ? 'zh-CN' : 'en-US');
  const micOk = permissions.microphone === 'granted';
  const live = topology === 'general';
  const blocked = !micOk ? 'Microphone access is required for this session. · 本次会话需要麦克风权限。'
    : live && !systemAudio ? 'Computer audio capture is not available on this computer. · 本机无法采集电脑声音。' : '';
  const start = async () => {
    setError('');
    setStarting(true);
    localStorage.setItem(sourcesKey(goal.goal_id), JSON.stringify(chosen));
    try {
      await window.copilot.startSession({ topology, goalId: goal.goal_id, documentIds: chosen, language: language || defaultLanguage,
        codingLanguage: coding || prefs?.default_coding_language || null, playbookId: playbook || prefs?.default_playbook_id || null,
        ...(topology === 'mock' ? { practiceMode } : {}) });
      onStarted();
    } catch (e) { setError((e as Error).message); setStarting(false); }
  };
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal preflight" onClick={(e) => e.stopPropagation()}>
        <div className="eyebrow">Preflight · 开始前检查</div>
        <h2 style={{ margin: '8px 0 4px' }}>{goal.company} · {goal.role}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>These choices apply to this session only; your goal and defaults stay as they are. · 只影响本次会话，不改目标和默认设置。</p>
        <div className="segmented" style={{ margin: '6px 0 4px' }}>
          <button className={live ? 'active' : ''} onClick={() => setTopology('general')}>Live interview · 实时面试</button>
          <button className={!live ? 'active' : ''} onClick={() => setTopology('mock')}>Practice · 语音练习</button>
        </div>

        {live ? <>
          <h4 className="setting-group">Interview setup · 面试方式</h4>
          <div className="choice-grid">
            <button className={`choice ${setup === 'computer' ? 'active' : ''}`} onClick={() => setSetup('computer')}>
              <Monitor size={18} /><b>This computer · 本机通话</b><span>Zoom, Teams, Meet… Captures your microphone and the meeting audio. · 采集你的麦克风和会议声音。</span></button>
            <button className="choice" disabled title="Coming soon · 即将支持">
              <Mic size={18} /><b>Phone or in person · 电话或面对面</b><span>Needs voice separation in one microphone; coming soon. · 需要在同一个麦克风里区分说话人，即将支持。</span></button>
          </div>
        </> : <>
          <h4 className="setting-group">Practice scenario · 练习方式</h4>
          <div className="segmented">
            {[['sequential', 'Prepared, in order · 顺序'], ['random', 'Prepared, random · 随机'], ['ai', 'AI improvises · AI 临场']].map(([m, label]) => (
              <button key={m} className={practiceMode === m ? 'active' : ''} onClick={() => setPracticeMode(m)}>{label}</button>))}
          </div>
          <p className="faint small">The interviewer speaks; answer out loud. You can switch questions in the cockpit. · 面试官用语音提问，你口头回答；面试中可在题目栏切换。</p>
        </>}

        <h4 className="setting-group">Knowledge sources · 知识来源</h4>
        {ready.length === 0 ? <p className="muted small">No prepared documents. Add a resume or materials in the Library. · 资料库里还没有可用资料。</p>
          : <div className="sources">{ready.map((d) => (
            <label key={d.document_id} className="check-row"><input type="checkbox" checked={chosen.includes(d.document_id)} onChange={() => toggle(d.document_id)} />
              <FileText size={15} className="faint" /><span className="spacer">{d.filename}</span><span className="badge">{d.kind === 'resume' ? 'Resume' : 'Material'}</span></label>))}</div>}

        <h4 className="setting-group">Answers · 回答</h4>
        <div className="grid3">
          <label className="field"><span>Language · 语言</span>
            <select className="select" value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="">Account default · 默认（{LANGUAGES.find(([c]) => c === defaultLanguage)?.[1] ?? defaultLanguage}）</option>
              {LANGUAGES.map(([c, l]) => <option key={c} value={c}>{l}</option>)}</select></label>
          <label className="field"><span>Coding language · 编程语言</span>
            <select className="select" value={coding} onChange={(e) => setCoding(e.target.value)}>
              <option value="">Account default · 默认{prefs?.default_coding_language ? `（${prefs.default_coding_language}）` : ''}</option>
              {CODING.map((c) => <option key={c}>{c}</option>)}</select></label>
          <label className="field"><span>Playbook · 回答风格</span>
            <select className="select" value={playbook} onChange={(e) => setPlaybook(e.target.value)}>
              <option value="">Account default · 默认</option>{playbooks.map((p) => <option key={p.playbook_id} value={p.playbook_id}>{p.name}</option>)}</select></label>
        </div>

        <h4 className="setting-group">Audio check · 音频检查</h4>
        <div className="setting"><div className="icon-tile"><Mic /></div><div className="what"><b>Microphone · 麦克风</b>
          <span>{micOk ? 'Hears your answers. · 用于识别你的回答。' : 'Grant microphone access to continue. · 请先授权麦克风。'}</span></div>
          {micOk ? <MicTest /> : <button className="btn sm" onClick={() => window.copilot.requestMicrophone().then(() => window.copilot.permissions().then(setPermissions))}>Grant microphone access · 授权</button>}</div>
        {live && <div className="setting"><div className="icon-tile"><Monitor /></div><div className="what"><b>Computer audio · 电脑声音</b>
          <span>{systemAudio ? 'Hears the interviewer from the meeting app. macOS asks once for System Audio Recording when the session starts. · 用于听到会议里的面试官，首次开始时 macOS 会询问一次。'
            : 'Not available on this computer. · 本机不支持。'}</span></div>
          {systemAudio ? <span className="badge good">Ready · 就绪</span> : <span className="badge bad">Unavailable</span>}</div>}
        <p className="faint small">Microphone and meeting audio start after you press Start. · 按下开始后才开始采集声音。</p>

        {(error || blocked) && <p className="error">{error || blocked}</p>}
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
          <button className="btn ghost" onClick={onClose}>Cancel · 取消</button>
          <button className="btn primary" disabled={!!blocked || starting || !prefs} onClick={start}>
            {starting ? 'Starting… · 正在开始…' : live ? 'Start session · 开始面试' : 'Start practice session · 开始练习'}</button>
        </div>
      </div>
    </div>
  );
}

// ── shell ─────────────────────────────────────────────────────────────────
function Shell({ username, role, signOut }: { username: string; role: string; signOut: () => void }) {
  const [route, setRoute] = useState<Route>({ page: 'goals' });
  const [goals, setGoals] = useState<Goal[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    const [g, d, s] = await Promise.all(['/api/v3/goals', '/api/v3/documents', '/api/v3/sessions'].map((p) => window.copilot.request('GET', p)));
    setGoals([...g.goals].sort((a: Goal, b: Goal) => b.created_at.localeCompare(a.created_at)));
    setDocs(d.documents);
    setSessions(s.sessions);
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {  // documents and debriefs are prepared in the background
    if (!docs.some((d) => d.status === 'preparing') && !sessions.some((s) => s.status === 'preparing')) return;
    const timer = setTimeout(() => void refresh(), 2000);
    return () => clearTimeout(timer);
  }, [docs, sessions, refresh]);
  useEffect(() => { const onFocus = () => void refresh(); window.addEventListener('focus', onFocus); return () => window.removeEventListener('focus', onFocus); }, [refresh]);

  const goal = route.page === 'goal' ? goals.find((g) => g.goal_id === route.goalId) : undefined;
  const liveGoal = goal ?? goals[0];
  const [preflight, setPreflight] = useState<{ goal: Goal; topology: 'general' | 'mock' } | null>(null);
  const start = (topology: 'general' | 'mock', target = liveGoal) => {
    setError('');
    if (!target) return setCreating(true);
    setPreflight({ goal: target, topology });
  };
  const title = { goals: 'Goals · 目标', goal: goal ? `${goal.company} · ${goal.role}` : 'Goal', library: 'Library · 资料库', history: 'History · 历史', settings: 'Settings · 设置' }[route.page];
  const nav = useMemo(() => [
    { page: 'library' as const, label: 'Library · 资料库', icon: <BookOpen /> },
    { page: 'history' as const, label: 'History · 历史', icon: <HistoryIcon /> },
    { page: 'settings' as const, label: 'Settings · 设置', icon: <SettingsIcon /> },
  ], []);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="logo">IR</div></div>
        <div className="section">
          <div className="side-head" onClick={() => setRoute({ page: 'goals' })}><span>Goals · 目标</span><span className="faint">{goals.length} ›</span></div>
          <button className="btn side-new" onClick={() => setCreating(true)}><Plus /> New goal · 新目标</button>
          <div className="side-label eyebrow">Up next · 当前目标</div>
        </div>
        <div className="side-goals">
          {goals.length === 0 ? <div style={{ padding: '4px 10px' }}><b className="small">No current goals</b><p className="small muted" style={{ margin: '4px 0' }}>Create one when an interview is on your horizon. · 有面试安排时创建一个。</p></div>
            : goals.map((g) => (
              <button key={g.goal_id} className={`side-goal ${route.page === 'goal' && route.goalId === g.goal_id ? 'active' : ''}`} onClick={() => setRoute({ page: 'goal', goalId: g.goal_id })}>
                <div className="title">{g.company}</div><div className="meta">{g.role}</div></button>))}
        </div>
        <div className="side-nav">{nav.map((n) => (
          <button key={n.page} className={route.page === n.page ? 'active' : ''} onClick={() => setRoute({ page: n.page } as Route)}>{n.icon}{n.label}</button>))}</div>
        <div className="side-user"><div className="avatar">{username[0]?.toUpperCase()}</div><span className="spacer">{username}</span><span className="badge">Local</span></div>
      </aside>
      <main className="main">
        <div className="topbar">
          <span className="crumb">{title}</span><span className="spacer" />
          {error && <span className="error">{error}</span>}
          {route.page !== 'goal' && <button className="btn primary" onClick={() => start('general')}><Radio /> Go Live · 实时面试</button>}
          <button className="btn ghost" title="Help · 帮助"><CircleHelp /></button>
        </div>
        <div className="content">
          {route.page === 'goals' && <GoalsPage goals={goals} docs={docs} sessions={sessions} open={(id) => setRoute({ page: 'goal', goalId: id })} newGoal={() => setCreating(true)} />}
          {route.page === 'goal' && goal && <GoalPage goal={goal} docs={docs} sessions={sessions} start={(t) => start(t, goal)} refresh={refresh}
            openSession={(id) => setRoute({ page: 'history', sessionId: id })} />}
          {route.page === 'library' && <LibraryPage docs={docs} refresh={refresh} />}
          {route.page === 'history' && <HistoryPage sessions={sessions} sessionId={route.sessionId} open={(id) => setRoute({ page: 'history', sessionId: id })} />}
          {route.page === 'settings' && <SettingsPage username={username} role={role} signOut={signOut} />}
        </div>
      </main>
      {preflight && <Preflight goal={preflight.goal} docs={docs} initial={preflight.topology} onClose={() => setPreflight(null)}
        onStarted={() => { setPreflight(null); void refresh(); }} />}
      {creating && <NewGoal onClose={() => setCreating(false)} onCreated={(g) => { setCreating(false); void refresh(); setRoute({ page: 'goal', goalId: g.goal_id }); }} />}
    </div>
  );
}

function App() {
  const [user, setUser] = useState<{ username: string; role: string } | null | undefined>(undefined);
  useEffect(() => { auth('session').then((s) => setUser(s?.account ?? null)).catch(() => setUser(null)); }, []);
  if (user === undefined) return <div className="auth"><span className="muted">Starting… · 正在启动…</span></div>;
  if (!user) return <SignIn onSignedIn={(username) => setUser({ username, role: 'member' })} />;
  return <Shell username={user.username} role={user.role} signOut={() => void auth('sign-out', {}).then(() => setUser(null))} />;
}

createRoot(document.getElementById('root')!).render(<App />);
