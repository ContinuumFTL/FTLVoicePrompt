// Serialize incremental writes so a late partial cannot duplicate the final tail.
export class DictationStream {
  private sent = "";
  private queue: Promise<void> = Promise.resolve();
  constructor(private insert: (text: string) => Promise<void>) {}

  write(raw: string): Promise<void> {
    const next = raw.trimStart();
    this.queue = this.queue.then(async () => {
      if (next === this.sent || !next) return;
      if (!next.startsWith(this.sent)) throw new Error("识别文本发生修订，已暂停自动输入；完整原文保留在面板中。");
      await this.insert(next.slice(this.sent.length));
      this.sent = next;
    });
    return this.queue;
  }
}
