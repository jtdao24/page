"""POST /vaults/{id}/ask: grounded answers through the local API."""
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api_support import API, TOKEN, client, create_note, posix_only, vault
from page_core.api import create_app
from page_core.llm import Generation, LLMAuthError, LLMRateLimitError, LLMUnavailableError
from test_semantic import CountingEncoder

__all__ = ["client", "vault"]
pytestmark = posix_only


class FakeModel:
    name = "fake-gemini"

    def __init__(self):
        self.calls, self.error, self.reply = [], None, "Fruit notes say apples [1]."

    def generate(self, system, prompt, *, max_output_tokens):
        self.calls.append(prompt)
        if self.error:
            raise self.error
        return Generation(self.reply, 200, 12, "STOP")


@pytest.fixture
def model():
    return FakeModel()


@pytest.fixture
def app(model, monkeypatch):
    from page_core.api import service
    encoder = CountingEncoder()
    monkeypatch.setattr(service, "SentenceEncoder", lambda: encoder)
    return create_app(session_token=TOKEN, chat_model=model)


def ask(client: TestClient, vault: dict[str, Any], **body):
    return client.post(f"{API}/vaults/{vault['id']}/ask", json=body)


def test_ask_returns_a_grounded_cited_answer(client, vault, model):
    note = create_note(client, vault, "fruit.md", "fruit apples are sweet\n\nspace stars are far")
    response = ask(client, vault, question="fruit apples?", budget=400)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["model"] == "fake-gemini" and data["answered_by_model"] is True
    assert data["answer"] == "Fruit notes say apples [1]."
    assert data["cited"] == [1]
    source = data["sources"][0]
    assert source["number"] == 1 and source["note_id"] == note["id"] and source["relative_path"] == "fruit.md"
    assert "fruit apples" in source["text"]
    usage = data["usage"]
    assert usage["budget"] == 400 and 0 < usage["context_tokens"] <= 400
    assert (usage["input_tokens"], usage["output_tokens"], usage["counter"]) == (200, 12, "utf8-bytes/3")
    (prompt,) = model.calls
    assert "Question: fruit apples?" in prompt and "fruit.md" in prompt


def test_empty_vault_answers_without_calling_the_model(client, vault, model):
    response = ask(client, vault, question="anything?")
    assert response.status_code == 200, response.text
    assert response.json()["answered_by_model"] is False and response.json()["sources"] == []
    assert model.calls == []


def test_unconfigured_model_is_refused(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from api_support import client_for
    with client_for(create_app(session_token=TOKEN)) as unconfigured:
        created = unconfigured.post(f"{API}/vaults", json={"root_path": str(tmp_path / "v"), "name": "V"})
        response = unconfigured.post(f"{API}/vaults/{created.json()['id']}/ask", json={"question": "q"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "llm_not_configured"


@pytest.mark.parametrize(("error", "status", "code"), [
    (LLMAuthError("x"), 502, "llm_auth_failed"),
    (LLMRateLimitError("x"), 429, "llm_rate_limited"),
    (LLMUnavailableError("x"), 503, "llm_unavailable"),
])
def test_provider_errors_are_translated(client, vault, model, error, status, code):
    create_note(client, vault, "fruit.md", "fruit apples")
    model.error = error
    response = ask(client, vault, question="fruit?")
    assert response.status_code == status and response.json()["error"]["code"] == code
    assert "fruit apples" not in response.text


@pytest.mark.parametrize("body", [{}, {"question": " "}, {"question": "q", "budget": 10},
                                  {"question": "q", "budget": "500"}, {"question": "q", "extra": 1},
                                  {"question": "x" * 2001}])
def test_invalid_requests_are_rejected(client, vault, model, body):
    response = ask(client, vault, **body)
    assert response.status_code == 422
    assert model.calls == []


def test_unknown_vault(client, model):
    response = client.post(f"{API}/vaults/00000000-0000-4000-8000-000000000000/ask", json={"question": "q"})
    assert response.status_code == 404 and model.calls == []


def test_ask_reports_the_whole_vault_size_for_comparison(client, vault):
    import math
    contents = ["fruit apples are sweet\n\nspace stars are far", "unrelated " * 200]
    for index, content in enumerate(contents):
        create_note(client, vault, f"n{index}.md", content)
    usage = ask(client, vault, question="fruit apples?", budget=200).json()["usage"]
    assert usage["vault_tokens"] == sum(math.ceil(len(text.encode()) / 3) for text in contents)
    assert usage["context_tokens"] < usage["vault_tokens"]
