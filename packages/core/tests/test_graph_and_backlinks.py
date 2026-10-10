from pathlib import Path

from fastapi.testclient import TestClient

from page_core.api import create_app
from page_core.service import KnowledgeService


def _client(vault: Path) -> TestClient:
    return TestClient(create_app(vault))


def test_backlinks_and_graph_include_isolated_notes(tmp_path: Path) -> None:
    service = KnowledgeService(tmp_path)
    source = service.create_note("Source", "Link to [[Target]] and [[Missing]].")
    target = service.create_note("Target", "No outgoing links.")
    isolated = service.create_note("Isolated", "Alone.")
    service.close()

    with _client(tmp_path) as client:
        backlinks = client.get("/api/note/backlinks", params={"id": target.id}).json()
        assert [item["source_id"] for item in backlinks] == [source.id]
        assert "[[Target]]" in backlinks[0]["excerpt"]

        graph = client.get("/api/graph").json()
        node_ids = {node["id"] for node in graph["nodes"]}
        assert node_ids == {source.id, target.id, isolated.id}
        assert graph["edges"] == [{"source": source.id, "target": target.id}]


def test_relationship_updates_after_edit_delete_and_restart(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        source = client.post("/api/notes", json={"title": "Source", "content": "[[Target]]"}).json()
        target = client.post("/api/notes", json={"title": "Target", "content": ""}).json()
        linked = client.get("/api/note/backlinks", params={"id": target["id"]}).json()
        assert [item["source_id"] for item in linked] == [source["id"]]

        client.put(
            "/api/note",
            params={"id": source["id"]},
            json={"content": "No links remain."},
        )
        assert client.get("/api/note/backlinks", params={"id": target["id"]}).json() == []
        assert client.get("/api/graph").json()["edges"] == []

        client.put(
            "/api/note",
            params={"id": source["id"]},
            json={"content": "Back to [[Target]]"},
        )
        client.delete("/api/note", params={"id": source["id"]})
        graph = client.get("/api/graph").json()
        assert graph["nodes"] == [{"id": target["id"], "title": "Target"}]
        assert graph["edges"] == []

    with _client(tmp_path) as restarted:
        rebuilt = restarted.get("/api/graph").json()
        assert rebuilt["nodes"] == [{"id": target["id"], "title": "Target"}]
        assert rebuilt["edges"] == []
        note = restarted.get("/api/note", params={"id": target["id"]})
        assert note.status_code == 200
