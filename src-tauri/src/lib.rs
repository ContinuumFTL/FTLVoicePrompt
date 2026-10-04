pub mod deepseek;
pub mod history;
pub mod hotkey;
pub mod overlay;
pub mod paste;
pub mod settings;
pub mod sidecar;
#[cfg(windows)]
mod sidecar_job;
pub mod windowing;
pub mod startup;

use directories::ProjectDirs;
use reqwest::Client;
use std::{path::PathBuf, sync::Mutex};
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

use deepseek::{analyze_with_deepseek, AnalysisPreset};
use history::{HistoryEntry, HistoryEntryDraft, HistoryStore};
use paste::{copy_text_to_clipboard, paste_text_to_window, PastePlan};
use settings::{AppSettings, AsrSettings, SettingsStore};
use sidecar::{SidecarManager, TranscriptionResponse};

pub struct AppState {
    settings: SettingsStore,
    history: HistoryStore,
    sidecar: SidecarManager,
    http: Client,
    target_hwnd: Mutex<Option<isize>>,
}

#[tauri::command]
fn frontend_ready(window: tauri::WebviewWindow) -> Result<(), String> {
    startup::mark("frontend_committed");
    window.show().map_err(|err| err.to_string())
}

#[tauri::command]
fn frontend_painted() {
    startup::mark("frontend_paint_opportunity");
}

#[tauri::command]
async fn show_input_panel(app: AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    show_input_panel_impl(&app, &state).await
}

async fn show_input_panel_impl(app: &AppHandle, state: &AppState) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("main") {
        // Capture the paste destination before activating our own window.
        if !window.is_focused().unwrap_or(true) {
            *state.target_hwnd.lock().map_err(|err| err.to_string())? =
                windowing::foreground_window_handle();
        }
        window.unminimize().map_err(|err| err.to_string())?;
        window.show().map_err(|err| err.to_string())?;
        window.set_focus().map_err(|err| err.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn prepare_models(state: State<'_, AppState>, settings: AsrSettings, retry: bool) -> Result<serde_json::Value, String> {
    let result = state.sidecar.prepare_models(&settings, retry).await;
    if let Ok(value) = &result {
        if value["models"].as_array().is_some_and(|models| !models.is_empty() && models.iter().all(|model| model["status"] == "ready")) {
            startup::models_ready();
        }
    }
    result
}

#[tauri::command]
async fn start_recording(state: State<'_, AppState>) -> Result<TranscriptionResponse, String> {
    let settings = state.settings.load()?;
    state.sidecar.start_recording(&settings.asr).await
}

#[tauri::command]
async fn input_devices(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    state.sidecar.input_devices(&state.settings.load()?.asr).await
}

#[tauri::command]
async fn stop_recording(state: State<'_, AppState>, session_id: String) -> Result<TranscriptionResponse, String> {
    state.sidecar.stop_recording(&session_id).await
}

#[tauri::command]
async fn recording_status(state: State<'_, AppState>, session_id: String) -> Result<TranscriptionResponse, String> {
    state.sidecar.recording_status(&session_id).await
}

#[tauri::command]
async fn abort_recording(state: State<'_, AppState>, session_id: String) -> Result<(), String> {
    state.sidecar.abort_recording(&session_id).await
}

#[tauri::command]
async fn analyze_text(
    state: State<'_, AppState>,
    text: String,
    preset: AnalysisPreset,
) -> Result<String, String> {
    let settings = state.settings.load()?;
    let api_key = load_deepseek_key()?;
    analyze_with_deepseek(
        &state.http,
        &settings.deepseek,
        &api_key,
        preset,
        text.trim(),
    )
    .await
}

#[tauri::command]
fn copy_text(text: String) -> Result<(), String> {
    copy_text_to_clipboard(&text)
}

#[tauri::command]
fn paste_text_to_target(state: State<'_, AppState>, text: String) -> Result<(), String> {
    let settings = state.settings.load()?;
    let target = *state.target_hwnd.lock().map_err(|err| err.to_string())?;
    paste_text_to_window(target, PastePlan::new(text, settings.paste.restore_clipboard))
}

#[tauri::command]
async fn paste_dictation(state: State<'_, AppState>, text: String, target: isize) -> Result<(), String> {
    if text.is_empty() { return Ok(()); }
    let settings = state.settings.load()?;
    tauri::async_runtime::spawn_blocking(move || {
        // Stop now fires on key-down; allow the user to release the hotkey
        // before injecting text without blocking the UI or waveform.
        for _ in 0..100 {
            if windowing::foreground_window_handle() != Some(target) || !windowing::modifiers_pressed() { break; }
            std::thread::sleep(std::time::Duration::from_millis(20));
        }
        paste::paste_dictation_to_current_window(target, PastePlan::new(text, settings.paste.restore_clipboard))
    }).await.map_err(|error| error.to_string())?
}

#[tauri::command]
fn load_history(state: State<'_, AppState>) -> Result<Vec<HistoryEntry>, String> {
    let settings = state.settings.load()?;
    state.history.load_entries(settings.history.limit)
}

#[tauri::command]
fn save_history_entry(
    state: State<'_, AppState>,
    entry: HistoryEntryDraft,
) -> Result<HistoryEntry, String> {
    state.history.save_entry(entry)
}

#[tauri::command]
fn clear_history(state: State<'_, AppState>) -> Result<(), String> {
    state.history.clear()
}

#[tauri::command]
fn load_settings(state: State<'_, AppState>) -> Result<AppSettings, String> {
    state.settings.load()
}

#[tauri::command]
fn save_settings(
    state: State<'_, AppState>,
    settings: AppSettings,
) -> Result<AppSettings, String> {
    state.settings.save(&settings)
}

#[tauri::command]
fn save_deepseek_key(key: String) -> Result<(), String> {
    let entry = keyring::Entry::new("ftl-voice-prompt", "deepseek-api-key")
        .map_err(|err| err.to_string())?;
    entry.set_password(key.trim()).map_err(|err| err.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    startup::init();
    tauri::Builder::default()
        .on_page_load(|webview, payload| {
            if webview.label() == "main" && matches!(payload.event(), tauri::webview::PageLoadEvent::Finished) {
                startup::mark("page_loaded");
            }
        })
        .on_window_event(|window, event| {
            if window.label() == "main" && matches!(event, tauri::WindowEvent::CloseRequested { .. }) {
                overlay::shutdown(window.app_handle());
                if let Some(state) = window.try_state::<AppState>() {
                    state.sidecar.shutdown();
                }
                if let Some(overlay) = window.app_handle().get_webview_window("recording-overlay") {
                    let _ = overlay.destroy();
                }
            }
        })
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        let app = app.clone();
                        tauri::async_runtime::spawn(async move {
                            let _ = app.emit("hotkey-opened", ());
                        });
                    }
                })
                .build(),
        )
        .setup(|app| {
            startup::mark("setup_started");
            let app_dir = app_data_dir();
            let backend_dir = resolve_backend_dir();
            let history = HistoryStore::new(app_dir.join("history.db"))?;
            let settings = SettingsStore::new(app_dir.join("settings.json"));
            app.manage(AppState {
                settings,
                history,
                sidecar: SidecarManager::new(backend_dir),
                http: Client::new(),
                target_hwnd: Mutex::new(None),
            });
            app.handle()
                .global_shortcut()
                .register(Shortcut::new(
                    Some(Modifiers::CONTROL | Modifiers::ALT),
                    Code::Space,
                ))
                .map_err(|err| err.to_string())?;
            #[cfg(windows)]
            hotkey::install(app.handle().clone())?;
            app.manage(overlay::OverlayStore::default());
            // The overlay already creates itself on the first recording. Avoid
            // starting a second WebView before the main window can paint.
            startup::mark("setup_finished");
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            frontend_ready,
            frontend_painted,
            overlay::recording_overlay_state,
            overlay::recording_overlay_painted,
            overlay::update_recording_overlay,
            show_input_panel,
            start_recording,
            input_devices,
            prepare_models,
            stop_recording,
            recording_status,
            abort_recording,
            analyze_text,
            copy_text,
            paste_text_to_target,
            paste_dictation,
            load_history,
            save_history_entry,
            clear_history,
            load_settings,
            save_settings,
            save_deepseek_key,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

fn load_deepseek_key() -> Result<String, String> {
    if let Ok(value) = std::env::var("DEEPSEEK_API_KEY") {
        if !value.trim().is_empty() {
            return Ok(value);
        }
    }
    let entry = keyring::Entry::new("ftl-voice-prompt", "deepseek-api-key")
        .map_err(|err| err.to_string())?;
    entry.get_password().map_err(|err| err.to_string())
}

fn app_data_dir() -> PathBuf {
    ProjectDirs::from("com", "ftlvoice", "FTL Voice Prompt")
        .map(|dirs| dirs.data_local_dir().to_path_buf())
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")).join(".data"))
}

fn resolve_backend_dir() -> PathBuf {
    let current = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    if let Some(path) = sidecar::resolve_backend_dir_from(&current) {
        return path;
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            if let Some(path) = sidecar::resolve_backend_dir_from(parent) {
                return path;
            }
        }
    }
    current.join("backend")
}
