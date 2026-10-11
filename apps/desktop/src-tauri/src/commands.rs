//! Tauri command handlers. Each checks that the caller is the trusted main
//! webview, then runs its blocking work on a blocking task. Commands expose
//! only the fixed operations below: no URL, header, shell, file or SQL access.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};

use tauri::{AppHandle, Emitter, State, Webview};

use crate::api::{
    AskResponse, GraphResponse, IndexResponse, NoteResponse, NoteSummaryResponse,
    ReconcileResponse, SearchResponse, SourceResponse, SourceSummaryResponse, VaultResponse,
};
use crate::backend::{BackendManager, BackendStatus};
use crate::error::DesktopError;
use crate::preferences::{DesktopPreferences, PreferencesStore};
use crate::secrets::{self, GeminiKeyStatus};

pub const MAIN_LABEL: &str = "main";
pub const BACKEND_STATUS_EVENT: &str = "backend-status";
pub const QUIT_REQUESTED_EVENT: &str = "quit-requested";

pub struct AppState {
    pub backend: Arc<BackendManager>,
    pub preferences: Arc<PreferencesStore>,
    pub quit_approved: Arc<AtomicBool>,
}

/// Only the main window's own webview may call commands.
pub fn check_caller(window_label: &str, webview_label: &str) -> Result<(), DesktopError> {
    if window_label == MAIN_LABEL && webview_label == MAIN_LABEL {
        Ok(())
    } else {
        Err(DesktopError::backend(
            "caller_not_allowed",
            "This window may not use Page commands.",
        ))
    }
}

fn ensure_main(webview: &Webview) -> Result<(), DesktopError> {
    check_caller(webview.window().label(), webview.label())
}

async fn blocking<T, F>(work: F) -> Result<T, DesktopError>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, DesktopError> + Send + 'static,
{
    tauri::async_runtime::spawn_blocking(work)
        .await
        .map_err(|_| DesktopError::backend("task_failed", "The desktop task failed."))?
}

/// Ask the frontend to run its dirty-document guard before quitting.
pub fn request_quit(app: &AppHandle) {
    let _ = app.emit_to(MAIN_LABEL, QUIT_REQUESTED_EVENT, ());
}

#[tauri::command(rename_all = "snake_case")]
pub async fn backend_start(
    webview: Webview,
    state: State<'_, AppState>,
) -> Result<BackendStatus, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.start()).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn backend_status(
    webview: Webview,
    state: State<'_, AppState>,
) -> Result<BackendStatus, DesktopError> {
    ensure_main(&webview)?;
    Ok(state.backend.status())
}

#[tauri::command(rename_all = "snake_case")]
pub async fn backend_restart(
    webview: Webview,
    state: State<'_, AppState>,
) -> Result<BackendStatus, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.restart()).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn vault_create(
    webview: Webview,
    state: State<'_, AppState>,
    root_path: String,
    name: String,
) -> Result<VaultResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.create_vault(&root_path, &name)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn vault_open(
    webview: Webview,
    state: State<'_, AppState>,
    root_path: String,
) -> Result<VaultResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.open_vault(&root_path)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn vault_list(
    webview: Webview,
    state: State<'_, AppState>,
) -> Result<Vec<VaultResponse>, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.list_vaults()).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn vault_get(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
) -> Result<VaultResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.get_vault(&vault_id)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn vault_close(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
) -> Result<(), DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.close_vault(&vault_id)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn vault_reconcile(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    known_renames: BTreeMap<String, String>,
) -> Result<ReconcileResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.reconcile(&vault_id, &known_renames)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn semantic_index(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    rebuild: bool,
) -> Result<IndexResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.index_vault(&vault_id, rebuild)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn semantic_search(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    query: String,
    limit: usize,
) -> Result<SearchResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.search_vault(&vault_id, &query, limit)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn ask_question(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    question: String,
    budget: usize,
) -> Result<AskResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.ask_question(&vault_id, &question, budget)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn source_list(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
) -> Result<Vec<SourceSummaryResponse>, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.list_sources(&vault_id)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn source_read(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    source_id: String,
) -> Result<SourceResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.read_source(&vault_id, &source_id)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn web_page_save(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    url: String,
) -> Result<NoteResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.save_web_page(&vault_id, &url)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn graph_read(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
) -> Result<GraphResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.read_graph(&vault_id)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn note_list(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
) -> Result<Vec<NoteSummaryResponse>, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.list_notes(&vault_id)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn note_read(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    note_id: String,
) -> Result<NoteResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || backend.client()?.read_note(&vault_id, &note_id)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn note_create(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    relative_path: String,
    content: String,
) -> Result<NoteResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || {
        backend
            .client()?
            .create_note(&vault_id, &relative_path, &content)
    })
    .await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn note_update(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    note_id: String,
    revision: String,
    content: String,
) -> Result<NoteResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || {
        backend
            .client()?
            .update_note(&vault_id, &note_id, &revision, &content)
    })
    .await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn note_move(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    note_id: String,
    revision: String,
    relative_path: String,
) -> Result<NoteResponse, DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || {
        backend
            .client()?
            .move_note(&vault_id, &note_id, &revision, &relative_path)
    })
    .await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn note_delete(
    webview: Webview,
    state: State<'_, AppState>,
    vault_id: String,
    note_id: String,
    revision: String,
) -> Result<(), DesktopError> {
    ensure_main(&webview)?;
    let backend = Arc::clone(&state.backend);
    blocking(move || {
        backend
            .client()?
            .delete_note(&vault_id, &note_id, &revision)
    })
    .await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn preferences_read(
    webview: Webview,
    state: State<'_, AppState>,
) -> Result<DesktopPreferences, DesktopError> {
    ensure_main(&webview)?;
    let store = Arc::clone(&state.preferences);
    blocking(move || store.read()).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn preferences_write(
    webview: Webview,
    state: State<'_, AppState>,
    preferences: DesktopPreferences,
) -> Result<(), DesktopError> {
    ensure_main(&webview)?;
    let store = Arc::clone(&state.preferences);
    blocking(move || store.write(&preferences)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn gemini_key_status(webview: Webview) -> Result<GeminiKeyStatus, DesktopError> {
    ensure_main(&webview)?;
    blocking(secrets::status).await
}

/// Save the key; the frontend restarts Page Core so it takes effect.
#[tauri::command(rename_all = "snake_case")]
pub async fn gemini_key_save(webview: Webview, key: String) -> Result<(), DesktopError> {
    ensure_main(&webview)?;
    blocking(move || secrets::save_key(&key)).await
}

#[tauri::command(rename_all = "snake_case")]
pub async fn gemini_key_clear(webview: Webview) -> Result<(), DesktopError> {
    ensure_main(&webview)?;
    blocking(secrets::clear_key).await
}

/// Begin the approved shutdown. Repeated calls do not start another one.
#[tauri::command(rename_all = "snake_case")]
pub async fn desktop_quit(
    app: AppHandle,
    webview: Webview,
    state: State<'_, AppState>,
) -> Result<(), DesktopError> {
    ensure_main(&webview)?;
    if state.quit_approved.swap(true, Ordering::SeqCst) {
        return Ok(());
    }
    let backend = Arc::clone(&state.backend);
    blocking(move || {
        backend.shutdown();
        Ok(())
    })
    .await?;
    app.exit(0);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::command_names::COMMAND_NAMES;

    #[test]
    fn only_the_main_webview_may_call() {
        assert!(check_caller("main", "main").is_ok());
        assert_eq!(
            check_caller("other", "main").unwrap_err().code,
            "caller_not_allowed"
        );
        assert!(check_caller("main", "child").is_err());
        assert!(check_caller("", "").is_err());
    }

    #[test]
    fn capability_grants_exactly_the_commands_and_event_listening() {
        let text = include_str!("../capabilities/default.json");
        let capability: serde_json::Value = serde_json::from_str(text).unwrap();
        assert_eq!(capability["windows"], serde_json::json!(["main"]));
        assert!(capability.get("remote").is_none());
        let mut granted: Vec<String> = capability["permissions"]
            .as_array()
            .unwrap()
            .iter()
            .map(|value| value.as_str().unwrap().to_owned())
            .collect();
        granted.sort();
        let mut expected: Vec<String> = COMMAND_NAMES
            .iter()
            .map(|name| format!("allow-{}", name.replace('_', "-")))
            .collect();
        expected.push("core:event:allow-listen".to_owned());
        expected.push("core:event:allow-unlisten".to_owned());
        // The native folder and save pickers only return the path the user chose.
        expected.push("dialog:allow-open".to_owned());
        expected.push("dialog:allow-save".to_owned());
        expected.sort();
        assert_eq!(granted, expected);
    }

    #[test]
    fn production_csp_forbids_scripts_frames_and_python_connections() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let security = &config["app"]["security"];
        for key in ["csp", "devCsp"] {
            let policy = security[key].as_object().unwrap();
            assert_eq!(policy["script-src"], "'self'");
            assert_eq!(policy["object-src"], "'none'");
            assert_eq!(policy["frame-src"], "'none'");
            assert_eq!(policy["style-src"], "'self' 'unsafe-inline'");
            let connect = policy["connect-src"].as_str().unwrap();
            assert!(!connect.contains("127.0.0.1") && !connect.contains('*'));
        }
        assert_eq!(security["csp"]["connect-src"], "ipc: http://ipc.localhost");
        assert!(config["app"]["windows"].as_array().unwrap().is_empty());
    }
}
