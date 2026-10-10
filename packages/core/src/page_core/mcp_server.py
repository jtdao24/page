"""MCP server exposing one vault's knowledge and context engine.

``python -m page_core.mcp_server --vault PATH`` serves read-only tools over
stdio to MCP clients such as Claude Desktop or Claude Code. Notes are never
written. Like the app, it reconciles metadata with the files and caches
embeddings in the vault's private storage. It calls no language model: the
client's own model consumes the context it returns.
"""

import argparse
import asyncio
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from page_core import __version__
from page_core.api.errors import translate
from page_core.api.service import LocalVaultService, revision_of_note
from page_core.domain import validate_note_path

INSTRUCTIONS = (
    "Page is the user's local Markdown knowledge base. Use get_context to gather the passages "
    "relevant to a question within a token budget, and cite them by note path and lines. Use "
    "search_notes to explore, read_note for a whole note, and related_notes to follow links."
)
_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                             open_world_hint=False)

Query = Annotated[str, Field(min_length=1, max_length=2000)]
NotePath = Annotated[str, Field(min_length=1, max_length=1024,
                                description="Vault-relative note path, e.g. projects/plan.md")]


class SearchResult(BaseModel):
    note_id: str
    path: str
    start_line: int
    end_line: int
    score: float
    text: str


class SearchResults(BaseModel):
    results: list[SearchResult]


class ContextSource(BaseModel):
    number: int
    note_id: str
    path: str
    start_line: int
    end_line: int
    relevance: float
    excerpt: bool
    text: str


class ContextUsage(BaseModel):
    tokens: int
    budget: int
    counter: str
    candidate_tokens: int
    considered: int
    selected: int


class OptimizedContext(BaseModel):
    context: str = Field(description="Numbered, source-attributed passages ready to use as model context")
    sources: list[ContextSource]
    usage: ContextUsage


class NoteContent(BaseModel):
    note_id: str
    path: str
    revision: str
    lines: int
    content: str


class LinkedNote(BaseModel):
    note_id: str | None
    path: str | None
    reference: str
    line: int = Field(description="Line of the link in the note that contains it")
    unresolved: Literal["missing", "ambiguous", "invalid"] | None


class RelatedNotes(BaseModel):
    note_id: str
    path: str
    links: list[LinkedNote] = Field(description="Wiki links from this note")
    backlinks: list[LinkedNote] = Field(description="Wiki links to this note from other notes")


class PageVaultTools:
    """The tools' behavior for one vault, on the service's single owning thread."""

    def __init__(self, root: Path) -> None:
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="page-mcp")
        try:
            self._service = self._worker.submit(LocalVaultService).result()
            self.vault = self._worker.submit(self._service.open_vault, root).result().vault
        except BaseException:
            self._worker.shutdown()
            raise

    def close(self) -> None:
        self._worker.submit(self._service.close).result()
        self._worker.shutdown()

    async def _run[T](self, action: Callable[[], T]) -> T:
        try:
            return await asyncio.wrap_future(self._worker.submit(action))
        except ToolError:
            raise
        except Exception as exc:
            error = translate(exc)
            # Generic, fixed messages only: no paths, note text or tracebacks.
            raise ToolError(f"{error.code}: {error.message}") from None

    def _note_id(self, path: str) -> UUID:
        try:
            relative = PurePosixPath(path)
            validate_note_path(relative)
        except (TypeError, ValueError):
            raise ToolError("invalid_path: Use a vault-relative .md path from search results.") from None
        # Pick up notes changed outside Page since the last tool call.
        self._service.reconcile(self.vault.id, {})
        for record in self._service.list_notes(self.vault.id):
            if record.relative_path == relative:
                return record.id
        raise ToolError(f"note_not_found: No note at {relative}.")

    async def search_notes(self, query: str, limit: int) -> SearchResults:
        hits = await self._run(lambda: self._service.search_vault(self.vault.id, query, limit))
        return SearchResults(results=[
            SearchResult(note_id=str(hit.chunk.note_id), path=str(hit.relative_path), start_line=hit.start_line,
                         end_line=hit.end_line, score=round(hit.score, 4), text=hit.chunk.text)
            for hit in hits])

    async def get_context(self, question: str, budget: int, candidates: int) -> OptimizedContext:
        package = await self._run(
            lambda: self._service.question_context(self.vault.id, question, budget, candidates))
        usage = package.usage
        return OptimizedContext(
            context=package.result.context_text,
            sources=[ContextSource(number=block.number, note_id=str(block.note_id), path=str(block.relative_path),
                                   start_line=block.start_line, end_line=block.end_line,
                                   relevance=round(block.relevance, 4), excerpt=block.compressed, text=block.text)
                     for block in package.blocks],
            usage=ContextUsage(tokens=usage.tokens, budget=usage.budget, counter=usage.counter,
                               candidate_tokens=usage.candidate_tokens, considered=usage.considered,
                               selected=usage.selected))

    async def read_note(self, path: str) -> NoteContent:
        def read() -> NoteContent:
            note = self._service.get_note(self.vault.id, self._note_id(path))
            return NoteContent(note_id=str(note.id), path=str(note.relative_path),
                               revision=revision_of_note(note), lines=len(note.content.splitlines()),
                               content=note.content)
        return await self._run(read)

    async def related_notes(self, path: str) -> RelatedNotes:
        def related() -> RelatedNotes:
            note_id = self._note_id(path)
            graph = self._service.get_graph(self.vault.id)
            paths = {node.id: str(node.relative_path) for node in graph.nodes}

            def linked(other: UUID | None, item) -> LinkedNote:
                return LinkedNote(note_id=None if other is None else str(other),
                                  path=None if other is None else paths.get(other),
                                  reference=item.link.target_reference, line=item.line,
                                  unresolved=item.unresolved_reason)
            return RelatedNotes(
                note_id=str(note_id), path=paths[note_id],
                links=[linked(item.link.target_note_id, item) for item in graph.links
                       if item.link.source_note_id == note_id],
                backlinks=[linked(item.link.source_note_id, item) for item in graph.links
                           if item.link.target_note_id == note_id and item.link.source_note_id != note_id])
        return await self._run(related)


def create_server(tools: PageVaultTools) -> MCPServer:
    server = MCPServer("page", title=f"Page: {tools.vault.name}", version=__version__,
                       instructions=INSTRUCTIONS)

    @server.tool(annotations=_READ_ONLY)
    async def search_notes(query: Query,
                           limit: Annotated[int, Field(ge=1, le=50)] = 10) -> SearchResults:
        """Semantic search over the vault's saved notes. Returns the most similar passages with
        their note path, line range and cosine score."""
        return await tools.search_notes(query, limit)

    @server.tool(annotations=_READ_ONLY)
    async def get_context(question: Query,
                          budget: Annotated[int, Field(ge=50, le=20000, description="Token budget")] = 1500,
                          candidates: Annotated[int, Field(ge=1, le=50)] = 10) -> OptimizedContext:
        """Page's optimized context for a question: the most relevant passages, deduplicated and
        trimmed to fit the token budget, numbered with their source note and lines. Use it as
        grounding and cite sources by path and lines. Token counts are estimates."""
        return await tools.get_context(question, budget, candidates)

    @server.tool(annotations=_READ_ONLY)
    async def read_note(path: NotePath) -> NoteContent:
        """The full Markdown content of one note, by vault-relative path."""
        return await tools.read_note(path)

    @server.tool(annotations=_READ_ONLY)
    async def related_notes(path: NotePath) -> RelatedNotes:
        """The notes this note links to and the notes that link to it, from wiki links."""
        return await tools.related_notes(path)

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m page_core.mcp_server",
                                     description="Serve a Page vault to MCP clients over stdio.")
    parser.add_argument("--vault", required=True, type=Path, help="Root folder of an existing Page vault")
    args = parser.parse_args(argv)
    try:
        tools = PageVaultTools(args.vault)
    except Exception as exc:
        error = translate(exc)
        # stdout belongs to the MCP protocol; diagnostics go to stderr.
        print(f"page-mcp: cannot open vault: {error.message}", file=sys.stderr)
        return 1
    try:
        create_server(tools).run("stdio")
    finally:
        tools.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
