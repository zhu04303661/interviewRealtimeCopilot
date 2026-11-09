// Main window: account, goals, materials and starting an interview.
import { useCallback, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const OWNER = 'main';
type Goal = { goal_id: string; role: string; company: string; job_description?: string };
type Doc = { document_id: string; filename: string; kind: string; status: string; text_chars?: number };

async function auth(path: string, body?: Record<string, unknown>) {
  const result = body
    ? await window.copilot.request('POST', `/local/auth/${path}`, { owner: OWNER, ...body })
    : await window.copilot.request('GET', `/local/auth/${path}?owner=${OWNER}`);
  if (!result.ok) throw new Error(result.error);
  return result.value;
}

function SignIn({ onSignedIn }: { onSignedIn: (name: string) => void }) {
  const [mode, setMode] = useState<'sign-in' | 'register'>('sign-in');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const submit = async () => {
    setError('');
    try {
      const session = await auth(mode, { username, password });
      onSignedIn(session.account.username);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="page" style={{ maxWidth: 420, marginTop: 80 }}>
      <h1>Interview Realtime Copilot</h1>
      <div className="card">
        <h2>{mode === 'sign-in' ? 'Sign in · 登录' : 'Create account · 注册'}</h2>
        <label>Username · 用户名</label>
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        <label>Password · 密码</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()} />
        {error && <p className="error small">{error}</p>}
        <div className="row" style={{ marginTop: 14 }}>
          <button className="primary" onClick={submit}>{mode === 'sign-in' ? 'Sign in' : 'Create account'}</button>
          <button className="ghost" onClick={() => setMode(mode === 'sign-in' ? 'register' : 'sign-in')}>
            {mode === 'sign-in' ? 'Create an account · 注册' : 'I have an account · 已有账号'}
          </button>
        </div>
      </div>
    </div>
  );
}

type SessionRow = { session_id: string; role: string; company: string; topology: string; created_at: string; duration_seconds: number | null;
  status: string; headline?: string; failure_reason?: string | null };

/** Past sessions and their Debriefs (generated after each session ends). */
function History() {
  const [rows, setRows] = useState<SessionRow[]>([]);
  const [open, setOpen] = useState<{ id: string; report: any } | null>(null);
  const load = useCallback(async () => setRows((await window.copilot.request('GET', '/api/v3/sessions')).sessions), []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {  // reports are prepared in the background
    if (!rows.some((r) => r.status === 'preparing')) return;
    const timer = setTimeout(() => void load(), 2000);
    return () => clearTimeout(timer);
  }, [rows, load]);
  const show = async (id: string) => setOpen({ id, report: (await window.copilot.request('GET', `/api/v3/sessions/${id}/report`)).report });
  const r = open?.report;
  return (
    <div className="grid">
      <div className="card">
        <h2>Sessions · 历史会话</h2>
        {rows.length === 0 && <p className="muted">No sessions yet. · 还没有会话。</p>}
        <ul className="list">
          {rows.map((row) => (
            <li key={row.session_id} className="row" style={{ cursor: 'pointer' }} onClick={() => show(row.session_id)}>
              <span style={{ flex: 1 }}>{row.role} · {row.company}<br /><span className="muted small">{new Date(row.created_at).toLocaleString()} · {row.topology === 'mock' ? 'Practice · 练习' : 'Live · 实时'}{row.duration_seconds != null ? ` · ${Math.round(row.duration_seconds / 60)} min` : ''}</span></span>
              <span className="badge">{row.status === 'ready' ? 'Report · 报告' : row.status === 'preparing' ? 'Preparing · 生成中' : row.failure_reason === 'no_content' ? 'No answers · 无回答' : 'No report · 无报告'}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="card">
        <h2>Debrief · 面试复盘</h2>
        {!open && <p className="muted">Choose a session. · 选择一个会话。</p>}
        {open && !r && <p className="muted">No report for this session. · 这个会话没有报告。</p>}
        {r && (
          <div>
            <p><strong>{r.overall?.headline}</strong></p>
            <p>{r.overall?.summary}</p>
            {r.strengths?.length > 0 && <><h2>Strengths · 优势</h2><ul>{r.strengths.map((x: any, i: number) => <li key={i}><strong>{x.label}</strong> — {x.evidence}</li>)}</ul></>}
            {r.improvements?.length > 0 && <><h2>To improve · 待改进</h2><ul>{r.improvements.map((x: any, i: number) => <li key={i}><strong>{x.label}</strong> — {x.evidence}<br /><span className="muted small">{x.practice_action}</span></li>)}</ul></>}
            {r.questions?.length > 0 && <><h2>Questions · 逐题点评</h2>{r.questions.map((q: any, i: number) => (
              <div key={i} style={{ marginBottom: 10 }}><span className="badge">{q.quality}</span> {q.answer_summary}<br /><span className="muted small">{q.feedback}</span>
                {q.stronger_version && <p className="small">Stronger · 更好的回答: {q.stronger_version}</p>}</div>))}</>}
            {r.action_plan?.length > 0 && <><h2>Action plan · 行动计划</h2><ul>{r.action_plan.map((x: any, i: number) => <li key={i}><strong>{x.title}</strong> — {x.how}</li>)}</ul></>}
          </div>
        )}
      </div>
    </div>
  );
}

function Workspace({ username, onSignOut }: { username: string; onSignOut: () => void }) {
  const [tab, setTab] = useState<'prepare' | 'history'>('prepare');
  const [goals, setGoals] = useState<Goal[]>([]);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [goalId, setGoalId] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState({ role: '', company: '', job_description: '' });
  const [language, setLanguage] = useState('en-US');
  const [permissions, setPermissions] = useState({ microphone: '', screen: '' });
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    const [g, d] = await Promise.all([window.copilot.request('GET', '/api/v3/goals'), window.copilot.request('GET', '/api/v3/documents')]);
    setGoals(g.goals);
    setDocs(d.documents);
    setGoalId((current) => current || g.goals[0]?.goal_id || '');
    setPermissions(await window.copilot.permissions());
  }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => {  // document preparation runs in the background
    if (!docs.some((d) => d.status === 'preparing')) return;
    const timer = setTimeout(() => void refresh(), 1500);
    return () => clearTimeout(timer);
  }, [docs, refresh]);

  const createGoal = async () => {
    setError('');
    try {
      const goal = await window.copilot.request('POST', '/api/v3/goals', draft);
      setDraft({ role: '', company: '', job_description: '' });
      setGoalId(goal.goal_id);
      await refresh();
    } catch (e) { setError((e as Error).message); }
  };
  const importDocs = async (kind: 'resume' | 'material') => {
    const imported = await window.copilot.importDocuments(kind);
    setSelected((s) => new Set([...s, ...imported.map((d) => d.document_id)]));
    await refresh();
  };
  const start = async (topology: 'general' | 'mock') => {
    setError('');
    if (!goalId) return setError('Create or choose a goal first. · 请先创建或选择一个目标。');
    if (permissions.microphone !== 'granted' && !(await window.copilot.requestMicrophone())) {
      return setError('Microphone access is required. · 需要麦克风权限。');
    }
    try {
      await window.copilot.startSession({ topology, goalId, documentIds: [...selected], language });
    } catch (e) { setError((e as Error).message); }
  };
  const toggle = (id: string) => setSelected((s) => { const next = new Set(s); next.has(id) ? next.delete(id) : next.add(id); return next; });

  return (
    <div className="page">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h1>Interview Realtime Copilot</h1>
        <div className="row">
          <button className={`ghost ${tab === 'prepare' ? 'active' : ''}`} onClick={() => setTab('prepare')}>Prepare · 准备</button>
          <button className={`ghost ${tab === 'history' ? 'active' : ''}`} onClick={() => setTab('history')}>History · 历史</button>
          <span className="muted">{username}</span><button className="ghost" onClick={onSignOut}>Sign out · 退出</button>
        </div>
      </div>
      {tab === 'history' ? <History /> : <>
      <div className="grid">
        <div className="card">
          <h2>Goal · 目标</h2>
          <select value={goalId} onChange={(e) => setGoalId(e.target.value)}>
            <option value="">—</option>
            {goals.map((g) => <option key={g.goal_id} value={g.goal_id}>{g.role} · {g.company}</option>)}
          </select>
          <label>New goal: role · 职位</label>
          <input value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })} />
          <label>Company · 公司</label>
          <input value={draft.company} onChange={(e) => setDraft({ ...draft, company: e.target.value })} />
          <label>Job description · 职位描述</label>
          <textarea value={draft.job_description} onChange={(e) => setDraft({ ...draft, job_description: e.target.value })} />
          <button style={{ marginTop: 10 }} onClick={createGoal} disabled={!draft.role || !draft.company}>Create goal · 创建目标</button>
        </div>
        <div className="card">
          <h2>Knowledge sources · 资料</h2>
          <div className="row">
            <button onClick={() => importDocs('resume')}>Add resume · 添加简历</button>
            <button onClick={() => importDocs('material')}>Add materials · 添加资料</button>
          </div>
          <ul className="list" style={{ marginTop: 10 }}>
            {docs.map((d) => (
              <li key={d.document_id} className="row">
                <input type="checkbox" style={{ width: 'auto' }} checked={selected.has(d.document_id)} onChange={() => toggle(d.document_id)} />
                <span style={{ flex: 1 }}>{d.filename}</span>
                <span className="badge">{d.kind}</span>
                <span className="badge">{d.status}</span>
              </li>
            ))}
          </ul>
          <p className="muted small">Checked sources ground the questions and answer hints. · 勾选的资料用于出题和回答提示。</p>
        </div>
      </div>
      <div className="card">
        <h2>Start · 开始</h2>
        <div className="row wrap">
          <select value={language} onChange={(e) => setLanguage(e.target.value)} style={{ width: 180 }}>
            <option value="en-US">English interview</option>
            <option value="zh-CN">中文面试</option>
          </select>
          <button className="primary" onClick={() => start('general')}>Go Live · 实时面试</button>
          <button onClick={() => start('mock')}>Practice · 语音练习</button>
        </div>
        <p className="muted small">
          Microphone · 麦克风: {permissions.microphone || '…'} · Screen &amp; system audio · 屏幕与系统声音: {permissions.screen || '…'}
          {permissions.screen !== 'granted' && <> — <button className="ghost" onClick={() => window.copilot.openScreenSettings()}>Open settings · 打开设置</button></>}
        </p>
        {error && <p className="error">{error}</p>}
      </div>
      </>}
    </div>
  );
}

function App() {
  const [user, setUser] = useState<string | null | undefined>(undefined);
  useEffect(() => { auth('session').then((s) => setUser(s?.account.username ?? null)).catch(() => setUser(null)); }, []);
  if (user === undefined) return <div className="page muted">Starting… · 正在启动…</div>;
  if (!user) return <SignIn onSignedIn={setUser} />;
  return <Workspace username={user} onSignOut={() => auth('sign-out', {}).then(() => setUser(null))} />;
}

createRoot(document.getElementById('root')!).render(<App />);
