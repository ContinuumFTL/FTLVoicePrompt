#[cfg(windows)]
use windows::Win32::{
    Foundation::HWND,
    UI::{
        Input::KeyboardAndMouse::{
            SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYBD_EVENT_FLAGS,
            KEYEVENTF_KEYUP, VIRTUAL_KEY, VK_CONTROL, VK_V,
        },
        WindowsAndMessaging::{GetForegroundWindow, SetForegroundWindow},
    },
};

#[cfg(windows)]
pub fn foreground_window_handle() -> Option<isize> {
    let hwnd = unsafe { GetForegroundWindow() };
    if hwnd.0.is_null() {
        None
    } else {
        Some(hwnd.0 as isize)
    }
}

#[cfg(not(windows))]
pub fn foreground_window_handle() -> Option<isize> {
    None
}

#[cfg(windows)]
pub fn activate_window(target_hwnd: Option<isize>) -> Result<(), String> {
    if let Some(handle) = target_hwnd {
        let ok = unsafe { SetForegroundWindow(HWND(handle as *mut std::ffi::c_void)) }.as_bool();
        if !ok {
            return Err("failed to activate target window".into());
        }
    }
    Ok(())
}

pub fn check_dictation_target(target: Option<isize>) -> Result<(), String> {
    if target.is_none() || target != foreground_window_handle() {
        return Err("输入窗口已切换，未自动贴入；识别原文已保留，请手动复制。".into());
    }
    if modifiers_pressed() {
        return Err("修饰键仍被按住，未自动贴入；请松开按键后手动复制原文。".into());
    }
    Ok(())
}

pub fn modifiers_pressed() -> bool {
    #[cfg(windows)]
    {
        use windows::Win32::UI::Input::KeyboardAndMouse::{GetAsyncKeyState, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN};
        return [VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN].iter()
            .any(|key| unsafe { GetAsyncKeyState(key.0 as i32) } < 0);
    }
    #[cfg(not(windows))]
    false
}

pub fn foreground_window_center() -> Option<(i32, i32)> {
    #[cfg(windows)]
    unsafe {
        use windows::Win32::{Foundation::RECT, UI::WindowsAndMessaging::GetWindowRect};
        let mut rect = RECT::default();
        GetWindowRect(GetForegroundWindow(), &mut rect).ok()?;
        return Some(((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2));
    }
    #[cfg(not(windows))]
    None
}

#[cfg(windows)]
pub fn send_ctrl_v() -> Result<(), String> {
    let inputs = [
        key_input(VK_CONTROL, false),
        key_input(VK_V, false),
        key_input(VK_V, true),
        key_input(VK_CONTROL, true),
    ];
    let sent = unsafe { SendInput(&inputs, std::mem::size_of::<INPUT>() as i32) };
    if sent == inputs.len() as u32 {
        Ok(())
    } else {
        Err("failed to send paste shortcut".into())
    }
}

#[cfg(windows)]
fn key_input(key: VIRTUAL_KEY, key_up: bool) -> INPUT {
    INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: key,
                wScan: 0,
                dwFlags: if key_up {
                    KEYEVENTF_KEYUP
                } else {
                    KEYBD_EVENT_FLAGS(0)
                },
                time: 0,
                dwExtraInfo: 0,
            },
        },
    }
}
