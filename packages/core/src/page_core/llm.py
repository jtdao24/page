"""Provider-neutral LLM interface and a Gemini implementation.

Page Core depends only on ``ChatModel``; Gemini is one adapter. The Gemini
client uses the standard library, reads its key from the environment, sends it
in a header (never a URL), and never logs or repeats the key, prompt or reply
in errors.
"""

import functools
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_MODEL_NAME = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")


class LLMError(Exception):
    """Base class for language-model failures. Messages are always generic."""


class LLMNotConfiguredError(LLMError):
    """No API key is configured, so no model can be called."""


class LLMAuthError(LLMError):
    """The provider rejected the API key."""


class LLMRateLimitError(LLMError):
    """The provider's rate limit or quota was reached."""


class LLMUnavailableError(LLMError):
    """The provider could not be reached or failed."""


class LLMBlockedError(LLMError):
    """The provider refused the request or reply for safety reasons."""


class LLMResponseError(LLMError):
    """The provider rejected the request or returned an unusable response."""


@dataclass(frozen=True, slots=True)
class Generation:
    text: str
    input_tokens: int
    output_tokens: int
    finish_reason: str


class ChatModel(Protocol):
    name: str

    def generate(self, system: str, prompt: str, *, max_output_tokens: int) -> Generation: ...


Opener = Callable[..., Any]


@functools.cache
def _tls_context() -> ssl.SSLContext:
    # python.org and python-build-standalone builds on macOS find no system CA
    # certificates, so use certifi's bundle (a dependency) to verify Gemini.
    import certifi
    return ssl.create_default_context(cafile=certifi.where())


def https_open(request: urllib.request.Request, *, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout, context=_tls_context())


class GeminiModel:
    """Gemini ``generateContent`` over HTTPS, with no SDK dependency."""

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL, *, timeout: float = 60.0,
                 opener: Opener = https_open) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise LLMNotConfiguredError("an API key is required")
        if not isinstance(model, str) or not _MODEL_NAME.fullmatch(model):
            raise ValueError("model must be a Gemini model ID such as gemini-3.5-flash-lite")
        self._key = api_key.strip()
        self.name = model
        self._timeout = timeout
        self._open = opener

    def __repr__(self) -> str:
        return f"GeminiModel(model={self.name!r})"

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] = os.environ) -> "GeminiModel | None":
        """``GEMINI_API_KEY`` (required) and ``PAGE_GEMINI_MODEL`` (optional)."""
        key = environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            return None
        return cls(key, environ.get("PAGE_GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL)

    def generate(self, system: str, prompt: str, *, max_output_tokens: int) -> Generation:
        if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or max_output_tokens < 1:
            raise ValueError("max_output_tokens must be a positive int")
        body = json.dumps({
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_output_tokens},
        }).encode("utf-8")
        request = urllib.request.Request(
            GEMINI_ENDPOINT.format(model=self.name), data=body, method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": self._key},
        )
        try:
            with self._open(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise _http_error(exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise LLMUnavailableError("Gemini could not be reached") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise LLMResponseError("Gemini returned an unreadable response") from None
        return _parse(payload)


def _http_error(status: int) -> LLMError:
    if status in (401, 403):
        return LLMAuthError("Gemini rejected the API key")
    if status == 429:
        return LLMRateLimitError("Gemini rate limit or quota reached")
    if status >= 500:
        return LLMUnavailableError(f"Gemini failed (HTTP {status})")
    # 400 covers malformed requests and, for Gemini, invalid API keys; 404 an unknown model.
    return LLMResponseError(f"Gemini rejected the request (HTTP {status})")


def _parse(payload: object) -> Generation:
    if not isinstance(payload, dict):
        raise LLMResponseError("Gemini returned an unexpected response")
    feedback = payload.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        raise LLMBlockedError("Gemini blocked the request")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
        raise LLMResponseError("Gemini returned no answer")
    candidate = candidates[0]
    finish = str(candidate.get("finishReason") or "STOP")
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    text = "".join(part["text"] for part in parts or [] if isinstance(part, dict) and isinstance(part.get("text"), str))
    if not text.strip():
        if finish in ("SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"):
            raise LLMBlockedError("Gemini withheld the answer")
        raise LLMResponseError("Gemini returned an empty answer")
    usage = payload.get("usageMetadata")
    usage = usage if isinstance(usage, dict) else {}

    def count(key: str) -> int:
        value = usage.get(key, 0)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    return Generation(text, count("promptTokenCount"), count("candidatesTokenCount"), finish)
