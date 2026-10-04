import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import config from "../src-tauri/tauri.conf.json";
import App from "./App";

describe("window chrome", () => {
  it("uses native window controls without a duplicate frontend title bar", () => {
    const markup = renderToStaticMarkup(<App />);

    expect(markup).not.toContain("data-tauri-drag-region");
    expect(config.app.windows[0]).toMatchObject({
      decorations: true,
      resizable: true,
      alwaysOnTop: false,
      skipTaskbar: false,
      visible: true,
    });
  });
  it("renders the editor and loading progress before the model is ready", () => {
    const markup = renderToStaticMarkup(<App />);
    expect(markup).toContain('aria-label="正在准备语音引擎"');
    expect(markup).toContain("<textarea");
    expect(markup).toContain("正在后台准备语音引擎");
  });
});
