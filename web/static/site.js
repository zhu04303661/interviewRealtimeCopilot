// Shared behaviour: header/footer, account state, API calls and the live cockpit demo.
const api = async (path, body) => {
  const response = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
};

function chrome() {
  const header = document.createElement('header');
  header.className = 'nav';
  header.innerHTML = `<div class="wrap">
    <a class="brand" href="/"><span class="logo">IR</span>Interview Realtime Copilot</a>
    <nav class="links"><a href="/#features">Features<span class="cn"> · 功能</span></a><a href="/demo.html">Demo<span class="cn"> · 演示</span></a><a href="/pricing.html">Pricing<span class="cn"> · 价格</span></a><a href="/download.html">Download<span class="cn"> · 下载</span></a></nav>
    <span class="spacer"></span><span id="account-slot"><a class="btn" href="/login.html">Sign in</a></span>
    <a class="btn primary" href="/download.html">Get started</a></div>`;
  document.body.prepend(header);
  const footer = document.createElement('footer');
  footer.innerHTML = `<div class="wrap"><span>© ${new Date().getFullYear()} Interview Realtime Copilot</span><span class="spacer"></span>
    <a href="/pricing.html">Pricing</a><a href="/download.html">Download</a><a href="/privacy.html">Privacy · 隐私</a><a href="/terms.html">Terms · 条款</a></div>`;
  document.body.append(footer);
  api('/api/me').then(({ user }) => {
    if (user) document.getElementById('account-slot').innerHTML = `<a class="btn" href="/account.html">${user.email.split('@')[0]} · ${user.plan === 'free' ? 'Free' : 'Pro'}</a>`;
    window.dispatchEvent(new CustomEvent('account', { detail: user }));
  }).catch(() => {});
}

/** The scripted cockpit: an interviewer question, its translation, the question card and a streamed bilingual hint. */
function cockpitDemo(root, { loop = true } = {}) {
  const script = [
    { who: 'Interviewer · 面试官', text: 'How did you split the uplink processing between the FPGA and the DSP, and what were the latency trade-offs?',
      zh: '你是如何在 FPGA 和 DSP 之间划分上行处理的？延迟上做了哪些取舍？' },
    { question: 'How did you split the uplink processing between the FPGA and the DSP, and what were the latency trade-offs?' },
    { hint: [['EN', ['FPGA did the per-subcarrier, fixed-latency work: FFT, RE demapping, channel-estimate correlations.',
      'The DSP ran the slower statistics and small matrix maths, two TTIs behind, which kept the FPGA pipeline deterministic.',
      'The trade-off: a 2-TTI feedback delay, which I mitigated with predictive smoothing.']],
      ['中文', ['FPGA 负责每个子载波、时延固定的计算：FFT、RE 解映射、信道估计相关。', 'DSP 处理较慢的统计和小矩阵运算，滞后两个 TTI，保证 FPGA 流水线确定性。', '代价是 2 个 TTI 的反馈延迟，我用预测平滑来弥补。']]] },
  ];
  const body = root.querySelector('.mock-body');
  const clock = root.querySelector('.clock');
  let seconds = 0;
  setInterval(() => { seconds++; clock.textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; }, 1000);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const type = async (el, text, speed = 18) => { el.classList.add('typing'); for (const ch of text) { el.textContent += ch; await wait(speed); } el.classList.remove('typing'); };
  async function run() {
    body.innerHTML = '';
    const line = document.createElement('div'); line.className = 'line fade-in';
    line.innerHTML = `<span class="stamp">${script[0].who}</span><div class="text"></div><div class="zh"></div>`;
    body.append(line);
    await type(line.querySelector('.text'), script[0].text, 26);
    await wait(400); line.querySelector('.zh').textContent = script[0].zh;
    await wait(600);
    const q = document.createElement('div'); q.className = 'q fade-in';
    q.innerHTML = `<span class="stamp">Question · 问题</span><div style="margin-top:6px">${script[1].question}</div>`;
    body.append(q);
    await wait(500);
    const hint = document.createElement('div'); hint.className = 'hint fade-in'; body.append(hint);
    for (const [lang, bullets] of script[2].hint) {
      const label = document.createElement('div'); label.className = 'lang'; label.textContent = lang; hint.append(label);
      const ul = document.createElement('ul'); hint.append(ul);
      for (const bullet of bullets) { const li = document.createElement('li'); ul.append(li); await type(li, bullet, 14); }
    }
    if (loop) { await wait(5000); run(); }
  }
  run();
}

window.addEventListener('DOMContentLoaded', () => {
  chrome();
  document.querySelectorAll('[data-cockpit]').forEach((el) => cockpitDemo(el));
  document.querySelectorAll('form[data-waitlist]').forEach((form) => form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const message = form.querySelector('.error');
    try {
      await api('/api/waitlist', { email: form.email.value, topic: form.dataset.waitlist });
      form.innerHTML = '<div class="notice">Thanks — we will email you. · 已登记，我们会邮件通知你。</div>';
    } catch (error) { message.textContent = error.message; }
  }));
});
