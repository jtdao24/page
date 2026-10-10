//! Ownership of the development Page Core subprocess.
//!
//! `BackendManager` launches at most one `python -m page_core.api --port 0`
//! child, reads its private bootstrap line, waits for authenticated health,
//! watches for crashes and stops the child gracefully. Every method blocks:
//! call it from ordinary worker threads or blocking tasks, never from the UI
//! thread or directly inside an async runtime.

use std::ffi::OsString;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::mpsc;
use std::sync::{Arc, Condvar, Mutex, MutexGuard, Weak};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::api::{CoreApiClient, HOST, is_token};
use crate::error::DesktopError;

pub const BOOTSTRAP_LIMIT: usize = 4096;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Lifecycle {
    Stopped,
    Starting,
    Ready,
    Failed,
    Stopping,
}

/// Public backend state. It never contains the endpoint, PID or token.
#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct BackendStatus {
    pub state: Lifecycle,
    pub generation: u64,
    pub core_version: Option<String>,
    pub error: Option<DesktopError>,
}

/// The interpreter, argument vector and working directory of the child.
#[derive(Clone, Debug)]
pub struct LaunchSpec {
    pub program: PathBuf,
    pub args: Vec<OsString>,
    pub cwd: PathBuf,
    /// Added to the inherited environment.
    pub env: Vec<(OsString, OsString)>,
}

/// Lifecycle deadlines; tests inject short values.
#[derive(Clone, Copy, Debug)]
pub struct Timing {
    pub startup_deadline: Duration,
    pub poll_interval: Duration,
    pub health_timeout: Duration,
    pub monitor_interval: Duration,
    pub shutdown_grace: Duration,
    pub settle_timeout: Duration,
}

impl Default for Timing {
    fn default() -> Self {
        Self {
            startup_deadline: Duration::from_secs(20),
            poll_interval: Duration::from_millis(100),
            health_timeout: Duration::from_secs(1),
            monitor_interval: Duration::from_millis(100),
            shutdown_grace: Duration::from_secs(10),
            // Longer than the HTTP client's 30-second request timeout.
            settle_timeout: Duration::from_secs(31),
        }
    }
}

/// The checkout this binary was built from, from the Rust manifest location.
pub fn checkout_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")))
}

/// Development discovery: `PAGE_PYTHON` or the checkout's `.venv` interpreter.
pub fn development_launch() -> Result<LaunchSpec, DesktopError> {
    let checkout = checkout_root();
    let program = resolve_interpreter(std::env::var_os("PAGE_PYTHON"), &checkout)?;
    Ok(LaunchSpec {
        program,
        args: ["-m", "page_core.api", "--port", "0"]
            .map(OsString::from)
            .to_vec(),
        cwd: checkout,
        env: Vec::new(),
    })
}

fn runtime_missing() -> DesktopError {
    DesktopError::backend(
        "runtime_missing",
        "This build of Page does not include its Python runtime. Build it with npm run tauri:bundle.",
    )
}

/// The packaged app's resource folder: `Contents/Resources` on macOS, the
/// executable's folder on Windows.
pub fn resource_dir(executable: &Path) -> Option<PathBuf> {
    let folder = executable.parent()?;
    if cfg!(target_os = "macos") {
        Some(folder.parent()?.join("Resources"))
    } else {
        Some(folder.to_path_buf())
    }
}

/// The bundled runtime: isolated mode (no user site or `PYTHON*` variables),
/// no bytecode writes inside the signed app, and the bundled model, offline.
pub fn bundled_launch(resources: &Path) -> Result<LaunchSpec, DesktopError> {
    let runtime = resources.join("runtime");
    let program = if cfg!(windows) {
        runtime.join("python").join("python.exe")
    } else {
        runtime.join("python").join("bin").join("python3")
    };
    if !program.is_file() {
        return Err(runtime_missing());
    }
    let env = [
        ("PAGE_MODEL_DIR", runtime.join("model").into_os_string()),
        ("HF_HUB_OFFLINE", "1".into()),
        ("TRANSFORMERS_OFFLINE", "1".into()),
        ("HF_HUB_DISABLE_TELEMETRY", "1".into()),
    ]
    .map(|(name, value)| (OsString::from(name), value))
    .to_vec();
    Ok(LaunchSpec {
        program,
        args: ["-I", "-B", "-m", "page_core.api", "--port", "0"]
            .map(OsString::from)
            .to_vec(),
        cwd: runtime,
        env,
    })
}

/// Release builds run the bundled runtime next to the executable.
pub fn packaged_launch() -> Result<LaunchSpec, DesktopError> {
    let executable = std::env::current_exe().map_err(|_| runtime_missing())?;
    bundled_launch(&resource_dir(&executable).ok_or_else(runtime_missing)?)
}

/// Accept exactly one nonempty absolute override, used verbatim: no argument
/// splitting, shell expansion or PATH search.
pub fn resolve_interpreter(
    override_path: Option<OsString>,
    checkout: &Path,
) -> Result<PathBuf, DesktopError> {
    match override_path {
        Some(value) => {
            let path = PathBuf::from(value);
            if path.as_os_str().is_empty() || !path.is_absolute() {
                return Err(DesktopError::backend(
                    "invalid_interpreter_override",
                    "PAGE_PYTHON must be an absolute path to a Python interpreter.",
                ));
            }
            Ok(path)
        }
        None if cfg!(windows) => Ok(checkout.join(".venv").join("Scripts").join("python.exe")),
        None => Ok(checkout.join(".venv").join("bin").join("python")),
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Bootstrap {
    host: String,
    port: u64,
    token: String,
}

/// Validate a complete bootstrap line. Rejected data is never echoed.
pub fn parse_bootstrap(line: &[u8]) -> Result<(u16, String), DesktopError> {
    let invalid = || {
        DesktopError::backend(
            "invalid_bootstrap",
            "Page Core reported an invalid endpoint.",
        )
    };
    let Some(json) = line.strip_suffix(b"\n") else {
        return Err(invalid());
    };
    if json.len() + 1 > BOOTSTRAP_LIMIT || json.contains(&b'\n') {
        return Err(invalid());
    }
    let bootstrap: Bootstrap = serde_json::from_slice(json).map_err(|_| invalid())?;
    if bootstrap.host != HOST
        || !(1..=65535).contains(&bootstrap.port)
        || !is_token(&bootstrap.token)
    {
        return Err(invalid());
    }
    Ok((bootstrap.port as u16, bootstrap.token))
}

#[derive(Debug, PartialEq, Eq)]
enum LineError {
    Oversized,
    Incomplete,
}

/// Read one newline-terminated line of at most `BOOTSTRAP_LIMIT` bytes.
fn read_line_limited(reader: &mut impl BufRead) -> Result<Vec<u8>, LineError> {
    let mut line = Vec::new();
    loop {
        let available = match reader.fill_buf() {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(_) => return Err(LineError::Incomplete),
        };
        if available.is_empty() {
            return Err(LineError::Incomplete);
        }
        let (taken, done) = match available.iter().position(|byte| *byte == b'\n') {
            Some(index) => (index + 1, true),
            None => (available.len(), false),
        };
        line.extend_from_slice(&available[..taken]);
        reader.consume(taken);
        if line.len() > BOOTSTRAP_LIMIT {
            return Err(LineError::Oversized);
        }
        if done {
            return Ok(line);
        }
    }
}

/// Read and discard with a fixed buffer until EOF.
fn drain(mut reader: impl Read) {
    let mut buffer = [0u8; 8192];
    while let Ok(count) = reader.read(&mut buffer) {
        if count == 0 {
            break;
        }
    }
}

struct Process {
    child: Mutex<Child>,
    readers: Mutex<Vec<JoinHandle<()>>>,
}

impl Process {
    fn join_readers(&self) {
        let handles: Vec<_> = lock(&self.readers).drain(..).collect();
        for handle in handles {
            let _ = handle.join();
        }
    }

    /// Kill without grace and reap; used for failed startups.
    fn kill(&self) {
        {
            let mut child = lock(&self.child);
            if matches!(child.try_wait(), Ok(None)) {
                let _ = child.kill();
            }
            let _ = child.wait();
        }
        self.join_readers();
    }

    /// SIGTERM, wait up to `grace`, then kill and reap.
    fn terminate(&self, grace: Duration) {
        let deadline = Instant::now() + grace;
        {
            let mut child = lock(&self.child);
            // Only signal while unreaped, so the PID cannot have been reused.
            if matches!(child.try_wait(), Ok(None)) {
                send_terminate(&mut child);
            }
        }
        loop {
            let exited = !matches!(lock(&self.child).try_wait(), Ok(None));
            if exited || Instant::now() >= deadline {
                break;
            }
            std::thread::sleep(Duration::from_millis(25));
        }
        self.kill();
    }

    fn exit_status(&self) -> Option<ExitStatus> {
        match lock(&self.child).try_wait() {
            Ok(status) => status,
            Err(_) => None,
        }
    }

    #[cfg(test)]
    fn id(&self) -> u32 {
        lock(&self.child).id()
    }
}

#[cfg(target_os = "macos")]
fn send_terminate(child: &mut Child) {
    let Ok(pid) = libc::pid_t::try_from(child.id()) else {
        let _ = child.kill();
        return;
    };
    // SAFETY: `pid` belongs to our own unreaped child.
    unsafe {
        libc::kill(pid, libc::SIGTERM);
    }
}

#[cfg(not(target_os = "macos"))]
fn send_terminate(child: &mut Child) {
    // Graceful signals are only implemented for macOS development.
    let _ = child.kill();
}

fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

fn describe_exit(status: Option<ExitStatus>) -> String {
    match status.and_then(|status| status.code()) {
        Some(code) => format!("exit status {code}"),
        None => "terminated by a signal".to_owned(),
    }
}

pub type StatusListener = Box<dyn Fn(&BackendStatus) + Send + Sync>;

struct State {
    lifecycle: Lifecycle,
    generation: u64,
    version: Option<String>,
    error: Option<DesktopError>,
    process: Option<Arc<Process>>,
    client: Option<Arc<CoreApiClient>>,
    in_flight: usize,
    closed: bool,
}

impl State {
    fn status(&self) -> BackendStatus {
        BackendStatus {
            state: self.lifecycle,
            generation: self.generation,
            core_version: self.version.clone(),
            error: self.error.clone(),
        }
    }

    fn outcome(&self) -> Result<BackendStatus, DesktopError> {
        if self.lifecycle == Lifecycle::Ready {
            Ok(self.status())
        } else {
            Err(self.error.clone().unwrap_or_else(unavailable))
        }
    }
}

fn unavailable() -> DesktopError {
    DesktopError::backend("backend_unavailable", "Page Core is not running.")
}

fn stopping() -> DesktopError {
    DesktopError::backend("backend_stopping", "Page is shutting down.")
}

/// Supplies the Gemini API key at each launch, so a changed key applies on restart.
pub type SecretSource = Box<dyn Fn() -> Option<String> + Send + Sync>;

struct Shared {
    launch: Result<LaunchSpec, DesktopError>,
    gemini_key: Mutex<Option<SecretSource>>,
    timing: Timing,
    state: Mutex<State>,
    changed: Condvar,
    listener: Mutex<Option<StatusListener>>,
}

impl Shared {
    /// Publish while holding the state lock so listeners observe statuses in order.
    fn publish(&self, state: &State) {
        if let Some(listener) = lock(&self.listener).as_ref() {
            listener(&state.status());
        }
        self.changed.notify_all();
    }
}

pub struct BackendManager {
    shared: Arc<Shared>,
}

/// A ready client plus an in-flight registration that shutdown waits for.
pub struct RequestLease {
    client: Arc<CoreApiClient>,
    shared: Arc<Shared>,
}

impl RequestLease {
    /// The client without the in-flight registration, for tests that keep a
    /// previous connection's client after a restart.
    pub fn detach(&self) -> Arc<CoreApiClient> {
        Arc::clone(&self.client)
    }
}

impl std::fmt::Debug for RequestLease {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("RequestLease { .. }")
    }
}

impl std::ops::Deref for RequestLease {
    type Target = CoreApiClient;

    fn deref(&self) -> &CoreApiClient {
        &self.client
    }
}

impl Drop for RequestLease {
    fn drop(&mut self) {
        let mut state = lock(&self.shared.state);
        state.in_flight -= 1;
        self.shared.changed.notify_all();
    }
}

impl BackendManager {
    pub fn new(launch: Result<LaunchSpec, DesktopError>, timing: Timing) -> Self {
        let state = State {
            lifecycle: Lifecycle::Stopped,
            generation: 0,
            version: None,
            error: None,
            process: None,
            client: None,
            in_flight: 0,
            closed: false,
        };
        Self {
            shared: Arc::new(Shared {
                launch,
                gemini_key: Mutex::new(None),
                timing,
                state: Mutex::new(state),
                changed: Condvar::new(),
                listener: Mutex::new(None),
            }),
        }
    }

    /// The checkout's development interpreter in debug builds; the bundled
    /// runtime in release builds.
    pub fn for_build() -> Self {
        let launch = if cfg!(debug_assertions) {
            development_launch()
        } else {
            packaged_launch()
        };
        Self::new(launch, Timing::default())
    }

    /// A stored key overrides any inherited `GEMINI_API_KEY`.
    pub fn set_gemini_key_source(&self, source: SecretSource) {
        *lock(&self.shared.gemini_key) = Some(source);
    }

    pub fn set_listener(&self, listener: StatusListener) {
        *lock(&self.shared.listener) = Some(listener);
    }

    pub fn status(&self) -> BackendStatus {
        lock(&self.shared.state).status()
    }

    /// The ready client, registered as in flight until the lease is dropped.
    pub fn client(&self) -> Result<RequestLease, DesktopError> {
        let mut state = lock(&self.shared.state);
        if state.closed {
            return Err(stopping());
        }
        match (&state.client, state.lifecycle) {
            (Some(client), Lifecycle::Ready) => {
                let client = Arc::clone(client);
                state.in_flight += 1;
                Ok(RequestLease {
                    client,
                    shared: Arc::clone(&self.shared),
                })
            }
            _ => Err(unavailable()),
        }
    }

    /// Start, join an attempt in progress, or return the ready status.
    pub fn start(&self) -> Result<BackendStatus, DesktopError> {
        let mut state = lock(&self.shared.state);
        loop {
            if state.closed {
                return Err(stopping());
            }
            match state.lifecycle {
                Lifecycle::Ready => return Ok(state.status()),
                Lifecycle::Starting => {
                    let joined = state.generation;
                    while state.lifecycle == Lifecycle::Starting && state.generation == joined {
                        state = self.wait(state);
                    }
                    return state.outcome();
                }
                Lifecycle::Stopping => state = self.wait(state),
                Lifecycle::Stopped | Lifecycle::Failed => break,
            }
        }
        state.lifecycle = Lifecycle::Starting;
        state.generation += 1;
        state.version = None;
        state.error = None;
        let generation = state.generation;
        self.shared.publish(&state);
        drop(state);

        let result = self.launch();
        let mut state = lock(&self.shared.state);
        match result {
            Ok((process, client, version)) => {
                state.lifecycle = Lifecycle::Ready;
                state.version = Some(version);
                state.process = Some(Arc::clone(&process));
                state.client = Some(client);
                spawn_monitor(
                    Arc::downgrade(&self.shared),
                    process,
                    generation,
                    self.shared.timing.monitor_interval,
                );
            }
            Err(error) => {
                state.lifecycle = Lifecycle::Failed;
                state.error = Some(error);
            }
        }
        self.shared.publish(&state);
        state.outcome()
    }

    /// Stop any owned child and start a fresh process with a new token.
    pub fn restart(&self) -> Result<BackendStatus, DesktopError> {
        let mut state = lock(&self.shared.state);
        while matches!(state.lifecycle, Lifecycle::Starting | Lifecycle::Stopping) && !state.closed
        {
            state = self.wait(state);
        }
        if state.closed {
            return Err(stopping());
        }
        if let Some(process) = self.begin_stop(&mut state) {
            drop(state);
            process.terminate(self.shared.timing.shutdown_grace);
            state = lock(&self.shared.state);
            state.lifecycle = Lifecycle::Stopped;
            self.shared.publish(&state);
        }
        drop(state);
        self.start()
    }

    /// Approved shutdown: reject new work, let in-flight requests settle,
    /// then stop and reap the child. Repeated calls wait for the first one.
    pub fn shutdown(&self) {
        let mut state = lock(&self.shared.state);
        if state.closed {
            while state.lifecycle == Lifecycle::Stopping {
                state = self.wait(state);
            }
            return;
        }
        state.closed = true;
        self.shared.changed.notify_all();
        while state.lifecycle == Lifecycle::Starting {
            state = self.wait(state);
        }
        let deadline = Instant::now() + self.shared.timing.settle_timeout;
        while state.in_flight > 0 {
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                break;
            }
            state = self
                .shared
                .changed
                .wait_timeout(state, remaining)
                .unwrap_or_else(|poisoned| poisoned.into_inner())
                .0;
        }
        let process = self.begin_stop(&mut state);
        drop(state);
        if let Some(process) = process {
            process.terminate(self.shared.timing.shutdown_grace);
        }
        let mut state = lock(&self.shared.state);
        state.lifecycle = Lifecycle::Stopped;
        self.shared.publish(&state);
    }

    fn begin_stop(&self, state: &mut MutexGuard<'_, State>) -> Option<Arc<Process>> {
        let process = state.process.take();
        state.client = None;
        state.version = None;
        if process.is_some() {
            state.lifecycle = Lifecycle::Stopping;
            self.shared.publish(state);
        }
        process
    }

    fn wait<'a>(&self, state: MutexGuard<'a, State>) -> MutexGuard<'a, State> {
        self.shared
            .changed
            .wait(state)
            .unwrap_or_else(|poisoned| poisoned.into_inner())
    }

    fn launch(&self) -> Result<(Arc<Process>, Arc<CoreApiClient>, String), DesktopError> {
        let spec = self.shared.launch.clone()?;
        let timing = self.shared.timing;
        let deadline = Instant::now() + timing.startup_deadline;
        let mut command = Command::new(&spec.program);
        command
            .args(&spec.args)
            .current_dir(&spec.cwd)
            .envs(spec.env.iter().map(|(name, value)| (name, value)));
        if let Some(key) = lock(&self.shared.gemini_key)
            .as_ref()
            .and_then(|source| source())
        {
            command.env("GEMINI_API_KEY", key);
        }
        let mut child = command
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| match error.kind() {
                std::io::ErrorKind::NotFound => DesktopError::backend(
                    "interpreter_not_found",
                    "The Python interpreter was not found. Create the .venv environment described in README.md or set PAGE_PYTHON.",
                ),
                std::io::ErrorKind::PermissionDenied => DesktopError::backend(
                    "interpreter_not_executable",
                    "The Python interpreter could not be executed. Check PAGE_PYTHON or the .venv environment.",
                ),
                _ => DesktopError::backend("backend_spawn_failed", "Page Core could not be started."),
            })?;
        let stdout = child.stdout.take();
        let stderr = child.stderr.take();
        let (sender, receiver) = mpsc::channel();
        let mut readers = Vec::new();
        if let Some(stderr) = stderr {
            readers.push(std::thread::spawn(move || drain(stderr)));
        }
        if let Some(stdout) = stdout {
            readers.push(std::thread::spawn(move || {
                let mut reader = BufReader::new(stdout);
                let _ = sender.send(read_line_limited(&mut reader));
                drain(reader);
            }));
        }
        let process = Arc::new(Process {
            child: Mutex::new(child),
            readers: Mutex::new(readers),
        });
        match Self::await_ready(&process, receiver, deadline, timing) {
            Ok((client, version)) => Ok((process, client, version)),
            Err(error) => {
                process.kill();
                Err(error)
            }
        }
    }

    fn await_ready(
        process: &Process,
        bootstrap: mpsc::Receiver<Result<Vec<u8>, LineError>>,
        deadline: Instant,
        timing: Timing,
    ) -> Result<(Arc<CoreApiClient>, String), DesktopError> {
        let timeout = || {
            DesktopError::backend(
                "backend_start_timeout",
                "Page Core did not become ready in time.",
            )
        };
        let exited = |status: Option<ExitStatus>| {
            DesktopError::backend(
                "backend_exited",
                format!(
                    "Page Core exited before it was ready ({}). Check that page-core is installed in the Python environment.",
                    describe_exit(status)
                ),
            )
        };
        let line = match bootstrap.recv_timeout(deadline.saturating_duration_since(Instant::now()))
        {
            Ok(Ok(line)) => line,
            Ok(Err(LineError::Oversized)) => {
                return Err(DesktopError::backend(
                    "invalid_bootstrap",
                    "Page Core reported an invalid endpoint.",
                ));
            }
            Ok(Err(LineError::Incomplete)) | Err(mpsc::RecvTimeoutError::Disconnected) => {
                // EOF: wait briefly for the exit status to describe it.
                let wait_until = deadline.min(Instant::now() + Duration::from_millis(500));
                while process.exit_status().is_none() && Instant::now() < wait_until {
                    std::thread::sleep(Duration::from_millis(10));
                }
                return Err(match process.exit_status() {
                    Some(status) => exited(Some(status)),
                    None => DesktopError::backend(
                        "invalid_bootstrap",
                        "Page Core reported an invalid endpoint.",
                    ),
                });
            }
            Err(mpsc::RecvTimeoutError::Timeout) => return Err(timeout()),
        };
        let (port, token) = parse_bootstrap(&line)?;
        let client = Arc::new(CoreApiClient::new(port, &token)?);
        drop(token);
        loop {
            if let Some(status) = process.exit_status() {
                return Err(exited(Some(status)));
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(timeout());
            }
            if let Ok(health) = client.health(timing.health_timeout.min(remaining)) {
                if process.exit_status().is_none() {
                    return Ok((client, health.version));
                }
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            std::thread::sleep(timing.poll_interval.min(remaining));
        }
    }

    #[cfg(test)]
    fn process_id(&self) -> Option<u32> {
        lock(&self.shared.state)
            .process
            .as_ref()
            .map(|process| process.id())
    }
}

impl Drop for BackendManager {
    fn drop(&mut self) {
        // Safety net: never leave an owned child running.
        let process = lock(&self.shared.state).process.take();
        if let Some(process) = process {
            process.kill();
        }
    }
}

fn spawn_monitor(shared: Weak<Shared>, process: Arc<Process>, generation: u64, interval: Duration) {
    std::thread::spawn(move || {
        loop {
            std::thread::sleep(interval);
            let Some(shared) = shared.upgrade() else {
                return;
            };
            let mut state = lock(&shared.state);
            let owned = state
                .process
                .as_ref()
                .is_some_and(|current| Arc::ptr_eq(current, &process));
            if state.generation != generation || state.lifecycle != Lifecycle::Ready || !owned {
                return;
            }
            let Some(status) = process.exit_status() else {
                continue;
            };
            state.lifecycle = Lifecycle::Failed;
            state.client = None;
            state.version = None;
            state.process = None;
            state.error = Some(DesktopError::backend(
                "backend_exited",
                format!(
                    "Page Core stopped unexpectedly ({}). Restart it to continue.",
                    describe_exit(Some(status))
                ),
            ));
            shared.publish(&state);
            drop(state);
            process.kill();
            return;
        }
    });
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;
    use std::io::Write as _;
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

    const TOKEN: &str = "PageTestToken_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx";

    fn timing() -> Timing {
        Timing {
            startup_deadline: Duration::from_millis(1500),
            poll_interval: Duration::from_millis(20),
            health_timeout: Duration::from_millis(200),
            monitor_interval: Duration::from_millis(20),
            shutdown_grace: Duration::from_millis(400),
            settle_timeout: Duration::from_millis(400),
        }
    }

    /// Answers authenticated health checks; 503 until `ready` is set.
    struct HealthServer {
        port: u16,
        ready: Arc<AtomicBool>,
        polls: Arc<AtomicUsize>,
        stop: Arc<AtomicBool>,
    }

    impl HealthServer {
        fn start(ready: bool) -> Self {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            listener.set_nonblocking(true).unwrap();
            let port = listener.local_addr().unwrap().port();
            let ready = Arc::new(AtomicBool::new(ready));
            let polls = Arc::new(AtomicUsize::new(0));
            let stop = Arc::new(AtomicBool::new(false));
            let (ready_flag, poll_count, stop_flag) =
                (Arc::clone(&ready), Arc::clone(&polls), Arc::clone(&stop));
            std::thread::spawn(move || {
                while !stop_flag.load(Ordering::SeqCst) {
                    let Ok((mut stream, _)) = listener.accept() else {
                        std::thread::sleep(Duration::from_millis(5));
                        continue;
                    };
                    stream.set_nonblocking(false).unwrap();
                    let mut buffer = [0u8; 2048];
                    let count = stream.read(&mut buffer).unwrap_or(0);
                    let request = String::from_utf8_lossy(&buffer[..count]).to_string();
                    poll_count.fetch_add(1, Ordering::SeqCst);
                    let authorized = request.contains(&format!("authorization: Bearer {TOKEN}"));
                    let body = r#"{"status":"ok","version":"9.9.9"}"#;
                    let reply = if authorized && ready_flag.load(Ordering::SeqCst) {
                        format!(
                            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                            body.len()
                        )
                    } else {
                        let error =
                            r#"{"error":{"code":"starting","message":"Starting.","details":null}}"#;
                        format!(
                            "HTTP/1.1 503 Busy\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{error}",
                            error.len()
                        )
                    };
                    let _ = stream.write_all(reply.as_bytes());
                }
            });
            Self {
                port,
                ready,
                polls,
                stop,
            }
        }

        fn bootstrap(&self) -> String {
            format!(
                r#"{{"host":"127.0.0.1","port":{},"token":"{TOKEN}"}}"#,
                self.port
            )
        }
    }

    impl Drop for HealthServer {
        fn drop(&mut self) {
            self.stop.store(true, Ordering::SeqCst);
        }
    }

    fn shell(script: &str) -> LaunchSpec {
        LaunchSpec {
            program: PathBuf::from("/bin/sh"),
            args: vec![OsString::from("-c"), OsString::from(script)],
            cwd: std::env::temp_dir(),
            env: Vec::new(),
        }
    }

    fn manager(script: &str) -> BackendManager {
        BackendManager::new(Ok(shell(script)), timing())
    }

    fn alive(pid: u32) -> bool {
        // SAFETY: signal 0 only checks for existence.
        unsafe { libc::kill(pid as libc::pid_t, 0) == 0 }
    }

    fn serving(server: &HealthServer, rest: &str) -> String {
        format!("printf '%s\\n' '{}'; {rest}", server.bootstrap())
    }

    #[test]
    fn bootstrap_accepts_the_real_shape() {
        let line = format!("{{\"host\":\"127.0.0.1\",\"port\":8765,\"token\":\"{TOKEN}\"}}\n");
        assert_eq!(
            parse_bootstrap(line.as_bytes()).unwrap(),
            (8765, TOKEN.to_owned())
        );
    }

    #[test]
    fn bootstrap_rejects_invalid_lines_without_echoing_them() {
        let secret = "SecretSecretSecretSecretSecretSecretSecret1";
        let cases = vec![
            format!("{{\"host\":\"127.0.0.1\",\"port\":8765,\"token\":\"{secret}\"}}"),
            format!(
                "{{\"host\":\"127.0.0.1\",\"port\":8765,\"token\":\"{secret}\",\"extra\":1}}\n"
            ),
            format!("{{\"host\":\"127.0.0.1\",\"port\":8765}}\n"),
            format!("{{\"host\":\"localhost\",\"port\":8765,\"token\":\"{secret}\"}}\n"),
            format!("{{\"host\":\"127.0.0.1\",\"port\":0,\"token\":\"{secret}\"}}\n"),
            format!("{{\"host\":\"127.0.0.1\",\"port\":65536,\"token\":\"{secret}\"}}\n"),
            format!("{{\"host\":\"127.0.0.1\",\"port\":87.5,\"token\":\"{secret}\"}}\n"),
            format!("{{\"host\":\"127.0.0.1\",\"port\":\"8765\",\"token\":\"{secret}\"}}\n"),
            format!("{{\"host\":\"127.0.0.1\",\"port\":8765,\"token\":\"{secret}x\"}}\n"),
            format!(
                "{{\"host\":\"127.0.0.1\",\"port\":8765,\"token\":\"{}!\"}}\n",
                &secret[..42]
            ),
            format!(
                "{{\"host\":\"127.0.0.1\",\"port\":8765,\"port\":8766,\"token\":\"{secret}\"}}\n"
            ),
            format!("{{\"host\":\"127.0.0.1\",\"port\":8765,\"token\":\"{secret}\"\n"),
            format!(
                "{{\"host\":\"127.0.0.1\",\"port\":8765,\"token\":\"{secret}\",\"pad\":\"{}\"}}\n",
                "x".repeat(5000)
            ),
        ];
        for case in cases {
            let error = parse_bootstrap(case.as_bytes()).unwrap_err();
            assert_eq!(error.code, "invalid_bootstrap");
            assert!(!format!("{error:?}").contains(secret));
        }
    }

    #[test]
    fn line_reader_enforces_limit_and_termination() {
        let mut ok = BufReader::new(&b"abc\nrest"[..]);
        assert_eq!(read_line_limited(&mut ok).unwrap(), b"abc\n");
        let mut eof = BufReader::new(&b"abc"[..]);
        assert_eq!(read_line_limited(&mut eof), Err(LineError::Incomplete));
        let big = vec![b'x'; BOOTSTRAP_LIMIT + 10];
        assert_eq!(
            read_line_limited(&mut BufReader::new(&big[..])),
            Err(LineError::Oversized)
        );
    }

    #[test]
    fn interpreter_override_must_be_one_absolute_path() {
        let checkout = Path::new("/checkout");
        assert_eq!(
            resolve_interpreter(None, checkout).unwrap(),
            PathBuf::from("/checkout/.venv/bin/python")
        );
        assert_eq!(
            resolve_interpreter(Some("/opt/py 3/bin/python -X dev".into()), checkout).unwrap(),
            PathBuf::from("/opt/py 3/bin/python -X dev")
        );
        assert!(resolve_interpreter(Some("".into()), checkout).is_err());
        assert!(resolve_interpreter(Some("python3".into()), checkout).is_err());
        assert!(resolve_interpreter(Some("~/bin/python".into()), checkout).is_err());
        assert!(resolve_interpreter(Some("$HOME/python".into()), checkout).is_err());
    }

    #[test]
    fn development_launch_uses_checkout_and_fixed_arguments() {
        let root = checkout_root();
        assert!(root.join("packages/core/pyproject.toml").is_file());
        if std::env::var_os("PAGE_PYTHON").is_none() {
            let spec = development_launch().unwrap();
            assert_eq!(spec.program, root.join(".venv/bin/python"));
            assert_eq!(
                spec.args,
                ["-m", "page_core.api", "--port", "0"]
                    .map(OsString::from)
                    .to_vec()
            );
            assert_eq!(spec.cwd, root);
        }
    }

    #[test]
    fn delayed_readiness_polls_health_until_ok() {
        let server = HealthServer::start(false);
        let manager = manager(&serving(&server, "exec sleep 30"));
        let ready = Arc::clone(&server.ready);
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(200));
            ready.store(true, Ordering::SeqCst);
        });
        let status = manager.start().unwrap();
        assert_eq!(status.state, Lifecycle::Ready);
        assert_eq!(status.generation, 1);
        assert_eq!(status.core_version.as_deref(), Some("9.9.9"));
        assert!(server.polls.load(Ordering::SeqCst) >= 2);
        let serialized = serde_json::to_string(&status).unwrap();
        assert!(!serialized.contains(TOKEN) && !serialized.contains(&server.port.to_string()));
        let pid = manager.process_id().unwrap();
        manager.shutdown();
        assert!(!alive(pid));
        assert_eq!(manager.status().state, Lifecycle::Stopped);
    }

    #[test]
    fn early_exit_is_reported_with_exit_status() {
        let manager = manager("echo 'Traceback: secret' >&2; exit 3");
        let error = manager.start().unwrap_err();
        assert_eq!(error.code, "backend_exited");
        assert!(error.message.contains("exit status 3"));
        assert!(!error.message.contains("secret"));
        assert_eq!(manager.status().state, Lifecycle::Failed);
    }

    #[test]
    fn launch_environment_and_stored_key_reach_the_child() {
        let out = std::env::temp_dir().join(format!("page-env-{}", std::process::id()));
        let mut spec = shell(&format!(
            "printf '%s|%s' \"$PAGE_TEST_VALUE\" \"$GEMINI_API_KEY\" > '{}'; exit 3",
            out.display()
        ));
        spec.env = vec![("PAGE_TEST_VALUE".into(), "bundled".into())];
        let manager = BackendManager::new(Ok(spec), timing());
        manager.set_gemini_key_source(Box::new(|| Some("stored-key".to_owned())));
        assert_eq!(manager.start().unwrap_err().code, "backend_exited");
        assert!(
            !manager
                .status()
                .error
                .unwrap()
                .message
                .contains("stored-key")
        );
        assert_eq!(std::fs::read_to_string(&out).unwrap(), "bundled|stored-key");
        manager.set_gemini_key_source(Box::new(|| None));
        let _ = manager.restart();
        let inherited = std::env::var("GEMINI_API_KEY").unwrap_or_default();
        assert_eq!(
            std::fs::read_to_string(&out).unwrap(),
            format!("bundled|{inherited}")
        );
        let _ = std::fs::remove_file(out);
    }

    #[test]
    fn bundled_launch_uses_the_runtime_in_resources() {
        let resources = std::env::temp_dir().join(format!("page-resources-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&resources);
        assert_eq!(
            bundled_launch(&resources).unwrap_err().code,
            "runtime_missing"
        );
        let runtime = resources.join("runtime");
        std::fs::create_dir_all(runtime.join("python/bin")).unwrap();
        std::fs::write(runtime.join("python/bin/python3"), b"").unwrap();
        let spec = bundled_launch(&resources).unwrap();
        assert_eq!(spec.program, runtime.join("python/bin/python3"));
        assert_eq!(
            spec.args,
            ["-I", "-B", "-m", "page_core.api", "--port", "0"]
                .map(OsString::from)
                .to_vec()
        );
        assert_eq!(spec.cwd, runtime);
        assert!(
            spec.env
                .contains(&("PAGE_MODEL_DIR".into(), runtime.join("model").into()))
        );
        assert!(spec.env.contains(&("HF_HUB_OFFLINE".into(), "1".into())));
        std::fs::remove_dir_all(resources).unwrap();
    }

    #[test]
    fn resources_are_found_from_the_executable() {
        let executable = Path::new("/Applications/Page.app/Contents/MacOS/page-desktop");
        let expected = if cfg!(target_os = "macos") {
            "/Applications/Page.app/Contents/Resources"
        } else {
            "/Applications/Page.app/Contents/MacOS"
        };
        assert_eq!(resource_dir(executable).unwrap(), PathBuf::from(expected));
    }

    #[test]
    fn missing_interpreter_is_actionable() {
        let spec = LaunchSpec {
            program: PathBuf::from("/nonexistent/page/python"),
            args: vec![],
            cwd: std::env::temp_dir(),
            env: Vec::new(),
        };
        let manager = BackendManager::new(Ok(spec), timing());
        assert_eq!(manager.start().unwrap_err().code, "interpreter_not_found");
        let invalid = BackendManager::new(
            resolve_interpreter(Some("python".into()), Path::new("/")).map(|program| LaunchSpec {
                program,
                args: vec![],
                cwd: PathBuf::from("/"),
                env: Vec::new(),
            }),
            timing(),
        );
        assert_eq!(
            invalid.start().unwrap_err().code,
            "invalid_interpreter_override"
        );
    }

    #[test]
    fn missing_bootstrap_times_out_and_reaps() {
        let manager = manager("exec sleep 30");
        let started = Instant::now();
        let error = manager.start().unwrap_err();
        assert_eq!(error.code, "backend_start_timeout");
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(manager.process_id().is_none());
    }

    #[test]
    fn health_that_never_succeeds_times_out() {
        let server = HealthServer::start(false);
        let manager = manager(&serving(&server, "exec sleep 30"));
        assert_eq!(manager.start().unwrap_err().code, "backend_start_timeout");
    }

    #[test]
    fn malformed_bootstrap_fails_and_kills_child() {
        let manager = manager(&format!("echo '{{\"token\":\"{TOKEN}\"}}'; exec sleep 30"));
        let error = manager.start().unwrap_err();
        assert_eq!(error.code, "invalid_bootstrap");
        assert!(!error.message.contains(TOKEN));
    }

    #[test]
    fn concurrent_starts_join_one_attempt() {
        let server = HealthServer::start(true);
        let counter = std::env::temp_dir().join(format!("page-start-count-{}", std::process::id()));
        let _ = std::fs::remove_file(&counter);
        let script = format!(
            "echo x >> '{}'; sleep 0.2; {}",
            counter.display(),
            serving(&server, "exec sleep 30")
        );
        let manager = Arc::new(manager(&script));
        let handles: Vec<_> = (0..4)
            .map(|_| {
                let manager = Arc::clone(&manager);
                std::thread::spawn(move || manager.start().unwrap())
            })
            .collect();
        let statuses: Vec<_> = handles
            .into_iter()
            .map(|handle| handle.join().unwrap())
            .collect();
        assert!(
            statuses
                .iter()
                .all(|status| status.generation == 1 && status.state == Lifecycle::Ready)
        );
        assert_eq!(manager.start().unwrap().generation, 1);
        assert_eq!(std::fs::read_to_string(&counter).unwrap(), "x\n");
        manager.shutdown();
        let _ = std::fs::remove_file(&counter);
    }

    #[test]
    fn restart_reaps_previous_child_and_increments_generation() {
        let server = HealthServer::start(true);
        let manager = manager(&serving(&server, "exec sleep 30"));
        manager.start().unwrap();
        let first = manager.process_id().unwrap();
        let status = manager.restart().unwrap();
        assert_eq!(status.generation, 2);
        assert!(!alive(first));
        let second = manager.process_id().unwrap();
        assert_ne!(first, second);
        manager.shutdown();
        assert!(!alive(second));
    }

    #[test]
    fn crash_after_ready_is_detected_and_not_restarted() {
        let server = HealthServer::start(true);
        let manager = manager(&serving(&server, "sleep 0.3; exit 7"));
        let events = Arc::new(Mutex::new(Vec::new()));
        let sink = Arc::clone(&events);
        manager.set_listener(Box::new(move |status| {
            sink.lock().unwrap().push(status.clone())
        }));
        manager.start().unwrap();
        let started = Instant::now();
        while manager.status().state == Lifecycle::Ready
            && started.elapsed() < Duration::from_secs(3)
        {
            std::thread::sleep(Duration::from_millis(10));
        }
        let status = manager.status();
        assert_eq!(status.state, Lifecycle::Failed);
        assert_eq!(status.generation, 1);
        assert!(status.error.unwrap().message.contains("exit status 7"));
        assert!(manager.client().is_err());
        let states: Vec<_> = events
            .lock()
            .unwrap()
            .iter()
            .map(|status| status.state)
            .collect();
        assert_eq!(
            states,
            vec![Lifecycle::Starting, Lifecycle::Ready, Lifecycle::Failed]
        );
    }

    #[test]
    fn graceful_shutdown_uses_sigterm() {
        let server = HealthServer::start(true);
        let marker = std::env::temp_dir().join(format!("page-term-{}", std::process::id()));
        let _ = std::fs::remove_file(&marker);
        let rest = format!(
            "trap 'echo term > \"{}\"; exit 0' TERM; while :; do sleep 0.05; done",
            marker.display()
        );
        let manager = manager(&serving(&server, &rest));
        manager.start().unwrap();
        let pid = manager.process_id().unwrap();
        let started = Instant::now();
        manager.shutdown();
        assert!(started.elapsed() < Duration::from_millis(400));
        assert_eq!(std::fs::read_to_string(&marker).unwrap(), "term\n");
        assert!(!alive(pid));
        let _ = std::fs::remove_file(&marker);
    }

    #[test]
    fn ignored_sigterm_falls_back_to_kill() {
        let server = HealthServer::start(true);
        let manager = manager(&serving(
            &server,
            "trap '' TERM; while :; do sleep 0.05; done",
        ));
        manager.start().unwrap();
        let pid = manager.process_id().unwrap();
        let started = Instant::now();
        manager.shutdown();
        assert!(started.elapsed() >= Duration::from_millis(400));
        assert!(!alive(pid));
    }

    #[test]
    fn shutdown_rejects_new_work_and_is_idempotent() {
        let server = HealthServer::start(true);
        let manager = Arc::new(manager(&serving(&server, "exec sleep 30")));
        manager.start().unwrap();
        let lease = manager.client().unwrap();
        let other = Arc::clone(&manager);
        let shutdown = std::thread::spawn(move || other.shutdown());
        std::thread::sleep(Duration::from_millis(100));
        // In-flight work is allowed to settle before the child is stopped.
        assert_eq!(manager.status().state, Lifecycle::Ready);
        assert_eq!(manager.client().unwrap_err().code, "backend_stopping");
        drop(lease);
        shutdown.join().unwrap();
        manager.shutdown();
        assert_eq!(manager.status().state, Lifecycle::Stopped);
        assert_eq!(manager.start().unwrap_err().code, "backend_stopping");
        assert_eq!(manager.restart().unwrap_err().code, "backend_stopping");
    }
}
