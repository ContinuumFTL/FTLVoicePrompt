import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
import { invoke } from "@tauri-apps/api/core";
import RecordingOverlay from "./RecordingOverlay";

const isOverlay = window.location.hash === "#recording-overlay";
if (isOverlay) document.body.classList.add("recording-overlay-page");

function DesktopApp() {
  React.useEffect(() => {
    // React has committed the complete interface. Do not wait for models or
    // requestAnimationFrame, which can be throttled while the window is hidden.
    if ("__TAURI_INTERNALS__" in window) {
      void invoke("frontend_ready").catch(console.error);
      // Two frames give the visible window a paint opportunity. This signal is
      // diagnostic only: neither opening the window nor loading models waits on it.
      let second = 0;
      const first = requestAnimationFrame(() => {
        second = requestAnimationFrame(() => { void invoke("frontend_painted").catch(console.error); });
      });
      return () => { cancelAnimationFrame(first); cancelAnimationFrame(second); };
    }
  }, []);
  return <App />;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {isOverlay ? <RecordingOverlay /> : <DesktopApp />}
  </React.StrictMode>,
);
