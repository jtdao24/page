from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from api_support import API, app, client, vault, create_note, notes_url, if_match, assert_error, posix_only, source_files
from page_core.semantic import ModelUnavailableError
from test_semantic import CountingEncoder

__all__ = ['app', 'client', 'vault']
pytestmark = posix_only


@pytest.fixture(autouse=True)
def encoder(monkeypatch):
    from page_core.api import service
    value = CountingEncoder()
    monkeypatch.setattr(service, 'SentenceEncoder', lambda: value)
    return value


def test_api_incremental_source_ids_disk_changes_and_reopen(client: TestClient, vault: dict[str, Any]):
    a = create_note(client, vault, '日本語.md', 'fruit 😀\r\n\r\nspace stars')
    root = Path(vault['root_path'])
    before = source_files(root)
    url = f"{API}/vaults/{vault['id']}"
    first = client.post(url+'/index', json={})
    assert first.status_code == 200, first.text
    assert first.json()['generated'] == 2
    assert client.post(url+'/index', json={}).json()['reused'] == 2
    search = client.post(url+'/search', json={'query':'fruit', 'limit':1})
    assert search.status_code == 200, search.text
    hit = search.json()['hits'][0]
    assert hit['note_id'] == a['id']
    assert hit['revision'] == a['revision']
    assert hit['start_line'] == 1
    assert a['content'].encode()[hit['start_byte']:hit['end_byte']].decode() == hit['text']
    assert source_files(root) == before
    client.delete(url)
    client.post(f'{API}/vaults/open', json={'root_path':str(root)})
    assert client.post(url+'/index', json={}).json()['generated'] == 0
    (root/'external.md').write_text('fruit bananas', encoding='utf-8')
    assert client.post(url+'/index', json={}).json()['generated'] == 1
    (root/'日本語.md').unlink()
    assert client.post(url+'/search', json={'query':'fruit'}).json()['hits'][0]['relative_path'] == 'external.md'
    client.delete(url)
    assert_error(client.post(url+'/search', json={'query':'fruit'}),404,'vault_not_found')


@pytest.mark.parametrize('body', [{'query':''}, {'query':'  '}, {'query':True}, {'query':'fruit','limit':True},
    {'query':'fruit','limit':0}, {'query':'fruit','limit':51}, {'query':'fruit','extra':1}, {'query':'x'*2001}])
def test_search_validation(client, vault, body):
    assert_error(client.post(f"{API}/vaults/{vault['id']}/search",json=body),422,'validation_error')


def test_safe_missing_model_and_failed_index(client, vault, monkeypatch):
    from page_core.api import service
    create_note(client, vault, 'a.md', 'fruit')
    def unavailable():
        raise ModelUnavailableError('secret path and credential')
    monkeypatch.setattr(service, 'SentenceEncoder', unavailable)
    response = client.post(f"{API}/vaults/{vault['id']}/search",json={'query':'fruit'})
    assert_error(response,503,'model_unavailable')
    assert 'secret' not in response.text


def test_empty_vault_does_not_require_model(client, vault, monkeypatch):
    from page_core.api import service
    def unavailable():
        raise AssertionError('empty vault must not load a model')
    monkeypatch.setattr(service, 'SentenceEncoder', unavailable)
    url = f"{API}/vaults/{vault['id']}"
    assert client.post(url+'/index', json={}).json()['chunks'] == 0
    assert client.post(url+'/search', json={'query':'fruit'}).json()['hits'] == []
