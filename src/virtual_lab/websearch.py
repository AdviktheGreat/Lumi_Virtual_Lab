"""Searching the web, for a model.

A search is sent to one of two engines. Exa is used when a key for it is in the environment, as EXA_API_KEY,
since it is made to be searched by programs and answers reliably. Without one it is sent to DuckDuckGo's page for
browsers that do not run scripts, which needs nothing and which answers a client that searches quickly with a
challenge instead of results, so the rate is held down and the failure says what to do about it.

The results are titles, addresses, and snippets. A snippet is what an engine chose to quote and is not the page, so
what a search finds is read with the tool that reads a page.
"""

import html
import os
import re
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from html.parser import HTMLParser

from virtual_lab.constants import MAX_WEB_SNIPPET_CHARS, WEB_SEARCH_DEFAULT_RESULTS, WEB_SEARCH_MAX_RESULTS
from virtual_lab.records import truncate_text
from virtual_lab.web import WebRequestError, post_json, request_text

EXA_KEY = "EXA_API_KEY"

# The longest query that is sent, which is far more than a search is helped by
MAX_QUERY_CHARS = 400

EXA_URL = "https://api.exa.ai/search"
DUCKDUCKGO_URL = "https://html.duckduckgo.com/html/"


@dataclass(frozen=True)
class SearchHit:
    """One result of a web search.

    :param title: The title of the page.
    :param url: Its address.
    :param snippet: What the engine quoted of it, which may be empty.
    :param published: The day it was published, as the engine gave it, if it did.
    """

    title: str
    url: str
    snippet: str
    published: str = ""


@dataclass(frozen=True)
class WebSearch:
    """The results of a web search.

    :param query: What was searched for.
    :param engine: Which engine answered.
    :param hits: The results, best first.
    :param note: Something to tell the reader about how it was searched, such as that the engine it was meant for
        failed and another answered.
    """

    query: str
    engine: str
    hits: tuple[SearchHit, ...]
    note: str | None = None

    def report(self) -> str:
        """The results as a model is told of them."""
        count = f"{len(self.hits)} result{'s' if len(self.hits) != 1 else ''}"
        lines = [f'Web search for "{self.query}", by {self.engine}: {count}']
        if self.note:
            lines.append(self.note)
        for number, hit in enumerate(self.hits, 1):
            lines.append("")
            lines.append(f"{number}. {hit.title or hit.url}")
            lines.append(f"   {hit.url}" + (f" (published {hit.published})" if hit.published else ""))
            if hit.snippet:
                lines.append(f"   {hit.snippet}")
        if self.hits:
            lines += ["", "A snippet is only what the engine quoted. Read a page with web_fetch to see what it says."]

        return "\n".join(lines)


def plain(text: object) -> str:
    """Text from an engine, with any markup taken out of it and its spaces made plain, and cut to a snippet's length."""
    unmarked = html.unescape(re.sub(r"<[^>]*>", "", str(text or "")))

    return truncate_text(" ".join(unmarked.split()), MAX_WEB_SNIPPET_CHARS)


def is_web_address(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def search_exa(query: str, limit: int, key: str) -> tuple[SearchHit, ...]:
    """Searches with Exa, which quotes the passages of each page that answer the query.

    :raises WebRequestError: If it cannot be reached or refuses the search.
    """
    found = post_json(
        EXA_URL,
        {"query": query, "type": "auto", "numResults": limit, "contents": {"highlights": True}},
        headers={"x-api-key": key},
    )
    results = found.get("results") if isinstance(found, dict) else None
    hits = []
    for item in results or ():
        if not isinstance(item, dict) or not is_web_address(str(item.get("url", ""))):
            continue
        passages = item.get("highlights")
        quoted = " ... ".join(str(passage) for passage in passages) if isinstance(passages, list) else ""
        hits.append(
            SearchHit(
                plain(item.get("title")),
                str(item["url"]),
                plain(quoted or item.get("text") or item.get("summary")),
                str(item.get("publishedDate") or "")[:10],
            )
        )

    return tuple(hits[:limit])


class DuckDuckGoResults(HTMLParser):
    """Reads the results from the page DuckDuckGo gives to browsers that do not run scripts.

    Each result's title is a link, to its address by way of a redirect through DuckDuckGo that the address is in,
    and its snippet is a link after it. An advertisement is a result of the same shape that is not a link to a
    page, and is left out.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hits: list[SearchHit] = []
        self._title: list[str] | None = None
        self._snippet: list[str] | None = None
        self._address: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        found = dict(attrs)
        classes = (found.get("class") or "").split()
        if "result__a" in classes:
            self._title = []
            self._address = target_of(found.get("href") or "")
            self.hits.append(SearchHit("", self._address or "", ""))
        elif "result__snippet" in classes and self.hits:
            self._snippet = []

    def handle_data(self, data: str) -> None:
        if self._title is not None:
            self._title.append(data)
        elif self._snippet is not None:
            self._snippet.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a":
            return
        if self._title is not None:
            last = self.hits.pop()
            self.hits.append(SearchHit(plain("".join(self._title)), last.url, last.snippet))
            self._title = None
        elif self._snippet is not None:
            last = self.hits.pop()
            self.hits.append(SearchHit(last.title, last.url, plain("".join(self._snippet))))
            self._snippet = None

    def results(self) -> tuple[SearchHit, ...]:
        """The results that lead to pages, which leaves out the advertisements."""
        return tuple(hit for hit in self.hits if hit.url)


def target_of(link: str) -> str:
    """The address a DuckDuckGo result leads to, or an empty string if it does not lead to a page.

    :param link: The result's link, which is DuckDuckGo's redirect with the address in it, or for an advertisement,
        DuckDuckGo's own.
    """
    address = urllib.parse.urljoin("https://duckduckgo.com/", link.strip())
    target = urllib.parse.parse_qs(urllib.parse.urlsplit(address).query).get("uddg")
    if not target or not is_web_address(target[0]):
        return ""

    return target[0]


def search_duckduckgo(query: str, limit: int) -> tuple[SearchHit, ...]:
    """Searches with DuckDuckGo, which needs no key.

    :raises WebRequestError: If it cannot be reached, or answers with a challenge in place of results.
    """
    page = request_text(DUCKDUCKGO_URL, params={"q": query}, max_attempts=2, use_cache=False)
    parser = DuckDuckGoResults()
    parser.feed(page)
    parser.close()
    hits = parser.results()
    if not hits and "anomaly" in page:
        raise WebRequestError(
            "DuckDuckGo asked for proof that this is not a program, which happens when it is searched often. Wait a "
            f"minute, or set {EXA_KEY} to search with an engine that is made for programs"
        )

    return hits[:limit]


def configured_key(name: str) -> str | None:
    """The key in an environment variable, or None if there is not one."""
    return os.environ.get(name, "").strip() or None


def search_web(query: str, limit: int = WEB_SEARCH_DEFAULT_RESULTS) -> WebSearch:
    """Searches the web.

    :param query: What to search for.
    :param limit: How many results to give at most.
    :raises ValueError: If there is nothing to search for, or the limit is not a number of results there may be.
    :raises WebRequestError: If every engine that could be used failed, saying why each did.
    :return: The results.
    """
    query = " ".join(query.split())
    if not query:
        raise ValueError("A search needs something to search for")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"A query is at most {MAX_QUERY_CHARS} characters, and this is {len(query)}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= WEB_SEARCH_MAX_RESULTS:
        raise ValueError(f"limit is how many results to give, from 1 to {WEB_SEARCH_MAX_RESULTS}, not {limit!r}")

    engines: list[tuple[str, Callable[[], tuple[SearchHit, ...]]]] = []
    if exa := configured_key(EXA_KEY):
        engines.append(("Exa", partial(search_exa, query, limit, exa)))
    engines.append(("DuckDuckGo", partial(search_duckduckgo, query, limit)))

    failures: list[str] = []
    for name, search in engines:
        try:
            hits = search()
        except WebRequestError as error:
            refused = " (its key was refused)" if error.status_code in (401, 403) else ""
            failures.append(f"{name} failed{refused}: {redact(str(error))}")
            continue
        note = f"{' '.join(failures)} So the search was made with {name}." if failures else None

        return WebSearch(query, name, hits, note)

    raise WebRequestError(" ".join(failures))


def redact(message: str) -> str:
    """A failure's message without any key in it, which an engine may be said to have refused."""
    if key := configured_key(EXA_KEY):
        message = message.replace(key, "***")

    return message
