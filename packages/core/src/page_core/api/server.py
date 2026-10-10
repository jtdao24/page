"""Standalone loopback runner: ``python -m page_core.api [--port PORT]``.

Binds 127.0.0.1 first, then prints one JSON bootstrap line with the actual
port and a fresh session token to stdout, then serves one Uvicorn process.
Diagnostics go to stderr. The bootstrap line is a credential, not a readiness
signal: clients confirm readiness with an authenticated health request.
"""

import argparse
import json
import re
import signal
import socket
import sys
from collections.abc import Sequence

import uvicorn

from .app import create_app
from .security import generate_token

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
_BACKLOG = 128

# Only stderr diagnostics; no access log, so URLs are never logged.
_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(levelname)s: %(message)s"}},
    "handlers": {"stderr": {"class": "logging.StreamHandler", "formatter": "plain", "stream": "ext://sys.stderr"}},
    "loggers": {
        "uvicorn": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": [], "level": "CRITICAL", "propagate": False},
        "page_core.api": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
    },
}


def _port(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,5}", value) or int(value) > 65535:
        raise argparse.ArgumentTypeError("must be an integer from 0 to 65535")
    return int(value)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m page_core.api", allow_abbrev=False,
        description=f"Serve the Page Core local API on {HOST} only.")
    parser.add_argument("--port", type=_port, default=DEFAULT_PORT,
                        help=f"TCP port on {HOST}; 0 lets the OS choose (default: {DEFAULT_PORT})")
    return parser.parse_args(argv)


def bind(port: int) -> socket.socket:
    """Bind and listen on the literal loopback address, without fallback.

    SO_REUSEADDR is deliberately not set, so an occupied port always fails.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((HOST, port))
        sock.listen(_BACKLOG)
    except BaseException:
        sock.close()
        raise
    return sock


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        sock = bind(args.port)
    except OSError as exc:
        print(f"page_core.api: cannot listen on {HOST}:{args.port}: {exc.strerror or 'error'}", file=sys.stderr)
        return 1
    try:
        token = generate_token()
        config = uvicorn.Config(
            create_app(session_token=token),
            host=HOST, port=sock.getsockname()[1], http="h11", loop="asyncio", ws="none",
            lifespan="on", reload=False, workers=1, proxy_headers=False, forwarded_allow_ips="",
            access_log=False, server_header=False, log_config=_LOG_CONFIG, env_file=None,
        )
        server = uvicorn.Server(config)
        bootstrap = {"host": HOST, "port": sock.getsockname()[1], "token": token}
        sys.stdout.write(json.dumps(bootstrap, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        # SIGTERM, like Ctrl+C, ends with KeyboardInterrupt once Uvicorn has
        # finished its graceful shutdown and the lifespan closed every vault.
        signal.signal(signal.SIGTERM, signal.default_int_handler)
        try:
            server.run(sockets=[sock])
        except KeyboardInterrupt:
            return 0
        return 0 if server.started else 1
    finally:
        sock.close()
