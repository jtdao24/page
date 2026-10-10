"""Natural-language semantic search over a vault's notes.

The service embeds the query with the same model as the index, retrieves the
most similar chunks from FAISS, drops chunks that no longer match the note on
disk, and groups the rest into note-level results. It has no dependency on
FastAPI or the desktop app.

Ranking: a note's score is the cosine similarity between the query and the
note's best-matching chunk (higher is more similar; range [-1, 1]). Notes are
ordered by descending score, then by path. Scores compare results within the
same model; they are not probabilities or confidence values.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import UUID

from page_core.domain import Note
from page_core.embeddings.encoder import Embedder, normalize_rows
from page_core.embeddings.index import ChunkHit, SemanticIndex

DEFAULT_LIMIT = 10
MAX_LIMIT = 50
MAX_QUERY_CHARS = 2000
EXCERPT_CHARS = 320

# Candidate chunks fetched per requested note, and the hard cap per search.
_CANDIDATES_PER_NOTE = 5
_MIN_CANDIDATES = 20
_MAX_CANDIDATES = 1000

NoteReader = Callable[[PurePosixPath], Note | None]
"""Returns a note's current state, or None if it is missing or unreadable."""


class QueryValidationError(ValueError):
    """The query or limit is invalid."""


@dataclass(frozen=True, slots=True)
class NoteMatch:
    note_id: UUID
    path: PurePosixPath
    title: str
    score: float
    excerpt: str
    chunk_id: int
    chunk_ordinal: int
    start_byte: int
    end_byte: int
    heading: str | None
    matched_chunks: int
    """Candidate chunks from this note that matched the query, including the best one."""


@dataclass(frozen=True, slots=True)
class SemanticSearchResult:
    query: str
    limit: int
    matches: tuple[NoteMatch, ...]
    candidates_considered: int
    stale_paths: tuple[PurePosixPath, ...]
    """Notes whose indexed chunks no longer match the file; they need re-indexing."""


def validate_query(query: object, limit: object = DEFAULT_LIMIT) -> tuple[str, int]:
    if not isinstance(query, str):
        raise QueryValidationError(f"query must be str, got {type(query).__name__}")
    text = query.strip()
    if not text:
        raise QueryValidationError("query must not be blank")
    if len(text) > MAX_QUERY_CHARS:
        raise QueryValidationError(f"query must be at most {MAX_QUERY_CHARS} characters")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise QueryValidationError(f"limit must be int, got {type(limit).__name__}")
    if not 1 <= limit <= MAX_LIMIT:
        raise QueryValidationError(f"limit must be between 1 and {MAX_LIMIT}, got {limit}")
    return text, limit


class SemanticSearchService:
    def __init__(self, index: SemanticIndex, embedder: Embedder, read_note: NoteReader) -> None:
        if embedder.model_id != index.model_id or embedder.dimension != index.dimension:
            raise ValueError("the query embedder must be the model the index was built with")
        self._index = index
        self._embedder = embedder
        self._read_note = read_note

    def search(self, query: str, limit: int = DEFAULT_LIMIT) -> SemanticSearchResult:
        text, limit = validate_query(query, limit)
        vector = normalize_rows(self._embedder.embed([text]), self._index.dimension)

        total = self._index.stats().chunks
        k = min(total, _MAX_CANDIDATES, max(_MIN_CANDIDATES, limit * _CANDIDATES_PER_NOTE))
        checked: dict[PurePosixPath, Note | None] = {}
        stale: set[PurePosixPath] = set()
        matches: list[NoteMatch] = []
        hits: list[ChunkHit] = []
        while True:
            hits = self._index.search(vector, k)
            matches = self._group(hits, limit, checked, stale)
            # Widen the search only if too few distinct notes came back and more exist.
            if len(matches) >= limit or k >= min(total, _MAX_CANDIDATES):
                break
            k = min(k * 2, total, _MAX_CANDIDATES)

        return SemanticSearchResult(
            query=text,
            limit=limit,
            matches=tuple(matches),
            candidates_considered=len(hits),
            stale_paths=tuple(sorted(stale, key=str)),
        )

    def _group(
        self,
        hits: list[ChunkHit],
        limit: int,
        checked: dict[PurePosixPath, Note | None],
        stale: set[PurePosixPath],
    ) -> list[NoteMatch]:
        best: dict[PurePosixPath, tuple[ChunkHit, Note]] = {}
        counts: dict[PurePosixPath, int] = {}
        for hit in hits:  # descending score, so the first valid hit per note is its best
            if hit.path not in checked:
                checked[hit.path] = self._read_note(hit.path)
            note = checked[hit.path]
            if note is None or not _chunk_matches(note, hit):
                stale.add(hit.path)
                continue
            counts[hit.path] = counts.get(hit.path, 0) + 1
            best.setdefault(hit.path, (hit, note))

        ranked = sorted(best.values(), key=lambda pair: (-pair[0].score, str(pair[0].path)))
        return [
            NoteMatch(
                note_id=note.id,
                path=hit.path,
                title=hit.path.stem,
                score=hit.score,
                excerpt=_excerpt(hit.text),
                chunk_id=hit.vector_id,
                chunk_ordinal=hit.ordinal,
                start_byte=hit.start_byte,
                end_byte=hit.end_byte,
                heading=hit.heading,
                matched_chunks=counts[hit.path],
            )
            for hit, note in ranked[:limit]
        ]


def _chunk_matches(note: Note, hit: ChunkHit) -> bool:
    """True if the note still contains the indexed chunk at the same bytes."""
    data = note.content.encode("utf-8")
    if hit.end_byte > len(data):
        return False
    return data[hit.start_byte : hit.end_byte] == hit.text.encode("utf-8")


def _excerpt(text: str) -> str:
    """The start of the chunk text, cut at a word boundary if it is long."""
    if len(text) <= EXCERPT_CHARS:
        return text
    cut = max(text.rfind(" ", 0, EXCERPT_CHARS), text.rfind("\n", 0, EXCERPT_CHARS))
    return text[: cut if cut > EXCERPT_CHARS // 2 else EXCERPT_CHARS].rstrip() + "…"
