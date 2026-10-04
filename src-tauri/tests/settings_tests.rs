use ftl_voice_prompt_lib::settings::{AppSettings, DeepSeekSettings, SettingsStore};

#[test]
fn last_selected_model_survives_reopening_settings_store() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("settings.json");
    for model in ["iic/SenseVoiceSmall", "paraformer-zh-streaming", "Qwen/Qwen3-ASR-1.7B"] {
        let mut settings = AppSettings::default();
        settings.asr.model = model.into();
        SettingsStore::new(path.clone()).save(&settings).unwrap();
        assert_eq!(SettingsStore::new(path.clone()).load().unwrap().asr.model, model);
    }
}

#[test]
fn default_settings_use_manual_deepseek_analysis() {
    let settings = AppSettings::default();

    assert_eq!(settings.hotkey, "Ctrl+Alt+Space");
    assert_eq!(settings.asr.model, "Qwen/Qwen3-ASR-1.7B");
    assert_eq!(settings.asr.device, "auto");
    assert!(!settings.deepseek.default_auto_analyze);
    assert_eq!(settings.deepseek.model, "deepseek-v4-flash");
}

#[test]
fn deepseek_defaults_target_current_api_names() {
    let settings = DeepSeekSettings::default();

    assert_eq!(settings.base_url, "https://api.deepseek.com");
    assert_eq!(settings.model, "deepseek-v4-flash");
    assert_eq!(settings.preset, "requirements");
}

#[test]
fn legacy_caret_follow_settings_are_ignored_and_removed_on_save() {
    let mut legacy = serde_json::to_value(AppSettings::default()).unwrap();
    legacy["window"] = serde_json::json!({ "autoFollowCaret": true });
    let settings: AppSettings = serde_json::from_value(legacy).unwrap();
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("settings.json");
    let store = SettingsStore::new(path.clone());
    store.save(&settings).unwrap();
    assert_eq!(store.load().unwrap(), settings);
    let saved: serde_json::Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
    assert!(saved.get("window").is_none());
}


#[test]
fn old_settings_gain_format_defaults_and_new_options_persist() {
    let mut legacy = serde_json::to_value(AppSettings::default()).unwrap();
    for key in ["terms", "englishPunctuation", "arabicNumbers"] {
        legacy["asr"].as_object_mut().unwrap().remove(key);
    }
    let mut settings: AppSettings = serde_json::from_value(legacy).unwrap();
    assert!(settings.asr.english_punctuation && settings.asr.arabic_numbers);
    assert!(settings.asr.terms.is_empty());
    settings.asr.terms = "Vibe Coding\nHarness Engineering".into();
    settings.asr.arabic_numbers = false;
    let directory = tempfile::tempdir().unwrap();
    let store = SettingsStore::new(directory.path().join("settings.json"));
    store.save(&settings).unwrap();
    assert_eq!(store.load().unwrap(), settings);
}
