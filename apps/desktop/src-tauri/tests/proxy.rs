//! Proxy environment variables must not divert loopback API traffic. This is
//! its own test binary because it changes process environment variables.

use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Duration;

use page_desktop_lib::api::CoreApiClient;

const TOKEN: &str = "PageTestToken_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx";

fn counting_server(body: &'static str) -> (u16, Arc<AtomicUsize>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    let count = Arc::new(AtomicUsize::new(0));
    let seen = Arc::clone(&count);
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(mut stream) = stream else { return };
            let mut buffer = [0u8; 4096];
            let _ = stream.read(&mut buffer);
            seen.fetch_add(1, Ordering::SeqCst);
            let reply = format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = stream.write_all(reply.as_bytes());
        }
    });
    (port, count)
}

#[test]
fn proxy_environment_is_ignored() {
    let (proxy_port, proxy_hits) = counting_server("[]");
    let (api_port, api_hits) = counting_server("[]");
    let proxy = format!("http://127.0.0.1:{proxy_port}");
    for name in ["HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"] {
        // SAFETY: this binary contains a single test, so no thread reads the environment concurrently.
        unsafe { std::env::set_var(name, &proxy) };
    }
    for name in ["NO_PROXY", "no_proxy"] {
        unsafe { std::env::remove_var(name) };
    }
    let client = CoreApiClient::new(api_port, TOKEN).unwrap();
    assert!(client.list_vaults().unwrap().is_empty());
    std::thread::sleep(Duration::from_millis(50));
    assert_eq!(api_hits.load(Ordering::SeqCst), 1);
    assert_eq!(proxy_hits.load(Ordering::SeqCst), 0);
}
