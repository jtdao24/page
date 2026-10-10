"""Gemini adapter: request shape, response parsing, error mapping, no key leaks."""
import io
import json
import urllib.error

import pytest

from page_core.llm import (
    DEFAULT_GEMINI_MODEL, GeminiModel, Generation, LLMAuthError, LLMBlockedError, LLMRateLimitError,
    LLMResponseError, LLMUnavailableError,
)

KEY = "test-key-should-never-leak-123"


class FakeOpener:
    def __init__(self, payload=None, error=None):
        self.payload, self.error, self.requests = payload, error, []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        body = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        return io.BytesIO(body)


def ok(text="An answer [1].", finish="STOP", usage=None):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
            "usageMetadata": usage if usage is not None else {"promptTokenCount": 120, "candidatesTokenCount": 9}}


def model(opener, name=DEFAULT_GEMINI_MODEL):
    return GeminiModel(KEY, name, timeout=12.5, opener=opener)


def test_request_shape_and_key_in_header_only():
    opener = FakeOpener(ok())
    result = model(opener).generate("system rules", "the prompt", max_output_tokens=256)

    assert result == Generation("An answer [1].", 120, 9, "STOP")
    (request, timeout), = opener.requests
    assert timeout == 12.5
    assert request.get_method() == "POST"
    assert request.full_url == ("https://generativelanguage.googleapis.com/v1beta/models/"
                                f"{DEFAULT_GEMINI_MODEL}:generateContent")
    assert KEY not in request.full_url
    assert request.get_header("X-goog-api-key") == KEY
    body = json.loads(request.data)
    assert body["systemInstruction"] == {"parts": [{"text": "system rules"}]}
    assert body["contents"] == [{"role": "user", "parts": [{"text": "the prompt"}]}]
    assert body["generationConfig"] == {"temperature": 0.2, "maxOutputTokens": 256}


def test_multiple_parts_and_missing_usage():
    payload = {"candidates": [{"content": {"parts": [{"text": "a"}, {"text": "b"}]}}]}
    assert model(FakeOpener(payload)).generate("s", "p", max_output_tokens=5) == Generation("ab", 0, 0, "STOP")


@pytest.mark.parametrize(("status", "error"), [
    (400, LLMResponseError), (401, LLMAuthError), (403, LLMAuthError), (404, LLMResponseError),
    (429, LLMRateLimitError), (500, LLMUnavailableError), (503, LLMUnavailableError),
])
def test_http_errors_are_mapped_without_leaking(status, error):
    body = io.BytesIO(f'{{"error": "{KEY} the prompt"}}'.encode())
    http = urllib.error.HTTPError("https://example", status, "boom", {}, body)
    with pytest.raises(error) as raised:
        model(FakeOpener(error=http)).generate("s", "the prompt", max_output_tokens=5)
    assert KEY not in str(raised.value) and "the prompt" not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("failure", [urllib.error.URLError("dns"), TimeoutError(), ConnectionResetError()])
def test_network_failures_are_unavailable(failure):
    with pytest.raises(LLMUnavailableError):
        model(FakeOpener(error=failure)).generate("s", "p", max_output_tokens=5)


@pytest.mark.parametrize(("payload", "error"), [
    (b"not json", LLMResponseError),
    ({"promptFeedback": {"blockReason": "SAFETY"}}, LLMBlockedError),
    ({"candidates": []}, LLMResponseError),
    ({"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}, LLMBlockedError),
    ({"candidates": [{"content": {"parts": [{"text": "  "}]}, "finishReason": "STOP"}]}, LLMResponseError),
    ([1, 2], LLMResponseError),
])
def test_unusable_responses(payload, error):
    with pytest.raises(error):
        model(FakeOpener(payload)).generate("s", "p", max_output_tokens=5)


def test_from_environment():
    assert GeminiModel.from_environment({}) is None
    assert GeminiModel.from_environment({"GEMINI_API_KEY": "  "}) is None
    assert GeminiModel.from_environment({"GEMINI_API_KEY": KEY}).name == DEFAULT_GEMINI_MODEL
    assert GeminiModel.from_environment({"GEMINI_API_KEY": KEY, "PAGE_GEMINI_MODEL": "gemini-3.8-flash"}).name == "gemini-3.8-flash"
    with pytest.raises(ValueError):
        GeminiModel.from_environment({"GEMINI_API_KEY": KEY, "PAGE_GEMINI_MODEL": "../x?key=1"})


def test_key_never_appears_in_repr_and_inputs_are_validated():
    gemini = model(FakeOpener(ok()))
    assert KEY not in repr(gemini) and KEY not in str(vars(gemini).get("name"))
    with pytest.raises(ValueError):
        gemini.generate("s", "p", max_output_tokens=0)
    with pytest.raises(ValueError):
        gemini.generate("s", "p", max_output_tokens=True)
