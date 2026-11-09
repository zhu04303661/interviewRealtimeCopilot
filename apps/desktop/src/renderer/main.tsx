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

function Workspace({ username, onSignOut }: { username: string; onSignOut: () => void }) {
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
        <div className="row"><span className="muted">{username}</span><button className="ghost" onClick={onSignOut}>Sign out · 退出</button></div>
      </div>
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
