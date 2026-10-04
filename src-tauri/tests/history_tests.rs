use ftl_voice_prompt_lib::history::{HistoryEntryDraft, HistoryStore};

#[test]
fn history_store_persists_only_text_fields() {
    let dir = tempfile::tempdir().unwrap();
    let store = HistoryStore::new(dir.path().join("history.db")).unwrap();

    store
        .save_entry(HistoryEntryDraft {
            id: None,
            created_at: None,
            raw_text: "原始文本".into(),
            analyzed_text: Some("分析文本".into()),
            preset: "requirements".into(),
            asr_model: "Qwen/Qwen3-ASR-1.7B".into(),
            duration_ms: 1500,
        })
        .unwrap();

    let entries = store.load_entries(10).unwrap();

    assert_eq!(entries.len(), 1);
    assert_eq!(entries[0].raw_text, "原始文本");
    assert_eq!(entries[0].analyzed_text.as_deref(), Some("分析文本"));
}
