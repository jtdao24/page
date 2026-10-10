"""Graph endpoints use real storage, canonical UUIDs and authenticated sessions."""
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from api_support import (API, app, client, vault, create_note, notes_url,
                         if_match, assert_error, posix_only, source_files)

__all__ = ['app', 'client', 'vault']
pytestmark = posix_only


def graph(client: TestClient, vault: dict[str, Any]) -> dict[str, Any]:
    response = client.get(f"{API}/vaults/{vault['id']}/graph")
    assert response.status_code == 200, response.text
    return response.json()


def test_crud_and_external_changes_update_canonical_graph(client: TestClient, vault: dict[str, Any]) -> None:
    a = create_note(client, vault, 'a.md', '[[b|B]] [[missing]]')
    b = create_note(client, vault, 'b.md')
    root = Path(vault['root_path'])
    before = source_files(root)
    snapshot = graph(client, vault)
    assert snapshot['vault_id'] == vault['id']
    assert {n['id'] for n in snapshot['nodes']} == {a['id'], b['id']}
    assert snapshot['links'][0]['target_note_id'] == b['id']
    assert snapshot['links'][0]['alias'] == 'B'
    assert snapshot['links'][1]['unresolved_reason'] == 'missing'
    assert source_files(root) == before
    moved = client.post(notes_url(vault, b['id'])+'/move', json={'relative_path':'nested/b.md'}, headers=if_match(b['revision']))
    assert moved.status_code == 200
    assert graph(client, vault)['links'][0]['target_note_id'] == b['id']
    deleted = client.delete(notes_url(vault, b['id']), headers=if_match(moved.json()['revision']))
    assert deleted.status_code == 204
    assert graph(client, vault)['links'][0]['target_note_id'] is None
    (root/'missing.md').write_text('[[a]]', encoding='utf-8')
    assert graph(client, vault)['links'][1]['target_note_id'] is not None
    (root/'a.md').write_text('no links', encoding='utf-8')
    assert len(graph(client, vault)['links']) == 1
    assert graph(client, vault)['links'][0]['target_note_id'] == a['id']


def test_empty_reopen_and_source_fidelity(client: TestClient, vault: dict[str, Any]) -> None:
    assert graph(client, vault) == {'vault_id':vault['id'], 'nodes':[], 'links':[]}
    a = create_note(client, vault, '日本語.md', '\ufeff[[日本語]]\r\n')
    snapshot = graph(client, vault)
    assert client.delete(f"{API}/vaults/{vault['id']}").status_code == 204
    assert client.post(f'{API}/vaults/open', json={'root_path':vault['root_path']}).status_code == 200
    assert graph(client, vault) == snapshot
    assert Path(vault['root_path'], '日本語.md').read_bytes() == '\ufeff[[日本語]]\r\n'.encode()
    assert snapshot['links'][0]['target_note_id'] == a['id']


def test_graph_requires_open_vault_and_valid_identifier(client: TestClient, vault: dict[str, Any]) -> None:
    assert_error(client.get(f'{API}/vaults/not-a-uuid/graph'),422,'validation_error')
    client.delete(f"{API}/vaults/{vault['id']}")
    assert_error(client.get(f"{API}/vaults/{vault['id']}/graph"),404,'vault_not_found')
