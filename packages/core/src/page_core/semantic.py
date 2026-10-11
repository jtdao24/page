"""Source-attributed, incremental semantic retrieval with an exact local baseline.

Only model setup downloads files. Ordinary inference uses a pinned local model;
imports and model loading are lazy so vault CRUD does not need a model installed.
"""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import UUID, uuid5

from page_core.domain import Chunk, Note, SourceDocument, validate_document_path
from page_core.metadata import MetadataRepository

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MAX_TOKENS = 220
DIMENSION = 384
FINGERPRINT = f"{MODEL}@{REVISION}:paragraph-v1:{MAX_TOKENS}:normalized-f32:{DIMENSION}"
# A plain folder holding the pinned model, used instead of the Hugging Face cache
# when set. The packaged app bundles one; ``export-model`` creates it.
MODEL_DIR_ENV = "PAGE_MODEL_DIR"
MODEL_MARKER = "page-model.json"


class ModelUnavailableError(Exception):
    """The pinned local embedding model has not been prepared."""


class IndexCorruptError(Exception):
    """An invalid cached vector requires an explicit rebuild."""


class EmbeddingError(Exception):
    """Model inference did not produce valid vectors."""


class Encoder(Protocol):
    fingerprint: str
    dimension: int

    def offsets(self, text: str) -> list[tuple[int, int]]: ...
    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


# Notes and read-only sources are indexed alike; chunks locate text in either.
Document = Note | SourceDocument


def split_note(note: Document, offsets: Callable[[str], list[tuple[int, int]]],
               max_tokens: int = MAX_TOKENS) -> tuple[Chunk, ...]:
    """Split paragraphs/headings at tokenizer boundaries without changing source.

    Offsets are character intervals from a fast tokenizer without special tokens.
    UUIDs depend on canonical note identity, exact text and duplicate occurrence,
    so moving a note or inserting a paragraph preserves unaffected chunk IDs.
    """
    if not isinstance(note, Note | SourceDocument) or not callable(offsets):
        raise TypeError("note and tokenizer are required")
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
        raise TypeError("max_tokens must be int")
    if max_tokens < 1:
        raise ValueError("max_tokens must be positive")
    content = note.content
    boundaries = [0]
    # Paragraphs and ATX headings: preserve all source characters, including
    # Markdown delimiters and line endings. No lossy rendering before encoding.
    boundaries += [m.end() for m in re.finditer(r"(?:\r\n|\r(?!\n)|(?<!\r)\n)[ \t]*(?:\r\n|\r(?!\n)|(?<!\r)\n)", content)]
    boundaries += [m.start() for m in re.finditer(r"(?:^|(?<=\n)|(?<=\r))#{1,6}[ \t]+", content) if m.start()]
    boundaries = sorted(set(boundaries + [len(content)]))
    spans: list[tuple[int, int, int]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        text = content[start:end]
        tokens = offsets(text)
        if not tokens or not text.strip("\ufeff \t\r\n"):
            continue
        cursor = start
        while cursor < end:
            remaining = content[cursor:end]
            tokens = offsets(remaining)
            if not tokens:
                break
            count = min(max_tokens, len(tokens))
            stop = cursor + tokens[count][0] if count < len(tokens) else end
            # Re-tokenize the actual slice; WordPiece continuations may tokenize
            # differently when a long word starts a new chunk.
            while stop > cursor and len(offsets(content[cursor:stop])) > max_tokens:
                count -= 1
                stop = cursor + tokens[count][0]
            if stop <= cursor:
                raise ValueError("tokenizer cannot split at a character boundary")
            spans.append((cursor, stop, len(offsets(content[cursor:stop]))))
            cursor = stop
    chunks: list[Chunk] = []
    occurrences: dict[str, int] = {}
    # Compute byte offsets once; these match Note's UTF-8 source, not Python
    # character indices (which differ for emoji and non-ASCII Markdown).
    byte_offsets = [0]
    for char in content:
        byte_offsets.append(byte_offsets[-1] + len(char.encode("utf-8")))
    for start, end, count in spans:
        text = content[start:end]
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        occurrence = occurrences.get(digest, 0)
        occurrences[digest] = occurrence + 1
        identifier = uuid5(note.id, f"paragraph-v1:{max_tokens}:{digest}:{occurrence}")
        chunks.append(Chunk(identifier, note.id, len(chunks), text,
                            byte_offsets[start], byte_offsets[end], count))
    return tuple(chunks)


def _checked_model_dir(directory: Path) -> Path:
    """A model folder is used only if its marker names exactly the pinned model."""
    marker = json.loads((directory / MODEL_MARKER).read_text(encoding="utf-8"))
    if marker != {"model": MODEL, "revision": REVISION}:
        raise ValueError("the model folder holds a different model")
    return directory


def export_model(destination: Path) -> None:
    """Copy the prepared pinned model into a plain folder for bundling.

    Unlike the Hugging Face cache, the copy has no symlinks, locks or markers
    that the library writes to, so it can live inside a signed, read-only app.
    """
    from huggingface_hub import snapshot_download
    source = Path(snapshot_download(MODEL, revision=REVISION, local_files_only=True))
    if destination.exists():
        raise FileExistsError(destination)
    # copyfile, not copy2: cache blobs are read-only, and the bundle must be rewritable.
    shutil.copytree(source, destination, symlinks=False, ignore=shutil.ignore_patterns("README.md", ".*"),
                    copy_function=shutil.copyfile)
    (destination / MODEL_MARKER).write_text(json.dumps({"model": MODEL, "revision": REVISION}) + "\n",
                                            encoding="utf-8")


class SentenceEncoder:
    """Fixed CPU MiniLM baseline; never downloads during indexing or search."""

    fingerprint = FINGERPRINT
    dimension = DIMENSION

    def __init__(self, *, download: bool = False) -> None:
        directory = None if download else os.environ.get(MODEL_DIR_ENV) or None
        try:
            from sentence_transformers import SentenceTransformer
            source, revision = MODEL, REVISION
            if directory is not None:
                source, revision = str(_checked_model_dir(Path(directory))), None
            self._model = SentenceTransformer(source, revision=revision, device="cpu",
                trust_remote_code=False, local_files_only=not download,
                model_kwargs={"use_safetensors": True})
            self._model.eval()
        except Exception as exc:
            raise ModelUnavailableError("prepare the pinned model first") from exc

    def offsets(self, text: str) -> list[tuple[int, int]]:
        encoded = self._model.tokenizer(text, add_special_tokens=False,
            return_offsets_mapping=True, truncation=False, verbose=False)
        return [(start, end) for start, end in encoded["offset_mapping"] if end > start]

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            if any(len(self.offsets(text)) > 254 for text in texts):
                raise EmbeddingError("input exceeds the model context window")
            # Fixed CPU execution, no dropout, one inference thread and exact
            # retrieval. This is a baseline, not a learned Page reranker.
            import torch
            torch.set_num_threads(1)
            return self._model.encode(list(texts), batch_size=32, show_progress_bar=False,
                normalize_embeddings=True, convert_to_numpy=True).tolist()
        except Exception as exc:
            raise EmbeddingError("local embedding inference failed") from exc


@dataclass(frozen=True, slots=True)
class IndexReport:
    notes: int
    chunks: int
    generated: int
    reused: int
    removed: int

    def __post_init__(self) -> None:
        for value in (self.notes, self.chunks, self.generated, self.reused, self.removed):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("index counts must be int")
            if value < 0:
                raise ValueError("index counts must be nonnegative")
        if self.generated + self.reused != self.chunks:
            raise ValueError("generated and reused must account for all chunks")


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk: Chunk
    relative_path: PurePosixPath
    revision: str
    start_line: int
    end_line: int
    score: float

    def __post_init__(self) -> None:
        if not isinstance(self.chunk, Chunk):
            raise TypeError("chunk must be Chunk")
        validate_document_path(self.relative_path)
        if not isinstance(self.revision, str):
            raise TypeError("revision must be str")
        if not re.fullmatch(r"[0-9a-f]{64}", self.revision):
            raise ValueError("revision must be a SHA-256 revision")
        for value in (self.start_line, self.end_line):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("source lines must be int")
        if self.start_line < 1 or self.end_line < self.start_line:
            raise ValueError("source line range is invalid")
        if not isinstance(self.score, float):
            raise TypeError("score must be float")
        if not math.isfinite(self.score) or not -1 <= self.score <= 1:
            raise ValueError("score must be finite cosine similarity")


class SemanticIndex:
    """Derived vectors persist in the vault's private metadata transaction.

    FAISS IndexFlatIP is reconstructed from cached vectors; no untrusted FAISS
    binary is deserialized. Failed reads/encodes leave the last snapshot intact.
    Each operation consumes freshly reconciled canonical Notes from its caller.
    """

    def __init__(self, repository: MetadataRepository, encoder: Encoder) -> None:
        self.repository = repository
        self.encoder = encoder
        self._chunks: tuple[Chunk, ...] = ()
        self._vectors: list[list[float]] = []

    def _vector(self, value: Sequence[float], *, cached: bool = False) -> list[float]:
        error = IndexCorruptError if cached else EmbeddingError
        if len(value) != self.encoder.dimension or not all(math.isfinite(v) for v in value):
            raise error("invalid embedding dimension or values")
        norm = math.sqrt(sum(v * v for v in value))
        if norm < 1e-8:
            raise error("zero embedding")
        if cached:
            if abs(norm - 1.0) > 1e-4:
                raise IndexCorruptError("cached embedding is not normalized")
            return list(value)
        return [float(v / norm) for v in value]

    def update(self, notes: tuple[Document, ...], *, rebuild: bool = False) -> IndexReport:
        if not isinstance(notes, tuple) or not all(isinstance(note, Note | SourceDocument) for note in notes):
            raise TypeError("notes must be a tuple of Note or SourceDocument values")
        if not isinstance(rebuild, bool):
            raise TypeError("rebuild must be bool")
        if any(note.vault_id != self.repository.vault.id for note in notes) or len({note.id for note in notes}) != len(notes):
            raise ValueError("notes must have unique canonical IDs in this vault")
        import numpy as np
        chunks = tuple(chunk for note in sorted(notes, key=lambda n: str(n.id))
                       for chunk in split_note(note, self.encoder.offsets))
        cached = self.repository.read_vectors(self.encoder.fingerprint)
        vectors: dict[str, list[float]] = {}
        needed = [chunk for chunk in chunks if rebuild or str(chunk.id) not in cached]
        for chunk in chunks:
            key = str(chunk.id)
            if not rebuild and key in cached:
                raw = cached[key]
                if not isinstance(raw, bytes) or len(raw) != self.encoder.dimension * 4:
                    raise IndexCorruptError("invalid cached vector size")
                vectors[key] = self._vector(np.frombuffer(raw, dtype="<f4").tolist(), cached=True)
        if needed:
            encoded = self.encoder.encode([chunk.text for chunk in needed])
            if len(encoded) != len(needed):
                raise EmbeddingError("embedding count mismatch")
            for chunk, vector in zip(needed, encoded, strict=True):
                vectors[str(chunk.id)] = self._vector(vector)
        rows = [(chunk.id, chunk.note_id, np.asarray(vectors[str(chunk.id)], dtype="<f4").tobytes())
                for chunk in chunks]
        self.repository.replace_vectors(self.encoder.fingerprint, rows)
        self._chunks = chunks
        self._vectors = [np.frombuffer(row[2], dtype="<f4").tolist() for row in rows]
        return IndexReport(len(notes), len(chunks), len(needed), len(chunks) - len(needed),
                           len(set(cached) - {str(chunk.id) for chunk in chunks}))

    def search(self, query: str, notes: tuple[Document, ...], revisions: dict[UUID, str],
               limit: int = 10) -> tuple[SearchHit, ...]:
        if not isinstance(query, str):
            raise TypeError("query must be str")
        if not query.strip() or len(query) > 2000:
            raise ValueError("query must be nonblank and at most 2000 characters")
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("limit must be int")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        if len(self.encoder.offsets(query)) > MAX_TOKENS:
            raise ValueError("query exceeds the model token limit")
        self.update(notes)
        if not self._chunks:
            return ()
        encoded = self.encoder.encode([query])
        if len(encoded) != 1:
            raise EmbeddingError("query embedding count mismatch")
        vector = self._vector(encoded[0])
        # Search every row to give ties a stable UUID order even at the top-k
        # boundary. Isolate FAISS from PyTorch's OpenMP runtime on macOS.
        try:
            process = subprocess.run([sys.executable, "-m", "page_core.vector_search"],
                input=json.dumps({"vectors": self._vectors, "query": vector}, allow_nan=False),
                text=True, capture_output=True, timeout=60, check=True)
            scores, positions = json.loads(process.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise EmbeddingError("local vector search failed") from exc
        ranked = sorted(zip(scores, positions, strict=True),
            key=lambda pair: (-pair[0], str(self._chunks[pair[1]].id)))[:limit]
        by_id = {note.id: note for note in notes}
        hits = []
        for score, position in ranked:
            chunk = self._chunks[position]
            note = by_id[chunk.note_id]
            raw = note.content.encode("utf-8")
            def line(byte: int) -> int:
                return 1 + len(re.findall(r"\r\n|\r|\n", raw[:byte].decode("utf-8")))
            # The end line is the line of the chunk's last character; a trailing
            # CRLF is one line break, so step back over both bytes together.
            last = 2 if chunk.text.endswith("\r\n") else len(chunk.text[-1].encode("utf-8"))
            hits.append(SearchHit(chunk, note.relative_path, revisions[note.id],
                line(chunk.start_byte), line(chunk.end_byte - last),
                max(-1.0, min(1.0, score))))
        return tuple(hits)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Prepare Page's pinned local embedding model")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare-model", help="download the pinned model into the Hugging Face cache")
    export = commands.add_parser("export-model", help="copy the prepared model to a plain folder")
    export.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.command == "prepare-model":
        SentenceEncoder(download=True)
        print(f"Prepared {MODEL}@{REVISION}. Indexing and search can now run offline.")
    else:
        export_model(args.destination)
        print(f"Exported {MODEL}@{REVISION} to {args.destination}. Set {MODEL_DIR_ENV} to use it.")
