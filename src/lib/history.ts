import type { HistoryEntry, SaveHistoryInput } from "../types";

export function createHistoryEntry(input: SaveHistoryInput): HistoryEntry {
  return {
    id: input.id ?? createId(),
    createdAt: input.createdAt ?? new Date().toISOString(),
    rawText: input.rawText,
    analyzedText: input.analyzedText || undefined,
    preset: input.preset,
    asrModel: input.asrModel,
    durationMs: input.durationMs,
  };
}

export function trimHistory(entries: HistoryEntry[], limit: number): HistoryEntry[] {
  return [...entries]
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    .slice(0, Math.max(limit, 0));
}

function createId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
