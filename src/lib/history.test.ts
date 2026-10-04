import { describe, expect, it } from "vitest";
import { createHistoryEntry, trimHistory } from "./history";

describe("history helpers", () => {
  it("stores text metadata without audio payloads", () => {
    const entry = createHistoryEntry({
      rawText: "这个 React component 里面的 useMemo 好像没必要。",
      analyzedText: "请检查 React component 中 useMemo 是否必要。",
      preset: "requirements",
      asrModel: "Qwen/Qwen3-ASR-1.7B",
      durationMs: 1200,
    });

    expect(entry.rawText).toContain("useMemo");
    expect(entry.audioPath).toBeUndefined();
    expect(entry.createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it("keeps newest entries when applying the history limit", () => {
    const entries = [
      createHistoryEntry({ rawText: "old", analyzedText: "", preset: "cleanup", asrModel: "Qwen/Qwen3-ASR-1.7B", durationMs: 1, createdAt: "2026-01-01T00:00:00.000Z" }),
      createHistoryEntry({ rawText: "new", analyzedText: "", preset: "cleanup", asrModel: "Qwen/Qwen3-ASR-1.7B", durationMs: 1, createdAt: "2026-01-02T00:00:00.000Z" }),
    ];

    expect(trimHistory(entries, 1).map((entry) => entry.rawText)).toEqual(["new"]);
  });
});
