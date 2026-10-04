//! Startup timings contain phase names only, never settings or transcript text.
use std::{fs::File, io::Write, sync::{Mutex, OnceLock, atomic::{AtomicBool, Ordering}}, time::Instant};

static START: OnceLock<Instant> = OnceLock::new();
static LOG: OnceLock<Mutex<File>> = OnceLock::new();
static MODELS_READY: AtomicBool = AtomicBool::new(false);

pub fn init() {
    START.get_or_init(Instant::now);
    let path = std::env::var_os("FTL_STARTUP_LOG").map(std::path::PathBuf::from)
        .unwrap_or_else(|| super::app_data_dir().join("startup.log"));
    if let Some(parent) = path.parent() { let _ = std::fs::create_dir_all(parent); }
    if let Ok(file) = File::create(path) { let _ = LOG.set(Mutex::new(file)); }
    mark("process_started");
}

pub fn mark(phase: &str) {
    if let (Some(start), Some(log)) = (START.get(), LOG.get()) {
        if let Ok(mut file) = log.lock() {
            let _ = writeln!(file, "{} {}ms", phase, start.elapsed().as_millis());
            let _ = file.flush();
        }
    }
}

pub fn models_ready() {
    if !MODELS_READY.swap(true, Ordering::Relaxed) { mark("models_ready"); }
}
