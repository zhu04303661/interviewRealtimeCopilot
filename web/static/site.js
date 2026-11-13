// Site behaviour: language, header/footer, account state, the cockpit demo and page logic.
document.documentElement.classList.add('js');  // enables scroll reveal; content stays visible without JS
const LANGS = { en: 'English', zh: '中文' };
let lang = localStorage.getItem('lang') || (navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en');
const urlLang = new URLSearchParams(location.search).get('lang');  // ?lang=en|zh: share a link in one language
if (urlLang in LANGS) { lang = urlLang; localStorage.setItem('lang', lang); }
const tr = (key, vars = {}) => Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), (window.I18N[lang] || {})[key] ?? window.I18N.en[key] ?? key);

function applyLanguage() {
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = tr(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((el) => { el.placeholder = tr(el.dataset.i18nPlaceholder); });
  document.querySelectorAll('.lang button').forEach((b) => b.classList.toggle('on', b.dataset.lang === lang));
  window.dispatchEvent(new Event('language'));
}

const api = async (path, body) => {
  const response = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
};
const el = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstChild; };

function chrome() {
  const page = document.body.dataset.page;
  const link = (href, key, name) => `<a href="${href}" class="${page === name ? 'active' : ''}" data-i18n="${key}"></a>`;
  document.body.prepend(el(`<header class="nav"><div class="wrap">
    <a class="brand" href="/"><span class="logo">IR</span>Interview Realtime Copilot</a>
    <nav class="links">${link('/use-cases.html', 'nav.scenarios', 'use-cases')}${link('/demo.html', 'nav.demo', 'demo')}${link('/pricing.html', 'nav.pricing', 'pricing')}${link('/download.html', 'nav.download', 'download')}<a href="/docs/" class="${page.startsWith('docs-') ? 'active' : ''}" data-i18n="nav.docs"></a></nav>
    <span class="spacer"></span><span class="lang">${Object.entries(LANGS).map(([k, v]) => `<button data-lang="${k}">${v}</button>`).join('')}</span>
    <span id="account-slot"><a class="btn" href="/login.html" data-i18n="nav.signin"></a></span>
    <a class="btn primary" href="/download.html" data-i18n="nav.start"></a></div></header>`));
  document.body.append(el(`<footer><div class="wrap"><span class="brand"><span class="logo">IR</span>Interview Realtime Copilot</span><span class="spacer"></span>
    <a href="/use-cases.html" data-i18n="nav.scenarios"></a><a href="/pricing.html" data-i18n="nav.pricing"></a><a href="/download.html" data-i18n="nav.download"></a>
    <a href="/docs/" data-i18n="nav.docs"></a><a href="/#wishlist" data-i18n="foot.wishlist"></a><a href="/privacy.html" data-i18n="foot.privacy"></a><a href="mailto:${window.SUPPORT_EMAIL}"><span data-i18n="foot.support"></span> · ${window.SUPPORT_EMAIL}</a><a href="/terms.html" data-i18n="foot.terms"></a><span>© ${new Date().getFullYear()}</span></div></footer>`));
  document.querySelectorAll('.lang button').forEach((b) => b.addEventListener('click', () => { lang = b.dataset.lang; localStorage.setItem('lang', lang); applyLanguage(); }));
  api('/api/me').then(({ user }) => {
    if (user) document.getElementById('account-slot').innerHTML = (user.admin ? `<a class="btn" href="/admin.html" data-i18n="nav.admin">${tr('nav.admin')}</a> ` : '')
      + `<a class="btn" href="/account.html">${user.email.split('@')[0]} · ${user.plan === 'free' ? 'Free' : 'Pro'}</a>`;
  }).catch(() => {});
}

/** Scripted cockpit: caption, translation, question card and a streamed bilingual hint. Restarts on language change. */
function cockpitDemo(root) {
  const body = root.querySelector('.mock-body');
  const clock = root.querySelector('.clock');
  let seconds = 0, run = 0;
  setInterval(() => { seconds++; clock.textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; }, 1000);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const scene = root.closest('[data-scene]')?.parentElement;
  const speak = (who) => scene?.querySelectorAll('.tile-v').forEach((tile) => tile.classList.toggle('speaking', tile.dataset.speaker === who));
  const phase = (name) => scene?.querySelectorAll('.phases span').forEach((chip) => chip.classList.toggle('on', chip.dataset.phase === name));
  async function play(id) {
    const alive = () => id === run;
    const type = async (node, text, speed) => { node.classList.add('typing'); for (const ch of text) { if (!alive()) return; node.textContent += ch; await wait(speed); } node.classList.remove('typing'); };
    body.innerHTML = '';
    // Step 1: the user's own resume and notes are uploaded and prepared.
    speak(null); phase('upload');
    const sources = el(`<div class="sources fade-in"><span class="stamp">${tr('up.title')}</span></div>`);
    body.append(sources);
    for (const [file, size] of [['Resume_Li_Ming.pdf', '2 pages'], ['AccelerComm_Interview_Prep.md', '115k chars'], ['System_Model_Framework.pdf', '38 pages']]) {
      const row = el(`<div class="src fade-in"><span>📄 ${file}</span><span class="faint">${size}</span><span class="badge-s">${tr('up.reading')}</span></div>`);
      sources.append(row); await wait(500); if (!alive()) return;
      row.querySelector('.badge-s').textContent = tr('up.ready'); row.querySelector('.badge-s').classList.add('ok');
    }
    sources.append(el(`<div class="src-done fade-in">${tr('up.done')}</div>`));
    await wait(1800); if (!alive()) return;
    body.innerHTML = '';
    const en = window.I18N.en, zh = window.I18N.zh;
    const other = lang === 'zh' ? en : zh;  // the translation line is in the other language
    const line = el(`<div class="line fade-in"><span class="stamp">${tr('mock.interviewer')}</span><div class="text"></div><div class="tr"></div></div>`);
    body.append(line);
    speak('interviewer'); phase('hear');
    await type(line.querySelector('.text'), (lang === 'zh' ? zh : en)['mock.q'], 24); if (!alive()) return;
    speak(null); phase('understand');
    await wait(350); line.querySelector('.tr').textContent = other['mock.q'];
    await wait(600); if (!alive()) return;
    body.append(el(`<div class="q fade-in"><span class="stamp">${tr('mock.question')}</span><div style="margin-top:7px">${(lang === 'zh' ? zh : en)['mock.q']}</div></div>`));
    await wait(500);
    phase('hint');
    const hint = el('<div class="hint fade-in"></div>'); body.append(hint);
    for (const [label, dict] of [['EN', en], ['中文', zh]]) {
      hint.append(el(`<div class="langtag">${label}</div>`));
      const ul = el('<ul></ul>'); hint.append(ul);
      for (const key of ['mock.h1', 'mock.h2', 'mock.h3']) { const li = el('<li></li>'); ul.append(li); await type(li, dict[key], 12); if (!alive()) return; }
    }
    phase('answer'); speak('me');
    await wait(6000); speak(null); if (alive()) play(id);
  }
  const restart = () => { run++; play(run); };
  window.addEventListener('language', restart);
  restart();
}

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const day = (ts) => (ts ? new Date(ts * 1000).toLocaleString(lang === 'zh' ? 'zh-CN' : 'en', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—');
const usd = (v) => `$${Number(v).toFixed(2)}`;

const pages = {
  async admin() {
    const root = document.getElementById('admin');
    const get = (p) => fetch(p).then(async (r) => { if (!r.ok) throw Object.assign(new Error(), { status: r.status }); return r.json(); });
    let data;
    try { data = await Promise.all(['/api/admin/overview', '/api/admin/usage', '/api/admin/messages', '/api/admin/users'].map(get)); }
    catch (e) {
      if (e.status === 401) { location.href = '/login.html?next=/admin.html'; return; }
      root.innerHTML = `<div class="notice warn">${tr('ad.denied')}</div>`; return;
    }
    let [o, u, m, users] = data, query = '';
    const card = (label, value, sub) => `<div class="card stat-card"><span class="muted small">${label}</span><b>${value}</b><span class="faint small">${sub}</span></div>`;
    const table = (head, rows) => rows.length ? `<div class="doc-table"><table><thead><tr>${head.map((h) => `<th>${tr(h)}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>` : `<p class="muted">${tr('ad.none')}</p>`;
    const render = () => {
      const p = o.subscriptions.plans, max = Math.max(0.0001, ...u.days.map((d) => d.usd));
      root.innerHTML = `<div class="stat-grid">
        ${card(tr('ad.users'), o.users.total, tr('ad.new', { d7: o.users.new_7d, d30: o.users.new_30d }))}
        ${card(tr('ad.active'), o.users.active_30d, tr('ad.devices', { n: o.users.devices }))}
        ${card(tr('ad.subs'), (p.monthly ?? 0) + (p.yearly ?? 0), tr('ad.subsplit', { m: p.monthly ?? 0, y: p.yearly ?? 0, f: p.free ?? 0 }))}
        ${card(tr('ad.month'), usd(o.usage.month_used_usd), tr('ad.of', { total: o.usage.month_allowance_usd.toFixed(2), req: o.usage.month_requests }))}
        ${card(tr('ad.remaining'), usd(o.usage.month_remaining_usd), tr('ad.credit', { credit: o.usage.credit_usd.toFixed(2), min: o.usage.audio_minutes_month }))}
        ${card(tr('ad.alltime'), usd(o.usage.all_time_used_usd), tr('ad.alltimereq', { req: o.usage.all_time_requests }))}</div>
        <h2>${tr('ad.daily')}</h2>${u.days.length ? `<div class="bars">${u.days.map((d) => `<div title="${d.day}: ${usd(d.usd)} · ${d.requests} · ${d.users}"><i style="height:${Math.max(3, d.usd / max * 100)}%"></i><span>${d.day.slice(5)}</span></div>`).join('')}</div>` : `<p class="muted">${tr('ad.none')}</p>`}
        ${u.models.length ? `<h2>${tr('ad.models')}</h2>` + table(['ad.c.model', 'ad.c.req', 'ad.month'], u.models.map((x) => `<tr><td>${esc(x.model)}</td><td>${x.requests}</td><td>${usd(x.usd)}</td></tr>`)) : ''}
        <h2>${tr('ad.userlist')} (${users.users.length})</h2><input class="input" id="admin-q" placeholder="${tr('ad.search')}" value="${esc(query)}" style="max-width:320px;margin-bottom:12px">
        ${table(['ad.c.email', 'ad.c.plan', 'ad.c.joined', 'ad.c.used', 'ad.c.balance', 'ad.c.req', 'ad.c.last'], users.users.map((x) => `<tr><td>${esc(x.email)}${x.admin ? ' <span class="faint">admin</span>' : ''}</td>
          <td>${x.plan}${x.status !== 'none' ? ` <span class="faint">${esc(x.status)}</span>` : ''}</td><td>${day(x.created_at)}</td>
          <td>${usd(x.used_usd)} / ${usd(x.allowance_usd)}</td><td>${usd(x.balance_usd)}</td><td>${x.requests}</td><td>${day(x.last_active)}</td></tr>`))}
        <h2>${tr('ad.wishes')} (${m.wishes.length})</h2>${table(['ad.c.when', 'ad.c.email', 'ad.c.text'], m.wishes.map((w) => `<tr><td>${day(w.created_at)}</td><td>${w.email ? `<a class="mail" href="mailto:${esc(w.email)}">${esc(w.email)}</a>` : tr('ad.anon')}</td><td style="white-space:pre-wrap">${esc(w.text)}</td></tr>`))}
        <h2>${tr('ad.waitlist')} (${m.waitlist.length})</h2>${table(['ad.c.when', 'ad.c.email', 'ad.c.topic'], m.waitlist.map((w) => `<tr><td>${day(w.created_at)}</td><td><a class="mail" href="mailto:${esc(w.email)}">${esc(w.email)}</a></td><td>${esc(w.topic)}</td></tr>`))}`;
      const q = document.getElementById('admin-q');
      q.addEventListener('change', async () => { query = q.value; users = await get(`/api/admin/users?q=${encodeURIComponent(query)}`); render(); });
    };
    render(); window.addEventListener('language', render);
  },
  pricing() {
    const note = document.getElementById('checkout-note');
    const show = () => { if (location.search.includes('checkout=cancelled')) note.innerHTML = `<div class="notice warn">${tr('pr.cancelled')}</div>`; };
    show(); window.addEventListener('language', show);
    document.querySelectorAll('[data-plan]').forEach((button) => button.addEventListener('click', async () => {
      const error = document.getElementById('checkout-error');
      error.textContent = ''; button.disabled = true;
      try {
        if (!(await api('/api/me')).user) { location.href = '/login.html?next=/pricing.html&mode=signup'; return; }
        location.href = (await api('/api/checkout', { plan: button.dataset.plan })).url;
      } catch (e) { error.textContent = e.message; button.disabled = false; }
    }));
  },
  async download() {
    const status = document.getElementById('mac-status'), slot = document.getElementById('mac-download');
    let latest = null;
    try { const r = await fetch('/downloads/latest.json', { cache: 'no-store' }); if (r.ok) latest = await r.json(); } catch { /* none yet */ }
    const render = () => {
      if (latest) {
        status.textContent = tr('dl.version', { v: latest.version, mb: latest.size_mb, date: latest.date });
        slot.innerHTML = `<a class="btn primary lg" href="/downloads/${latest.file}">${tr('cta.download')}</a>`;
      } else {
        status.textContent = tr('dl.preparing');
        if (!slot.firstChild) slot.append(waitlistForm('macos'));
      }
    };
    render(); window.addEventListener('language', render);
  },
  login() {
    const params = new URLSearchParams(location.search);
    let mode = params.get('mode') === 'signup' ? 'signup' : 'login';
    const render = () => {
      document.getElementById('title').textContent = tr(mode === 'signup' ? 'auth.signup' : 'auth.signin');
      document.getElementById('submit').textContent = tr(mode === 'signup' ? 'auth.create' : 'auth.signin');
      document.getElementById('switch').textContent = tr(mode === 'signup' ? 'auth.toLogin' : 'auth.toSignup');
      document.getElementById('rule').textContent = mode === 'signup' ? tr('auth.rule') : '';
    };
    render(); window.addEventListener('language', render);
    document.getElementById('switch').addEventListener('click', (e) => { e.preventDefault(); mode = mode === 'signup' ? 'login' : 'signup'; render(); });
    document.getElementById('auth').addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        await api(mode === 'signup' ? '/api/signup' : '/api/login', { email: e.target.email.value, password: e.target.password.value });
        location.href = params.get('next')?.startsWith('/') ? params.get('next') : '/account.html';
      } catch (error) { document.getElementById('error').textContent = error.message; }
    });
  },
  async account() {
    const { user } = await api('/api/me');
    if (!user) { location.href = '/login.html?next=/account.html'; return; }
    const render = () => {
      if (location.search.includes('checkout=success')) document.getElementById('notice').innerHTML = `<div class="notice">${tr('acc.paid')}</div>`;
      const pro = user.plan !== 'free';
      const until = user.current_period_end ? new Date(user.current_period_end * 1000).toLocaleDateString(lang === 'zh' ? 'zh-CN' : 'en') : '';
      document.getElementById('panel').innerHTML = `<p><b>${user.email}</b></p>
        <p>${tr('acc.plan')}: <b>${tr(pro ? (user.plan === 'yearly' ? 'acc.yearly' : 'acc.monthly') : 'acc.free')}</b> <span class="faint">${user.status !== 'none' ? '(' + user.status + ')' : ''}</span></p>
        ${until ? `<p class="muted">${tr('acc.renews')}: ${until}</p>` : ''}
        ${user.usage ? `<p style="margin-top:22px">${tr('acc.usage', { month: user.usage.month, used: user.usage.used_usd.toFixed(2), total: user.usage.allowance_usd.toFixed(2) })}</p>
        <div class="usage-bar"><i style="width:${user.usage.used_percent}%"></i></div>
        <p class="muted small">${tr('acc.balance', { balance: user.usage.balance_usd.toFixed(2) })}${user.usage.credit_usd > 0 ? ' · ' + tr('acc.credit', { credit: user.usage.credit_usd.toFixed(2) }) : ''}</p>
        ${user.usage.balance_usd <= 0 ? `<div class="notice warn">${tr('acc.empty')}</div>` : ''}` : ''}
        <div class="cta">${pro ? `<button class="btn primary" id="portal">${tr('acc.manage')}</button>` : `<a class="btn primary" href="/pricing.html">${tr('acc.upgrade')}</a>`}
        <a class="btn" href="/download.html">${tr('acc.download')}</a><button class="btn" id="logout">${tr('acc.signout')}</button></div><p class="error" id="error"></p>`;
      document.getElementById('logout').onclick = async () => { await api('/api/logout', {}); location.href = '/'; };
      const portal = document.getElementById('portal');
      if (portal) portal.onclick = async () => { try { location.href = (await api('/api/portal', {})).url; } catch (e) { document.getElementById('error').textContent = e.message; } };
    };
    render(); window.addEventListener('language', render);
  },
};

/** Help Center: filter the sidebar as you type, and highlight the section being read in "On this page". */
function docs() {
  const search = document.querySelector('.docs-search');
  if (!search) return;
  search.addEventListener('input', () => {
    const q = search.value.trim().toLowerCase();
    document.querySelectorAll('.docs-nav details').forEach((group) => {
      let any = false;
      group.querySelectorAll('a').forEach((a) => { const hit = !q || a.textContent.toLowerCase().includes(q); a.hidden = !hit; any ||= hit; });
      group.hidden = !any; if (q) group.open = true;
    });
  });
  const links = [...document.querySelectorAll('.docs-toc a')];
  const io = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (e.isIntersecting) links.forEach((a) => a.classList.toggle('on', a.getAttribute('href') === `#${e.target.id}`));
  }), { rootMargin: '-80px 0px -70% 0px' });
  document.querySelectorAll('.docs-main h2[id]').forEach((h) => io.observe(h));
}

function waitlistForm(topic) {
  const form = el(`<form class="inline-form" data-waitlist="${topic}"><input class="input" name="email" type="email" placeholder="you@example.com" required>
    <button class="btn primary" data-i18n="dl.notify">${tr('dl.notify')}</button><p class="error"></p></form>`);
  bindWaitlist(form);
  return form;
}
function bindWaitlist(form) {
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    try { await api('/api/waitlist', { email: form.email.value, topic: form.dataset.waitlist }); form.replaceWith(el(`<div class="notice">${tr('dl.thanks')}</div>`)); }
    catch (error) { form.querySelector('.error').textContent = error.message; }
  });
}

/** Ambient effects: drifting starfield, cursor spotlight, tile glow that follows the pointer, gentle 3D tilt. */
function effects() {
  const canvas = document.getElementById('stars');
  if (canvas && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const ctx = canvas.getContext('2d');
    let stars = [];
    const size = () => { canvas.width = innerWidth * devicePixelRatio; canvas.height = innerHeight * devicePixelRatio;
      stars = Array.from({ length: 90 }, () => ({ x: Math.random() * canvas.width, y: Math.random() * canvas.height, r: Math.random() * 1.4 + .3, v: Math.random() * .25 + .05 })); };
    size(); addEventListener('resize', size);
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const s of stars) {
        s.y -= s.v * devicePixelRatio; if (s.y < 0) s.y = canvas.height;
        ctx.beginPath(); ctx.arc(s.x, s.y, s.r * devicePixelRatio, 0, 7); ctx.fillStyle = `rgba(170,190,255,${.25 + s.r / 3})`; ctx.fill();
      }
      requestAnimationFrame(draw);
    };
    draw();
  }
  addEventListener('pointermove', (e) => { document.documentElement.style.setProperty('--mx', e.clientX + 'px'); document.documentElement.style.setProperty('--my', e.clientY + 'px'); });
  document.querySelectorAll('.tile, .plan').forEach((tile) => {
    tile.addEventListener('pointermove', (e) => {
      const r = tile.getBoundingClientRect(), x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      tile.style.setProperty('--x', `${x * 100}%`); tile.style.setProperty('--y', `${y * 100}%`);
      tile.style.transform = `perspective(900px) rotateX(${(.5 - y) * 4}deg) rotateY(${(x - .5) * 5}deg) translateY(-2px)`;
    });
    tile.addEventListener('pointerleave', () => { tile.style.transform = ''; });
  });
  // Count the stats up when they come into view.
  document.querySelectorAll('.stats b').forEach((b) => {
    const m = b.textContent.match(/^(~?)(\d+)(.*)$/); if (!m) return;
    const [, pre, num, post] = m; b.textContent = pre + '0' + post;
    new IntersectionObserver(([e], o) => { if (!e.isIntersecting) return; o.disconnect(); let i = 0; const end = +num;
      const step = () => { i = Math.min(end, i + Math.ceil(end / 30)); b.textContent = pre + i + post; if (i < end) requestAnimationFrame(step); }; step(); }).observe(b);
  });
  document.querySelectorAll('.mock').forEach((m) => m.append(Object.assign(document.createElement('div'), { className: 'scan' })));
}

window.addEventListener('DOMContentLoaded', () => {
  chrome();
  effects();
  applyLanguage();
  document.querySelectorAll('[data-cockpit]').forEach(cockpitDemo);
  document.querySelectorAll('form[data-waitlist]').forEach(bindWaitlist);
  pages[document.body.dataset.page]?.();
  docs();
  document.querySelectorAll('.wish-form').forEach((form) => form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      await api('/api/wish', { text: form.text.value, email: form.email.value, page: location.pathname });
      form.innerHTML = `<div class="notice">${tr('wish.thanks')}</div>`;
    } catch (error) { form.querySelector('.error').textContent = error.message; button.disabled = false; }
  }));
  const io = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { threshold: 0.12 });
  document.querySelectorAll('.reveal').forEach((node) => io.observe(node));
});
