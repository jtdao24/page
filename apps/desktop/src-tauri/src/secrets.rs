//! The Gemini API key, kept in the operating system's credential store
//! (macOS Keychain, Windows Credential Manager). It reaches Page Core only
//! through the child's environment at launch, and never the webview, logs
//! or errors.

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

pub fn read_key() -> Result<Option<String>, DesktopError> {
    match entry()?.get_password() {
        Ok(key) => Ok(Some(key)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(_) => Err(store_error()),
    }
}

pub fn save_key(key: &str) -> Result<(), DesktopError> {
    let key = validate_key(key)?;
    entry()?.set_password(key).map_err(|_| store_error())
}

pub fn clear_key() -> Result<(), DesktopError> {
    match entry()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
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
}
