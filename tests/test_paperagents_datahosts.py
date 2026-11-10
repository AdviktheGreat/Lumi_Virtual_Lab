"""Tests of asking the places that keep data what they have, and of fetching a file from one. The internet is replaced
by a stand-in that answers for the addresses it is told of and says what it was asked, so these run offline. What
matters most is what is refused, which is any host that the source was not told it may go to, at the start of a request
and at every address it is sent on to; and that a file is only kept if it is what the place said it is."""

import hashlib
import io
import json
import threading
import urllib.parse
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import requests
import urllib3.response
from requests.structures import CaseInsensitiveDict

import virtual_lab.paperagents.datahosts as hosting
import virtual_lab.webpages as webpages
from virtual_lab.environment import StoppedError
from virtual_lab.paperagents.data import DataError, DataFile, Reference, Source, parse_reference
from virtual_lab.paperagents.datahosts import fetch_file, list_files

PUBLIC = "93.184.216.34"


def md5(body: bytes) -> str:
    return hashlib.md5(body).hexdigest()


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class Reply:
    """Stands in for a streaming response."""

    def __init__(
        self,
        url: str,
        status: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        content_length: bool = True,
        between: Callable[[], None] | None = None,
    ) -> None:
        self.url = url
        self.status_code = status
        self.body = body
        self.headers = CaseInsensitiveDict(headers or {})
        if content_length and "Content-Length" not in self.headers and 200 <= status < 300:
            self.headers["Content-Length"] = str(len(body))
        self.between = between
        self.closed = False

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        for start in range(0, len(self.body), chunk_size):
            if start and self.between is not None:
                self.between()
            yield self.body[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class Dribble(io.RawIOBase):
    """A connection that gives one byte for each read of it, as a host that is sending slowly does."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.at = 0
        self.reads = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        self.reads += 1
        if self.at >= len(self.body):
            return 0
        buffer[0] = self.body[self.at]
        self.at += 1

        return 1


class Dribbling(Reply):
    """Stands in for a response that is read from a connection that sends a byte at a time. Waiting for a whole chunk of
    it would take a read of the connection for each byte of the chunk."""

    def __init__(self, url: str, body: bytes, declared: int | None = None) -> None:
        length = str(len(body) if declared is None else declared)
        super().__init__(url, body=body, headers={"Content-Length": length})
        self.connection = Dribble(body)
        self.raw = urllib3.response.HTTPResponse(
            body=io.BufferedReader(self.connection),
            preload_content=False,
            decode_content=False,
            status=200,
            headers={"Content-Length": length},
        )

    def iter_content(self, chunk_size: int = 8192) -> Iterator[bytes]:
        raise AssertionError("a response read from its connection is not waited on for a whole chunk")


class Session:
    def __init__(self, web: "Web") -> None:
        self.web = web

    def request(self, method: str, url: str, **kwargs: Any) -> Reply:
        return self.web.answer(method, url, kwargs)

    def close(self) -> None:
        pass


class Web:
    """The addresses that answer, and what was asked of them."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Reply | Exception] = {}
        self.asked: list[tuple[str, str]] = []
        self.headers: list[dict[str, str]] = []

    def add(self, url: str, body: bytes = b"", status: int = 200, **options: Any) -> None:
        self.routes[("GET", url)] = Reply(url, status, body, **options)

    def json(self, url: str, value: Any, status: int = 200) -> None:
        self.add(url, json.dumps(value).encode("utf-8"), status)

    def redirect(self, url: str, to: str, status: int = 302) -> None:
        self.routes[("GET", url)] = Reply(url, status, headers={"Location": to})
        self.routes[("HEAD", url)] = Reply(url, status, headers={"Location": to})

    def fail(self, url: str, error: Exception) -> None:
        self.routes[("GET", url)] = error

    def answer(self, method: str, url: str, kwargs: dict[str, Any]) -> Reply:
        self.asked.append((method, url))
        self.headers.append(dict(kwargs.get("headers") or {}))
        assert kwargs.get("allow_redirects") is False, "a redirect has to be followed by hand, so each is checked"
        assert kwargs.get("stream") is True
        found = self.routes.get((method, url))
        if found is None and method == "HEAD":
            full = self.routes.get(("GET", url))
            if isinstance(full, Reply):
                found = Reply(url, full.status_code, b"", {**full.headers})
        if found is None:
            raise AssertionError(f"Unexpected {method} to {url}")
        if isinstance(found, Exception):
            raise found
        found.closed = False

        return found

    def got(self, url: str) -> bool:
        return any(asked == url for _, asked in self.asked)

    @property
    def hosts(self) -> set[str]:
        return {urllib.parse.urlsplit(url).hostname or "" for _, url in self.asked}


PRIVATE_HOSTS = {"internal.example.org": "10.1.2.3", "metadata.example.org": "169.254.169.254"}


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Web:
    fake = Web()
    monkeypatch.setattr(hosting, "page_session", lambda: Session(fake))
    monkeypatch.setattr(webpages.RATE_LIMITER, "min_interval", 0.0)

    def lookup(host: str, port: Any, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(0, 0, 0, "", (PRIVATE_HOSTS.get(host, PUBLIC), port))]

    monkeypatch.setattr(webpages.socket, "getaddrinfo", lookup)

    return fake


def zenodo(web: Web, files: dict[str, bytes], record: int = 1234567, **metadata: Any) -> None:
    base = f"https://zenodo.org/api/records/{record}"
    web.json(
        base,
        {
            "metadata": {"title": "Cell atlas", "license": {"id": "cc-by-4.0"}, **metadata},
            "files": [
                {
                    "key": name,
                    "size": len(body),
                    "checksum": f"md5:{md5(body)}",
                    "links": {"self": f"{base}/files/{urllib.parse.quote(name)}/content"},
                }
                for name, body in files.items()
            ],
        },
    )
    for name, body in files.items():
        web.add(f"{base}/files/{urllib.parse.quote(name)}/content", body)


class TestWhatAPlaceHas:
    def test_zenodo_gives_names_sizes_md5_checksums_and_a_license(self, web: Web) -> None:
        zenodo(web, {"counts.csv": b"a,b\n1,2\n", "readme.txt": b"hello"})

        listed = list_files(parse_reference("https://zenodo.org/records/1234567"))

        assert listed.title == "Cell atlas" and listed.license == {"name": "cc-by-4.0", "url": None}
        assert [(file.name, file.bytes, file.checksum, file.why) for file in listed.files] == [
            ("counts.csv", 8, ("md5", md5(b"a,b\n1,2\n")), None),
            ("readme.txt", 5, ("md5", md5(b"hello")), None),
        ]
        assert not listed.truncated and listed.notes == []

    def test_a_record_with_no_open_files_says_so(self, web: Web) -> None:
        web.json(
            "https://zenodo.org/api/records/9", {"metadata": {"title": "Closed"}, "access": {"files": "restricted"}}
        )

        listed = list_files(Reference("zenodo", "9"))

        assert listed.files == [] and "no files that are open" in listed.notes[0]

    def test_figshare_gives_md5_and_a_license_and_says_a_link_is_not_a_file(self, web: Web) -> None:
        web.json(
            "https://api.figshare.com/v2/articles/55",
            {"title": "Plots", "license": {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}},
        )
        web.json(
            "https://api.figshare.com/v2/articles/55/files?limit=201",
            [
                {
                    "name": "a.png",
                    "size": 10,
                    "download_url": "https://ndownloader.figshare.com/files/1",
                    "computed_md5": "A" * 32,
                    "supplied_md5": "",
                    "is_link_only": False,
                },
                {
                    "name": "elsewhere",
                    "size": 0,
                    "download_url": "https://example.org/x",
                    "computed_md5": "",
                    "supplied_md5": "",
                    "is_link_only": True,
                },
            ],
        )

        listed = list_files(Reference("figshare", "55"))

        assert listed.license == {"name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"}
        assert listed.files[0].checksum == ("md5", "a" * 32) and listed.files[0].why is None
        assert listed.files[1].why is not None and "link to a file held elsewhere" in listed.files[1].why

    def test_dryad_files_are_listed_with_their_checksums_and_said_not_to_be_fetched(self, web: Web) -> None:
        doi = "doi%3A10.5061%2Fdryad.abc123"
        web.json(
            f"https://datadryad.org/api/v2/datasets/{doi}",
            {
                "title": "Fish growth",
                "license": "https://spdx.org/licenses/CC0-1.0.html",
                "_links": {"stash:version": {"href": "/api/v2/versions/77"}},
            },
        )
        web.json(
            "https://datadryad.org/api/v2/versions/77/files?page=1&per_page=100",
            {
                "count": 1,
                "total": 1,
                "_embedded": {
                    "stash:files": [{"path": "growth.csv", "size": 50, "digest": "b" * 64, "digestType": "sha-256"}]
                },
            },
        )

        listed = list_files(Reference("dryad", "10.5061/dryad.abc123"))

        assert listed.license == {"name": "CC0-1.0", "url": "https://spdx.org/licenses/CC0-1.0.html"}
        assert listed.files[0].checksum == ("sha256", "b" * 64)
        assert listed.files[0].why is not None and "signed in" in listed.files[0].why

    def test_github_gives_the_files_of_a_release_and_the_license_of_the_project(self, web: Web) -> None:
        base = "https://github.com/example/cellmapper/releases/download/v1.2"
        web.json(
            "https://api.github.com/repos/example/cellmapper/releases/tags/v1.2",
            {
                "tag_name": "v1.2",
                "assets": [
                    {
                        "name": "tables.zip",
                        "size": 9,
                        "digest": f"sha256:{'c' * 64}",
                        "browser_download_url": f"{base}/tables.zip",
                    },
                    {"name": "old.zip", "size": 9, "digest": None, "browser_download_url": f"{base}/old.zip"},
                    {
                        "name": "stray.zip",
                        "size": 9,
                        "browser_download_url": "https://github.com/other/repo/releases/download/v1/x",
                    },
                ],
            },
        )
        web.json(
            "https://api.github.com/repos/example/cellmapper", {"license": {"spdx_id": "MIT", "name": "MIT License"}}
        )

        listed = list_files(Reference("github", "example/cellmapper@v1.2"))

        assert listed.title == "example/cellmapper v1.2" and listed.license == {"name": "MIT", "url": None}
        assert listed.files[0].checksum == ("sha256", "c" * 64)
        assert listed.files[1].checksum is None and listed.files[1].why is None
        assert listed.files[2].why == "its address is not one of this release's"
        assert web.headers[0]["Accept"] == "application/vnd.github+json"

    def test_github_without_a_tag_asks_for_the_latest_release(self, web: Web) -> None:
        web.json("https://api.github.com/repos/example/cellmapper/releases/latest", {"tag_name": "v9", "assets": []})
        web.json("https://api.github.com/repos/example/cellmapper", {"license": None})

        listed = list_files(Reference("github", "example/cellmapper"))

        assert listed.title == "example/cellmapper v9" and listed.license is None
        assert "no files attached" in listed.notes[0]

    def test_a_license_that_cannot_be_had_does_not_keep_the_files_from_being_listed(self, web: Web) -> None:
        web.json("https://api.github.com/repos/example/cellmapper/releases/latest", {"tag_name": "v9", "assets": []})
        web.json("https://api.github.com/repos/example/cellmapper", {}, status=403)

        assert list_files(Reference("github", "example/cellmapper")).license is None

    def test_hugging_face_is_fetched_at_the_revision_that_was_listed(self, web: Web) -> None:
        revision = "d" * 40
        web.redirect(
            "https://huggingface.co/api/datasets/squad?blobs=true",
            "https://huggingface.co/api/datasets/rajpurkar/squad?blobs=true",
        )
        web.json(
            "https://huggingface.co/api/datasets/rajpurkar/squad?blobs=true",
            {
                "id": "rajpurkar/squad",
                "sha": revision,
                "cardData": {"license": ["cc-by-sa-4.0"]},
                "siblings": [
                    {"rfilename": "plain_text/train.parquet", "size": 20, "lfs": {"sha256": "e" * 64, "size": 20}},
                    {"rfilename": "README.md", "size": 5},
                    {"rfilename": "../escape", "size": 5},
                ],
            },
        )

        listed = list_files(Reference("huggingface", "squad"))

        assert listed.title == "rajpurkar/squad" and listed.license == {"name": "cc-by-sa-4.0", "url": None}
        assert (
            listed.files[0].url
            == f"https://huggingface.co/datasets/rajpurkar/squad/resolve/{revision}/plain_text/train.parquet"
        )
        assert listed.files[0].checksum == ("sha256", "e" * 64) and listed.files[1].checksum is None
        assert listed.files[2].why == "its name is not one that can be kept safely"

    def test_a_gated_hugging_face_dataset_is_listed_and_not_fetched(self, web: Web) -> None:
        web.json(
            "https://huggingface.co/api/datasets/org/name?blobs=true",
            {"id": "org/name", "gated": "manual", "siblings": [{"rfilename": "a.csv", "size": 5}]},
        )

        listed = list_files(Reference("huggingface", "org/name"))

        assert listed.files[0].why is not None and "gated" in listed.files[0].why

    def test_geo_gives_the_supplementary_files_and_the_series_matrix_with_the_size_each_is(self, web: Web) -> None:
        suppl = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE12nnn/GSE12345/suppl/"
        matrix = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE12nnn/GSE12345/matrix/"
        index = (
            '<html><a href="?C=N;O=D">Name</a><a href="/geo/series/GSE12nnn/GSE12345/">Parent Directory</a>'
            '<a href="filelist.txt">filelist.txt</a><a href="GSE12345_RAW.tar">GSE12345_RAW.tar</a>'
            '<a href="sub/">sub/</a><a href="a%20b.csv.gz">a b.csv.gz</a></html>'
        )
        web.add(suppl, index.encode("utf-8"))
        web.add(f"{suppl}GSE12345_RAW.tar", b"x" * 300)
        web.add(f"{suppl}a%20b.csv.gz", b"y" * 40)
        web.add(matrix, b'<a href="GSE12345_series_matrix.txt.gz">m</a>')
        web.add(f"{matrix}GSE12345_series_matrix.txt.gz", b"z" * 7)

        listed = list_files(Reference("geo", "GSE12345"))

        assert [(file.name, file.bytes, file.checksum, file.why) for file in listed.files] == [
            ("suppl/GSE12345_RAW.tar", 300, None, None),
            ("suppl/a b.csv.gz", 40, None, None),
            ("matrix/GSE12345_series_matrix.txt.gz", 7, None, None),
        ]
        assert ("HEAD", f"{suppl}GSE12345_RAW.tar") in web.asked

    def test_a_sample_is_looked_for_where_samples_are_kept(self, web: Web) -> None:
        for folder in ("suppl", "matrix"):
            web.add(f"https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM100nnn/GSM100123/{folder}/", b"", 404)

        with pytest.raises(DataError) as caught:
            list_files(Reference("geo", "GSM100123"))

        assert caught.value.kind == "missing"

    def test_a_file_whose_size_geo_does_not_say_is_not_fetched(self, web: Web) -> None:
        suppl = "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE12nnn/GSE12345/suppl/"
        web.add(suppl, b'<a href="a.txt">a</a>')
        web.add(f"{suppl}a.txt", b"hello", headers={"Content-Length": ""}, content_length=False)
        web.add("https://ftp.ncbi.nlm.nih.gov/geo/series/GSE12nnn/GSE12345/matrix/", b"", 404)

        listed = list_files(Reference("geo", "GSE12345"))

        assert listed.files[0].bytes is None and "size is not given" in (listed.files[0].why or "")

    def test_ena_gives_the_read_files_of_each_run_with_their_sizes_and_md5(self, web: Web) -> None:
        web.json(
            "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=PRJEB1&result=read_run"
            "&fields=run_accession,fastq_bytes,fastq_md5,fastq_ftp&format=json&limit=200",
            [
                {
                    "run_accession": "ERR1",
                    "fastq_bytes": "10;20",
                    "fastq_md5": f"{'1' * 32};{'2' * 32}",
                    "fastq_ftp": "ftp.sra.ebi.ac.uk/vol1/fastq/ERR001/ERR1/ERR1_1.fastq.gz;"
                    "ftp.sra.ebi.ac.uk/vol1/fastq/ERR001/ERR1/ERR1_2.fastq.gz",
                },
                {"run_accession": "ERR2", "fastq_bytes": "", "fastq_md5": "", "fastq_ftp": ""},
                {"run_accession": "ERR3", "fastq_bytes": "5", "fastq_md5": "", "fastq_ftp": "a;b"},
            ],
        )

        listed = list_files(Reference("ena", "PRJEB1"))

        assert [(file.name, file.bytes, file.checksum) for file in listed.files] == [
            ("ERR1_1.fastq.gz", 10, ("md5", "1" * 32)),
            ("ERR1_2.fastq.gz", 20, ("md5", "2" * 32)),
        ]
        assert listed.files[0].url == "https://ftp.sra.ebi.ac.uk/vol1/fastq/ERR001/ERR1/ERR1_1.fastq.gz"

    def test_ena_with_nothing_to_fetch_says_so(self, web: Web) -> None:
        web.json(
            "https://www.ebi.ac.uk/ena/portal/api/filereport?accession=PRJNA1&result=read_run"
            "&fields=run_accession,fastq_bytes,fastq_md5,fastq_ftp&format=json&limit=200",
            [],
        )

        assert "no read files" in list_files(Reference("ena", "PRJNA1")).notes[0]

    def test_more_files_than_are_listed_are_said_to_be_there(self, web: Web) -> None:
        files = {f"f{number:03d}.txt": b"x" for number in range(205)}
        zenodo(web, files)

        listed = list_files(Reference("zenodo", "1234567"))

        assert len(listed.files) == 200 and listed.total_files == 205 and listed.truncated
        assert "more files than the 200" in listed.notes[-1]

    def test_a_file_with_a_name_that_could_go_elsewhere_is_listed_and_not_fetched(self, web: Web) -> None:
        zenodo(web, {"../../etc/passwd": b"x", ".hidden": b"x", "ok.txt": b"x"})

        listed = list_files(Reference("zenodo", "1234567"))

        assert [file.why for file in listed.files] == ["its name is not one that can be kept safely"] * 2 + [None]

    def test_a_file_with_no_size_is_listed_and_not_fetched_since_the_limit_could_not_be_kept(self, web: Web) -> None:
        zenodo(web, {"ok.txt": b"x"})
        record = json.loads(web.routes[("GET", "https://zenodo.org/api/records/1234567")].body)  # type: ignore[union-attr]
        del record["files"][0]["size"]
        web.json("https://zenodo.org/api/records/1234567", record)

        assert "size is not given" in (list_files(Reference("zenodo", "1234567")).files[0].why or "")

    @pytest.mark.parametrize(
        ("status", "kind"),
        [(404, "missing"), (410, "missing"), (403, "unavailable"), (429, "unavailable"), (500, "unreachable")],
    )
    def test_what_the_host_says_is_told_by_what_it_means(self, web: Web, status: int, kind: str) -> None:
        web.add("https://zenodo.org/api/records/5", b"", status)

        with pytest.raises(DataError) as caught:
            list_files(Reference("zenodo", "5"))

        assert caught.value.kind == kind

    def test_an_answer_that_is_not_a_listing_is_said_not_to_be(self, web: Web) -> None:
        web.add("https://zenodo.org/api/records/5", b"<html>maintenance</html>")

        with pytest.raises(DataError, match="did not answer with a listing") as caught:
            list_files(Reference("zenodo", "5"))

        assert caught.value.kind == "unreachable"

    def test_a_host_that_cannot_be_reached_is_said_so_without_its_details(self, web: Web) -> None:
        web.fail("https://zenodo.org/api/records/5", requests.ConnectionError("secret detail"))

        with pytest.raises(DataError, match="Could not reach zenodo.org") as caught:
            list_files(Reference("zenodo", "5"))

        assert "secret" not in str(caught.value)

    def test_a_listing_that_is_too_large_is_refused(self, web: Web, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(hosting, "MAX_LISTING_BYTES", 50)
        web.add("https://zenodo.org/api/records/5", b"{" + b" " * 200 + b"}")

        with pytest.raises(DataError, match="Could not read") as caught:
            list_files(Reference("zenodo", "5"))

        assert caught.value.kind == "unreachable"

    def test_a_stop_is_honoured_before_a_host_is_asked(self, web: Web) -> None:
        with pytest.raises(StoppedError):
            list_files(Reference("zenodo", "5"), should_stop=lambda: True)

        assert web.asked == []


class TestWhereARequestMayGo:
    def test_only_the_hosts_a_source_names_are_asked(self, web: Web) -> None:
        zenodo(web, {"a.txt": b"x"})

        list_files(Reference("zenodo", "1234567"))

        assert web.hosts == {"zenodo.org"}

    def test_a_redirect_to_a_host_that_is_not_allowed_is_refused_before_it_is_asked(self, web: Web) -> None:
        web.redirect("https://zenodo.org/api/records/5", "https://evil.example.org/records/5")

        with pytest.raises(DataError, match="evil.example.org") as caught:
            list_files(Reference("zenodo", "5"))

        assert caught.value.kind == "refused" and web.hosts == {"zenodo.org"}

    def test_a_redirect_to_a_host_that_only_ends_like_an_allowed_one_is_refused(self, web: Web) -> None:
        web.redirect("https://zenodo.org/api/records/5", "https://zenodo.org.evil.example/x")

        with pytest.raises(DataError) as caught:
            list_files(Reference("zenodo", "5"))

        assert caught.value.kind == "refused" and web.hosts == {"zenodo.org"}

    def test_a_redirect_to_plain_http_is_refused(self, web: Web) -> None:
        web.redirect("https://zenodo.org/api/records/5", "http://zenodo.org/api/records/5")

        with pytest.raises(DataError, match="only https") as caught:
            list_files(Reference("zenodo", "5"))

        assert caught.value.kind == "refused"

    @pytest.mark.parametrize("target", ["https://internal.example.org/x", "https://metadata.example.org/x"])
    def test_a_host_that_leads_to_the_private_network_is_refused_even_if_the_source_names_it(
        self, web: Web, monkeypatch: pytest.MonkeyPatch, target: str
    ) -> None:
        host = urllib.parse.urlsplit(target).hostname or ""

        with hosting.Fetcher(Source("test", "Test", (host,))) as fetcher:
            with pytest.raises(DataError, match="not a site on the public internet") as caught:
                fetcher.read(target, "x")

        assert caught.value.kind == "refused" and web.asked == []

    @pytest.mark.parametrize(
        "url",
        [
            "http://zenodo.org/api/records/5",
            "https://zenodo.org:8443/api/records/5",
            "https://user:pass@zenodo.org/api/records/5",
            "https://example.org/api/records/5",
            "ftp://zenodo.org/x",
        ],
    )
    def test_an_address_that_is_not_plain_https_at_an_allowed_host_is_refused(self, web: Web, url: str) -> None:
        with hosting.Fetcher(hosting.SOURCES["zenodo"]) as fetcher:
            with pytest.raises(DataError) as caught:
                fetcher.read(url, "x")

        assert caught.value.kind == "refused" and web.asked == []

    def test_an_address_that_hides_another_host_after_a_backslash_only_ever_reaches_the_allowed_one(
        self, web: Web
    ) -> None:
        url = "https://zenodo.org\\@evil.example/x"
        web.add("https://zenodo.org/%5C@evil.example/x", b"{}")

        with hosting.Fetcher(hosting.SOURCES["zenodo"]) as fetcher:
            fetcher.read(url, "x")

        assert web.hosts == {"zenodo.org"}

    def test_a_source_is_not_sent_to_the_hosts_of_another(self, web: Web) -> None:
        with hosting.Fetcher(hosting.SOURCES["zenodo"]) as fetcher:
            with pytest.raises(DataError) as caught:
                fetcher.read("https://api.github.com/repos/a/b", "x")

        assert caught.value.kind == "refused"

    def test_a_host_a_download_is_sent_on_to_is_not_one_that_a_request_may_start_at(self, web: Web) -> None:
        with hosting.Fetcher(hosting.SOURCES["huggingface"]) as fetcher:
            with pytest.raises(DataError) as caught:
                fetcher.read("https://cdn-lfs.hf.co/x", "x")
            assert fetcher.allows("https://cdn-lfs.hf.co/x", via=True) and not fetcher.allows("https://cdn-lfs.hf.co/x")

        assert caught.value.kind == "refused"

    def test_too_many_redirects_are_given_up_on(self, web: Web) -> None:
        for number in range(10):
            web.redirect(f"https://zenodo.org/a{number}", f"https://zenodo.org/a{number + 1}")
        web.redirect("https://zenodo.org/api/records/5", "https://zenodo.org/a0")

        with pytest.raises(DataError, match="too many times") as caught:
            list_files(Reference("zenodo", "5"))

        assert caught.value.kind == "unreachable"

    def test_the_proxy_settings_of_the_environment_are_not_used(self) -> None:
        with hosting.Fetcher(hosting.SOURCES["zenodo"]) as fetcher:
            assert fetcher.session.trust_env is False


def listed_file(body: bytes, url: str, *, checksum: tuple[str, str] | None = None, size: int | None = None) -> DataFile:
    return DataFile("a.bin", len(body) if size is None else size, url, checksum)


ZENODO = Reference("zenodo", "1234567")
FILE_URL = "https://zenodo.org/api/records/1234567/files/a.bin/content"


class TestFetchingAFile:
    def test_a_file_is_written_counted_and_summed(self, web: Web, tmp_path: Path) -> None:
        body = bytes(range(256)) * 1000
        web.add(FILE_URL, body)
        counted: list[int] = []

        fetched = fetch_file(
            ZENODO, listed_file(body, FILE_URL, checksum=("md5", md5(body))), tmp_path / "x" / "a.bin", counted.append
        )

        assert (tmp_path / "x" / "a.bin").read_bytes() == body
        assert fetched.bytes == len(body) == sum(counted)
        assert fetched.sha256 == sha256(body) and fetched.checked == ("md5", md5(body))
        assert len(counted) > 1 and max(counted) <= hosting.CHUNK_BYTES

    def test_a_sha256_checksum_is_the_one_that_was_computed(self, web: Web, tmp_path: Path) -> None:
        web.add(FILE_URL, b"abc")

        fetched = fetch_file(
            ZENODO, listed_file(b"abc", FILE_URL, checksum=("sha256", sha256(b"abc"))), tmp_path / "a", lambda n: None
        )

        assert fetched.checked == ("sha256", sha256(b"abc"))

    def test_a_file_that_has_no_checksum_is_kept_if_it_is_the_size_that_was_said_and_says_it_was_not_checked(
        self, web: Web, tmp_path: Path
    ) -> None:
        web.add(FILE_URL, b"abc")

        fetched = fetch_file(ZENODO, listed_file(b"abc", FILE_URL), tmp_path / "a", lambda n: None)

        assert fetched.checked is None and fetched.sha256 == sha256(b"abc")

    def test_a_corrupt_file_is_caught_by_its_checksum_and_is_not_kept(self, web: Web, tmp_path: Path) -> None:
        good, bad = b"the data as it was", b"the data as it saw"
        web.add(FILE_URL, bad)

        with pytest.raises(DataError, match="not what Zenodo says it is.*discarded") as caught:
            fetch_file(
                ZENODO, listed_file(good, FILE_URL, checksum=("md5", md5(good))), tmp_path / "a.bin", lambda n: None
            )

        assert caught.value.kind == "checksum" and not (tmp_path / "a.bin").exists()
        assert md5(bad) in str(caught.value) and md5(good) in str(caught.value)

    def test_a_file_that_is_shorter_than_it_was_said_to_be_is_not_kept(self, web: Web, tmp_path: Path) -> None:
        web.add(FILE_URL, b"abc", content_length=False)

        with pytest.raises(DataError, match="Only 3 of the 10 bytes") as caught:
            fetch_file(ZENODO, listed_file(b"", FILE_URL, size=10), tmp_path / "a.bin", lambda n: None)

        assert caught.value.kind == "size" and not (tmp_path / "a.bin").exists()

    def test_a_file_that_goes_on_past_its_size_is_stopped_when_it_does(self, web: Web, tmp_path: Path) -> None:
        body = b"x" * (hosting.CHUNK_BYTES * 3)
        web.add(FILE_URL, body, content_length=False)
        counted: list[int] = []

        with pytest.raises(DataError, match="more than the 70,000 bytes") as caught:
            fetch_file(ZENODO, listed_file(b"", FILE_URL, size=70_000), tmp_path / "a.bin", counted.append)

        assert caught.value.kind == "size" and not (tmp_path / "a.bin").exists()
        assert sum(counted) <= 70_000

    def test_a_host_that_says_a_different_size_than_the_listing_is_not_believed(self, web: Web, tmp_path: Path) -> None:
        web.add(FILE_URL, b"abc", headers={"Content-Length": "999"})

        with pytest.raises(DataError, match="says a.bin is 999 bytes, and its listing said 3") as caught:
            fetch_file(ZENODO, listed_file(b"abc", FILE_URL), tmp_path / "a.bin", lambda n: None)

        assert caught.value.kind == "size" and not (tmp_path / "a.bin").exists()

    def test_a_body_that_was_compressed_for_the_way_is_not_kept_as_the_file(self, web: Web, tmp_path: Path) -> None:
        web.add(FILE_URL, b"abc", headers={"Content-Encoding": "gzip"})

        with pytest.raises(DataError, match="compressed"):
            fetch_file(ZENODO, listed_file(b"abc", FILE_URL), tmp_path / "a.bin", lambda n: None)

    def test_the_file_is_asked_for_as_it_is_stored(self, web: Web, tmp_path: Path) -> None:
        web.add(FILE_URL, b"abc")

        fetch_file(ZENODO, listed_file(b"abc", FILE_URL), tmp_path / "a", lambda n: None)

        assert web.headers[0]["Accept-Encoding"] == "identity"

    def test_a_host_that_answers_with_a_status_is_told_by_it(self, web: Web, tmp_path: Path) -> None:
        web.add(FILE_URL, b"", 404)

        with pytest.raises(DataError, match="not found") as caught:
            fetch_file(ZENODO, listed_file(b"abc", FILE_URL), tmp_path / "a", lambda n: None)

        assert caught.value.kind == "missing" and not (tmp_path / "a").exists()

    def test_a_connection_that_is_cut_off_leaves_nothing(self, web: Web, tmp_path: Path) -> None:
        def cut() -> None:
            raise requests.ConnectionError("reset by peer")

        web.add(FILE_URL, b"x" * (hosting.CHUNK_BYTES * 2), between=cut)

        with pytest.raises(DataError, match="was cut off") as caught:
            fetch_file(ZENODO, listed_file(b"", FILE_URL, size=hosting.CHUNK_BYTES * 2), tmp_path / "a", lambda n: None)

        assert caught.value.kind == "unreachable" and not (tmp_path / "a").exists()

    def test_a_stop_in_the_middle_of_a_file_leaves_nothing(self, web: Web, tmp_path: Path) -> None:
        stop = threading.Event()
        web.add(FILE_URL, b"x" * (hosting.CHUNK_BYTES * 3), between=stop.set)

        with pytest.raises(StoppedError):
            fetch_file(
                ZENODO,
                listed_file(b"", FILE_URL, size=hosting.CHUNK_BYTES * 3),
                tmp_path / "a",
                lambda n: None,
                stop.is_set,
            )

        assert not (tmp_path / "a").exists()

    def test_a_file_that_takes_too_long_is_given_up_on(
        self, web: Web, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hosting, "DOWNLOAD_GRACE_SECONDS", -1)
        monkeypatch.setattr(hosting, "SLOWEST_BYTES_PER_SECOND", 10**12)
        web.add(FILE_URL, b"abc")

        with pytest.raises(DataError, match="too slow") as caught:
            fetch_file(ZENODO, listed_file(b"abc", FILE_URL), tmp_path / "a", lambda n: None)

        assert caught.value.kind == "unreachable" and not (tmp_path / "a").exists()

    def test_a_host_that_sends_a_byte_at_a_time_is_looked_at_as_often_as_it_sends(
        self, web: Web, tmp_path: Path
    ) -> None:
        body = b"x" * 1000
        slow = Dribbling(FILE_URL, body)
        web.routes[("GET", FILE_URL)] = slow
        stop = threading.Event()
        sent: list[int] = []

        def counted(count: int) -> None:
            sent.append(count)
            if len(sent) == 3:
                stop.set()

        with pytest.raises(StoppedError):
            fetch_file(ZENODO, listed_file(body, FILE_URL), tmp_path / "a", counted, stop.is_set)

        assert sent == [1, 1, 1] and slow.connection.reads < 10 and not (tmp_path / "a").exists()

    def test_a_host_that_sends_a_byte_at_a_time_is_given_up_on_when_it_has_had_too_long(
        self, web: Web, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(hosting, "DOWNLOAD_GRACE_SECONDS", -1)
        monkeypatch.setattr(hosting, "SLOWEST_BYTES_PER_SECOND", 10**12)
        slow = Dribbling(FILE_URL, b"x" * 1000)
        web.routes[("GET", FILE_URL)] = slow

        with pytest.raises(DataError, match="too slow"):
            fetch_file(ZENODO, listed_file(b"x" * 1000, FILE_URL), tmp_path / "a", lambda n: None)

        assert slow.connection.reads < 10 and not (tmp_path / "a").exists()

    def test_a_file_that_comes_a_byte_at_a_time_is_kept_when_it_is_whole_and_matches(
        self, web: Web, tmp_path: Path
    ) -> None:
        body = b"abcdefgh" * 40
        web.routes[("GET", FILE_URL)] = Dribbling(FILE_URL, body)

        fetched = fetch_file(
            ZENODO, listed_file(body, FILE_URL, checksum=("md5", md5(body))), tmp_path / "a", lambda n: None
        )

        assert (tmp_path / "a").read_bytes() == body and fetched.sha256 == sha256(body)

    def test_a_connection_that_ends_before_the_file_does_leaves_nothing(self, web: Web, tmp_path: Path) -> None:
        web.routes[("GET", FILE_URL)] = Dribbling(FILE_URL, b"abc", declared=10)

        with pytest.raises(DataError, match="was cut off") as caught:
            fetch_file(ZENODO, listed_file(b"", FILE_URL, size=10), tmp_path / "a", lambda n: None)

        assert caught.value.kind == "unreachable" and not (tmp_path / "a").exists()

    def test_a_file_whose_address_is_at_a_host_that_is_not_allowed_is_not_asked_for(
        self, web: Web, tmp_path: Path
    ) -> None:
        with pytest.raises(DataError) as caught:
            fetch_file(ZENODO, listed_file(b"abc", "https://evil.example.org/a.bin"), tmp_path / "a", lambda n: None)

        assert caught.value.kind == "refused" and web.asked == [] and not (tmp_path / "a").exists()

    def test_a_file_that_was_said_not_to_be_fetchable_is_not_asked_for(self, web: Web, tmp_path: Path) -> None:
        file = listed_file(b"abc", FILE_URL)
        file.why = "needs an account"

        with pytest.raises(DataError, match="needs an account"):
            fetch_file(ZENODO, file, tmp_path / "a", lambda n: None)

        assert web.asked == []

    def test_a_download_is_sent_on_to_the_host_that_holds_it_and_to_no_other(self, web: Web, tmp_path: Path) -> None:
        figshare = Reference("figshare", "55")
        start = "https://ndownloader.figshare.com/files/1"
        stored = "https://abc123.r2.cloudflarestorage.com/figshare/1/a.bin?X-Signature=zzz"
        web.redirect(start, stored)
        web.add(stored, b"abc")

        fetched = fetch_file(figshare, listed_file(b"abc", start), tmp_path / "a", lambda n: None)

        assert fetched.bytes == 3 and web.hosts == {"ndownloader.figshare.com", "abc123.r2.cloudflarestorage.com"}

    def test_a_download_that_is_sent_on_somewhere_else_is_refused_and_nothing_is_written(
        self, web: Web, tmp_path: Path
    ) -> None:
        figshare = Reference("figshare", "55")
        start = "https://ndownloader.figshare.com/files/1"
        web.redirect(start, "https://attacker.example.net/a.bin")
        web.add("https://attacker.example.net/a.bin", b"abc")

        with pytest.raises(DataError, match="attacker.example.net") as caught:
            fetch_file(figshare, listed_file(b"abc", start), tmp_path / "a", lambda n: None)

        assert caught.value.kind == "refused" and not web.got("https://attacker.example.net/a.bin")
        assert not (tmp_path / "a").exists()

    def test_a_download_is_not_sent_on_to_a_host_that_only_one_other_source_may_use(
        self, web: Web, tmp_path: Path
    ) -> None:
        web.redirect(FILE_URL, "https://abc123.r2.cloudflarestorage.com/a.bin")
        web.add("https://abc123.r2.cloudflarestorage.com/a.bin", b"abc")

        with pytest.raises(DataError) as caught:
            fetch_file(ZENODO, listed_file(b"abc", FILE_URL), tmp_path / "a", lambda n: None)

        assert caught.value.kind == "refused"


def test_no_part_of_a_failed_fetch_is_left_in_a_folder_made_for_it(web: Web, tmp_path: Path) -> None:
    web.add(FILE_URL, b"abc")
    target = tmp_path / "deep" / "er" / "a.bin"

    with pytest.raises(DataError):
        fetch_file(ZENODO, listed_file(b"abd", FILE_URL, checksum=("md5", md5(b"abd"))), target, lambda n: None)

    assert not target.exists()
