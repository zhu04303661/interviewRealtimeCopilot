// Main window: account, goals, library, history and settings.
import { BookOpen, CircleHelp, FileText, Flag, History as HistoryIcon, Mic, Plus, Radio, Search, Settings as SettingsIcon, Upload } from 'lucide-react';
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
  useEffect(() => {
    setReport(null);
    if (sessionId) void window.copilot.request('GET', `/api/v3/sessions/${sessionId}/report`).then((r) => setReport(r.report ?? false));
  }, [sessionId, sessions]);
  const row = sessions.find((s) => s.session_id === sessionId);
  if (sessionId && row) {
    return (
      <div className="page">
        <button className="link small" onClick={() => open()}>← History · 历史</button>
        <div className="page-head" style={{ marginTop: 16 }}><div><div className="eyebrow">{row.topology === 'mock' ? 'Practice · 练习' : 'Live · 实时面试'} · {when(row.created_at)}</div>
          <h1 className="long">{report?.overall?.headline ?? `${row.company} · ${row.role}`}</h1><p>{report?.overall?.summary ?? (row.status === 'preparing' ? 'Preparing the debrief… · 正在生成复盘…' : 'No debrief for this session. · 这个会话没有复盘。')}</p></div></div>
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

function SettingsPage({ username, signOut }: { username: string; signOut: () => void }) {
  const [section, setSection] = useState<'general' | 'permissions' | 'account'>('general');
  const [language, setLanguage] = useState(localStorage.getItem('language') ?? 'en-US');
  const [permissions, setPermissions] = useState({ microphone: '', screen: '' });
  useEffect(() => { void window.copilot.permissions().then(setPermissions); }, [section]);
  const state = (value: string) => value === 'granted' ? <span className="badge good">Allowed · 已允许</span> : <span className="badge warn">{value || '…'}</span>;
  return (
    <div className="page settings">
      <nav>{(['general', 'permissions', 'account'] as const).map((s) => (
        <button key={s} className={section === s ? 'active' : ''} onClick={() => setSection(s)}>{{ general: 'General · 通用', permissions: 'Permissions · 权限', account: 'Account · 账号' }[s]}</button>))}</nav>
      <div>
        {section === 'general' && <><h2 style={{ marginTop: 0 }}>General · 通用</h2>
          <div className="setting"><div className="what"><b>Interview language · 面试语言</b><span>Language the interviewer speaks and transcripts expect. · 面试官说话和转写使用的语言。</span></div>
            <select className="select" style={{ width: 180 }} value={language} onChange={(e) => { setLanguage(e.target.value); localStorage.setItem('language', e.target.value); }}>
              <option value="en-US">English</option><option value="zh-CN">中文</option></select></div></>}
        {section === 'permissions' && <><h2 style={{ marginTop: 0 }}>Permissions · 权限</h2>
          <div className="setting"><div className="what"><b>Microphone · 麦克风</b><span>Hears your answers. · 用于识别你的回答。</span></div>{state(permissions.microphone)}
            {permissions.microphone !== 'granted' && <button className="btn sm" onClick={() => window.copilot.requestMicrophone().then(() => window.copilot.permissions().then(setPermissions))}>Allow · 允许</button>}</div>
          <div className="setting"><div className="what"><b>Screen &amp; system audio · 屏幕与系统录音</b><span>Hears the interviewer in Live mode. · Live 模式下用于听到面试官。</span></div>{state(permissions.screen)}
            {permissions.screen !== 'granted' && <button className="btn sm" onClick={() => window.copilot.openScreenSettings()}>Open settings · 打开设置</button>}</div></>}
        {section === 'account' && <><h2 style={{ marginTop: 0 }}>Account · 账号</h2>
          <div className="setting"><div className="what"><b>{username}</b><span>Local account on this computer. · 本机账号。</span></div><button className="btn sm" onClick={signOut}>Sign out · 退出</button></div></>}
      </div>
    </div>
  );
}

// ── shell ─────────────────────────────────────────────────────────────────
function Shell({ username, signOut }: { username: string; signOut: () => void }) {
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
  const start = async (topology: 'general' | 'mock', target = liveGoal) => {
    setError('');
    if (!target) return setCreating(true);
    if ((await window.copilot.permissions()).microphone !== 'granted' && !(await window.copilot.requestMicrophone())) {
      return setError('Microphone access is required. · 需要麦克风权限。');
    }
    try {
      await window.copilot.startSession({ topology, goalId: target.goal_id, documentIds: chosenSources(target.goal_id, docs), language: localStorage.getItem('language') ?? 'en-US' });
    } catch (e) { setError((e as Error).message); }
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
          {route.page === 'settings' && <SettingsPage username={username} signOut={signOut} />}
        </div>
      </main>
      {creating && <NewGoal onClose={() => setCreating(false)} onCreated={(g) => { setCreating(false); void refresh(); setRoute({ page: 'goal', goalId: g.goal_id }); }} />}
    </div>
  );
}

function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined);
  useEffect(() => { auth('session').then((s) => setUser(s?.account.username ?? null)).catch(() => setUser(null)); }, []);
  if (user === undefined) return <div className="auth"><span className="muted">Starting… · 正在启动…</span></div>;
  if (!user) return <SignIn onSignedIn={setUser} />;
  return <Shell username={user} signOut={() => void auth('sign-out', {}).then(() => setUser(null))} />;
}

createRoot(document.getElementById('root')!).render(<App />);
