import asyncio
import gc
import http.client
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from page_core.api.app import _submit

pytestmark = pytest.mark.skipif(os.name != "posix", reason="signal-based shutdown is exercised on POSIX")

DEADLINE = 20.0


def launch(*args: str, env: dict[str, str] | None = None) -> subprocess.Popen[str]:
    return subprocess.Popen([sys.executable, "-m", "page_core.api", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env={**os.environ, **(env or {})})


def read_bootstrap(process: subprocess.Popen[str]) -> dict[str, Any]:
    assert process.stdout is not None
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(DEADLINE), "no bootstrap line before the deadline"
    line = process.stdout.readline()
    assert line.endswith("\n")
    return json.loads(line)


def request(port: int, token: str, path: str = "/api/v1/health",
            headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    deadline = time.monotonic() + DEADLINE
    while True:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=DEADLINE)
        try:
            connection.request("GET", path, headers={"Authorization": f"Bearer {token}", **(headers or {})})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        except ConnectionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)
        finally:
            connection.close()


def stop(process: subprocess.Popen[str], sig: signal.Signals) -> tuple[str, str]:
    process.send_signal(sig)
    stdout, stderr = process.communicate(timeout=DEADLINE)
    return stdout, stderr


@pytest.fixture
def server() -> Iterator[subprocess.Popen[str]]:
    process = launch("--port", "0", env={"WEB_CONCURRENCY": "3", "FORWARDED_ALLOW_IPS": "*"})
    try:
        yield process
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=DEADLINE)


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_runner_serves_authenticated_loopback_and_shuts_down(server: subprocess.Popen[str], sig: signal.Signals) -> None:
    bootstrap = read_bootstrap(server)
    assert set(bootstrap) == {"host", "port", "token"}
    assert bootstrap["host"] == "127.0.0.1" and 0 < bootstrap["port"] <= 65535
    assert len(bootstrap["token"]) == 43
    port, token = bootstrap["port"], bootstrap["token"]

    status, body = request(port, token)
    assert status == 200 and body["status"] == "ok"
    assert request(port, "wrong-token")[0] == 401
    assert request(port, token, headers={"Origin": "null"})[0] == 403
    # Proxy headers are never trusted, even with FORWARDED_ALLOW_IPS=*.
    assert request(port, token, headers={"X-Forwarded-For": "192.168.1.9"})[0] == 200
    with socket.create_connection(("127.0.0.1", port), timeout=DEADLINE) as probe:
        assert probe.getpeername() == ("127.0.0.1", port)

    stdout, stderr = stop(server, sig)
    assert server.returncode == 0, stderr
    assert stdout == ""
    assert token not in stderr
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=DEADLINE).close()


@pytest.mark.parametrize("args", [
    ["--port", "70000"], ["--port", "-1"], ["--port", "abc"], ["--port", "1.5"], ["--port", ""],
    ["--port", "0x10"], ["--host", "0.0.0.0"], ["--reload"], ["--workers", "2"], ["--po", "0"], ["extra"],
])
def test_invalid_arguments_exit_nonzero_without_credentials(args: list[str]) -> None:
    process = launch(*args)
    stdout, stderr = process.communicate(timeout=DEADLINE)
    assert process.returncode == 2
    assert stdout == ""
    assert "usage:" in stderr


def test_occupied_port_fails_without_fallback() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        process = launch("--port", str(port))
        stdout, stderr = process.communicate(timeout=DEADLINE)
    assert process.returncode == 1
    assert stdout == ""
    assert f"127.0.0.1:{port}" in stderr


def test_cancelled_storage_job_failure_is_never_logged_by_asyncio() -> None:
    reported: list[dict[str, object]] = []
    release = threading.Event()

    def job() -> None:
        release.wait(5)
        raise RuntimeError("secret note text")

    async def scenario() -> None:
        asyncio.get_running_loop().set_exception_handler(lambda loop, context: reported.append(context))
        with ThreadPoolExecutor(max_workers=1) as executor:
            waiting = asyncio.ensure_future(_submit(executor, job))
            await asyncio.sleep(0.05)
            waiting.cancel()
            release.set()
            await asyncio.sleep(0.2)
        gc.collect()
        await asyncio.sleep(0)

    asyncio.run(scenario())

    assert reported == []
