//! The Gemini API key, kept in the operating system's credential store
//! (macOS Keychain, Windows Credential Manager). It reaches Page Core only
//! through the child's environment at launch, and never the webview, logs
//! or errors.

use std::sync::Mutex;

use serde::Serialize;

use crate::error::DesktopError;

const SERVICE: &str = "com.page.desktop";
const ACCOUNT: &str = "gemini-api-key";
const MAX_KEY_LENGTH: usize = 256;

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct GeminiKeyStatus {
    /// A key is saved in the credential store.
    pub stored: bool,
    /// Page was started with `GEMINI_API_KEY` set, used when nothing is stored.
    pub from_environment: bool,
}

fn store_error() -> DesktopError {
    DesktopError::preferences(
        "credential_store_failed",
        "The system credential store could not be used.",
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

fn entry() -> Result<keyring::Entry, DesktopError> {
    keyring::Entry::new(SERVICE, ACCOUNT).map_err(|_| store_error())
}

/// The key as last read or written in this app run. macOS asks the user before
/// each Keychain read by an app it doesn't fully trust (every debug rebuild), so
/// the Keychain is read at most once per run; saving and removing update it.
static CACHE: Mutex<Option<Option<String>>> = Mutex::new(None);

fn load_from_keychain() -> Result<Option<String>, DesktopError> {
    match entry()?.get_password() {
        Ok(key) => Ok(Some(key)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(_) => Err(store_error()),
    }
}

/// Returns the cached value, or loads it once. A failed load isn't cached.
fn cached_read(
    cache: &Mutex<Option<Option<String>>>,
    load: impl FnOnce() -> Result<Option<String>, DesktopError>,
) -> Result<Option<String>, DesktopError> {
    let mut cached = cache
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    if let Some(value) = cached.as_ref() {
        return Ok(value.clone());
    }
    let value = load()?;
    *cached = Some(value.clone());
    Ok(value)
}

fn remember(value: Option<String>) {
    *CACHE
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(value);
}

pub fn read_key() -> Result<Option<String>, DesktopError> {
    cached_read(&CACHE, load_from_keychain)
}

pub fn save_key(key: &str) -> Result<(), DesktopError> {
    let key = validate_key(key)?;
    entry()?.set_password(key).map_err(|_| store_error())?;
    remember(Some(key.to_owned()));
    Ok(())
}

pub fn clear_key() -> Result<(), DesktopError> {
    match entry()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => {
            remember(None);
            Ok(())
        }
        Err(_) => Err(store_error()),
    }
}

pub fn status() -> Result<GeminiKeyStatus, DesktopError> {
    Ok(GeminiKeyStatus {
        stored: read_key()?.is_some(),
        from_environment: std::env::var_os("GEMINI_API_KEY").is_some_and(|value| !value.is_empty()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn the_keychain_is_read_once_and_failures_are_retried() {
        let cache = Mutex::new(None);
        let mut loads = 0;
        let failed = cached_read(&cache, || {
            loads += 1;
            Err(store_error())
        });
        assert!(failed.is_err());
        for _ in 0..3 {
            let value = cached_read(&cache, || {
                loads += 1;
                Ok(Some("key".to_owned()))
            });
            assert_eq!(value.unwrap().as_deref(), Some("key"));
        }
        assert_eq!(loads, 2);
        let empty = Mutex::new(None);
        assert_eq!(cached_read(&empty, || Ok(None)).unwrap(), None);
        assert_eq!(cached_read(&empty, || panic!("read again")).unwrap(), None);
    }
}
