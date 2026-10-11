//! The Gemini API key, kept in a private file in Page's settings folder (the
//! folder is 0700 and the file 0600 on Unix). It reaches Page Core only through
//! the child's environment at launch, and never the webview, logs or errors.
//!
//! The macOS Keychain was used before, but it asks the user for permission on
//! every read by an app it doesn't fully trust, which includes every rebuild.

use std::fs;
use std::io::{Read, Write};
use std::path::PathBuf;
use std::sync::Mutex;

use serde::Serialize;

use crate::error::DesktopError;
use crate::preferences::{create_private, open_no_follow, prepare_private_directory};

const FILE_NAME: &str = "gemini-api-key";
const MAX_KEY_LENGTH: usize = 256;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct GeminiKeyStatus {
    /// A key is saved in Page's settings.
    pub stored: bool,
    /// Page was started with `GEMINI_API_KEY` set, used when nothing is stored.
    pub from_environment: bool,
}

fn store_error() -> DesktopError {
    DesktopError::preferences(
        "key_store_failed",
        "Page could not read or save the Gemini key in its settings folder.",
    )
}

/// A plausible API key: one token of printable ASCII, no spaces.
pub fn validate_key(key: &str) -> Result<&str, DesktopError> {
    let key = key.trim();
    if key.is_empty()
        || key.len() > MAX_KEY_LENGTH
        || !key.bytes().all(|byte| byte.is_ascii_graphic())
    {
        return Err(DesktopError::preferences(
            "invalid_api_key",
            "Paste the API key exactly as Google AI Studio shows it.",
        ));
    }
    Ok(key)
}

pub struct KeyStore {
    directory: PathBuf,
    write_lock: Mutex<()>,
}

impl KeyStore {
    pub fn new(directory: PathBuf) -> Self {
        Self {
            directory,
            write_lock: Mutex::new(()),
        }
    }

    fn path(&self) -> PathBuf {
        self.directory.join(FILE_NAME)
    }

    pub fn read(&self) -> Result<Option<String>, DesktopError> {
        let file = match open_no_follow(&self.path()) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err(store_error()),
        };
        let metadata = file.metadata().map_err(|_| store_error())?;
        if !metadata.is_file() {
            return Err(store_error());
        }
        // If the file was made readable by others, make it private again before use.
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if metadata.permissions().mode() & 0o077 != 0 {
                file.set_permissions(fs::Permissions::from_mode(0o600))
                    .map_err(|_| store_error())?;
            }
        }
        let mut text = String::new();
        file.take(MAX_KEY_LENGTH as u64 + 2)
            .read_to_string(&mut text)
            .map_err(|_| store_error())?;
        validate_key(&text).map(|key| Some(key.to_owned()))
    }

    /// Replace the key atomically in the same private folder.
    pub fn save(&self, key: &str) -> Result<(), DesktopError> {
        let key = validate_key(key)?;
        let _guard = self
            .write_lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        prepare_private_directory(&self.directory).map_err(|_| store_error())?;
        let temporary = self
            .directory
            .join(format!(".{FILE_NAME}.{}.tmp", std::process::id()));
        let result = (|| -> std::io::Result<()> {
            let mut file = create_private(&temporary)?;
            file.write_all(format!("{key}\n").as_bytes())?;
            file.sync_all()?;
            drop(file);
            fs::rename(&temporary, self.path())
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
            return Err(store_error());
        }
        Ok(())
    }

    pub fn clear(&self) -> Result<(), DesktopError> {
        let _guard = self
            .write_lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        match fs::remove_file(self.path()) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(_) => Err(store_error()),
        }
    }

    pub fn status(&self) -> Result<GeminiKeyStatus, DesktopError> {
        Ok(GeminiKeyStatus {
            stored: self.read()?.is_some(),
            from_environment: std::env::var_os("GEMINI_API_KEY")
                .is_some_and(|value| !value.is_empty()),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::preferences::tests::TempDir;

    #[test]
    fn keys_are_validated_without_echoing_them() {
        assert_eq!(
            validate_key("  AIzaSy-abc_123  ").unwrap(),
            "AIzaSy-abc_123"
        );
        for bad in [
            "",
            "   ",
            "two words",
            "tab\tkey",
            "naïve",
            &"k".repeat(257),
        ] {
            let error = validate_key(bad).unwrap_err();
            assert_eq!(error.code, "invalid_api_key");
            assert!(bad.trim().is_empty() || !error.message.contains(bad.trim()));
        }
        assert!(validate_key(&"k".repeat(256)).is_ok());
    }

    #[test]
    fn the_key_is_saved_privately_read_back_and_cleared() {
        let temp = TempDir::new("keys");
        let store = KeyStore::new(temp.0.join("settings"));
        assert_eq!(store.read().unwrap(), None);
        assert!(!store.status().unwrap().stored);
        store.save("  AIza-first  ").unwrap();
        store.save("AIza-second").unwrap();
        assert_eq!(store.read().unwrap().as_deref(), Some("AIza-second"));
        assert!(store.status().unwrap().stored);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode =
                |path: &std::path::Path| fs::metadata(path).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode(&temp.0.join("settings")), 0o700);
            assert_eq!(mode(&store.path()), 0o600);
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(store.path(), fs::Permissions::from_mode(0o644)).unwrap();
            assert_eq!(store.read().unwrap().as_deref(), Some("AIza-second"));
            assert_eq!(
                fs::metadata(store.path()).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
        assert!(store.save("not valid").is_err());
        assert_eq!(store.read().unwrap().as_deref(), Some("AIza-second"));
        store.clear().unwrap();
        store.clear().unwrap();
        assert_eq!(store.read().unwrap(), None);
    }

    #[test]
    fn a_tampered_key_file_is_rejected() {
        let temp = TempDir::new("keys-bad");
        let store = KeyStore::new(temp.0.clone());
        fs::write(store.path(), "two words\n").unwrap();
        assert_eq!(store.read().unwrap_err().code, "invalid_api_key");
        fs::remove_file(store.path()).unwrap();
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(temp.0.join("elsewhere"), store.path()).unwrap();
            fs::write(temp.0.join("elsewhere"), "AIza-linked").unwrap();
            assert_eq!(store.read().unwrap_err().code, "key_store_failed");
        }
    }
}
