"""Opt-in real-model integration test; normal tests never download models."""

import os
from importlib.util import find_spec
from pathlib import PurePosixPath

import pytest


@pytest.mark.skipif(os.environ.get("PAGE_TEST_MODEL") != "1", reason="set PAGE_TEST_MODEL=1 for real MiniLM validation")
def test_real_minilm_token_budget_normalization_and_background(fs_vault):
    np = pytest.importorskip("numpy")
    if find_spec("faiss") is None or find_spec("torch") is None:
        pytest.skip("install the ingestion extra")
    from page_core.ingestion.chunking import chunk_markdown
    from page_core.ingestion.embedding import MiniLM
    from page_core.ingestion.index import IngestionIndex

    model = MiniLM()
    assert model.model is MiniLM().model
    note = fs_vault.create_note(PurePosixPath("cats.md"),
        "# Cats\n" + "Cats are domesticated mammals. " * 200 + "\n## Habitat\nCats live indoors.\n")
    spans = chunk_markdown(note.id, note.content, model.tokenizer)
    assert len(spans) > 1
    assert all(len(model.tokenizer.encode(s.chunk.text, verbose=False)) <= model.model.max_seq_length for s in spans)
    vectors = model.encode([s.chunk.text for s in spans])
    assert vectors.shape == (len(spans), 384)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)
    index = IngestionIndex(fs_vault, model)
    assert index.start()
    index.wait(60)
    assert index.status()["state"] == "complete", index.status()
    result = index.search(spans[0].chunk.text)[0]
    assert result["score"] == pytest.approx(1, abs=1e-5)
    assert result["note_id"] == str(note.id)
