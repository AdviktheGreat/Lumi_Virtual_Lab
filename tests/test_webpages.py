"""Tests for reading a page of the web on behalf of a model.

These run offline. The address of every page is the model's own, so the tests that matter most are those of what is
refused: what an address leads to, at the start and at each redirect, and where the socket is actually connected.
The rest is that a page comes back as text a model can use, in parts it can go on from.
"""

import http.server
import threading
from collections.abc import Iterator
from typing import Any

import pytest
import requests
from conftest import FakeResponse

import virtual_lab.papers
import virtual_lab.webpages as webpages
from virtual_lab.constants import WEB_MAX_REDIRECTS, WEB_PAGE_CHARS
from virtual_lab.web import DisallowedHostError, ResponseTooLargeError, WebRequestError
from virtual_lab.webpages import (
    PAGE_CACHE,
    Page,
    PageCache,
    PublicOnlyAdapter,
    check_page_url,
    fetch_page,
    is_public_address,
    page_session,
    read_html,
    read_page,
)

PUBLIC = "93.184.216.34"
HOSTS = {
    "example.org": [PUBLIC],
    "www.example.org": [PUBLIC],
    "intranet.example.org": ["10.1.2.3"],
    "both.example.org": [PUBLIC, "192.168.0.7"],
    "metadata.example.org": ["169.254.169.254"],
    "loopback6.example.org": ["::1"],
    "mapped.example.org": ["::ffff:127.0.0.1"],
}


def resolver(host: str, port: Any, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
    # An address written out leads to itself, as it does for a real resolver
    if host not in HOSTS and not host.replace(".", "").isdigit():
        raise OSError(f"no such host {host}")
    return [(0, 0, 0, "", (address, port)) for address in HOSTS.get(host, [host])]


@pytest.fixture(autouse=True)
def fast_and_isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    PAGE_CACHE.clear()
    monkeypatch.setattr(webpages.RATE_LIMITER, "min_interval", 0.0)
    monkeypatch.setattr(webpages.time, "sleep", lambda seconds: None)

    yield

    PAGE_CACHE.clear()


@pytest.fixture
def names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Makes the names above lead where they say, and any other not be found."""

    def lookup(host: str, port: Any, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        try:
            return resolver(host, port)
        except OSError as error:
            raise webpages.socket.gaierror(str(error)) from error

    monkeypatch.setattr(webpages.socket, "getaddrinfo", lookup)


class FakeSession:
    """Stands in for the session a page is read with, answering with the responses it is given in order."""

    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.requests.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"Unexpected request to {url}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response

        return response

    def close(self) -> None:
        self.closed = True

    @property
    def urls(self) -> list[str]:
        return [request["url"] for request in self.requests]


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch, names: None) -> FakeSession:
    """The session pages are read with, which has nothing to answer until a test gives it something."""
    fake = FakeSession()
    monkeypatch.setattr(webpages, "page_session", lambda: fake)

    return fake


def html(body: str, headers: dict[str, str] | None = None, status: int = 200) -> FakeResponse:
    return FakeResponse(
        status_code=status, body=body.encode(), headers={"Content-Type": "text/html; charset=utf-8", **(headers or {})}
    )


def redirect(location: str, status: int = 302) -> FakeResponse:
    return FakeResponse(status_code=status, headers={"Location": location})


class TestWhichAddressesArePublic:
    @pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
    def test_an_address_on_the_public_internet_is(self, address: str) -> None:
        assert is_public_address(address)

    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "127.1.2.3",
            "10.0.0.1",
            "172.16.0.1",
            "172.31.255.255",
            "192.168.1.1",
            "169.254.169.254",
            "0.0.0.0",
            "100.64.0.1",
            "192.0.0.1",
            "198.18.0.1",
            "224.0.0.1",
            "255.255.255.255",
            "::1",
            "::",
            "fe80::1",
            "fe80::1%en0",
            "fc00::1",
            "fd12:3456::1",
            "ff02::1",
            "not an address",
            "",
        ],
    )
    def test_an_address_that_is_not_routed_there_is_not(self, address: str) -> None:
        assert not is_public_address(address)

    @pytest.mark.parametrize(
        "address",
        [
            # IPv6 forms that lead to an IPv4 address are as public as that one is
            "::ffff:127.0.0.1",
            "::ffff:10.0.0.1",
            "::ffff:169.254.169.254",
            "2002:7f00:1::1",
            "2002:a9fe:a9fe::1",
            "64:ff9b::7f00:1",
            "64:ff9b::a00:1",
        ],
    )
    def test_an_ipv6_address_that_leads_to_a_private_ipv4_one_is_not(self, address: str) -> None:
        assert not is_public_address(address)

    @pytest.mark.parametrize("address", ["::ffff:8.8.8.8", "2002:808:808::1", "64:ff9b::808:808"])
    def test_an_ipv6_address_that_leads_to_a_public_ipv4_one_is(self, address: str) -> None:
        assert is_public_address(address)


class TestWhichAddressesMayBeRead:
    def test_a_page_of_a_public_site_is_allowed(self, names: None) -> None:
        assert check_page_url("https://example.org/a/b?c=d") == "https://example.org/a/b?c=d"
        assert check_page_url("http://example.org/") == "http://example.org/"
        assert check_page_url("https://example.org:443/") == "https://example.org:443/"

    def test_an_address_without_a_scheme_is_taken_to_be_https(self, names: None) -> None:
        assert check_page_url("  www.example.org/page ") == "https://www.example.org/page"

    @pytest.mark.parametrize("host", ["intranet", "both", "metadata", "loopback6", "mapped"])
    def test_a_name_that_leads_to_a_private_address_is_refused(self, host: str, names: None) -> None:
        with pytest.raises(DisallowedHostError, match="not a site on the public internet"):
            check_page_url(f"https://{host}.example.org/")

    def test_the_refusal_does_not_say_where_the_name_led(self, names: None) -> None:
        with pytest.raises(DisallowedHostError) as refused:
            check_page_url("https://intranet.example.org/")

        assert "10.1.2.3" not in str(refused.value)

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/",
            "http://localhost/",
            "http://localhost./",
            "http://[::1]/",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/",
            "http://192.168.1.1/admin",
            "http://0.0.0.0/",
            "http://0/",
            # Other ways of writing 127.0.0.1, which a resolver reads and a text match does not
            "http://2130706433/",
            "http://0x7f.0.0.1/",
            "http://127.1/",
            "http://[::ffff:127.0.0.1]/",
            "http://[::ffff:7f00:1]/",
        ],
    )
    def test_an_address_that_is_the_machine_or_its_network_is_refused_however_it_is_written(self, url: str) -> None:
        with pytest.raises((DisallowedHostError, WebRequestError)):
            check_page_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "ftp://example.org/x",
            "gopher://example.org/x",
            "data:text/html,hello",
            "javascript:alert(1)",
            "mailto:someone@example.org",
        ],
    )
    def test_a_scheme_that_is_not_http_is_refused(self, url: str, names: None) -> None:
        with pytest.raises(DisallowedHostError):
            check_page_url(url)

    @pytest.mark.parametrize("url", ["https://example.org:8443/", "http://example.org:8080/", "http://example.org:22/"])
    def test_a_port_that_is_not_the_standard_one_is_refused(self, url: str, names: None) -> None:
        with pytest.raises(DisallowedHostError, match="standard port"):
            check_page_url(url)

    def test_a_port_of_the_other_scheme_is_refused(self, names: None) -> None:
        with pytest.raises(DisallowedHostError, match="standard port"):
            check_page_url("http://example.org:443/")

    @pytest.mark.parametrize("url", ["https://user:password@example.org/", "https://user@example.org/"])
    def test_a_name_and_password_in_the_address_are_refused(self, url: str, names: None) -> None:
        with pytest.raises(DisallowedHostError, match="name and password"):
            check_page_url(url)

    def test_an_address_that_hides_its_host_behind_a_backslash_is_not_read_as_the_site_before_it(
        self, names: None
    ) -> None:
        # urllib3 ends the host at a backslash where urlsplit does not, so the two read this as different sites
        with pytest.raises(DisallowedHostError):
            check_page_url("https://intranet.example.org\\@example.org/")

    @pytest.mark.parametrize("url", ["https:///no-host", "https://", "http://:80/"])
    def test_an_address_with_no_host_is_refused(self, url: str, names: None) -> None:
        with pytest.raises(DisallowedHostError):
            check_page_url(url)

    def test_a_name_that_cannot_be_found_is_said_not_to_be_found(self, names: None) -> None:
        with pytest.raises(WebRequestError, match="Could not find missing.example.org"):
            check_page_url("https://missing.example.org/")


class LocalServer(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"a secret that lives on this machine")

    def log_message(self, *args: Any) -> None:
        return None


class TestTheConnectionItself:
    """What a name led to when it was checked is not what a connection is made to, if it can be made to change."""

    def test_a_connection_to_a_private_address_is_refused_before_anything_is_sent(self) -> None:
        server = http.server.HTTPServer(("127.0.0.1", 0), LocalServer)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with pytest.raises(DisallowedHostError, match="not on the public internet"):
                # Not through check_page_url, which would refuse it first: this is what is left if that was got round
                page_session().get(f"http://127.0.0.1:{server.server_port}/", timeout=5)
        finally:
            server.shutdown()
            server.server_close()

    def test_the_session_ignores_the_proxy_settings_of_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:3128")

        made = page_session()

        assert made.trust_env is False
        assert made.rebuild_proxies(requests.Request("GET", "https://example.org/").prepare(), {}) == {}

    def test_both_schemes_are_read_through_the_adapter_that_checks(self) -> None:
        made = page_session()

        assert isinstance(made.get_adapter("http://example.org/"), PublicOnlyAdapter)
        assert isinstance(made.get_adapter("https://example.org/"), PublicOnlyAdapter)

    def test_each_page_gets_a_session_of_its_own_so_no_cookie_is_kept_for_the_next(self) -> None:
        assert page_session() is not page_session()


class TestReadingAPage:
    def test_a_page_is_read_as_text_with_its_title_and_where_it_was_read_from(self, session: FakeSession) -> None:
        session.responses.append(html("<title>A page</title><h1>Hello</h1><p>Some words.</p>"))

        page = fetch_page("https://example.org/page")

        assert (page.title, page.url, page.kind) == ("A page", "https://example.org/page", "text/html")
        assert page.text == "# Hello\n\nSome words."
        assert session.closed

    def test_the_request_says_who_is_asking_and_does_not_follow_redirects_itself(self, session: FakeSession) -> None:
        session.responses.append(html("<p>x</p>"))

        fetch_page("https://example.org/")

        request = session.requests[0]
        assert "virtual-lab" in request["headers"]["User-Agent"]
        assert request["allow_redirects"] is False
        assert request["stream"] is True
        assert request["timeout"] > 0

    def test_a_redirect_to_another_public_site_is_followed_and_the_page_says_where_it_ended_up(
        self, session: FakeSession
    ) -> None:
        session.responses += [redirect("https://www.example.org/there"), html("<p>Arrived</p>")]

        page = fetch_page("https://example.org/here")

        assert session.urls == ["https://example.org/here", "https://www.example.org/there"]
        assert (page.url, page.text) == ("https://www.example.org/there", "Arrived")

    def test_a_relative_redirect_stays_on_the_site(self, session: FakeSession) -> None:
        session.responses += [redirect("/moved", 301), html("<p>Moved</p>")]

        fetch_page("https://example.org/old")

        assert session.urls[1] == "https://example.org/moved"

    @pytest.mark.parametrize(
        "location",
        [
            "http://127.0.0.1/admin",
            "http://169.254.169.254/latest/meta-data/",
            "https://intranet.example.org/",
            "https://both.example.org/",
            "file:///etc/passwd",
            "http://example.org:8080/",
        ],
    )
    def test_a_redirect_to_somewhere_private_is_refused_and_not_requested(
        self, location: str, session: FakeSession
    ) -> None:
        session.responses += [redirect(location), html("<p>secret</p>")]

        with pytest.raises(DisallowedHostError):
            fetch_page("https://example.org/")

        assert session.urls == ["https://example.org/"]
        assert session.closed

    def test_a_page_that_redirects_in_circles_is_given_up_on(self, session: FakeSession) -> None:
        session.responses += [redirect("https://example.org/again") for _ in range(WEB_MAX_REDIRECTS + 2)]

        with pytest.raises(WebRequestError, match="redirected more than"):
            fetch_page("https://example.org/")

        assert len(session.requests) == WEB_MAX_REDIRECTS + 1

    def test_a_redirect_with_nowhere_to_go_is_an_error_and_not_a_page(self, session: FakeSession) -> None:
        session.responses.append(FakeResponse(status_code=302, body=b"<p>Found</p>"))

        with pytest.raises(WebRequestError, match="no location"):
            fetch_page("https://example.org/")

    @pytest.mark.parametrize(
        ("status", "said"),
        [
            (404, "there is no such page"),
            (403, "refuses automated readers"),
            (401, "needs a login"),
            (429, "limiting how often"),
            (410, "removed"),
            (500, "returned 500"),
        ],
    )
    def test_a_page_that_is_not_given_says_why_as_far_as_that_is_known(
        self, status: int, said: str, session: FakeSession
    ) -> None:
        session.responses.append(html("<p>Nope</p>", status=status))

        with pytest.raises(WebRequestError, match=said) as failed:
            fetch_page("https://example.org/")

        assert failed.value.status_code == status

    def test_a_page_that_says_it_is_too_big_is_not_read(self, session: FakeSession) -> None:
        session.responses.append(html("<p>x</p>", headers={"Content-Length": "999999999"}))

        with pytest.raises(ResponseTooLargeError, match="declared"):
            fetch_page("https://example.org/")

    def test_a_page_that_turns_out_to_be_too_big_is_abandoned(
        self, session: FakeSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(webpages, "MAX_WEB_PAGE_BYTES", 1000)
        session.responses.append(html("<p>" + "x" * 5000 + "</p>"))

        with pytest.raises(ResponseTooLargeError):
            fetch_page("https://example.org/")

    def test_a_failure_of_the_connection_is_a_failure_to_read_the_page(self, session: FakeSession) -> None:
        session.responses.append(requests.ConnectionError("connection reset"))  # type: ignore[arg-type]

        with pytest.raises(WebRequestError, match="Could not read https://example.org/: ConnectionError"):
            fetch_page("https://example.org/")

    def test_an_address_that_is_refused_is_not_requested_at_all(self, session: FakeSession) -> None:
        with pytest.raises(DisallowedHostError):
            fetch_page("http://intranet.example.org/")

        assert session.requests == []

    def test_a_server_that_is_too_slow_to_send_is_given_up_on(
        self, session: FakeSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = iter([0.0, 0.0, 0.0, 0.0, 1000.0, 1000.0, 1000.0])
        monkeypatch.setattr(webpages.time, "monotonic", lambda: next(clock))
        monkeypatch.setattr("virtual_lab.web.time.monotonic", lambda: next(clock))
        session.responses.append(html("<p>" + "x" * 50_000 + "</p>"))

        with pytest.raises(WebRequestError, match="too slow"):
            fetch_page("https://example.org/")


class TestWhatKindOfThingItIs:
    def test_plain_text_is_given_as_it_is_with_its_line_endings_made_plain(self, session: FakeSession) -> None:
        session.responses.append(
            FakeResponse(body=b"one\r\ntwo\r\n\r\n\r\n\r\nthree\x00  \n", headers={"Content-Type": "text/plain"})
        )

        page = fetch_page("https://example.org/notes.txt")

        assert (page.kind, page.title, page.text) == ("text/plain", "", "one\ntwo\n\nthree")

    @pytest.mark.parametrize("kind", ["application/json", "text/csv", "application/xml", "application/vnd.api+json"])
    def test_data_that_is_text_is_read_as_text(self, kind: str, session: FakeSession) -> None:
        session.responses.append(FakeResponse(body=b'{"a": 1}', headers={"Content-Type": kind}))

        assert fetch_page("https://example.org/x").text == '{"a": 1}'

    @pytest.mark.parametrize("kind", ["image/png", "application/zip", "video/mp4", "application/gzip"])
    def test_a_file_that_is_not_text_is_not_read_and_the_model_is_told_to_download_it_with_code(
        self, kind: str, session: FakeSession
    ) -> None:
        session.responses.append(FakeResponse(body=b"\x89PNG\r\n\x00\x00", headers={"Content-Type": kind}))

        with pytest.raises(WebRequestError, match=f"is {kind}, which is not text.*download it"):
            fetch_page("https://example.org/x")

    def test_a_pdf_is_read_by_its_text(self, session: FakeSession, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[bytes] = []

        def text_of(data: bytes, name: str = "") -> str:
            seen.append(data)
            return "Title\r\n\r\n\r\n\r\nAbstract"

        monkeypatch.setattr(virtual_lab.papers, "pdf_text", text_of)
        session.responses.append(FakeResponse(body=b"%PDF-1.7 binary", headers={"Content-Type": "application/pdf"}))

        page = fetch_page("https://example.org/paper.pdf")

        assert seen == [b"%PDF-1.7 binary"]
        assert (page.kind, page.text) == ("application/pdf", "Title\n\nAbstract")

    def test_a_pdf_that_cannot_be_read_says_so(self, session: FakeSession, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken(data: bytes, name: str = "") -> str:
            raise ValueError(f"{name} could not be read as a PDF: damaged")

        monkeypatch.setattr(virtual_lab.papers, "pdf_text", broken)
        session.responses.append(FakeResponse(body=b"%PDF-", headers={"Content-Type": "application/pdf"}))

        with pytest.raises(WebRequestError, match="could not be read as a PDF: damaged"):
            fetch_page("https://example.org/paper.pdf")

    def test_a_pdf_without_pypdf_says_how_to_have_it(
        self, session: FakeSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing(data: bytes, name: str = "") -> str:
            raise ImportError('Reading a PDF needs pypdf: pip install "virtual-lab[papers]"')

        monkeypatch.setattr(virtual_lab.papers, "pdf_text", missing)
        session.responses.append(FakeResponse(body=b"%PDF-", headers={"Content-Type": "application/pdf"}))

        with pytest.raises(WebRequestError, match=r"needs pypdf.*virtual-lab\[papers\]"):
            fetch_page("https://example.org/paper.pdf")

    @pytest.mark.parametrize(
        ("body", "kind"),
        [
            (b"  <!DOCTYPE html><html><body>x</body></html>", "text/html"),
            (b"<html><body>x</body></html>", "text/html"),
            (b"just some words", "text/plain"),
        ],
    )
    def test_what_a_server_does_not_say_is_found_from_what_it_sent(
        self, body: bytes, kind: str, session: FakeSession
    ) -> None:
        session.responses.append(FakeResponse(body=body, headers={"Content-Type": "application/octet-stream"}))

        assert fetch_page("https://example.org/x").kind == kind

    def test_a_pdf_that_a_server_does_not_say_is_one_is_known_by_how_it_begins(
        self, session: FakeSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(virtual_lab.papers, "pdf_text", lambda data, name="": "Read")
        session.responses.append(FakeResponse(body=b"%PDF-1.4\n...", headers={}))

        page = fetch_page("https://example.org/download?id=3")

        assert (page.kind, page.text) == ("application/pdf", "Read")

    def test_a_file_with_nothing_to_say_what_it_is_and_binary_in_it_is_not_read(self, session: FakeSession) -> None:
        session.responses.append(FakeResponse(body=b"\x00\x01\x02binary", headers={}))

        with pytest.raises(WebRequestError, match="not text"):
            fetch_page("https://example.org/x")

    def test_the_character_set_the_server_gives_is_used(self, session: FakeSession) -> None:
        session.responses.append(
            FakeResponse(
                body="<p>café</p>".encode("latin-1"), headers={"Content-Type": "text/html; charset=ISO-8859-1"}
            )
        )

        assert fetch_page("https://example.org/").text == "café"

    def test_the_character_set_the_page_gives_is_used_when_the_server_gives_none(self, session: FakeSession) -> None:
        body = '<meta charset="windows-1252"><p>naïve “quoted”</p>'.encode("windows-1252")
        session.responses.append(FakeResponse(body=body, headers={"Content-Type": "text/html"}))

        assert fetch_page("https://example.org/").text == "naïve “quoted”"

    def test_a_character_set_python_does_not_have_does_not_lose_the_page(self, session: FakeSession) -> None:
        session.responses.append(
            FakeResponse(body=b"<p>fine</p>", headers={"Content-Type": "text/html; charset=no-such-codec"})
        )

        assert fetch_page("https://example.org/").text == "fine"


class TestTextOfAnHtmlPage:
    def read(self, markup: str, base: str = "https://example.org/dir/page.html") -> tuple[str, str, dict[str, str]]:
        return read_html(markup, base)

    def test_what_is_not_the_text_of_a_page_is_left_out(self) -> None:
        _, text, _ = self.read(
            "<html><head><title>T</title><style>p{color:red}</style><script>var secret = 1;</script></head>"
            "<body><nav>Menu Home About</nav><p>Real text.</p><script>alert(1)</script>"
            "<noscript>Enable scripts</noscript><svg><text>drawn</text></svg>"
            "<aside>Related</aside><footer>Copyright</footer></body></html>"
        )

        assert text == "Real text."

    def test_the_title_is_not_part_of_the_text_and_is_tidied(self) -> None:
        title, text, _ = self.read("<title>\n  A   long\n title </title><p>Body</p>")

        assert (title, text) == ("A long title", "Body")

    def test_headings_lists_and_line_breaks_are_kept_as_lines(self) -> None:
        _, text, _ = self.read(
            "<h1>Top</h1><p>Intro<br>second line</p><h3>Sub</h3><ul><li>one</li><li>two <b>bold</b></li></ul>"
            "<p>After</p>"
        )

        assert text == "# Top\n\nIntro\nsecond line\n\n### Sub\n\n- one\n- two bold\n\nAfter"

    def test_a_table_is_kept_as_rows_with_its_cells_between_bars(self) -> None:
        _, text, _ = self.read(
            "<table><tr><th>Gene</th><th>Score</th></tr><tr><td>TP53</td><td>0.91</td></tr>"
            "<tr><td>BRCA1</td><td></td></tr></table>"
        )

        assert text == "Gene | Score\nTP53 | 0.91\nBRCA1"

    def test_preformatted_text_keeps_its_spacing_and_other_text_does_not(self) -> None:
        _, text, _ = self.read("<p>a    b\n\n c</p><pre>def f():\n    return 1\n</pre>")

        assert text == "a b c\n\ndef f():\n    return 1"

    def test_character_references_are_read(self) -> None:
        _, text, _ = self.read("<p>5 &lt; 6 &amp; 7 &gt; 3 &mdash; caf&eacute; &#946;</p>")

        assert text == "5 < 6 & 7 > 3 — café β"

    def test_a_menu_that_is_never_closed_does_not_take_the_page_with_it(self) -> None:
        _, text, _ = self.read("<nav>Menu<p>" + "The real content of the page. " * 30 + "</p>" + "<div>pad</div>" * 40)

        assert "The real content of the page." in text

    def test_furniture_inside_furniture_is_left_out_to_its_end(self) -> None:
        _, text, _ = self.read("<nav>A<nav>B</nav>C</nav><p>kept</p>")

        assert text == "kept"

    def test_text_that_is_all_there_is_in_a_page_that_sends_the_reader_on_says_where(self) -> None:
        _, text, _ = self.read('<head><meta http-equiv="refresh" content="0; URL=/kegg/tables/br08606.html"></head>')

        assert text == (
            "This page only sends the reader on to https://example.org/kegg/tables/br08606.html. "
            "Read that address instead."
        )

    def test_a_page_with_nothing_in_it_has_no_text(self) -> None:
        assert self.read("<html><body><script>render()</script></body></html>")[1] == ""

    def test_links_are_made_whole_without_their_fragments_and_without_what_is_not_a_page(self) -> None:
        _, _, links = self.read(
            '<p><a href="/abs">Absolute path</a> <a href="rel.html#part">Relative</a> '
            '<a href="https://other.org/x">Other  site</a> <a href="#top">Top</a> '
            '<a href="mailto:a@b.org">Mail</a> <a href="javascript:void(0)">Script</a> '
            '<a href="https://other.org/x">Again</a> <a>No target</a></p>'
        )

        assert links == {
            "https://example.org/abs": "Absolute path",
            "https://example.org/dir/rel.html": "Relative",
            "https://other.org/x": "Other site",
        }

    def test_the_links_of_menus_are_not_listed(self) -> None:
        _, _, links = self.read('<nav><a href="/menu">Menu</a></nav><p><a href="/body">Body</a></p>')

        assert list(links) == ["https://example.org/body"]

    def test_a_link_to_the_page_itself_and_a_very_long_one_are_not_listed(self) -> None:
        _, _, links = self.read(
            f'<a href="/dir/page.html">Self</a><a href="/{"x" * 300}">Long</a><a href="/fine">Fine</a>'
        )

        assert list(links) == ["https://example.org/fine"]

    def test_an_empty_label_is_replaced_by_one_found_later(self) -> None:
        _, _, links = self.read('<a href="/x"><img src="a.png"></a><a href="/x">Named</a>')

        assert links == {"https://example.org/x": "Named"}

    def test_a_page_of_broken_markup_is_still_read(self) -> None:
        _, text, _ = self.read("<p>one<p>two</b></i><div><span>three<td>four</table></div></p></p>")

        assert text == "one\n\ntwo\nthree | four"


class TestAPageInParts:
    TEXT = "\n".join(f"Paragraph {number}: " + "word " * 40 for number in range(400))

    def page(self, text: str | None = None) -> Page:
        return Page("https://example.org/long", "Long", "text/html", self.TEXT if text is None else text)

    def test_a_short_page_is_given_whole(self) -> None:
        said = Page("https://example.org/", "Short", "text/html", "Hello").report()

        assert said == (
            "Page: Short\nURL: https://example.org/\nType: text/html\nCharacters 0 to 5 of 5.\n----\nHello"
        )

    def test_a_long_page_says_where_the_next_part_begins(self) -> None:
        said = self.page().report()

        end = int(said.split("To read on, call again with start=")[1].split(".")[0])
        assert 0 < end <= WEB_PAGE_CHARS
        assert f"Characters 0 to {end:,} of {len(self.TEXT):,}." in said

    def test_the_parts_together_are_the_whole_page_with_none_of_it_lost_or_given_twice(self) -> None:
        page = self.page()
        start, parts = 0, []
        while True:
            said = page.report(start=start)
            parts.append(said.split("\n----\n", 1)[1])
            if "To read on" not in said:
                break
            start = int(said.split("start=")[1].split(".")[0])

        assert "".join(parts) == self.TEXT
        assert len(parts) > 2

    def test_a_part_ends_at_a_line_where_there_is_one_near(self) -> None:
        said = self.page().report()
        shown = said.split("\n----\n", 1)[1]

        assert self.TEXT.startswith(shown)
        assert self.TEXT[len(shown)] == "\n"

    def test_a_part_is_no_longer_than_asked(self) -> None:
        said = self.page().report(chars=1000)

        assert len(said.split("\n----\n", 1)[1]) <= 1000

    def test_a_page_with_no_line_breaks_is_cut_where_it_must_be(self) -> None:
        page = self.page("x" * 50_000)

        assert page.report(chars=1000).split("\n----\n", 1)[1] == "x" * 1000

    def test_a_place_past_the_end_is_refused_and_says_how_long_the_page_is(self) -> None:
        with pytest.raises(ValueError, match="has 5 characters, so there is nothing to read from 9"):
            self.page("Hello").report(start=9)

    def test_a_place_before_the_top_is_refused(self) -> None:
        with pytest.raises(ValueError, match="start is where to begin"):
            self.page("Hello").report(start=-1)

    def test_a_page_without_text_says_so(self) -> None:
        said = self.page("").report()

        assert "no text that can be read" in said
        assert "Characters" not in said

    def test_links_are_listed_after_the_text_when_asked_for(self) -> None:
        links = (("https://a.org/", "A site"), ("https://b.org/", ""))
        page = Page("https://example.org/", "T", "text/html", "Body", links)

        assert "Links on the page" not in page.report()
        assert page.report(links=True).endswith(
            "----\nBody\n----\nLinks on the page (2):\n- A site: https://a.org/\n- (no text): https://b.org/"
        )

    def test_a_page_with_no_links_lists_none(self) -> None:
        assert "Links on the page" not in Page("u", "T", "text/html", "Body").report(links=True)


class TestKeepingWhatWasRead:
    def test_reading_on_does_not_fetch_the_page_again(self, session: FakeSession) -> None:
        session.responses.append(html("<p>" + "word " * 10_000 + "</p>"))

        first = read_page("https://example.org/long")
        start = int(first.split("start=")[1].split(".")[0])
        second = read_page("https://example.org/long", start=start)

        assert len(session.requests) == 1
        assert f"Characters {start:,} to" in second

    def test_each_page_is_kept_under_the_address_it_was_asked_for_by(self, session: FakeSession) -> None:
        session.responses += [html("<p>one</p>"), html("<p>two</p>")]

        assert read_page("https://example.org/1").endswith("one")
        assert read_page("https://example.org/2").endswith("two")
        assert len(session.requests) == 2

    def test_a_page_that_failed_is_not_kept(self, session: FakeSession) -> None:
        session.responses += [html("", status=500), html("<p>fine</p>")]

        with pytest.raises(WebRequestError):
            read_page("https://example.org/")

        assert read_page("https://example.org/").endswith("fine")

    def test_a_page_is_forgotten_after_a_while_and_read_again(
        self, session: FakeSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = [1000.0]
        monkeypatch.setattr(webpages.time, "monotonic", lambda: now[0])
        session.responses += [html("<p>old</p>"), html("<p>new</p>")]

        assert read_page("https://example.org/").endswith("old")
        now[0] += 10_000
        assert read_page("https://example.org/").endswith("new")

    def test_the_oldest_is_dropped_to_keep_to_the_number_kept(self) -> None:
        cache = PageCache(entries=2, seconds=100)
        for name in "abc":
            cache.put(name, Page(name, "", "text/plain", name))

        assert [cache.get(name) is not None for name in "abc"] == [False, True, True]

    def test_one_read_lately_is_the_last_to_go(self) -> None:
        cache = PageCache(entries=2, seconds=100)
        cache.put("a", Page("a", "", "text/plain", "a"))
        cache.put("b", Page("b", "", "text/plain", "b"))
        cache.get("a")
        cache.put("c", Page("c", "", "text/plain", "c"))

        assert [cache.get(name) is not None for name in "abc"] == [True, False, True]

    def test_a_page_whose_address_is_refused_is_not_kept_either(self, session: FakeSession) -> None:
        with pytest.raises(DisallowedHostError):
            read_page("https://intranet.example.org/")

        assert PAGE_CACHE.get("https://intranet.example.org/") is None
