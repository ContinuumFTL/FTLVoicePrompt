import { describe, expect, it } from "vitest";
import { createDefaultSettings, normalizeSettings } from "./settings";

describe("settings defaults", () => {
  it("uses manual DeepSeek analysis with a Windows global hotkey by default", () => {
    const settings = createDefaultSettings();

    expect(settings.hotkey).toBe("Ctrl+Alt+Space");
    expect(settings.asr.model).toBe("Qwen/Qwen3-ASR-1.7B");
    expect(settings.asr.device).toBe("auto");
    expect(settings.deepseek.defaultAutoAnalyze).toBe(false);
    expect(settings.deepseek.model).toBe("deepseek-v4-flash");
    expect(settings.deepseek.preset).toBe("requirements");
    expect(settings.paste.restoreClipboard).toBe(true);
  });

  it("keeps known values and fills missing nested settings", () => {
    const settings = normalizeSettings({
      hotkey: "Ctrl+Shift+Space",
      asr: { model: "Qwen/Qwen3-ASR-1.7B" },
      history: { limit: 20 },
    });

    expect(settings.hotkey).toBe("Ctrl+Shift+Space");
    expect(settings.asr.model).toBe("Qwen/Qwen3-ASR-1.7B");
    expect(settings.asr.device).toBe("auto");
    expect(settings.asr.language).toBe("zh");
    expect(settings.history.limit).toBe(20);
    expect(settings.deepseek.baseUrl).toBe("https://api.deepseek.com");
  });
});
