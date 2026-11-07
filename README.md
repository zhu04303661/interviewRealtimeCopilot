# Final Round Desktop 3.0.7 源码恢复

目标为 `final-round-desktop-3.0.7-arm64-mac.dmg`，macOS ARM64。应用标识为 `com.finalround.desktop`，包内 Electron 版本为 39.2.7。全部结果来自本地静态分析，应用没有启动。

## 从这里看代码

- [主进程](readable-js/out/main/index.mjs)约 2.2 万行，保留了大量类名和发布包里的注释。Electron 初始化在 22067 行，IPC 网关在 5800 行，音频采集在 8783 行，音频检测在 9486 行，认证在 10109 行，会话管理在 14528 行，原生键盘桥接在 17047 行，语音在 19851 行。
- [预加载入口](readable-js/out/preload/index.cjs)及同目录的其他六个 CJS 文件提供主进程与渲染窗口之间的桥接。[IPC 字面量索引](evidence/ipc-literal-calls.json)记录 103 个命令和 64 个查询的注册位置，以及字面量广播、事件推送和桥接 API。该索引只收录匹配的静态调用。
- [主窗口 HTML](readable-js/out/renderer/main-window/index.html)及[主窗口 JavaScript](readable-js/out/renderer/assets/index-CQEWRyAV.js)可作为前端入口。[七个 HTML 入口与脚本](evidence/renderer-entries.json)还覆盖 cockpit、interviewer、intro、recorder、audio indicator 和 capture halo 窗口。
- [主进程分段](wakaru-derived/main-inspection/)和[渲染入口分段](wakaru-derived/renderer-inspection/)分别包含 150 和 642 个静态分析片段。各目录的 `provenance.json` 给出片段来源和输入字节范围，生成的 `.map` 映射回包内 JavaScript。拆分边界由 Wakaru 推断，片段只供阅读，初始化顺序和运行等价性未经验证。

## 精度和文件布局

| 目录 | 内容 |
| --- | --- |
| `asar-exact/` | 从 ASAR 和其伴随目录提取的 5,791 个文件，保留发布字节。包括应用构建产物和随包的第三方依赖。 |
| `readable-js/` | 保留原目录结构的应用构建产物。334 个脚本通过格式化前后语法树对照，其中 331 个使用 Prettier 3.9.10，3 个使用 Babel 8.1.0。对照忽略位置、注释排版、同运算符逻辑链的结合形式及等价的字面对象键写法。HTML、CSS、媒体和字体逐字节复制。 |
| `wakaru-derived/` | Wakaru 1.14.0 为 23 个选定脚本生成的可读派生版本，以及主进程和渲染入口的分段。macOS 上直接使用 Wakaru 发布的 ARM64 CLI。 |
| `native/` | REA 与 Kuna 导出的 C 伪代码、原生函数索引、反汇编、符号和链接信息。每个原生目标以地址关联伪代码与指令。 |
| `package/` | 从只读 DMG 复制的应用 Resources、Info.plist 和主启动器。 |
| `evidence/`、`method/` | REA Evidence、独立完整性清单和提取、格式化、索引脚本。 |

应用的 ASAR 索引中没有 `.map`，334 个应用脚本的注释及两份 CSS 均无 source map 指令。DMG 内没有找到独立 `.dSYM`。包内内容可恢复到发布版 JavaScript、HTML、CSS 和静态资源的粒度。开发期 TypeScript/TSX、原始模块文件名及布局、构建工程和原生 C++/Objective-C++ 源文件仍缺失。渲染脚本的部分局部标识符已被缩短。分段和 C 伪代码会保留推断内容，其类型、名称和控制流应结合原始字节或汇编核对。服务端源码未随这个桌面包交付。

## 完整性与证据

- DMG SHA-256 为 `47d71142b4dfc97bbeba137a3b87001052687a3b55c39afcbf54468ecd72ae65`。完整 ASAR SHA-256 为 `cb23c28ca0375c3f65cfd0d8a6266ff8473b7d4bc9d20a0620cd319070064faf`。ASAR 头部 JSON 的 SHA-256 与 Info.plist 声明一致。
- [ASAR 逐文件记录](evidence/asar-files.json)覆盖 5,799 个文件条目。5,789 个符合声明的大小、文件哈希和块哈希。两个随包 macOS ARM64 ONNX Runtime 文件的实际字节与 ASAR 声明冲突，已原样保留并标为 `mismatch`。另外八个缺失条目均为其他架构或平台的 ONNX Runtime 文件。macOS 对只读挂载上应用执行的 `codesign --verify --deep --strict` 返回成功，签名验证与 ASAR 自带哈希是不同层面的核验。
- [DMG REA 摘要](evidence/rea-dmg-summary.json)的完整分析 Evidence ID 为 `ev_ba72fd3c1f81bf6a480f9ace280481bea7ef427f58435401f322b3ba5189ad8b`。
- [主进程 REA 摘要](evidence/rea-main-summary.json)对应 `ev_eea645a20996b5c5fada7cd3937df93eb36bec878d3a92dc70f7c939af1f186e`。[预加载和部分渲染 REA 摘要](evidence/rea-renderer-summary.json)对应 `ev_26357a7396577643684bfedbf18b5df9ed09182a72d8a522fc2c34e5015e8f85`。REA 针对选定入口和共享脚本构建语义图。较宽的渲染器分析在 `client` 分块的语义阶段超时，部分证据已保留。其余渲染脚本仍已逐字节提取、解析并格式化。

## 原生反编译

REA 6.8.0 使用 [Kuna 1.992](https://github.com/Noelo-Lab/kuna/releases/tag/v1.992) 的 macOS ARM64 发布文件。Kuna 压缩包与发布方提供的 SHA-256 一致。每个目标的 `project/` 有整库 C 伪代码和生成的头文件，`decompiled/decompile-index.json` 则按地址索引逐函数文件。整库结果适合顺序阅读，逐函数结果有自己的证据和限制。

| 目标 | 已导出伪代码函数 | 整库伪代码 |
| --- | ---: | --- |
| `audio_capture.node` | 3,012 | [音频采集](native/audio_capture.node/project/audio_capture.node.c) |
| `audio_detect.node` | 94 | [音频检测](native/audio_detect.node/project/audio_detect.node.c) |
| `keyboard_monitor.node` | 192 | [键盘监听](native/keyboard_monitor.node/project/keyboard_monitor.node.c) |
| `Final Round` | 9 | [Electron 启动器](native/Final%20Round/project/Final%20Round.c) |

[原生覆盖记录](evidence/native-coverage.json)区分整库和 REA 逐地址导出的统计。逐地址清单会列出没有本地可反编译函数体的导入或链接槽。整库唯一失败的函数是 `audio_capture.node` 的 `webrtc::NoiseSuppressor::Process`（`0x9748c`），在整库导出和单函数复查时均达到反编译预算，已保留[对应汇编](native/audio_capture.node/focused/webrtc-NoiseSuppressor-Process-0x9748c.asm)。Electron Framework 与 ONNX Runtime 的第三方原生实现只保留包内证据或原始随包字节，未纳入上述四个目标的反编译范围。

[交付复核](evidence/delivery-verification.json)记录 5,791 个提取文件、343 个可读文本文件和 3,307 个逐函数伪代码文件的哈希检查。所有随附的整库原生输出也与各自的 REA 缓存清单核对。

## 当前重建版

[Final Round Recovered.app](launch/Final%20Round%20Recovered.app) 使用原版桌面页面、IPC 和实时客户端。原厂服务端的功能由本机的 Python 后端（`launch/backend`）提供：账号、目标、资料库、Playbook、会话、历史、文档准备和实时面试。应用启动时由 Electron 主进程拉起后端，通过本机回环地址加随机令牌通信，应用退出时后端随之退出。

在原版欢迎页点「Sign in locally」。继续使用之前激活的 `admin` 和你设置的密码；首次激活使用本机的一次性激活码。

数据保存在应用包之外的固定目录，重建、重装都不会丢：账号在 `~/Library/Application Support/Final Round Recovered Local Accounts/`，工作区（目标、资料、会话、历史）在 `~/Library/Application Support/Final Round Recovered Local Data/workspace/`。首次启动新版本时，旧的 `launch/profile/workspace/` 会复制过去，原目录保留作备份。设置 `FRLOCAL_DATA_DIR` 可把全部数据改到别处（测试使用临时目录）。账号删除、在线账单与官方支持提交在本机版不可用。

### 面试中的语音

- **说话人**：按采集声道区分。麦克风是「You · 我」，电脑声音是「Interviewer · 面试官」；同一声道里的多位面试官统一标为面试官。电话混音模式不支持。
- **实时字幕**：使用 `gpt-live-transcribe`（低延迟档），语言提示为英文和中文，并带上目标职位、公司和职位描述中的专有名词，提高术语识别率。字幕边说边出，每句定稿后成为对话中的一行。
- **中英对照**：面试官的每句话定稿后翻译成另一种语言（中文译英文，其他语言译中文），显示在原文下方。AI 模拟面试官的问题同样附译文。你自己的话不翻译。
- **提炼问题**：面试官每说完一句，后端把该句的翻译和「是否是一个完整的问题」放在同一次模型调用里完成。完整问题以「Question · 问题」卡片显示提炼后的问题及译文，并立即开始生成提示；问题没说完时等下一句合并后再判断；寒暄显示「Heard · no answer needed」。模型调用失败时按问号和疑问句式判断，面试不中断。
- **回答提示**：流式输出，先给可直接说的英文要点（**EN**），再给对应的中文（**中文**）。提示依据 Goal 的职位、公司和职位描述，以及本次会话选定的简历与资料；长资料（例如 3GPP 规范）按问题关键词选取最相关的段落，用到资料段落时卡片下方显示「From your materials」。新问题出现时，未完成的旧提示会标为被取代，新提示立即开始。
- **断线重连**：客户端重连后，后端补发错过的帧。

### 练习模式的语音面试官

练习模式默认使用 OpenAI Realtime API（`gpt-realtime-2.1`）的 speech-to-speech 语音代理：面试官用语音（marin）提问，你口头回答，语义断句判断你何时说完，再追问或进入下一主题。开场前先从简历和所选资料中提炼 4–6 个面试主题。旁边的提示板与 Live 模式相同：面试官每说完一轮，显示中英对照，并自动流式给出 EN/中文 双语回答提示。外放时面试官说话期间麦克风静音以防回声，只有语气词的片段（如「呃」「Uh」）不计为回答。戴耳机时可设 `FRLOCAL_PRACTICE_BARGE_IN=1` 允许打断。`FRLOCAL_PRACTICE_VOICE=live` 改用 GPT-Live 全双工，`text` 为无语音的文字面试官；模型不可用时自动退回文字面试官。

### 资料与 Knowledge sources

上传的简历和资料先显示为准备中，后端在独立子进程中提取文字（PDF 使用 pdfium），完成后变为可用。支持 PDF、DOCX、TXT 和 Markdown；单个文件最大 500 MB，文字最多 2,000 万字符，单个文件准备时间上限 10 分钟。上传时直接在磁盘上复制所选文件。扫描版 PDF、不支持的格式或无法读取的文件会标为无法准备。未准备的文件，以及被旧版本拒绝的文件，会在下次登录后自动重新准备。

Goal 的 Knowledge sources 决定新会话默认使用的简历和资料，Preflight 可为单次会话调整。每次请求发送简历最多 8,000 字符、每份资料最多 5,000 字符，合计不超过 24,000 字符。Debrief 也参考公司介绍和职位描述。

简历结构化编辑、跨会话自动学习、视频虚拟面试官、Playbook 对提示的影响和电话混音的说话人分离尚未实现。

### 配置模型

后端优先使用进程环境中的 `OPENAI_API_KEY`，未设置时在每次请求前读取 `~/.env` 中的 `OPENAI_API_KEY`。写入 `~/.env` 后可直接从 Finder 打开，修改密钥无需重启。请求经过 macOS 系统代理（HTTP、HTTPS 或 SOCKS5）。只有使用实时面试、屏幕题分析和 Debrief 时才向 OpenAI 发送所需内容。

### 权限与签名

应用用登录钥匙串中的本地证书「Final Round Recovered Local Signing」签名，macOS 按应用标识和该证书识别授权，重建后麦克风、屏幕录制与系统音频权限保持有效。没有该证书时构建脚本退回 ad-hoc 签名，届时每次重建都要重新授权。后端在未收到代理设置时使用 macOS 系统代理（含 WebSocket）。

## 代码结构

| 路径 | 内容 |
| --- | --- |
| `launch/backend/` | Python 后端（`frlocal`，Python 3.12，uv 管理依赖）。`accounts` 本地账号；`workspace/` 存储、记录、文档准备与工作区 API；`retrieval` 长资料段落检索；`openai` 唯一的 OpenAI 访问层；`realtime/` 实时面试（`asr` 转写、`understanding` 翻译与提炼问题、`coach` 提示词、`session` 单场面试状态机、`engine` 注册表与 WebSocket）；`screen` 屏幕题分析。 |
| `launch/app/` | 打进 ASAR 的 Electron 侧代码：`python-backend.mjs` 启动与转发、`local-auth-ipc.mjs` 账号 IPC、`local-auth-ui.mjs` 登录界面、`bootstrap.mjs` 独立配置目录。 |
| `launch/build/` | `build.sh` 安装后端依赖并生成 ASAR；`repack.mjs` 对原版主进程、预加载、主窗口和面试窗口（cockpit）的逐处补丁；`stage.sh` 写入应用并签名；`install.sh` 备份后安装到 `launch/Final Round Recovered.app`。 |
| `launch/tests/` | 打包应用的端到端测试：`app-e2e.mjs`（主窗口）与 `cockpit-e2e.mjs`（实时练习面试）。 |
| `launch/reports/` | 最近一次构建和测试的结果。 |
| `launch/legacy/` | 已被取代的实验代码、旧 JavaScript 后端和历史日志，仅作参考。 |
| `launch/pre-*/` | 每次安装前的 ASAR 与 Info.plist 备份。 |

### 构建与测试

```zsh
cd launch/backend && uv run pytest -q        # 后端测试（53 项，使用模拟 OpenAI）
uvx ruff check src tests                      # 代码检查
sh launch/build/build.sh                      # 安装后端依赖并生成 ASAR
sh launch/build/install.sh python-backend     # 退出应用、备份到 launch/pre-python-backend/、安装并重新打开
```

后端测试覆盖账号兼容性（含旧版 JavaScript 生成的密码摘要）、工作区 API、文档准备与 500 MB 上限、长资料检索（含 2,000 万字符的耗时）、SSE 解析，以及实时面试的完整流程：声道与说话人、面试官翻译、问题提炼与分句合并、寒暄忽略、模型失败回退、流式提示与取代、转写配置、重复音频帧、练习模式、断线补发、Debrief 与屏幕题。延迟测试在模拟的模型耗时之外，限制「定稿到问题卡片」和「定稿到首个提示字」的额外开销，并确认提示逐字转发。

[打包检查](launch/reports/repack.json) · [桌面端到端](launch/reports/app-e2e.json) · [后端测试](launch/reports/backend-tests.txt) · [真实语音练习](launch/reports/practice-real.txt)（`launch/tests/practice-real.mjs`，使用真实 OpenAI，并用 macOS `say` 经扬声器作答）

## 旧版实验

访客模式、早期 AI 模拟面试和 JavaScript 版本地后端的代码与日志已移到 `launch/legacy/`，对应的 ASAR 与 Info.plist 备份仍在 `launch/pre-guest/`、`launch/pre-interview/`、`launch/pre-auth-only/`、`launch/pre-local-auth/` 和 `launch/pre-local-workspace/`。
