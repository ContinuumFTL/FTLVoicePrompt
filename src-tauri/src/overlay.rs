use serde::{Deserialize, Serialize};
use std::{sync::Mutex, time::Duration};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, WebviewUrl, WebviewWindowBuilder};

#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct OverlayState {
    pub status: String,
    pub session_id: Option<String>,
}

#[derive(Default)]
pub struct OverlayStore(pub Mutex<OverlayState>, Mutex<RenderHealth>);

#[derive(Default)]
struct RenderHealth {
    running: bool,
    stopping: bool,
    probe: u64,
    painted: bool,
    recoveries: u8,
}

// Rebuilding a WebView must run outside synchronous command handlers on Windows.
// Serialize updates so a new recording cannot race a previous window rebuild.
static UPDATE_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

fn should_show(state: &OverlayState) -> bool {
    matches!(state.status.as_str(), "preparing" | "recording")
}

pub fn shutdown(app: &AppHandle) {
    if let Some(store) = app.try_state::<OverlayStore>() {
        if let Ok(mut health) = store.1.lock() { health.stopping = true; }
        if let Ok(mut state) = store.0.lock() { *state = OverlayState::default(); }
    }
}

// A visible HWND can contain a blank or unresponsive WebView. Require a frame
// containing the actual capsule, rather than treating show() as render success.
#[tauri::command]
pub fn recording_overlay_painted(window: tauri::WebviewWindow, store: tauri::State<'_, OverlayStore>, probe_id: u64) -> Result<bool, String> {
    if window.label() != "recording-overlay" { return Err("绘制回执来源无效".into()); }
    let mut health = store.1.lock().map_err(|error| error.to_string())?;
    if health.running && health.probe == probe_id {
        health.painted = true;
        return Ok(true);
    }
    Ok(false)
}

pub fn create(app: &AppHandle) -> Result<(), String> {
    let window = WebviewWindowBuilder::new(app, "recording-overlay", WebviewUrl::App("index.html#recording-overlay".into()))
        .title("语音录音状态").inner_size(360.0, 88.0)
        .decorations(false).transparent(true).shadow(false).resizable(false)
        .minimizable(false).maximizable(false).closable(false)
        .always_on_top(true).skip_taskbar(true).focusable(false).focused(false).visible(false)
        .build().map_err(|error| error.to_string())?;
    window.set_ignore_cursor_events(true).map_err(|error| error.to_string())
}

#[tauri::command]
pub fn recording_overlay_state(store: tauri::State<'_, OverlayStore>) -> Result<OverlayState, String> {
    Ok(store.0.lock().map_err(|error| error.to_string())?.clone())
}

#[tauri::command]
pub async fn update_recording_overlay(app: AppHandle, store: tauri::State<'_, OverlayStore>, status: String, session_id: Option<String>) -> Result<(), String> {
    let _update = UPDATE_LOCK.lock().await;
    if store.1.lock().map_err(|error| error.to_string())?.stopping { return Ok(()); }
    let state = OverlayState { status, session_id };
    let was_visible = should_show(&*store.0.lock().map_err(|error| error.to_string())?);
    *store.0.lock().map_err(|error| error.to_string())? = state.clone();
    let visible = should_show(&state);
    if visible && !was_visible {
        store.1.lock().map_err(|error| error.to_string())?.recoveries = 0;
    }
    display(&app, &state)?;
    if visible {
        let mut health = store.1.lock().map_err(|error| error.to_string())?;
        if !health.running {
            health.running = true;
            let handle = app.clone();
            tauri::async_runtime::spawn(async move {
                if let Err(error) = watch_rendering(&handle).await {
                    crate::startup::mark("overlay_render_recovery_failed");
                    if let Ok(mut health) = handle.state::<OverlayStore>().1.lock() { health.running = false; }
                    let _ = handle.emit_to("main", "recording-overlay-error", format!("录音仍可继续，胶囊恢复失败：{error}"));
                }
            });
        }
    }
    Ok(())
}

fn display(app: &AppHandle, state: &OverlayState) -> Result<(), String> {
    let visible = should_show(state);
    if app.get_webview_window("recording-overlay").is_none() {
        if !visible { return Ok(()); }
        create(app)?;
    }
    let window = app.get_webview_window("recording-overlay").ok_or("录音状态窗口不可用")?;
    if visible {
        // Match the monitor containing the foreground input, including DPI and
        // the taskbar work area. Never activate the capsule.
        let monitors = app.available_monitors().map_err(|error| error.to_string())?;
        let point = crate::windowing::foreground_window_center();
        let monitor = monitors.iter().find(|monitor| point.is_some_and(|(x, y)| {
            let p = monitor.position(); let s = monitor.size();
            x >= p.x && y >= p.y && x < p.x + s.width as i32 && y < p.y + s.height as i32
        })).or(monitors.first());
        if let Some(monitor) = monitor {
            let area = monitor.work_area();
            let scale = monitor.scale_factor();
            let width = (360.0 * scale) as i32;
            let height = (88.0 * scale) as i32;
            window.set_position(PhysicalPosition::new(
                area.position.x + (area.size.width as i32 - width) / 2,
                area.position.y + area.size.height as i32 - height - (12.0 * scale) as i32,
            )).map_err(|error| error.to_string())?;
        }
    }
    app.emit_to("recording-overlay", "recording-overlay-state", state).map_err(|error| error.to_string())?;
    if visible {
        show_without_activation(&window)
    } else {
        window.hide().map_err(|error| error.to_string())
    }
}

fn show_without_activation(window: &tauri::WebviewWindow) -> Result<(), String> {
    // Update the framework's visibility cache before forcing the native state.
    window.show().map_err(|error| error.to_string())?;
    #[cfg(windows)]
    {
        // unminimize() uses SW_RESTORE, which can activate a window. Always use
        // the non-activating native restore, even if framework flags are stale.
        use windows::Win32::{Foundation::HWND, UI::WindowsAndMessaging::{
            ShowWindow, SetWindowPos, HWND_TOPMOST, SW_SHOWNOACTIVATE,
            SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE, SWP_SHOWWINDOW,
        }};
        let (send, receive) = std::sync::mpsc::channel();
        let restored = window.clone();
        window.run_on_main_thread(move || {
            let result = restored.hwnd().map_err(|error| error.to_string()).and_then(|handle| unsafe {
                let hwnd = HWND(handle.0);
                let _ = ShowWindow(hwnd, SW_SHOWNOACTIVATE);
                SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW).map_err(|error| error.to_string())
            });
            let _ = send.send(result);
        }).map_err(|error| error.to_string())?;
        receive.recv_timeout(Duration::from_secs(2)).map_err(|error| error.to_string())?
    }
    #[cfg(not(windows))]
    {
        window.set_always_on_top(true).map_err(|error| error.to_string())?;
        window.unminimize().map_err(|error| error.to_string())
    }
}

async fn watch_rendering(app: &AppHandle) -> Result<(), String> {
    loop {
        tokio::time::sleep(Duration::from_millis(500)).await;
        let (probe, session) = {
            let _update = UPDATE_LOCK.lock().await;
            let store = app.state::<OverlayStore>();
            let state = store.0.lock().map_err(|error| error.to_string())?.clone();
            if !should_show(&state) || store.1.lock().map_err(|error| error.to_string())?.stopping {
                store.1.lock().map_err(|error| error.to_string())?.running = false;
                return Ok(());
            }
            let probe = {
                let mut health = store.1.lock().map_err(|error| error.to_string())?;
                health.probe += 1;
                health.painted = false;
                health.probe
            };
            if let Some(window) = app.get_webview_window("recording-overlay") {
                // Two animation frames allow painting after a show/restore.
                // No audio or transcript data is included in this diagnostic.
                let script = format!(r#"requestAnimationFrame(() => requestAnimationFrame(() => {{
                    const capsule = document.querySelector('.recording-capsule');
                    if (!capsule || !document.querySelector('.capsule-wave i')) return;
                    const bounds = capsule.getBoundingClientRect();
                    const style = getComputedStyle(capsule);
                    if (bounds.width > 0 && bounds.height > 0 && bounds.right > 0 && bounds.bottom > 0
                        && bounds.left < innerWidth && bounds.top < innerHeight
                        && style.display !== 'none' && style.visibility === 'visible' && Number(style.opacity) > 0) {{
                        window.__TAURI_INTERNALS__.invoke('recording_overlay_painted', {{ probeId: {probe} }}).catch(() => {{}});
                    }}
                }}));"#);
                if window.eval(script).is_err() { crate::startup::mark("overlay_render_probe_send_failed"); }
            }
            (probe, state.session_id)
        };
        tokio::time::sleep(Duration::from_millis(1500)).await;
        let _update = UPDATE_LOCK.lock().await;
        let store = app.state::<OverlayStore>();
        let state = store.0.lock().map_err(|error| error.to_string())?.clone();
        if !should_show(&state) || state.session_id != session || store.1.lock().map_err(|error| error.to_string())?.stopping { continue; }
        {
            let mut health = store.1.lock().map_err(|error| error.to_string())?;
            if health.probe != probe || health.painted { continue; }
            if health.recoveries >= 3 { return Err("胶囊页面连续无绘制回应，请检查前端运行环境".into()); }
            health.recoveries += 1;
            // Discard delayed responses from the old page.
            health.probe += 1;
        }
        crate::startup::mark("overlay_render_unresponsive_rebuilding");
        if let Some(window) = app.get_webview_window("recording-overlay") {
            window.destroy().map_err(|error| error.to_string())?;
            for _ in 0..100 {
                if app.get_webview_window("recording-overlay").is_none() { break; }
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
            if app.get_webview_window("recording-overlay").is_some() { return Err("胶囊旧窗口未能释放".into()); }
        }
        display(app, &state)?;
    }
}
