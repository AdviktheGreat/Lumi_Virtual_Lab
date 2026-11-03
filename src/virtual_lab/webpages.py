"""Reading a page of the web, for a model.

web.py reaches the services a tool names, so it keeps a list of the hosts it will talk to. A page is the
opposite case: the address is the model's own, and a search result, or the page before it, may be where it
got the address from. So where web.py asks which host, this asks what the host is. An address that does not
lead to the public internet is refused: this machine's own services, the network it is on, and the metadata
service of the cloud it may be running in. That is asked of the address given, of every redirect, and of the
address the connection is actually made to, since a name can lead to one address when it is checked and another
when it is connected to.

What comes back is text, because a model has no use for markup. A page is long, so it is given in parts, each
saying where the next begins, and the text of a page is kept for a few minutes so that reading on does not
fetch it again.
"""

import ipaddress
import re
import socket
import threading
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from virtual_lab.constants import (
    MAX_WEB_PAGE_BYTES,
    MAX_WEB_PAGE_LINKS,
    WEB_MAX_REDIRECTS,
    WEB_PAGE_CACHE_ENTRIES,
    WEB_PAGE_CACHE_SECONDS,
    WEB_PAGE_CHARS,
    WEB_PAGE_TOTAL_SECONDS,
    WEB_TIMEOUT_SECONDS,
    WEB_USER_AGENT,
)
from virtual_lab.web import (
    RATE_LIMITER,
    DisallowedHostError,
    WebRequestError,
    decode_body,
    normalize_url,
    read_bytes_capped,
)

# The ports a page is read from. Another is how a service meant for the machine's own use is usually reached.
STANDARD_PORTS = {"http": 80, "https": 443}

# The part of the network that is the NAT64 translation prefix, in which an IPv4 address is the last four bytes
NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
SIIT_PREFIX = ipaddress.ip_network("::ffff:0:0:0/96")
# The long-deprecated IPv4-compatible form, which no public host has and some stacks may read as the IPv4 address
IPV4_COMPATIBLE_PREFIX = ipaddress.ip_network("::/96")

# What is said of the client, which sites that refuse an unnamed one let through, and which says who is asking
PAGE_HEADERS = {
    "User-Agent": f"Mozilla/5.0 (compatible; {WEB_USER_AGENT})",
    "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,text/plain;q=0.8,*/*;q=0.5",
    "Accept-Language": "en",
}

HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
TEXT_TYPES = frozenset({"application/json", "application/xml", "application/x-ndjson", "application/ld+json"})
PDF_TYPE = "application/pdf"

# Tags whose contents are not the page's text, and those that are its furniture: menus, footers, and sidebars
HIDDEN_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "canvas", "object"})
FURNITURE_TAGS = frozenset({"nav", "footer", "aside"})
BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "header",
        "blockquote",
        "ul",
        "ol",
        "table",
        "tr",
        "pre",
        "figure",
        "figcaption",
        "details",
        "summary",
        "dl",
        "dt",
        "dd",
        "form",
        "address",
        "caption",
        "li",
    }
)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
# The block tags that are set apart from what is around them by a blank line, as the rest are by a line break
PARAGRAPH_TAGS = frozenset(
    {"p", "ul", "ol", "table", "pre", "blockquote", "figure", "details", "dl", "section", "article"}
)

# The most characters of a link's text, and of its address, to list. A longer address is a tracking link or data.
MAX_LINK_LABEL_CHARS = 80
MAX_LINK_CHARS = 200

# Marks the end of a table cell until the line is tidied, and is taken out of the text so that it is not in it
CELL_END = "\ue000"


def is_public_address(address: str) -> bool:
    """Whether an address is one on the public internet.

    :param address: An IPv4 or IPv6 address, as a connection or a resolver reports it.
    :return: False for loopback, private, link-local, reserved, multicast, and the other ranges that are not routed
        on the public internet, and for anything that is not an address.
    """
    try:
        found = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(found, ipaddress.IPv6Address):
        # An IPv6 address that carries an IPv4 one leads to it, so it is as public as that is
        if found in IPV4_COMPATIBLE_PREFIX:
            return False
        embedded = found.ipv4_mapped or found.sixtofour
        if embedded is None and (found in NAT64_PREFIX or found in SIIT_PREFIX):
            embedded = ipaddress.IPv4Address(int(found) & 0xFFFFFFFF)
        if embedded is not None:
            return is_public_address(str(embedded))

    return found.is_global and not found.is_multicast


def refuse_unless_public(host: str, port: int) -> None:
    """Checks that a name leads only to addresses on the public internet.

    Every address it leads to is checked and not just the first, since a connection may be made to any of them.

    :raises DisallowedHostError: If it leads to any that is not, or to none.
    :raises WebRequestError: If it cannot be looked up.
    """
    try:
        found = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as error:
        raise WebRequestError(f"Could not find {host}: {error}") from error
    addresses = {str(entry[4][0]) for entry in found}
    if not addresses or not all(is_public_address(address) for address in addresses):
        # Which address it led to is not said, as it is what the page was being asked for
        raise DisallowedHostError(f"Refusing to read {host}: it is not a site on the public internet")


def check_page_url(url: str) -> str:
    """Checks that an address is one a page may be read from, and returns it as it is to be requested.

    :param url: The address. One without a scheme is taken to be of https.
    :raises DisallowedHostError: If it is not http or https, names a port that is not the standard one, has a name
        and password in it, or leads anywhere but the public internet.
    :raises WebRequestError: If its host cannot be found.
    :return: The address, as the HTTP client will send it.
    """
    url = url.strip()
    if "://" not in url:
        url = f"https://{url}"
    normalized = normalize_url(url)
    try:
        parsed = urllib.parse.urlsplit(normalized)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise DisallowedHostError(f'Refusing to read "{url}": {error}') from error
    if parsed.scheme not in STANDARD_PORTS:
        raise DisallowedHostError(f'Refusing to read "{url}": only http and https addresses are read')
    if parsed.username is not None or parsed.password is not None:
        raise DisallowedHostError(f'Refusing to read "{url}": an address may not carry a name and password')
    if not hostname:
        raise DisallowedHostError(f'Refusing to read "{url}": it has no host')
    if port is not None and port != STANDARD_PORTS[parsed.scheme]:
        raise DisallowedHostError(f'Refusing to read "{url}": only the standard port of {parsed.scheme} is read')
    refuse_unless_public(hostname, STANDARD_PORTS[parsed.scheme])

    return normalized


class PublicOnly:
    """Checks the address a connection was made to, before anything is sent over it.

    The address was checked when the name was looked up, but a name can be made to lead to a public address then
    and a private one a moment later, which is how a check made on a name is got round. Checking where the socket
    is actually connected closes that, and is done before a secure connection's handshake as well as before a
    request.
    """

    def _new_conn(self) -> Any:
        sock = super()._new_conn()  # type: ignore[misc]
        try:
            if not is_public_address(str(sock.getpeername()[0])):
                raise DisallowedHostError("Refusing to read a site that is not on the public internet")
        except BaseException:
            sock.close()
            raise

        return sock


class PublicOnlyConnection(PublicOnly, HTTPConnection):
    pass


class PublicOnlySecureConnection(PublicOnly, HTTPSConnection):
    pass


class PublicOnlyPool(HTTPConnectionPool):
    ConnectionCls = PublicOnlyConnection


class PublicOnlySecurePool(HTTPSConnectionPool):
    ConnectionCls = PublicOnlySecureConnection


class PublicOnlyAdapter(HTTPAdapter):
    """Makes connections that are only to addresses on the public internet."""

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": PublicOnlyPool, "https": PublicOnlySecurePool}


def page_session() -> requests.Session:
    """A session for reading one page, which keeps nothing for the next.

    It ignores the proxy settings of the environment. A connection through a proxy is made to the proxy, which
    leads wherever it is told to, so the address checked would not be the one reached.
    """
    session = requests.Session()
    session.trust_env = False
    adapter = PublicOnlyAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


@dataclass(frozen=True)
class Page:
    """What a page held, as text.

    :param url: Where it was read from, after any redirects.
    :param title: Its title, or an empty string.
    :param kind: Its media type.
    :param text: Its text.
    :param links: The addresses it links to, with what each is called, in the order they are on the page.
    """

    url: str
    title: str
    kind: str
    text: str
    links: tuple[tuple[str, str], ...] = ()

    def report(self, start: int = 0, links: bool = False, chars: int = WEB_PAGE_CHARS) -> str:
        """The page as a model is told of it, from one place in its text, and with where to go on from.

        :param start: The character to begin at.
        :param links: Whether to list the addresses it links to.
        :param chars: The most characters of text to give.
        """
        total = len(self.text)
        heading = [f"Page: {self.title}" if self.title else "Page:", f"URL: {self.url}", f"Type: {self.kind}"]
        if start < 0:
            raise ValueError(f"start is where to begin reading, a number of characters from the top, not {start}")
        if total == 0:
            body = "The page has no text that can be read. It may be made by scripts that are not run here."
            notes = []
        elif start >= total:
            raise ValueError(f"The page has {total:,} characters, so there is nothing to read from {start:,}")
        else:
            end = min(start + chars, total)
            if end < total:
                # Ended at a paragraph where there is one near, rather than in the middle of a sentence
                cut = self.text.rfind("\n", start + chars * 4 // 5, end)
                end = cut if cut > start else end
            body = self.text[start:end]
            notes = [f"Characters {start:,} to {end:,} of {total:,}."]
            if end < total:
                notes.append(f"To read on, call again with start={end}.")
        parts = [*heading, *notes, "----", body]
        if links and self.links:
            listed = "\n".join(f"- {label or '(no text)'}: {link}" for link, label in self.links)
            parts += ["----", f"Links on the page ({len(self.links)}):", listed]

        return "\n".join(parts)


class TextExtractor(HTMLParser):
    """Reads the text of an HTML page, with its headings, lists, and tables kept as lines, and the links in it.

    The standard library's parser is used because it does not give up on the HTML of the real web, and no other
    is a dependency of this library.

    :param base: The address of the page, which relative links are against.
    :param drop_furniture: Whether to leave out menus, footers, and sidebars.
    """

    def __init__(self, base: str, drop_furniture: bool = True) -> None:
        super().__init__(convert_charrefs=True)
        self.base = base
        self.drop_furniture = drop_furniture
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.links: dict[str, str] = {}
        self.refresh: str | None = None
        self._hidden: str | None = None
        self._depth = 0
        self._in_title = False
        self._pre = 0
        self._link: tuple[str, list[str]] | None = None

    def _at_line_start(self) -> bool:
        return not self.parts or self.parts[-1].endswith("\n")

    def _break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._hidden is not None:
            if tag == self._hidden:
                self._depth += 1
            return
        if tag in HIDDEN_TAGS or (self.drop_furniture and tag in FURNITURE_TAGS):
            self._hidden, self._depth = tag, 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta":
            fields = {name: value or "" for name, value in attrs}
            moved = re.search(r"url\s*=\s*[\"']?([^\"';\s]+)", fields.get("content", ""), re.IGNORECASE)
            if fields.get("http-equiv", "").lower() == "refresh" and moved:
                self.refresh = urllib.parse.urljoin(self.base, moved[1])
        elif tag in HEADING_TAGS:
            self._break()
            self.parts.append("\n" + "#" * int(tag[1]) + " ")
        elif tag in ("td", "th"):
            # A cell that follows text without the one before it having been closed is still a cell
            if not self._at_line_start() and self.parts[-1] != CELL_END:
                self.parts.append(CELL_END)
        elif tag == "li":
            self._break()
            self.parts.append("- ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "hr":
            self._break()
        elif tag == "pre":
            self.parts.append("\n\n")
            self._pre += 1
        elif tag in PARAGRAPH_TAGS:
            self.parts.append("\n\n")
        elif tag in BLOCK_TAGS:
            self._break()
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                # Joined against the page, and without what is after a #, which is a place in the page
                found = urllib.parse.urldefrag(urllib.parse.urljoin(self.base, href.strip()))[0]
                if found.startswith(("http://", "https://")) and found != self.base and len(found) <= MAX_LINK_CHARS:
                    self._link = (found, [])

    def handle_endtag(self, tag: str) -> None:
        if self._hidden is not None:
            if tag == self._hidden:
                self._depth -= 1
                if self._depth == 0:
                    self._hidden = None
            return
        if tag == "title":
            self._in_title = False
        elif tag in HEADING_TAGS:
            self.parts.append("\n\n")
        elif tag in ("td", "th"):
            self.parts.append(CELL_END)
        elif tag == "pre":
            self._pre = max(0, self._pre - 1)
            self.parts.append("\n\n")
        elif tag in PARAGRAPH_TAGS:
            self.parts.append("\n\n")
        elif tag in BLOCK_TAGS:
            self._break()
        elif tag == "a" and self._link is not None:
            found, label = self._link
            self._link = None
            text = " ".join("".join(label).split())
            if found not in self.links or (text and not self.links[found]):
                self.links[found] = text[:MAX_LINK_LABEL_CHARS]

    def handle_data(self, data: str) -> None:
        if self._hidden is not None:
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        data = data.replace(CELL_END, " ")
        if self._link is not None:
            self._link[1].append(data)
        if self._pre:
            self.parts.append(data)
            return
        data = re.sub(r"\s+", " ", data)
        if self._at_line_start() or (self.parts and self.parts[-1].endswith(" ")):
            data = data.lstrip(" ")
        if data:
            self.parts.append(data)

    def text(self) -> str:
        """The text read, tidied into lines with no more than one blank between."""
        lines = []
        for line in "".join(self.parts).split("\n"):
            line = re.sub(rf"(\s*{CELL_END})+\s*$", "", line)
            line = re.sub(rf"\s*{CELL_END}\s*", " | ", line).rstrip()
            lines.append(line)

        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())

    @property
    def furniture_left_open(self) -> bool:
        """Whether the page ended inside a menu, footer, or sidebar, which is a sign that it was never closed."""
        return self._hidden in FURNITURE_TAGS


def read_html(html: str, base: str) -> tuple[str, str, dict[str, str]]:
    """The title, text, and links of an HTML page.

    :param html: The page.
    :param base: Its address.
    """
    extractor = TextExtractor(base)
    extractor.feed(html)
    extractor.close()
    text = extractor.text()
    if extractor.furniture_left_open:
        # A menu or a footer that was never closed takes the rest of the page with it, so it is read again with
        # them kept, and what it makes of it is used if it is more
        again = TextExtractor(base, drop_furniture=False)
        again.feed(html)
        again.close()
        if len(again.text()) > len(text):
            extractor, text = again, again.text()

    if not text and extractor.refresh:
        # A page that only sends the browser on, as the pages of some sites that have moved do
        text = f"This page only sends the reader on to {extractor.refresh}. Read that address instead."

    return extractor.title(), text, extractor.links


def header_charset(response: requests.Response) -> str | None:
    """The character set a response says it is in, if it says."""
    found = re.search(r"charset\s*=\s*[\"']?([\w.:-]+)", response.headers.get("Content-Type", ""), re.IGNORECASE)

    return found[1] if found else None


def html_charset(body: bytes) -> str | None:
    """The character set an HTML page says it is in, in a tag near its top, if it says."""
    found = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?([\w.:-]+)", body[:4096], re.IGNORECASE)

    return found[1].decode("ascii", errors="replace") if found else None


def media_type(response: requests.Response, body: bytes) -> str:
    """What kind of thing a response is, from what it says and, where it says nothing useful, from what it is."""
    said = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if said and said not in ("application/octet-stream", "binary/octet-stream"):
        return said
    head = body[:2048].lstrip().lower()
    if head.startswith(b"%pdf-"):
        return PDF_TYPE
    if head.startswith((b"<!doctype html", b"<html")):
        return "text/html"
    if b"\x00" not in body[:2048]:
        return "text/plain"

    return said or "application/octet-stream"


def page_from(response: requests.Response, url: str, body: bytes) -> Page:
    """What a response holds, as a page.

    :param response: The response.
    :param url: Where it came from.
    :param body: What it sent.
    :raises WebRequestError: If it is not something that has text to read, or is a document that cannot be read.
    """
    kind = media_type(response, body)
    if kind in HTML_TYPES:
        html = decode_body(body, header_charset(response) or html_charset(body) or "utf-8")
        title, text, links = read_html(html, url)

        return Page(url, title, kind, text, tuple(links.items())[:MAX_WEB_PAGE_LINKS])
    if kind == PDF_TYPE:
        from virtual_lab.papers import pdf_text

        try:
            return Page(url, "", kind, tidy_text(pdf_text(body, url)))
        except ImportError as error:
            raise WebRequestError(f"{url} is a PDF, and reading one needs pypdf: {error}") from error
        except ValueError as error:
            raise WebRequestError(str(error)) from error
    if kind.startswith("text/") or kind in TEXT_TYPES or kind.endswith(("+json", "+xml")):
        return Page(url, "", kind, tidy_text(decode_body(body, header_charset(response) or "utf-8")))

    raise WebRequestError(
        f"{url} is {kind}, which is not text, and a page is read as text. Code can download it, where it can reach "
        "the internet."
    )


def tidy_text(text: str) -> str:
    """Text with its line endings made plain, no more than one blank line between paragraphs, and nothing at the
    ends. A NUL is taken out, which a model is not helped by."""
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")

    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in text.split("\n"))).strip()


def status_message(url: str, status: int) -> str:
    """What to say of a page that was refused or not found."""
    hint = {
        401: "it needs a login",
        403: "it refuses automated readers, or needs a login",
        404: "there is no such page",
        410: "it has been removed",
        429: "it is limiting how often it is read, so try again later",
    }.get(status)

    return f"{url} returned {status}" + (f": {hint}" if hint else "")


def fetch_page(url: str) -> Page:
    """Reads a page from the web.

    Redirects are followed by hand, so that the address each leads to is checked before it is requested.

    :param url: The address.
    :raises DisallowedHostError: If it, or a redirect from it, is not a site on the public internet.
    :raises ResponseTooLargeError: If the page is more than MAX_WEB_PAGE_BYTES.
    :raises WebRequestError: If it cannot be read.
    :return: What it held.
    """
    deadline = time.monotonic() + WEB_PAGE_TOTAL_SECONDS
    current = check_page_url(url)
    session = page_session()
    try:
        for _ in range(WEB_MAX_REDIRECTS + 1):
            RATE_LIMITER.wait(urllib.parse.urlsplit(current).hostname or "")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WebRequestError(f"{current} was too slow to send")
            try:
                with session.get(
                    current,
                    headers=PAGE_HEADERS,
                    timeout=min(WEB_TIMEOUT_SECONDS, remaining),
                    stream=True,
                    allow_redirects=False,
                ) as response:
                    if 300 <= response.status_code < 400:
                        location = response.headers.get("Location")
                        if not location:
                            raise WebRequestError(f"{current} returned {response.status_code} with no location")
                        current = check_page_url(urllib.parse.urljoin(current, location))
                        continue
                    if not response.ok:
                        raise WebRequestError(status_message(current, response.status_code), response.status_code)

                    return page_from(response, current, read_bytes_capped(response, MAX_WEB_PAGE_BYTES, deadline))
            except requests.RequestException as error:
                raise WebRequestError(f"Could not read {current}: {type(error).__name__}: {error}") from error
    finally:
        session.close()

    raise WebRequestError(f"{url} redirected more than {WEB_MAX_REDIRECTS} times")


class PageCache:
    """Remembers the pages read lately, so that reading on from where a call stopped is not another request."""

    def __init__(self, entries: int = WEB_PAGE_CACHE_ENTRIES, seconds: float = WEB_PAGE_CACHE_SECONDS) -> None:
        self.entries = entries
        self.seconds = seconds
        self._pages: OrderedDict[str, tuple[float, Page]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, url: str) -> Page | None:
        with self._lock:
            held = self._pages.get(url)
            if held is None:
                return None
            if time.monotonic() - held[0] > self.seconds:
                del self._pages[url]
                return None
            self._pages.move_to_end(url)

            return held[1]

    def put(self, url: str, page: Page) -> None:
        with self._lock:
            self._pages[url] = (time.monotonic(), page)
            self._pages.move_to_end(url)
            while len(self._pages) > self.entries:
                self._pages.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._pages.clear()


PAGE_CACHE = PageCache()


def read_page(url: str, start: int = 0, links: bool = False) -> str:
    """Reads a page from the web and renders it for a model.

    :param url: The address.
    :param start: The character of its text to begin at, to read on from where an earlier call stopped.
    :param links: Whether to list the addresses it links to.
    :raises DisallowedHostError: If the address is not a site on the public internet.
    :raises WebRequestError: If it cannot be read.
    :raises ValueError: If start is not a place in the text.
    """
    key = url.strip()
    page = PAGE_CACHE.get(key)
    if page is None:
        page = fetch_page(url)
        PAGE_CACHE.put(key, page)

    return page.report(start=start, links=links)
