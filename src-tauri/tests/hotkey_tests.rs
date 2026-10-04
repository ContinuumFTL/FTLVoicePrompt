use ftl_voice_prompt_lib::{hotkey::RightAltState, windowing::check_dictation_target};

#[test]
fn right_alt_starts_on_press_without_waiting_for_release_or_repeating() {
    let mut state = RightAltState::default();
    assert_eq!(state.key(true, true, false), (true, true));
    assert_eq!(state.key(true, true, false), (true, false));
    assert_eq!(state.key(true, false, false), (true, false));
    assert_eq!(state.key(true, false, false), (false, false));
    assert_eq!(state.key(true, true, false), (true, true));
    assert_eq!(state.key(true, false, false), (true, false));
}

#[test]
fn other_keys_and_modified_alt_do_not_start_dictation() {
    let mut state = RightAltState::default();
    assert_eq!(state.key(false, true, false), (false, false));
    assert_eq!(state.key(true, true, true), (false, false));
    assert_eq!(state.key(true, true, false), (false, false));
    assert_eq!(state.key(true, false, true), (false, false));
    state.key(true, true, false);
    state.key(false, true, false);
    assert_eq!(state.key(true, false, false), (true, false));
}

#[test]
fn missing_or_stale_window_cannot_receive_dictation() {
    assert!(check_dictation_target(None).is_err());
    assert!(check_dictation_target(Some(-1)).is_err());
}
