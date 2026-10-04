//! Interactive smoke test: displays only a disposable capsule with synthetic
//! meter samples, verifies frontend polling and focus preservation, then exits.
//! pnpm build
//! cargo run --release --features tauri/custom-protocol --manifest-path src-tauri/Cargo.toml --example overlay_smoke
use ftl_voice_prompt_lib::{overlay::{self, OverlayStore}, windowing};
use std::{sync::atomic::{AtomicBool, AtomicUsize, Ordering}, time::Duration};
use tauri::Manager;

static POLLS: AtomicUsize = AtomicUsize::new(0);
static PASSED: AtomicBool = AtomicBool::new(false);
static READY: AtomicBool = AtomicBool::new(false);
static PAINTS: AtomicUsize = AtomicUsize::new(0);

#[tauri::command]
fn recording_overlay_painted(window: tauri::WebviewWindow, store: tauri::State<'_, OverlayStore>, probe_id: u64) -> Result<bool, String> {
    let accepted = overlay::recording_overlay_painted(window, store, probe_id)?;
    if accepted { PAINTS.fetch_add(1, Ordering::Relaxed); }
    Ok(accepted)
}

#[tauri::command]
fn recording_status(session_id: String) -> serde_json::Value {
    let count = POLLS.fetch_add(1, Ordering::Relaxed);
    let levels: Vec<f32> = (0..32).map(|index| {
        if count > 12 { 0.0 } else { ((index as f32 + count as f32) * 0.7).sin().abs() * 0.8 }
    }).collect();
    serde_json::json!({"sessionId": session_id, "status": "recording", "rawText": "",
        "audioLevels": levels, "captureReady": true, "durationMs": 0, "model": "fixture", "language": "auto"})
}

fn main() {
    let mut context = tauri::generate_context!();
    context.config_mut().app.windows.clear();
    let previous = windowing::foreground_window_handle();
    if previous.is_none() {
        eprintln!("FAIL: no foreground window available for the focus check");
        std::process::exit(1);
    }
    tauri::Builder::default()
        .manage(OverlayStore::default())
        .invoke_handler(tauri::generate_handler![overlay::recording_overlay_state, recording_overlay_painted, recording_status])
        .setup(move |app| {
            overlay::create(app.handle())?;
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while !READY.load(Ordering::Relaxed) {
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
                let outcome: Result<(), String> = async {
                    for (status, milliseconds) in [("preparing", 1000), ("recording", 2500), ("transcribing", 500), ("idle", 200)] {
                        println!("CHECK: state {status}");
                        overlay::update_recording_overlay(handle.clone(), handle.state(), status.into(), Some("fixture".into())).await?;
                        tokio::time::sleep(Duration::from_millis(milliseconds)).await;
                        let window = handle.get_webview_window("recording-overlay").ok_or("capsule missing")?;
                        if window.is_visible().map_err(|e| e.to_string())? != matches!(status, "preparing" | "recording") {
                            return Err(format!("incorrect visibility for {status}"));
                        }
                        if windowing::foreground_window_handle() != previous {
                            return Err(format!("foreground changed during {status}"));
                        }
                    }
                    if POLLS.load(Ordering::Relaxed) < 10 { return Err("capsule frontend did not poll microphone levels".into()); }
                    for damage in ["hidden", "minimized", "offscreen", "destroyed"] {
                        println!("CHECK: recovery after {damage}");
                        overlay::update_recording_overlay(handle.clone(), handle.state(), "recording".into(), Some("fixture".into())).await?;
                        let window = handle.get_webview_window("recording-overlay").ok_or("capsule missing")?;
                        match damage {
                            "hidden" => window.hide(),
                            "minimized" => window.minimize(),
                            "offscreen" => window.set_position(tauri::PhysicalPosition::new(-32000, -32000)),
                            _ => window.destroy(),
                        }.map_err(|e| e.to_string())?;
                        tokio::time::sleep(Duration::from_millis(200)).await;
                        match damage {
                            "hidden" if window.is_visible().map_err(|e| e.to_string())? => return Err("hide fixture failed".into()),
                            "minimized" if !window.is_minimized().map_err(|e| e.to_string())? => return Err("minimize fixture failed".into()),
                            "destroyed" if handle.get_webview_window("recording-overlay").is_some() => return Err("destroy fixture failed".into()),
                            _ => {}
                        }
                        // An idle update must not recreate a missing window. The next
                        // recording must recover it, including the frontend subscription.
                        overlay::update_recording_overlay(handle.clone(), handle.state(), "idle".into(), None).await?;
                        if damage == "destroyed" && handle.get_webview_window("recording-overlay").is_some() {
                            return Err("idle recreated the capsule".into());
                        }
                        let polls_before = POLLS.load(Ordering::Relaxed);
                        overlay::update_recording_overlay(handle.clone(), handle.state(), "recording".into(), Some("fixture".into())).await?;
                        tokio::time::sleep(Duration::from_millis(1500)).await;
                        let restored = handle.get_webview_window("recording-overlay").ok_or("capsule not recreated")?;
                        if !restored.is_visible().map_err(|e| e.to_string())? || restored.is_minimized().map_err(|e| e.to_string())? {
                            return Err(format!("capsule not restored after {damage}"));
                        }
                        let position = restored.outer_position().map_err(|e| e.to_string())?;
                        let on_screen = handle.available_monitors().map_err(|e| e.to_string())?.iter().any(|monitor| {
                            let area = monitor.work_area();
                            position.x >= area.position.x && position.y >= area.position.y
                                && position.x < area.position.x + area.size.width as i32
                                && position.y < area.position.y + area.size.height as i32
                        });
                        if !on_screen { return Err(format!("capsule offscreen after {damage}")); }
                        if POLLS.load(Ordering::Relaxed) <= polls_before + 2 { return Err(format!("frontend not polling after {damage}")); }
                        if windowing::foreground_window_handle() != previous { return Err(format!("foreground changed after {damage}: before={previous:?}, after={:?}", windowing::foreground_window_handle())); }
                    }
                    // Reproduce a visible but empty WebView. This does not send
                    // another recording-state update: recovery must work within
                    // the same recording, without touching the microphone.
                    for damage in ["blank-document", "missing-capsule"] {
                        println!("CHECK: rendered content recovery after {damage}");
                        let recovery_started = std::time::Instant::now();
                        let window = handle.get_webview_window("recording-overlay").ok_or("capsule missing")?;
                        if damage == "blank-document" {
                            window.navigate("about:blank".parse().unwrap()).map_err(|e| e.to_string())?;
                        } else {
                            window.eval("document.getElementById('root').replaceChildren();").map_err(|e| e.to_string())?;
                        }
                        tokio::time::sleep(Duration::from_millis(300)).await;
                        if !window.is_visible().map_err(|e| e.to_string())? { return Err("blank fixture must remain visible".into()); }
                        let paints_before = PAINTS.load(Ordering::Relaxed);
                        let polls_before = POLLS.load(Ordering::Relaxed);
                        let deadline = std::time::Instant::now() + Duration::from_secs(10);
                        loop {
                            if PAINTS.load(Ordering::Relaxed) > paints_before && POLLS.load(Ordering::Relaxed) > polls_before + 2 { break; }
                            if std::time::Instant::now() >= deadline { return Err(format!("no rendered capsule after {damage}")); }
                            tokio::time::sleep(Duration::from_millis(100)).await;
                        }
                        if windowing::foreground_window_handle() != previous { return Err(format!("foreground changed after {damage}")); }
                        let current = handle.state::<OverlayStore>().0.lock().unwrap().clone();
                        if current.status != "recording" || current.session_id.as_deref() != Some("fixture") {
                            return Err("recovery changed the recording session".into());
                        }
                        println!("RESTORED: {damage} in {}ms", recovery_started.elapsed().as_millis());
                    }
                    // Stopping while a render probe is pending must not resurrect
                    // the capsule after recording has ended.
                    handle.get_webview_window("recording-overlay").unwrap().navigate("about:blank".parse().unwrap()).map_err(|e| e.to_string())?;
                    overlay::update_recording_overlay(handle.clone(), handle.state(), "idle".into(), None).await?;
                    tokio::time::sleep(Duration::from_secs(3)).await;
                    if handle.get_webview_window("recording-overlay").is_some_and(|window| window.is_visible().unwrap_or(true)) {
                        return Err("render recovery reopened an idle capsule".into());
                    }
                    overlay::shutdown(&handle);
                    overlay::update_recording_overlay(handle.clone(), handle.state(), "recording".into(), Some("late".into())).await?;
                    if handle.get_webview_window("recording-overlay").is_some_and(|window| window.is_visible().unwrap_or(true)) {
                        return Err("late update reopened the capsule during shutdown".into());
                    }
                    Ok(())
                }.await;
                match outcome {
                    Ok(()) => {
                        PASSED.store(true, Ordering::Relaxed);
                        println!("PASS: window and blank-WebView recovery; verified capsule frames and audio polling; same recording session; idle cleanup; foreground preserved");
                        handle.exit(0);
                    }
                    Err(error) => { eprintln!("FAIL: {error}"); handle.exit(1); }
                }
            });
            Ok(())
        })
        .build(context).expect("overlay smoke failed to initialize")
        .run(|_, event| {
            if matches!(event, tauri::RunEvent::Ready) { READY.store(true, Ordering::Relaxed); }
            // The destroyed-window case temporarily has no windows. Only the
            // test's explicit PASS/FAIL exit may end this process.
            if let tauri::RunEvent::ExitRequested { code: None, api, .. } = event {
                api.prevent_exit();
            }
        });
    if !PASSED.load(Ordering::Relaxed) { std::process::exit(1); }
}
