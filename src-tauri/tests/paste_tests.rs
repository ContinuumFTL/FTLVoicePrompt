use ftl_voice_prompt_lib::paste::PastePlan;

#[test]
fn paste_plan_restores_clipboard_by_default() {
    let plan = PastePlan::new("hello".into(), true);

    assert_eq!(plan.text, "hello");
    assert!(plan.restore_clipboard);
}

// Opt in: creates only a disposable native EDIT window and briefly focuses it.
// No microphone, external application, or message submission is involved.
#[cfg(windows)]
#[test]
#[ignore = "requires an interactive Windows desktop"]
fn native_edit_receives_unicode_dictation() {
    use ftl_voice_prompt_lib::{paste::paste_dictation_to_current_window, windowing};
    use std::time::{Duration, Instant};
    use windows::{core::w, Win32::{Foundation::{HWND, LPARAM, WPARAM}, UI::{
        Input::KeyboardAndMouse::SetFocus,
        WindowsAndMessaging::*,
    }}};

    unsafe {
        let previous = windowing::foreground_window_handle();
        let hwnd = CreateWindowExW(
            WINDOW_EX_STYLE::default(), w!("EDIT"), w!("已有内容："),
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            100, 100, 440, 180, None, None, None, None,
        ).unwrap();
        struct Cleanup(HWND, Option<isize>);
        impl Drop for Cleanup {
            fn drop(&mut self) {
                unsafe { let _ = DestroyWindow(self.0); }
                let _ = windowing::activate_window(self.1);
            }
        }
        let _cleanup = Cleanup(hwnd, previous);
        // A test launched by a background agent has no foreground activation
        // grant. Temporarily attach input queues solely to focus our own fixture.
        #[link(name = "kernel32")]
        extern "system" { fn GetCurrentThreadId() -> u32; }
        #[link(name = "user32")]
        extern "system" { fn AttachThreadInput(from: u32, to: u32, attach: i32) -> i32; }
        let current_thread = GetCurrentThreadId();
        let foreground_thread = GetWindowThreadProcessId(GetForegroundWindow(), None);
        let attached = AttachThreadInput(current_thread, foreground_thread, 1) != 0;
        let activated = SetForegroundWindow(hwnd).as_bool();
        if attached { AttachThreadInput(current_thread, foreground_thread, 0); }
        assert!(activated, "could not focus disposable edit fixture");
        let _ = SetFocus(hwnd);
        // EM_SETSEL: append at the caret without replacing existing text.
        let end = GetWindowTextLengthW(hwnd);
        SendMessageW(hwnd, 0x00B1, WPARAM(end as usize), LPARAM(end as isize));
        let target = hwnd.0 as isize;
        let worker = std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(100));
            for segment in ["语音", "输入测试", " · Codex 123"] {
                paste_dictation_to_current_window(target, PastePlan::new(segment.into(), true))?;
            }
            Ok::<(), String>(())
        });
        let deadline = Instant::now() + Duration::from_secs(3);
        let mut text = [0u16; 128];
        loop {
            let mut message = MSG::default();
            while PeekMessageW(&mut message, None, 0, 0, PM_REMOVE).as_bool() {
                let _ = TranslateMessage(&message);
                DispatchMessageW(&message);
            }
            let length = GetWindowTextW(hwnd, &mut text) as usize;
            if worker.is_finished() && length > 0 { break; }
            if Instant::now() > deadline { break; }
            std::thread::sleep(Duration::from_millis(10));
        }
        worker.join().unwrap().unwrap();
        let length = GetWindowTextW(hwnd, &mut text) as usize;
        assert_eq!(String::from_utf16_lossy(&text[..length]), "已有内容：语音输入测试 · Codex 123");
    }
}
