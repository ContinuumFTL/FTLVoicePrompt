use serde::{Deserialize, Serialize};
use std::{fs, path::PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default, rename_all = "camelCase")]
pub struct AppSettings {
    pub hotkey: String,
    pub asr: AsrSettings,
    pub deepseek: DeepSeekSettings,
    pub history: HistorySettings,
    pub paste: PasteSettings,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
#[serde(default)]
pub struct AsrSettings {
    pub input_device: String,
    pub model: String,
    pub device: String,
    pub dtype: String,
    pub language: String,
    pub terms: String,
    pub english_punctuation: bool,
    pub arabic_numbers: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DeepSeekSettings {
    pub enabled: bool,
    pub default_auto_analyze: bool,
    pub base_url: String,
    pub model: String,
    pub preset: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct HistorySettings {
    pub limit: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct PasteSettings {
    pub restore_clipboard: bool,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            hotkey: "Ctrl+Alt+Space".into(),
            asr: AsrSettings::default(),
            deepseek: DeepSeekSettings::default(),
            history: HistorySettings::default(),
            paste: PasteSettings::default(),
        }
    }
}

impl Default for AsrSettings {
    fn default() -> Self {
        Self {
            input_device: String::new(),
            model: "Qwen/Qwen3-ASR-1.7B".into(),
            device: "auto".into(),
            dtype: "bfloat16".into(),
            language: "zh".into(),
            terms: String::new(),
            english_punctuation: true,
            arabic_numbers: true,
        }
    }
}

impl Default for DeepSeekSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            default_auto_analyze: false,
            base_url: "https://api.deepseek.com".into(),
            model: "deepseek-v4-flash".into(),
            preset: "requirements".into(),
        }
    }
}

impl Default for HistorySettings {
    fn default() -> Self {
        Self { limit: 100 }
    }
}

impl Default for PasteSettings {
    fn default() -> Self {
        Self {
            restore_clipboard: true,
        }
    }
}

#[derive(Debug, Clone)]
pub struct SettingsStore {
    path: PathBuf,
}

impl SettingsStore {
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    pub fn load(&self) -> Result<AppSettings, String> {
        if !self.path.exists() {
            return Ok(AppSettings::default());
        }
        let content = fs::read_to_string(&self.path).map_err(|err| err.to_string())?;
        serde_json::from_str(&content).map_err(|err| err.to_string())
    }

    pub fn save(&self, settings: &AppSettings) -> Result<AppSettings, String> {
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).map_err(|err| err.to_string())?;
        }
        let content = serde_json::to_string_pretty(settings).map_err(|err| err.to_string())?;
        fs::write(&self.path, content).map_err(|err| err.to_string())?;
        Ok(settings.clone())
    }
}
