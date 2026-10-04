use chrono::Utc;
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct HistoryEntry {
    pub id: String,
    pub created_at: String,
    pub raw_text: String,
    pub analyzed_text: Option<String>,
    pub preset: String,
    pub asr_model: String,
    pub duration_ms: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct HistoryEntryDraft {
    pub id: Option<String>,
    pub created_at: Option<String>,
    pub raw_text: String,
    pub analyzed_text: Option<String>,
    pub preset: String,
    pub asr_model: String,
    pub duration_ms: i64,
}

#[derive(Debug, Clone)]
pub struct HistoryStore {
    path: PathBuf,
}

impl HistoryStore {
    pub fn new(path: PathBuf) -> Result<Self, String> {
        let store = Self { path };
        store.initialize()?;
        Ok(store)
    }

    pub fn save_entry(&self, draft: HistoryEntryDraft) -> Result<HistoryEntry, String> {
        let entry = HistoryEntry {
            id: draft.id.unwrap_or_else(create_id),
            created_at: draft
                .created_at
                .unwrap_or_else(|| Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true)),
            raw_text: draft.raw_text,
            analyzed_text: draft.analyzed_text.filter(|text| !text.trim().is_empty()),
            preset: draft.preset,
            asr_model: draft.asr_model,
            duration_ms: draft.duration_ms,
        };
        let connection = self.connection()?;
        connection
            .execute(
                "INSERT OR REPLACE INTO history_entries (id, created_at, raw_text, analyzed_text, preset, asr_model, duration_ms)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![
                    entry.id,
                    entry.created_at,
                    entry.raw_text,
                    entry.analyzed_text,
                    entry.preset,
                    entry.asr_model,
                    entry.duration_ms
                ],
            )
            .map_err(|err| err.to_string())?;
        Ok(entry)
    }

    pub fn load_entries(&self, limit: usize) -> Result<Vec<HistoryEntry>, String> {
        let connection = self.connection()?;
        let mut statement = connection
            .prepare(
                "SELECT id, created_at, raw_text, analyzed_text, preset, asr_model, duration_ms
                 FROM history_entries
                 ORDER BY created_at DESC
                 LIMIT ?1",
            )
            .map_err(|err| err.to_string())?;
        let rows = statement
            .query_map([limit as i64], |row| {
                Ok(HistoryEntry {
                    id: row.get(0)?,
                    created_at: row.get(1)?,
                    raw_text: row.get(2)?,
                    analyzed_text: row.get(3)?,
                    preset: row.get(4)?,
                    asr_model: row.get(5)?,
                    duration_ms: row.get(6)?,
                })
            })
            .map_err(|err| err.to_string())?;

        rows.collect::<Result<Vec<_>, _>>()
            .map_err(|err| err.to_string())
    }

    pub fn clear(&self) -> Result<(), String> {
        let connection = self.connection()?;
        connection
            .execute("DELETE FROM history_entries", [])
            .map_err(|err| err.to_string())?;
        Ok(())
    }

    fn initialize(&self) -> Result<(), String> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent).map_err(|err| err.to_string())?;
        }
        let connection = self.connection()?;
        connection
            .execute_batch(
                "CREATE TABLE IF NOT EXISTS history_entries (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    analyzed_text TEXT,
                    preset TEXT NOT NULL,
                    asr_model TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL
                );",
            )
            .map_err(|err| err.to_string())?;
        Ok(())
    }

    fn connection(&self) -> Result<Connection, String> {
        Connection::open(&self.path).map_err(|err| err.to_string())
    }
}

fn create_id() -> String {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!("{}-{}", nanos, std::process::id())
}
