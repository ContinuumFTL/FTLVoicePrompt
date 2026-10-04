export type PanelView = "compose" | "history" | "settings";
export type RecordingStatus = "idle" | "preparing" | "recording" | "transcribing" | "error";
export type AnalysisStatus = "idle" | "pending" | "running" | "done" | "error";
export type HotkeyRecordingAction = "start" | "stop" | "ignore";

export interface PanelState {
  view: PanelView;
  rawText: string;
  durationMs: number;
  asrModel: string;
  sessionId?: string;
  recording: {
    status: RecordingStatus;
    error?: string;
  };
  analysis: {
    status: AnalysisStatus;
    text: string;
    error?: string;
  };
}

export type PanelAction =
  | { type: "hotkeyOpened" }
  | { type: "recordingPreparing" }
  | { type: "recordingStarted"; sessionId?: string }
  | { type: "transcriptionPartial"; sessionId: string; text: string }
  | { type: "recordingStopped" }
  | { type: "transcriptionCompleted"; rawText: string; durationMs: number; asrModel: string; autoAnalyze: boolean }
  | { type: "recordingFailed"; error: string }
  | { type: "analysisStarted" }
  | { type: "analysisCompleted"; text: string }
  | { type: "analysisFailed"; error: string }
  | { type: "rawTextEdited"; text: string }
  | { type: "analysisTextEdited"; text: string }
  | { type: "viewChanged"; view: PanelView };

export function createInitialPanelState(): PanelState {
  return {
    view: "compose",
    rawText: "",
    durationMs: 0,
    asrModel: "",
    recording: { status: "idle" },
    analysis: { status: "idle", text: "" },
  };
}

export function hotkeyRecordingAction(status: RecordingStatus): HotkeyRecordingAction {
  if (status === "recording") return "stop";
  if (status === "transcribing" || status === "preparing") return "ignore";
  return "start";
}

export function panelReducer(state: PanelState, action: PanelAction): PanelState {
  switch (action.type) {
    case "recordingPreparing":
      return { ...createInitialPanelState(), recording: { status: "preparing" } };
    case "transcriptionPartial":
      if (state.recording.status !== "recording" || action.sessionId !== state.sessionId) return state;
      return { ...state, rawText: action.text };
    case "hotkeyOpened":
    case "recordingStarted":
      return {
        ...state,
        view: "compose",
        rawText: "",
        durationMs: 0,
        asrModel: "",
        sessionId: action.type === "recordingStarted" ? action.sessionId : undefined,
        recording: { status: "recording" },
        analysis: { status: "idle", text: "" },
      };
    case "recordingStopped":
      return {
        ...state,
        recording: { status: "transcribing" },
      };
    case "transcriptionCompleted":
      return {
        ...state,
        rawText: action.rawText,
        durationMs: action.durationMs,
        asrModel: action.asrModel,
        recording: { status: "idle" },
        analysis: {
          status: action.autoAnalyze && action.rawText.trim() ? "pending" : "idle",
          text: "",
        },
      };
    case "recordingFailed":
      return {
        ...state,
        rawText: "",
        sessionId: undefined,
        recording: { status: "error", error: action.error },
      };
    case "analysisStarted":
      return {
        ...state,
        analysis: { ...state.analysis, status: "running", error: undefined },
      };
    case "analysisCompleted":
      return {
        ...state,
        analysis: { status: "done", text: action.text },
      };
    case "analysisFailed":
      return {
        ...state,
        analysis: { ...state.analysis, status: "error", error: action.error },
      };
    case "rawTextEdited":
      return {
        ...state,
        rawText: action.text,
      };
    case "analysisTextEdited":
      return {
        ...state,
        analysis: { ...state.analysis, text: action.text },
      };
    case "viewChanged":
      return {
        ...state,
        view: action.view,
      };
    default:
      return state;
  }
}
