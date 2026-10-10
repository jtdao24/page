//! Fixed, authenticated HTTP client for the Page Core loopback API.
//!
//! `CoreApiClient` only builds URLs from the validated `127.0.0.1` port and
//! the endpoint table below. It is a blocking client: construct, use and drop
//! it on ordinary worker threads, never directly inside an async runtime.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::time::Duration;

use reqwest::blocking::Client;
use reqwest::header::{AUTHORIZATION, CONTENT_TYPE, ETAG, HeaderValue, IF_MATCH};
use reqwest::{Method, redirect, retry};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::error::{DesktopError, ErrorKind, OUTCOME_UNKNOWN, is_canonical_uuid, is_revision};

pub const HOST: &str = "127.0.0.1";
const PREFIX: &str = "/api/v1";
const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HealthResponse {
    pub status: String,
    pub version: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct VaultResponse {
    pub id: String,
    pub name: String,
    pub root_path: String,
    pub needs_reconciliation: bool,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NoteSummaryResponse {
    pub id: String,
    pub vault_id: String,
    pub relative_path: String,
    pub created_at: String,
    pub updated_at: String,
    pub revision: String,
}

#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NoteResponse {
    pub id: String,
    pub vault_id: String,
    pub relative_path: String,
    pub created_at: String,
    pub updated_at: String,
    pub revision: String,
    pub content: String,
}

impl fmt::Debug for NoteResponse {
    // Note content stays out of Debug output.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("NoteResponse")
            .field("id", &self.id)
            .field("vault_id", &self.vault_id)
            .field("revision", &self.revision)
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReconcileResponse {
    pub added: u64,
    pub modified: u64,
    pub renamed: u64,
    pub missing: u64,
    pub unchanged: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GraphNodeResponse {
    pub id: String,
    pub relative_path: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GraphLinkResponse {
    pub source_note_id: String,
    pub target_reference: String,
    #[serde(deserialize_with = "Option::deserialize")]
    pub target_note_id: Option<String>,
    #[serde(deserialize_with = "Option::deserialize")]
    pub alias: Option<String>,
    pub line: u64,
    #[serde(deserialize_with = "Option::deserialize")]
    pub unresolved_reason: Option<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GraphResponse {
    pub vault_id: String,
    pub nodes: Vec<GraphNodeResponse>,
    pub links: Vec<GraphLinkResponse>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ErrorEnvelope {
    error: ErrorBody,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ErrorBody {
    code: String,
    message: String,
    #[serde(deserialize_with = "Option::deserialize")]
    details: Option<Map<String, Value>>,
}

#[derive(Serialize)]
struct CreateVaultRequest<'a> {
    root_path: &'a str,
    name: &'a str,
}

#[derive(Serialize)]
struct OpenVaultRequest<'a> {
    root_path: &'a str,
}

#[derive(Serialize)]
struct ReconcileRequest<'a> {
    known_renames: &'a BTreeMap<String, String>,
}

#[derive(Serialize)]
struct CreateNoteRequest<'a> {
    relative_path: &'a str,
    content: &'a str,
}

#[derive(Serialize)]
struct UpdateNoteRequest<'a> {
    content: &'a str,
}

#[derive(Serialize)]
struct MoveNoteRequest<'a> {
    relative_path: &'a str,
}

struct Reply {
    etags: Vec<HeaderValue>,
    body: Vec<u8>,
}

/// Whether a request can change storage; decides how failures are reported.
#[derive(Clone, Copy, PartialEq, Eq)]
enum Effect {
    Read,
    Mutation,
}

pub struct CoreApiClient {
    http: Client,
    base: String,
    port: u16,
    authorization: HeaderValue,
}

impl fmt::Debug for CoreApiClient {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("CoreApiClient { .. }")
    }
}

/// Accept only a token shaped like `secrets.token_urlsafe(32)`.
pub fn is_token(value: &str) -> bool {
    value.len() == 43
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}

impl CoreApiClient {
    /// Build a client for `127.0.0.1:port` with a validated token.
    pub fn new(port: u16, token: &str) -> Result<Self, DesktopError> {
        if port == 0 || !is_token(token) {
            return Err(DesktopError::backend(
                "invalid_bootstrap",
                "Page Core reported an invalid endpoint.",
            ));
        }
        let mut authorization =
            HeaderValue::from_str(&format!("Bearer {token}")).map_err(|_| {
                DesktopError::backend(
                    "invalid_bootstrap",
                    "Page Core reported an invalid endpoint.",
                )
            })?;
        authorization.set_sensitive(true);
        let http = Client::builder()
            .no_proxy()
            .redirect(redirect::Policy::none())
            .retry(retry::never())
            .referer(false)
            // A fresh connection per request: no idle-connection reuse, so
            // the client never resends a request on a stale connection.
            .pool_max_idle_per_host(0)
            .connect_timeout(CONNECT_TIMEOUT)
            .timeout(REQUEST_TIMEOUT)
            .connection_verbose(false)
            .build()
            .map_err(|_| {
                DesktopError::backend(
                    "client_unavailable",
                    "The HTTP client could not be created.",
                )
            })?;
        Ok(Self {
            http,
            base: format!("http://{HOST}:{port}{PREFIX}"),
            port,
            authorization,
        })
    }

    /// The loopback port, for Rust-side diagnostics and tests only; it is
    /// never sent to the frontend.
    pub fn port(&self) -> u16 {
        self.port
    }

    pub fn health(&self, timeout: Duration) -> Result<HealthResponse, DesktopError> {
        let reply = self.send(
            Method::GET,
            "/health",
            None,
            None,
            Some(timeout),
            Effect::Read,
            200,
        )?;
        let health: HealthResponse = decode(&reply.body, Effect::Read)?;
        if health.status != "ok" || self.contains_credential(health.version.as_bytes()) {
            return Err(invalid_response(Effect::Read));
        }
        Ok(health)
    }

    pub fn create_vault(&self, root_path: &str, name: &str) -> Result<VaultResponse, DesktopError> {
        let body = json(&CreateVaultRequest { root_path, name })?;
        let reply = self.send(
            Method::POST,
            "/vaults",
            Some(body),
            None,
            None,
            Effect::Mutation,
            201,
        )?;
        vault(decode(&reply.body, Effect::Mutation)?, Effect::Mutation)
    }

    pub fn open_vault(&self, root_path: &str) -> Result<VaultResponse, DesktopError> {
        let body = json(&OpenVaultRequest { root_path })?;
        let reply = self.send(
            Method::POST,
            "/vaults/open",
            Some(body),
            None,
            None,
            Effect::Mutation,
            200,
        )?;
        vault(decode(&reply.body, Effect::Mutation)?, Effect::Mutation)
    }

    pub fn list_vaults(&self) -> Result<Vec<VaultResponse>, DesktopError> {
        let reply = self.send(Method::GET, "/vaults", None, None, None, Effect::Read, 200)?;
        let vaults: Vec<VaultResponse> = decode(&reply.body, Effect::Read)?;
        vaults
            .into_iter()
            .map(|item| vault(item, Effect::Read))
            .collect()
    }

    pub fn get_vault(&self, vault_id: &str) -> Result<VaultResponse, DesktopError> {
        let route = format!("/vaults/{}", uuid(vault_id)?);
        let reply = self.send(Method::GET, &route, None, None, None, Effect::Read, 200)?;
        let result = vault(decode(&reply.body, Effect::Read)?, Effect::Read)?;
        if result.id != vault_id {
            return Err(invalid_response(Effect::Read));
        }
        Ok(result)
    }

    pub fn close_vault(&self, vault_id: &str) -> Result<(), DesktopError> {
        let route = format!("/vaults/{}", uuid(vault_id)?);
        let reply = self.send(
            Method::DELETE,
            &route,
            None,
            None,
            None,
            Effect::Mutation,
            204,
        )?;
        empty(&reply, Effect::Mutation)
    }

    pub fn reconcile(
        &self,
        vault_id: &str,
        known_renames: &BTreeMap<String, String>,
    ) -> Result<ReconcileResponse, DesktopError> {
        let route = format!("/vaults/{}/reconcile", uuid(vault_id)?);
        for note_id in known_renames.keys() {
            uuid(note_id)?;
        }
        let body = json(&ReconcileRequest { known_renames })?;
        let reply = self.send(
            Method::POST,
            &route,
            Some(body),
            None,
            None,
            Effect::Mutation,
            200,
        )?;
        decode(&reply.body, Effect::Mutation)
    }

    pub fn list_notes(&self, vault_id: &str) -> Result<Vec<NoteSummaryResponse>, DesktopError> {
        let route = format!("/vaults/{}/notes", uuid(vault_id)?);
        let reply = self.send(Method::GET, &route, None, None, None, Effect::Read, 200)?;
        let notes: Vec<NoteSummaryResponse> = decode(&reply.body, Effect::Read)?;
        for note in &notes {
            if !is_canonical_uuid(&note.id)
                || note.vault_id != vault_id
                || !is_revision(&note.revision)
            {
                return Err(invalid_response(Effect::Read));
            }
        }
        Ok(notes)
    }

    pub fn read_graph(&self, vault_id: &str) -> Result<GraphResponse, DesktopError> {
        let route = format!("/vaults/{}/graph", uuid(vault_id)?);
        let reply = self.send(Method::GET, &route, None, None, None, Effect::Read, 200)?;
        let graph: GraphResponse = decode(&reply.body, Effect::Read)?;
        let ids: BTreeSet<&str> = graph.nodes.iter().map(|node| node.id.as_str()).collect();
        if graph.vault_id != vault_id
            || ids.len() != graph.nodes.len()
            || graph
                .nodes
                .iter()
                .any(|node| !is_canonical_uuid(&node.id) || node.relative_path.is_empty())
            || graph.links.iter().any(|edge| {
                !ids.contains(edge.source_note_id.as_str())
                    || edge.line == 0
                    || edge.target_reference.trim().is_empty()
                    || match (&edge.target_note_id, &edge.unresolved_reason) {
                        (Some(id), None) => !ids.contains(id.as_str()),
                        (None, Some(reason)) => {
                            !["missing", "ambiguous", "invalid"].contains(&reason.as_str())
                        }
                        _ => true,
                    }
            })
        {
            return Err(invalid_response(Effect::Read));
        }
        Ok(graph)
    }

    pub fn read_note(&self, vault_id: &str, note_id: &str) -> Result<NoteResponse, DesktopError> {
        let route = format!("/vaults/{}/notes/{}", uuid(vault_id)?, uuid(note_id)?);
        let reply = self.send(Method::GET, &route, None, None, None, Effect::Read, 200)?;
        full_note(&reply, vault_id, Some(note_id), Effect::Read)
    }

    pub fn create_note(
        &self,
        vault_id: &str,
        relative_path: &str,
        content: &str,
    ) -> Result<NoteResponse, DesktopError> {
        let route = format!("/vaults/{}/notes", uuid(vault_id)?);
        let body = json(&CreateNoteRequest {
            relative_path,
            content,
        })?;
        let reply = self.send(
            Method::POST,
            &route,
            Some(body),
            None,
            None,
            Effect::Mutation,
            201,
        )?;
        full_note(&reply, vault_id, None, Effect::Mutation)
    }

    pub fn update_note(
        &self,
        vault_id: &str,
        note_id: &str,
        revision: &str,
        content: &str,
    ) -> Result<NoteResponse, DesktopError> {
        let route = format!("/vaults/{}/notes/{}", uuid(vault_id)?, uuid(note_id)?);
        let precondition = if_match(revision)?;
        let body = json(&UpdateNoteRequest { content })?;
        let reply = self.send(
            Method::PUT,
            &route,
            Some(body),
            Some(precondition),
            None,
            Effect::Mutation,
            200,
        )?;
        full_note(&reply, vault_id, Some(note_id), Effect::Mutation)
    }

    pub fn move_note(
        &self,
        vault_id: &str,
        note_id: &str,
        revision: &str,
        relative_path: &str,
    ) -> Result<NoteResponse, DesktopError> {
        let route = format!("/vaults/{}/notes/{}/move", uuid(vault_id)?, uuid(note_id)?);
        let precondition = if_match(revision)?;
        let body = json(&MoveNoteRequest { relative_path })?;
        let reply = self.send(
            Method::POST,
            &route,
            Some(body),
            Some(precondition),
            None,
            Effect::Mutation,
            200,
        )?;
        full_note(&reply, vault_id, Some(note_id), Effect::Mutation)
    }

    pub fn delete_note(
        &self,
        vault_id: &str,
        note_id: &str,
        revision: &str,
    ) -> Result<(), DesktopError> {
        let route = format!("/vaults/{}/notes/{}", uuid(vault_id)?, uuid(note_id)?);
        let precondition = if_match(revision)?;
        let reply = self.send(
            Method::DELETE,
            &route,
            None,
            Some(precondition),
            None,
            Effect::Mutation,
            204,
        )?;
        empty(&reply, Effect::Mutation)
    }

    #[allow(clippy::too_many_arguments)]
    fn send(
        &self,
        method: Method,
        route: &str,
        body: Option<Vec<u8>>,
        if_match: Option<HeaderValue>,
        timeout: Option<Duration>,
        effect: Effect,
        expected: u16,
    ) -> Result<Reply, DesktopError> {
        let mut request = self
            .http
            .request(method, format!("{}{route}", self.base))
            .header(AUTHORIZATION, self.authorization.clone());
        if let Some(value) = if_match {
            request = request.header(IF_MATCH, value);
        }
        if let Some(bytes) = body {
            request = request
                .header(CONTENT_TYPE, HeaderValue::from_static("application/json"))
                .body(bytes);
        }
        if let Some(limit) = timeout {
            request = request.timeout(limit);
        }
        let response = request
            .send()
            .map_err(|error| transport_error(&error, effect))?;
        let status = response.status().as_u16();
        let etags: Vec<HeaderValue> = response.headers().get_all(ETAG).iter().cloned().collect();
        let body = response
            .bytes()
            .map_err(|error| transport_error(&error, effect))?
            .to_vec();
        if status == expected {
            return Ok(Reply { etags, body });
        }
        if (400..600).contains(&status) {
            if self.contains_credential(&body) {
                return Err(invalid_response(effect).with_status(status));
            }
            return Err(api_error(status, &body, effect));
        }
        Err(invalid_response(effect).with_status(status))
    }

    fn contains_credential(&self, bytes: &[u8]) -> bool {
        let token = &self.authorization.as_bytes()[b"Bearer ".len()..];
        bytes.windows(token.len()).any(|window| window == token)
    }
}

fn json<T: Serialize>(value: &T) -> Result<Vec<u8>, DesktopError> {
    serde_json::to_vec(value)
        .map_err(|_| DesktopError::protocol("invalid_request", "The request could not be encoded."))
}

fn uuid(value: &str) -> Result<&str, DesktopError> {
    if is_canonical_uuid(value) {
        Ok(value)
    } else {
        Err(DesktopError::protocol(
            "invalid_identifier",
            "Expected a canonical lowercase UUID.",
        ))
    }
}

fn if_match(revision: &str) -> Result<HeaderValue, DesktopError> {
    if !is_revision(revision) {
        return Err(DesktopError::protocol(
            "invalid_revision",
            "Expected a note revision.",
        ));
    }
    HeaderValue::from_str(&format!("\"{revision}\""))
        .map_err(|_| DesktopError::protocol("invalid_revision", "Expected a note revision."))
}

fn decode<T: DeserializeOwned>(body: &[u8], effect: Effect) -> Result<T, DesktopError> {
    serde_json::from_slice(body).map_err(|_| invalid_response(effect))
}

fn invalid_response(effect: Effect) -> DesktopError {
    match effect {
        Effect::Read => DesktopError::protocol(
            "invalid_response",
            "Page Core returned an invalid response.",
        ),
        Effect::Mutation => DesktopError::protocol(
            OUTCOME_UNKNOWN,
            "Page Core returned an invalid response; the change may or may not have been saved.",
        ),
    }
}

fn transport_error(error: &reqwest::Error, effect: Effect) -> DesktopError {
    if error.is_connect() {
        // Nothing was sent: storage cannot have changed.
        return DesktopError::transport("backend_unreachable", "Page Core could not be reached.");
    }
    match (effect, error.is_timeout()) {
        (Effect::Mutation, _) => DesktopError::transport(
            OUTCOME_UNKNOWN,
            "The connection to Page Core failed; the change may or may not have been saved.",
        ),
        (Effect::Read, true) => {
            DesktopError::transport("request_timeout", "Page Core did not answer in time.")
        }
        (Effect::Read, false) => {
            DesktopError::transport("transport_failed", "The connection to Page Core failed.")
        }
    }
}

fn is_error_code(code: &str) -> bool {
    !code.is_empty()
        && code.len() <= 64
        && code
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte == b'_')
}

fn api_error(status: u16, body: &[u8], effect: Effect) -> DesktopError {
    let Ok(ErrorEnvelope { error }) = serde_json::from_slice::<ErrorEnvelope>(body) else {
        return invalid_response(effect).with_status(status);
    };
    if !is_error_code(&error.code)
        || error.message.len() > 500
        || error.message.chars().any(char::is_control)
    {
        return invalid_response(effect).with_status(status);
    }
    DesktopError {
        kind: ErrorKind::Api,
        status: Some(status),
        code: error.code,
        message: error.message,
        details: error.details,
    }
}

fn vault(value: VaultResponse, effect: Effect) -> Result<VaultResponse, DesktopError> {
    if is_canonical_uuid(&value.id) && !value.root_path.is_empty() {
        Ok(value)
    } else {
        Err(invalid_response(effect))
    }
}

fn empty(reply: &Reply, effect: Effect) -> Result<(), DesktopError> {
    if reply.body.is_empty() {
        Ok(())
    } else {
        Err(invalid_response(effect))
    }
}

fn full_note(
    reply: &Reply,
    vault_id: &str,
    note_id: Option<&str>,
    effect: Effect,
) -> Result<NoteResponse, DesktopError> {
    let note: NoteResponse = decode(&reply.body, effect)?;
    let valid = is_canonical_uuid(&note.id)
        && note.vault_id == vault_id
        && note_id.is_none_or(|expected| note.id == expected)
        && is_revision(&note.revision)
        && reply.etags.len() == 1
        && reply.etags[0].as_bytes() == format!("\"{}\"", note.revision).as_bytes();
    if valid {
        Ok(note)
    } else {
        Err(invalid_response(effect))
    }
}

#[cfg(test)]
pub(crate) mod test_server {
    //! A minimal HTTP/1.1 server that records raw requests and replays
    //! scripted responses, one per connection.

    use std::io::{BufRead, BufReader, Read, Write};
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex};
    use std::thread::JoinHandle;

    #[derive(Clone, Debug)]
    pub struct Recorded {
        pub method: String,
        pub path: String,
        pub headers: Vec<(String, String)>,
        pub body: Vec<u8>,
    }

    impl Recorded {
        pub fn header(&self, name: &str) -> Vec<&str> {
            self.headers
                .iter()
                .filter(|(key, _)| key.eq_ignore_ascii_case(name))
                .map(|(_, value)| value.as_str())
                .collect()
        }

        pub fn json(&self) -> serde_json::Value {
            serde_json::from_slice(&self.body).unwrap()
        }
    }

    pub enum Script {
        /// A complete raw response.
        Respond(String),
        /// Read the request, then close without answering.
        Drop,
    }

    pub struct TestServer {
        pub port: u16,
        pub requests: Arc<Mutex<Vec<Recorded>>>,
        handle: Option<JoinHandle<()>>,
    }

    pub fn response(status: &str, headers: &[(&str, &str)], body: &str) -> Script {
        let mut text = format!(
            "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n",
            body.len()
        );
        for (name, value) in headers {
            text.push_str(&format!("{name}: {value}\r\n"));
        }
        text.push_str("\r\n");
        text.push_str(body);
        Script::Respond(text)
    }

    pub fn json_response(status: &str, body: &serde_json::Value) -> Script {
        response(
            status,
            &[("Content-Type", "application/json")],
            &body.to_string(),
        )
    }

    impl TestServer {
        pub fn start(scripts: Vec<Script>) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let port = listener.local_addr().unwrap().port();
            let requests = Arc::new(Mutex::new(Vec::new()));
            let recorded = Arc::clone(&requests);
            let handle = std::thread::spawn(move || {
                for script in scripts {
                    let Ok((stream, _)) = listener.accept() else {
                        return;
                    };
                    let mut reader = BufReader::new(stream.try_clone().unwrap());
                    let mut line = String::new();
                    if reader.read_line(&mut line).unwrap_or(0) == 0 {
                        // An empty connection, such as the one from finish().
                        continue;
                    }
                    let mut parts = line.split_whitespace();
                    let method = parts.next().unwrap_or_default().to_owned();
                    let path = parts.next().unwrap_or_default().to_owned();
                    let mut headers = Vec::new();
                    loop {
                        let mut header = String::new();
                        reader.read_line(&mut header).unwrap();
                        let header = header.trim_end();
                        if header.is_empty() {
                            break;
                        }
                        let (name, value) = header.split_once(':').unwrap();
                        headers.push((name.to_owned(), value.trim().to_owned()));
                    }
                    let length = headers
                        .iter()
                        .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
                        .map(|(_, value)| value.parse::<usize>().unwrap())
                        .unwrap_or(0);
                    let mut body = vec![0; length];
                    reader.read_exact(&mut body).unwrap();
                    recorded.lock().unwrap().push(Recorded {
                        method,
                        path,
                        headers,
                        body,
                    });
                    let mut stream = stream;
                    if let Script::Respond(text) = script {
                        let _ = stream.write_all(text.as_bytes());
                    }
                    let _ = stream.shutdown(std::net::Shutdown::Both);
                }
            });
            Self {
                port,
                requests,
                handle: Some(handle),
            }
        }

        pub fn finish(mut self) -> Vec<Recorded> {
            // Unblock a pending accept if the script was not consumed.
            let _ = std::net::TcpStream::connect(("127.0.0.1", self.port));
            if let Some(handle) = self.handle.take() {
                let _ = handle.join();
            }
            self.requests.lock().unwrap().clone()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::test_server::{Script, TestServer, json_response, response};
    use super::*;
    use serde_json::json;

    const TOKEN: &str = "PageTestToken_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
    const VAULT: &str = "11111111-1111-4111-8111-111111111111";
    const NOTE: &str = "22222222-2222-4222-8222-222222222222";

    fn revision() -> String {
        "ab".repeat(32)
    }

    fn note_json(content: &str) -> Value {
        json!({
            "id": NOTE, "vault_id": VAULT, "relative_path": "ideas/first.md",
            "created_at": "2026-01-01T00:00:00.000000+00:00",
            "updated_at": "2026-01-01T00:00:00.000000+00:00",
            "revision": revision(), "content": content,
        })
    }

    fn note_reply(status: &str, content: &str) -> Script {
        let etag = format!("\"{}\"", revision());
        response(
            status,
            &[("Content-Type", "application/json"), ("ETag", &etag)],
            &note_json(content).to_string(),
        )
    }

    fn vault_json() -> Value {
        json!({"id": VAULT, "name": "Notes", "root_path": "/tmp/notes", "needs_reconciliation": false})
    }

    fn with_server<T>(
        scripts: Vec<Script>,
        call: impl FnOnce(&CoreApiClient) -> T,
    ) -> (T, Vec<test_server::Recorded>) {
        let server = TestServer::start(scripts);
        let client = CoreApiClient::new(server.port, TOKEN).unwrap();
        let result = call(&client);
        drop(client);
        (result, server.finish())
    }

    fn assert_common(request: &test_server::Recorded, method: &str, path: &str) {
        assert_eq!(request.method, method);
        assert_eq!(request.path, path);
        assert_eq!(
            request.header("authorization"),
            vec![format!("Bearer {TOKEN}").as_str()]
        );
        assert!(request.header("origin").is_empty());
        assert!(request.header("cookie").is_empty());
        assert!(request.header("referer").is_empty());
    }

    #[test]
    fn rejects_invalid_endpoint_material() {
        assert!(CoreApiClient::new(0, TOKEN).is_err());
        assert!(CoreApiClient::new(8765, "short").is_err());
        assert!(CoreApiClient::new(8765, &format!("{}!", &TOKEN[..42])).is_err());
        let client = CoreApiClient::new(8765, TOKEN).unwrap();
        assert!(!format!("{client:?}").contains(TOKEN));
    }

    #[test]
    fn graph_reads_validate_topology_and_use_fixed_authenticated_route() {
        let valid = json!({"vault_id": VAULT, "nodes": [{"id": NOTE, "relative_path": "a.md"}],
            "links": [{"source_note_id": NOTE, "target_reference": "a", "target_note_id": NOTE,
                "alias": null, "line": 1, "unresolved_reason": null}]});
        let mut dangling = valid.clone();
        dangling["links"][0]["target_note_id"] = json!(VAULT);
        let mut malformed = valid.clone();
        malformed["links"][0]
            .as_object_mut()
            .unwrap()
            .remove("alias");
        let mut foreign = valid.clone();
        foreign["vault_id"] = json!(NOTE);
        let (results, requests) = with_server(
            vec![valid, dangling, malformed, foreign]
                .iter()
                .map(|body| json_response("200 OK", body))
                .collect(),
            |client| (0..4).map(|_| client.read_graph(VAULT)).collect::<Vec<_>>(),
        );
        assert_eq!(
            results[0].as_ref().unwrap().links[0]
                .target_note_id
                .as_deref(),
            Some(NOTE)
        );
        for result in &results[1..] {
            assert_eq!(result.as_ref().unwrap_err().code, "invalid_response");
        }
        for request in &requests {
            assert_common(request, "GET", &format!("/api/v1/vaults/{VAULT}/graph"));
        }
    }

    #[test]
    fn health_requires_ok_status() {
        let (result, requests) = with_server(
            vec![json_response(
                "200 OK",
                &json!({"status": "ok", "version": "0.1.0"}),
            )],
            |client| client.health(Duration::from_secs(1)),
        );
        assert_eq!(result.unwrap().version, "0.1.0");
        assert_common(&requests[0], "GET", "/api/v1/health");
        let (result, _) = with_server(
            vec![json_response(
                "200 OK",
                &json!({"status": "starting", "version": "0.1.0"}),
            )],
            |client| client.health(Duration::from_secs(1)),
        );
        assert_eq!(result.unwrap_err().code, "invalid_response");
    }

    #[test]
    fn credentials_cannot_be_forwarded_in_health_or_errors() {
        let (results, _) = with_server(
            vec![
                json_response("200 OK", &json!({"status": "ok", "version": TOKEN})),
                json_response(
                    "500 Internal Server Error",
                    &json!({"error": {
                        "code": "internal_error", "message": TOKEN, "details": null
                    }}),
                ),
            ],
            |client| {
                vec![
                    client.health(Duration::from_secs(1)).unwrap_err(),
                    client.list_vaults().unwrap_err(),
                ]
            },
        );
        for error in results {
            assert_eq!(error.code, "invalid_response");
            assert!(!serde_json::to_string(&error).unwrap().contains(TOKEN));
        }
    }

    #[test]
    fn vault_endpoints_send_documented_requests() {
        let (results, requests) = with_server(
            vec![
                json_response("201 Created", &vault_json()),
                json_response("200 OK", &vault_json()),
                json_response("200 OK", &json!([vault_json()])),
                json_response("200 OK", &vault_json()),
                response("204 No Content", &[], ""),
                json_response(
                    "200 OK",
                    &json!({"added": 1, "modified": 0, "renamed": 2, "missing": 0, "unchanged": 3}),
                ),
            ],
            |client| {
                let renames = BTreeMap::from([(NOTE.to_owned(), "moved/first.md".to_owned())]);
                (
                    client.create_vault("/tmp/notes", "Notes").unwrap(),
                    client.open_vault("/tmp/notes").unwrap(),
                    client.list_vaults().unwrap(),
                    client.get_vault(VAULT).unwrap(),
                    client.close_vault(VAULT).unwrap(),
                    client.reconcile(VAULT, &renames).unwrap(),
                )
            },
        );
        assert_eq!(results.0.id, VAULT);
        assert_eq!(results.2.len(), 1);
        assert_eq!(results.5.renamed, 2);
        assert_common(&requests[0], "POST", "/api/v1/vaults");
        assert_eq!(
            requests[0].json(),
            json!({"root_path": "/tmp/notes", "name": "Notes"})
        );
        assert_eq!(requests[0].header("content-type"), vec!["application/json"]);
        assert_common(&requests[1], "POST", "/api/v1/vaults/open");
        assert_eq!(requests[1].json(), json!({"root_path": "/tmp/notes"}));
        assert_common(&requests[2], "GET", "/api/v1/vaults");
        assert!(requests[2].body.is_empty());
        assert_common(&requests[3], "GET", &format!("/api/v1/vaults/{VAULT}"));
        assert_common(&requests[4], "DELETE", &format!("/api/v1/vaults/{VAULT}"));
        assert_common(
            &requests[5],
            "POST",
            &format!("/api/v1/vaults/{VAULT}/reconcile"),
        );
        assert_eq!(
            requests[5].json(),
            json!({"known_renames": {NOTE: "moved/first.md"}})
        );
    }

    #[test]
    fn note_endpoints_send_documented_requests() {
        let summary = json!([{
            "id": NOTE, "vault_id": VAULT, "relative_path": "ideas/first.md",
            "created_at": "2026-01-01T00:00:00.000000+00:00",
            "updated_at": "2026-01-01T00:00:00.000000+00:00", "revision": revision(),
        }]);
        let (results, requests) = with_server(
            vec![
                json_response("200 OK", &summary),
                note_reply("201 Created", "\u{feff}a\r\nb"),
                note_reply("200 OK", "x"),
                note_reply("200 OK", "y"),
                note_reply("200 OK", "y"),
                response("204 No Content", &[], ""),
            ],
            |client| {
                (
                    client.list_notes(VAULT).unwrap(),
                    client
                        .create_note(VAULT, "ideas/first.md", "\u{feff}a\r\nb")
                        .unwrap(),
                    client.read_note(VAULT, NOTE).unwrap(),
                    client.update_note(VAULT, NOTE, &revision(), "y").unwrap(),
                    client
                        .move_note(VAULT, NOTE, &revision(), "archive/first.md")
                        .unwrap(),
                    client.delete_note(VAULT, NOTE, &revision()).unwrap(),
                )
            },
        );
        assert_eq!(results.0.len(), 1);
        assert_eq!(results.1.content, "\u{feff}a\r\nb");
        let quoted = format!("\"{}\"", revision());
        assert_common(
            &requests[0],
            "GET",
            &format!("/api/v1/vaults/{VAULT}/notes"),
        );
        assert_common(
            &requests[1],
            "POST",
            &format!("/api/v1/vaults/{VAULT}/notes"),
        );
        assert_eq!(
            requests[1].json(),
            json!({"relative_path": "ideas/first.md", "content": "\u{feff}a\r\nb"})
        );
        assert!(requests[1].header("if-match").is_empty());
        assert_common(
            &requests[2],
            "GET",
            &format!("/api/v1/vaults/{VAULT}/notes/{NOTE}"),
        );
        assert_common(
            &requests[3],
            "PUT",
            &format!("/api/v1/vaults/{VAULT}/notes/{NOTE}"),
        );
        assert_eq!(requests[3].json(), json!({"content": "y"}));
        assert_eq!(requests[3].header("if-match"), vec![quoted.as_str()]);
        assert_common(
            &requests[4],
            "POST",
            &format!("/api/v1/vaults/{VAULT}/notes/{NOTE}/move"),
        );
        assert_eq!(
            requests[4].json(),
            json!({"relative_path": "archive/first.md"})
        );
        assert_eq!(requests[4].header("if-match"), vec![quoted.as_str()]);
        assert_common(
            &requests[5],
            "DELETE",
            &format!("/api/v1/vaults/{VAULT}/notes/{NOTE}"),
        );
        assert_eq!(requests[5].header("if-match"), vec![quoted.as_str()]);
        assert!(requests[5].body.is_empty());
        assert!(requests[5].header("content-type").is_empty());
    }

    #[test]
    fn invalid_identifiers_never_reach_the_network() {
        let (results, requests) = with_server(vec![], |client| {
            vec![
                client.get_vault("../vaults").unwrap_err(),
                client
                    .read_note(VAULT, "22222222-2222-4222-8222-22222222222G")
                    .unwrap_err(),
                client.update_note(VAULT, NOTE, "*", "x").unwrap_err(),
                client
                    .delete_note(VAULT, NOTE, &"AB".repeat(32))
                    .unwrap_err(),
                client
                    .reconcile(
                        VAULT,
                        &BTreeMap::from([("bad".to_owned(), "a.md".to_owned())]),
                    )
                    .unwrap_err(),
            ]
        });
        assert!(
            results
                .iter()
                .all(|error| error.kind == ErrorKind::Protocol)
        );
        assert!(requests.is_empty());
    }

    #[test]
    fn full_notes_require_a_matching_strong_etag() {
        let cases = vec![
            response("200 OK", &[], &note_json("x").to_string()),
            response(
                "200 OK",
                &[("ETag", &format!("W/\"{}\"", revision()))],
                &note_json("x").to_string(),
            ),
            response(
                "200 OK",
                &[("ETag", &format!("\"{}\"", "cd".repeat(32)))],
                &note_json("x").to_string(),
            ),
        ];
        let (results, _) = with_server(cases, |client| {
            (0..3)
                .map(|_| client.read_note(VAULT, NOTE).unwrap_err())
                .collect::<Vec<_>>()
        });
        assert!(results.iter().all(|error| error.code == "invalid_response"));
    }

    #[test]
    fn malformed_successes_become_safe_protocol_errors() {
        let secret_body = "{\"id\": \"secret note body\"";
        let mut extra = vault_json();
        extra["token"] = json!(TOKEN);
        let (results, _) = with_server(
            vec![
                response("200 OK", &[], secret_body),
                json_response("200 OK", &extra),
                json_response(
                    "200 OK",
                    &json!({"id": VAULT, "name": 1, "root_path": "/x", "needs_reconciliation": false}),
                ),
                response("204 No Content", &[], ""),
                note_reply("200 OK", "x"),
            ],
            |client| {
                vec![
                    client.list_vaults().unwrap_err(),
                    client.open_vault("/tmp/notes").unwrap_err(),
                    client.get_vault(VAULT).unwrap_err(),
                    client.list_notes(VAULT).unwrap_err(),
                    // A full note from another vault is rejected.
                    client
                        .read_note("33333333-3333-4333-8333-333333333333", NOTE)
                        .unwrap_err(),
                ]
            },
        );
        assert_eq!(results[0].code, "invalid_response");
        assert_eq!(results[1].code, OUTCOME_UNKNOWN);
        for error in &results {
            assert_eq!(error.kind, ErrorKind::Protocol);
            let text = format!("{error:?}{}", serde_json::to_string(error).unwrap());
            assert!(!text.contains("secret note body") && !text.contains(TOKEN));
        }
    }

    #[test]
    fn mutation_with_invalid_response_is_unknown() {
        let (result, _) = with_server(vec![response("200 OK", &[], "not json")], |client| {
            client.update_note(VAULT, NOTE, &revision(), "x")
        });
        let error = result.unwrap_err();
        assert!(error.is_outcome_unknown());
        assert_eq!(error.kind, ErrorKind::Protocol);
    }

    #[test]
    fn api_errors_keep_status_code_and_details() {
        let partial = json!({"error": {
            "code": "metadata_sync_failed",
            "message": "The filesystem changed but metadata could not be saved; reconcile the vault.",
            "details": {"filesystem_changed": true, "operation": "move", "relative_path": "new/path.md",
                        "note_id": NOTE, "reconciliation_required": true}}});
        let conflict = json!({"error": {"code": "revision_conflict", "message": "Read again.", "details": null}});
        let (results, _) = with_server(
            vec![
                json_response("503 Service Unavailable", &partial),
                json_response("412 Precondition Failed", &conflict),
                json_response(
                    "500 Internal Server Error",
                    &json!({"error": {"code": "x"}}),
                ),
                response("502 Bad Gateway", &[], "<html>proxy</html>"),
            ],
            |client| {
                vec![
                    client
                        .move_note(VAULT, NOTE, &revision(), "new/path.md")
                        .unwrap_err(),
                    client
                        .update_note(VAULT, NOTE, &revision(), "x")
                        .unwrap_err(),
                    client.read_note(VAULT, NOTE).unwrap_err(),
                    client.list_notes(VAULT).unwrap_err(),
                ]
            },
        );
        assert_eq!(results[0].kind, ErrorKind::Api);
        assert_eq!(results[0].status, Some(503));
        assert_eq!(results[0].code, "metadata_sync_failed");
        assert_eq!(
            &Value::Object(results[0].details.clone().unwrap()),
            &partial["error"]["details"]
        );
        assert_eq!(
            (results[1].status, results[1].code.as_str()),
            (Some(412), "revision_conflict")
        );
        assert_eq!(
            (results[2].kind, results[2].status),
            (ErrorKind::Protocol, Some(500))
        );
        assert_eq!(
            (results[3].kind, results[3].code.as_str()),
            (ErrorKind::Protocol, "invalid_response")
        );
        assert!(!format!("{:?}", results[3]).contains("proxy"));
    }

    #[test]
    fn redirects_are_not_followed() {
        let target = TestServer::start(vec![json_response("200 OK", &json!([]))]);
        let location = format!("http://127.0.0.1:{}/api/v1/vaults", target.port);
        let (result, requests) = with_server(
            vec![response(
                "307 Temporary Redirect",
                &[("Location", &location)],
                "",
            )],
            |client| client.list_vaults(),
        );
        let error = result.unwrap_err();
        assert_eq!((error.kind, error.status), (ErrorKind::Protocol, Some(307)));
        assert_eq!(requests.len(), 1);
        assert!(target.finish().is_empty());
    }

    #[test]
    fn dropped_mutation_is_sent_once_and_reported_unknown() {
        let (result, requests) = with_server(vec![Script::Drop, Script::Drop], |client| {
            client.create_note(VAULT, "a.md", "secret content")
        });
        let error = result.unwrap_err();
        assert_eq!(error.kind, ErrorKind::Transport);
        assert!(error.is_outcome_unknown());
        assert!(!format!("{error:?}").contains("secret content"));
        // The second scripted connection is only consumed by finish(): no retry happened.
        assert_eq!(requests.len(), 1);
    }

    #[test]
    fn unreachable_backend_is_not_an_unknown_outcome() {
        let port = {
            let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
            listener.local_addr().unwrap().port()
        };
        let client = CoreApiClient::new(port, TOKEN).unwrap();
        let error = client
            .update_note(VAULT, NOTE, &revision(), "x")
            .unwrap_err();
        assert_eq!(error.code, "backend_unreachable");
    }
}
