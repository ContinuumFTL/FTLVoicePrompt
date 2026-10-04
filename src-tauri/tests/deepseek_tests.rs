use ftl_voice_prompt_lib::deepseek::{build_deepseek_request, AnalysisPreset};

#[test]
fn deepseek_request_disables_thinking_for_prompt_cleanup() {
    let request = build_deepseek_request(
        "deepseek-v4-flash",
        AnalysisPreset::Requirements,
        "帮我整理这个需求",
    );

    assert_eq!(request["model"], "deepseek-v4-flash");
    assert_eq!(request["thinking"]["type"], "disabled");
    assert_eq!(request["messages"][1]["content"], "帮我整理这个需求");
}

#[test]
fn cleanup_preset_asks_model_not_to_add_requirements() {
    let request = build_deepseek_request(
        "deepseek-v4-flash",
        AnalysisPreset::Cleanup,
        "这个 React component 需要改一下",
    );
    let system = request["messages"][0]["content"].as_str().unwrap();

    assert!(system.contains("不要整理成需求文档"));
    assert!(system.contains("保留技术名词"));
}
