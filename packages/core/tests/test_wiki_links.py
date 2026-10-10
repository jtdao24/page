from page_core.wiki_links import (
    NoteRef,
    extract_wiki_links,
    resolve_links,
    resolve_title,
)


def test_extracts_title_and_alias() -> None:
    links = extract_wiki_links("See [[Another Note|the other one]] today.")
    assert len(links) == 1
    assert links[0].title == "Another Note"
    assert links[0].display_text == "the other one"
    assert links[0].raw == "[[Another Note|the other one]]"


def test_ignores_fenced_and_inline_code() -> None:
    text = """
```
[[Not A Link]]
```

Use `[[Also Not]]` and then [[Real Note]].
"""
    links = extract_wiki_links(text)
    assert [link.title for link in links] == ["Real Note"]


def test_unresolved_and_duplicate_title_resolution() -> None:
    notes = [
        NoteRef(id="projects/Alpha.md", title="Alpha", path="projects/Alpha.md"),
        NoteRef(id="Alpha.md", title="Alpha", path="Alpha.md"),
        NoteRef(id="Beta.md", title="Beta", path="Beta.md"),
    ]
    assert resolve_title("Missing", notes) is None
    assert resolve_title("Beta", notes) == "Beta.md"
    # Duplicate titles pick the shortest path, then lexicographic order.
    assert resolve_title("Alpha", notes) == "Alpha.md"
    assert resolve_title("projects/Alpha", notes) == "projects/Alpha.md"


def test_resolve_links_skips_code_and_sets_excerpt() -> None:
    notes = [NoteRef(id="Target.md", title="Target", path="Target.md")]
    text = "Intro\nSee [[Target]] nearby.\n`[[Target]]`"
    resolved = resolve_links(text, notes)
    assert len(resolved) == 1
    assert resolved[0].target_id == "Target.md"
    assert resolved[0].excerpt == "See [[Target]] nearby."
