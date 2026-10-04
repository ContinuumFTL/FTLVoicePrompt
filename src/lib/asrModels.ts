export const ASR_MODELS = [
  { id: "Qwen/Qwen3-ASR-1.7B", label: "Qwen3-ASR 1.7B · 停止后识别" },
  { id: "iic/SenseVoiceSmall", label: "SenseVoice Small · 停止后识别" },
  { id: "paraformer-zh-streaming", label: "Paraformer 中文 · 边说边出字" },
] as const;

export function modelLabel(id: string): string {
  return ASR_MODELS.find((model) => model.id === id)?.label ?? id;
}
