use arboard::Clipboard;
use std::{thread, time::Duration};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PastePlan {
    pub text: String,
    pub restore_clipboard: bool,
}

impl PastePlan {
    pub fn new(text: String, restore_clipboard: bool) -> Self {
        Self {
            text,
            restore_clipboard,
        }
    }
}

pub fn copy_text_to_clipboard(text: &str) -> Result<(), String> {
    let mut clipboard = Clipboard::new().map_err(|err| err.to_string())?;
    clipboard.set_text(text.to_owned()).map_err(|err| err.to_string())
}

pub fn paste_text_to_window(target_hwnd: Option<isize>, plan: PastePlan) -> Result<(), String> {
    paste_impl(target_hwnd, plan, false)
}

pub fn paste_dictation_to_current_window(target: isize, plan: PastePlan) -> Result<(), String> {
    paste_impl(Some(target), plan, true)
}

fn paste_impl(target_hwnd: Option<isize>, plan: PastePlan, require_current: bool) -> Result<(), String> {
    if require_current { crate::windowing::check_dictation_target(target_hwnd)?; }
    let mut clipboard = Clipboard::new().map_err(|err| err.to_string())?;
    let previous = if plan.restore_clipboard {
        clipboard.get_text().ok()
    } else {
        None
    };
    clipboard
        .set_text(plan.text)
        .map_err(|err| err.to_string())?;

    let result: Result<(), String> = (|| {
        #[cfg(windows)]
        {
            if require_current { crate::windowing::check_dictation_target(target_hwnd)?; }
            else { crate::windowing::activate_window(target_hwnd)?; }
            crate::windowing::send_ctrl_v()?;
        }
        Ok(())
    })();

    #[cfg(not(windows))]
    {
        let _ = target_hwnd;
    }

    if let Some(previous_text) = previous {
        thread::sleep(Duration::from_millis(120));
        let _ = clipboard.set_text(previous_text);
    }
    result
}
