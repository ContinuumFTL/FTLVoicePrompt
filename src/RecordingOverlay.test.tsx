import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import { Waveform } from "./RecordingOverlay";
import RecordingOverlay from "./RecordingOverlay";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { recordingStatus } from "./lib/tauriClient";

vi.mock("@tauri-apps/api/event", () => ({ listen: async () => () => undefined }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: async () => ({ status: "recording", sessionId: "one" }) }));
vi.mock("./lib/tauriClient", () => ({ recordingStatus: vi.fn() }));

it("uses measured volume for bar heights and rests at silence without a fake animation", () => {
  const silence = renderToStaticMarkup(<Waveform levels={Array(32).fill(0)} />);
  const speech = renderToStaticMarkup(<Waveform levels={Array(32).fill(1)} />);
  expect(silence.match(/height:3px/g)).toHaveLength(32);
  expect(speech.match(/height:32px/g)).toHaveLength(32);
  expect(silence).not.toContain("animation");
});

it("announces readiness only after capture confirmation and surfaces audio warnings", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  const container = document.createElement("div");
  const root = createRoot(container);
  const snapshot = { sessionId: "one", status: "recording" as const, rawText: "", model: "test", language: "zh", durationMs: 0, audioLevels: Array(32).fill(0) };
  vi.mocked(recordingStatus).mockResolvedValue({ ...snapshot, captureReady: false });
  try {
    await act(async () => root.render(<RecordingOverlay />));
    expect(container.textContent).toContain("正在开启麦克风");
    expect(container.textContent).not.toContain("可以说话");
    vi.mocked(recordingStatus).mockResolvedValue({ ...snapshot, captureReady: true });
    await act(async () => { await vi.advanceTimersByTimeAsync(80); });
    expect(container.textContent).toContain("可以说话");
    vi.mocked(recordingStatus).mockResolvedValue({ ...snapshot, captureReady: true, stopRequested: true, audioLevels: Array(32).fill(1) });
    await act(async () => { await vi.advanceTimersByTimeAsync(80); });
    expect(container.textContent).toContain("补收尾音");
    expect(container.querySelector(".capsule-wave i")?.getAttribute("style")).toContain("32px");
    vi.mocked(recordingStatus).mockResolvedValue({ ...snapshot, captureReady: true, captureWarning: "音频输入溢出 1 次" });
    await act(async () => { await vi.advanceTimersByTimeAsync(80); });
    expect(container.textContent).toContain("音频输入溢出 1 次");
  } finally {
    await act(async () => root.unmount());
    vi.useRealTimers();
  }
});
