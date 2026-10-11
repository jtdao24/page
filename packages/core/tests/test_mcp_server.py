"""MCP server: tools invoked through a real in-process MCP client."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from mcp import Client

from api_support import posix_only
from page_core import mcp_server
from page_core.api import service
from page_core.mcp_server import PageVaultTools, create_server
from page_core.metadata import PersistentVault
from test_semantic import CountingEncoder

pytestmark = posix_only


@pytest.fixture
def encoder(monkeypatch):
    encoder = CountingEncoder()
    monkeypatch.setattr(service, "SentenceEncoder", lambda: encoder)
    return encoder


@pytest.fixture
def root(tmp_path: Path) -> Path:
    PersistentVault.create(tmp_path / "vault", "Garden").close()
    notes = {
        "fruit.md": "# Fruit\n\nfruit apples are sweet and crisp\n\nSee [[space]] and [[nowhere]].\n",
        "space.md": "# Space\n\nspace stars are far away\n",
        "plans/trip.md": "Trip notes link to [[space]].\n",
    }
    for path, text in notes.items():
        (tmp_path / "vault" / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "vault" / path).write_text(text, encoding="utf-8")
    return tmp_path / "vault"


@pytest.fixture
def tools(root, encoder):
    tools = PageVaultTools(root)
    yield tools
    tools.close()


def call(tools: PageVaultTools, name: str, **arguments: Any):
    async def run():
        async with Client(create_server(tools)) as client:
            return await client.call_tool(name, arguments)
    return asyncio.run(run())


def ok(tools: PageVaultTools, name: str, **arguments: Any) -> dict[str, Any]:
    result = call(tools, name, **arguments)
    assert not result.is_error, result.content
    assert json.loads(result.content[0].text) == result.structured_content
    return result.structured_content


def error(tools: PageVaultTools, name: str, **arguments: Any) -> str:
    result = call(tools, name, **arguments)
    assert result.is_error
    text = result.content[0].text
    prefix = f"Error executing tool {name}: "
    return text.removeprefix(prefix)


def test_tools_are_listed_read_only_with_schemas(tools):
    async def run():
        async with Client(create_server(tools)) as client:
            return (await client.list_tools()).tools
    listed = {tool.name: tool for tool in asyncio.run(run())}
    assert set(listed) == {"search_notes", "get_context", "read_note", "related_notes"}
    for tool in listed.values():
        assert tool.annotations.read_only_hint is True and tool.annotations.destructive_hint is False
        assert tool.description and tool.output_schema
    budget = listed["get_context"].input_schema["properties"]["budget"]
    assert (budget["minimum"], budget["maximum"], budget["default"]) == (50, 20000, 1500)


def test_search_returns_passages_with_source_references(tools):
    results = ok(tools, "search_notes", query="fruit apples", limit=2)["results"]
    assert len(results) == 2
    top = results[0]
    assert top["path"] == "fruit.md" and "fruit apples" in top["text"]
    assert top["start_line"] == 3 and top["end_line"] >= 3 and 0 < top["score"] <= 1


def test_get_context_respects_the_budget_and_numbers_sources(tools):
    data = ok(tools, "get_context", question="fruit apples?", budget=60)
    usage = data["usage"]
    assert usage["budget"] == 60 and 0 < usage["tokens"] <= 60 and usage["counter"] == "utf8-bytes/3"
    assert usage["selected"] == len(data["sources"]) >= 1
    first = data["sources"][0]
    assert first["number"] == 1 and first["path"] == "fruit.md"
    assert data["context"].startswith("[1] fruit.md") and first["text"] in data["context"]
    larger = ok(tools, "get_context", question="fruit apples?", budget=2000)
    assert larger["usage"]["tokens"] >= usage["tokens"]


def test_read_note_and_related_notes(tools, root):
    note = ok(tools, "read_note", path="fruit.md")
    assert note["content"] == (root / "fruit.md").read_text() and note["lines"] == 5
    assert len(note["revision"]) == 64
    related = ok(tools, "related_notes", path="fruit.md")
    assert related["path"] == "fruit.md" and related["note_id"] == note["note_id"]
    assert [(link["path"], link["unresolved"]) for link in related["links"]] == [("space.md", None), (None, "missing")]
    assert related["links"][0]["line"] == 5
    assert related["backlinks"] == []
    backlinks = ok(tools, "related_notes", path="space.md")["backlinks"]
    assert sorted((link["path"], link["line"]) for link in backlinks) == [("fruit.md", 5), ("plans/trip.md", 1)]


def test_notes_changed_outside_page_are_seen(tools, root):
    (root / "new.md").write_text("fresh fruit idea\n", encoding="utf-8")
    assert ok(tools, "read_note", path="new.md")["content"] == "fresh fruit idea\n"
    assert "new.md" in {hit["path"] for hit in ok(tools, "search_notes", query="fruit")["results"]}


def test_errors_are_tool_errors_with_safe_messages(tools, encoder, root):
    assert error(tools, "read_note", path="missing.md") == "note_not_found: No note at missing.md."
    for bad in ("../outside.md", "/etc/passwd", "notes.exe"):
        assert error(tools, "read_note", path=bad).startswith("invalid_path:")
    assert "budget" in error(tools, "get_context", question="fruit", budget=10)
    assert "query" in error(tools, "search_notes", query="")
    encoder.fail = True
    message = error(tools, "search_notes", query="fruit")
    assert message == "embedding_failed: Local embedding inference failed; try again."
    assert str(root) not in message


def test_tools_never_write_notes(tools, root):
    before = {path: path.read_bytes() for path in root.rglob("*.md")}
    ok(tools, "search_notes", query="fruit")
    ok(tools, "get_context", question="fruit")
    ok(tools, "related_notes", path="fruit.md")
    assert {path: path.read_bytes() for path in root.rglob("*.md")} == before


def test_empty_vault_returns_empty_results(tmp_path, encoder):
    PersistentVault.create(tmp_path / "empty", "Empty").close()
    tools = PageVaultTools(tmp_path / "empty")
    try:
        assert ok(tools, "search_notes", query="anything")["results"] == []
        data = ok(tools, "get_context", question="anything")
        assert data["sources"] == [] and data["usage"]["tokens"] == 0
    finally:
        tools.close()


def test_main_refuses_a_folder_that_is_not_a_vault(tmp_path, capsys):
    assert mcp_server.main(["--vault", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "cannot open vault" in captured.err


def test_stdio_server_serves_an_mcp_client(root):
    from mcp import StdioServerParameters

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "page_core.mcp_server", "--vault", str(root)])
        async with Client(params) as client:
            tools = (await client.list_tools()).tools
            note = await client.call_tool("read_note", {"path": "space.md"})
            return {tool.name for tool in tools}, note
    names, note = asyncio.run(run())
    assert "get_context" in names
    assert note.structured_content["content"] == "# Space\n\nspace stars are far away\n"


def test_importing_the_server_does_not_import_torch():
    script = "import sys, page_core.mcp_server\nprint('torch' in sys.modules)\n"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


def test_deleted_notes_are_not_found(tools, root):
    assert ok(tools, "read_note", path="space.md")
    (root / "space.md").unlink()
    assert error(tools, "read_note", path="space.md") == "note_not_found: No note at space.md."


def test_oversized_passages_are_returned_as_marked_excerpts(tools, root):
    sentences = " ".join(f"fruit sentence {n} about orchards." for n in range(60))
    (root / "long.md").write_text(sentences + "\n", encoding="utf-8")
    data = ok(tools, "get_context", question="fruit orchards", budget=60)
    assert data["usage"]["tokens"] <= 60
    long = [source for source in data["sources"] if source["path"] == "long.md"]
    assert long and long[0]["excerpt"] is True and len(long[0]["text"]) < len(sentences)


def test_sources_are_searchable_and_readable(tools, root):
    from test_sources import make_pdf
    (root / "papers").mkdir()
    (root / "papers" / "fruit.pdf").write_bytes(make_pdf(["fruit orchard yields"]))
    results = ok(tools, "search_notes", query="fruit orchard", limit=5)["results"]
    assert {(hit["path"], hit["kind"]) for hit in results} >= {("papers/fruit.pdf", "pdf"), ("fruit.md", "note")}
    pdf = ok(tools, "read_note", path="papers/fruit.pdf")
    assert (pdf["kind"], pdf["content"]) == ("pdf", "[Page 1]\nfruit orchard yields\n")
    assert ok(tools, "read_note", path="fruit.md")["kind"] == "note"
    assert error(tools, "read_note", path="papers/missing.pdf") == "source_not_found: No readable file at papers/missing.pdf."
