//! Windows closes the job handle even if the desktop is forcibly terminated.
use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle, RawHandle};
use windows::Win32::Foundation::HANDLE;
use windows::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
    JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

pub struct SidecarJob(OwnedHandle);

impl SidecarJob {
    pub fn new() -> Result<Self, String> {
        unsafe {
            // No name and no inheritable security attributes: only this desktop
            // owns a job handle; Python cannot keep the job alive after exit.
            let handle = CreateJobObjectW(None, None).map_err(|e| e.to_string())?;
            let owned = OwnedHandle::from_raw_handle(handle.0);
            let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            SetInformationJobObject(handle, JobObjectExtendedLimitInformation,
                &limits as *const _ as *const _, std::mem::size_of_val(&limits) as u32)
                .map_err(|e| e.to_string())?;
            Ok(Self(owned))
        }
    }

    pub fn attach(&self, process: RawHandle) -> Result<(), String> {
        unsafe { AssignProcessToJobObject(HANDLE(self.0.as_raw_handle()), HANDLE(process)) }
            .map_err(|e| format!("无法将语音后端关联到桌面进程: {e}"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{process::{Command, Stdio}, time::{Duration, Instant}};
    use std::os::windows::process::CommandExt;
    use windows::Win32::{Foundation::WAIT_OBJECT_0, System::Threading::{OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE}};

    // A separate parent process proves forced exit works without running Drop.
    #[test]
    fn job_parent_fixture() {
        let Some(report) = std::env::var_os("FTL_JOB_TEST_REPORT") else { return };
        let job = SidecarJob::new().unwrap();
        let mut child = Command::new("cmd.exe")
            .args(["/d", "/c", "ping -n 60 127.0.0.1 > nul"])
            .creation_flags(0x08000000).stdout(Stdio::null()).stderr(Stdio::null())
            .spawn().unwrap();
        if let Err(error) = job.attach(child.as_raw_handle()) {
            let _ = child.kill();
            panic!("{error}");
        }
        std::fs::write(report, child.id().to_string()).unwrap();
        let _ = child.wait();
    }

    #[test]
    fn forced_parent_exit_terminates_owned_backend() {
        let dir = tempfile::tempdir().unwrap();
        let report = dir.path().join("child.pid");
        let mut parent = Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "sidecar_job::tests::job_parent_fixture", "--nocapture"])
            .env("FTL_JOB_TEST_REPORT", &report).creation_flags(0x08000000)
            .stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
        let deadline = Instant::now() + Duration::from_secs(10);
        let child_pid = loop {
            if let Ok(pid) = std::fs::read_to_string(&report) {
                if let Ok(pid) = pid.parse::<u32>() { break pid; }
            }
            if parent.try_wait().unwrap().is_some() || Instant::now() >= deadline {
                let _ = parent.kill();
                let _ = parent.wait();
                panic!("fixture did not attach its backend");
            }
            std::thread::sleep(Duration::from_millis(25));
        };
        let child = unsafe { OpenProcess(PROCESS_SYNCHRONIZE, false, child_pid) }.unwrap();
        let child = unsafe { OwnedHandle::from_raw_handle(child.0) };
        parent.kill().unwrap();
        parent.wait().unwrap();
        assert_eq!(unsafe { WaitForSingleObject(HANDLE(child.as_raw_handle()), 5000) }, WAIT_OBJECT_0);
    }
}
