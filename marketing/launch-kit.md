# 发布文案与渠道链接

每个渠道用自己的链接（带 `utm_source`），管理后台「流量与转化」就能按渠道看到浏览、下载点击和注册。
中文渠道链接到 `/zh/`，英文渠道链接到首页。

| 渠道 | 链接 |
|---|---|
| 小红书 | https://copilot.xichiuk.com/zh/?utm_source=xiaohongshu |
| 知乎 | https://copilot.xichiuk.com/zh/?utm_source=zhihu |
| V2EX | https://copilot.xichiuk.com/zh/?utm_source=v2ex |
| 即刻 | https://copilot.xichiuk.com/zh/?utm_source=jike |
| 一亩三分地 | https://copilot.xichiuk.com/zh/?utm_source=1point3acres |
| 微信（朋友圈/群/公众号） | https://copilot.xichiuk.com/zh/?utm_source=wechat |
| B 站（演示视频简介） | https://copilot.xichiuk.com/zh/?utm_source=bilibili |
| Product Hunt | https://copilot.xichiuk.com/?utm_source=producthunt |
| Hacker News (Show HN) | https://copilot.xichiuk.com/?utm_source=hackernews |
| Reddit | https://copilot.xichiuk.com/?utm_source=reddit |
| X / Twitter | https://copilot.xichiuk.com/?utm_source=x |
| LinkedIn | https://copilot.xichiuk.com/?utm_source=linkedin |
| YouTube（演示视频简介） | https://copilot.xichiuk.com/?utm_source=youtube |

三篇指南文章可以单独分享（搜索流量的入口）：
- 英语不够好，如何通过英文面试：`/zh/docs/english-interview.html`
- 什么是 AI 面试助手，怎么选：`/zh/docs/ai-interview-assistant.html`
- 明天就面试、来不及准备：两小时计划：`/zh/docs/last-minute-prep.html`

## 小红书（图文，配 3–4 张应用截图或录屏封面）

**标题备选**
- 英语一般，我是怎么撑过英文技术面的
- 面试官语速太快听不懂？这个实时翻译 + 提词的工具救了我
- 明天面试来不及准备，两小时急救方案

**正文**
英文面试最怕两件事：没听全问题，和脑子里有答案但英文说不出来。

最近在用一个 Mac 上的 AI 面试助手 Interview Realtime Copilot：
1. 面试官每说一句，窗口里实时出字幕，下面就是中文翻译
2. 问题说完会自动变成一张「问题卡片」，不怕中间停顿
3. 几秒内给出 3–4 条英文要点，内容来自我自己上传的简历和准备笔记，不是瞎编
4. 面试前可以用语音模拟面试：AI 面试官把我准备的题一道道问出来，还会追问
5. 结束后有逐题复盘，还能回放录音

资料都存在自己电脑上，共享屏幕时窗口不会被看到。免费版每月有额度可以先试。

目前只有 Mac 版（Apple 芯片），Windows 在做。
#英文面试 #面试准备 #求职 #外企面试 #留学生求职 #程序员面试 #AI工具

## 知乎（回答「英文面试怎么准备」「有哪些好用的面试工具」类问题）

先回答问题本身（把 `/zh/docs/english-interview.html` 的五个做法用自己的话写出来），最后一段再提工具：

> 另外说一个我自己做的工具：Interview Realtime Copilot，一个 Mac 上的实时 AI 面试助手。它做三件事——实时字幕加中英翻译、说完自动识别出问题、基于你上传的简历和笔记给出几条英文要点；面试前还能用语音模拟面试把准备的题过一遍。资料保存在本机。免费版有每月额度，欢迎试用和提意见：（链接）

知乎对纯广告很敏感：回答要先有独立价值，注明「利益相关：开发者」。

## V2EX（「分享创造」节点）

**标题**：做了个 Mac 上的实时 AI 面试助手：实时字幕翻译 + 基于自己简历的回答提示 + 语音模拟面试

**正文**
自己找工作时的痛点：英文面试听不全问题，准备的材料到现场想不起来。于是做了这个。

- 分别采集会议声音和麦克风，实时转写 + 中英互译
- 面试官说完后识别出完整问题（中间停顿不会被切开），几秒内给出要点
- 要点只用你上传的简历 / 笔记里的事实
- ⌥S 截屏解答编程题和系统设计题
- 语音模拟面试：从准备文档里提取所有问答，AI 面试官用语音提问、追问
- 每场有录音和逐题复盘；数据在本机，窗口对屏幕共享不可见

技术上：Electron + React，本地 Python 引擎，macOS 系统声音用 Core Audio Tap 采集。
目前 macOS 14.2+ / Apple 芯片，测试版还没做 Apple 公证（首次打开要在系统设置里点「仍要打开」）。
免费版每月有额度。欢迎拍砖：（链接）

## Product Hunt

**Name**: Interview Realtime Copilot
**Tagline**: A realtime AI copilot that hears your interview and hints your answer
**Description**
Interview Realtime Copilot is a Mac app for live job interviews. It transcribes and translates the interviewer as they speak (English ↔ Chinese), recognises each finished question, and streams a short answer built from your own resume and notes. Press ⌥S and it reads the coding problem on your screen. Before the interview, a spoken AI interviewer rehearses your prepared questions; afterwards you get a question-by-question debrief with the recording. Your files stay on your Mac and the cockpit is hidden from screen sharing. Free plan included.
**Topics**: Productivity, Artificial Intelligence, Career, Mac
**First comment (maker)**
Hi PH — I built this after too many interviews in my second language where I half-heard the question. Three things I cared about: hints must come from *my* materials (no invented experience), a question with pauses must stay one question, and I must be able to rehearse out loud first. It's an early preview (Apple Silicon, not yet notarised). I'd love feedback — there is a wishlist on the site.

## Show HN

**Title**: Show HN: Realtime interview copilot for Mac – live translation and resume-grounded hints
**Text**
I built a Mac app that listens to a live interview (system audio via Core Audio taps + microphone), transcribes and translates it, detects when a question is complete, and streams a 3–4 bullet answer grounded in the user's own resume and notes. It also has a speech-to-speech mock interviewer that asks the questions extracted from your prep notes, and a per-question debrief afterwards. Electron + React UI, a local Python engine, data stored locally. Things that were harder than expected: not splitting one spoken question at pauses, echo of the interviewer in the microphone, and macOS system-audio capture. Preview build, Apple Silicon only. Feedback welcome.

## Reddit

多数求职类版块（r/cscareerquestions 等）禁止自我推广，先读版规。适合的地方：r/SideProject、r/macapps、r/EnglishLearning（只分享英文面试指南那篇）。用 Show HN 那段文字，开头加一句 "I'm the developer."

## X / LinkedIn（配 20–30 秒录屏）

EN: Interviews in a second language are hard: you half-hear the question, then translate your answer in your head. I built Interview Realtime Copilot — it translates the interviewer live, spots the question, and hints an answer from your own resume. Mac preview, free plan: （link）

中文：用第二语言面试，最难的是没听全问题、有答案却说不出口。做了个 Mac 应用 Interview Realtime Copilot：实时翻译面试官的话、识别问题、基于你自己的简历给出回答要点，还能语音模拟面试。免费试用：（链接）

## 演示视频（B 站 / YouTube，60–90 秒）

1. 0–10s：痛点一句话 + 应用窗口悬浮在视频会议上的画面
2. 10–25s：上传简历和准备文档 →「已提取 N 道准备题」
3. 25–50s：实时面试：面试官提问 → 字幕和翻译 → 问题卡片 → 双语要点
4. 50–65s：⌥S 截屏解答一道编程题
5. 65–80s：语音模拟面试 + 复盘页
6. 结尾：网址 + 「免费版每月有额度」
