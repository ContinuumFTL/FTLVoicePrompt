import type { AppSettings } from "../types";

type PartialDeep<T> = {
  [K in keyof T]?: T[K] extends object ? PartialDeep<T[K]> : T[K];
};

export function createDefaultSettings(): AppSettings {
  return {
    hotkey: "Ctrl+Alt+Space",
    asr: {
      inputDevice: "",
      model: "Qwen/Qwen3-ASR-1.7B",
      device: "auto",
      dtype: "bfloat16",
      language: "zh",
      terms: "",
      englishPunctuation: true,
      arabicNumbers: true,
    },
    deepseek: {
      enabled: true,
      defaultAutoAnalyze: false,
      baseUrl: "https://api.deepseek.com",
      model: "deepseek-v4-flash",
      preset: "requirements",
    },
    history: {
      limit: 100,
    },
    paste: {
      restoreClipboard: true,
    },
  };
}

export function normalizeSettings(input?: PartialDeep<AppSettings> | null): AppSettings {
  const defaults = createDefaultSettings();
  if (!input) return defaults;

  return {
    ...defaults,
    ...input,
    asr: {
      ...defaults.asr,
      ...input.asr,
    },
    deepseek: {
      ...defaults.deepseek,
      ...input.deepseek,
    },
    history: {
      ...defaults.history,
      ...input.history,
    },
    paste: {
      ...defaults.paste,
      ...input.paste,
    },
  };
}
