from __future__ import annotations

from pydantic import BaseModel, Field


class NoteSummary(BaseModel):
    id: str
    title: str
    path: str


class Note(NoteSummary):
    content: str


class NoteCreate(BaseModel):
    title: str = Field(min_length=1)
    content: str = ""


class NoteUpdate(BaseModel):
    content: str
    title: str | None = None


class Backlink(BaseModel):
    source_id: str
    source_title: str
    excerpt: str
    target_title: str


class GraphNode(BaseModel):
    id: str
    title: str


class GraphEdge(BaseModel):
    source: str
    target: str


class GraphData(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
