"""Tests for searching the web on behalf of a model.

These run offline against responses shaped like the real ones. DuckDuckGo's is the one most likely to change under
the parser, so its fixture is trimmed from a page it really sent, and a test at the end reads the real one when
VIRTUAL_LAB_LIVE_TESTS=1 is set.
"""

import os
from urllib.parse import parse_qs, urlsplit

import pytest
from conftest import FakeResponse, FakeTransport

from virtual_lab.constants import MAX_WEB_SNIPPET_CHARS, WEB_SEARCH_MAX_RESULTS
from virtual_lab.web import WebRequestError
from virtual_lab.websearch import (
    BRAVE_KEY,
    MAX_QUERY_CHARS,
    TAVILY_KEY,
    DuckDuckGoResults,
    SearchHit,
    WebSearch,
    plain,
    search_web,
    target_of,
)

live_only = pytest.mark.skipif(
    os.environ.get("VIRTUAL_LAB_LIVE_TESTS") != "1",
    reason="Set VIRTUAL_LAB_LIVE_TESTS=1 to query the real services",
)

# Trimmed from a page DuckDuckGo sent for the query "DepMap CRISPR gene effect", with an advertisement of the shape it
# sends added, since a search that has none is not the usual case
DUCKDUCKGO_PAGE = """
<html><body><div id="links" class="results">
  <div class="result results_links results_links_deep result--ad">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a rel="nofollow" class="result__a" href="https://duckduckgo.com/y.js?ad_domain=shop.example&amp;ad_provider=bing">A shop</a>
      </h2>
      <a class="result__snippet" href="https://duckduckgo.com/y.js?ad_domain=shop.example">Buy things now</a>
    </div>
  </div>
  <div class="result results_links results_links_deep web-result ">
    <div class="links_main links_deep result__body"> <!-- This is the visible part -->
      <h2 class="result__title">
        <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdepmap.org%2F&amp;rut=06a9cb">DepMap: The Cancer Dependency Map Project at Broad Institute</a>
      </h2>
      <div class="result__extras">
        <div class="result__extras__url">
          <span class="result__icon"><a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdepmap.org%2F&amp;rut=06a9cb"><img class="result__icon__img" alt="" src="//external-content.duckduckgo.com/ip3/depmap.org.ico" /></a></span>
          <a class="result__url" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdepmap.org%2F&amp;rut=06a9cb">
            depmap.org
          </a>
        </div>
      </div>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdepmap.org%2F&amp;rut=06a9cb">Updates to <b>CRISPR</b> pipeline including improvements in library correction, ChrY <b>gene</b> <b>effect</b> correction &amp; more.</a>
      <div class="clear"></div>
    </div>
  </div>
  <div class="result results_links results_links_deep web-result ">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdepmap.org%2Fportal%2Fdata_page%2F%3Frelease%3DDepMap%2BPublic%2B22Q4%26file%3DCRISPRGeneEffect.csv&amp;rut=88ac17">DepMap — Data downloads</a>
      </h2>
      <a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdepmap.org%2Fportal%2Fdata_page%2F">Gene effect scores: more negative means more essential.</a>
    </div>
  </div>
  <div class="result results_links results_links_deep web-result ">
    <div class="links_main links_deep result__body">
      <h2 class="result__title">
        <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fno-snippet">No snippet here</a>
      </h2>
    </div>
  </div>
</div></body></html>
"""  # noqa: E501

CHALLENGE_PAGE = (
    '<html><body><div class="anomaly-modal__modal">Unfortunately, bots use DuckDuckGo too.</div></body></html>'
)
NO_RESULTS_PAGE = '<html><body><div class="no-results">No results.</div></body></html>'


@pytest.fixture(autouse=True)
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Searches the way a person with no key does, unless a test says otherwise."""
    monkeypatch.delenv(TAVILY_KEY, raising=False)
    monkeypatch.delenv(BRAVE_KEY, raising=False)


def duckduckgo(transport: FakeTransport, page: str = DUCKDUCKGO_PAGE, status: int = 200) -> None:
    headers = {"Content-Type": "text/html"}
    transport.responses.append(FakeResponse(status_code=status, body=page.encode(), headers=headers))


class TestReadingDuckDuckGo:
    def read(self, page: str) -> tuple[SearchHit, ...]:
        parser = DuckDuckGoResults()
        parser.feed(page)
        parser.close()

        return parser.results()

    def test_each_result_is_its_title_where_it_leads_and_what_was_quoted_of_it(self) -> None:
        hits = self.read(DUCKDUCKGO_PAGE)

        assert hits[0] == SearchHit(
            "DepMap: The Cancer Dependency Map Project at Broad Institute",
            "https://depmap.org/",
            "Updates to CRISPR pipeline including improvements in library correction, ChrY gene effect "
            "correction & more.",
        )

    def test_the_address_is_the_one_in_the_redirect_and_not_the_redirect(self) -> None:
        hits = self.read(DUCKDUCKGO_PAGE)

        assert [hit.url for hit in hits] == [
            "https://depmap.org/",
            "https://depmap.org/portal/data_page/?release=DepMap+Public+22Q4&file=CRISPRGeneEffect.csv",
            "https://example.org/no-snippet",
        ]
        assert not any("duckduckgo.com" in hit.url for hit in hits)

    def test_an_advertisement_is_left_out_and_its_snippet_is_not_given_to_a_result(self) -> None:
        hits = self.read(DUCKDUCKGO_PAGE)

        assert "A shop" not in [hit.title for hit in hits]
        assert "Buy things now" not in [hit.snippet for hit in hits]
        assert hits[0].snippet.startswith("Updates to")

    def test_a_result_with_no_snippet_has_an_empty_one_and_does_not_take_the_next_ones(self) -> None:
        hits = self.read(DUCKDUCKGO_PAGE)

        assert hits[-1] == SearchHit("No snippet here", "https://example.org/no-snippet", "")
        assert hits[1].snippet == "Gene effect scores: more negative means more essential."

    def test_a_page_with_no_results_has_none(self) -> None:
        assert self.read(NO_RESULTS_PAGE) == ()
        assert self.read("") == ()

    @pytest.mark.parametrize(
        ("link", "target"),
        [
            ("//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.org%2Fx%3Fy%3D1&rut=z", "https://a.org/x?y=1"),
            ("https://duckduckgo.com/l/?uddg=http%3A%2F%2Fa.org%2F", "http://a.org/"),
            ("https://duckduckgo.com/y.js?ad_domain=shop.example", ""),
            ("//duckduckgo.com/l/?uddg=javascript%3Aalert(1)", ""),
            ("//duckduckgo.com/l/?uddg=file%3A%2F%2F%2Fetc%2Fpasswd", ""),
            ("//duckduckgo.com/l/?rut=z", ""),
            ("", ""),
        ],
    )
    def test_where_a_result_leads_is_read_from_its_link(self, link: str, target: str) -> None:
        assert target_of(link) == target


class TestSearchingWithoutAKey:
    def test_the_search_goes_to_duckduckgo_with_the_query_and_the_results_say_so(
        self, web_transport: FakeTransport
    ) -> None:
        duckduckgo(web_transport)

        found = search_web("DepMap  CRISPR\ngene effect")

        assert web_transport.urls == ["https://html.duckduckgo.com/html/"]
        assert web_transport.params == [{"q": "DepMap CRISPR gene effect"}]
        assert found.engine == "DuckDuckGo"
        assert found.note is None
        assert [hit.title for hit in found.hits][0].startswith("DepMap: The Cancer")
        assert 'Web search for "DepMap CRISPR gene effect", by DuckDuckGo: 3 results' in found.report()

    def test_the_results_are_as_many_as_asked_for(self, web_transport: FakeTransport) -> None:
        duckduckgo(web_transport)

        assert len(search_web("depmap", limit=2).hits) == 2

    def test_the_client_says_who_is_asking(self, web_transport: FakeTransport) -> None:
        duckduckgo(web_transport)

        search_web("depmap")

        assert "virtual-lab" in web_transport.requests[0]["headers"]["User-Agent"]

    def test_the_same_search_is_made_again_and_not_remembered(self, web_transport: FakeTransport) -> None:
        duckduckgo(web_transport)
        duckduckgo(web_transport, NO_RESULTS_PAGE)

        assert len(search_web("depmap").hits) == 3
        assert len(search_web("depmap").hits) == 0

    def test_a_search_that_finds_nothing_says_so(self, web_transport: FakeTransport) -> None:
        duckduckgo(web_transport, NO_RESULTS_PAGE)

        found = search_web("qwertyuiop asdfghjkl")

        assert found.hits == ()
        assert found.report() == 'Web search for "qwertyuiop asdfghjkl", by DuckDuckGo: 0 results'

    def test_a_challenge_in_place_of_results_says_what_to_do_about_it(self, web_transport: FakeTransport) -> None:
        duckduckgo(web_transport, CHALLENGE_PAGE, status=202)

        with pytest.raises(WebRequestError, match=f"asked for proof.*{TAVILY_KEY} or {BRAVE_KEY}"):
            search_web("depmap")

    def test_a_service_that_is_down_is_a_failed_search(self, web_transport: FakeTransport) -> None:
        web_transport.responses += [FakeResponse(status_code=503), FakeResponse(status_code=503)]

        with pytest.raises(WebRequestError, match="DuckDuckGo failed"):
            search_web("depmap")


class TestSearchingWithAKey:
    TAVILY = {
        "results": [
            {
                "title": "Tavily <b>one</b>",
                "url": "https://one.example/a",
                "content": "First   snippet\nhere.",
                "score": 0.9,
            },
            {"title": "Two", "url": "https://two.example/b", "content": "", "score": 0.5},
            {"title": "Not a page", "url": "javascript:alert(1)", "content": "x"},
            {"title": "No address", "content": "x"},
            "not a result",
        ]
    }
    BRAVE = {
        "web": {
            "results": [
                {
                    "title": "Brave <strong>one</strong>",
                    "url": "https://one.example/a",
                    "description": "A <strong>bold</strong> &amp; true claim.",
                },
                {"title": "Two", "url": "https://two.example/b"},
            ]
        }
    }

    def test_tavily_is_used_when_there_is_a_key_and_the_key_is_sent_as_a_credential(
        self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TAVILY_KEY, "tvly-secret")
        web_transport.post_responses.append(FakeResponse(json_body=self.TAVILY))

        found = search_web("depmap", limit=5)

        assert found.engine == "Tavily"
        assert web_transport.requests == []
        sent = web_transport.post_requests[0]
        assert sent["url"] == "https://api.tavily.com/search"
        assert sent["json"] == {"query": "depmap", "max_results": 5, "search_depth": "basic"}
        assert sent["headers"]["Authorization"] == "Bearer tvly-secret"
        assert found.hits == (
            SearchHit("Tavily one", "https://one.example/a", "First snippet here."),
            SearchHit("Two", "https://two.example/b", ""),
        )

    def test_brave_is_used_when_there_is_a_key_and_no_tavily_one(
        self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(BRAVE_KEY, "brave-secret")
        web_transport.responses.append(FakeResponse(json_body=self.BRAVE))

        found = search_web("depmap", limit=7)

        assert found.engine == "Brave Search"
        request = web_transport.requests[0]
        assert urlsplit(request["url"]).netloc == "api.search.brave.com"
        assert request["params"] == {"q": "depmap", "count": 7}
        assert request["headers"]["X-Subscription-Token"] == "brave-secret"
        assert found.hits[0] == SearchHit("Brave one", "https://one.example/a", "A bold & true claim.")

    def test_tavily_is_preferred_to_brave(self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(TAVILY_KEY, "tvly-secret")
        monkeypatch.setenv(BRAVE_KEY, "brave-secret")
        web_transport.post_responses.append(FakeResponse(json_body=self.TAVILY))

        assert search_web("depmap").engine == "Tavily"

    def test_a_key_of_only_spaces_is_no_key(
        self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TAVILY_KEY, "   ")
        duckduckgo(web_transport)

        assert search_web("depmap").engine == "DuckDuckGo"

    def test_an_engine_that_refuses_the_key_is_said_to_have_and_the_next_is_used(
        self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TAVILY_KEY, "tvly-secret")
        web_transport.post_responses.append(FakeResponse(status_code=401))
        duckduckgo(web_transport)

        found = search_web("depmap")

        assert found.engine == "DuckDuckGo"
        assert found.note is not None
        assert "Tavily failed (its key was refused)" in found.note
        assert "So the search was made with DuckDuckGo." in found.note
        assert found.note in found.report()

    def test_an_engine_that_is_down_is_said_to_be_and_the_next_is_used(
        self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(BRAVE_KEY, "brave-secret")
        web_transport.responses += [FakeResponse(status_code=500)] * 3
        duckduckgo(web_transport)

        found = search_web("depmap")

        assert found.engine == "DuckDuckGo"
        assert found.note is not None and "Brave Search failed:" in found.note

    def test_when_every_engine_fails_each_is_named_and_no_key_is_given_away(
        self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TAVILY_KEY, "tvly-secret")
        web_transport.post_responses.append(FakeResponse(status_code=403))
        duckduckgo(web_transport, CHALLENGE_PAGE, status=202)

        with pytest.raises(WebRequestError) as failed:
            search_web("depmap")

        message = str(failed.value)
        assert "Tavily failed (its key was refused)" in message
        assert "DuckDuckGo failed" in message
        assert "tvly-secret" not in message

    def test_a_key_that_an_error_repeats_is_taken_out_of_it(
        self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(BRAVE_KEY, "brave-secret")

        def echo(url: str, **kwargs: object) -> FakeResponse:
            raise WebRequestError(f"{url} refused brave-secret")

        monkeypatch.setattr("virtual_lab.websearch.request_json", echo)
        duckduckgo(web_transport)

        found = search_web("depmap")

        assert found.note is not None
        assert "brave-secret" not in found.note and "***" in found.note

    def test_a_key_is_not_in_what_the_model_is_told(
        self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TAVILY_KEY, "tvly-secret")
        web_transport.post_responses.append(FakeResponse(json_body=self.TAVILY))

        assert "tvly-secret" not in search_web("depmap").report()

    def test_a_reply_of_the_wrong_shape_is_no_results_and_not_a_crash(
        self, web_transport: FakeTransport, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TAVILY_KEY, "tvly-secret")
        web_transport.post_responses.append(FakeResponse(json_body=["unexpected"]))

        assert search_web("depmap").hits == ()


class TestWhatIsAskedFor:
    @pytest.mark.parametrize("query", ["", "   ", "\n\t"])
    def test_a_search_needs_something_to_search_for(self, query: str) -> None:
        with pytest.raises(ValueError, match="needs something to search for"):
            search_web(query)

    def test_a_query_that_is_far_too_long_is_refused(self) -> None:
        with pytest.raises(ValueError, match=f"at most {MAX_QUERY_CHARS} characters"):
            search_web("word " * 500)

    @pytest.mark.parametrize("limit", [0, -1, WEB_SEARCH_MAX_RESULTS + 1, True, "5", 2.5, None])
    def test_a_number_of_results_there_cannot_be_is_refused(self, limit: object) -> None:
        with pytest.raises(ValueError, match="limit is how many results"):
            search_web("depmap", limit=limit)  # type: ignore[arg-type]

    def test_the_most_results_there_may_be_is_allowed(self, web_transport: FakeTransport) -> None:
        duckduckgo(web_transport)

        assert search_web("depmap", limit=WEB_SEARCH_MAX_RESULTS).hits


class TestWhatTheModelIsTold:
    def test_each_result_is_numbered_with_its_address_and_snippet_and_the_reader_is_told_a_snippet_is_not_the_page(
        self,
    ) -> None:
        said = WebSearch(
            "q", "Brave Search", (SearchHit("One", "https://a.org/", "About one."), SearchHit("", "https://b.org/", ""))
        ).report()

        assert said == (
            'Web search for "q", by Brave Search: 2 results\n'
            "\n1. One\n   https://a.org/\n   About one.\n"
            "\n2. https://b.org/\n   https://b.org/\n"
            "\nA snippet is only what the engine quoted. Read a page with web_fetch to see what it says."
        )

    def test_one_result_is_not_called_results(self) -> None:
        assert ": 1 result\n" in WebSearch("q", "DuckDuckGo", (SearchHit("One", "https://a.org/", ""),)).report()

    def test_markup_is_taken_out_of_what_an_engine_quotes_and_its_spaces_made_plain(self) -> None:
        assert plain("A <b>bold</b>\n\n  &amp; <i>slanted</i>  &lt;claim&gt;") == "A bold & slanted <claim>"
        assert plain(None) == ""

    def test_a_snippet_is_cut_to_the_length_one_is_shown_at(self) -> None:
        assert len(plain("word " * 500)) <= MAX_WEB_SNIPPET_CHARS + 100
        assert plain("word " * 500).startswith("word word")


@live_only
class TestTheRealDuckDuckGo:
    """Whether the parser still reads the page DuckDuckGo sends, which is the one thing here that can stop being so."""

    def test_a_real_search_gives_results_with_titles_addresses_and_snippets(self) -> None:
        found = search_web("DepMap CRISPR gene effect", limit=5)

        assert found.hits
        assert all(hit.title and hit.url.startswith("http") and "duckduckgo.com" not in hit.url for hit in found.hits)
        assert any(hit.snippet for hit in found.hits)
        assert parse_qs(urlsplit(found.hits[0].url).query) is not None
