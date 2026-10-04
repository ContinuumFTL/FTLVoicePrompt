export type AnalysisPreset = "requirements" | "cleanup";

export interface AsrSettings {
  inputDevice: string;
  model: string;
  device: "auto" | "cuda:0" | "cpu";
  dtype: "auto" | "bfloat16" | "float16" | "float32";
  terms: string;
  englishPunctuation: boolean;
  arabicNumbers: boolean;
  language: string;
}

export interface AudioInputDevice {
  id: string;
  name: string;
  hostApi: string;
  aliases?: string[];
}

export interface DeepSeekSettings {
  enabled: boolean;
  defaultAutoAnalyze: boolean;
  baseUrl: string;
  model: string;
  preset: AnalysisPreset;
}

export interface HistorySettings {
  limit: number;
}

export interface PasteSettings {
  restoreClipboard: boolean;
}

export interface AppSettings {
  hotkey: string;
  asr: AsrSettings;
  deepseek: DeepSeekSettings;
  history: HistorySettings;
  paste: PasteSettings;
}

export interface HistoryEntry {
  id: string;
  createdAt: string;
  rawText: string;
  analyzedText?: string;
  preset: AnalysisPreset;
  asrModel: string;
  durationMs: number;
  audioPath?: never;
}

export interface TranscriptionResult {
  audioLevels?: number[];
  captureReady?: boolean;
  stopRequested?: boolean;
  captureStartMs?: number | null;
  captureWarning?: string | null;
  sessionId: string;
  status: "recording" | "transcribing" | "done" | "error";
  error?: string | null;
  rawText: string;
  durationMs: number;
  model: string;
  language: string;
}

export interface ModelPreparation {
  selected: string;
  models: Array<{ model: string; status: "queued" | "loading" | "ready" | "error"; error?: string | null; elapsedSeconds: number }>;
}

export interface SaveHistoryInput {
  id?: string;
  createdAt?: string;
  rawText: string;
  analyzedText?: string;
  preset: AnalysisPreset;
  asrModel: string;
  durationMs: number;
}
