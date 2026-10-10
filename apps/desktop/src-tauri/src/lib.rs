use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use tauri::Manager;

struct BackendProcess(Mutex<Option<Child>>);

fn repo_root() -> Option<PathBuf> {
    let mut dir = std::env::current_dir().ok()?;
    for _ in 0..8 {
        if dir.join("packages").join("core").exists() {
            return Some(dir);
        }
        dir = dir.parent()?.to_path_buf();
    }
    None
}

fn python_executable(root: &std::path::Path) -> PathBuf {
    if cfg!(windows) {
        let venv = root.join(".venv").join("Scripts").join("python.exe");
        if venv.exists() {
            return venv;
        }
        PathBuf::from("python")
    } else {
        let venv = root.join(".venv").join("bin").join("python");
        if venv.exists() {
            return venv;
        }
        PathBuf::from("python3")
    }
}

fn api_already_running() -> bool {
    std::net::TcpStream::connect_timeout(
        &"127.0.0.1:8765".parse().expect("static address"),
        Duration::from_millis(200),
    )
    .is_ok()
}

fn spawn_backend() -> Option<Child> {
    if api_already_running() {
        return None;
    }
    let root = repo_root()?;
    let python = python_executable(&root);
    let mut command = Command::new(python);
    command
        .arg("-m")
        .arg("page_core")
        .current_dir(&root)
        .stdin(Stdio::null());
    #[cfg(not(debug_assertions))]
    {
        command.stdout(Stdio::null()).stderr(Stdio::null());
    }
    command.spawn().ok()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(BackendProcess(Mutex::new(None)))
        .setup(|app| {
            if let Some(child) = spawn_backend() {
                *app.state::<BackendProcess>().0.lock().expect("backend mutex") = Some(child);
            }
            // Give the API a brief head start before the window loads notes.
            thread::sleep(Duration::from_millis(150));
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if window.label() == "main"
                    && let Some(state) = window.try_state::<BackendProcess>()
                    && let Ok(mut child) = state.0.lock()
                    && let Some(mut process) = child.take()
                {
                    let _ = process.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Page");
}
