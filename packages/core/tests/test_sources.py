"""Read-only sources: discovery, PDF/code extraction, caching and domain rules."""
import os
from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

from page_core.domain import SourceDocument, validate_document_path, validate_source_path
from page_core.sources import (
    MAX_SOURCE_BYTES, SourceLibrary, SourceNotFoundError, SourceUnreadableError, extract_pdf, extract_text, source_id,
)


def make_pdf(pages: list[str]) -> bytes:
    """A minimal valid PDF with one line of Helvetica text per page."""
    count = len(pages)
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [" + " ".join(f"{4 + 2 * i} 0 R" for i in range(count)) + f"] /Count {count} >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for index, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                       f"/Contents {5 + 2 * index} 0 R >>")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def test_source_paths_and_documents_are_validated():
    assert validate_source_path(PurePosixPath("papers/a.pdf")) == PurePosixPath("papers/a.pdf")
    assert validate_document_path(PurePosixPath("notes/a.md")) == PurePosixPath("notes/a.md")
    assert validate_document_path(PurePosixPath("code/x.py")) == PurePosixPath("code/x.py")
    assert validate_source_path(PurePosixPath("Scan.PDF")).suffix == ".PDF"
    for bad in ("a.md", "a.exe", "../a.pdf", "/a.pdf", "a:b.pdf"):
        with pytest.raises(ValueError):
            validate_source_path(PurePosixPath(bad))
    with pytest.raises(TypeError):
        validate_document_path("a.pdf")
    vault = uuid4()
    document = SourceDocument(uuid4(), vault, PurePosixPath("x.py"), "print()", "a" * 64)
    assert document.kind == "code"
    for bad_revision in ("A" * 64, "a" * 63, "z" * 64):
        with pytest.raises(ValueError):
            SourceDocument(uuid4(), vault, PurePosixPath("x.py"), "", bad_revision)


def test_pdf_text_is_extracted_page_by_page():
    assert extract_pdf(make_pdf(["Espresso uses eighteen grams", "Second page text"])) == (
        "[Page 1]\nEspresso uses eighteen grams\n\n[Page 2]\nSecond page text\n")
    assert extract_pdf(make_pdf([""])) == ""
    with pytest.raises(SourceUnreadableError):
        extract_pdf(b"%PDF-1.4 this is not a real pdf")


def test_code_and_text_are_decoded_as_utf8():
    assert extract_text(PurePosixPath("a.py"), "﻿print('ü')\n".encode()) == "print('ü')\n"
    with pytest.raises(SourceUnreadableError):
        extract_text(PurePosixPath("a.txt"), b"\xff\xfe\x00bad")


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    files = {
        "notes/plan.md": b"# not a source",
        "papers/study.pdf": make_pdf(["Coffee extraction study"]),
        "code/timer.py": b"def brew():\n    return 25\n",
        "readme.txt": b"plain text",
        "data.bin": b"\x00",
        ".hidden/secret.py": b"x = 1",
        "node_modules/lib/index.js": b"module.exports = 1",
        "build/out.js": b"bundle",
        "broken.txt": b"\xff\xfe bad",
    }
    for path, data in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
    (root / "link.py").symlink_to(root / "code" / "timer.py")
    return root


def test_listing_finds_supported_files_and_skips_hidden_generated_and_linked(vault_root):
    vault_id = uuid4()
    entries = SourceLibrary(vault_root, vault_id).list()
    assert [(str(entry.relative_path), entry.kind) for entry in entries] == [
        ("broken.txt", "text"), ("code/timer.py", "code"), ("papers/study.pdf", "pdf"), ("readme.txt", "text")]
    assert entries[1].id == source_id(vault_id, PurePosixPath("code/timer.py"))
    assert entries[1].size_bytes == len(b"def brew():\n    return 25\n")


def test_oversized_files_are_not_sources(vault_root):
    with (vault_root / "huge.txt").open("wb") as handle:
        handle.truncate(MAX_SOURCE_BYTES + 1)
    assert "huge.txt" not in {str(entry.relative_path) for entry in SourceLibrary(vault_root, uuid4()).list()}


def test_documents_skip_unreadable_files_and_get_reports_them(vault_root):
    vault_id = uuid4()
    library = SourceLibrary(vault_root, vault_id)
    documents = {str(document.relative_path): document for document in library.documents()}
    assert set(documents) == {"code/timer.py", "papers/study.pdf", "readme.txt"}
    assert documents["papers/study.pdf"].content == "[Page 1]\nCoffee extraction study\n"
    assert library.get(documents["readme.txt"].id).content == "plain text"
    with pytest.raises(SourceUnreadableError):
        library.get(source_id(vault_id, PurePosixPath("broken.txt")))
    with pytest.raises(SourceNotFoundError):
        library.get(uuid4())


def test_extraction_is_cached_until_the_file_changes(vault_root):
    calls = []

    def extract(path, data):
        calls.append(str(path))
        return extract_text(path, data)
    library = SourceLibrary(vault_root, uuid4(), extract=extract)
    library.documents()
    first = len(calls)
    library.documents()
    assert len(calls) == first
    target = vault_root / "readme.txt"
    target.write_bytes(b"changed text!")
    os.utime(target, ns=(1, 1))
    changed = {str(d.relative_path): d for d in library.documents()}
    assert calls[first:] == ["readme.txt"]
    assert changed["readme.txt"].content == "changed text!"
    target.unlink()
    assert "readme.txt" not in {str(d.relative_path) for d in library.documents()}
