//! Dedicated Right Alt dictation key. The callback only queues work; ASR never
//! runs on the Windows hook thread.
#[derive(Default)]
pub struct RightAltState {
    held: bool,
    passthrough: bool,
}

impl RightAltState {
    // Returns (consume, trigger). Start on the first key-down, never on repeats.
    pub fn key(&mut self, right_alt: bool, down: bool, modified: bool) -> (bool, bool) {
        if !right_alt {
            return (false, false);
        }
        if down {
            if self.passthrough { return (false, false); }
            if !self.held && modified {
                self.passthrough = true;
                return (false, false);
            }
            let trigger = !self.held;
            self.held = true;
            (true, trigger)
        } else {
            let consumed = self.held;
            *self = Self::default();
            (consumed, false)
        }
    }
}

#[cfg(windows)]
mod native {
    use super::RightAltState;
    use std::{cell::RefCell, sync::mpsc};
    use tauri::{AppHandle, Emitter};
    use windows::Win32::{
        Foundation::{LPARAM, LRESULT, WPARAM},
        UI::{Input::KeyboardAndMouse::{GetAsyncKeyState, VK_CONTROL, VK_SHIFT, VK_LMENU, VK_LWIN, VK_RWIN, VK_RMENU},
            WindowsAndMessaging::*},
    };

    thread_local! {
        static STATE: RefCell<RightAltState> = RefCell::new(RightAltState::default());
        static EVENTS: RefCell<Option<mpsc::SyncSender<isize>>> = const { RefCell::new(None) };
    }

    unsafe extern "system" fn callback(code: i32, message: WPARAM, data: LPARAM) -> LRESULT {
        if code >= 0 {
            let event = &*(data.0 as *const KBDLLHOOKSTRUCT);
            if !event.flags.contains(LLKHF_INJECTED) {
                let down = matches!(message.0 as u32, WM_KEYDOWN | WM_SYSKEYDOWN);
                let up = matches!(message.0 as u32, WM_KEYUP | WM_SYSKEYUP);
                if down || up {
                    let modified = [VK_CONTROL, VK_SHIFT, VK_LMENU, VK_LWIN, VK_RWIN]
                        .iter().any(|key| GetAsyncKeyState(key.0 as i32) < 0);
                    let (consume, trigger) = STATE.with(|state| state.borrow_mut()
                        .key(event.vkCode == VK_RMENU.0 as u32, down, modified));
                    if trigger {
                        if let Some(target) = crate::windowing::foreground_window_handle() {
                            EVENTS.with(|sender| {
                                if let Some(sender) = sender.borrow().as_ref() { let _ = sender.try_send(target); }
                            });
                        }
                    }
                    if consume { return LRESULT(1); }
                }
            }
        }
        CallNextHookEx(None, code, message, data)
    }

    pub fn install(app: AppHandle) -> Result<(), String> {
        let (events, receiver) = mpsc::sync_channel(8);
        let (ready, installed) = mpsc::sync_channel(1);
        std::thread::Builder::new().name("right-alt-hook".into()).spawn(move || unsafe {
            EVENTS.with(|slot| *slot.borrow_mut() = Some(events));
            match SetWindowsHookExW(WH_KEYBOARD_LL, Some(callback), None, 0) {
                Ok(hook) => {
                    let _ = ready.send(Ok(()));
                    let mut message = MSG::default();
                    while GetMessageW(&mut message, None, 0, 0).0 > 0 {
                        let _ = TranslateMessage(&message);
                        DispatchMessageW(&message);
                    }
                    let _ = UnhookWindowsHookEx(hook);
                }
                Err(error) => { let _ = ready.send(Err(error.to_string())); }
            }
        }).map_err(|error| error.to_string())?;
        installed.recv().map_err(|error| error.to_string())??;
        std::thread::Builder::new().name("dictation-events".into()).spawn(move || {
            for target in receiver { let _ = app.emit("dictation-hotkey", target); }
        }).map_err(|error| error.to_string())?;
        Ok(())
    }
}

#[cfg(windows)]
pub use native::install;
