//! Remembered workspace selections, stored as `workspace.json` in the
//! application configuration directory, outside every vault.
//!
//! Only successful selections are stored: vault IDs, resolved roots and the
//! last selected note ID. Never note content, drafts, revisions, endpoints,
//! tokens or executable settings.

use std::collections::HashSet;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

use crate::error::{DesktopError, is_canonical_uuid};

pub const FORMAT_VERSION: u32 = 1;
pub const MAX_RECENT: usize = 10;
pub const FILE_NAME: &str = "workspace.json";
const MAX_FILE_SIZE: u64 = 64 * 1024;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RecentVault {
    pub vault_id: String,
    pub root_path: String,
    #[serde(deserialize_with = "Option::deserialize")]
    pub last_note_id: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DesktopPreferences {
    pub version: u32,
    pub recent_vaults: Vec<RecentVault>,
    #[serde(deserialize_with = "Option::deserialize")]
    pub active_vault_id: Option<String>,
}

impl Default for DesktopPreferences {
    fn default() -> Self {
        Self {
            version: FORMAT_VERSION,
            recent_vaults: Vec::new(),
            active_vault_id: None,
        }
    }
}

fn invalid() -> DesktopError {
    DesktopError::preferences(
        "preferences_invalid",
        "The remembered workspace settings are invalid.",
    )
}

impl DesktopPreferences {
    /// Check version, identifiers, absolute roots, uniqueness and limits.
    pub fn validate(&self) -> Result<(), DesktopError> {
        if self.version != FORMAT_VERSION {
            return Err(DesktopError::preferences(
                "preferences_unsupported",
                "The remembered workspace settings use an unsupported format.",
            ));
        }
        if self.recent_vaults.len() > MAX_RECENT {
            return Err(invalid());
        }
        let mut ids = HashSet::new();
        let mut roots = HashSet::new();
        for entry in &self.recent_vaults {
            let root = Path::new(&entry.root_path);
            let valid = is_canonical_uuid(&entry.vault_id)
                && !entry.root_path.is_empty()
                && !entry.root_path.contains('\0')
                && root.is_absolute()
                && entry.last_note_id.as_deref().is_none_or(is_canonical_uuid)
                && ids.insert(entry.vault_id.as_str())
                && roots.insert(entry.root_path.as_str());
            if !valid {
                return Err(invalid());
            }
        }
        if let Some(active) = &self.active_vault_id {
            if !ids.contains(active.as_str()) {
                return Err(invalid());
            }
        }
        Ok(())
    }
}

/// Reads and atomically replaces `workspace.json`; writes are serialized.
pub struct PreferencesStore {
    directory: PathBuf,
    write_lock: Mutex<()>,
}

impl PreferencesStore {
    pub fn new(directory: PathBuf) -> Self {
        Self {
            directory,
            write_lock: Mutex::new(()),
        }
    }

    pub fn path(&self) -> PathBuf {
        self.directory.join(FILE_NAME)
    }

    /// Missing settings are the defaults; anything else unreadable is an error
    /// and the file is left untouched.
    pub fn read(&self) -> Result<DesktopPreferences, DesktopError> {
        let unreadable = || {
            DesktopError::preferences(
                "preferences_unreadable",
                "The remembered workspace settings could not be read.",
            )
        };
        match fs::symlink_metadata(&self.directory) {
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(DesktopPreferences::default());
            }
            Err(_) => return Err(unreadable()),
            Ok(metadata) if !metadata.file_type().is_dir() => return Err(unreadable()),
            Ok(_) => {}
        }
        let path = self.path();
        match fs::symlink_metadata(&path) {
            Ok(metadata) if !metadata.file_type().is_file() => return Err(unreadable()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(DesktopPreferences::default());
            }
            Err(_) => return Err(unreadable()),
            Ok(_) => {}
        }
        let mut file = match open_no_follow(&path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                // A dangling symlink also reports NotFound through O_NOFOLLOW-less
                // platforms; check the link itself.
                return match fs::symlink_metadata(&path) {
                    Err(_) => Ok(DesktopPreferences::default()),
                    Ok(_) => Err(unreadable()),
                };
            }
            Err(_) => return Err(unreadable()),
        };
        let metadata = file.metadata().map_err(|_| unreadable())?;
        if !metadata.file_type().is_file() || metadata.len() > MAX_FILE_SIZE {
            return Err(unreadable());
        }
        let mut bytes = Vec::new();
        Read::by_ref(&mut file)
            .take(MAX_FILE_SIZE + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| unreadable())?;
        let preferences: DesktopPreferences =
            serde_json::from_slice(&bytes).map_err(|_| invalid())?;
        preferences.validate()?;
        Ok(preferences)
    }

    /// Validate, then replace the file atomically in the same directory.
    pub fn write(&self, preferences: &DesktopPreferences) -> Result<(), DesktopError> {
        preferences.validate()?;
        let _guard = self
            .write_lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        let failed = || {
            DesktopError::preferences(
                "preferences_write_failed",
                "The remembered workspace could not be saved.",
            )
        };
        self.prepare_directory().map_err(|_| failed())?;
        let path = self.path();
        if let Ok(metadata) = fs::symlink_metadata(&path) {
            if !metadata.file_type().is_file() {
                return Err(failed());
            }
        }
        let mut bytes = serde_json::to_vec_pretty(preferences).map_err(|_| failed())?;
        bytes.push(b'\n');
        let temporary = self
            .directory
            .join(format!(".{FILE_NAME}.{}.tmp", std::process::id()));
        let result = (|| -> std::io::Result<()> {
            let mut file = create_private(&temporary)?;
            file.write_all(&bytes)?;
            file.sync_all()?;
            drop(file);
            fs::rename(&temporary, &path)?;
            if let Ok(directory) = File::open(&self.directory) {
                let _ = directory.sync_all();
            }
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
            return Err(failed());
        }
        Ok(())
    }

    fn prepare_directory(&self) -> std::io::Result<()> {
        prepare_private_directory(&self.directory)
    }
}

/// Create `directory` if needed and restrict it to this user (0700 on Unix).
pub(crate) fn prepare_private_directory(directory: &Path) -> std::io::Result<()> {
    {
        match fs::symlink_metadata(directory) {
            Ok(metadata) if metadata.file_type().is_dir() => {}
            Ok(_) => return Err(std::io::Error::other("not a directory")),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                let mut builder = fs::DirBuilder::new();
                builder.recursive(true);
                #[cfg(unix)]
                {
                    use std::os::unix::fs::DirBuilderExt;
                    builder.mode(0o700);
                }
                builder.create(directory)?;
            }
            Err(error) => return Err(error),
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(directory, fs::Permissions::from_mode(0o700))?;
        }
        Ok(())
    }
}

pub(crate) fn open_no_follow(path: &Path) -> std::io::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "macos")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        // Do not block if a file is replaced with a FIFO between lstat and open.
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    #[cfg(not(target_os = "macos"))]
    if fs::symlink_metadata(path)?.file_type().is_symlink() {
        return Err(std::io::Error::other("symlink"));
    }
    options.open(path)
}

pub(crate) fn create_private(path: &Path) -> std::io::Result<File> {
    let _ = fs::remove_file(path);
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path)
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;

    /// A unique temporary directory removed on drop, even after a failed assertion.
    pub struct TempDir(pub PathBuf);

    impl TempDir {
        pub fn new(label: &str) -> Self {
            use std::sync::atomic::{AtomicUsize, Ordering};
            static COUNTER: AtomicUsize = AtomicUsize::new(0);
            let path = std::env::temp_dir().join(format!(
                "page-test-{label}-{}-{}",
                std::process::id(),
                COUNTER.fetch_add(1, Ordering::SeqCst)
            ));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }
    }

    impl Drop for TempDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn id(n: u32) -> String {
        format!("{n:08x}-0000-4000-8000-000000000000")
    }

    fn entry(n: u32) -> RecentVault {
        RecentVault {
            vault_id: id(n),
            root_path: format!("/vaults/{n}"),
            last_note_id: Some(id(100 + n)),
        }
    }

    fn sample() -> DesktopPreferences {
        DesktopPreferences {
            version: 1,
            recent_vaults: vec![entry(1), entry(2)],
            active_vault_id: Some(id(1)),
        }
    }

    #[test]
    fn missing_settings_are_defaults() {
        let dir = TempDir::new("prefs-missing");
        let store = PreferencesStore::new(dir.0.join("config"));
        assert_eq!(store.read().unwrap(), DesktopPreferences::default());
    }

    #[test]
    fn round_trip_is_private_and_atomic() {
        let dir = TempDir::new("prefs-roundtrip");
        let store = PreferencesStore::new(dir.0.join("config"));
        store.write(&sample()).unwrap();
        assert_eq!(store.read().unwrap(), sample());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(store.path()).unwrap().permissions().mode() & 0o777,
                0o600
            );
            assert_eq!(
                fs::metadata(dir.0.join("config"))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o700
            );
        }
        let names: Vec<_> = fs::read_dir(dir.0.join("config"))
            .unwrap()
            .map(|e| e.unwrap().file_name())
            .collect();
        assert_eq!(names, vec![std::ffi::OsString::from(FILE_NAME)]);
        let text = fs::read_to_string(store.path()).unwrap();
        assert!(text.ends_with("}\n"));
    }

    #[test]
    fn validation_rejects_bad_versions_types_and_limits() {
        let mut bad = sample();
        bad.version = 2;
        assert_eq!(bad.validate().unwrap_err().code, "preferences_unsupported");
        let mut relative = sample();
        relative.recent_vaults[0].root_path = "vaults/1".into();
        assert!(relative.validate().is_err());
        let mut uuid = sample();
        uuid.active_vault_id = None;
        uuid.recent_vaults[0].vault_id = id(10).to_uppercase();
        assert!(uuid.validate().is_err());
        let mut note = sample();
        note.recent_vaults[0].last_note_id = Some("x".into());
        assert!(note.validate().is_err());
        let mut duplicate_root = sample();
        duplicate_root.recent_vaults[1].root_path = "/vaults/1".into();
        assert!(duplicate_root.validate().is_err());
        let mut duplicate_id = sample();
        duplicate_id.recent_vaults[1].vault_id = id(1);
        assert!(duplicate_id.validate().is_err());
        let mut active = sample();
        active.active_vault_id = Some(id(9));
        assert!(active.validate().is_err());
        let many = DesktopPreferences {
            version: 1,
            recent_vaults: (0..11).map(entry).collect(),
            active_vault_id: None,
        };
        assert!(many.validate().is_err());
        let ten = DesktopPreferences {
            version: 1,
            recent_vaults: (0..10).map(entry).collect(),
            active_vault_id: None,
        };
        assert!(ten.validate().is_ok());
    }

    #[test]
    fn malformed_files_are_reported_and_preserved() {
        let dir = TempDir::new("prefs-malformed");
        let store = PreferencesStore::new(dir.0.clone());
        for text in [
            "not json",
            r#"{"version":1,"recent_vaults":[]}"#,
            r#"{"version":1,"recent_vaults":[{"vault_id":"00000001-0000-4000-8000-000000000000","root_path":"/vaults/1"}],"active_vault_id":null}"#,
            r#"{"version":1,"recent_vaults":[],"active_vault_id":null,"token":"x"}"#,
            r#"{"version":"1","recent_vaults":[],"active_vault_id":null}"#,
            r#"{"version":2,"recent_vaults":[],"active_vault_id":null}"#,
        ] {
            fs::write(store.path(), text).unwrap();
            assert!(store.read().is_err());
            assert_eq!(fs::read_to_string(store.path()).unwrap(), text);
        }
    }

    #[test]
    fn invalid_writes_leave_the_previous_file() {
        let dir = TempDir::new("prefs-invalid-write");
        let store = PreferencesStore::new(dir.0.clone());
        store.write(&sample()).unwrap();
        let mut bad = sample();
        bad.recent_vaults[0].root_path = "relative".into();
        assert!(store.write(&bad).is_err());
        assert_eq!(store.read().unwrap(), sample());
    }

    #[cfg(unix)]
    #[test]
    fn failed_replacement_preserves_the_prior_file() {
        let dir = TempDir::new("prefs-readonly");
        let store = PreferencesStore::new(dir.0.join("config"));
        store.write(&sample()).unwrap();
        let before = fs::read(store.path()).unwrap();
        // A non-file temporary path makes the atomic write fail before rename.
        let temporary = dir
            .0
            .join("config")
            .join(format!(".{FILE_NAME}.{}.tmp", std::process::id()));
        fs::create_dir(&temporary).unwrap();
        fs::write(temporary.join("keep"), b"x").unwrap();
        let mut next = sample();
        next.active_vault_id = Some(id(2));
        assert_eq!(
            store.write(&next).unwrap_err().code,
            "preferences_write_failed"
        );
        assert_eq!(fs::read(store.path()).unwrap(), before);
        assert!(temporary.join("keep").is_file());
    }

    #[cfg(unix)]
    #[test]
    fn symlinks_and_special_files_are_rejected() {
        let dir = TempDir::new("prefs-symlink");
        let real = dir.0.join("real");
        fs::create_dir(&real).unwrap();
        fs::write(real.join(FILE_NAME), serde_json::to_vec(&sample()).unwrap()).unwrap();
        let linked_dir = dir.0.join("linked");
        std::os::unix::fs::symlink(&real, &linked_dir).unwrap();
        let store = PreferencesStore::new(linked_dir);
        assert!(store.read().is_err());
        assert!(store.write(&sample()).is_err());

        let files = dir.0.join("files");
        fs::create_dir(&files).unwrap();
        std::os::unix::fs::symlink(real.join(FILE_NAME), files.join(FILE_NAME)).unwrap();
        let store = PreferencesStore::new(files.clone());
        assert_eq!(store.read().unwrap_err().code, "preferences_unreadable");
        assert!(store.write(&sample()).is_err());
        assert!(
            fs::symlink_metadata(files.join(FILE_NAME))
                .unwrap()
                .file_type()
                .is_symlink()
        );

        let special = dir.0.join("special");
        fs::create_dir_all(special.join(FILE_NAME)).unwrap();
        let store = PreferencesStore::new(special);
        assert!(store.read().is_err());
        assert!(store.write(&sample()).is_err());
    }

    #[test]
    fn serialized_writes_keep_the_last_completed_selection() {
        let dir = TempDir::new("prefs-ordered");
        let store = std::sync::Arc::new(PreferencesStore::new(dir.0.clone()));
        let handles: Vec<_> = (1..=8)
            .map(|n| {
                let store = std::sync::Arc::clone(&store);
                std::thread::spawn(move || {
                    let preferences = DesktopPreferences {
                        version: 1,
                        recent_vaults: vec![entry(n)],
                        active_vault_id: Some(id(n)),
                    };
                    store.write(&preferences).unwrap();
                })
            })
            .collect();
        for handle in handles {
            handle.join().unwrap();
        }
        // Every write completes whole: the result is one valid selection.
        let result = store.read().unwrap();
        assert_eq!(result.recent_vaults.len(), 1);
        assert_eq!(
            result.active_vault_id.as_deref(),
            Some(result.recent_vaults[0].vault_id.as_str())
        );
    }
}
