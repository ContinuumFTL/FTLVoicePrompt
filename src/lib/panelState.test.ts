import { describe, expect, it } from "vitest";
import { createInitialPanelState, hotkeyRecordingAction, panelReducer } from "./panelState";

describe("panel state", () => {
  it("starts recording when the hotkey opens the panel", () => {
    const state = panelReducer(createInitialPanelState(), { type: "hotkeyOpened" });

    expect(state.view).toBe("compose");
    expect(state.recording.status).toBe("recording");
    expect(state.rawText).toBe("");
  });

  it("puts transcription on the left and waits for manual analysis by default", () => {
    const recording = panelReducer(createInitialPanelState(), { type: "hotkeyOpened" });
    const state = panelReducer(recording, {
      type: "transcriptionCompleted",
      rawText: "帮我改一下这个页面的 resource list",
      durationMs: 2500,
      asrModel: "Qwen/Qwen3-ASR-1.7B",
      autoAnalyze: false,
    });

    expect(state.rawText).toContain("resource list");
    expect(state.analysis.status).toBe("idle");
    expect(state.analysis.text).toBe("");
  });

  it("queues analysis automatically when enabled in settings", () => {
    const state = panelReducer(createInitialPanelState(), {
      type: "transcriptionCompleted",
      rawText: "整理成 prompt",
      durationMs: 900,
      asrModel: "Qwen/Qwen3-ASR-1.7B",
      autoAnalyze: true,
    });

    expect(state.analysis.status).toBe("pending");
  });

  it("maps hotkey presses to legal recorder actions", () => {
    expect(hotkeyRecordingAction("idle")).toBe("start");
    expect(hotkeyRecordingAction("error")).toBe("start");
    expect(hotkeyRecordingAction("recording")).toBe("stop");
    expect(hotkeyRecordingAction("transcribing")).toBe("ignore");
    expect(hotkeyRecordingAction("preparing")).toBe("ignore");
  });

  it("ignores late streaming text after stop and from a previous recording", () => {
    const recording = panelReducer(createInitialPanelState(), { type: "recordingStarted", sessionId: "new" });
    const partial = panelReducer(recording, { type: "transcriptionPartial", sessionId: "new", text: "实时文字" });
    expect(partial.rawText).toBe("实时文字");
    expect(panelReducer(partial, { type: "transcriptionPartial", sessionId: "old", text: "旧文字" })).toBe(partial);
    const stopped = panelReducer(partial, { type: "recordingStopped" });
    expect(panelReducer(stopped, { type: "transcriptionPartial", sessionId: "new", text: "迟到文字" })).toBe(stopped);
  });

  it("does not analyze empty audio and discards failed partial text", () => {
    const state = panelReducer(createInitialPanelState(), { type: "transcriptionCompleted", rawText: "", durationMs: 10, asrModel: "paraformer-zh-streaming", autoAnalyze: true });
    expect(state.analysis.status).toBe("idle");
    const failed = panelReducer({ ...state, rawText: "半句" }, { type: "recordingFailed", error: "连接断开" });
    expect(failed.rawText).toBe("");
  });
});
