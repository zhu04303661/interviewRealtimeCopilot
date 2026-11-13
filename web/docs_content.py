"""Help Center content (web/static/docs/). Each page: slug, title, lead and blocks, all in English and Chinese.

Blocks: ("h2", en, zh) · ("p", en, zh) · ("ul", [(en, zh)…]) · ("steps", [(en, zh)…]) · ("note", en, zh)
        ("cards", [(en_title, zh_title, en_text, zh_text)…]) · ("table", [(en, zh) headers], [[cell…]…]) where a cell is str or (en, zh)
"""

E = "linkyourfuture2026@outlook.com"

DOCS = [
    ("start", "Getting started", "快速入门", [
        dict(slug="index", title=("Help Center", "帮助中心"),
             lead=("What Interview Realtime Copilot does, the loop it runs on, and how to find your way around this guide.",
                   "Interview Realtime Copilot 能做什么、它的使用循环，以及如何使用本手册。"),
             blocks=[
                 ("p", "Interview Realtime Copilot is a Mac app that helps you through real job interviews. It listens to the interviewer, translates as they speak, recognises each question and shows a short answer built from your own resume and notes. It also rehearses with you before the interview and reviews every session afterwards.",
                  "Interview Realtime Copilot 是一款 Mac 应用，帮助你应对真实的求职面试：实时聆听面试官、同步翻译、识别每个问题，并基于你自己的简历和准备资料给出简短的回答。面试前陪你演练，面试后为每场会话做复盘。"),
                 ("note", "New here? Install the app, sign in with your website account, create a goal and add your resume — then start a practice session. Every plan includes a monthly AI allowance; no API key is needed.",
                  "第一次使用？安装应用，用网站账号登录，创建目标并上传简历，然后开始一次语音练习。每个套餐都包含每月 AI 额度，无需 API 密钥。"),
                 ("h2", "The loop: Prepare, Practise, Perform, Review", "使用循环：准备、练习、实战、复盘"),
                 ("p", "Everything in the app follows the same four steps for each job you apply for. Go round the loop once per interview.",
                  "应用的一切都围绕每个求职目标的四个步骤展开，每场面试走一轮。"),
                 ("cards", [("1. Prepare", "1. 准备", "Create a goal (role and company) and add your resume and preparation notes.", "创建目标（职位和公司），上传简历和准备资料。"),
                            ("2. Practise", "2. 练习", "A spoken AI interviewer asks your prepared questions and follows up.", "AI 面试官用语音提问你准备的问题并追问。"),
                            ("3. Perform", "3. 实战", "Go Live in your real interview; the cockpit listens, translates and hints.", "正式面试时开启实时模式，面试窗口聆听、翻译并提示。"),
                            ("4. Review", "4. 复盘", "Read the debrief and replay the recording, then prepare better next time.", "阅读复盘、回放录音，下次准备得更好。")]),
                 ("h2", "Words you will see a lot", "常见术语"),
                 ("table", [("Term", "术语"), ("Meaning", "含义")], [
                     [("Goal", "目标"), ("One role at one company. Practice, live sessions and debriefs belong to a goal.", "一个公司的一个职位；练习、实时面试和复盘都归属于某个目标。")],
                     [("Knowledge sources", "知识来源"), ("The resume and documents a session may use to answer.", "一次会话可用来回答问题的简历和资料。")],
                     [("Cockpit", "面试窗口"), ("The floating window you see during a session, hidden from screen sharing.", "会话中悬浮显示的窗口，共享屏幕时不可见。")],
                     [("Hint", "回答提示"), ("Three or four speakable bullets in English and Chinese.", "三到四条可直接说出口的中英文要点。")],
                     [("Debrief", "复盘"), ("The review written after each session.", "每场会话结束后生成的点评报告。")],
                     [("AI allowance", "AI 额度"), ("The monthly AI usage included in your plan.", "套餐每月包含的 AI 使用量。")]]),
                 ("h2", "Common questions", "常见问题"),
                 ("ul", [("Which Macs are supported? Apple Silicon (M1–M4) with macOS 14.2 or later.", "支持哪些 Mac？Apple 芯片（M1–M4），macOS 14.2 及以上。"),
                         ("Does the interviewer see it? No — the cockpit is excluded from screen sharing and recordings.", "面试官看得到吗？看不到，面试窗口不会出现在共享屏幕和录屏中。"),
                         (f"Need help? Email {E}.", f"需要帮助？请发邮件至 {E}。")]),
             ]),
        dict(slug="install", title=("Install and sign in", "安装与登录"),
             lead=("Download the app, open it the first time, and sign in with your website account.", "下载应用、首次打开，并用网站账号登录。"),
             blocks=[
                 ("steps", [("Download the DMG from the Download page and open it.", "在下载页下载 DMG 并打开。"),
                            ("Drag Interview Realtime Copilot into Applications.", "把 Interview Realtime Copilot 拖进「应用程序」。"),
                            ("Open it. Preview builds are not yet notarised by Apple, so macOS blocks the first launch: open System Settings → Privacy & Security and click “Open Anyway”.", "打开应用。测试版尚未经 Apple 公证，首次启动会被拦截：打开「系统设置 → 隐私与安全性」，点击「仍要打开」。"),
                            ("Sign in with your email and password, or choose “Create an account”. It is the same account as on the website.", "用邮箱和密码登录，或选择「注册新账号」。账号与网站通用。")]),
                 ("note", "Downloading from mainland China can be slow because the server is in the UK. Using a faster network or proxy helps.", "从中国大陆下载可能较慢（服务器在英国），换用更快的网络或代理会有帮助。"),
                 ("h2", "Your workspace", "你的工作区"),
                 ("p", "Goals, documents, transcripts, debriefs and recordings are stored on your Mac, in a workspace that belongs to your account. Signing out keeps them; signing in again opens them.",
                  "目标、资料、字幕、复盘和录音都保存在你的 Mac 上，属于你账号的工作区。退出登录不会删除，再次登录即可打开。"),
             ]),
        dict(slug="permissions", title=("Set up permissions", "设置系统权限"),
             lead=("The microphone hears you; System Audio Recording hears the interviewer in your meeting app.", "麦克风用来听你；「系统录音」用来听会议软件里的面试官。"),
             blocks=[
                 ("table", [("Permission", "权限"), ("Needed for", "用途"), ("Where", "在哪里开启")], [
                     [("Microphone", "麦克风"), ("Practice and Live — your answers", "练习和实时面试——听你的回答"), ("Asked the first time you start a session", "首次开始会话时弹窗询问")],
                     [("System Audio Recording", "系统录音"), ("Live — the interviewer's voice", "实时面试——听面试官的声音"), ("System Settings → Privacy & Security → Screen & System Audio Recording", "系统设置 → 隐私与安全性 → 录屏与系统录音")],
                     [("Screen Recording", "屏幕录制"), ("Solve screen and auto-capture", "截屏解答与自动截屏"), ("Same panel as above", "同上")]]),
                 ("p", "Settings → Privacy & Stealth shows the state of each permission with a button to grant it. Preflight, the check before every session, lets you test the microphone level.",
                  "「设置 → 隐私与隐身」会显示每项权限的状态和授权按钮；每次会话前的「开始前检查」可以测试麦克风音量。"),
                 ("note", "After changing a permission in System Settings, quit and reopen the app so macOS applies it.", "在系统设置中更改权限后，请退出并重新打开应用，使其生效。"),
             ]),
        dict(slug="plans", title=("Plans and AI allowance", "套餐与 AI 额度"),
             lead=("Every plan includes a monthly AI allowance — no API key needed.", "每个套餐都包含每月 AI 额度，无需 API 密钥。"),
             blocks=[
                 ("table", [("Plan", "套餐"), ("Price", "价格"), ("AI allowance per month", "每月 AI 额度")], [
                     [("Free", "免费版"), "$0", "$1"], [("Pro monthly", "Pro 月付"), ("$29 / month", "$29 / 月"), "$20"], [("Pro yearly", "Pro 年付"), ("$199 / year", "$199 / 年"), "$20"]]),
                 ("ul", [("The allowance resets on the 1st of each month (UTC). Settings → Account shows what you have used and what is left.", "额度在每月 1 日（UTC）重置；「设置 → 账号」显示已用和剩余额度。"),
                         ("Spoken practice uses the most (realtime voice); live hints and translation use less; debriefs cost a few cents.", "语音练习消耗最多（实时语音），实时提示和翻译较少，复盘每次只需几美分。"),
                         ("When the allowance is used up, the cockpit says so. Subscribe, or add your own OpenAI key in Settings → Account (requests then go straight to OpenAI and do not count against the allowance).", "额度用完时面试窗口会提示。你可以订阅，或在「设置 → 账号」填写自己的 OpenAI 密钥（之后直接连接 OpenAI，不占额度）。")]),
                 ("h2", "Subscribe or manage billing", "订阅与管理"),
                 ("p", "In Settings → Account click Subscribe (or Manage billing). The website opens already signed in; payment is handled by Stripe. Cancel anytime — Pro stays active until the end of the paid period.",
                  "在「设置 → 账号」点「订阅」（或「管理订阅」），网站会自动登录打开，付款由 Stripe 处理。可随时取消，已付费周期内仍可使用 Pro。"),
             ]),
        dict(slug="first-interview", title=("Your first interview, end to end", "第一场面试：完整流程"),
             lead=("From an empty app to a debrief in about fifteen minutes.", "从空白应用到拿到复盘，大约十五分钟。"),
             blocks=[
                 ("steps", [("Create a goal: role, company and (ideally) the job description.", "创建目标：职位、公司，最好附上职位描述。"),
                            ("Add your resume and preparation notes on the goal's Prep tab. Wait until they show Ready.", "在目标的「准备」页上传简历和准备资料，等待显示「就绪」。"),
                            ("Click Practice. In Preflight choose the practice mode and sources, test the microphone, and start.", "点「练习」。在开始前检查里选择练习方式和资料、测试麦克风，然后开始。"),
                            ("Answer out loud. Use Suggest answer when you are stuck, or Expand answer to continue what you said.", "大声作答。卡住时点「生成回答」，或用「补充回答」接着你说的内容。"),
                            ("Click End. The debrief appears in History within a minute.", "点「结束」，一分钟内复盘会出现在「历史」中。"),
                            ("On interview day, open your meeting app, click Go Live and keep the cockpit beside the call.", "面试当天打开会议软件，点「Go Live」，把面试窗口放在通话旁边。")]),
             ]),
    ]),
    ("prepare", "Goals and materials", "目标与资料", [
        dict(slug="goals", title=("Goals", "目标"),
             lead=("A goal is one role at one company; everything else hangs off it.", "目标就是一个公司的一个职位，其他内容都挂在目标之下。"),
             blocks=[
                 ("p", "Create a goal from the sidebar. Add the job description so hints and practice questions focus on what the role needs. The goal page has three tabs: Overview, Prep (documents) and Sessions.",
                  "在侧边栏创建目标，附上职位描述，回答提示和练习题会更聚焦职位需求。目标页有三个标签：概览、准备（资料）和会话。"),
             ]),
        dict(slug="materials", title=("Resume and preparation notes", "简历与准备资料"),
             lead=("What to upload, what happens to it, and how prepared questions are found.", "上传什么、上传后如何处理，以及如何提取准备题。"),
             blocks=[
                 ("ul", [("Formats: PDF, Word (.docx), Markdown and plain text, up to 500 MB per file.", "格式：PDF、Word（.docx）、Markdown 和纯文本，单个文件最大 500 MB。"),
                         ("Each document is read once and kept as text on your Mac, so large PDFs are only processed the first time.", "每份资料只读取一次并以文本保存在本机，大型 PDF 只在首次处理。"),
                         ("Every prepared question in your notes (Q&A, headings ending in “?”, numbered questions) becomes a practice question.", "资料中所有准备好的问题（问答、以问号结尾的标题、编号问题）都会变成练习题。")]),
                 ("note", "Hints only use facts from your materials. If something is not in them, the copilot suggests how to answer honestly rather than inventing experience.", "回答提示只使用资料中的事实；资料里没有的内容，它会建议你如何如实回答，而不是编造经历。"),
                 ("h2", "Knowledge sources", "知识来源"),
                 ("p", "Preflight lets you choose which documents a session may use. The choice is remembered per goal.", "开始前检查里可以选择本次会话可用的资料，选择会按目标记住。"),
             ]),
    ]),
    ("practice", "Practice interviews", "语音练习", [
        dict(slug="practice", title=("Spoken practice", "语音模拟面试"),
             lead=("A spoken AI interviewer asks your prepared questions, waits for you to finish and follows up.", "AI 面试官用语音提问你准备的问题，等你说完后追问。"),
             blocks=[
                 ("h2", "Practice modes", "练习方式"),
                 ("table", [("Mode", "方式"), ("What happens", "说明")], [
                     [("In order", "按顺序"), ("Prepared questions in the order of your notes.", "按资料中的顺序提问准备题。")],
                     [("Random", "随机"), ("Prepared questions shuffled; none repeated.", "准备题随机提问，不重复。")],
                     [("AI improvises", "AI 临场"), ("New questions based on the role and your answers.", "根据职位和你的回答临场出题。")]]),
                 ("ul", [("The question panel shows progress (asked / total). Click any question to jump to it.", "题目栏显示进度（已问 / 总数），点击任意题目即可跳转。"),
                         ("The interviewer waits about 2.5 seconds of silence before replying, so pauses while you think are fine.", "面试官会在你停顿约 2.5 秒后才回应，思考时的停顿没有关系。"),
                         ("Each question gets at most one follow-up, then the interview moves on.", "每题最多追问一次，然后进入下一题。")]),
                 ("h2", "Help while answering", "作答时的辅助"),
                 ("ul", [("Suggest answer — under an interviewer line: a bilingual hint for that question.", "生成回答——在面试官的话下方：为该问题生成双语提示。"),
                         ("Expand answer — under your own line: continues what you said with the facts you have not mentioned yet.", "补充回答——在你自己的话下方：接着你说的内容，补上还没提到的要点。")]),
             ]),
    ]),
    ("live", "Live interview", "实时面试", [
        dict(slug="go-live", title=("Go Live", "开启实时面试"),
             lead=("Start a live session for a real interview on Zoom, Teams, Meet or any call app.", "在 Zoom、Teams、Meet 等任意通话软件中进行真实面试。"),
             blocks=[
                 ("steps", [("Join the call in your meeting app.", "先在会议软件中加入通话。"),
                            ("Click Go Live on the goal. In Preflight choose the knowledge sources, answer language and playbook.", "在目标页点「Go Live」，在开始前检查里选择资料、回答语言和回答风格。"),
                            ("Start. The cockpit opens and both meters (Mic and Computer) should move when people speak.", "开始后面试窗口打开，有人说话时「Mic」和「Computer」两个音量条都应跳动。")]),
                 ("h2", "What you see", "你会看到"),
                 ("ul", [("Interviewer lines appear as they speak, with the translation underneath.", "面试官的话实时出现，下方附译文。"),
                         ("Pauses inside a question do not split it; a finished question becomes a question card.", "问题中的停顿不会把它切开，说完后变成问题卡片。"),
                         ("A hint streams in: three or four bullets in English and Chinese, from your materials.", "回答提示逐字出现：三到四条中英文要点，依据你的资料。"),
                         ("If a question is cut off mid-sentence, a hint still appears after a short pause.", "如果问题只说了一半，短暂停顿后也会给出提示。")]),
                 ("note", "The copilot hears everything your Mac plays. Close music and videos during the interview so they are not transcribed.", "副驾会听到 Mac 播放的所有声音，面试时请关闭音乐和视频，以免被转写。"),
             ]),
        dict(slug="cockpit", title=("The cockpit and stealth", "面试窗口与隐身"),
             lead=("Keep the cockpit readable for you and invisible to everyone else.", "让面试窗口对你清晰可读，对其他人不可见。"),
             blocks=[
                 ("ul", [("Hide from screen sharing is on by default: the cockpit does not appear in shared screens or recordings. Turning it off shows a warning.", "「共享屏幕时隐藏」默认开启：面试窗口不会出现在共享屏幕和录屏中；关闭时会显示警告。"),
                         ("Appearance: opacity 70–100% (default 80%), background and text colours, with a live preview.", "外观：透明度 70–100%（默认 80%）、背景色和文字色，带实时预览。"),
                         ("Move and resize it with the keyboard so you never reach for the mouse during a call.", "可以用快捷键移动和调整宽度，通话中无需用鼠标。")]),
             ]),
        dict(slug="shortcuts", title=("Keyboard shortcuts", "快捷键"),
             lead=("Default shortcuts; change any of them in Settings → Shortcuts.", "默认快捷键，可在「设置 → 快捷键」中修改。"),
             blocks=[
                 ("table", [("Action", "操作"), ("Shortcut", "快捷键")], [
                     [("Show or hide the results panel", "显示/隐藏结果面板"), "⌥ C"], [("Solve screen", "截屏解答"), "⌥ S"],
                     [("Show or hide the cockpit", "显示/隐藏面试窗口"), "⌥ A"], [("Move the cockpit", "移动面试窗口"), "⌥ ↑ ↓ ← →"],
                     [("Wider / narrower", "加宽 / 变窄"), "⌥ =  /  ⌥ −"]]),
             ]),
        dict(slug="solve-screen", title=("Coding, system design and screen help", "编程、系统设计与截屏解答"),
             lead=("Let the copilot read the problem on your screen and explain a solution.", "让副驾读取屏幕上的题目并给出解法。"),
             blocks=[
                 ("ul", [("Press ⌥S (or Solve screen in the cockpit) to capture the screen once. The copilot reads the coding problem, diagram or error and writes a solution with its complexity and edge cases.", "按 ⌥S（或面试窗口中的「截屏解答」）截取一次屏幕：读取编程题、架构图或报错，写出解法并说明复杂度和边界情况。"),
                         ("Auto-capture (Settings → Privacy & Stealth) does this by itself when the interviewer asks a coding or system-design question.", "开启「自动截屏」（设置 → 隐私与隐身）后，面试官问到编程或系统设计题时会自动截屏解答。"),
                         ("Defaults → Coding language sets the language solutions are written in.", "「默认设置 → 编程语言」决定解答代码使用的语言。")]),
                 ("note", "Screen capture needs the Screen Recording permission. Only one screenshot is taken per request; nothing is recorded continuously.", "截屏需要「屏幕录制」权限；每次只截一张图，不会持续录屏。"),
             ]),
    ]),
    ("review", "History and debriefs", "历史与复盘", [
        dict(slug="debriefs", title=("Debriefs and recordings", "复盘与录音"),
             lead=("Every session is recorded on your Mac and reviewed question by question.", "每场会话都在本机录音，并逐题复盘。"),
             blocks=[
                 ("ul", [("History lists your sessions; open one to read its debrief and play the recording.", "「历史」列出所有会话，打开即可阅读复盘、播放录音。"),
                         ("The debrief reviews every question (up to 40 per session): what was missing and a stronger spoken version, using only what you actually said.", "复盘逐题点评（每场最多 40 题）：指出遗漏，并给出更好的说法，只依据你实际说过的话。"),
                         ("The recording mixes your microphone, the computer audio and the practice interviewer's voice. It is saved when you click End.", "录音混合了你的麦克风、电脑声音和练习面试官的语音，在点「结束」时保存。")]),
                 ("note", "No debrief? A session needs some of your own speech to review. If the microphone was muted or denied, there is nothing to assess.", "没有复盘？会话里需要有你自己的发言才能点评；如果麦克风被静音或未授权，就无法评估。"),
             ]),
    ]),
    ("account", "Account, privacy and settings", "账号、隐私与设置", [
        dict(slug="privacy", title=("Privacy and your data", "隐私与数据"),
             lead=("What stays on your Mac and what is sent for processing.", "哪些内容留在本机，哪些会发送处理。"),
             blocks=[
                 ("ul", [("On your Mac: goals, documents, extracted questions, transcripts, debriefs and recordings.", "保存在本机：目标、资料、提取的问题、字幕、复盘和录音。"),
                         ("Sent during a session you start: audio and the text needed to answer (the question and relevant passages of your materials), to the speech and language models.", "在你开始的会话中发送：音频和回答所需的文字（问题及资料中的相关段落），发送给语音和语言模型。"),
                         ("Our server keeps your email, a password hash, your plan and usage amounts. Payments are processed by Stripe.", "我们的服务器只保存邮箱、密码哈希、套餐和用量；付款由 Stripe 处理。")]),
             ]),
        dict(slug="settings", title=("Settings reference", "设置说明"),
             lead=("The six sections of Settings.", "设置的六个分区。"),
             blocks=[
                 ("table", [("Section", "分区"), ("What it controls", "内容")], [
                     [("General", "通用"), ("Launch at login, version.", "开机启动、版本信息。")],
                     [("Appearance", "外观"), ("Cockpit opacity and colours, with preview.", "面试窗口透明度和颜色，带预览。")],
                     [("Defaults", "默认设置"), ("Answer language, coding language, playbook.", "回答语言、编程语言、回答风格。")],
                     [("Privacy & Stealth", "隐私与隐身"), ("Hide from screen sharing, permissions, auto-capture, AI memory.", "共享屏幕时隐藏、系统权限、自动截屏、AI 记忆。")],
                     [("Shortcuts", "快捷键"), ("Nine shortcuts, click to rebind, reset.", "九个快捷键，点击重新绑定、恢复默认。")],
                     [("Account", "账号"), ("Plan and allowance, subscribe, your own OpenAI key, sign out, support.", "套餐与额度、订阅、自己的 OpenAI 密钥、退出登录、联系客服。")]]),
             ]),
    ]),
    ("help", "Troubleshooting and FAQ", "故障排查与常见问题", [
        dict(slug="troubleshooting", title=("Troubleshooting", "故障排查"),
             lead=("Fixes for the problems people meet most often.", "最常见问题的解决办法。"),
             blocks=[
                 ("table", [("Problem", "问题"), ("What to do", "解决办法")], [
                     [("The Computer meter does not move in Live", "实时面试中「Computer」音量条不动"), ("Allow System Audio Recording for the app, quit and reopen it, and check the meeting's sound plays through this Mac.", "为应用开启「系统录音」权限，退出并重新打开，确认会议声音从这台 Mac 播放。")],
                     [("The Mic meter does not move", "「Mic」音量条不动"), ("Allow the microphone in System Settings → Privacy & Security → Microphone; check the input device in macOS Sound settings.", "在「系统设置 → 隐私与安全性 → 麦克风」中允许，并检查 macOS 声音设置中的输入设备。")],
                     [("“Your monthly AI allowance is used up”", "提示「本月 AI 额度已用完」"), ("Subscribe in Settings → Account, wait for next month, or add your own OpenAI key.", "在「设置 → 账号」订阅、等待下月重置，或填写自己的 OpenAI 密钥。")],
                     [("macOS says the app cannot be opened", "macOS 提示无法打开应用"), ("System Settings → Privacy & Security → Open Anyway (preview builds are not notarised yet).", "「系统设置 → 隐私与安全性 → 仍要打开」（测试版尚未公证）。")],
                     [("Cannot reach the account service", "无法连接账号服务"), ("Check your internet connection or proxy; the app keeps you signed in and retries.", "检查网络或代理；应用会保持登录并自动重试。")],
                     [("A continuous question is split into pieces", "一个连续的问题被切成几段"), ("Usually a very long pause; the copilot still answers the combined question. Tell us if it keeps happening.", "通常是停顿过长；副驾仍会把它们合并作答。如果反复出现请告诉我们。")]]),
                 ("h2", "Contact support", "联系客服"),
                 ("p", f"Email {E} with what you did, what you expected and what happened. In the app, the Help button (?) opens a new email for you.",
                  f"请发邮件至 {E}，说明你的操作、期望结果和实际情况。在应用中点「帮助」按钮（?）会直接打开一封新邮件。"),
             ]),
    ]),
]
