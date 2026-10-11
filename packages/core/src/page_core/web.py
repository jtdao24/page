"""Save a web page into a vault as a Markdown note.

The page is fetched once, at the user's request, and converted to Markdown with
the standard library: headings, paragraphs, lists, links and code are kept;
scripts, styles, navigation and forms are dropped. The note records its source
URL and when it was saved, and is then an ordinary, editable note.
"""

import ipaddress
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any

MAX_PAGE_BYTES = 5 * 1024 * 1024
TIMEOUT_SECONDS = 20
USER_AGENT = "Page/0.1 (+local knowledge workspace; saves pages on request)"


class WebPageError(Exception):
    """Base class for web page failures. Messages are fixed and safe to show."""


class InvalidUrlError(WebPageError):
    """The URL is not an http(s) address Page may fetch."""


class WebFetchError(WebPageError):
    """The page could not be downloaded."""


class UnsupportedPageError(WebPageError):
    """The address did not return an HTML or text page, or it was too large."""


@dataclass(frozen=True, slots=True)
class WebPage:
    url: str
    title: str
    markdown: str


def check_url(url: str, resolve: Callable[[str], list[str]] | None = None) -> str:
    """Accept only http(s) URLs whose host is not this computer or its local link."""
    if not isinstance(url, str):
        raise TypeError("url must be str")
    url = url.strip()
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or len(url) > 2048 or parts.username:
        raise InvalidUrlError("Enter a full http:// or https:// address.")
    addresses = (resolve or _resolve)(parts.hostname)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise InvalidUrlError("Page does not fetch addresses on this computer.")
    return url


def _resolve(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except (socket.gaierror, UnicodeError):
        raise WebFetchError("The address could not be found.") from None


class _NoUnsafeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_open(request: urllib.request.Request, timeout: float) -> Any:
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _NoUnsafeRedirects())
    return opener.open(request, timeout=timeout)


def fetch_page(url: str, *, opener: Callable[..., Any] = _default_open,
               resolve: Callable[[str], list[str]] | None = None) -> WebPage:
    url = check_url(url, resolve)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"})
    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type", "")
            media = content_type.split(";")[0].strip().lower()
            if media not in ("text/html", "application/xhtml+xml", "text/plain"):
                raise UnsupportedPageError("The address is not a web page.")
            data = response.read(MAX_PAGE_BYTES + 1)
            final_url = response.geturl() if hasattr(response, "geturl") else url
            charset = response.headers.get_content_charset() or "utf-8"
    except WebPageError:
        raise
    except urllib.error.HTTPError as exc:
        raise WebFetchError(f"The site answered with HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise WebFetchError("The page could not be downloaded.") from None
    if len(data) > MAX_PAGE_BYTES:
        raise UnsupportedPageError("The page is larger than 5 MB.")
    try:
        text = data.decode(charset, errors="replace")
    except LookupError:
        text = data.decode("utf-8", errors="replace")
    if media == "text/plain":
        title = urllib.parse.urlsplit(final_url).path.rsplit("/", 1)[-1] or urllib.parse.urlsplit(final_url).hostname or "Page"
        return WebPage(final_url, title, text.strip() + "\n")
    title, markdown = html_to_markdown(text)
    return WebPage(final_url, title or urllib.parse.urlsplit(final_url).hostname or "Page", markdown)


# Some sites wrap the whole page in a <form>, so forms are kept; their controls carry no text.
_SKIP = {"script", "style", "noscript", "template", "svg", "nav", "footer", "button", "iframe", "select", "aside", "textarea"}
_BLOCK = {"p", "div", "section", "article", "main", "header", "br", "tr", "table", "figure", "figcaption", "blockquote", "dl", "dt", "dd"}


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._pre = 0
        self._lists: list[str] = []
        self._href: str | None = None

    def _newline(self, count: int = 2) -> None:
        self.out.append("\n" * count)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip or tag in _SKIP:
            self._skip += tag in _SKIP
            return
        if tag == "title":
            self._in_title = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._newline()
            self.out.append("#" * int(tag[1]) + " ")
        elif tag in _BLOCK:
            self._newline(1 if tag in ("br", "tr", "dt", "dd") else 2)
        elif tag in ("ul", "ol"):
            self._lists.append(tag)
            self._newline(1)
        elif tag == "li":
            depth = max(len(self._lists) - 1, 0)
            marker = "1." if self._lists and self._lists[-1] == "ol" else "-"
            self.out.append("\n" + "  " * depth + marker + " ")
        elif tag == "pre":
            self._pre += 1
            self.out.append("\n\n```\n")
        elif tag == "code" and not self._pre:
            self.out.append("`")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "a":
            href = dict(attrs).get("href")
            self._href = href if href and href.startswith(("http://", "https://")) else None
            if self._href:
                self.out.append("[")

    def handle_endtag(self, tag: str) -> None:
        if self._skip:
            self._skip -= tag in _SKIP
            return
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") or tag in _BLOCK:
            self._newline()
        elif tag in ("ul", "ol"):
            if self._lists:
                self._lists.pop()
            self._newline()
        elif tag == "pre":
            self._pre = max(self._pre - 1, 0)
            self.out.append("\n```\n\n")
        elif tag == "code" and not self._pre:
            self.out.append("`")
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "a" and self._href:
            self.out.append(f"]({self._href})")
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.out.append(data if self._pre else re.sub(r"\s+", " ", data))


def html_to_markdown(html: str) -> tuple[str, str]:
    """Return the page title and its readable content as Markdown."""
    converter = _Converter()
    converter.feed(html)
    converter.close()
    text = "".join(converter.out)
    lines = [line.rstrip() for line in text.split("\n")]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    cleaned = re.sub(r"\*\*\s*\*\*|\[\s*\]\([^)]*\)", "", cleaned)
    return " ".join(converter.title.split()), cleaned + "\n"


def note_for_page(page: WebPage, saved_at: datetime) -> tuple[PurePosixPath, str]:
    """A note path under ``web/<host>/`` and its content, with source front matter."""
    parts = urllib.parse.urlsplit(page.url)
    host = re.sub(r"[^a-z0-9.-]", "-", (parts.hostname or "site").lower()).strip(".-") or "site"
    slug = re.sub(r"[^a-z0-9]+", "-", page.title.lower()).strip("-")[:60].strip("-") or "page"
    title = page.title.replace('"', "'")
    # Pages usually start with their own top heading; add the title only when they don't.
    heading = "" if page.markdown.startswith("# ") else f"# {page.title}\n\n"
    content = (f'---\nsource: {page.url}\nsaved: {saved_at.date().isoformat()}\ntitle: "{title}"\n---\n\n'
               f"{heading}{page.markdown}")
    return PurePosixPath("web", host, f"{slug}.md"), content
