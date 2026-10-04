import { invoke } from "@tauri-apps/api/core";
import type { AnalysisPreset, AppSettings, HistoryEntry, SaveHistoryInput, TranscriptionResult, ModelPreparation, AsrSettings } from "../types";
import { createDefaultSettings, normalizeSettings } from "./settings";
import { createHistoryEntry, trimHistory } from "./history";

const SETTINGS_KEY = "ftl-voice-prompt.settings";
const HISTORY_KEY = "ftl-voice-prompt.history";

export async function inputDevices(): Promise<import("../types").AudioInputDevice[]> {
  if (isTauriRuntime()) return invoke("input_devices");
  return [];
}

export async function prepareModels(settings: AsrSettings, retry = false): Promise<ModelPreparation> {
  if (isTauriRuntime()) return invoke("prepare_models", { settings, retry });
  return { selected: settings.model, models: [{ model: settings.model, status: "ready", elapsedSeconds: 0 }] };
}

export async function loadSettings(): Promise<AppSettings> {
  if (isTauriRuntime()) {
    return normalizeSettings(await invoke<AppSettings>("load_settings"));
  }
  const raw = localStorage.getItem(SETTINGS_KEY);
  return normalizeSettings(raw ? JSON.parse(raw) : null);
}

export async function saveSettings(settings: AppSettings): Promise<AppSettings> {
  const normalized = normalizeSettings(settings);
  if (isTauriRuntime()) {
    return normalizeSettings(await invoke<AppSettings>("save_settings", { settings: normalized }));
  }
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(normalized));
  return normalized;
}

export async function saveDeepSeekKey(key: string): Promise<void> {
  if (isTauriRuntime()) {
    await invoke("save_deepseek_key", { key });
  } else {
    sessionStorage.setItem("ftl-voice-prompt.deepseek-key", key);
  }
}

export async function startRecording(): Promise<TranscriptionResult> {
  if (isTauriRuntime()) {
    return invoke<TranscriptionResult>("start_recording");
  }
  return { sessionId: crypto.randomUUID(), status: "recording", rawText: "", model: (await loadSettings()).asr.model, durationMs: 0, language: "auto" };
}

export async function recordingStatus(sessionId: string): Promise<TranscriptionResult> {
  if (isTauriRuntime()) return invoke("recording_status", { sessionId });
  return { sessionId, status: "recording", rawText: "", model: "dev-fake", durationMs: 0, language: "auto" };
}

export async function abortRecording(sessionId: string): Promise<void> {
  if (isTauriRuntime()) await invoke("abort_recording", { sessionId });
}

export async function showInputPanel(): Promise<void> {
  if (isTauriRuntime()) {
    await invoke("show_input_panel");
  }
}

export async function stopRecording(sessionId: string): Promise<TranscriptionResult> {
  if (isTauriRuntime()) {
    return invoke<TranscriptionResult>("stop_recording", { sessionId });
  }
  return {
    sessionId,
    status: "done",
    rawText: "帮我检查这个 React component 里面的 useMemo，resource merge 的逻辑可以抽出去。",
    durationMs: 1800,
    model: "dev-fake",
    language: "zh",
  };
}

export async function analyzeText(text: string, preset: AnalysisPreset): Promise<string> {
  if (isTauriRuntime()) {
    return invoke<string>("analyze_text", { text, preset });
  }
  if (preset === "cleanup") {
    return text.replace(/\s+/g, " ").trim();
  }
  return `请根据以下口述需求进行处理：\n- ${text.trim()}\n- 保留技术名词、文件名、函数名和变量名\n- 如有不确定内容，请标注需要确认`;
}

export async function copyText(text: string): Promise<void> {
  if (isTauriRuntime()) {
    await invoke("copy_text", { text });
  } else {
    await navigator.clipboard?.writeText(text);
  }
}

export async function pasteTextToTarget(text: string): Promise<void> {
  if (isTauriRuntime()) {
    await invoke("paste_text_to_target", { text });
  } else {
    await copyText(text);
  }
}

export async function pasteDictation(text: string, target: number): Promise<void> {
  if (isTauriRuntime()) await invoke("paste_dictation", { text, target });
}

export async function updateRecordingOverlay(status: string, sessionId: string | null): Promise<void> {
  if (isTauriRuntime()) await invoke("update_recording_overlay", { status, sessionId });
}

export async function loadHistory(): Promise<HistoryEntry[]> {
  if (isTauriRuntime()) {
    return invoke<HistoryEntry[]>("load_history");
  }
  const raw = localStorage.getItem(HISTORY_KEY);
  return raw ? JSON.parse(raw) : [];
}

export async function saveHistoryEntry(input: SaveHistoryInput): Promise<HistoryEntry> {
  if (isTauriRuntime()) {
    return invoke<HistoryEntry>("save_history_entry", { entry: input });
  }
  const settings = createDefaultSettings();
  const entry = createHistoryEntry(input);
  const entries = trimHistory(
    [entry, ...(await loadHistory()).filter((item) => item.id !== entry.id)],
    settings.history.limit,
  );
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
  return entry;
}

export async function clearHistory(): Promise<void> {
  if (isTauriRuntime()) {
    await invoke("clear_history");
  } else {
    localStorage.removeItem(HISTORY_KEY);
  }
}

function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
