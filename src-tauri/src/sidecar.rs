use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, File},
    path::{Path, PathBuf},
    process::{Command as StdCommand, Stdio},
    sync::Mutex,
    time::Duration,
};
use tokio::{process::Child, process::Command, time::sleep};

use crate::settings::AsrSettings;

// Version 12 requires the external text-rule loader and live format diagnostics.
const SIDECAR_PROTOCOL: u64 = 12;

fn check_protocol(protocol: u64) -> Result<(), String> {
    if protocol == SIDECAR_PROTOCOL { Ok(()) } else {
        Err("检测到旧语音后端，文字替换规则尚未生效。仅重启桌面项目不会替换残留后端；请先关闭旧语音后端，再重新准备模型。".into())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TranscriptionResponse {
    pub session_id: String,
    pub status: String,
    pub error: Option<String>,
    pub raw_text: String,
    pub duration_ms: i64,
    pub model: String,
    pub language: String,
    #[serde(default)]
    pub audio_levels: Vec<f32>,
    #[serde(default)]
    pub capture_ready: bool,
    #[serde(default)]
    pub stop_requested: bool,
    #[serde(default)]
    pub capture_start_ms: Option<f64>,
    #[serde(default)]
    pub capture_warning: Option<String>,
}

pub struct SidecarManager {
    client: Client,
    child: Mutex<Option<Child>>,
    base_url: String,
    backend_dir: PathBuf,
    #[cfg(windows)]
    job: Mutex<Option<crate::sidecar_job::SidecarJob>>,
}

impl SidecarManager {
    pub fn shutdown(&self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(process) = child.as_mut() {
                let _ = process.start_kill();
            }
        }
    }

    pub fn new(backend_dir: PathBuf) -> Self {
        Self {
            client: Client::new(),
            child: Mutex::new(None),
            base_url: "http://127.0.0.1:8765".into(),
            backend_dir,
            #[cfg(windows)]
            job: Mutex::new(None),
        }
    }

    pub async fn prepare_models(&self, settings: &AsrSettings, retry: bool) -> Result<serde_json::Value, String> {
        self.ensure_running(settings).await?;
        let response = self.client.post(format!("{}/models/prepare?retry={}", self.base_url, retry))
            .json(settings).timeout(Duration::from_secs(10)).send().await.map_err(|err| err.to_string())?;
        response.error_for_status().map_err(|err| err.to_string())?
            .json().await.map_err(|err| err.to_string())
    }

    pub async fn input_devices(&self, settings: &AsrSettings) -> Result<serde_json::Value, String> {
        self.ensure_running(settings).await?;
        let response = self.client.get(format!("{}/audio/devices", self.base_url))
            .timeout(Duration::from_secs(10)).send().await.map_err(|err| err.to_string())?;
        read_response(response).await
    }

    pub async fn start_recording(&self, settings: &AsrSettings) -> Result<TranscriptionResponse, String> {
        self.ensure_running(settings).await?;
        let response = self.client.post(format!("{}/recording/start", self.base_url))
            .json(settings).timeout(Duration::from_secs(10)).send().await
            .map_err(|err| err.to_string())?;
        read_response(response).await
    }

    pub async fn stop_recording(&self, session_id: &str) -> Result<TranscriptionResponse, String> {
        let response = self.client.post(format!("{}/recording/stop", self.base_url))
            .json(&serde_json::json!({"sessionId": session_id}))
            .timeout(Duration::from_secs(200)).send().await.map_err(|err| err.to_string())?;
        read_response(response).await
    }

    pub async fn recording_status(&self, session_id: &str) -> Result<TranscriptionResponse, String> {
        let response = self.client.get(format!("{}/recording/status/{}", self.base_url, session_id))
            .timeout(Duration::from_secs(5)).send().await.map_err(|err| err.to_string())?;
        read_response(response).await
    }

    pub async fn abort_recording(&self, session_id: &str) -> Result<(), String> {
        let response = self.client.post(format!("{}/recording/abort", self.base_url))
            .json(&serde_json::json!({"sessionId": session_id}))
            .timeout(Duration::from_secs(10)).send().await.map_err(|err| err.to_string())?;
        response.error_for_status().map_err(|err| err.to_string())?;
        Ok(())
    }

    async fn ensure_running(&self, settings: &AsrSettings) -> Result<(), String> {
        if let Ok(protocol) = self.health().await {
            return check_protocol(protocol);
        }
        {
            let mut child_guard = self.child.lock().map_err(|err| err.to_string())?;
            if let Some(child) = child_guard.as_mut() {
                match child.try_wait() {
                    Ok(Some(_)) => {
                        *child_guard = None;
                    }
                    Err(_) => {
                        *child_guard = None;
                    }
                    Ok(None) => {}
                }
            }
            if child_guard.is_none() {
                if !self.backend_dir.join("voice_prompt_sidecar").exists() {
                    return Err(format!(
                        "Python sidecar backend directory is invalid: {}",
                        self.backend_dir.display()
                    ));
                }
                let python = resolve_python(&self.backend_dir);
                let log_path = self.backend_dir.join("sidecar.log");
                let stderr = File::create(&log_path)
                    .map(Stdio::from)
                    .unwrap_or_else(|_| Stdio::null());
                let stdout = File::create(self.backend_dir.join("sidecar.out.log"))
                    .map(Stdio::from)
                    .unwrap_or_else(|_| Stdio::null());
                let mut command = Command::new(python);
                #[cfg(windows)]
                command.creation_flags(0x08000000); // CREATE_NO_WINDOW
                #[cfg(windows)]
                let mut job_guard = self.job.lock().map_err(|err| err.to_string())?;
                #[cfg(windows)]
                if job_guard.is_none() {
                    *job_guard = Some(crate::sidecar_job::SidecarJob::new()?);
                }
                let mut child = command
                    .arg("-m")
                    .arg("voice_prompt_sidecar")
                    .current_dir(&self.backend_dir)
                    .env("FTL_ASR_MODEL", &settings.model)
                    .env("FTL_ASR_DEVICE", &settings.device)
                    .env("FTL_ASR_DTYPE", &settings.dtype)
                    .env("FTL_ASR_LANGUAGE", &settings.language)
                    .env("PYTHONUTF8", "1")
                    .env("HF_HUB_OFFLINE", "1")
                    .env("TRANSFORMERS_OFFLINE", "1")
                    .kill_on_drop(true)
                    .stdout(stdout)
                    .stderr(stderr)
                    .spawn()
                    .map_err(|err| err.to_string())?;
                #[cfg(windows)]
                if let Err(error) = child.raw_handle().ok_or_else(|| "语音后端进程已退出".to_string())
                    .and_then(|handle| job_guard.as_ref().unwrap().attach(handle)) {
                    let _ = child.start_kill();
                    return Err(error);
                }
                *child_guard = Some(child);
            }
        }
        self.wait_until_ready().await
    }

    async fn wait_until_ready(&self) -> Result<(), String> {
        for _ in 0..150 {
            if let Ok(protocol) = self.health().await {
                return check_protocol(protocol);
            }
            {
                let mut guard = self.child.lock().map_err(|err| err.to_string())?;
                if let Some(child) = guard.as_mut() {
                    if let Some(status) = child.try_wait().map_err(|err| err.to_string())? {
                        return Err(format!("语音后端启动失败（{}），请查看 {}", status, self.backend_dir.join("sidecar.log").display()));
                    }
                }
            }
            sleep(Duration::from_millis(100)).await;
        }
        Err(format!(
            "语音后端启动超时，请重试准备。日志：{}",
            self.backend_dir.join("sidecar.log").display()
        ))
    }

    async fn health(&self) -> Result<u64, String> {
        let response = self.client.get(format!("{}/health", self.base_url))
            .timeout(Duration::from_secs(2)).send().await.map_err(|err| err.to_string())?
            .error_for_status().map_err(|err| err.to_string())?;
        let value: serde_json::Value = response.json().await.map_err(|err| err.to_string())?;
        Ok(value["protocol"].as_u64().unwrap_or(1))
    }
}

async fn read_response<T: serde::de::DeserializeOwned>(response: reqwest::Response) -> Result<T, String> {
    let status = response.status();
    let value: serde_json::Value = response.json().await.map_err(|err| err.to_string())?;
    if !status.is_success() {
        return Err(value["detail"].as_str().map(str::to_owned).unwrap_or_else(|| value.to_string()));
    }
    serde_json::from_value(value).map_err(|err| err.to_string())
}

fn resolve_python(backend_dir: &Path) -> PathBuf {
    if let Ok(path) = std::env::var("FTL_VOICE_PROMPT_PYTHON") {
        return PathBuf::from(path);
    }
    for candidate in python_candidates(backend_dir) {
        if python_can_start(&candidate) {
            return candidate;
        }
    }
    PathBuf::from("python")
}

fn python_candidates(backend_dir: &Path) -> Vec<PathBuf> {
    let project_dir = backend_dir.parent().unwrap_or(backend_dir);
    [backend_dir, project_dir]
        .into_iter()
        .flat_map(|root| {
            [
                root.join(".venv").join("Scripts").join("python.exe"),
                root.join(".venv").join("python.exe"),
            ]
        })
        .collect()
}

fn python_can_start(path: &Path) -> bool {
    if !path.exists() {
        return false;
    }
    StdCommand::new(path)
        .arg("-c")
        .arg("import sys")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

pub fn resolve_backend_dir_from(start_dir: &Path) -> Option<PathBuf> {
    for ancestor in start_dir.ancestors() {
        let candidate = ancestor.join("backend");
        if candidate.join("voice_prompt_sidecar").exists() {
            return Some(candidate);
        }
    }
    None
}

pub fn ensure_backend_log_dir(backend_dir: &Path) -> Result<(), String> {
    fs::create_dir_all(backend_dir).map_err(|err| err.to_string())
}

#[cfg(test)]
mod tests {
    use super::python_candidates;
    use std::path::Path;

    #[test]
    fn includes_conda_style_project_python_candidate() {
        let backend_dir = Path::new(r"C:\project\backend");

        let candidates = python_candidates(backend_dir);

        assert!(candidates.contains(&Path::new(r"C:\project\.venv\python.exe").to_path_buf()));
    }
    #[test]
    fn startup_wait_accepts_current_protocol_after_initial_unavailability() {
        use std::io::{Read, Write};
        use std::net::TcpListener;
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let mut manager = super::SidecarManager::new(std::path::PathBuf::new());
        manager.base_url = format!("http://{}", listener.local_addr().unwrap());
        let server = std::thread::spawn(move || {
            for status in ["503 Service Unavailable", "200 OK"] {
                let (mut socket, _) = listener.accept().unwrap();
                socket.set_read_timeout(Some(std::time::Duration::from_secs(3))).unwrap();
                let mut request = [0; 4096];
                socket.read(&mut request).unwrap();
                let body = format!(r#"{{"status":"ok","protocol":{}}}"#, super::SIDECAR_PROTOCOL);
                write!(socket, "HTTP/1.1 {}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", status, body.len(), body).unwrap();
            }
        });
        let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
        runtime.block_on(async {
            tokio::time::timeout(std::time::Duration::from_secs(3), manager.wait_until_ready())
                .await.expect("startup should accept a ready backend immediately").unwrap();
        });
        server.join().unwrap();
        assert!(super::check_protocol(7).is_err());
        assert!(super::check_protocol(11).is_err());
    }

}
