"""Saving web pages: URL safety, fetching rules and HTML-to-Markdown conversion."""
import io
import urllib.error
from datetime import UTC, datetime
from email.message import Message
from pathlib import PurePosixPath

import pytest

from page_core.web import (
    MAX_PAGE_BYTES, InvalidUrlError, UnsupportedPageError, WebFetchError, WebPage, check_url, fetch_page,
    html_to_markdown, note_for_page,
)

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731


def test_only_public_http_urls_are_accepted():
    assert check_url(" https://example.com/a ", PUBLIC) == "https://example.com/a"
    for bad in ("file:///etc/passwd", "ftp://example.com", "javascript:alert(1)", "example.com", "https://user@example.com/"):
        with pytest.raises(InvalidUrlError):
            check_url(bad, PUBLIC)
    for address in ("127.0.0.1", "::1", "169.254.169.254", "0.0.0.0"):
        with pytest.raises(InvalidUrlError):
            check_url("http://internal.test/", lambda host, address=address: [address])


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8", url: str = "https://example.com/coffee"):
        self._body, self._url = io.BytesIO(body), url
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self, limit: int = -1) -> bytes:
        return self._body.read(limit)

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


HTML = b"""<html><head><title> Brewing   Espresso </title><style>body{}</style></head><body>
<nav>Home | About</nav><script>track()</script>
<h1>Espresso</h1><p>A <strong>double</strong> uses <em>18 g</em> of coffee. See <a href="https://example.com/grind">grind guide</a>.</p>
<ul><li>Fine grind</li><li>25 seconds</li></ul><pre>ratio = 1:2
time = 25</pre><footer>Copyright</footer></body></html>"""


def test_html_becomes_readable_markdown():
    title, markdown = html_to_markdown(HTML.decode())
    assert title == "Brewing Espresso"
    assert markdown.startswith("# Espresso\n\nA **double** uses *18 g* of coffee. See [grind guide](https://example.com/grind).")
    assert "- Fine grind\n- 25 seconds" in markdown
    assert "```\nratio = 1:2\ntime = 25\n```" in markdown
    for dropped in ("Home | About", "track()", "Copyright", "body{}"):
        assert dropped not in markdown


def test_fetch_page_converts_html_and_plain_text():
    requests = []

    def opener(request, timeout):
        requests.append((request.full_url, request.get_header("User-agent"), timeout))
        return FakeResponse(HTML)
    page = fetch_page("https://example.com/coffee", opener=opener, resolve=PUBLIC)
    assert page.title == "Brewing Espresso" and page.url == "https://example.com/coffee"
    assert "# Espresso" in page.markdown
    assert requests[0][0] == "https://example.com/coffee" and requests[0][1].startswith("Page/")
    text = fetch_page("https://example.com/notes.txt", resolve=PUBLIC,
                      opener=lambda request, timeout: FakeResponse(b"plain notes", "text/plain", "https://example.com/notes.txt"))
    assert (text.title, text.markdown) == ("notes.txt", "plain notes\n")


def test_fetch_failures_are_typed_and_generic():
    with pytest.raises(UnsupportedPageError):
        fetch_page("https://example.com/a.pdf", resolve=PUBLIC, opener=lambda r, timeout: FakeResponse(b"%PDF", "application/pdf"))
    with pytest.raises(UnsupportedPageError):
        fetch_page("https://example.com/", resolve=PUBLIC, opener=lambda r, timeout: FakeResponse(b"x" * (MAX_PAGE_BYTES + 1)))

    def http_error(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", Message(), None)
    with pytest.raises(WebFetchError, match="HTTP 404"):
        fetch_page("https://example.com/", resolve=PUBLIC, opener=http_error)

    def offline(request, timeout):
        raise urllib.error.URLError("secret detail")
    with pytest.raises(WebFetchError) as error:
        fetch_page("https://example.com/", resolve=PUBLIC, opener=offline)
    assert "secret" not in str(error.value)


def test_page_notes_live_under_web_with_source_front_matter():
    page = WebPage("https://Example.com/coffee?x=1", 'Brewing "Espresso": A Guide', "Body text.\n")
    path, content = note_for_page(page, datetime(2026, 10, 10, 12, tzinfo=UTC))
    assert path == PurePosixPath("web/example.com/brewing-espresso-a-guide.md")
    assert content.startswith('---\nsource: https://Example.com/coffee?x=1\nsaved: 2026-10-10\ntitle: "Brewing \'Espresso\': A Guide"\n---\n\n')
    assert content.endswith("# Brewing \"Espresso\": A Guide\n\nBody text.\n")
    assert note_for_page(WebPage("https://example.com/", "???", ""), datetime.now(UTC))[0].name == "page.md"
    _, own_heading = note_for_page(WebPage("https://example.com/", "Guide", "# Guide\n\nText.\n"), datetime.now(UTC))
    assert own_heading.count("# Guide") == 1 and own_heading.endswith("---\n\n# Guide\n\nText.\n")
