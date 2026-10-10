"""Real wiki syntax and canonical identity/relationship behavior."""
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

import pytest

from page_core.domain import Note
from page_core.graph import build_graph, parse_wiki_links

VAULT = UUID(int=1)


def note(identifier: int, path: str, content: str = "") -> Note:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Note(UUID(int=identifier), VAULT, PurePosixPath(path), content, now, now)


def test_parser_alias_embeds_fragments_locations_and_escaping() -> None:
    refs = parse_wiki_links('日本語 [[folder/Note#Heading|Display]]\r\n![[Asset]]\r[[#Local]]\n\\[[escaped]] [[ ]] [[broken\nlink]]')
    assert [(r.target_reference, r.alias, r.line) for r in refs] == [
        ('folder/Note#Heading', 'Display', 1), ('Asset', None, 2), ('#Local', None, 3)]


@pytest.mark.parametrize('content', [
    '[[outer [[nested]]]] [[real]]', '`[[code]]` [[real]]', '`<!--` [[real]]', '<!-- ` --> [[real]]', '<!--\n```\n-->\n[[real]]', '``[[code]] ` nested`` [[real]]',
    '```md\n[[code]]\n```\n[[real]]', '~~~\n[[code]]\n~~~\n[[real]]',
    '<!-- [[code]] --> [[real]]', '    [[code]]\n[[real]]',
    '---\nvalue: [[code]]\n---\n[[real]]',
    '> ```\n> [[code]]\n> ```\n[[real]]',
])
def test_excludes_non_prose_links(content: str) -> None:
    assert [r.target_reference for r in parse_wiki_links(content)] == ['real']


def test_resolution_and_backlinks_are_deterministic_and_preserve_duplicates() -> None:
    source = note(2, 'folder/source.md', '[[Same|first]] [[Same#part]] [[root/Target.md]] [[#self]] [[Missing]] [[../bad]] [[Duplicate]]')
    same = note(3, 'folder/Same.md')
    other = note(4, 'other/Same.md')
    target = note(5, 'root/Target.md')
    duplicates = (note(6, 'x/Duplicate.md'), note(7, 'y/Duplicate.md'))
    graph = build_graph(VAULT, (source, same, other, target, *duplicates))
    assert graph == build_graph(VAULT, (target, other, same, source, *reversed(duplicates)))
    assert [e.link.target_note_id for e in graph.links] == [same.id, same.id, target.id, source.id, None, None, None]
    assert [e.unresolved_reason for e in graph.links[-3:]] == ['missing', 'invalid', 'ambiguous']
    assert len(graph.backlinks(same.id)) == 2
    assert graph.links[0].alias == 'first'
    assert graph.backlinks(target.id)[0].link.source_note_id == source.id


def test_explicit_root_relative_and_unique_basename_resolution() -> None:
    a = note(2, 'nested/a.md', '[[/Target]] [[./Target]] [[Unique]] [[target]]')
    root, local, unique = note(3, 'Target.md'), note(4, 'nested/Target.md'), note(5, 'else/Unique.md')
    graph = build_graph(VAULT, (a, root, local, unique))
    assert [e.link.target_note_id for e in graph.links] == [root.id, local.id, unique.id, None]


def test_rebuilding_after_move_does_not_invent_ids_or_rewrite_links() -> None:
    a, b = note(2, 'a.md', '[[b]]'), note(3, 'b.md')
    before = build_graph(VAULT, (a, b))
    moved = note(3, 'archive/b.md')
    assert build_graph(VAULT, (a, moved)).links == before.links
    renamed = note(3, 'c.md')
    assert build_graph(VAULT, (a, renamed)).links[0].unresolved_reason == 'missing'
    assert build_graph(VAULT, (a,)).links[0].link.target_note_id is None


@pytest.mark.parametrize('value', [None, 42, b'[[note]]'])
def test_parser_never_coerces(value: object) -> None:
    with pytest.raises(TypeError):
        parse_wiki_links(value)  # type: ignore[arg-type]


def test_graph_rejects_foreign_or_duplicate_notes() -> None:
    a = note(2, 'a.md')
    with pytest.raises(ValueError): build_graph(UUID(int=99), (a,))
    with pytest.raises(ValueError): build_graph(VAULT, (a, a))
    with pytest.raises(TypeError): build_graph(VAULT, [a])  # type: ignore[arg-type]
    assert build_graph(VAULT, ()).links == ()


def test_graph_values_reject_wrong_types_and_inconsistent_endpoints() -> None:
    from page_core.graph import WikiReference, GraphLink, GraphNode, GraphSnapshot
    from page_core.domain import Link
    with pytest.raises(TypeError): WikiReference("a", None, True)
    with pytest.raises(ValueError): WikiReference(" ", None, 1)
    with pytest.raises(TypeError): GraphNode("id", PurePosixPath("a.md"))  # type: ignore[arg-type]
    with pytest.raises(ValueError): GraphLink(Link(UUID(int=2), "a"), None, 1, None)
    with pytest.raises(ValueError): GraphSnapshot(VAULT, (), (GraphLink(Link(UUID(int=2), "a"), None, 1, "missing"),))
