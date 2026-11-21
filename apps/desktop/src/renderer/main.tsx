// Main window: account, goals, library, history and settings.
import { BookOpen, CircleHelp, FileText, Flag, History as HistoryIcon, Mic, Monitor, Plus, Radio, Search, Settings as SettingsIcon, Upload } from 'lucide-react';
import type React from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { resolveUiLang, setUiLang, t, useUiLang } from './i18n';
import './styles.css';

const OWNER = 'main';
type Goal = { goal_id: string; role: string; company: string; job_description?: string; company_detail?: string; created_at: string };
type Doc = { document_id: string; filename: string; kind: 'resume' | 'material'; status: string; text_chars?: number; byte_size?: number; created_at?: string; failure_reason?: string };
type SessionRow = { session_id: string; goal_id: string; role: string; company: string; topology: string; created_at: string;
  duration_seconds: number | null; status: string; headline?: string; failure_reason?: string | null; story_shared?: boolean };
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
const docStatus = (d: Doc) => d.status === 'ready' ? <span className="badge good">{t('Ready')}</span>
  : d.status === 'preparing' ? <span className="badge warn">{t('Preparing')}</span> : <span className="badge bad">{t("Couldn't prepare")}</span>;
/** Knowledge sources chosen for a goal (default: every ready document). */
const sourcesKey = (goalId: string) => `sources:${goalId}`;
const chosenSources = (goalId: string, docs: Doc[]) => {
  const saved = localStorage.getItem(sourcesKey(goalId));
  const ready = docs.filter((d) => d.status === 'ready').map((d) => d.document_id);
  return saved ? (JSON.parse(saved) as string[]).filter((id) => ready.includes(id)) : ready;
};

// ── sign in ───────────────────────────────────────────────────────────────
/** Signs in to this account's local workspace (goals, documents, sessions), creating it on first use. */
async function openWorkspace(local: LocalCredentials) {
  // Create first: a failed sign-in makes the engine pause further attempts for a moment.
  try { return (await auth('register', local)).account; } catch (e) {
    if (!/already/i.test((e as Error).message)) throw e;
    return (await auth('sign-in', local)).account;
  }
}

function SignIn({ onSignedIn }: { onSignedIn: (email: string, role: string) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const emailProblem = !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email.trim()) ? t('Enter a valid email address.') : '';
  const passwordProblem = password.length < 10 ? t('Password: at least 10 characters.') : '';
  const submit = async () => {
    setError('');
    if (emailProblem || (mode === 'register' && passwordProblem)) return setError(emailProblem || passwordProblem);
    setBusy(true);
    try {
      const { user, local } = await window.copilot.cloudAuth(mode, email.trim(), password);
      onSignedIn(user.email, (await openWorkspace(local)).role);
    } catch (e) { setError(String((e as Error).message).replace(/^Error invoking remote method '[^']+': (Error: )?/, '')); }
    setBusy(false);
  };
  return (
    <div className="auth">
      <div className="card">
        <div className="logo">IR</div>
        <h1>{mode === 'login' ? t('Welcome back') : t('Create your account')}</h1>
        <p className="muted small" style={{ marginTop: 0 }}>{t('Your Interview Realtime Copilot account — the same one as on the website.')}</p>
        <label className="field"><span>{t('Email')}</span><input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus /></label>
        <label className="field"><span>{t('Password')}{mode === 'register' && <span className="muted"> ({password.length}/10)</span>}</span>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && submit()} /></label>
        {mode === 'register' && <p className="small muted" style={{ margin: '-4px 0 14px' }}>{t('Free plan included: a monthly allowance of our realtime AI engine.')}</p>}
        {error && <p className="error">{error}</p>}
        <button className="btn primary" disabled={busy} style={{ width: '100%', justifyContent: 'center' }} onClick={submit}>
          {busy ? '…' : mode === 'login' ? t('Sign in') : t('Create account')}</button>
        <p className="small muted" style={{ textAlign: 'center', marginBottom: 0 }}>
          <button className="link" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
            {mode === 'login' ? t('New here? Create an account') : t('Already registered? Sign in')}</button>
        </p>
      </div>
    </div>
  );
}

/** Plan, this month's AI allowance and balance, with links to subscribe or manage billing on the website. */
function CloudPlan() {
  const L = useUiLang();
  const [state, setState] = useState<Awaited<ReturnType<typeof window.copilot.cloudStatus>> | null>(null);
  const refresh = () => window.copilot.cloudStatus().then(setState);
  useEffect(() => { void refresh(); }, []);
  const user = state?.user;
  const pro = user && user.plan !== 'free';
  return <>
    <h4 className="setting-group">{t('Plan & AI allowance')}</h4>
    {!user ? <p className="muted small">{state?.offline ? t('Cannot reach the account service right now.') : t('Loading…')}</p> : <>
      <Setting title={pro ? (user.plan === 'yearly' ? t('Pro yearly') : t('Pro monthly')) : t('Free')}
        what={(L === 'zh'
          ? `${user.usage.month} 额度已用 ${user.usage.used_percent}%`
          : `AI allowance for ${user.usage.month}: ${user.usage.used_percent}% used`) +
          (user.usage.credit_usd > 0 ? ` · ${t('plus extra credit')}` : '')}>
        <button className="btn sm primary" onClick={() => window.copilot.cloudOpen(pro ? '/account.html' : '/pricing.html')}>{pro ? t('Manage billing') : t('Subscribe')}</button>
        <button className="btn sm" onClick={refresh}>{t('Refresh')}</button>
      </Setting>
      <div className="meter-bar"><i style={{ width: `${user.usage.used_percent}%`, background: user.usage.used_percent >= 90 ? 'var(--bad)' : undefined }} /></div>
      {user.usage.balance_usd <= 0 && <p className="error small">{t('Your AI allowance for this month is used up. Subscribe to Pro for more.')}</p>}
    </>}
  </>;
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
        <h2>{t('New goal')}</h2>
        <p className="muted small" style={{ marginTop: -10 }}>{t('One role at one company. Two fields are enough.')}</p>
        <label className="field"><span>{t('Role')}</span><input className="input" value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })} autoFocus /></label>
        <label className="field"><span>{t('Company')}</span><input className="input" value={draft.company} onChange={(e) => setDraft({ ...draft, company: e.target.value })} /></label>
        <label className="field"><span>{t('Job description (optional)')}</span>
          <textarea className="textarea" value={draft.job_description} onChange={(e) => setDraft({ ...draft, job_description: e.target.value })} /></label>
        {error && <p className="error">{error}</p>}
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button className="btn ghost" onClick={onClose}>{t('Cancel')}</button>
          <button className="btn primary" disabled={!draft.role.trim() || !draft.company.trim()} onClick={create}>{t('Create goal')}</button>
        </div>
      </div>
    </div>
  );
}

// ── pages ─────────────────────────────────────────────────────────────────
function GoalsPage({ goals, docs, sessions, open, newGoal }: { goals: Goal[]; docs: Doc[]; sessions: SessionRow[]; open: (id: string) => void; newGoal: () => void }) {
  const L = useUiLang();
  const [query, setQuery] = useState('');
  const [hideGuide, setHideGuide] = useState(localStorage.getItem('guide:hidden') === '1');
  const shown = goals.filter((g) => `${g.role} ${g.company}`.toLowerCase().includes(query.toLowerCase()));
  const steps = [goals.length > 0, docs.some((d) => d.kind === 'resume'), sessions.some((s) => s.topology === 'mock'), sessions.some((s) => s.status === 'ready')];
  const current = steps.indexOf(false);
  return (
    <div className="page">
      <div className="page-head">
        <div><div className="eyebrow">{t('Interview plan')}</div><h1>{t('Goals')}</h1>
          <p>{L === 'zh' ? `${goals.length} 个目标 · ${sessions.length} 次会话`
            : `${goals.length} current goal${goals.length === 1 ? '' : 's'} · ${sessions.length} session${sessions.length === 1 ? '' : 's'}`}</p></div>
        <button className="btn" onClick={newGoal}>{t('New goal')}</button>
      </div>
      {!hideGuide && current !== -1 && (
        <div className="hero" style={{ marginTop: 28 }}>
          <div className="row"><div className="eyebrow">{t('Getting started')}</div><span className="spacer" />
            <button className="link small" onClick={() => { localStorage.setItem('guide:hidden', '1'); setHideGuide(true); }}>{t('Dismiss')}</button></div>
          <h2 style={{ margin: '10px 0 0', fontSize: 22 }}>{t('Four steps to your first debrief')}</h2>
          <ol className="steps">
            {[t('Create a goal'), t('Add your resume'), t('Run a practice session'), t('Read your debrief')].map((label, i) => (
              <li key={label} className={steps[i] ? 'done' : i === current ? 'current' : ''}>{label}</li>))}
          </ol>
        </div>
      )}
      <div className="row" style={{ margin: '26px 0 4px' }}>
        <div className="segmented"><button className="active">{t('Current')} · {goals.length}</button></div><span className="spacer" />
        <div style={{ position: 'relative', width: 240 }}>
          <Search size={15} style={{ position: 'absolute', left: 11, top: 10, color: 'var(--text-3)' }} />
          <input className="input" style={{ paddingLeft: 32 }} placeholder={t('Search goals')} value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
      </div>
      {shown.length === 0 ? (
        <Empty icon={<Flag />} title={t('Give one role its own preparation room')}>
          <p>{t('Questions, hints and debriefs are tailored to the goal.')}</p>
          <button className="btn primary" onClick={newGoal}><Plus />{t('New goal')}</button>
        </Empty>
      ) : shown.map((g) => {
        const count = sessions.filter((s) => s.goal_id === g.goal_id).length;
        return (
          <div key={g.goal_id} className="list-row clickable" onClick={() => open(g.goal_id)}>
            <div className="icon-tile"><Flag /></div>
            <div className="spacer"><div className="title">{g.company} · {g.role}</div><div className="meta">{L === 'zh'
              ? `创建于 ${when(g.created_at)} · ${count} 次会话` : `Created ${when(g.created_at)} · ${count} session${count === 1 ? '' : 's'}`}</div></div>
            <span className="faint">›</span>
          </div>
        );
      })}
    </div>
  );
}

function GoalPage({ goal, docs, sessions, start, openSession, refresh }: { goal: Goal; docs: Doc[]; sessions: SessionRow[];
  start: (topology: 'general' | 'mock') => void; openSession: (id: string) => void; refresh: () => void }) {
  const L = useUiLang();
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
  const sessionList = (rows: SessionRow[]) => rows.length === 0 ? <p className="muted" style={{ padding: '14px 4px' }}>{t('No sessions yet')}</p>
    : rows.map((s) => (
      <div key={s.session_id} className="list-row clickable" onClick={() => openSession(s.session_id)}>
        <div className="icon-tile">{s.topology === 'mock' ? <Mic /> : <Radio />}</div>
        <div className="spacer"><div className="title">{s.headline ?? (s.topology === 'mock' ? t('Practice') : t('Live interview'))}</div>
          <div className="meta">{when(s.created_at)}{s.duration_seconds != null ? ` · ${minutes(s.duration_seconds)}` : ''}</div></div>
        {s.status === 'ready' ? <span className="badge good">{t('Debrief')}</span> : s.status === 'preparing' ? <span className="badge warn">{t('Preparing')}</span> : <span className="badge">{t('No report')}</span>}
      </div>
    ));
  return (
    <div className="page">
      <div className="page-head">
        <div><h1 className={`${goal.company} ${goal.role}`.length > 34 ? 'long' : ''} style={{ marginTop: 0 }}>{goal.company} · {goal.role}</h1>
          <p className="small">{goal.job_description ? goal.job_description.slice(0, 160) + (goal.job_description.length > 160 ? '…' : '') : t('No job description')}</p></div>
        <div className="row"><button className="btn" onClick={() => start('mock')}><Mic />{t('Practice')}</button>
          <button className="btn primary" onClick={() => start('general')}><Radio />{t('Go Live')}</button></div>
      </div>
      <div className="tabs">
        {(['overview', 'prep', 'sessions'] as const).map((id) => (
          <button key={id} className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
            {{ overview: t('Overview'), prep: t('Prep'), sessions: t('Sessions') }[id]}{id === 'sessions' && <span className="count">{mine.length}</span>}</button>))}
      </div>
      {tab === 'overview' && (
        <div className="two-col">
          <div className="stack">
            <div className="hero">
              <div className="eyebrow">{t('Next focus')}</div>
              <p style={{ fontSize: 16, margin: '12px 0 16px' }}>{latest?.headline ?? t('Run a practice session to get your first debrief.')}</p>
              <div className="row">
                <button className="btn" onClick={() => start('mock')}><Mic />{t('Continue prep')}</button>
                {latest && <button className="link small" onClick={() => openSession(latest.session_id)}>{t('Read the debrief')}</button>}
              </div>
            </div>
            <div className="card"><div className="card-head"><h3>{t('Recent sessions')}</h3>
              <button className="link small" onClick={() => setTab('sessions')}>All sessions · {mine.length}</button></div>
              <div className="card-body">{sessionList(mine.slice(0, 3))}</div></div>
          </div>
          <div className="card">
            <div className="card-head" style={{ paddingBottom: 14 }}><h3>{t('Goal context')}</h3><button className="link small" onClick={() => setTab('prep')}>{t('Edit')}</button></div>
            <div className="kv"><span>{t('Resume')}</span><span>{resume ? resume.filename : t('Not attached')}</span></div>
            <div className="kv"><span>{t('Materials')}</span><span>{materials.length} {t('attached')}</span></div>
            <div className="kv"><span>{t('Job description')}</span><span>{goal.job_description ? t('Added') : t('None')}</span></div>
          </div>
        </div>
      )}
      {tab === 'prep' && (
        <div className="card">
          <div className="card-head"><h3>{t('Knowledge sources')}</h3>
            <div className="row"><button className="btn sm" onClick={() => importDocs('resume')}><Upload />{t('Resume')}</button>
              <button className="btn sm" onClick={() => importDocs('material')}><Upload />{t('Materials')}</button></div></div>
          <div className="card-body">
            <p className="muted small">{t('Checked sources ground the practice questions and answer hints for this goal.')}</p>
            {docs.length === 0 && <p className="muted">{t('No documents yet')}</p>}
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
      <div className="page-head"><div><h1 style={{ marginTop: 0 }}>{t('Library')}</h1>
        <p>{t('The copilot draws on your resumes and materials. One pool, reused across every goal.')}</p></div></div>
      <div className="tabs" style={{ alignItems: 'flex-end' }}>
        <button className={`tab ${tab === 'resume' ? 'active' : ''}`} onClick={() => setTab('resume')}>{t('Resumes')}<span className="count">{docs.filter((d) => d.kind === 'resume').length}</span></button>
        <button className={`tab ${tab === 'material' ? 'active' : ''}`} onClick={() => setTab('material')}>{t('Materials')}<span className="count">{docs.filter((d) => d.kind === 'material').length}</span></button>
        <span className="spacer" /><button className="btn sm" style={{ marginBottom: 8 }} onClick={upload}><Upload />{t('Upload a file')}</button>
      </div>
      {shown.length === 0 ? (
        <Empty icon={<BookOpen />} title={tab === 'resume' ? t('Add a resume.') : t('Add a material.')}>
          <p>{tab === 'resume' ? t('Answers use only experience from your resume.')
            : t('Notes, briefs or Q&A docs the copilot uses while you answer. PDF, DOCX, TXT or MD, up to 500 MB.')}</p>
          <button className="btn" onClick={upload}><Upload />{t('Upload a file')}</button>
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

/** After a live interview: offer to share an anonymous 面经 on the site's story board — drafted from the
 *  transcript by the engine, reviewed by the user, then submitted for moderation. Nothing posts unreviewed. */
function ShareStory({ row, sessionId }: { row: SessionRow; sessionId: string }) {
  type Story = { company: string; role: string; round: string; lang: string; outcome: string; text: string; questions: string[] };
  const [story, setStory] = useState<Story>({ company: row.company, role: row.role, round: 'technical', lang: 'zh', outcome: '', text: '', questions: [] });
  const [phase, setPhase] = useState<'ask' | 'drafting' | 'edit' | 'sending' | 'done' | 'closed'>('ask');
  const [error, setError] = useState('');
  if (row.topology === 'mock' || row.story_shared || phase === 'closed') return null;
  const set = (patch: Partial<Story>) => setStory((s) => ({ ...s, ...patch }));
  const ROUNDS: [string, string][] = [['hr', 'HR screen'], ['oa', 'Online assessment / OA'], ['technical', 'Technical'],
    ['system-design', 'System design'], ['behavioral', 'Behavioral'], ['manager', 'Hiring manager'],
    ['onsite', 'Onsite / final'], ['other', 'Other']];
  const draft = async () => {
    setPhase('drafting'); setError('');
    try {
      const r = await window.copilot.request('POST', `/api/v3/sessions/${sessionId}/story`) as { draft: Story };
      setStory((s) => ({ ...s, ...r.draft }));
      setPhase('edit');
    } catch (e) { setError((e as Error).message); setPhase('ask'); }
  };
  const submit = async () => {
    setPhase('sending'); setError('');
    try {
      await window.copilot.shareStory(story);
      void window.copilot.request('POST', `/api/v3/sessions/${sessionId}/shared`).catch(() => undefined);
      setPhase('done');
    } catch (e) { setError((e as Error).message); setPhase('edit'); }
  };
  return (
    <div className="card" style={{ marginTop: 20 }}>
      <div className="card-head"><h3>{t('Share your story')}</h3></div>
      <div className="card-body">
        {phase === 'done'
          ? <p>{t('Sent for review — thank you! Once approved it appears anonymously on the story board, and your account earns about 30 minutes of AI usage.')}
            {' '}<button className="link small" onClick={() => window.copilot.cloudOpen('/interviews.html')}>{t('View the board')}</button></p>
          : phase === 'edit' || phase === 'sending' ? (
            <div>
              <div className="row" style={{ gap: 12 }}>
                <label className="field" style={{ flex: 1 }}><span>{t('Company')}</span><input className="input" value={story.company} onChange={(e) => set({ company: e.target.value })} /></label>
                <label className="field" style={{ flex: 1 }}><span>{t('Role')}</span><input className="input" value={story.role} onChange={(e) => set({ role: e.target.value })} /></label>
              </div>
              <div className="row" style={{ gap: 12 }}>
                <label className="field" style={{ flex: 1 }}><span>{t('Round')}</span><select className="select" value={story.round} onChange={(e) => set({ round: e.target.value })}>
                  {ROUNDS.map(([v, label]) => <option key={v} value={v}>{t(label)}</option>)}</select></label>
                <label className="field" style={{ flex: 1 }}><span>{t('Language')}</span><select className="select" value={story.lang} onChange={(e) => set({ lang: e.target.value })}>
                  <option value="zh">中文</option><option value="en">English</option><option value="other">{t('Other')}</option></select></label>
                <label className="field" style={{ flex: 1 }}><span>{t('Outcome')}</span><select className="select" value={story.outcome} onChange={(e) => set({ outcome: e.target.value })}>
                  <option value="">{t('Prefer not to say')}</option><option value="offer">{t('Offer')}</option><option value="rejected">{t('Rejected')}</option>
                  <option value="waiting">{t('Waiting')}</option><option value="declined">{t('Declined')}</option></select></label>
              </div>
              <label className="field"><span>{t('Your story')}</span>
                <textarea className="textarea" style={{ minHeight: 160 }} value={story.text} onChange={(e) => set({ text: e.target.value })} /></label>
              <p className="muted small">{t('Reviewed before it appears; your name and email are never shown. Approved stories earn ~30 minutes of AI usage.')}</p>
              {error && <p className="error small">{error}</p>}
              <div className="row" style={{ justifyContent: 'flex-end' }}>
                <button className="btn ghost" onClick={() => setPhase('ask')}>{t('Back')}</button>
                <button className="btn primary" disabled={phase === 'sending' || story.text.trim().length < 30 || !story.company.trim() || !story.role.trim()} onClick={submit}>
                  {phase === 'sending' ? t('Sending…') : t('Submit for review')}</button>
              </div>
            </div>
          ) : (
            <div>
              <p className="muted">{t("Help other candidates prepare: we can draft an anonymous story from this interview's transcript for you to review. Nothing is shared until you approve it; approved stories earn ~30 minutes of AI usage.")}</p>
              {error && <p className="error small">{error}</p>}
              <div className="row">
                <button className="btn primary" disabled={phase === 'drafting'} onClick={draft}>{phase === 'drafting' ? t('Drafting…') : t('Draft my story')}</button>
                <button className="btn ghost" onClick={() => setPhase('closed')}>{t('No thanks')}</button>
              </div>
            </div>
          )}
      </div>
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
        <button className="link small" onClick={() => open()}>← {t('History')}</button>
        <div className="page-head" style={{ marginTop: 16 }}><div><div className="eyebrow">{row.topology === 'mock' ? t('Practice') : t('Live')} · {when(row.created_at)}</div>
          <h1 className="long">{report?.overall?.headline ?? `${row.company} · ${row.role}`}</h1><p>{report?.overall?.summary ?? (row.status === 'preparing' ? t('Preparing the debrief…') : t('No debrief for this session.'))}</p></div></div>
        <div className="card" style={{ marginTop: 20, padding: '14px 18px' }}>
          <div className="row"><b>{t('Recording')}</b><span className="spacer" />
            {audio ? <audio controls src={audio} style={{ width: 420 }} /> : <span className="muted small">{t('No recording for this session.')}</span>}</div>
        </div>
        <ShareStory row={row} sessionId={sessionId} />
        {report && (
          <div className="two-col" style={{ marginTop: 24 }}>
            <div className="stack">
              {report.questions?.length > 0 && <div className="card"><div className="card-head"><h3>{t('Questions')}</h3></div><div className="card-body prose">
                {report.questions.map((q: any, i: number) => (<div key={i} style={{ padding: '12px 0', borderBottom: '1px solid var(--line)' }}>
                  <span className="badge">{q.quality}</span><p><b>{q.answer_summary}</b></p><p className="muted">{q.feedback}</p>
                  {q.stronger_version && <p><span className="eyebrow">{t('Stronger')}</span><br />{q.stronger_version}</p>}</div>))}</div></div>}
              {report.action_plan?.length > 0 && <div className="card"><div className="card-head"><h3>{t('Action plan')}</h3></div><div className="card-body prose"><ul>
                {report.action_plan.map((x: any, i: number) => <li key={i}><b>{x.title}</b> — {x.how}</li>)}</ul></div></div>}
            </div>
            <div className="stack">
              <div className="card"><div className="card-head"><h3>{t('Strengths')}</h3></div><div className="card-body prose"><ul>
                {(report.strengths ?? []).map((x: any, i: number) => <li key={i}><b>{x.label}</b><br /><span className="muted small">{x.evidence}</span></li>)}</ul></div></div>
              <div className="card"><div className="card-head"><h3>{t('To improve')}</h3></div><div className="card-body prose"><ul>
                {(report.improvements ?? []).map((x: any, i: number) => <li key={i}><b>{x.label}</b><br /><span className="muted small">{x.practice_action}</span></li>)}</ul></div></div>
            </div>
          </div>
        )}
      </div>
    );
  }
  return (
    <div className="page">
      <div className="page-head"><div><h1 style={{ marginTop: 0 }}>{t('History')}</h1><p>{t('Every practice and live session, with its debrief.')}</p></div></div>
      <div style={{ marginTop: 20 }}>
        {sessions.length === 0 ? <Empty icon={<HistoryIcon />} title={t('No sessions yet')}><p>{t('Your debriefs appear here after each session.')}</p></Empty>
          : sessions.map((s) => (
            <div key={s.session_id} className="list-row clickable" onClick={() => open(s.session_id)}>
              <div className="icon-tile">{s.topology === 'mock' ? <Mic /> : <Radio />}</div>
              <div className="spacer"><div className="title">{s.company} · {s.role}</div>
                <div className="meta">{s.topology === 'mock' ? t('Practice') : t('Live')} · {when(s.created_at)}{s.duration_seconds != null ? ` · ${minutes(s.duration_seconds)}` : ''}{s.headline ? ` · ${s.headline}` : ''}</div></div>
              {s.status === 'ready' ? <span className="badge good">{t('Debrief')}</span> : s.status === 'preparing' ? <span className="badge warn">{t('Preparing')}</span>
                : <span className="badge">{s.failure_reason === 'no_content' ? t('No answers') : t('No report')}</span>}
            </div>))}
      </div>
    </div>
  );
}

const SHORTCUT_ROWS: { group: string; hint: string; rows: { ids: (keyof DeviceSettings['shortcuts'])[]; label: string; what: string }[] }[] = [
  { group: 'Interview actions', hint: 'Trigger these during an active session', rows: [
    { ids: ['toggleResults'], label: 'Toggle results panel', what: 'Show or hide the answers in the cockpit' },
    { ids: ['solveScreen'], label: 'Solve screen', what: 'Capture the screen and answer what is on it' },
  ] },
  { group: 'Assistant window', hint: "Control the assistant window's position and visibility", rows: [
    { ids: ['toggleAssistant'], label: 'Show or hide assistant', what: 'Show or hide the cockpit window' },
    { ids: ['moveUp', 'moveDown', 'moveLeft', 'moveRight'], label: 'Move assistant', what: 'Move the cockpit in any direction' },
    { ids: ['grow'], label: 'Grow assistant', what: 'Make the cockpit wider' },
    { ids: ['shrink'], label: 'Shrink assistant', what: 'Make the cockpit narrower' },
  ] },
];
const isMac = window.copilot.platform === 'darwin';
const KEY_NAMES: Record<string, string> = isMac
  ? { Alt: '⌥', Option: '⌥', Shift: '⇧', Control: '⌃', Ctrl: '⌃', Command: '⌘', Cmd: '⌘', CommandOrControl: '⌘', Up: '↑', Down: '↓', Left: '←', Right: '→' }
  : { Option: 'Alt', Control: 'Ctrl', CommandOrControl: 'Ctrl', Command: 'Win', Cmd: 'Win', Super: 'Win', Up: '↑', Down: '↓', Left: '←', Right: '→' };
const keyGlyphs = (accelerator: string) => accelerator.split('+').map((k) => KEY_NAMES[k] ?? k);
/** Turn a keydown into an Electron accelerator; null until a non-modifier key with a modifier is pressed. */
function accelerator(e: React.KeyboardEvent): string | null {
  const key = { ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right', ' ': 'Space' }[e.key] ?? (e.key.length === 1 ? e.key.toUpperCase() : null);
  if (!key || ['Meta', 'Alt', 'Shift', 'Control'].includes(e.key)) return null;
  const mods = [e.metaKey && (isMac ? 'Command' : 'Super'), e.ctrlKey && 'Control', e.altKey && 'Alt', e.shiftKey && 'Shift'].filter(Boolean);
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
  const L = useUiLang();
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
  const permission = (value: string) => value === 'granted' ? <span className="badge good">{t('✓ Granted')}</span> : <span className="badge warn">{value === 'denied' ? t('Denied') : t('Not set')}</span>;
  const sections: [Section, string][] = [['general', t('General')], ['appearance', t('Appearance')], ['defaults', t('Defaults')],
    ['privacy', t('Privacy & Stealth')], ['shortcuts', t('Shortcuts')], ['account', t('Account')]];
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
          <h2>{t('General')}</h2>
          <h4 className="setting-group">{t('Interface')}</h4>
          <Setting title={t('Interface')} what={t('The language of the app itself. Restart-free; takes effect immediately.')}>
            <select className="select" style={{ width: 190 }} value={prefs.ui_language ?? ''}
              onChange={(e) => { void savePrefs({ ui_language: e.target.value || null }); setUiLang(resolveUiLang(e.target.value || null)); }}>
              <option value="">{t('System')}</option><option value="en">English</option><option value="zh">中文</option>
            </select></Setting>
          <h4 className="setting-group">{t('Startup')}</h4>
          <Setting title={t('Launch at login')} what={t('Open the app automatically when you sign in to this computer.')}>
            <Switch label="Launch at login" on={device.launchAtLogin} onChange={(on) => update({ launchAtLogin: on })} /></Setting>
          <h4 className="setting-group">{t('App updates')}</h4>
          <Setting title={`Interview Realtime Copilot ${info.version}`} what={t('Updates ship with packaged builds and are not available in development.')}>
            <button className="btn sm" disabled>{t('Check for updates')}</button></Setting>
        </>}
        {section === 'appearance' && <>
          <h2>{t('Appearance')}</h2>
          <h4 className="setting-group">{t('Cockpit')}</h4>
          <p className="muted small">{t('How the assistant panel looks during a live session. These settings stay on this device and never change on their own.')}</p>
          <div className="checker">
            <div className="preview" style={{ background: rgba(device.background, device.opacity), color: device.text }}>
              <div className="preview-head"><span className="dot" /> <b style={{ font: '600 12px var(--mono)' }}>Listening</b></div>
              <div style={{ padding: '12px 14px' }}><div>Start with the outcome, then the two decisions that got you there.</div>
                <div style={{ opacity: .62, marginTop: 8, fontSize: 13 }}>Secondary detail sits at this weight.</div></div>
              <div className="preview-foot"><span>Solve screen</span><span>00:07</span></div>
            </div>
          </div>
          <Setting title={t('Opacity')} what={t('How much of the meeting behind the panel shows through. Ships at 80%; below 70% the answer text stops surviving real meeting content, so that is the floor.')}>
            <input type="range" min={70} max={100} value={Math.round(device.opacity * 100)} onChange={(e) => update({ opacity: Number(e.target.value) / 100 })} style={{ width: 180 }} />
            <span className="faint" style={{ font: '12px var(--mono)', width: 40 }}>{Math.round(device.opacity * 100)}%</span></Setting>
          {(['background', 'text'] as const).map((key) => (
            <Setting key={key} title={key === 'background' ? t('Background') : t('Text')}
              what={key === 'background' ? t("The panel's base colour.") : t('The base colour for text; the three text weights are derived from it.')}>
              <input type="color" value={device[key]} onChange={(e) => update({ [key]: e.target.value })} style={{ width: 36, height: 32, border: 0, background: 'none' }} />
              <input className="input" style={{ width: 110, fontFamily: 'var(--mono)' }} defaultValue={device[key]} key={device[key]}
                onBlur={(e) => /^#[0-9a-f]{6}$/i.test(e.target.value) && update({ [key]: e.target.value })} />
              <button className="btn ghost sm" disabled={device[key] === defaults[key]} onClick={() => update({ [key]: defaults[key] })}>{t('Use default')}</button>
            </Setting>))}
          {ratio < 4.5 && <p className="error">{t('Low contrast')} ({ratio.toFixed(1)}:1). {t('Text may be hard to read during a session; aim for at least 4.5:1.')}</p>}
        </>}
        {section === 'defaults' && <>
          <h2>{t('Defaults')}</h2>
          <h4 className="setting-group">{t('Launch defaults')}</h4>
          <p className="muted small">{t('What a fresh session starts from.')}</p>
          <Setting title={t('Interview language')} what={t('The language the interviewer speaks and the copilot transcribes.')}>
            <select className="select" style={{ width: 190 }} value={prefs.default_language ?? ''} onChange={(e) => savePrefs({ default_language: e.target.value || null })}>
              <option value="">{t('System default')}</option><option value="en-US">English</option><option value="zh-CN">中文（普通话）</option>
              <option value="ja-JP">日本語</option><option value="ko-KR">한국어</option><option value="de-DE">Deutsch</option><option value="fr-FR">Français</option><option value="es-ES">Español</option>
            </select></Setting>
          <Setting title={t('Assistance')} what={t('The language translations and answer hints use — Chinese help during an English interview, or English only.')}>
            <select className="select" style={{ width: 190 }} value={prefs.default_assist_language ?? ''} onChange={(e) => savePrefs({ default_assist_language: e.target.value || null })}>
              <option value="">{t('System default')}</option><option value="en">English</option><option value="zh">中文</option>
            </select></Setting>
          <Setting title={t('Coding language')} what={t('The default language for code the copilot writes.')}>
            <select className="select" style={{ width: 190 }} value={prefs.default_coding_language ?? ''} onChange={(e) => savePrefs({ default_coding_language: e.target.value || null })}>
              <option value="">{t('Any')}</option>{['Python', 'C++', 'C', 'Java', 'JavaScript', 'TypeScript', 'Go', 'Rust', 'MATLAB'].map((l) => <option key={l}>{l}</option>)}
            </select></Setting>
          <Setting title={t('Default playbook')} what={t('How the copilot shows up when a goal has no choice yet.')}>
            <select className="select" style={{ width: 190 }} value={prefs.default_playbook_id ?? ''} onChange={(e) => savePrefs({ default_playbook_id: e.target.value || null })}>
              <option value="">{t('Platform default')}</option>{playbooks.map((p) => <option key={p.playbook_id} value={p.playbook_id}>{p.name}</option>)}
            </select></Setting>
        </>}
        {section === 'privacy' && <>
          <h2>{t('Privacy & Stealth')}</h2>
          <h4 className="setting-group">{t('Stealth')}</h4>
          <p className="muted small">{t('Keep the cockpit out of view while you interview.')}</p>
          <Setting title={t('Hide from screen sharing')} what={t('The cockpit never appears in a shared screen or recording.')}>
            <Switch label="Hide from screen sharing" on={device.stealth} onChange={(on) => update({ stealth: on })} /></Setting>
          {!device.stealth && <p className="error">{t('While this is off, anyone you share your screen with can see the cockpit, and recordings will include it.')}</p>}
          <h4 className="setting-group">{t('System access')}</h4>
          <p className="muted small">{t('Needed to hear the interview and read the shared screen. Capture runs only during an active session.')}</p>
          <Setting icon={<Mic />} title={t('Microphone')} what={t('Required for hearing your voice during interviews.')}>{permission(permissions.microphone)}
            <button className="btn sm" disabled={permissions.microphone === 'granted'} onClick={() => window.copilot.requestMicrophone().then(() => window.copilot.permissions().then(setPermissions))}>
              {permissions.microphone === 'granted' ? 'Granted' : t('Grant')}</button></Setting>
          <Setting icon={<Monitor />} title={t('Screen & System Audio')} what={t('Required to hear the interviewer in Live mode and for screen capture.')}>{permission(permissions.screen)}
            <button className="btn sm" disabled={permissions.screen === 'granted'} onClick={() => window.copilot.openScreenSettings()}>{permissions.screen === 'granted' ? 'Granted' : t('Open settings')}</button></Setting>
          <h4 className="setting-group">{t('Screen capture')}</h4>
          <Setting title={t('Auto-capture')} what={t('When a coding or system-design question needs what is on your screen, capture it to read the content. Captures stay hidden from the interviewer and only happen during an active session.')}>
            <Switch label="Auto-capture" on={device.autoCapture} onChange={(on) => update({ autoCapture: on })} /></Setting>
          <h4 className="setting-group">{t('Voice & memory')}</h4>
          <Setting title={t('Voice sample')} what={voice ? (L === 'zh' ? `已保存 ${new Date(voice.created_at ?? voice.updated_at ?? Date.now()).toLocaleDateString()}` : `Saved ${new Date(voice.created_at ?? voice.updated_at ?? Date.now()).toLocaleDateString()}`) : t('No voice sample is saved.')}>
            {voice && <button className="btn sm" onClick={() => window.copilot.request('DELETE', '/api/v3/voice-sample').then(() => setVoice(null))}>{t('Delete')}</button>}</Setting>
          <Setting title={t('Erase its memory')} what={t('Deletes learned facts, preferences, strengths and weaknesses across every goal. Sessions, debriefs and documents stay.')}>
            <button className="btn sm" onClick={async () => { if (confirm(t('Erase everything the coach has learned?'))) { await window.copilot.request('DELETE', '/api/v3/memory'); setMessage(t('Memory erased.')); } }}>{t('Erase everything…')}</button></Setting>
          <h4 className="setting-group">{t('Data authorization')}</h4>
          <Setting title={t('Share data')} what={t('Allow sharing your data with service providers that help operate and improve the product.')}>
            <Switch label="Share data" on={!!consents.share_data} onChange={(on) => saveConsents({ share_data: on })} /></Setting>
          <Setting title={t('AI training')} what={t('Allow your data to be used to improve the AI.')}>
            <Switch label="AI training" on={!!consents.ai_training} onChange={(on) => saveConsents({ ai_training: on })} /></Setting>
          <p className="faint small">{t('Turning a switch off applies to new data from that point on.')}</p>
          {message && <p className="small">{message}</p>}
        </>}
        {section === 'shortcuts' && <>
          <h2>{t('Shortcuts')}</h2>
          <p className="muted small">{t('These shortcuts are active during a session. No window-switching needed. Click any shortcut to reassign it.')}</p>
          {SHORTCUT_ROWS.map((group) => (<div key={group.group}>
            <h4 className="setting-group">{t(group.group)}</h4><p className="muted small" style={{ marginTop: -4 }}>{t(group.hint)}</p>
            {group.rows.map((row) => (
              <Setting key={row.label} title={t(row.label)} what={t(row.what)}>
                <span className="row" style={{ gap: 6 }}>{row.ids.map((id) => (
                  <button key={id} className={`keys ${recording === id ? 'recording' : ''}`} onClick={() => setRecording(id)}
                    onKeyDown={(e) => { if (recording !== id) return; e.preventDefault(); if (e.key === 'Escape') return setRecording(null);
                      const key = accelerator(e); if (key) { void update({ shortcuts: { ...device.shortcuts, [id]: key } }); setRecording(null); } }}
                    onBlur={() => recording === id && setRecording(null)}>
                    {recording === id ? t('Press keys…') : keyGlyphs(device.shortcuts[id]).map((k, i) => <kbd key={i}>{k}</kbd>)}
                  </button>))}</span>
              </Setting>))}
          </div>))}
          <div style={{ marginTop: 18 }}><button className="btn sm" onClick={() => update({ shortcuts: defaults.shortcuts })}>{t('Reset to defaults')}</button></div>
        </>}
        {section === 'account' && <>
          <h2>{t('Account')}</h2>
          <h4 className="setting-group">{t('Account')}</h4>
          <Setting title={t('Help & support')} what="linkyourfuture2026@outlook.com"><button className="btn sm" onClick={() => void window.copilot.contactSupport()}>{t('Email us')}</button></Setting>
          <Setting title={username} what={t('Signed in with your website account')}>
            <button className="btn sm" onClick={signOut}>{t('Sign out')}</button></Setting>
          <CloudPlan />
          <h4 className="setting-group">{t('Local workspace')}</h4>
          <p className="muted small">{t('This computer stores your workspace: goals, documents, sessions and debriefs.')}</p>
          <Setting title={t('Delete account')} what={t('Account deletion is unavailable in this local build.')}><button className="btn sm" disabled>{t('Delete account…')}</button></Setting>
          {role === 'admin' && accounts.length > 0 && <>
            <h4 className="setting-group">{t('Local accounts')}</h4>
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
      {level === null ? <button className="btn sm" onClick={start}>{t('Test microphone')}</button>
        : <><span className="level"><span style={{ width: `${Math.round(level * 100)}%` }} /></span><button className="btn ghost sm" onClick={() => stop.current()}>{t('Stop')}</button></>}
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
  const [assist, setAssist] = useState('');
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
  const defaultAssist = prefs?.default_assist_language || (navigator.language.startsWith('zh') ? 'zh' : 'en');
  const micOk = permissions.microphone === 'granted';
  const live = topology === 'general';
  const blocked = !micOk ? t('Microphone access is required for this session.')
    : live && !systemAudio ? t('Computer audio capture is not available on this computer.') : '';
  const start = async () => {
    setError('');
    setStarting(true);
    localStorage.setItem(sourcesKey(goal.goal_id), JSON.stringify(chosen));
    try {
      await window.copilot.startSession({ topology, goalId: goal.goal_id, documentIds: chosen, language: language || defaultLanguage,
        assist: assist || defaultAssist,
        codingLanguage: coding || prefs?.default_coding_language || null, playbookId: playbook || prefs?.default_playbook_id || null,
        ...(topology === 'mock' ? { practiceMode } : {}) });
      onStarted();
    } catch (e) { setError((e as Error).message); setStarting(false); }
  };
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal preflight" onClick={(e) => e.stopPropagation()}>
        <div className="eyebrow">{t('Preflight')}</div>
        <h2 style={{ margin: '8px 0 4px' }}>{goal.company} · {goal.role}</h2>
        <p className="muted small" style={{ marginTop: 0 }}>{t('These choices apply to this session only; your goal and defaults stay as they are.')}</p>
        <div className="segmented" style={{ margin: '6px 0 4px' }}>
          <button className={live ? 'active' : ''} onClick={() => setTopology('general')}>{t('Live interview')}</button>
          <button className={!live ? 'active' : ''} onClick={() => setTopology('mock')}>{t('Practice')}</button>
        </div>

        {live ? <>
          <h4 className="setting-group">{t('Interview setup')}</h4>
          <div className="choice-grid">
            <button className={`choice ${setup === 'computer' ? 'active' : ''}`} onClick={() => setSetup('computer')}>
              <Monitor size={18} /><b>{t('This computer')}</b><span>{t('Zoom, Teams, Meet… Captures your microphone and the meeting audio.')}</span></button>
            <button className="choice" disabled title={t('Coming soon')}>
              <Mic size={18} /><b>{t('Phone or in person')}</b><span>{t('Needs voice separation in one microphone; coming soon.')}</span></button>
          </div>
        </> : <>
          <h4 className="setting-group">{t('Practice scenario')}</h4>
          <div className="segmented">
            {[['sequential', t('Prepared, in order')], ['random', t('Prepared, random')], ['ai', t('AI improvises')]].map(([m, label]) => (
              <button key={m} className={practiceMode === m ? 'active' : ''} onClick={() => setPracticeMode(m)}>{label}</button>))}
          </div>
          <p className="faint small">{t('The interviewer speaks; answer out loud. You can switch questions in the cockpit.')}</p>
        </>}

        <h4 className="setting-group">{t('Knowledge sources')}</h4>
        {ready.length === 0 ? <p className="muted small">{t('No prepared documents. Add a resume or materials in the Library.')}</p>
          : <div className="sources">{ready.map((d) => (
            <label key={d.document_id} className="check-row"><input type="checkbox" checked={chosen.includes(d.document_id)} onChange={() => toggle(d.document_id)} />
              <FileText size={15} className="faint" /><span className="spacer">{d.filename}</span><span className="badge">{d.kind === 'resume' ? 'Resume' : 'Material'}</span></label>))}</div>}

        <h4 className="setting-group">{t('Answers')}</h4>
        <div className="grid3">
          <label className="field"><span>{t('Interview language')}</span>
            <select className="select" value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="">{t('Account default')}（{LANGUAGES.find(([c]) => c === defaultLanguage)?.[1] ?? defaultLanguage}）</option>
              {LANGUAGES.map(([c, l]) => <option key={c} value={c}>{l}</option>)}</select></label>
          <label className="field"><span>{t('Assistance')}</span>
            <select className="select" value={assist} onChange={(e) => setAssist(e.target.value)}>
              <option value="">{t('Account default')}（{defaultAssist === 'zh' ? '中文' : 'English'}）</option>
              <option value="en">English</option><option value="zh">中文</option></select></label>
          <label className="field"><span>{t('Coding language')}</span>
            <select className="select" value={coding} onChange={(e) => setCoding(e.target.value)}>
              <option value="">{t('Account default')}</option>
              {CODING.map((c) => <option key={c}>{c}</option>)}</select></label>
          <label className="field"><span>{t('Playbook')}</span>
            <select className="select" value={playbook} onChange={(e) => setPlaybook(e.target.value)}>
              <option value="">{t('Account default')}</option>{playbooks.map((p) => <option key={p.playbook_id} value={p.playbook_id}>{p.name}</option>)}</select></label>
        </div>

        <h4 className="setting-group">{t('Audio check')}</h4>
        <div className="setting"><div className="icon-tile"><Mic /></div><div className="what"><b>{t('Microphone')}</b>
          <span>{micOk ? t('Hears your answers.') : t('Grant microphone access to continue.')}</span></div>
          {micOk ? <MicTest /> : <button className="btn sm" onClick={() => window.copilot.requestMicrophone().then(() => window.copilot.permissions().then(setPermissions))}>{t('Grant microphone access')}</button>}</div>
        {live && <div className="setting"><div className="icon-tile"><Monitor /></div><div className="what"><b>{t('Computer audio')}</b>
          <span>{!systemAudio ? t('Not available on this computer.') : isMac ? t('Hears the interviewer from the meeting app. macOS asks once for System Audio Recording when the session starts.')
            : t('Hears the interviewer from the meeting app (whatever plays through your speakers or headphones).')}</span></div>
          {systemAudio ? <span className="badge good">{t('Ready')}</span> : <span className="badge bad">{t('Unavailable')}</span>}</div>}
        <p className="faint small">{t('Microphone and meeting audio start after you press Start.')}</p>

        {(error || blocked) && <p className="error">{error || blocked}</p>}
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
          <button className="btn ghost" onClick={onClose}>{t('Cancel')}</button>
          <button className="btn primary" disabled={!!blocked || starting || !prefs} onClick={start}>
            {starting ? t('Starting…') : live ? t('Start session') : t('Start practice session')}</button>
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
  useEffect(() => {  // a live interview just ended: land on its debrief, where the story-share card prompts them
    window.copilot.onSessionEnded((id, topology) => { if (topology !== 'mock') void refresh().then(() => setRoute({ page: 'history', sessionId: id })); });
  }, [refresh]);

  const goal = route.page === 'goal' ? goals.find((g) => g.goal_id === route.goalId) : undefined;
  const liveGoal = goal ?? goals[0];
  const [preflight, setPreflight] = useState<{ goal: Goal; topology: 'general' | 'mock' } | null>(null);
  const start = (topology: 'general' | 'mock', target = liveGoal) => {
    setError('');
    if (!target) return setCreating(true);
    setPreflight({ goal: target, topology });
  };
  const title = { goals: t('Goals'), goal: goal ? `${goal.company} · ${goal.role}` : t('Goal'), library: t('Library'), history: t('History'), settings: t('Settings') }[route.page];
  const nav = [
    { page: 'library' as const, label: 'Library', icon: <BookOpen /> },
    { page: 'history' as const, label: 'History', icon: <HistoryIcon /> },
    { page: 'settings' as const, label: 'Settings', icon: <SettingsIcon /> },
  ];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand"><div className="logo">IR</div></div>
        <div className="section">
          <div className="side-head" onClick={() => setRoute({ page: 'goals' })}><span>{t('Goals')}</span><span className="faint">{goals.length} ›</span></div>
          <button className="btn side-new" onClick={() => setCreating(true)}><Plus />{t('New goal')}</button>
          <div className="side-label eyebrow">{t('Up next')}</div>
        </div>
        <div className="side-goals">
          {goals.length === 0 ? <div style={{ padding: '4px 10px' }}><b className="small">{t('No current goals')}</b><p className="small muted" style={{ margin: '4px 0' }}>{t('Create one when an interview is on your horizon.')}</p></div>
            : goals.map((g) => (
              <button key={g.goal_id} className={`side-goal ${route.page === 'goal' && route.goalId === g.goal_id ? 'active' : ''}`} onClick={() => setRoute({ page: 'goal', goalId: g.goal_id })}>
                <div className="title">{g.company}</div><div className="meta">{g.role}</div></button>))}
        </div>
        <div className="side-nav">{nav.map((n) => (
          <button key={n.page} className={route.page === n.page ? 'active' : ''} onClick={() => setRoute({ page: n.page } as Route)}>{n.icon}{t(n.label)}</button>))}</div>
        <div className="side-user"><div className="avatar">{username[0]?.toUpperCase()}</div><span className="spacer">{username}</span><span className="badge">{t('Local')}</span></div>
      </aside>
      <main className="main">
        <div className="topbar">
          <span className="crumb">{title}</span><span className="spacer" />
          {error && <span className="error">{error}</span>}
          {route.page !== 'goal' && <button className="btn primary" onClick={() => start('general')}><Radio />{t('Go Live')}</button>}
          <button className="btn ghost" title={t('Help — email linkyourfuture2026@outlook.com')} onClick={() => void window.copilot.contactSupport()}><CircleHelp /></button>
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
  useUiLang();
  const [user, setUser] = useState<{ username: string; role: string } | null | undefined>(undefined);
  useEffect(() => {
    void window.copilot.request('GET', '/api/v3/me/prefs')
      .then((prefs: Record<string, any>) => setUiLang(resolveUiLang(prefs?.ui_language))).catch(() => {});
  }, []);
  useEffect(() => {
    void window.copilot.cloudStatus().then(async (cloud) => {
      if (!cloud.signedIn || !cloud.local) return setUser(null);
      setUser({ username: cloud.email!, role: (await openWorkspace(cloud.local)).role });
    }).catch(() => setUser(null));
  }, []);
  if (user === undefined) return <div className="auth"><span className="muted">{t('Starting…')}</span></div>;
  if (!user) return <SignIn onSignedIn={(username, role) => setUser({ username, role })} />;
  return <Shell username={user.username} role={user.role}
    signOut={() => void Promise.allSettled([auth('sign-out', {}), window.copilot.cloudSignOut()]).then(() => setUser(null))} />;
}

createRoot(document.getElementById('root')!).render(<App />);
