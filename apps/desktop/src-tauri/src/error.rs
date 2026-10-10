use serde::Serialize;
use serde_json::{Map, Value};

/// Which layer produced a desktop failure.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ErrorKind {
    /// A valid Page Core error envelope.
    Api,
    /// The request could not be completed over loopback HTTP.
    Transport,
    /// Page Core answered with something that violates the API contract.
    Protocol,
    /// The backend process is unavailable or failed to start.
    Backend,
    /// Desktop preferences could not be read, validated or written.
    Preferences,
}

/// The serializable error returned by every desktop command.
///
/// Messages are fixed, safe text. Raw response bodies, child output, tokens
/// and note content never appear here.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct DesktopError {
    pub kind: ErrorKind,
    pub status: Option<u16>,
    pub code: String,
    pub message: String,
    pub details: Option<Map<String, Value>>,
}

/// Code for a mutation that may have reached Page Core but whose result is
/// unknown: storage may or may not have changed.
pub const OUTCOME_UNKNOWN: &str = "mutation_outcome_unknown";

impl DesktopError {
    pub fn new(kind: ErrorKind, code: &str, message: impl Into<String>) -> Self {
        Self {
            kind,
            status: None,
            code: code.to_owned(),
            message: message.into(),
            details: None,
        }
    }

    pub fn backend(code: &str, message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Backend, code, message)
    }

    pub fn protocol(code: &str, message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Protocol, code, message)
    }

    pub fn transport(code: &str, message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Transport, code, message)
    }

    pub fn preferences(code: &str, message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Preferences, code, message)
    }

    pub fn with_status(mut self, status: u16) -> Self {
        self.status = Some(status);
        self
    }

    pub fn is_outcome_unknown(&self) -> bool {
        self.code == OUTCOME_UNKNOWN
    }
}

impl std::fmt::Display for DesktopError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for DesktopError {}

/// A canonical lowercase hyphenated UUID, as Page Core produces and accepts.
pub fn is_canonical_uuid(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 36
        && bytes.iter().enumerate().all(|(index, byte)| match index {
            8 | 13 | 18 | 23 => *byte == b'-',
            _ => byte.is_ascii_digit() || (b'a'..=b'f').contains(byte),
        })
}

/// A note revision: 64 lowercase hexadecimal characters.
pub fn is_revision(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_uuids_only() {
        assert!(is_canonical_uuid("123e4567-e89b-42d3-a456-426614174000"));
        assert!(!is_canonical_uuid("123E4567-E89B-42D3-A456-426614174000"));
        assert!(!is_canonical_uuid("123e4567e89b42d3a456426614174000"));
        assert!(!is_canonical_uuid("{123e4567-e89b-42d3-a456-426614174000}"));
        assert!(!is_canonical_uuid("../../vaults/aaaaaaaaaaaaaaaaaaaaaaaa"));
        assert!(!is_canonical_uuid(""));
    }

    #[test]
    fn revisions_are_lowercase_sha256_hex() {
        assert!(is_revision(&"a1".repeat(32)));
        assert!(!is_revision(&"A1".repeat(32)));
        assert!(!is_revision(&"a".repeat(63)));
        assert!(!is_revision(&format!("\"{}\"", "a".repeat(62))));
    }

    #[test]
    fn errors_serialize_with_stable_shape() {
        let error = DesktopError::transport(OUTCOME_UNKNOWN, "unknown").with_status(503);
        let value = serde_json::to_value(&error).unwrap();
        assert_eq!(
            value,
            serde_json::json!({
                "kind": "transport", "status": 503, "code": OUTCOME_UNKNOWN,
                "message": "unknown", "details": null
            })
        );
    }
}
