import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";
import { Mic } from "lucide-react";
import { recordingStatus } from "./lib/tauriClient";
import "./recordingOverlay.css";

type OverlayState = { status: string; sessionId: string | null };
const silence = Array<number>(32).fill(0);

export function Waveform({ levels }: { levels: number[] }) {
  return <div className="capsule-wave" aria-label="麦克风实时音量">
    {Array.from({ length: 32 }, (_, index) => {
      const level = Number.isFinite(levels[index]) ? Math.max(0, Math.min(1, levels[index])) : 0;
      return <i key={index} style={{ height: `${3 + level * 29}px`, opacity: 0.3 + level * 0.7 }} />;
    })}
  </div>;
}

export default function RecordingOverlay() {
  const [state, setState] = useState<OverlayState>({ status: "idle", sessionId: null });
  const [levels, setLevels] = useState(silence);
  const [error, setError] = useState("");
  const [captureReady, setCaptureReady] = useState(false);
  const [finishingCapture, setFinishingCapture] = useState(false);
  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    void listen<OverlayState>("recording-overlay-state", ({ payload }) => { if (!disposed) setState(payload); })
      .then(async (unlisten) => {
        if (disposed) { unlisten(); return; }
        cleanup = unlisten;
        const current = await invoke<OverlayState>("recording_overlay_state");
        if (!disposed) setState(current);
      }).catch(() => setError("状态连接中断"));
    return () => { disposed = true; cleanup?.(); };
  }, []);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setLevels(silence);
    setError("");
    setCaptureReady(false);
    setFinishingCapture(false);
    if (!["recording", "transcribing"].includes(state.status) || !state.sessionId) return;
    const sessionId = state.sessionId;
    async function poll() {
      try {
        const snapshot = await recordingStatus(sessionId);
        if (!active) return;
        setLevels(snapshot.status === "recording" ? snapshot.audioLevels ?? silence : silence);
        setCaptureReady(snapshot.captureReady === true);
        setFinishingCapture(snapshot.status === "recording" && snapshot.stopRequested === true);
        setError(snapshot.error || snapshot.captureWarning || "");
      } catch { if (active) { setLevels(silence); setError("麦克风连接中断"); } }
      if (active) timer = setTimeout(poll, 80);
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [state.status, state.sessionId]);
  const hearing = levels.some((level) => level > 0.15);
  const label = error || (finishingCapture ? "补收尾音 · 1.5 秒后结束" : state.status === "transcribing" ? "正在识别" : state.status === "preparing" || !captureReady ? "正在开启麦克风" : hearing ? "正在聆听" : "可以说话 · 等待声音");
  return <div className="recording-capsule" role="status" aria-live="polite">
    <span className={`capsule-mic ${error ? "capsule-error" : ""}`}><Mic size={19} /></span>
    <div className="capsule-content"><span className="capsule-label">{label}</span><Waveform levels={levels} /></div>
    <span className="capsule-key">右 Alt<span>{state.status === "transcribing" || finishingCapture ? "收尾中" : "结束"}</span></span>
  </div>;
}
