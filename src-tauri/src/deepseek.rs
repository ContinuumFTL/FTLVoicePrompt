use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::settings::DeepSeekSettings;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum AnalysisPreset {
    #[serde(rename = "requirements")]
    Requirements,
    #[serde(rename = "cleanup")]
    Cleanup,
}

impl AnalysisPreset {
    pub fn from_setting(value: &str) -> Self {
        match value {
            "cleanup" => Self::Cleanup,
            _ => Self::Requirements,
        }
    }
}

pub fn build_deepseek_request(model: &str, preset: AnalysisPreset, text: &str) -> Value {
    json!({
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": system_prompt(preset),
            },
            {
                "role": "user",
                "content": text,
            }
        ],
        "thinking": { "type": "disabled" },
        "stream": false,
    })
}

pub async fn analyze_with_deepseek(
    client: &Client,
    settings: &DeepSeekSettings,
    api_key: &str,
    preset: AnalysisPreset,
    text: &str,
) -> Result<String, String> {
    let request = build_deepseek_request(&settings.model, preset, text);
    let url = format!("{}/chat/completions", settings.base_url.trim_end_matches('/'));
    let response: Value = client
        .post(url)
        .bearer_auth(api_key)
        .json(&request)
        .send()
        .await
        .map_err(|err| err.to_string())?
        .error_for_status()
        .map_err(|err| err.to_string())?
        .json()
        .await
        .map_err(|err| err.to_string())?;

    response["choices"][0]["message"]["content"]
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| "DeepSeek response did not include message content".into())
}

fn system_prompt(preset: AnalysisPreset) -> &'static str {
    match preset {
        AnalysisPreset::Requirements => {
            "你是语音输入后的需求整理器。请把用户口述整理成适合发给 AI 编程助手的结构化需求文档。不要添加用户没有表达的需求。保留技术名词、文件名、函数名、库名、变量名。对不确定内容标注“可能需要确认”。只输出整理后的文本。"
        }
        AnalysisPreset::Cleanup => {
            "你是语音转写清理器。请纠正错别字、标点和明显重复，不要整理成需求文档，不要添加新需求。保留技术名词、文件名、函数名、库名、变量名。只输出清理后的文本。"
        }
    }
}
