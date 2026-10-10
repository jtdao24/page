"""Local-request and bearer-token checks for the whole application.

``LocalAccessMiddleware`` wraps every HTTP request, including unknown routes,
unsupported methods, OPTIONS and the OpenAPI document. It inspects raw ASGI
headers, so duplicate headers are never collapsed, and rejects a request
before its body is read or any storage work is scheduled. It also adds
``Cache-Control: no-store`` to every response and turns unexpected failures
into a safe 500 envelope instead of a traceback.
"""

import ipaddress
import re
import secrets
from collections.abc import MutableMapping
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import ApiError, error_response, internal_error, logger

_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_HOST = re.compile(r"(?:127\.0\.0\.1|localhost)(?::([1-9][0-9]{0,4}))?", re.IGNORECASE)


def generate_token() -> str:
    """A fresh credential from 32 random bytes; kept only in memory."""
    return secrets.token_urlsafe(32)


def validate_token(token: object) -> str:
    """Accept exactly 43 URL-safe ASCII characters, as from ``token_urlsafe(32)``."""
    if not isinstance(token, str):
        raise TypeError(f"session_token must be str, got {type(token).__name__}")
    if not _TOKEN.fullmatch(token):
        raise ValueError("session_token must be 43 URL-safe characters from 32 random bytes")
    return token


def _headers(scope: Scope, name: bytes) -> list[bytes]:
    return [value for key, value in scope.get("headers", ()) if key.lower() == name]


def _loopback_peer(scope: Scope) -> bool:
    client = scope.get("client")
    if not client:
        return False
    try:
        address = ipaddress.ip_address(client[0])
    except (TypeError, ValueError, IndexError):
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback


def _valid_host(values: list[bytes]) -> bool:
    if len(values) != 1:
        return False
    try:
        host = values[0].decode("ascii")
    except UnicodeDecodeError:
        return False
    match = _HOST.fullmatch(host)
    return match is not None and (match.group(1) is None or int(match.group(1)) <= 65535)


def _authorized(values: list[bytes], expected: bytes) -> bool:
    if len(values) != 1:
        return False
    scheme, separator, credential = values[0].partition(b" ")
    if not separator or scheme.lower() != b"bearer" or not credential:
        return False
    # Compare even malformed credentials in constant time against the token.
    return secrets.compare_digest(credential, expected)


class LocalAccessMiddleware:
    """Reject non-local, cross-origin or unauthenticated requests."""

    def __init__(self, app: ASGIApp, *, token: str) -> None:
        self.app = app
        self._token = validate_token(token).encode("ascii")

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        rejection = self._reject(scope)
        if rejection is not None:
            await _send_error(rejection, send)
            return
        started = False

        async def send_no_store(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message = _with_no_store(message)
            await send(message)

        try:
            await self.app(scope, receive, send_no_store)
        except Exception as exc:
            logger.error("internal_error: %s", type(exc).__name__)
            if not started:
                await _send_error(internal_error(), send)

    def _reject(self, scope: Scope) -> ApiError | None:
        if not _loopback_peer(scope):
            return ApiError(403, "local_access_required", "Only loopback clients may use this API.")
        if not _valid_host(_headers(scope, b"host")):
            return ApiError(400, "invalid_host", "The Host header must name 127.0.0.1 or localhost.")
        if _headers(scope, b"origin"):
            return ApiError(403, "origin_not_allowed", "Browser origins are not allowed.")
        if not _authorized(_headers(scope, b"authorization"), self._token):
            return ApiError(401, "unauthorized", "A valid bearer token is required.",
                            headers={"WWW-Authenticate": "Bearer"})
        return None


def _with_no_store(message: Message) -> MutableMapping[str, Any]:
    headers = [(key, value) for key, value in message.get("headers", ())
               if key.lower() != b"cache-control"]
    headers.append((b"cache-control", b"no-store"))
    return {**message, "headers": headers}


async def _send_error(error: ApiError, send: Send) -> None:
    response = error_response(error)

    async def send_no_store(message: Message) -> None:
        if message["type"] == "http.response.start":
            message = _with_no_store(message)
        await send(message)

    await response({"type": "http"}, _never_receive, send_no_store)


async def _never_receive() -> Message:
    raise RuntimeError("error responses do not read the request")
