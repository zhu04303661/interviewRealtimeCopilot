// Site behaviour: language, header/footer, account state, the cockpit demo and page logic.
document.documentElement.classList.add('js');  // enables scroll reveal; content stays visible without JS
const LANGS = { en: 'English', zh: '中文' };
let lang = localStorage.getItem('lang') || (navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en');
const tr = (key, vars = {}) => Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, v), (window.I18N[lang] || {})[key] ?? window.I18N.en[key] ?? key);

function applyLanguage() {
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = tr(el.dataset.i18n); });
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
    <nav class="links">${link('/use-cases.html', 'nav.scenarios', 'use-cases')}${link('/demo.html', 'nav.demo', 'demo')}${link('/pricing.html', 'nav.pricing', 'pricing')}${link('/download.html', 'nav.download', 'download')}</nav>
    <span class="spacer"></span><span class="lang">${Object.entries(LANGS).map(([k, v]) => `<button data-lang="${k}">${v}</button>`).join('')}</span>
    <span id="account-slot"><a class="btn" href="/login.html" data-i18n="nav.signin"></a></span>
    <a class="btn primary" href="/download.html" data-i18n="nav.start"></a></div></header>`));
  document.body.append(el(`<footer><div class="wrap"><span class="brand"><span class="logo">IR</span>Interview Realtime Copilot</span><span class="spacer"></span>
    <a href="/use-cases.html" data-i18n="nav.scenarios"></a><a href="/pricing.html" data-i18n="nav.pricing"></a><a href="/download.html" data-i18n="nav.download"></a>
    <a href="/privacy.html" data-i18n="foot.privacy"></a><a href="/terms.html" data-i18n="foot.terms"></a><span>© ${new Date().getFullYear()}</span></div></footer>`));
  document.querySelectorAll('.lang button').forEach((b) => b.addEventListener('click', () => { lang = b.dataset.lang; localStorage.setItem('lang', lang); applyLanguage(); }));
  api('/api/me').then(({ user }) => {
    if (user) document.getElementById('account-slot').innerHTML = `<a class="btn" href="/account.html">${user.email.split('@')[0]} · ${user.plan === 'free' ? 'Free' : 'Pro'}</a>`;
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

const pages = {
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
        <div class="cta">${pro ? `<button class="btn primary" id="portal">${tr('acc.manage')}</button>` : `<a class="btn primary" href="/pricing.html">${tr('acc.upgrade')}</a>`}
        <a class="btn" href="/download.html">${tr('acc.download')}</a><button class="btn" id="logout">${tr('acc.signout')}</button></div><p class="error" id="error"></p>`;
      document.getElementById('logout').onclick = async () => { await api('/api/logout', {}); location.href = '/'; };
      const portal = document.getElementById('portal');
      if (portal) portal.onclick = async () => { try { location.href = (await api('/api/portal', {})).url; } catch (e) { document.getElementById('error').textContent = e.message; } };
    };
    render(); window.addEventListener('language', render);
  },
};

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

window.addEventListener('DOMContentLoaded', () => {
  chrome();
  applyLanguage();
  document.querySelectorAll('[data-cockpit]').forEach(cockpitDemo);
  document.querySelectorAll('form[data-waitlist]').forEach(bindWaitlist);
  pages[document.body.dataset.page]?.();
  const io = new IntersectionObserver((entries) => entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); } }), { threshold: 0.12 });
  document.querySelectorAll('.reveal').forEach((node) => io.observe(node));
});
