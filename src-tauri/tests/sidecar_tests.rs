use ftl_voice_prompt_lib::sidecar::resolve_backend_dir_from;

#[test]
fn resolves_backend_from_release_exe_directory_by_walking_up_to_project_root() {
    let root = tempfile::tempdir().unwrap();
    let release_dir = root.path().join("src-tauri").join("target").join("release");
    let backend_dir = root.path().join("backend");
    std::fs::create_dir_all(backend_dir.join("voice_prompt_sidecar")).unwrap();
    std::fs::create_dir_all(&release_dir).unwrap();

    let resolved = resolve_backend_dir_from(&release_dir).unwrap();

    assert_eq!(resolved, backend_dir);
}

#[test]
fn returns_none_when_backend_does_not_exist() {
    let root = tempfile::tempdir().unwrap();

    assert!(resolve_backend_dir_from(root.path()).is_none());
}
