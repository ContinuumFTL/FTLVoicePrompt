import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import * as client from "./lib/tauriClient";
import { createDefaultSettings } from "./lib/settings";
import type { TranscriptionResult } from "./types";

const hotkeys = vi.hoisted(() => new Map<string, (event: { payload: number | string }) => void>());
vi.mock("@tauri-apps/api/event", () => ({
  listen: async (name: string, callback: (event: { payload: number | string }) => void) => { hotkeys.set(name, callback); return () => hotkeys.delete(name); },
}));

vi.mock("./lib/tauriClient", () => ({
  inputDevices: vi.fn(),
  prepareModels: vi.fn(), loadSettings: vi.fn(), loadHistory: vi.fn(), startRecording: vi.fn(),
  recordingStatus: vi.fn(), stopRecording: vi.fn(), abortRecording: vi.fn(),
  saveSettings: vi.fn(), saveHistoryEntry: vi.fn(), analyzeText: vi.fn(),
  clearHistory: vi.fn(), copyText: vi.fn(), pasteTextToTarget: vi.fn(), pasteDictation: vi.fn(), updateRecordingOverlay: vi.fn(),
  saveDeepSeekKey: vi.fn(), showInputPanel: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

let root: Root;
let container: HTMLDivElement;
const result: TranscriptionResult = { sessionId: "one", status: "recording", rawText: "", model: "paraformer-zh-streaming", language: "auto", durationMs: 1200 };

beforeEach(async () => {
  vi.resetAllMocks();
  vi.mocked(client.inputDevices).mockResolvedValue([{ id: "usb-mic", name: "USB Microphone", hostApi: "Windows WASAPI" }]);
  Object.assign(window, { __TAURI_INTERNALS__: {} });
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const settings = createDefaultSettings();
  settings.asr.model = result.model;
  vi.mocked(client.prepareModels).mockImplementation(async (asr) => ({ selected: asr.model,
    models: [{model: asr.model, status: "ready", elapsedSeconds: 0}] }));
  vi.mocked(client.loadSettings).mockResolvedValue(settings);
  vi.mocked(client.loadHistory).mockResolvedValue([]);
  vi.mocked(client.abortRecording).mockResolvedValue();
  vi.mocked(client.showInputPanel).mockResolvedValue();
  vi.mocked(client.updateRecordingOverlay).mockResolvedValue();
  vi.mocked(client.saveSettings).mockImplementation(async (settings) => structuredClone(settings));
  vi.mocked(client.saveHistoryEntry).mockImplementation(async (entry) => ({ ...entry, id: "history", createdAt: new Date().toISOString() }));
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<App />));
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  Reflect.deleteProperty(window, "__TAURI_INTERNALS__");
  vi.useRealTimers();
});

function button(text: string) {
  return [...container.querySelectorAll("button")].find((button) => button.textContent?.trim() === text)!;
}

describe("model selection and live recording", () => {
  it("surfaces capsule recovery failures without stopping dictation", async () => {
    vi.mocked(client.startRecording).mockResolvedValue(result);
    vi.mocked(client.recordingStatus).mockResolvedValue({ ...result, rawText: "继续输入" });
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    await act(async () => hotkeys.get("recording-overlay-error")!({ payload: "录音仍可继续，胶囊恢复失败" }));
    expect(container.textContent).toContain("录音仍可继续，胶囊恢复失败");
    expect(button("停止").disabled).toBe(false);
    expect(client.stopRecording).not.toHaveBeenCalled();
    expect(client.abortRecording).not.toHaveBeenCalled();
    expect(client.pasteDictation).toHaveBeenCalledWith("继续输入", 123);
  });
  it("writes partial text before stop and only appends the final tail", async () => {
    vi.mocked(client.startRecording).mockResolvedValue(result);
    vi.mocked(client.recordingStatus).mockResolvedValue({ ...result, rawText: "实时内容" });
    vi.mocked(client.stopRecording).mockResolvedValue({ ...result, status: "done", rawText: "实时内容，结束" });
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    expect(client.startRecording).toHaveBeenCalledWith();
    expect(client.pasteDictation).toHaveBeenCalledWith("实时内容", 123);
    expect(client.stopRecording).not.toHaveBeenCalled();
    expect(client.updateRecordingOverlay).toHaveBeenCalledWith("recording", "one");
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    expect(vi.mocked(client.pasteDictation).mock.calls).toEqual([["实时内容", 123], ["，结束", 123]]);
    expect(client.updateRecordingOverlay).toHaveBeenLastCalledWith("idle", "one");
  });
  it("dictates into the starting window without opening the panel or analyzing", async () => {
    await act(async () => (container.querySelector('button[title="设置"]') as HTMLButtonElement).click());
    await act(async () => (container.querySelector('input[type="checkbox"]') as HTMLInputElement).click());
    await act(async () => button("保存设置").click());
    expect(client.saveSettings).toHaveBeenLastCalledWith(expect.objectContaining({ deepseek: expect.objectContaining({ defaultAutoAnalyze: true }) }));
    await act(async () => (container.querySelector('button[title="输入"]') as HTMLButtonElement).click());
    vi.mocked(client.startRecording).mockResolvedValue(result);
    vi.mocked(client.recordingStatus).mockResolvedValue(result);
    vi.mocked(client.stopRecording).mockResolvedValue({ ...result, status: "done", rawText: "输入到记事本" });
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    expect(client.showInputPanel).not.toHaveBeenCalled();
    expect(client.pasteDictation).not.toHaveBeenCalled();
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 456 }));
    expect(client.pasteDictation).toHaveBeenCalledTimes(1);
    expect(client.pasteDictation).toHaveBeenCalledWith("输入到记事本", 123);
    expect(client.analyzeText).not.toHaveBeenCalled();
  });

  it("still inputs recognized text if history storage fails", async () => {
    vi.mocked(client.startRecording).mockResolvedValue(result);
    vi.mocked(client.recordingStatus).mockResolvedValue(result);
    vi.mocked(client.stopRecording).mockResolvedValue({ ...result, status: "done", rawText: "继续输入" });
    vi.mocked(client.saveHistoryEntry).mockRejectedValue(new Error("disk unavailable"));
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    expect(client.pasteDictation).toHaveBeenCalledWith("继续输入", 123);
    expect(container.textContent).toContain("历史保存失败");
  });

  it("keeps the transcript and exposes paste failures without retrying", async () => {
    vi.mocked(client.startRecording).mockResolvedValue(result);
    vi.mocked(client.recordingStatus).mockResolvedValue(result);
    vi.mocked(client.stopRecording).mockResolvedValue({ ...result, status: "done", rawText: "保留原文" });
    vi.mocked(client.pasteDictation).mockRejectedValue(new Error("输入窗口已切换"));
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    expect(container.querySelector("textarea")!.value).toBe("保留原文");
    expect(container.textContent).toContain("自动输入失败");
    expect(client.showInputPanel).toHaveBeenCalledTimes(1);
    expect(client.pasteDictation).toHaveBeenCalledTimes(1);
  });

  it("ignores repeated hotkeys while the microphone is starting", async () => {
    const start = deferred<TranscriptionResult>();
    vi.mocked(client.startRecording).mockReturnValue(start.promise);
    vi.mocked(client.recordingStatus).mockResolvedValue(result);
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    await act(async () => hotkeys.get("dictation-hotkey")!({ payload: 123 }));
    expect(client.startRecording).toHaveBeenCalledTimes(1);
    expect(client.stopRecording).not.toHaveBeenCalled();
    await act(async () => start.resolve(result));
  });
  it("prepares only the saved selection on startup", () => {
    expect(client.prepareModels).toHaveBeenCalled();
    expect(vi.mocked(client.prepareModels).mock.calls.every(([asr]) => asr.model === result.model)).toBe(true);
  });
  it("keeps settings usable while models are loading in the background", async () => {
    vi.mocked(client.prepareModels).mockResolvedValue({ selected: result.model,
      models: [{ model: result.model, status: "loading", elapsedSeconds: 2 }] });
    await act(async () => (container.querySelector('button[title="设置"]') as HTMLButtonElement).click());
    await act(async () => button("保存设置").click());
    expect(container.querySelector("fieldset")!.disabled).toBe(false);
    await act(async () => (container.querySelector('button[title="输入"]') as HTMLButtonElement).click());
    expect(container.textContent).toContain("后台加载中");
    expect(button("录音").disabled).toBe(true);
    expect(client.startRecording).not.toHaveBeenCalled();
  });
  it("saves each model choice without resetting the selected speech language", async () => {
    await act(async () => (container.querySelector('button[title="设置"]') as HTMLButtonElement).click());
    const language = [...container.querySelectorAll("select")].find((select) => [...select.options].some((option) => option.value === "zh"))!;
    await act(async () => {
      language.value = "zh";
      language.dispatchEvent(new Event("change", { bubbles: true }));
    });
    const select = container.querySelector<HTMLSelectElement>('select[aria-label="模型"]')!;
    expect(select.options.length).toBe(3);
    for (const option of [...select.options]) {
      await act(async () => {
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await act(async () => button("保存设置").click());
      expect(client.saveSettings).toHaveBeenLastCalledWith(expect.objectContaining({ asr: expect.objectContaining({ model: option.value, language: "zh" }) }));
    }
  });

  it("shows partial text, locks actions and ignores a late response after completion", async () => {
    vi.useFakeTimers();
    const start = deferred<TranscriptionResult>();
    const late = deferred<TranscriptionResult>();
    vi.mocked(client.startRecording).mockReturnValue(start.promise);
    vi.mocked(client.recordingStatus).mockResolvedValueOnce({ ...result, rawText: "实时内容" }).mockReturnValue(late.promise);
    vi.mocked(client.stopRecording).mockResolvedValue({ ...result, status: "done", rawText: "最终内容" });
    await act(async () => button("录音").click());
    expect(container.textContent).toContain("正在开启麦克风");
    expect(button("录音").disabled).toBe(true);
    await act(async () => start.resolve(result));
    expect(container.querySelector("textarea")!.value).toBe("实时内容");
    expect(container.querySelector("textarea")!.readOnly).toBe(true);
    expect(button("分析").disabled).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(201); });
    await act(async () => button("停止").click());
    expect(container.querySelector("textarea")!.value).toBe("最终内容");
    expect(client.saveHistoryEntry).toHaveBeenCalledTimes(1);
    expect(client.saveHistoryEntry).toHaveBeenCalledWith(expect.objectContaining({ asrModel: result.model }));
    await act(async () => late.resolve({ ...result, rawText: "迟到的旧内容" }));
    expect(container.querySelector("textarea")!.value).toBe("最终内容");
    expect(container.querySelector("textarea")!.readOnly).toBe(false);
  });

  it("does not save empty recognition or trigger analysis", async () => {
    vi.mocked(client.startRecording).mockResolvedValue(result);
    vi.mocked(client.recordingStatus).mockResolvedValue(result);
    vi.mocked(client.stopRecording).mockResolvedValue({ ...result, status: "done" });
    await act(async () => button("录音").click());
    await act(async () => button("停止").click());
    expect(container.textContent).toContain("没有识别到有效语音");
    expect(client.saveHistoryEntry).not.toHaveBeenCalled();
    expect(client.analyzeText).not.toHaveBeenCalled();
  });

  it("keeps the usable transcript when history storage fails", async () => {
    vi.mocked(client.startRecording).mockResolvedValue(result);
    vi.mocked(client.recordingStatus).mockResolvedValue(result);
    vi.mocked(client.stopRecording).mockResolvedValue({ ...result, status: "done", rawText: "保留识别结果" });
    vi.mocked(client.saveHistoryEntry).mockRejectedValue(new Error("disk unavailable"));
    await act(async () => button("录音").click());
    await act(async () => button("停止").click());
    expect(container.querySelector("textarea")!.value).toBe("保留识别结果");
    expect(container.textContent).toContain("历史保存失败");
    expect(container.querySelector("textarea")!.readOnly).toBe(false);
  });
});


it("saves editable terms and retains them when reopening settings", async () => {
  await act(async () => (container.querySelector('button[title="设置"]') as HTMLButtonElement).click());
  const terms = container.querySelector('textarea[aria-label="常用术语"]') as HTMLTextAreaElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(terms, "Vibe Coding\nHarness Engineering");
    terms.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => button("保存设置").click());
  expect(client.saveSettings).toHaveBeenLastCalledWith(expect.objectContaining({ asr: expect.objectContaining({ terms: "Vibe Coding\nHarness Engineering", englishPunctuation: true, arabicNumbers: true }) }));
  await act(async () => (container.querySelector('button[title="输入"]') as HTMLButtonElement).click());
  await act(async () => (container.querySelector('button[title="设置"]') as HTMLButtonElement).click());
  expect((container.querySelector('textarea[aria-label="常用术语"]') as HTMLTextAreaElement).value).toBe("Vibe Coding\nHarness Engineering");
});

it("saves microphone choice and preserves it when a refresh no longer finds the device", async () => {
  await act(async () => (container.querySelector('button[title="设置"]') as HTMLButtonElement).click());
  const microphone = container.querySelector<HTMLSelectElement>('select[aria-label="麦克风"]')!;
  expect(microphone.textContent).toContain("USB Microphone");
  await act(async () => {
    microphone.value = "usb-mic";
    microphone.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => button("保存设置").click());
  expect(client.saveSettings).toHaveBeenLastCalledWith(expect.objectContaining({ asr: expect.objectContaining({ inputDevice: "usb-mic" }) }));
  vi.mocked(client.inputDevices).mockResolvedValue([]);
  await act(async () => button("刷新设备").click());
  expect(microphone.value).toBe("usb-mic");
  expect(microphone.textContent).toContain("当前未找到");
  vi.mocked(client.inputDevices).mockRejectedValue(new Error("设备刷新失败"));
  await act(async () => button("刷新设备").click());
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("设备刷新失败");
});

it("shows a saved legacy microphone as its current endpoint without driver suffixes", async () => {
  await act(async () => (container.querySelector('button[title="设置"]') as HTMLButtonElement).click());
  const microphone = container.querySelector<HTMLSelectElement>('select[aria-label="麦克风"]')!;
  await act(async () => {
    microphone.value = "usb-mic";
    microphone.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () => button("保存设置").click());
  vi.mocked(client.inputDevices).mockResolvedValue([{ id: "wasapi-mic", name: "USB Microphone", hostApi: "Windows WASAPI", aliases: ["usb-mic", "wasapi-mic"] }]);
  await act(async () => button("刷新设备").click());
  expect(microphone.value).toBe("wasapi-mic");
  expect([...microphone.options].map((option) => option.textContent)).toEqual(["跟随系统默认麦克风", "USB Microphone"]);
});
