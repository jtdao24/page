pub mod api;
pub mod backend;
pub mod command_names;
pub mod commands;
pub mod error;
pub mod preferences;
pub mod secrets;

use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::webview::NewWindowResponse;
use tauri::{
    AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder, WindowEvent, Wry,
};

use backend::BackendManager;
use commands::{AppState, MAIN_LABEL, request_quit};
use preferences::PreferencesStore;

const QUIT_MENU_ID: &str = "page-quit";

/// Only the bundled app (or the configured dev server in debug builds) may load.
pub fn navigation_allowed(url: &Url, dev_url: Option<&Url>) -> bool {
    let bundled = match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" | "https" => url.host_str() == Some("tauri.localhost"),
        _ => false,
    };
    bundled || dev_url.is_some_and(|dev| dev.origin() == url.origin())
}

/// The default macOS menu, except that Quit is an ordinary item routed
/// through the frontend's dirty-document guard. The predefined Quit item
/// terminates the application without any chance to cancel.
fn build_menu(app: &AppHandle) -> tauri::Result<Menu<Wry>> {
    let quit = MenuItem::with_id(app, QUIT_MENU_ID, "Quit Page", true, Some("CmdOrCtrl+Q"))?;
    let edit = Submenu::with_items(
        app,
        "Edit",
        true,
        &[
            // Undo and redo stay with CodeMirror's own key bindings.
            &PredefinedMenuItem::cut(app, None)?,
            &PredefinedMenuItem::copy(app, None)?,
            &PredefinedMenuItem::paste(app, None)?,
            &PredefinedMenuItem::select_all(app, None)?,
        ],
    )?;
    let window = Submenu::with_items(
        app,
        "Window",
        true,
        &[
            &PredefinedMenuItem::minimize(app, None)?,
            &PredefinedMenuItem::maximize(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::close_window(app, None)?,
        ],
    )?;
    #[cfg(target_os = "macos")]
    let application = Submenu::with_items(
        app,
        "Page",
        true,
        &[
            &PredefinedMenuItem::about(app, None, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::services(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &PredefinedMenuItem::hide(app, None)?,
            &PredefinedMenuItem::hide_others(app, None)?,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;
    #[cfg(not(target_os = "macos"))]
    let application = Submenu::with_items(app, "File", true, &[&quit])?;
    Menu::with_items(app, &[&application, &edit, &window])
}

fn quit_approved(app: &AppHandle) -> bool {
    app.try_state::<AppState>()
        .is_some_and(|state| state.quit_approved.load(Ordering::SeqCst))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend = Arc::new(BackendManager::for_build());
    let quit = Arc::new(AtomicBool::new(false));
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .menu(build_menu)
        .on_menu_event(|app, event| {
            if event.id() == QUIT_MENU_ID {
                request_quit(app);
            }
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == MAIN_LABEL && !quit_approved(window.app_handle()) {
                    api.prevent_close();
                    request_quit(window.app_handle());
                }
            }
        })
        .setup({
            let backend = Arc::clone(&backend);
            let quit = Arc::clone(&quit);
            move |app| {
                let handle = app.handle().clone();
                backend.set_listener(Box::new(move |status| {
                    use tauri::Emitter;
                    let _ = handle.emit_to(MAIN_LABEL, commands::BACKEND_STATUS_EVENT, status);
                }));
                let directory = app.path().app_config_dir()?;
                // Read at each Core launch, so a changed key applies on restart; a
                // missing or unreadable file falls back to the environment.
                let keys = Arc::new(secrets::KeyStore::new(directory.clone()));
                let source = Arc::clone(&keys);
                backend.set_gemini_key_source(Box::new(move || source.read().ok().flatten()));
                app.manage(AppState {
                    backend,
                    preferences: Arc::new(PreferencesStore::new(directory)),
                    keys,
                    quit_approved: quit,
                });
                let dev_url = if cfg!(debug_assertions) {
                    app.config().build.dev_url.clone()
                } else {
                    None
                };
                WebviewWindowBuilder::new(app, MAIN_LABEL, WebviewUrl::App("index.html".into()))
                    .title("Page")
                    .inner_size(1024.0, 720.0)
                    .min_inner_size(800.0, 600.0)
                    .on_navigation(move |url| navigation_allowed(url, dev_url.as_ref()))
                    .on_new_window(|_, _| NewWindowResponse::Deny)
                    .build()?;
                Ok(())
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::backend_start,
            commands::backend_status,
            commands::backend_restart,
            commands::vault_create,
            commands::vault_open,
            commands::vault_list,
            commands::vault_get,
            commands::vault_close,
            commands::vault_reconcile,
            commands::graph_read,
            commands::semantic_index,
            commands::semantic_search,
            commands::ask_question,
            commands::source_list,
            commands::source_read,
            commands::web_page_save,
            commands::note_list,
            commands::note_read,
            commands::note_create,
            commands::note_update,
            commands::note_move,
            commands::note_delete,
            commands::preferences_read,
            commands::preferences_write,
            commands::gemini_key_status,
            commands::gemini_key_save,
            commands::gemini_key_clear,
            commands::desktop_quit,
        ])
        .build(tauri::generate_context!())
        .expect("error while building Page");

    app.run(move |app, event| match event {
        RunEvent::ExitRequested { api, .. } if !quit.load(Ordering::SeqCst) => {
            api.prevent_exit();
            request_quit(app);
        }
        RunEvent::Exit => {
            // Normally already done by desktop_quit. Covers terminations that
            // macOS does not let us cancel, such as Quit from the Dock.
            let backend = Arc::clone(&backend);
            let _ = std::thread::spawn(move || backend.shutdown()).join();
        }
        _ => {}
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn navigation_is_limited_to_app_origins() {
        let dev = Url::parse("http://localhost:1420").unwrap();
        let allowed = [
            "tauri://localhost/index.html",
            "http://tauri.localhost/",
            "http://localhost:1420/src/main.tsx",
        ];
        for url in allowed {
            assert!(
                navigation_allowed(&Url::parse(url).unwrap(), Some(&dev)),
                "{url}"
            );
        }
        let denied = [
            "https://example.com/",
            "http://127.0.0.1:8765/api/v1/health",
            "http://localhost:1421/",
            "file:///etc/passwd",
            "tauri://example.com/",
        ];
        for url in denied {
            assert!(
                !navigation_allowed(&Url::parse(url).unwrap(), Some(&dev)),
                "{url}"
            );
        }
        assert!(!navigation_allowed(
            &Url::parse("http://localhost:1420/").unwrap(),
            None
        ));
    }
}
