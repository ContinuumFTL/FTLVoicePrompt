import { useEffect, useReducer, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { DictationStream } from "./lib/dictationStream";
import {
  Clipboard,
  FileText,
  History,
  Mic,
  PanelRight,
  Send,
  Settings,
  Sparkles,
  Square,
  Trash2,
} from "lucide-react";
import type { AnalysisPreset, AppSettings, HistoryEntry, ModelPreparation } from "./types";
import { createDefaultSettings } from "./lib/settings";
import { ASR_MODELS, modelLabel } from "./lib/asrModels";
import { createHistoryEntry, trimHistory } from "./lib/history";
import { createInitialPanelState, hotkeyRecordingAction, panelReducer } from "./lib/panelState";
import {
  analyzeText,
  clearHistory,
  copyText,
  loadHistory,
  loadSettings,
  pasteTextToTarget,
  pasteDictation,
  updateRecordingOverlay,
  saveDeepSeekKey,
  saveHistoryEntry,
  saveSettings,
  showInputPanel,
  startRecording,
  stopRecording,
  recordingStatus,
  abortRecording,
  prepareModels,
  inputDevices,
} from "./lib/tauriClient";

const presetLabels: Record<AnalysisPreset, string> = {
  requirements: "需求文档",
  cleanup: "纠正原文",
};

export default function App() {
  const [settings, setSettings] = useState<AppSettings>(createDefaultSettings());
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [state, dispatch] = useReducer(panelReducer, createInitialPanelState());
  const [apiKey, setApiKey] = useState("");
  const [message, setMessage] = useState("");
  const [savingSettings, setSavingSettings] = useState(false);
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [modelPreparation, setModelPreparation] = useState<ModelPreparation | null>(null);
  const [preparationError, setPreparationError] = useState("");
  const [retryPreparation, setRetryPreparation] = useState(0);
  const [activeHistory, setActiveHistory] = useState<{ id: string; createdAt: string } | null>(null);
  const recordingStatusRef = useRef(state.recording.status);
  const recordingActionLockRef = useRef(false);
  const sessionRef = useRef<string | null>(null);
  const dictationTargetRef = useRef<number | null>(null);
  const dictationStreamRef = useRef<DictationStream | null>(null);
  const beginRecordingRef = useRef<(target?: number) => Promise<void>>(async () => undefined);
  const finishRecordingRef = useRef<() => Promise<void>>(async () => undefined);

  useEffect(() => {
    recordingStatusRef.current = state.recording.status;
    void updateRecordingOverlay(state.recording.status, state.sessionId ?? null).catch((error) => setMessage(getErrorMessage(error)));
  }, [state.recording.status, state.sessionId]);

  useEffect(() => {
    const sessionId = state.sessionId;
    if (state.recording.status !== "recording" || !sessionId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await recordingStatus(sessionId!);
        if (!active || recordingStatusRef.current !== "recording") return;
        if (result.sessionId !== sessionId) throw new Error("录音会话不匹配，请重新开始");
        if (result.error || result.status === "error") throw new Error(result.error || "识别失败");
        dispatch({ type: "transcriptionPartial", sessionId: sessionId!, text: result.rawText });
        if (result.captureWarning) setMessage(result.captureWarning);
        if (dictationStreamRef.current && result.rawText.trim()) {
          try { await dictationStreamRef.current.write(result.rawText); }
          catch (error) { if (active) setMessage(`流式输入已暂停：${getErrorMessage(error)}`); }
        }
      } catch (error) {
        if (!active || recordingStatusRef.current !== "recording") return;
        recordingStatusRef.current = "error";
        sessionRef.current = null;
        let detail = getErrorMessage(error);
        try { await abortRecording(sessionId!); }
        catch { detail += "；后端连接中断，录音会在连接超时后自动停止。"; }
        if (active) dispatch({ type: "recordingFailed", error: detail });
        if (dictationTargetRef.current !== null) void showInputPanel().catch(() => undefined);
        return;
      }
      if (active) timer = setTimeout(poll, 200);
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [state.recording.status, state.sessionId]);

  useEffect(() => () => {
    if (sessionRef.current) void abortRecording(sessionRef.current).catch(() => undefined);
  }, []);

  useEffect(() => {
    void loadSettings().then((saved) => { setSettings(saved); setSettingsLoaded(true); }).catch((error) => setMessage(getErrorMessage(error)));
    void loadHistory().then(setHistory).catch((error) => setMessage(getErrorMessage(error)));
  }, []);

  useEffect(() => {
    if (!settingsLoaded) return;
    let active = true;
    let first = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const prepared = await prepareModels(settings.asr, first && retryPreparation > 0);
        first = false;
        if (!active) return;
        setModelPreparation(prepared);
        setPreparationError("");
        if (prepared.models.every((model) => model.status === "ready" || model.status === "error")) return;
      } catch (error) {
        if (!active) return;
        setPreparationError(getErrorMessage(error));
        return;
      }
      if (active) timer = setTimeout(poll, 500);
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [settings.asr, settingsLoaded, retryPreparation]);

  useEffect(() => {
    if (state.analysis.status === "pending" && state.rawText) {
      void runAnalysis();
    }
  }, [state.analysis.status, state.rawText]);

  useEffect(() => {
    if (typeof window === "undefined" || !("__TAURI_INTERNALS__" in window)) return;
    let disposed = false;
    const unlisteners: (() => void)[] = [];
    const track = (cleanup: () => void) => { if (disposed) cleanup(); else unlisteners.push(cleanup); };
    void listen<string>("recording-overlay-error", ({ payload }) => setMessage(payload))
      .then(track).catch((error) => setMessage(getErrorMessage(error)));
    void
      listen("hotkey-opened", () => {
        const action = hotkeyRecordingAction(recordingStatusRef.current);
        if (action === "stop") void finishRecordingRef.current();
        if (action === "start") {
          void showInputPanel()
            .then(() => beginRecordingRef.current())
            .catch((error) => setMessage(getErrorMessage(error)));
        }
      }).then(track).catch((error) => setMessage(getErrorMessage(error)));
    void listen<number>("dictation-hotkey", ({ payload }) => {
      const action = hotkeyRecordingAction(recordingStatusRef.current);
      if (action === "stop") void finishRecordingRef.current();
      if (action === "start") void beginRecordingRef.current(payload);
    }).then(track).catch((error) => setMessage(getErrorMessage(error)));
    return () => {
      disposed = true;
      unlisteners.forEach((cleanup) => cleanup());
    };
  }, []);

  async function beginRecording(target?: number) {
    if (!modelPreparation?.models.some((model) => model.model === settings.asr.model && model.status === "ready") || preparationError) {
      if (target !== undefined) {
        setMessage("语音模型尚未就绪，请等待加载完成后再次按右 Alt");
        await showInputPanel().catch((error) => setMessage(getErrorMessage(error)));
      }
      return;
    }
    if (savingSettings || state.analysis.status === "running" || recordingActionLockRef.current || hotkeyRecordingAction(recordingStatusRef.current) !== "start") return;
    recordingActionLockRef.current = true;
    dictationTargetRef.current = target ?? null;
    dictationStreamRef.current = target === undefined ? null : new DictationStream((text) => pasteDictation(text, target));
    recordingStatusRef.current = "preparing";
    dispatch({ type: "recordingPreparing" });
    setActiveHistory(null);
    setMessage("");
    try {
      const result = await startRecording();
      sessionRef.current = result.sessionId;
      recordingStatusRef.current = "recording";
      dispatch({ type: "recordingStarted", sessionId: result.sessionId });
      if (result.captureWarning) setMessage(result.captureWarning);
    } catch (error) {
      recordingStatusRef.current = "error";
      dispatch({ type: "recordingFailed", error: getErrorMessage(error) });
      if (target !== undefined) await showInputPanel().catch(() => undefined);
    } finally {
      recordingActionLockRef.current = false;
    }
  }

  async function finishRecording() {
    const sessionId = sessionRef.current;
    if (!sessionId || recordingActionLockRef.current || recordingStatusRef.current !== "recording") return;
    recordingActionLockRef.current = true;
    const dictationTarget = dictationTargetRef.current;
    recordingStatusRef.current = "transcribing";
    dispatch({ type: "recordingStopped" });
    try {
      const result = await stopRecording(sessionId);
      if (result.sessionId !== sessionId || result.status !== "done" || result.error) throw new Error(result.error || "录音结果不完整，请重试");
      recordingStatusRef.current = "idle";
      if (!result.rawText.trim()) {
        dispatch({ type: "transcriptionCompleted", rawText: "", durationMs: result.durationMs, asrModel: result.model, autoAnalyze: false });
        setMessage("没有识别到有效语音");
        if (dictationTarget !== null) await showInputPanel().catch(() => undefined);
        return;
      }
      let historySaved = false;
      try {
        const entry = await saveHistoryEntry({
          rawText: result.rawText, analyzedText: "", preset: settings.deepseek.preset,
          asrModel: result.model, durationMs: result.durationMs,
        });
        setActiveHistory({ id: entry.id, createdAt: entry.createdAt });
        setHistory((items) => trimHistory([entry, ...items.filter((item) => item.id !== entry.id)], settings.history.limit));
        historySaved = true;
      } catch (error) {
        setMessage(`识别已完成，但历史保存失败：${getErrorMessage(error)}`);
      }
      // Establish the history identity before auto-analysis can run.
      dispatch({
        type: "transcriptionCompleted", rawText: result.rawText,
        durationMs: result.durationMs, asrModel: result.model,
        autoAnalyze: dictationTarget === null && historySaved && settings.deepseek.defaultAutoAnalyze,
      });
      if (dictationTarget !== null) {
        try {
          await dictationStreamRef.current?.write(result.rawText);
          if (historySaved) setMessage(result.captureWarning || "语音原文已输入");
        } catch (error) {
          setMessage(`识别已完成，自动输入失败：${getErrorMessage(error)}`);
          await showInputPanel().catch(() => undefined);
        }
      }
      if (result.captureWarning) {
        const warning = result.captureWarning;
        setMessage((current) => current.includes(warning) ? current : [current, warning].filter(Boolean).join("；"));
      }
    } catch (error) {
      await abortRecording(sessionId).catch(() => undefined);
      recordingStatusRef.current = "error";
      dispatch({ type: "recordingFailed", error: getErrorMessage(error) });
      if (dictationTarget !== null) await showInputPanel().catch(() => undefined);
    } finally {
      sessionRef.current = null;
      dictationTargetRef.current = null;
      dictationStreamRef.current = null;
      recordingActionLockRef.current = false;
    }
  }

  beginRecordingRef.current = beginRecording;
  finishRecordingRef.current = finishRecording;

  async function runAnalysis() {
    if (!state.rawText.trim() || ["preparing", "recording", "transcribing"].includes(recordingStatusRef.current)) return;
    dispatch({ type: "analysisStarted" });
    try {
      const text = await analyzeText(state.rawText, settings.deepseek.preset);
      dispatch({ type: "analysisCompleted", text });
      const entry = createHistoryEntry({
        id: activeHistory?.id,
        createdAt: activeHistory?.createdAt,
        rawText: state.rawText,
        analyzedText: text,
        preset: settings.deepseek.preset,
        asrModel: state.asrModel || settings.asr.model,
        durationMs: state.durationMs,
      });
      await saveHistoryEntry(entry);
      setActiveHistory({ id: entry.id, createdAt: entry.createdAt });
      setHistory((items) => trimHistory([entry, ...items.filter((item) => item.id !== entry.id)], settings.history.limit));
    } catch (error) {
      dispatch({ type: "analysisFailed", error: getErrorMessage(error) });
    }
  }

  async function copy(text: string) {
    await copyText(text);
    setMessage("已复制");
  }

  async function paste(text: string) {
    await pasteTextToTarget(text);
    setMessage("已贴入");
  }

  async function persistSettings(next: AppSettings) {
    if (["preparing", "recording", "transcribing"].includes(recordingStatusRef.current) || savingSettings) return;
    setSavingSettings(true);
    try {
      const saved = await saveSettings(next);
      if (saved.asr.device !== settings.asr.device || saved.asr.dtype !== settings.asr.dtype) setModelPreparation(null);
      setSettings(saved);
      setMessage("设置已保存，下次录音使用所选模型");
    } catch (error) { setMessage(getErrorMessage(error)); }
    finally { setSavingSettings(false); }
  }

  async function saveKey() {
    await saveDeepSeekKey(apiKey);
    setApiKey("");
    setMessage("Key 已保存");
  }

  async function removeHistory() {
    await clearHistory();
    setHistory([]);
    setMessage("历史已清空");
  }

  const isRecording = state.recording.status === "recording";
  const isBusy = state.recording.status === "preparing" || state.recording.status === "transcribing" || state.analysis.status === "running" || savingSettings;
  const selectedPreparation = modelPreparation?.models.find((model) => model.model === settings.asr.model);
  const modelReady = selectedPreparation?.status === "ready" && !preparationError;
  const modelStatusText = preparationError || selectedPreparation?.error || (
    modelReady ? "已就绪，可立即录音" : selectedPreparation?.status === "loading"
      ? `后台加载中（${Math.round(selectedPreparation.elapsedSeconds)} 秒），可先切换设置`
      : "正在后台准备语音引擎，窗口可正常操作"
  );

  return (
    <main className="shell">
      <aside className="sidebar" aria-label="navigation">
        <button
          className={state.view === "compose" ? "active" : ""}
          onClick={() => dispatch({ type: "viewChanged", view: "compose" })}
          title="输入"
        >
          <PanelRight size={18} />
        </button>
        <button
          className={state.view === "history" ? "active" : ""}
          onClick={() => dispatch({ type: "viewChanged", view: "history" })}
          title="历史"
        >
          <History size={18} />
        </button>
        <button
          className={state.view === "settings" ? "active" : ""}
          onClick={() => dispatch({ type: "viewChanged", view: "settings" })}
          title="设置"
        >
          <Settings size={18} />
        </button>
      </aside>

      <section className="content">
        {state.view === "compose" && (
          <ComposeView
            rawText={state.rawText}
            analysisText={state.analysis.text}
            recordingStatus={state.recording.status}
            analysisStatus={state.analysis.status}
            preset={settings.deepseek.preset}
            isRecording={isRecording}
            isBusy={isBusy}
            model={settings.asr.model}
            modelReady={modelReady}
            modelStatusText={modelStatusText}
            onRetry={() => { setPreparationError(""); setRetryPreparation((value) => value + 1); }}
            canRetry={!!preparationError || selectedPreparation?.status === "error"}
            onRawChange={(text) => dispatch({ type: "rawTextEdited", text })}
            onAnalysisChange={(text) => dispatch({ type: "analysisTextEdited", text })}
            onRecord={isRecording ? finishRecording : () => beginRecording()}
            onAnalyze={runAnalysis}
            onCopy={copy}
            onPaste={paste}
          />
        )}

        {state.view === "history" && (
          <HistoryView entries={history} onCopy={copy} onPaste={paste} onClear={removeHistory} />
        )}

        {state.view === "settings" && (
          <SettingsView
            disabled={isRecording || isBusy}
            settings={settings}
            apiKey={apiKey}
            onApiKeyChange={setApiKey}
            onSaveKey={saveKey}
            onSave={persistSettings}
          />
        )}
      </section>

      {(message || state.recording.error || state.analysis.error) && (
        <div className="toast" role="status">{state.recording.error || state.analysis.error || message}</div>
      )}
    </main>
  );
}

interface ComposeViewProps {
  modelReady: boolean;
  modelStatusText: string;
  canRetry: boolean;
  onRetry: () => void;
  model: string;
  rawText: string;
  analysisText: string;
  recordingStatus: string;
  analysisStatus: string;
  preset: AnalysisPreset;
  isRecording: boolean;
  isBusy: boolean;
  onRawChange: (text: string) => void;
  onAnalysisChange: (text: string) => void;
  onRecord: () => void;
  onAnalyze: () => void;
  onCopy: (text: string) => void;
  onPaste: (text: string) => void;
}

function ComposeView(props: ComposeViewProps) {
  return (
    <div className="compose">
      <div className="toolbar">
        <button disabled={props.isBusy || (!props.isRecording && !props.modelReady)} className={props.isRecording ? "danger" : "primary"} onClick={props.onRecord}>
          {props.isRecording ? <Square size={16} /> : <Mic size={16} />}
          {props.isRecording ? "停止" : "录音"}
        </button>
        <button onClick={props.onAnalyze} disabled={!props.rawText.trim() || props.isBusy || props.isRecording}>
          <Sparkles size={16} />
          分析
        </button>
        <span className="status">{renderStatus(props.recordingStatus, props.analysisStatus)}</span>
        <span className="preset">{presetLabels[props.preset]}</span>
      </div>
      <div className="modelStatus">{modelLabel(props.model)} · {props.modelStatusText} {props.canRetry && <button onClick={props.onRetry}>重试准备</button>}</div>
      {!props.modelReady && !props.canRetry && <progress className="modelProgress" aria-label="正在准备语音引擎" />}
      <div className="modelStatus">右 Alt：开始 / 停止 · Paraformer 边说边输入，Qwen / SenseVoice 停止后输入</div>
      <div className="split">
        <TextPane
          disabled={props.isBusy || props.isRecording}
          title="原文"
          icon={<FileText size={16} />}
          value={props.rawText}
          placeholder="..."
          onChange={props.onRawChange}
          onCopy={props.onCopy}
          onPaste={props.onPaste}
        />
        <TextPane
          disabled={props.isBusy || props.isRecording}
          title="分析"
          icon={<Sparkles size={16} />}
          value={props.analysisText}
          placeholder="..."
          onChange={props.onAnalysisChange}
          onCopy={props.onCopy}
          onPaste={props.onPaste}
        />
      </div>
    </div>
  );
}

interface TextPaneProps {
  disabled?: boolean;
  title: string;
  icon: React.ReactNode;
  value: string;
  placeholder: string;
  onChange: (text: string) => void;
  onCopy: (text: string) => void;
  onPaste: (text: string) => void;
}

function TextPane(props: TextPaneProps) {
  return (
    <section className="pane">
      <header>
        <span>
          {props.icon}
          {props.title}
        </span>
        <div className="iconButtons">
          <button title="复制" disabled={props.disabled || !props.value.trim()} onClick={() => props.onCopy(props.value)}>
            <Clipboard size={15} />
          </button>
          <button title="贴入" disabled={props.disabled || !props.value.trim()} onClick={() => props.onPaste(props.value)}>
            <Send size={15} />
          </button>
        </div>
      </header>
      <textarea readOnly={props.disabled} value={props.value} placeholder={props.placeholder} onChange={(event) => props.onChange(event.target.value)} />
    </section>
  );
}

function HistoryView({
  entries,
  onCopy,
  onPaste,
  onClear,
}: {
  entries: HistoryEntry[];
  onCopy: (text: string) => void;
  onPaste: (text: string) => void;
  onClear: () => void;
}) {
  return (
    <div className="historyView">
      <div className="toolbar">
        <span className="sectionTitle">历史</span>
        <button onClick={onClear} disabled={entries.length === 0}>
          <Trash2 size={16} />
          清空
        </button>
      </div>
      <div className="historyList">
        {entries.map((entry) => (
          <article className="historyItem" key={entry.id}>
            <time>{new Date(entry.createdAt).toLocaleString()}</time>
            <p>{entry.analyzedText || entry.rawText}</p>
            <div className="historyActions">
              <button onClick={() => onCopy(entry.rawText)}>复制原文</button>
              <button onClick={() => onPaste(entry.rawText)}>贴入原文</button>
              {entry.analyzedText && <button onClick={() => onCopy(entry.analyzedText!)}>复制分析</button>}
              {entry.analyzedText && <button onClick={() => onPaste(entry.analyzedText!)}>贴入分析</button>}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

function SettingsView({
  disabled,
  settings,
  apiKey,
  onApiKeyChange,
  onSaveKey,
  onSave,
}: {
  disabled: boolean;
  settings: AppSettings;
  apiKey: string;
  onApiKeyChange: (value: string) => void;
  onSaveKey: () => void;
  onSave: (settings: AppSettings) => void;
}) {
  const [draft, setDraft] = useState(settings);
  const [devices, setDevices] = useState<import("./types").AudioInputDevice[]>([]);
  const [loadingDevices, setLoadingDevices] = useState(false);
  const [deviceError, setDeviceError] = useState("");
  const selectedDeviceId = devices.find((device) => device.id === draft.asr.inputDevice || device.aliases?.includes(draft.asr.inputDevice))?.id ?? draft.asr.inputDevice;

  async function refreshDevices() {
    setLoadingDevices(true);
    setDeviceError("");
    try {
      setDevices(await inputDevices());
    } catch (error) {
      setDeviceError(getErrorMessage(error));
    } finally {
      setLoadingDevices(false);
    }
  }

  useEffect(() => {
    if (!disabled) void refreshDevices();
  }, [disabled]);

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  return (
    <fieldset disabled={disabled} className="settingsView">
      <label>
        <span>麦克风</span>
        <select aria-label="麦克风" disabled={loadingDevices} value={selectedDeviceId}
          onChange={(event) => setDraft({ ...draft, asr: { ...draft.asr, inputDevice: event.target.value } })}>
          <option value="">跟随系统默认麦克风</option>
          {draft.asr.inputDevice && !devices.some((device) => device.id === selectedDeviceId) &&
            <option value={draft.asr.inputDevice}>已保存的麦克风（当前未找到）</option>}
          {devices.map((device, index) => <option key={`${device.id}-${index}`} value={device.id}>{device.name}</option>)}
        </select>
      </label>
      <button type="button" disabled={loadingDevices} onClick={() => void refreshDevices()}>{loadingDevices ? "正在刷新麦克风…" : "刷新设备"}</button>
      {deviceError && <p role="alert">{deviceError}</p>}
      <p className="settingsHint">切换或插拔麦克风后可刷新列表。保存后用于下一次录音；跟随系统默认时，每次录音重新获取默认设备。</p>
      <label>
        <span>快捷键</span>
        <input readOnly value="右 Alt（语音输入）；Ctrl+Alt+Space（面板）" />
      </label>
      <label>
        <span>模型</span>
        <select aria-label="模型" value={draft.asr.model} onChange={(event) => setDraft({ ...draft, asr: { ...draft.asr, model: event.target.value, dtype: "auto" } })}>
          {ASR_MODELS.map((model) => <option key={model.id} value={model.id}>{model.label}</option>)}
        </select>
      </label>
      <label>
        <span>模型运行设备</span>
        <select value={draft.asr.device} onChange={(event) => setDraft({ ...draft, asr: { ...draft.asr, device: event.target.value as AppSettings["asr"]["device"] } })}>
          <option value="cuda:0">cuda:0</option>
          <option value="auto">auto</option>
          <option value="cpu">cpu</option>
        </select>
      </label>
      <label>
        <span>精度</span>
        <select disabled={draft.asr.model !== ASR_MODELS[0].id} value={draft.asr.dtype} onChange={(event) => setDraft({ ...draft, asr: { ...draft.asr, dtype: event.target.value as AppSettings["asr"]["dtype"] } })}>
          <option value="bfloat16">bfloat16</option>
          <option value="auto">auto</option>
          <option value="float16">float16</option>
          <option value="float32">float32</option>
        </select>
      </label>
      <label>
        <span>语言</span>
        <select disabled={draft.asr.model === "paraformer-zh-streaming"} value={draft.asr.language} onChange={(event) => setDraft({ ...draft, asr: { ...draft.asr, language: event.target.value } })}>
          <option value="auto">自动判断语言</option>
          <option value="zh">中文</option>
          <option value="en">英语</option>
        </select>
      </label>
      <p className="settingsHint">只加载当前选择的模型，保存后下次启动会沿用。切换模型会释放旧模型并加载新模型。SenseVoice / Paraformer 使用 float32，Paraformer 自动识别中英文。</p>
      <label className="termsField">
        <span>常用术语（每行一个，仅 Qwen 使用）</span>
        <textarea aria-label="常用术语" rows={4} placeholder={"Vibe Coding\nHarness Engineering"} value={draft.asr.terms} onChange={(event) => setDraft({ ...draft, asr: { ...draft.asr, terms: event.target.value } })} />
      </label>
      <p className="settingsHint">填写希望准确识别的术语原文。保存后用于下一次录音，不会强制替换识别结果。Qwen 中文识别会额外提示“会话”，减少与“绘画”混淆。</p>
      <label>
        <span>预设</span>
        <select
          value={draft.deepseek.preset}
          onChange={(event) =>
            setDraft({ ...draft, deepseek: { ...draft.deepseek, preset: event.target.value as AnalysisPreset } })
          }
        >
          <option value="requirements">结构化需求文档</option>
          <option value="cleanup">纠正语音内容</option>
        </select>
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={draft.deepseek.defaultAutoAnalyze}
          onChange={(event) =>
            setDraft({ ...draft, deepseek: { ...draft.deepseek, defaultAutoAnalyze: event.target.checked } })
          }
        />
        <span>录完自动分析</span>
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={draft.paste.restoreClipboard}
          onChange={(event) => setDraft({ ...draft, paste: { ...draft.paste, restoreClipboard: event.target.checked } })}
        />
        <span>贴入后恢复剪贴板</span>
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={draft.asr.englishPunctuation} onChange={(event) => setDraft({ ...draft, asr: { ...draft.asr, englishPunctuation: event.target.checked } })} />
        <span>英文标点，句读标点后加空格</span>
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={draft.asr.arabicNumbers} onChange={(event) => setDraft({ ...draft, asr: { ...draft.asr, arabicNumbers: event.target.checked } })} />
        <span>中文数值转阿拉伯数字</span>
      </label>
      <p className="settingsHint">数值默认用阿拉伯数字，再按规则替换，如“一个、两个、一些、一看、二看”。可编辑 backend/text-rules.env 查看和修改全部个人规则，保存后从下一次录音生效。</p>
      <label>
        <span>历史数量</span>
        <input
          type="number"
          min={1}
          max={500}
          value={draft.history.limit}
          onChange={(event) =>
            setDraft({ ...draft, history: { ...draft.history, limit: Number(event.target.value) || 100 } })
          }
        />
      </label>
      <label>
        <span>DeepSeek Key</span>
        <input type="password" value={apiKey} onChange={(event) => onApiKeyChange(event.target.value)} />
      </label>
      <div className="settingsActions">
        <button onClick={() => onSave(draft)}>保存设置</button>
        <button onClick={onSaveKey} disabled={!apiKey.trim()}>
          保存 Key
        </button>
      </div>
    </fieldset>
  );
}

function renderStatus(recordingStatus: string, analysisStatus: string): string {
  if (recordingStatus === "preparing") return "正在开启麦克风";
  if (recordingStatus === "recording") return "录音中";
  if (recordingStatus === "transcribing") return "转写中";
  if (analysisStatus === "running") return "分析中";
  return "就绪";
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
