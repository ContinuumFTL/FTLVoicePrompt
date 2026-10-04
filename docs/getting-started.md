# 在 Windows 上使用 FTL Voice Prompt

FTL Voice Prompt 是本地语音输入工具。你可以按快捷键录音，把识别出的文字输入当前窗口；也可以在面板里编辑文字，再按需交给 DeepSeek 整理。本文面向从公开仓库克隆源码、使用 VS Code F5 启动的用户。

## 1. 准备开发环境

主要支持环境为 Windows + NVIDIA 显卡。CPU 用户可以选择 SenseVoice Small；官方支持 CPU 推理，但不同机器的速度需要分别说明，不能把 GPU 或其他推理后端的基准直接视为本工具的性能。

先安装以下工具，然后重新打开 VS Code 和终端，让新 PATH 生效：

| 工具 | 项目使用方式 |
| --- | --- |
| VS Code、Git | 克隆并打开仓库，使用内置 Node 调试终端启动 |
| Node.js | 推荐已验证的 24.13.0；启动脚本接受 22 或 24 |
| pnpm | 10.28.0，版本记录在 package.json 中 |
| Python | 3.12，Windows Python Launcher 应能识别 `py -3.12` |
| Rust | 当前验证工具链为 1.88.0，使用 Windows MSVC 工具链 |
| Microsoft C++ Build Tools | 安装“使用 C++ 的桌面开发”，包含 Windows SDK |
| Microsoft Edge WebView2 Runtime | Tauri 界面的运行环境 |
| NVIDIA 驱动 | 使用 CUDA 时，需要兼容 CUDA 12.8 的驱动；初始化脚本不修改驱动 |

官方安装入口：[Node.js](https://nodejs.org/en/download)、[pnpm](https://pnpm.io/installation)、[Python](https://www.python.org/downloads/windows/)、[Rust](https://www.rust-lang.org/tools/install)、[Tauri 的 Windows 前置要求](https://v2.tauri.app/start/prerequisites/#windows)。

## 2. 初始化依赖和模型

在 VS Code 中打开仓库根目录，在 PowerShell 终端执行：

```powershell
pnpm run setup
```

脚本创建 `.venv/Scripts/python.exe`，安装锁定的前端依赖、Python 依赖，以及 torch / torchaudio 2.8.0。检测到 `nvidia-smi` 时选择 CUDA 12.8 安装包，否则选择 CPU 安装包。默认下载 Qwen3-ASR 1.7B，首次下载可能需要较长时间和数 GB 磁盘空间；模型文件存放在上游工具的用户缓存中，不写入 Git 仓库。

明确要求 CUDA 并检查它可用：

```powershell
pnpm run setup -Device cuda
```

只准备 SenseVoice 的 CPU 路径：

```powershell
pnpm run setup -Device cpu -Models sensevoice
```

应用的新用户默认模型仍是 Qwen。若只下载了 SenseVoice，首次打开后在设置中选择 `SenseVoice Small` 并保存；初始 Qwen 缺失提示不表示 SenseVoice 安装失败。

需要三个模型时使用 `pnpm run setup -Models all`。已有虚拟环境会复用，支持标准 venv 和 `.venv/python.exe` 的 Conda 布局；脚本不覆盖损坏的现有目录。不安装系统开发工具或显卡驱动。

Python 安装由 `backend/constraints.txt` 固定经过本地测试的依赖版本。该文件是环境约束快照，CPU/CUDA 的 torch 安装来源由脚本选择；它不是跨平台锁文件。

### 2.1 单独准备其他模型

初始化完成后，无需重新安装全部依赖就能下载或检查模型：

```powershell
cd backend
..\.venv\Scripts\python.exe -m voice_prompt_sidecar.manage download --models sensevoice paraformer
..\.venv\Scripts\python.exe -m voice_prompt_sidecar.manage check --models all
cd ..
```

Conda 布局改用 `..\.venv\python.exe`。`download` 是显式联网操作，支持复用上游下载缓存；`check` 只读取本地权重，并检查必需文件及 Qwen 分片。下载失败后重新执行下载命令，完成前不要把缓存目录存在当作模型已安装。模型的来源记录写入被 Git 忽略的 `.data/model-downloads.json`；ModelScope 未提供的精确修订不会伪造为已知值。

## 3. 按 F5 启动

先检查启动环境，不打开应用：

```powershell
pnpm start:check
```

在 VS Code 的“运行和调试”中选择 `FTL Voice Prompt（快速启动）`，按 F5。首次没有 exe，或者源码更新后，启动器会构建当前源码；构建成功后打开桌面窗口。后续源码未变时复用 release exe。编译失败会停止启动并在终端显示错误。

日常也可使用 `pnpm start`。修改界面并需要热更新时，选择 `FTL Voice Prompt（桌面开发）` 或运行 `pnpm tauri:dev`。切换启动方式前先关闭已有窗口，避免两份应用争用快捷键或语音后端。快速启动是运行 release 应用，不能当作 Rust 源码断点调试。

启动器自动解析本项目的 Python，支持标准 venv 和 Conda。需要其他解释器时，可以设置 `FTL_VOICE_PROMPT_PYTHON` 为该解释器的完整路径；路径无效时明确失败，不悄悄改用系统 Python。启动期间不会自动联网下载模型。

## 4. 录音和输入文字

等待所选模型准备完成，再把光标放到目标输入框。按一次右 Alt 开始录音，提示“可以说话”后开始说话，再按一次停止。Qwen 和 SenseVoice 在停止后输出整段文字；Paraformer 在录音期间增量输入，停止后补齐尾部。

识别完成前保持目标窗口前台。目标改变、粘贴失败或识别文字发生不支持的修订时，程序保留文字供手动复制，不自动发送消息，也不自动按 Enter。右 Alt 是固定的听写键；其他 Alt 操作使用左 Alt，Ctrl/Shift/Windows 已按下时的右 Alt 组合会传给原应用。

`Ctrl+Alt+Space` 打开面板并开始录音。设置中可以选择麦克风、模型、运行设备、语言和术语。Qwen 使用术语提示，其他模型保留术语配置但不使用；SenseVoice 和 Paraformer 使用 float32。

## 5. 文本分析、历史和个人规则

语音识别在本机运行，不上传音频，也不保存录音历史。文字历史保存在本机 SQLite 数据库；历史条数设置目前限制加载和显示数量，不自动删除数据库里的旧记录，可以在历史页清空全部文字历史。

DeepSeek 是可选的联网文本分析。使用时由用户在设置中保存自己的 API Key，或设置 `DEEPSEEK_API_KEY`；保存的 Key 使用系统凭据库，不写入仓库。按“分析”，或启用自动分析后，识别文字会发送到所配置的 DeepSeek 接口。纯语音输入不需要该 Key。

当前 `backend/text-rules.env` 包含项目作者使用的文字规则，可编辑或在设置中停用数值转换及相关规则，也可用 `FTL_VOICE_PROMPT_RULES_FILE` 指定自己的 UTF-8 规则文件。保存后从下一轮录音生效，不追溯修改历史。Qwen 中文识别还会提示“会话”以减少与“绘画”混淆，属于现有识别提示。

## 6. 排查问题

| 情况 | 处理方式 |
| --- | --- |
| 找不到 Node、pnpm、Rust 或 C++ 工具 | 按第 1 节安装开发环境，重新打开终端；脚本会报告缺少的工具 |
| 找不到项目 Python 或依赖 | 执行 `pnpm run setup`；已有损坏 `.venv` 会报错，脚本不会自动删除它 |
| 缺少模型或分片 | 使用第 2.1 节下载所选模型，再执行离线检查 |
| CUDA 不可用 | 检查 NVIDIA 驱动及 torch 安装；用 `pnpm run setup -Device cuda -CheckOnly -SkipModels` 定位，CPU 兼容路径选择 SenseVoice |
| 旧语音后端协议不兼容、端口占用 | 关闭旧的项目实例；程序不会自动结束未知进程。当前后端协议为 12 |
| 构建提示 exe 拒绝访问 | 先关闭占用该构建的应用或调试会话，再重新启动 |
| 麦克风没有输入 | 检查 Windows 麦克风权限、输入设备和系统默认设置，在设置页刷新设备列表 |
| 识别成功但无法输入 | 保持目标前台，检查目标是否接受 Ctrl+V，以及两边的权限级别；使用面板手动复制 |

后端绑定本机 `127.0.0.1:8765`，它是桌面应用内部接口，不提供公网服务。环境检查 `doctor`、权重检查 `check` 和启动预检查不会录音；真实麦克风检查需要另行显式启用。

## 7. 检查代码和 CPU 集成

常规检查不下载权重、不录音：

```powershell
node --test scripts/start.test.mjs
pnpm test --no-cache
pnpm build
.\.venv\Scripts\python.exe -X utf8 -m pytest backend -q
cargo test --locked --manifest-path src-tauri/Cargo.toml
```

使用自己选择的公开测试音频检查 SenseVoice CPU 集成：

```powershell
cd backend
..\.venv\Scripts\python.exe -m voice_prompt_sidecar.manage smoke --model sensevoice --device cpu --audio C:\path\public-sample.wav
```

这条命令只识别指定文件，不打开麦克风、不写入应用历史或剪贴板，报告实际设备、非空结果的字符数和包含模型加载的耗时。它是集成冒烟，不能作为所有硬件的延迟承诺。官方支持和历史数据见 [SenseVoice](https://github.com/QwenAudio/SenseVoice#docker-support) 与 [历史基准及限制](https://github.com/modelscope/FunASR/blob/main/docs/benchmark/historical_asr.md)。

仓库的 Windows CI 会在不下载模型的 CPU 环境中检查代码并构建桌面程序。真实 VS Code F5、物理按键和麦克风体验需要对应的宿主验证，CI 构建成功不能代替这些结果。
