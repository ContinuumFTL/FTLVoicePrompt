import { describe, expect, it, vi } from "vitest";
import { DictationStream } from "./dictationStream";

describe("external streaming dictation", () => {
  it("serializes partials and inserts only the final unseen tail", async () => {
    let release!: () => void;
    const first = new Promise<void>((resolve) => { release = resolve; });
    const insert = vi.fn().mockReturnValueOnce(first).mockResolvedValue(undefined);
    const stream = new DictationStream(insert);
    const a = stream.write("你好");
    const b = stream.write("你好世界");
    const c = stream.write("你好世界！");
    await Promise.resolve();
    expect(insert.mock.calls).toEqual([["你好"]]);
    release();
    await Promise.all([a, b, c]);
    await stream.write("你好世界！");
    expect(insert.mock.calls).toEqual([["你好"], ["世界"], ["！"]]);
  });

  it("never resumes or duplicates uncertain writes after a target failure", async () => {
    const insert = vi.fn().mockRejectedValue(new Error("window changed"));
    const stream = new DictationStream(insert);
    await expect(stream.write("你好")).rejects.toThrow("window changed");
    await expect(stream.write("你好世界")).rejects.toThrow("window changed");
    expect(insert).toHaveBeenCalledTimes(1);
  });

  it("refuses to erase existing input if a recognizer revises committed text", async () => {
    const insert = vi.fn().mockResolvedValue(undefined);
    const stream = new DictationStream(insert);
    await stream.write("原文");
    await expect(stream.write("改写")).rejects.toThrow("修订");
    expect(insert).toHaveBeenCalledTimes(1);
  });
});


it("preserves punctuation spaces including a space-only final tail", async () => {
  const insert = vi.fn().mockResolvedValue(undefined);
  const stream = new DictationStream(insert);
  await stream.write("你好?");
  await stream.write("你好? ");
  await stream.write("你好? 下一句. ");
  expect(insert.mock.calls).toEqual([["你好?"], [" "], ["下一句. "]]);
});
