"""Generates the website pages (web/static/*.html) and the translations (web/static/i18n.js).

Every visible string is written once here in English and Chinese: t("key", en, zh)
puts a data-i18n placeholder in the page and the pair in the dictionary. The
language switcher in site.js swaps them; nothing is mixed on screen.

    python3 web/build_site.py
"""

from __future__ import annotations

import json
from pathlib import Path

STATIC = Path(__file__).parent / "static"
STRINGS: dict[str, dict[str, str]] = {"en": {}, "zh": {}}


def t(key: str, en: str, zh: str, tag: str = "span", cls: str = "") -> str:
    STRINGS["en"][key], STRINGS["zh"][key] = en, zh
    return f'<{tag} data-i18n="{key}"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{en}</{tag}>'


def page(name: str, title: tuple[str, str], body: str) -> None:
    key = f"title.{name}"
    STRINGS["en"][key], STRINGS["zh"][key] = title
    head = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title data-i18n="{key}">{title[0]}</title><meta name="description" content="Real-time interview copilot: live transcript, '
            f'question detection, answer hints grounded in your own resume, spoken practice and debriefs.">'
            f'<meta name="keywords" content="AI interview assistant, interview copilot, real-time interview help, interview answer generator, coding interview AI, AI面试助手, 实时面试辅助, 面试外挂, 面试神器, 英文面试, 跨语言面试, 面试翻译, 编程面试代码, 面试题答案, 模拟面试">'
            f'<meta property="og:title" content="{title[0]}"><meta property="og:type" content="website"><meta property="og:url" content="https://copilot.xichiuk.com/{"" if name == "index" else name + ".html"}">'
            f'<meta property="og:description" content="Real-time AI interview assistant: live translation, question detection, answers from your resume, coding help from your screen.">'
            f'<link rel="canonical" href="https://copilot.xichiuk.com/{"" if name == "index" else name + ".html"}">'
            f'<script type="application/ld+json">{LD}</script>'
            f'<link rel="stylesheet" href="/site.css"><script src="/i18n.js" defer></script><script src="/site.js" defer></script></head><body data-page="{name}">'
            '<svg width="0" height="0" style="position:absolute"><defs><linearGradient id="ig" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9d85ff"/><stop offset=".5" stop-color="#5b8cff"/><stop offset="1" stop-color="#3fe0ff"/></linearGradient></defs></svg>'
            '<div class="bg-grid"></div><div class="aurora"><i></i><i></i><i></i></div><canvas id="stars"></canvas><div class="spot"></div>')
    (STATIC / f"{name}.html").write_text(head + body + "</body></html>\n")


LD = json.dumps({"@context": "https://schema.org", "@graph": [
    {"@type": "SoftwareApplication", "name": "Interview Realtime Copilot", "applicationCategory": "BusinessApplication", "operatingSystem": "macOS 14.2+",
     "description": "AI interview assistant (AI面试助手) that listens to live interviews, translates English and Chinese in real time, detects each question and suggests answers from your own resume; solves coding questions from your screen; spoken mock interviews and debriefs.",
     "offers": [{"@type": "Offer", "price": "0", "priceCurrency": "USD", "name": "Free"}, {"@type": "Offer", "price": "29", "priceCurrency": "USD", "name": "Pro monthly"},
                {"@type": "Offer", "price": "199", "priceCurrency": "USD", "name": "Pro yearly"}]},
    {"@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": "What is an AI interview assistant (面试外挂 / AI面试助手)?", "acceptedAnswer": {"@type": "Answer", "text": "A desktop app that listens to your live interview, recognises each question and shows a short answer drawn from your own resume and notes, with English–Chinese translation."}},
        {"@type": "Question", "name": "Can it help if my English is not fluent?", "acceptedAnswer": {"@type": "Answer", "text": "Yes. Every interviewer line is translated into Chinese as it is spoken, and hints give natural English you can say directly."}},
        {"@type": "Question", "name": "Does it help with coding interviews?", "acceptedAnswer": {"@type": "Answer", "text": "Yes. It reads the coding problem on your screen and writes a working solution with complexity and edge cases, hidden from screen sharing."}},
        {"@type": "Question", "name": "I have no time to prepare. Can it still help?", "acceptedAnswer": {"@type": "Answer", "text": "Upload your resume, notes or the job description; prepared questions are extracted for spoken practice and live hints come from the same files."}}]}]}, ensure_ascii=False)

COCKPIT = ('<div class="stage"><div class="scene" data-scene>'
           # The meeting the candidate is in (what the interviewer and candidate see on the call).
           '<div class="meeting"><div class="meeting-bar"><span class="rec"></span>' + t("scene.call", "Interview · AccelerComm", "面试 · AccelerComm")
           + '<span class="spacer"></span><span class="faint">45:12</span></div>'
           '<div class="tiles"><div class="tile-v" data-speaker="interviewer"><div class="avatar">AK</div><span class="name">'
           + t("scene.interviewer", "Interviewer", "面试官") + '</span><span class="wave"><i></i><i></i><i></i></span></div>'
           '<div class="tile-v" data-speaker="me"><div class="avatar me">LM</div><span class="name">' + t("scene.you", "You", "你")
           + '</span><span class="wave"><i></i><i></i><i></i></span></div></div>'
           '<div class="controls"><span>🎙</span><span>📷</span><span>🖥</span><span class="leave">✕</span></div></div>'
           # The cockpit floating above it; never captured by screen sharing.
           '<div class="mock" data-cockpit><div class="mock-head"><span class="dot"></span>'
           + t("mock.listening", "Listening", "聆听中") + '<span class="stealth">' + t("scene.hidden", "Hidden from screen share", "共享屏幕不可见")
           + '</span></div><div class="mock-body"></div><div class="mock-foot">' + t("mock.solve", "Solve screen ⌥S", "截屏解答 ⌥S")
           + '<span class="clock">00:00</span></div></div></div>'
           '<div class="phases"><span data-phase="upload">' + t("phase.upload", "1 · Upload resume & notes", "1 · 上传简历和资料") + '</span><span data-phase="hear">' + t("phase.hear", "2 · Hears the question", "2 · 听到问题") + '</span><span data-phase="understand">'
           + t("phase.understand", "3 · Understands it", "3 · 理解问题") + '</span><span data-phase="hint">'
           + t("phase.hint", "4 · Hints your answer", "4 · 提示回答") + '</span><span data-phase="answer">'
           + t("phase.answer", "5 · You answer", "5 · 你来作答") + '</span></div></div>')

SCENARIOS = [
    ("video", "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"url(#ig)\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M15 10l5-3v10l-5-3z\"/><rect x=\"2\" y=\"6\" width=\"13\" height=\"12\" rx=\"2\"/></svg>", "Video interviews on Zoom, Teams or Meet", "Zoom、Teams、Meet 视频面试",
     "The copilot hears the meeting and your microphone separately, recognises each question once the interviewer finishes, and streams a one-minute answer built from your resume — while you keep eye contact.",
     "分别听取会议声音和你的麦克风，在面试官说完时识别出完整问题，并基于你的简历给出一分钟内能说完的回答，你可以一直看着镜头。"),
    ("language", "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"url(#ig)\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18\"/></svg>", "Interviewing in your second language", "用第二语言面试",
     "Every interviewer line is translated as it is spoken (English ↔ Chinese), and hints come in both languages, so you understand precisely and answer fluently.",
     "面试官的每句话实时翻译（中英互译），回答提示同时给出两种语言，听得准、答得顺。"),
    ("technical", "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"url(#ig)\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><rect x=\"3\" y=\"4\" width=\"18\" height=\"12\" rx=\"2\"/><path d=\"M8 20h8M9 9l-2 2 2 2M15 9l2 2-2 2\"/></svg>", "Technical and coding rounds", "技术面与编程题",
     "Press ⌥S — or let auto-capture do it — and the copilot reads the coding problem, diagram or error on your screen and explains a solution with its trade-offs.",
     "按 ⌥S，或交给自动截屏：读取屏幕上的编程题、架构图或报错，给出解法和取舍。"),
    ("prep", "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"url(#ig)\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M4 19V5a2 2 0 012-2h12v16H6a2 2 0 00-2 2z\"/><path d=\"M8 7h6M8 11h6\"/></svg>", "Rehearsing your prepared Q&A", "演练你准备的问答",
     "Upload your preparation document and every prepared question is extracted. A spoken AI interviewer asks them in order, at random or improvises, follows up once, and never repeats itself.",
     "上传准备文档，自动提取所有准备好的问题。AI 面试官用语音按顺序、随机或临场提问，每题追问一次，不重复。"),
    ("midanswer", "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"url(#ig)\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M12 20h9\"/><path d=\"M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z\"/></svg>", "Getting stuck mid-answer", "回答到一半卡住",
     "Already talking? Expand answer continues from what you just said with the most valuable facts you have not mentioned yet, in under a minute.",
     "已经开口但思路断了？「补充回答」会接着你刚说的内容，补上你还没提到的关键事实。"),
    ("after", "<svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"url(#ig)\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\"><path d=\"M3 3v18h18\"/><path d=\"M7 15l4-4 3 3 5-6\"/></svg>", "Improving after every interview", "每场面试后的复盘提升",
     "Each session ends with a debrief: every question reviewed, what was missing, a stronger spoken version — and the recording to replay.",
     "每场结束都有复盘：逐题点评、指出遗漏，并给出更好的说法，还能回放录音。"),
]


def scenario_tiles(detail: bool) -> str:
    tiles = []
    for key, icon, en_title, zh_title, en_text, zh_text in SCENARIOS:
        tiles.append(f'<div class="tile{" wide" if detail else ""} reveal"><div class="ico">{icon}</div>'
                     + t(f"sc.{key}.title", en_title, zh_title, "h3") + t(f"sc.{key}.text", en_text, zh_text, "p") + "</div>")
    return '<div class="bento">' + "".join(tiles) + "</div>"


def build() -> None:
    page("index", ("Interview Realtime Copilot — your private co-pilot for live interviews", "Interview Realtime Copilot — 你的私人面试副驾"), f'''
<section class="hero"><div class="wrap hero-grid"><div>
<span class="pill"><b>{t("hero.new", "NEW", "新")}</b>{t("hero.pill", "Spoken practice with your own prepared questions", "用你自己的准备题做语音模拟面试")}</span>
<h1>{t("hero.h1a", "Answer every interview question", "每一道面试题，")}<br><span class="grad-text">{t("hero.h1b", "with calm confidence.", "都能从容作答。")}</span></h1>
{t("hero.lead", "Interview Realtime Copilot listens to the interviewer, translates as they speak, spots each question and streams a concise answer built from your own resume and notes.", "Interview Realtime Copilot 实时聆听面试官、同步翻译、识别每一个问题，并基于你自己的简历和准备资料给出简洁的回答提示。", "p", "lead")}
<div class="cta"><a class="btn primary lg" href="/download.html">{t("cta.download", "Download for macOS", "下载 macOS 版")}</a><a class="btn lg" href="/demo.html">{t("cta.demo", "Watch the demo", "观看演示")}</a></div>
<div class="trust">{t("trust.1", "Local-first: your files stay on your Mac", "本地优先：文件只存在你的 Mac")}{t("trust.2", "Hidden from screen sharing", "共享屏幕时不可见")}{t("trust.3", "No API key needed", "无需 API 密钥")}</div>
</div>{COCKPIT}</div></section>

<section style="padding-top:0"><div class="wrap"><div class="stats reveal">
<div><b class="grad-text">~2 s</b>{t("stat.1", "from the end of a question to the first hint", "从问题说完到第一条提示")}</div>
<div><b class="grad-text">EN ↔ 中文</b>{t("stat.2", "live translation and bilingual hints", "实时翻译与双语提示")}</div>
<div><b class="grad-text">100%</b>{t("stat.3", "of your prepared Q&A turned into practice", "准备问答全部变成练习题")}</div>
<div><b class="grad-text">40</b>{t("stat.4", "questions reviewed in each debrief", "每场复盘最多点评的题数")}</div>
</div></div></section>

<section id="uses"><div class="wrap"><div class="center reveal"><span class="eyebrow">{t("use.eyebrow", "Why people use it", "为什么选择它")}</span><h2>{t("use.h2", "Four problems it solves on interview day", "面试当天，它帮你解决四个难题")}</h2></div><div class="bento"><div class="tile wide reveal"><div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="url(#ig)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/></svg></div>{t("use.lang.t", "Interview in English without the language barrier", "英语不够好，也能从容面对英文面试", "h3")}{t("use.lang.p", "Every question is translated into Chinese the moment it is asked, and each hint gives you natural English you can say straight away.", "面试官每说一句，立刻翻译成中文；回答提示直接给出地道、可以照着说的英文。", "p")}</div><div class="tile wide reveal"><div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="url(#ig)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5a3 3 0 00-6 .5A3 3 0 004 11a3 3 0 002 5 3 3 0 006 1V5z"/><path d="M12 5a3 3 0 016 .5A3 3 0 0120 11a3 3 0 01-2 5 3 3 0 01-6 1"/></svg></div>{t("use.expert.t", "An expert listening in, answering with real knowledge", "AI 实时旁听，用专业知识帮你解答", "h3")}{t("use.expert.p", "The copilot follows the conversation and answers technical questions with precise domain knowledge — mechanisms, trade-offs, numbers — combined with your own experience.", "AI 全程旁听，遇到专业问题时结合你的经历，用准确的专业知识给出机制、取舍和数据。", "p")}</div><div class="tile wide reveal"><div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="url(#ig)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="13" r="8"/><path d="M12 9v4l3 2M9 2h6"/></svg></div>{t("use.prep.t", "No time to prepare? Start from what you have", "来不及准备？用现有资料马上开始", "h3")}{t("use.prep.p", "Drop in your resume, notes or the job description. Questions are extracted and practised out loud in minutes, and every live hint is drawn from those files.", "放入简历、笔记或职位描述，几分钟内提取问题并开始语音练习；正式面试时每条提示都来自这些资料。", "p")}</div><div class="tile wide reveal"><div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="url(#ig)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M9 9l-2 2 2 2M15 9l2 2-2 2"/></svg></div>{t("use.code.t", "Coding questions solved from your screen", "监控屏幕，快速写出面试题代码", "h3")}{t("use.code.p", "When a coding problem appears on your screen, the copilot reads it and writes a working solution with its complexity and edge cases — hidden from screen share.", "屏幕上出现编程题时，AI 自动读取题目，写出可运行的代码并说明复杂度和边界情况；共享屏幕中不可见。", "p")}</div></div></div></section>

<section id="scenarios"><div class="wrap"><div class="center reveal"><span class="eyebrow">{t("sc.eyebrow", "Built for real interview moments", "为真实的面试时刻而生")}</span>
<h2>{t("sc.h2", "The six moments it handles for you", "它为你解决的六个关键时刻")}</h2>
{t("sc.lead", "From the first video call to the final debrief — wherever an interview gets hard, the copilot has a specific answer.", "从第一次视频面试到最后的复盘——面试中每个容易卡住的时刻，它都有对应的解决办法。", "p", "lead")}</div>
{scenario_tiles(False)}<div class="center" style="margin-top:34px"><a class="btn" href="/use-cases.html">{t("sc.more", "Explore every use case →", "查看全部使用场景 →")}</a></div></div></section>

<section><div class="wrap"><div class="center reveal"><span class="eyebrow">{t("how.eyebrow", "How it works", "使用方式")}</span><h2>{t("how.h2", "Ready in four steps", "四步即可开始")}</h2></div>
<div class="timeline">
<div class="reveal">{t("how.1t", "Create a goal", "创建目标", "h3")}{t("how.1p", "One role at one company, plus the job description.", "一个公司的一个职位，再加上职位描述。", "p")}</div>
<div class="reveal">{t("how.2t", "Add your resume and notes", "上传简历和资料", "h3")}{t("how.2p", "PDF, Word or Markdown up to 500 MB; every prepared question is extracted.", "支持 PDF、Word、Markdown，最大 500 MB，自动提取全部准备题。", "p")}</div>
<div class="reveal">{t("how.3t", "Practise out loud", "语音练习", "h3")}{t("how.3p", "A spoken AI interviewer asks your questions and follows up.", "AI 面试官用语音提问并追问。", "p")}</div>
<div class="reveal">{t("how.4t", "Go Live", "正式面试", "h3")}{t("how.4p", "Open your meeting app; the copilot listens, translates and hints.", "打开会议软件，副驾实时聆听、翻译和提示。", "p")}</div>
</div></div></section>

<section><div class="wrap split"><div class="reveal"><span class="eyebrow">{t("priv.eyebrow", "Privacy", "隐私")}</span>
<h2>{t("priv.h2", "Your preparation never leaves your Mac.", "你的准备资料不离开你的 Mac。")}</h2>
<ul class="checks"><li>{t("priv.1", "Goals, documents, transcripts, debriefs and recordings are stored locally.", "目标、资料、字幕、复盘和录音都保存在本机。")}</li>
<li>{t("priv.2", "Audio is processed only during a session you start.", "只在你开始会话时处理音频。")}</li>
<li>{t("priv.3", "The cockpit is excluded from screen sharing and recordings.", "面试窗口不会出现在共享屏幕和录屏中。")}</li></ul></div>
<div class="glass reveal">{t("priv.card.t", "Answers only from what is true", "只说真实的经历", "h3")}{t("priv.card.p", "Hints use facts from your resume and notes. When something is not in your materials, the copilot tells you how to answer honestly instead of inventing experience.", "回答提示只引用你简历和资料中的事实。资料里没有的内容，它会建议你如何如实回答，而不是编造经历。", "p", "muted")}</div></div></section>

<section><div class="wrap"><div class="final reveal"><h2>{t("final.h2", "Walk into your next interview prepared.", "带着准备，走进下一场面试。")}</h2>
{t("final.p", "Start free with two practice sessions a month. Upgrade when the interviews get real.", "每月 2 次免费练习，面试真正来临时再升级。", "p", "lead")}
<div class="cta" style="justify-content:center"><a class="btn primary lg" href="/download.html">{t("cta.start", "Get started free", "免费开始")}</a><a class="btn lg" href="/pricing.html">{t("cta.pricing", "See pricing", "查看价格")}</a></div></div></div></section>''')

    page("use-cases", ("Use cases — Interview Realtime Copilot", "使用场景 — Interview Realtime Copilot"), f'''
<section class="hero"><div class="wrap center"><span class="eyebrow">{t("uc.eyebrow", "Use cases", "使用场景")}</span>
<h1>{t("uc.h1a", "One copilot,", "一个副驾，")}<br><span class="grad-text">{t("uc.h1b", "every kind of interview.", "覆盖每一种面试。")}</span></h1>
{t("uc.lead", "Here is exactly what the copilot does in each situation — and what you see on screen.", "每种情况下它具体做什么、你在屏幕上看到什么，都在这里。", "p", "lead")}</div></section>
<section style="padding-top:0"><div class="wrap">{scenario_tiles(True)}</div></section>
<section><div class="wrap split"><div class="reveal"><span class="eyebrow">{t("uc.flow.eyebrow", "In the room", "面试现场")}</span><h2>{t("uc.flow.h2", "What a live question looks like", "一道实时问题的完整过程")}</h2>
<ul class="checks"><li>{t("uc.flow.1", "The interviewer's words appear as they speak, with the translation underneath.", "面试官说话时字幕实时出现，下方附译文。")}</li>
<li>{t("uc.flow.2", "Pauses in the middle of a question do not split it; the finished question becomes a card.", "问题中间的停顿不会把它切开，说完后变成问题卡片。")}</li>
<li>{t("uc.flow.3", "Three or four speakable bullets stream in, grounded in your materials.", "三到四条可直接说出口的要点逐字出现，依据你的资料。")}</li>
<li>{t("uc.flow.4", "Click Suggest answer or Expand answer on any line when you want more.", "需要时，在任意一行点「生成回答」或「补充回答」。")}</li></ul></div>{COCKPIT}</div></section>''')

    page("demo", ("Demo — Interview Realtime Copilot", "演示 — Interview Realtime Copilot"), f'''
<section class="hero"><div class="wrap hero-grid"><div><span class="eyebrow">{t("demo.eyebrow", "Live demo", "实时演示")}</span>
<h1>{t("demo.h1a", "See a question", "看一道问题")}<br><span class="grad-text">{t("demo.h1b", "answered in seconds.", "如何在几秒内被回答。")}</span></h1>
{t("demo.lead", "This is the cockpit you see during an interview. It floats above your meeting, stays hidden from screen sharing and never needs a click.", "这是面试时你看到的窗口：悬浮在会议之上、共享屏幕时不可见，全程无需点击。", "p", "lead")}
<ul class="checks"><li>{t("demo.1", "Live caption and translation", "实时字幕与翻译")}</li><li>{t("demo.2", "Question card when the interviewer finishes", "面试官说完即生成问题卡片")}</li><li>{t("demo.3", "Bilingual one-minute hint from your resume", "基于简历的一分钟双语提示")}</li></ul>
<div class="cta"><a class="btn primary lg" href="/download.html">{t("cta.try", "Try it yourself", "亲自试用")}</a></div></div>{COCKPIT}</div></section>''')

    plan_cta = lambda plan, en, zh: f'<button class="btn primary" data-plan="{plan}">{t(f"plan.{plan}.cta", en, zh)}</button>'  # noqa: E731
    page("pricing", ("Pricing — Interview Realtime Copilot", "价格 — Interview Realtime Copilot"), f'''
<section class="hero"><div class="wrap center"><span class="eyebrow">{t("pr.eyebrow", "Pricing", "价格")}</span>
<h1>{t("pr.h1a", "Simple plans.", "简单的方案，")}<br><span class="grad-text">{t("pr.h1b", "Cancel anytime.", "随时可取消。")}</span></h1>
{t("pr.lead", "AI usage is included as a monthly allowance — no API key, no surprise bills.", "每月包含 AI 使用额度——无需 API 密钥，没有意外账单。", "p", "lead")}<div id="checkout-note"></div>
<div class="plans">
<div class="plan">{t("plan.free.name", "Free", "免费版", "h3")}<div class="price">$0</div>{t("plan.free.sub", "Try it on your next practice.", "在下一次练习中试试。", "p", "muted small")}
<ul><li>{t("plan.free.1", "$1 of AI usage every month — about 2 practice sessions", "每月 $1 AI 额度，约可做 2 次语音练习")}</li><li>{t("plan.free.2", "Live translation and hints", "实时翻译与提示")}</li><li>{t("plan.free.3", "Prepared-question extraction", "自动提取准备题")}</li><li>{t("plan.free.4", "A debrief after each session", "每场会话的复盘")}</li></ul>
<a class="btn" href="/download.html">{t("cta.download", "Download for macOS", "下载 macOS 版")}</a></div>
<div class="plan">{t("plan.monthly.name", "Pro monthly", "Pro 月付", "h3")}<div class="price">$29<small>{t("per.month", " / month", " / 月")}</small></div>{t("plan.monthly.sub", "For an active job search.", "适合正在求职。", "p", "muted small")}
<ul><li>{t("plan.pro.1", "$20 of AI usage every month — hours of live interviews", "每月 $20 AI 额度，足够数小时实时面试")}</li><li>{t("plan.pro.2", "Spoken practice and debriefs", "语音练习与复盘")}</li><li>{t("plan.pro.3", "Solve screen and auto-capture", "截屏解答与自动截屏")}</li><li>{t("plan.pro.4", "Recordings and full debriefs", "录音与完整复盘")}</li></ul>
{plan_cta("monthly", "Subscribe monthly", "订阅月付")}</div>
<div class="plan featured"><span class="tag">{t("plan.best", "BEST VALUE", "最划算")}</span>{t("plan.yearly.name", "Pro yearly", "Pro 年付", "h3")}<div class="price">$199<small>{t("per.year", " / year", " / 年")}</small></div>{t("plan.yearly.sub", "Save 43% — about $16.60 a month.", "节省 43%，约每月 $16.60。", "p", "muted small")}
<ul><li>{t("plan.y.1", "Everything in Pro monthly", "包含 Pro 月付全部功能")}</li><li>{t("plan.y.2", "Early access to Windows", "抢先体验 Windows 版")}</li><li>{t("plan.y.3", "Priority support", "优先支持")}</li></ul>
{plan_cta("yearly", "Subscribe yearly", "订阅年付")}</div></div><p class="error" id="checkout-error"></p></div></section>
<section style="padding-top:0"><div class="wrap"><h2 class="center">{t("faq.h2", "Questions", "常见问题")}</h2><div class="faq">
<details><summary>{t("faq.1q", "Do I need my own OpenAI key?", "需要自己的 OpenAI 密钥吗？")}</summary>{t("faq.1a", "No. Every plan includes a monthly AI allowance (Free $1, Pro $20). When it runs out, the app tells you and you can upgrade — or use your own key.", "不需要。每个套餐都含每月 AI 额度（免费 $1，Pro $20），用完时应用会提示你升级，也可以填写自己的密钥。", "p")}</details>
<details><summary>{t("faq.2q", "Where is my data stored?", "我的数据存在哪里？")}</summary>{t("faq.2a", "On your Mac: documents, transcripts, debriefs and recordings. Only the audio and text needed for a live answer are sent to the AI models during a session.", "在你的 Mac 上：资料、字幕、复盘和录音。只有会话中生成回答所需的音频和文字会发送给 AI 模型。", "p")}</details>
<details><summary>{t("faq.3q", "Can I cancel?", "可以取消吗？")}</summary>{t("faq.3a", "Yes, anytime from your account page. Pro stays active until the end of the paid period.", "可以，随时在账号页取消，已付费周期内仍可使用 Pro。", "p")}</details>
<details><summary>{t("faq.4q", "Which platforms are supported?", "支持哪些系统？")}</summary>{t("faq.4a", "macOS 14.2 or later today; Windows is coming.", "目前支持 macOS 14.2 及以上，Windows 即将推出。", "p")}</details>
</div></div></section>''')

    page("download", ("Download — Interview Realtime Copilot", "下载 — Interview Realtime Copilot"), f'''
<section class="hero"><div class="wrap split"><div><span class="eyebrow">{t("dl.eyebrow", "Download", "下载")}</span><h1>{t("dl.h1", "Get the desktop app.", "下载桌面应用。")}</h1>
{t("dl.lead", "The copilot runs on your Mac, next to your meeting app.", "应用在你的 Mac 上运行，配合会议软件使用。", "p", "lead")}
<div class="card" style="margin-top:26px">{t("dl.mac", "macOS 14.2 or later · Apple Silicon (M1–M4)", "macOS 14.2 及以上 · Apple 芯片（M1–M4）", "h3")}<p class="muted small" id="mac-status" data-i18n="dl.checking">{"Checking for the current build…"}</p><div id="mac-download"></div>
{t("dl.key", "Sign in with your website account: every plan includes a monthly AI allowance, no API key needed. You can also add your own OpenAI key in Settings.", "用网站账号登录即可：每个套餐都包含每月 AI 额度，无需 API 密钥；也可以在设置中填写自己的 OpenAI 密钥。", "p", "notice small")}
{t("dl.gatekeeper", "Preview builds are not yet notarised by Apple: after the first launch, open System Settings → Privacy & Security and click “Open Anyway”.", "测试版尚未经 Apple 公证：首次启动后，打开「系统设置 → 隐私与安全性」，点击「仍要打开」。", "p", "faint small")}</div>
<div class="card" style="margin-top:16px">{t("dl.win", "Windows — coming soon", "Windows——即将推出", "h3")}{t("dl.win.p", "Leave your email and we will tell you when it is ready.", "留下邮箱，发布时通知你。", "p", "muted small")}
<form class="inline-form" data-waitlist="windows"><input class="input" name="email" type="email" placeholder="you@example.com" required><button class="btn primary">{t("dl.notify", "Notify me", "通知我")}</button><p class="error"></p></form></div></div>
<div class="glass">{t("dl.after", "After installing", "安装之后", "h3")}<ul class="checks"><li>{t("dl.a1", "Allow the microphone when asked.", "按提示允许麦克风。")}</li><li>{t("dl.a2", "For live interviews, allow System Audio Recording so the copilot hears the meeting.", "实时面试需要允许「系统录音」，以便听到会议声音。")}</li><li>{t("dl.a3", "Create a goal, add your resume and notes, and start a practice session.", "创建目标、上传简历和资料，然后开始一次语音练习。")}</li></ul></div></div></section>''')
    t("dl.preparing", "The preview build is being prepared — leave your email to get it first.", "测试版正在准备中——留下邮箱，第一时间获取。")
    t("dl.thanks", "Thanks — we will email you.", "已登记，我们会邮件通知你。")
    t("dl.version", "Version {v} · {mb} MB · {date}", "版本 {v} · {mb} MB · {date}")

    page("login", ("Sign in — Interview Realtime Copilot", "登录 — Interview Realtime Copilot"), f'''
<div class="wrap"><div class="auth"><h2 id="title" style="margin-top:0" data-i18n="auth.signin">Sign in</h2>
<form id="auth"><label class="field">{t("auth.email", "Email", "邮箱")}<input class="input" name="email" type="email" autocomplete="email" required></label>
<label class="field"><span><span data-i18n="auth.password">Password</span> <span class="faint" id="rule"></span></span><input class="input" name="password" type="password" autocomplete="current-password" required></label>
<p class="error" id="error"></p><button class="btn primary lg" style="width:100%" id="submit" data-i18n="auth.signin">Sign in</button></form>
<p class="small muted center"><a href="#" id="switch" data-i18n="auth.toSignup">New here? Create an account</a></p></div></div>''')
    for key, en, zh in [("auth.signin", "Sign in", "登录"), ("auth.signup", "Create your account", "创建账号"), ("auth.create", "Create account", "注册"),
                        ("auth.password", "Password", "密码"), ("auth.rule", "(at least 10 characters)", "（至少 10 位）"),
                        ("auth.toSignup", "New here? Create an account", "第一次来？创建账号"), ("auth.toLogin", "Already registered? Sign in", "已有账号？登录")]:
        t(key, en, zh)

    page("account", ("Account — Interview Realtime Copilot", "账号 — Interview Realtime Copilot"), f'''
<div class="wrap" style="max-width:820px;padding:80px 28px"><span class="eyebrow">{t("acc.eyebrow", "Account", "账号")}</span><h1 style="font-size:44px">{t("acc.h1", "Your subscription", "你的订阅")}</h1>
<div id="notice"></div><div class="card" id="panel"><p class="muted" data-i18n="acc.loading">Loading…</p></div></div>''')
    for key, en, zh in [("acc.loading", "Loading…", "加载中…"), ("acc.plan", "Plan", "套餐"), ("acc.free", "Free", "免费版"), ("acc.monthly", "Pro monthly", "Pro 月付"),
                        ("acc.yearly", "Pro yearly", "Pro 年付"), ("acc.renews", "Renews or ends on", "续费或到期日"), ("acc.manage", "Manage billing", "管理订阅"),
                        ("acc.upgrade", "Upgrade to Pro", "升级到 Pro"), ("acc.download", "Download the app", "下载应用"), ("acc.signout", "Sign out", "退出登录"),
                        ("acc.paid", "Payment received — Pro activates as soon as Stripe confirms it, usually within seconds.", "已收到付款——Stripe 确认后立即开通 Pro，通常只需几秒。"),
                        ("pr.cancelled", "Checkout was cancelled — nothing was charged.", "已取消支付，未产生扣款。"),
                        ("acc.usage", "AI allowance for {month}: ${used} of ${total} used", "{month} AI 额度：已用 ${used} / ${total}"),
                        ("acc.balance", "Remaining: ${balance}", "剩余：${balance}"), ("acc.credit", "includes ${credit} credit", "含 ${credit} 余额"),
                        ("acc.empty", "This month's AI allowance is used up. Upgrade to Pro for a larger monthly allowance.", "本月 AI 额度已用完，升级 Pro 可获得更多每月额度。")]:
        t(key, en, zh)

    page("privacy", ("Privacy — Interview Realtime Copilot", "隐私 — Interview Realtime Copilot"), f'''
<div class="wrap" style="max-width:820px;padding:80px 28px">{t("pv.h1", "Privacy", "隐私", "h1")}
{t("pv.1t", "Stored on your Mac", "保存在你的 Mac 上", "h3")}{t("pv.1p", "Goals, documents, extracted questions, transcripts, debriefs and recordings are kept in the app's local data folder.", "目标、资料、提取的问题、字幕、复盘和录音都保存在应用的本地数据文件夹中。", "p", "muted")}
{t("pv.2t", "Sent for processing", "处理时发送的内容", "h3")}{t("pv.2p", "During a session you start, audio and the text needed to answer — the question and relevant passages of your materials — are sent to the speech and language models. Nothing is sent when no session is running.", "在你开始的会话中，音频和生成回答所需的文字（问题及资料中的相关段落）会发送给语音和语言模型。没有会话时不发送任何内容。", "p", "muted")}
{t("pv.3t", "This website", "本网站", "h3")}{t("pv.3p", "We store your email, a password hash and your subscription status. Payments are processed by Stripe; we never see your card number.", "我们保存你的邮箱、密码哈希和订阅状态。付款由 Stripe 处理，我们不会接触你的卡号。", "p", "muted")}
{t("pv.note", "This is a plain-language summary, not legal advice. A full policy will be published before general availability.", "以上为通俗说明，并非法律文件。正式发布前将公布完整的隐私政策。", "p", "faint small")}</div>''')
    page("terms", ("Terms — Interview Realtime Copilot", "条款 — Interview Realtime Copilot"), f'''
<div class="wrap" style="max-width:820px;padding:80px 28px">{t("tm.h1", "Terms", "服务条款", "h1")}
{t("tm.p", "Preview service. Subscriptions renew automatically until cancelled from your account page. Use the copilot in line with the rules of the interviews you take part in. Full terms will be published before general availability.", "预览版服务。订阅会自动续费，直到你在账号页取消。请在遵守所参加面试规则的前提下使用。正式发布前将公布完整条款。", "p", "muted")}</div>''')
    page("404", ("Not found — Interview Realtime Copilot", "页面不存在 — Interview Realtime Copilot"), f'''
<div class="wrap center" style="padding:140px 28px">{t("nf.h1", "Page not found", "页面不存在", "h1")}<a class="btn primary" href="/">{t("nf.home", "Back to home", "返回首页")}</a></div>''')

    for key, en, zh in [("up.title", "Knowledge sources", "知识来源"), ("up.reading", "Reading…", "读取中…"), ("up.ready", "Ready", "已就绪"),
                        ("up.done", "151 prepared questions found — the copilot answers from these.", "已提取 151 道准备题——副驾将据此作答。")]:
        t(key, en, zh)
    # Shared chrome and the cockpit demo script.
    for key, en, zh in [("nav.scenarios", "Use cases", "使用场景"), ("nav.demo", "Demo", "演示"), ("nav.pricing", "Pricing", "价格"), ("nav.download", "Download", "下载"),
                        ("nav.signin", "Sign in", "登录"), ("nav.start", "Get started", "开始使用"), ("foot.privacy", "Privacy", "隐私"), ("foot.terms", "Terms", "条款"),
                        ("mock.interviewer", "Interviewer", "面试官"), ("mock.question", "Question", "问题"),
                        ("mock.q", "How did you split the uplink processing between the FPGA and the DSP, and what were the latency trade-offs?",
                         "你是如何在 FPGA 和 DSP 之间划分上行处理的？延迟上做了哪些取舍？"),
                        ("mock.h1", "The FPGA did the per-subcarrier, fixed-latency work: FFT, RE demapping and channel-estimate correlations.",
                         "FPGA 负责每个子载波、时延固定的计算：FFT、RE 解映射和信道估计相关。"),
                        ("mock.h2", "The DSP ran the slower statistics two TTIs behind, which kept the FPGA pipeline deterministic.",
                         "DSP 滞后两个 TTI 处理较慢的统计运算，保证 FPGA 流水线的确定性。"),
                        ("mock.h3", "The trade-off was a 2-TTI feedback delay, which I mitigated with predictive smoothing.",
                         "代价是 2 个 TTI 的反馈延迟，我用预测平滑来弥补。")]:
        t(key, en, zh)
    (STATIC / "robots.txt").write_text("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /account.html\nSitemap: https://copilot.xichiuk.com/sitemap.xml\n")
    urls = "".join(f"<url><loc>https://copilot.xichiuk.com/{p}</loc></url>" for p in ("", "use-cases.html", "demo.html", "pricing.html", "download.html", "privacy.html"))
    (STATIC / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n')
    (STATIC / "llms.txt").write_text("""# Interview Realtime Copilot
> AI interview assistant (AI面试助手, 实时面试辅助) for macOS. Listens to live video interviews (Zoom, Teams, Meet), translates English and Chinese in real time, detects each question and suggests a one-minute answer from the user's own resume and notes. Solves coding interview questions from the screen, runs spoken mock interviews from prepared Q&A, and writes a debrief with the recording after each session. Local-first; hidden from screen sharing. Free plan; Pro $29/month or $199/year.

- [Use cases](https://copilot.xichiuk.com/use-cases.html): cross-language interviews, expert answers, last-minute preparation, coding questions from the screen
- [Demo](https://copilot.xichiuk.com/demo.html)
- [Pricing](https://copilot.xichiuk.com/pricing.html)
- [Download](https://copilot.xichiuk.com/download.html)
""")
    (STATIC / "i18n.js").write_text("// Generated by web/build_site.py — edit the strings there.\nwindow.I18N = "
                                    + json.dumps(STRINGS, ensure_ascii=False, indent=0) + ";\n")
    print(f"{len(STRINGS['en'])} strings")


if __name__ == "__main__":
    build()
