"""Tests that the server turns away whoever is not the person who started it."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from virtual_lab.server.security import (
    LOCAL_HOSTS,
    TOKEN_COOKIE,
    Guard,
    host_name,
    inline_script_sources,
    new_token,
    page_policy,
    policy_of_file,
)

TOKEN = "a-token-only-the-owner-has"
BASE = "http://localhost:8000"


async def answer(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "method": request.method})


def make_client(token: str | None = TOKEN, allowed_hosts: Any = LOCAL_HOSTS, base_url: str = BASE) -> TestClient:
    app = Starlette(
        routes=[
            Route("/", answer),
            Route("/page", answer, methods=["GET", "POST", "HEAD", "DELETE"]),
            Route("/api/health", answer),
            Route("/api/things", answer, methods=["GET", "POST", "DELETE", "OPTIONS"]),
        ]
    )
    app.add_middleware(Guard, token=token, allowed_hosts=allowed_hosts)

    return TestClient(app, base_url=base_url, follow_redirects=False)


def ask_guard(
    inner: Any,
    path: str = "/page",
    query: bytes = b"",
    token: str | None = None,
    headers: Any = ((b"host", b"localhost"),),
) -> list[dict[str, Any]]:
    """What a guard sends for a GET to an application that is called directly, as no client would call it."""
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": path, "query_string": query, "headers": list(headers)}
    asyncio.run(Guard(inner, token=token)(scope, receive, send))

    return sent


async def refuse_to_be_reached(scope: Any, receive: Any, send: Any) -> None:
    raise AssertionError("A request that should have been turned away reached the application")


def error_code(response: Any) -> str:
    return response.json()["error"]["code"]


class TestHost:
    @pytest.mark.parametrize(
        ("header", "name"),
        [
            ("localhost:8000", "localhost"),
            ("LOCALHOST", "localhost"),
            ("127.0.0.1:8765", "127.0.0.1"),
            ("[::1]:8000", "[::1]"),
            ("[::1]", "[::1]"),
            ("[FE80::1]:8000", "[fe80::1]"),
            ("localhost:", "localhost"),
            ("lab.example:65535", "lab.example"),
            ("", ""),
        ],
    )
    def test_the_name_in_a_host_header_is_what_comes_before_its_port(self, header: str, name: str) -> None:
        assert host_name(header) == name

    @pytest.mark.parametrize(
        "header",
        [
            "localhost:8000@evil.example",
            "evil.example@localhost",
            "localhost:8000 evil.example",
            " localhost",
            "localhost\t",
            "localhost:abc",
            "localhost:123456",
            "localhost:80:80",
            "localhost/path",
            "localhost?x",
            "localhost#x",
            "localhost\\evil.example",
            "[::1]x",
            "[::1",
            "[::1]:80:80",
            "[evil.example]",
            "[]",
        ],
    )
    def test_a_header_that_is_not_a_name_with_a_port_names_nothing(self, header: str) -> None:
        assert host_name(header) == ""

        sent = ask_guard(refuse_to_be_reached, "/api/things", headers=((b"host", header.encode()),))

        assert sent[0]["status"] == 403
        assert b"forbidden_host" in sent[1]["body"]

    @pytest.mark.parametrize("base_url", ["http://localhost:8000", "http://127.0.0.1:1234", "http://[::1]:8000"])
    def test_this_machine_may_reach_the_server_by_any_of_its_names(self, base_url: str) -> None:
        response = make_client(base_url=base_url).get("/", headers={"cookie": f"{TOKEN_COOKIE}={TOKEN}"})

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "base_url",
        ["http://evil.example", "http://localhost.evil.example", "http://127.0.0.1.evil.example:8000"],
    )
    def test_a_name_that_points_at_this_machine_by_dns_is_turned_away(self, base_url: str) -> None:
        client = make_client(base_url=base_url)

        for path in ("/", "/page", "/api/health", "/api/things"):
            response = client.get(path, headers={"authorization": f"Bearer {TOKEN}"})
            assert response.status_code == 403, path
            assert error_code(response) == "forbidden_host"

    def test_a_name_the_server_was_told_of_may_reach_it(self) -> None:
        client = make_client(allowed_hosts=(*LOCAL_HOSTS, "Lab.Example"), base_url="http://lab.example:9000")

        assert client.get("/api/things", headers={"authorization": f"Bearer {TOKEN}"}).status_code == 200

    def test_a_request_that_names_no_host_is_turned_away(self) -> None:
        sent = ask_guard(refuse_to_be_reached, "/api/things", headers=())

        assert sent[0]["status"] == 403

    def test_a_name_is_matched_whatever_the_case_of_either_side(self) -> None:
        client = make_client(allowed_hosts=(*LOCAL_HOSTS, "[FE80::1]"), base_url="http://[fe80::1]:9000")

        assert client.get("/api/things", headers={"authorization": f"Bearer {TOKEN}"}).status_code == 200


class TestOrigin:
    def test_a_page_of_another_address_may_not_change_anything_even_with_the_token(self) -> None:
        client = make_client()

        for method in ("POST", "DELETE"):
            response = client.request(
                method,
                "/api/things",
                headers={"authorization": f"Bearer {TOKEN}", "origin": "http://evil.example"},
            )
            assert response.status_code == 403
            assert error_code(response) == "forbidden_origin"

    @pytest.mark.parametrize("origin", ["null", "http://localhost:9999", "https://localhost:8000.evil.example"])
    def test_an_origin_that_is_not_the_servers_own_is_turned_away(self, origin: str) -> None:
        response = make_client().post("/api/things", headers={"authorization": f"Bearer {TOKEN}", "origin": origin})

        assert response.status_code == 403

    def test_a_request_the_browser_says_is_cross_site_is_turned_away(self) -> None:
        response = make_client().post(
            "/api/things", headers={"authorization": f"Bearer {TOKEN}", "sec-fetch-site": "cross-site"}
        )

        assert response.status_code == 403

    @pytest.mark.parametrize("headers", [{}, {"origin": BASE}, {"sec-fetch-site": "same-origin"}])
    def test_the_servers_own_pages_and_programs_that_send_no_origin_may_change_things(
        self, headers: dict[str, str]
    ) -> None:
        response = make_client().post("/api/things", headers={"authorization": f"Bearer {TOKEN}", **headers})

        assert response.status_code == 200

    @pytest.mark.parametrize(
        ("host", "origin"),
        [("LOCALHOST:8000", "http://localhost:8000"), ("localhost:8000", "http://LocalHost:8000")],
    )
    def test_the_case_of_the_names_does_not_make_a_page_another_address(self, host: str, origin: str) -> None:
        response = make_client().post(
            "/api/things", headers={"authorization": f"Bearer {TOKEN}", "host": host, "origin": origin}
        )

        assert response.status_code == 200

    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
    def test_looking_at_things_is_not_held_to_the_origin_since_a_page_cannot_read_the_answer(self, method: str) -> None:
        response = make_client().request(
            method, "/api/things", headers={"authorization": f"Bearer {TOKEN}", "origin": "http://evil.example"}
        )

        assert response.status_code == 200


class TestToken:
    def test_the_api_wants_the_token(self) -> None:
        client = make_client()

        for headers in ({}, {"authorization": "Bearer not-it"}, {"authorization": "Basic " + TOKEN}):
            response = client.get("/api/things", headers=headers)
            assert response.status_code == 401
            assert error_code(response) == "unauthorized"

        assert client.get("/api/things", headers={"authorization": f"Bearer {TOKEN}"}).status_code == 200
        assert client.get("/api/things", headers={"authorization": f"bearer  {TOKEN} "}).status_code == 200

    def test_the_cookie_the_link_sets_is_the_token_too(self) -> None:
        client = make_client()

        assert client.get("/api/things", headers={"cookie": f"{TOKEN_COOKIE}={TOKEN}"}).status_code == 200
        assert client.get("/api/things", headers={"cookie": f"{TOKEN_COOKIE}=wrong"}).status_code == 401
        assert client.get("/api/things", headers={"cookie": f"other={TOKEN}"}).status_code == 401

    def test_a_token_that_is_not_ascii_is_wrong_and_nothing_worse(self) -> None:
        response = make_client().get("/api/things", headers={"authorization": "Bearer ü".encode()})

        assert response.status_code == 401

    def test_the_token_is_not_taken_from_an_address_of_the_api(self) -> None:
        assert make_client().get(f"/api/things?token={TOKEN}").status_code == 401

    def test_the_health_check_and_the_pages_need_no_token(self) -> None:
        client = make_client()

        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/page").status_code == 200

    def test_with_no_token_the_api_wants_none(self) -> None:
        client = make_client(token=None)

        assert client.get("/api/things").status_code == 200
        assert client.get(f"/?token={TOKEN}").status_code == 200

    def test_the_link_with_the_token_sets_a_cookie_and_shows_the_page_without_it(self) -> None:
        client = make_client()

        response = client.get(f"/page?a=1&token={TOKEN}&b=two%20words")

        assert response.status_code == 303
        assert response.headers["location"] == "/page?a=1&b=two+words"
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{TOKEN_COOKIE}={TOKEN}")
        assert "HttpOnly" in cookie
        assert "SameSite=strict" in cookie
        # Only the API is asked for it, so no page or file the server shows is sent it
        assert "Path=/api" in cookie
        assert "Max-Age" not in cookie and "expires" not in cookie.lower()
        assert client.get("/api/things").status_code == 200

    @pytest.mark.parametrize("path", ["//evil.example/page", "///evil.example", "//"])
    def test_the_link_with_the_token_never_sends_the_browser_to_another_address(self, path: str) -> None:
        sent = ask_guard(refuse_to_be_reached, path, f"token={TOKEN}".encode(), token=TOKEN)

        location = dict(sent[0]["headers"])[b"location"].decode()
        assert sent[0]["status"] == 303
        assert location.startswith("/") and not location.startswith("//")

    def test_the_link_with_only_the_token_goes_to_the_first_page(self) -> None:
        response = make_client().get(f"/?token={TOKEN}")

        assert response.status_code == 303
        assert response.headers["location"] == "/"

    def test_a_wrong_token_in_a_link_sets_nothing(self) -> None:
        client = make_client()

        response = client.get("/page?token=wrong")

        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert client.get("/api/things").status_code == 401

    @pytest.mark.parametrize("method", ["POST", "HEAD", "DELETE"])
    def test_only_looking_at_a_page_is_sent_to_where_the_cookie_is_set(self, method: str) -> None:
        response = make_client().request(method, f"/page?token={TOKEN}")

        assert response.status_code == 200
        assert "set-cookie" not in response.headers

    def test_the_first_token_in_a_link_is_the_one_that_counts(self) -> None:
        client = make_client()

        assert client.get(f"/page?token=wrong&token={TOKEN}").status_code == 200
        assert "set-cookie" not in client.get(f"/page?token=wrong&token={TOKEN}").headers

        response = client.get(f"/page?token={TOKEN}&token=wrong")

        assert response.status_code == 303
        assert response.headers["location"] == "/page"

    def test_a_token_that_is_sent_as_a_header_is_the_one_that_counts_over_a_cookie(self) -> None:
        response = make_client().get(
            "/api/things", headers={"authorization": "Bearer wrong", "cookie": f"{TOKEN_COOKIE}={TOKEN}"}
        )

        assert response.status_code == 401

    def test_a_token_is_one_that_cannot_be_guessed(self) -> None:
        tokens = {new_token() for _ in range(20)}

        assert len(tokens) == 20
        assert all(len(token) >= 32 for token in tokens)


ALERT = "'sha256-bhHHL3z2vDgxUt0W3dWQOrprscmda2Y5pLsLg4GF+pI='"
TWO_LINES = "'sha256-fhj3NzEbLcOy8mndeDlrA1HxT7Zu+oefdoyyMYGIPHg='"


class TestPagePolicy:
    def test_a_script_written_into_a_page_is_named_by_its_hash(self) -> None:
        assert inline_script_sources("<html><script>alert(1)</script></html>") == [ALERT]

    def test_a_script_in_a_file_is_named_by_nothing(self) -> None:
        page = '<script src="/a.js"></script><script async SRC = "/b.js">ignored()</script><script src=/c.js></script>'

        assert inline_script_sources(page) == []

    def test_a_script_that_only_has_an_attribute_that_ends_in_src_is_in_the_page(self) -> None:
        assert inline_script_sources('<script data-src="x" type="module">alert(1)</script>') == [ALERT]

    def test_an_empty_script_needs_nothing(self) -> None:
        assert inline_script_sources("<script></script><script>alert(1)</script>") == [ALERT]

    def test_a_script_is_found_whatever_the_case_of_its_tags(self) -> None:
        assert inline_script_sources("<SCRIPT>alert(1)</SCRIPT >") == [ALERT]

    def test_a_script_that_is_more_than_once_in_a_page_is_named_once(self) -> None:
        assert inline_script_sources("<script>alert(1)</script><p></p><script>alert(1)</script>") == [ALERT]

    def test_scripts_are_named_in_order_of_their_hashes(self) -> None:
        assert inline_script_sources("<script>a\nb</script><script>alert(1)</script>") == [ALERT, TWO_LINES]

    def test_a_line_break_is_the_newline_a_browser_hashes_whatever_it_was_saved_as(self) -> None:
        assert inline_script_sources("<script>a\r\nb</script>") == [TWO_LINES]
        assert inline_script_sources("<script>a\rb</script>") == [TWO_LINES]

    def test_a_script_is_what_is_between_the_tags_exactly(self) -> None:
        assert inline_script_sources("<script>alert(1) </script>") != [ALERT]
        assert inline_script_sources("<script>\nalert(1)</script>") != [ALERT]

    def test_a_page_may_run_its_own_files_and_its_own_scripts_and_nothing_else(self) -> None:
        policy = page_policy("<script>alert(1)</script>")

        directives = dict(part.split(" ", 1) for part in policy.split("; "))
        assert directives["default-src"] == "'self'"
        assert directives["script-src"] == f"'self' {ALERT}"
        assert directives["style-src"] == "'self' 'unsafe-inline'"
        assert directives["object-src"] == "'none'"
        assert directives["base-uri"] == "'none'"
        assert directives["form-action"] == "'self'"
        assert directives["frame-ancestors"] == "'none'"
        assert "unsafe-eval" not in policy and "script-src 'self' 'unsafe-inline'" not in policy

    def test_a_page_with_no_script_of_its_own_runs_only_its_files(self) -> None:
        assert "script-src 'self';" in page_policy("<p>No script</p>")

    def test_the_policy_of_a_file_is_kept_until_the_file_changes(self, tmp_path: Path) -> None:
        page = tmp_path / "page.html"
        page.write_text("<script>alert(1)</script>")
        policy_of_file.cache_clear()

        first = policy_of_file(str(page), page.stat().st_mtime_ns, page.stat().st_size)
        again = policy_of_file(str(page), page.stat().st_mtime_ns, page.stat().st_size)
        assert again == first and ALERT in first
        assert policy_of_file.cache_info().hits == 1

        page.write_text("<script>a\nb</script>")
        changed = policy_of_file(str(page), page.stat().st_mtime_ns, page.stat().st_size)
        assert TWO_LINES in changed and ALERT not in changed

    def test_a_page_that_is_not_text_is_read_for_what_can_be(self, tmp_path: Path) -> None:
        page = tmp_path / "page.html"
        page.write_bytes(b"<script>alert(1)</script>\xff\xfe")

        assert ALERT in policy_of_file(str(page), 1, 2)


class TestHeaders:
    def test_every_answer_says_not_to_guess_its_type_or_show_it_in_a_frame(self) -> None:
        client = make_client()
        elsewhere = make_client(base_url="http://evil.example")

        # What is turned away, and the link that sets the cookie, are answered by the guard itself
        answers = (
            client.get("/"),
            client.get("/api/health"),
            client.get("/api/things"),
            client.get(f"/?token={TOKEN}"),
            elsewhere.get("/api/things"),
        )
        for response in answers:
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["referrer-policy"] == "no-referrer"

    def test_what_a_route_says_for_itself_is_left_as_it_said_however_it_wrote_the_name(self) -> None:
        async def inner(scope: Any, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": [(b"X-Frame-Options", b"SAMEORIGIN")]})
            await send({"type": "http.response.body", "body": b""})

        sent = ask_guard(inner)

        framing = [value for name, value in sent[0]["headers"] if name.lower() == b"x-frame-options"]
        assert framing == [b"SAMEORIGIN"]

    def test_what_the_api_says_is_not_kept_and_the_pages_may_be(self) -> None:
        client = make_client()

        assert client.get("/api/health").headers["cache-control"] == "no-store"
        assert "cache-control" not in client.get("/page").headers

    def test_a_turned_away_request_is_told_in_the_servers_shape(self) -> None:
        response = make_client().get("/api/things")

        assert response.json() == {
            "error": {
                "code": "unauthorized",
                "message": "Open the link the server printed when it started, which has the token in it",
            }
        }
