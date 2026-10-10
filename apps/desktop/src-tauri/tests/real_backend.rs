//! End-to-end test with this checkout's real Python backend, launched by the
//! production `BackendManager` and used through the production `CoreApiClient`.
//! A missing interpreter is a failure, not a skip.

#![cfg(target_os = "macos")]

use std::collections::BTreeMap;
use std::fs;
use std::net::TcpStream;
use std::path::PathBuf;
use std::sync::Arc;

use page_desktop_lib::backend::{BackendManager, Lifecycle, Timing, development_launch};
use page_desktop_lib::error::ErrorKind;

/// Removes the temporary vault and stops the backend even after a failed assertion.
struct Fixture {
    root: PathBuf,
    manager: Arc<BackendManager>,
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.manager.shutdown();
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn desktop_bridge_drives_the_real_backend() {
    let root = std::env::temp_dir().join(format!("page-desktop-it-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    // Resolve symlinks such as /var -> /private/var, as the API reports resolved roots.
    let root = root.canonicalize().unwrap();
    let launch = development_launch().expect("the development interpreter must be configured");
    assert!(
        launch.program.is_file(),
        "Python environment missing: {}",
        launch.program.display()
    );
    let fixture = Fixture {
        root: root.clone(),
        manager: Arc::new(BackendManager::new(Ok(launch), Timing::default())),
    };
    let manager = &fixture.manager;

    let status = manager.start().expect("backend should become ready");
    assert_eq!((status.state, status.generation), (Lifecycle::Ready, 1));
    assert!(status.core_version.is_some());

    let vault_root = root.join("vault");
    let vault_path = vault_root.to_str().unwrap();
    let client = manager.client().unwrap();
    let vault = client.create_vault(vault_path, "Integration").unwrap();
    assert_eq!(vault.root_path, vault_path);
    let content = "\u{feff}# Título\r\nzweite Zeile\r\nno final newline";
    let created = client
        .create_note(&vault.id, "ideas/first.md", content)
        .unwrap();
    assert_eq!(
        fs::read(vault_root.join("ideas/first.md")).unwrap(),
        content.as_bytes()
    );

    let read = client.read_note(&vault.id, &created.id).unwrap();
    assert_eq!(
        (read.content.as_str(), read.revision.as_str()),
        (content, created.revision.as_str())
    );

    let updated = client
        .update_note(&vault.id, &created.id, &read.revision, "line\rcr only")
        .unwrap();
    assert_eq!(
        fs::read(vault_root.join("ideas/first.md")).unwrap(),
        b"line\rcr only"
    );
    let moved = client
        .move_note(
            &vault.id,
            &created.id,
            &updated.revision,
            "archive/first.md",
        )
        .unwrap();
    assert_eq!(
        (moved.id.as_str(), moved.created_at.as_str()),
        (created.id.as_str(), created.created_at.as_str())
    );
    assert!(!vault_root.join("ideas/first.md").exists());

    // An external edit makes the accepted revision stale.
    fs::write(vault_root.join("archive/first.md"), b"edited outside Page").unwrap();
    let stale = client
        .update_note(&vault.id, &created.id, &moved.revision, "mine")
        .unwrap_err();
    assert_eq!(
        (stale.kind, stale.status, stale.code.as_str()),
        (ErrorKind::Api, Some(412), "revision_conflict")
    );
    assert_eq!(
        fs::read(vault_root.join("archive/first.md")).unwrap(),
        b"edited outside Page"
    );

    // External additions appear after reconciliation.
    fs::write(vault_root.join("external.md"), b"outside").unwrap();
    let counts = client.reconcile(&vault.id, &BTreeMap::new()).unwrap();
    assert_eq!(counts.added, 1);
    let paths: Vec<String> = client
        .list_notes(&vault.id)
        .unwrap()
        .into_iter()
        .map(|note| note.relative_path)
        .collect();
    assert_eq!(
        paths,
        vec!["archive/first.md".to_owned(), "external.md".to_owned()]
    );

    let doomed = client.create_note(&vault.id, "doomed.md", "").unwrap();
    client
        .delete_note(&vault.id, &doomed.id, &doomed.revision)
        .unwrap();
    assert!(!vault_root.join("doomed.md").exists());

    let current = client.read_note(&vault.id, &created.id).unwrap();
    let old_client = client.detach();
    let old_port = old_client.port();
    drop(client);

    let restarted = manager.restart().unwrap();
    assert_eq!(
        (restarted.state, restarted.generation),
        (Lifecycle::Ready, 2)
    );
    // The previous process and credential are gone.
    assert_eq!(
        old_client.list_vaults().unwrap_err().code,
        "backend_unreachable"
    );
    drop(old_client);
    let client = manager.client().unwrap();
    assert!(client.list_vaults().unwrap().is_empty());
    let reopened = client.open_vault(vault_path).unwrap();
    assert_eq!(reopened.id, vault.id);
    let again = client.read_note(&vault.id, &created.id).unwrap();
    assert_eq!(again.content, "edited outside Page");
    assert_eq!(
        (again.created_at.as_str(), again.revision.as_str()),
        (created.created_at.as_str(), current.revision.as_str())
    );
    let port = client.port();
    drop(client);

    manager.shutdown();
    assert_eq!(manager.status().state, Lifecycle::Stopped);
    assert!(TcpStream::connect(("127.0.0.1", port)).is_err());
    assert!(TcpStream::connect(("127.0.0.1", old_port)).is_err());
}
