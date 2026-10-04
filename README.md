# FTL Voice Prompt

Windows-only local-first voice prompt input panel.

新用户请先阅读 [中文快速开始](docs/getting-started.md)。项目以 Windows + NVIDIA 显卡为主要使用环境，提供明确的环境初始化、模型准备和 VS Code F5 启动入口；SenseVoice Small 的 CPU 路径可单独检查。

项目代码采用 [MIT 许可证](LICENSE)。模型权重和第三方依赖遵循各自的许可，见 [第三方说明](THIRD_PARTY_NOTICES.md)。

## What It Does

- Settings include a per-line terminology list used as Qwen recognition context for the next recording. Other models retain the list but do not use it. Terms are hints, not unconditional replacements.
- Chinese punctuation (with one space after sentence punctuation) and numeric values are converted by default in transcripts, history and dictation. Each conversion can be disabled in settings. Numbers default to Arabic digits, then common one/two counting expressions use Chinese (including 一点、两点、一个、两个). Complete decimals are parsed first, including mixed forms such as 五点5 → 5.5; opus is written as Opus. Listed lexical exceptions such as 一起 and 一定 stay Chinese. Streaming holds unfinished numeric expressions and lexical exceptions until enough following text arrives.

Personal text rules are listed explicitly in [`backend/text-rules.env`](backend/text-rules.env), including `1些=>一些`, `1看=>一看` and `2看=>二看`. Edit this UTF-8 file and save; the next recording reloads it, while an existing recording keeps its original rules. Each `REPLACE_` line maps an Arabic integer followed by Chinese text to a literal result; longest matches win without cascading. `KEEP_` lines protect fixed expressions before numeric conversion, and `CASE_` lines normalize English word casing. The file contains all personal exceptions; removing a line removes that rule. Numeric parsing and boundaries remain in code, so `11个`, `第1个`, `1.2个`, `-2个` and `v1个` do not match the `1个` rule. Use unique keys and double-quoted values, with comments on separate lines. Missing or malformed files report their path (and line for syntax errors) before recording starts. The process environment variable `FTL_VOICE_PROMPT_RULES_FILE` can select another file by absolute path. Disabling numeric conversion also disables these rules.

Verb repetitions such as `瞧1瞧、看1看、用1用、使1使、钓1钓` use the same editable rules. To check the running backend without recording audio or pasting text, POST `/format/preview` on `http://127.0.0.1:8765` with `{"text":"看1看","settings":{"arabicNumbers":true}}`. The response includes the formatted `text`, backend `pid`, and `rulesFile`; GET `/health` returns the same PID and protocol version. Protocol 12 is required by the desktop client, so it rejects older backends that lack the external rule loader. Restarting the desktop alone can reuse an orphaned backend; an obsolete backend must be stopped after confirming it is idle before preparing models again.

On Windows, newly spawned speech backends are assigned to a desktop-owned job with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Windows terminates those backends and their descendants when the desktop exits, including forced termination such as stopping a debug task, without relying on Rust destructors. Failure to attach the backend is reported and that child is stopped. This cannot retroactively manage a backend started by an older desktop version. The `sidecar_job` Rust regression forcibly kills a separate test parent and verifies its attached child exits; it uses no microphone or model.

- With the app running and the selected model ready, click an input field in Notepad, Codex Desktop, or another app. Tap **Right Alt** to start recording and tap again to stop. Qwen and SenseVoice recognize the entire recording only after stop, then insert the complete transcript. Paraformer appends text during recording and inserts only the remaining tail after stop. The voice panel does not take focus. This inserts text only; it does not press Enter or send a message, and this mode does not run DeepSeek analysis.
- A small microphone capsule appears above the taskbar on the input window's screen. It is always on top, does not take keyboard focus, and lets mouse clicks pass through. It shows microphone startup and recording, then hides immediately when stop is requested. Its waveform uses actual 50 ms RMS measurements from the recording stream; silence produces flat bars, not a decorative animation. The visible capsule polls volume independently so slower recognition does not stop microphone feedback.
- Qwen and SenseVoice are never split into short recognition segments, in either Right Alt or panel recording. Paraformer alone uses native streaming. Streaming text is appended without rewriting existing input; a failed insertion or unexpected recognizer revision pauses further automatic writes and retains the complete transcript for manual copying.
- Model preparation also opens an inactive microphone stream; capturing starts only when recording is requested. The stream is reused between recordings. The capsule reports "可以说话" only after the first valid input buffer arrives; startup without valid samples fails rather than pretending to record. A short startup gap still exists, so wait for this indication before speaking.
- Input overflow/underflow no longer causes the current audio buffer to be silently dropped. Capture warnings and significant clipping are surfaced in the capsule and panel; driver-lost audio cannot be reconstructed. The response includes capture readiness and microphone start-to-first-buffer time for diagnostics. Chinese is the default language for Qwen and SenseVoice; language selection persists when switching models. Paraformer uses its Chinese streaming model without a language override. Automatic language detection remains selectable.
- Stopping keeps the microphone active for another 1.5 seconds to capture trailing syllables. The capsule stays hidden during this trailing capture and final transcription. Offline models still transcribe the whole recording only once.
- Right Alt is reserved for dictation (triggered immediately on key-down; holding it does not repeat). Use Left Alt for normal Alt combinations. Right Alt pressed with Ctrl/Shift/Windows already held is passed through, including AltGr layouts that synthesize Ctrl. The existing panel shortcut remains available.
- Keep the destination input focused until transcription finishes. If another window is foreground or a modifier is held at paste time, automatic input is refused and the transcript remains in the panel for manual copying. Apps must accept Ctrl+V; Windows can block input into elevated apps when the voice app runs at a lower privilege level. Closing the voice app disables the shortcut; minimizing it keeps the shortcut active.
- `Ctrl+Alt+Space` brings the window forward without moving it and starts recording.
- The app uses a normal resizable window with a system title bar and taskbar entry; it does not follow input fields or stay always on top.
- Press the shortcut again, or click `停止`, to stop and transcribe.
- Select Qwen3-ASR 1.7B, SenseVoice Small, or Paraformer Chinese streaming in settings and save. The selection persists and applies to the next recording.
- Both recording modes follow the selected model: Paraformer displays text while speaking and flushes the remaining audio on stop; Qwen and SenseVoice transcribe the whole recording after stop.
- Startup restores the saved model selection and loads only that model in the background. Switching releases the previous model and loads the new selection; other installed models are not preloaded. Recording becomes available when the selected model is ready; loading never starts the microphone automatically.
- The main window is visible during startup. A lightweight HTML loading indicator appears before React loads, followed by the editor and a separate indeterminate progress bar while the speech engine prepares. The recording capsule WebView is created on first recording, so it does not delay the main window at startup.
- Startup phase timings are written to `startup.log` in the application data directory (`FTL_STARTUP_LOG` can override the file path). The log contains elapsed milliseconds for process entry, setup, page load, React commit, a paint opportunity, and model readiness; a paint opportunity alone does not prove pixels reached the screen. No settings or transcript text are logged.
- Model loading uses local weights only, avoiding online metadata timeouts. Missing weights or loading failures show an error with a retry button. Changing device or precision requires preparation again.
- The left pane keeps the local transcript. Partial text cannot be edited, copied, pasted, or analyzed until transcription finishes.
- `分析` sends the transcript text to DeepSeek and writes the result into the right pane.
- Both panes and history entries support copy and paste into the previously focused input.
- History stores text only. Audio is not retained.

## Local Development

Recommended first-time setup (Windows PowerShell, after installing the prerequisites in the quick-start guide):

```powershell
pnpm run setup
pnpm start:check
```

This installs the pinned Python environment and downloads Qwen weights explicitly. Use `pnpm run setup -Device cpu -Models sensevoice` for the CPU path, then select SenseVoice in the app settings. Existing standard venv and Conda-style project interpreters are both supported. `pnpm run setup -CheckOnly -SkipModels` inspects the existing environment without installing packages or downloading weights. The commands below are the manual alternative.

Install Node/Rust dependencies:

```powershell
pnpm install
```

Create and install the Python sidecar environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "backend[test]"
```

This checkout currently uses a conda-style environment at `.venv/python.exe`; use that interpreter instead of `.venv/Scripts/python.exe` for the commands below. The application detects both layouts.

For a compatible NVIDIA GPU, install the matching CUDA pair before the backend dependencies. The RTX 4090 environment was verified with:

```powershell
.\.venv\python.exe -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
.\.venv\python.exe -m pip install -e "backend[test]"
```

`auto` uses CUDA when available and CPU otherwise. SenseVoice and Paraformer use float32; Qwen uses the selected GPU precision (float32 on CPU). Paraformer handles Chinese/English automatically.

For everyday use, start the release executable. The launcher builds it when missing or older than the current source; otherwise it reuses the existing executable without a development server:

```powershell
pnpm start
```

In VS Code select `FTL Voice Prompt（快速启动）`. Both launch configurations use the project launcher to resolve Python. Static configuration and command prechecks are distinct from a real VS Code F5 test. The `FTL Voice Prompt（桌面开发）` configuration remains available for development:

```powershell
pnpm tauri:dev
```

Build the local executable:

```powershell
pnpm tauri build
```

The built executable is written to `src-tauri/target/release/ftl-voice-prompt.exe`.

## DeepSeek

Set `DEEPSEEK_API_KEY` in the environment or save the key from the settings view.

The app uses:

- Base URL: `https://api.deepseek.com`
- Model: `deepseek-v4-flash`
- Thinking: disabled

Only transcript text is sent to DeepSeek. Audio is not uploaded.

## Verification

The native startup regression uses the production frontend with a deliberately slow, fake speech backend. It verifies that the visible editor and loading progress render while preparation is still pending. It uses a separate WebView profile, starts no microphone or Python process, and registers no global shortcuts:

```powershell
pnpm build
cargo run --release --features tauri/custom-protocol --manifest-path src-tauri/Cargo.toml --example startup_smoke
```

```powershell
pnpm test
pnpm build
.\.venv\Scripts\python.exe -m pytest backend
cd src-tauri
cargo test
```

An opt-in native paste check creates and closes a disposable Windows EDIT control (briefly taking focus), then verifies mixed Chinese/English text through the production clipboard/SendInput path:

```powershell
cargo test --manifest-path src-tauri/Cargo.toml --test paste_tests native_edit_receives_unicode_dictation -- --ignored --nocapture
```

Right Alt verification covers tap/repeat/modifier handling, partial writes before stop, serialized final-tail insertion without duplication, preserving text on write failure, and the native EDIT paste check. Waveform tests cover measured sound, silence, and capture completion. The opt-in real-model test verifies output before stop for Paraformer and output only after stop for Qwen/SenseVoice using a public audio sample. These checks do not replace physical-key/microphone testing in Notepad or Codex Desktop.

The optional hardware check briefly captures twice using the default microphone, retaining only counts and startup diagnostics, then closes the device. No audio is written or transcribed:

```powershell
$env:FTL_REAL_MICROPHONE = "1"
.\.venv\python.exe -X utf8 -m pytest backend/tests/test_real_microphone.py -s -q
Remove-Item Env:FTL_REAL_MICROPHONE
```

On this machine the prepared microphone delivered its first valid buffer in 78 ms and 15 ms in two consecutive checks. These measure the microphone stage only, not full hotkey latency or recognition accuracy.

The native capsule smoke test briefly shows synthetic meter samples, checks frontend polling, state transitions, hiding, and foreground preservation, then exits without opening the microphone:

```powershell
pnpm build
cargo run --release --features tauri/custom-protocol --manifest-path src-tauri/Cargo.toml --example overlay_smoke
```

The application reads weights from local Hugging Face / ModelScope caches. A fresh machine prepares weights with `pnpm run setup` or the explicit model download commands in the quick-start guide; application startup does not download weights. To verify installed models explicitly with a public Chinese audio sample, without recording the microphone:

```powershell
$env:FTL_REAL_MODELS = "1"
.\.venv\python.exe -X utf8 -m pytest backend/tests/test_real_models.py -s -q
Remove-Item Env:FTL_REAL_MODELS
```

This opt-in test loads actual models and checks streaming results before stop, cache reset, and switching back to Qwen. Normal tests skip this real-model check. The sidecar protocol is version 12; an already running incompatible sidecar must be closed before trying the new executable. Closing the main window stops its owned sidecar.

Startup measurements on this RTX 4090 machine (2026-09-08): the earlier 0.13-second result measured only the native window shell and must not be interpreted as usable UI startup. After delaying window display until React commits the interface, a release launch reached visible, accessible recording/settings/transcript controls in 0.74 seconds (Windows UI Automation check). This measures actual controls, not pixel-level first paint; WebView remote debugging was unavailable on this machine. The window uses a white background and a startup placeholder, with an eight-second visibility fallback if the frontend fails to mount.

These measurements apply to the release executable, not `tauri:dev`, which also loads the interface from Vite. The earlier three-model preload and instant-switch strategy has been removed: only the saved selection loads at startup, and switching models now requires loading again. The selected model remains reusable for repeated recordings in the same session. Model preparation time depends on the selection and does not block the window or settings. Model choices are saved immediately when settings are saved, so restarting restores the last saved choice even after an unexpected exit. Checks cover single-model loading, previous-model release, skipping obsolete queued selections, and settings persistence; they do not use the microphone.
