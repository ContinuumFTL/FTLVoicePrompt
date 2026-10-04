//! Native WebView startup regression: the real UI must paint while ASR is slow.
//! Build the frontend, then run with --features tauri/custom-protocol.
//! Uses disposable settings; never starts Python, records audio, or registers hotkeys.
use ftl_voice_prompt_lib::{overlay::{self, OverlayStore}, settings::AppSettings};
use std::{sync::{OnceLock, atomic::{AtomicBool, Ordering}}, time::{Duration, Instant}};
use tauri::Manager;

static START: OnceLock<Instant> = OnceLock::new();
static PREPARING: AtomicBool = AtomicBool::new(false);
static PASSED: AtomicBool = AtomicBool::new(false);

#[tauri::command]
fn load_settings() -> AppSettings { AppSettings::default() }
#[tauri::command]
fn load_history() -> Vec<serde_json::Value> { vec![] }
#[tauri::command]
async fn prepare_models() -> serde_json::Value {
    PREPARING.store(true, Ordering::Relaxed);
    tokio::time::sleep(Duration::from_secs(180)).await;
    serde_json::json!({"selected":"Qwen/Qwen3-ASR-1.7B", "models":[]})
}
#[tauri::command]
fn frontend_ready() {
    println!("frontend_committed {}ms", START.get().unwrap().elapsed().as_millis());
}
#[tauri::command]
fn frontend_painted(window: tauri::WebviewWindow) {
    window.eval(r#"
        requestAnimationFrame(() => requestAnimationFrame(() => {
            const shell = document.querySelector('.shell');
            const progress = document.querySelector('progress[aria-label="正在准备语音引擎"]');
            const record = document.querySelector('.toolbar button');
            const painted = !!shell && shell.getBoundingClientRect().width > 0 &&
                getComputedStyle(shell).visibility === 'visible' && !!progress && record?.disabled;
            const fcp = performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? null;
            window.__TAURI_INTERNALS__.invoke('startup_check', { painted: !!painted, fcp });
        }));
    "#).unwrap();
}
#[tauri::command]
fn startup_check(app: tauri::AppHandle, painted: bool, fcp: Option<f64>) {
    let visible = app.get_webview_window("main").unwrap().is_visible().unwrap();
    let passed = painted && visible && PREPARING.load(Ordering::Relaxed)
        && app.get_webview_window("recording-overlay").is_none();
    println!("startup_check passed={passed} elapsed={}ms fcp={fcp:?}ms visible={visible} asr_pending={}",
        START.get().unwrap().elapsed().as_millis(), PREPARING.load(Ordering::Relaxed));
    PASSED.store(passed, Ordering::Relaxed);
    if !passed || !std::env::args().any(|arg| arg == "--hold") {
        app.exit(if passed { 0 } else { 1 });
    }
}
fn main() {
    START.set(Instant::now()).unwrap();
    let mut context = tauri::generate_context!();
    context.config_mut().identifier = "com.ftlvoice.prompt.startup-smoke".into();
    context.config_mut().app.windows[0].title = "FTL Voice Prompt · 启动验证".into();
    tauri::Builder::default()
        .manage(OverlayStore::default())
        .invoke_handler(tauri::generate_handler![load_settings, load_history, prepare_models,
            frontend_ready, frontend_painted, startup_check, overlay::update_recording_overlay])
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let deadline = if std::env::args().any(|arg| arg == "--hold") { 120 } else { 20 };
                tokio::time::sleep(Duration::from_secs(deadline)).await;
                let passed = PASSED.load(Ordering::Relaxed);
                if !passed { eprintln!("FAIL: startup did not paint before the deadline"); }
                handle.exit(if passed { 0 } else { 1 });
            });
            Ok(())
        })
        .run(context).expect("startup test failed");
    if !PASSED.load(Ordering::Relaxed) { std::process::exit(1); }
}
