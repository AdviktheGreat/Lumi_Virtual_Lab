"""Asking the places that keep data what files a dataset has, and fetching them.

This is the only part of PaperAgents that fetches data, and it is made so that it can go nowhere but where it was
told it may. A request is made to a source (data.SOURCES) and is refused unless its address is https, is at a host
that the source names, and leads to the public internet. A download is sent on by the host it was asked of, as the large
files of every source are, and every address it is sent on to is checked in the same way, against the hosts that the
source is sent on to. Nothing that a listing says, or a link in a paper, widens this.

What is received is written to a file a chunk at a time, and counted and summed as it goes, so that nothing is held in
memory and a file that is more than it was said to be is stopped when it passes that. It is kept only if it is exactly
as big as the place said, and, if the place gave a checksum, only if it matches. The SHA-256 is always worked out, and
is what is kept to tell later that a file is the same.
"""

import contextlib
import hashlib
import json
import re
import time
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from virtual_lab.constants import WEB_MAX_REDIRECTS, WEB_TIMEOUT_SECONDS, WEB_USER_AGENT
from virtual_lab.environment import StoppedError
from virtual_lab.paperagents.data import (
    MAX_LISTED_FILES,
    SOURCES,
    DataError,
    DataFile,
    Listing,
    Reference,
    Source,
    host_matches,
    safe_path,
)
from virtual_lab.web import RATE_LIMITER, DisallowedHostError, WebRequestError, normalize_url, read_bytes_capped
from virtual_lab.webpages import check_page_url, page_session

# The most that a listing may be, and how long it may take to make, which is long for GEO, whose files are each asked
# the size of
MAX_LISTING_BYTES = 5_000_000
LISTING_SECONDS = 90
CHUNK_BYTES = 1 << 16
# How long a file may take: this long, and then as long as it takes at the slowest rate that is worth waiting for
DOWNLOAD_GRACE_SECONDS = 600
SLOWEST_BYTES_PER_SECOND = 64 * 1024
# Where Figshare and Dryad count files from, and how many of a page
PAGE_FILES = 100

HEX = {"md5": re.compile(r"[0-9a-f]{32}"), "sha256": re.compile(r"[0-9a-f]{64}")}
GEO_FILE_FOLDERS = ("suppl", "matrix")
GEO_SKIPPED = frozenset({"filelist.txt"})
# How many of a series' files are listed, since the size of each is a request of its own
GEO_LISTED_FILES = 50
COMMIT = re.compile(r"[0-9a-f]{40}")


class Fetcher:
    """Makes the requests of one source, and refuses any that are not to the hosts it is allowed.

    :param source: Which source it is for.
    :param should_stop: Says whether the work it is for has been asked to stop, which is looked at before each request
        and for each chunk of a file.
    """

    def __init__(self, source: Source, should_stop: Callable[[], bool] | None = None) -> None:
        self.source = source
        self.should_stop = should_stop or (lambda: False)
        self.session = page_session()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *args: object) -> None:
        self.session.close()

    def why_not(self, url: str, via: bool = False) -> str | None:
        """Why an address is not one that this source is asked at, or, if it is the place a request is sent on to, at
        one that it is sent on to as well, or None if it is. Only what is said of the address is looked at."""
        try:
            parts = urllib.parse.urlsplit(url)
            host = parts.hostname or ""
        except ValueError as error:
            return str(error)
        hosts = (*self.source.hosts, *self.source.via) if via else self.source.hosts
        if parts.scheme != "https":
            return "only https is used"
        if parts.username is not None or parts.password is not None:
            return "an address may not carry a name and password"
        if not host_matches(host, hosts):
            return f"{host or 'that address'} is not a host that {self.source.name} is fetched from"

        return None

    def allows(self, url: str, via: bool = False) -> bool:
        return self.why_not(url, via) is None

    def check(self, url: str, via: bool = False) -> str:
        """An address as it is to be requested.

        :raises DataError: If it is not https at a host that is allowed, or does not lead to the public internet.
        """
        try:
            normalized = normalize_url(url)
        except (DisallowedHostError, ValueError) as error:
            raise DataError(f"Refusing {shown(url)}: {error}", "refused") from error
        if (reason := self.why_not(normalized, via)) is not None:
            raise DataError(f"Refusing {shown(url)}: {reason}", "refused")
        try:
            return check_page_url(normalized)
        except DisallowedHostError as error:
            raise DataError(str(error), "refused") from error
        except WebRequestError as error:
            raise DataError(str(error), "unreachable") from error

    @contextlib.contextmanager
    def request(
        self, url: str, method: str = "GET", accept: str = "application/json", identity: bool = False
    ) -> Iterator[requests.Response]:
        """A response, once the request has been sent on as far as it goes. Each address it is sent on to is checked
        before it is requested.

        :param identity: Whether the body is to be as it is stored, and not compressed for the way.
        :raises DataError: If an address is refused, or the host cannot be reached.
        """
        headers = {"User-Agent": WEB_USER_AGENT, "Accept": accept}
        if identity:
            headers["Accept-Encoding"] = "identity"
        current = self.check(url)
        for _ in range(WEB_MAX_REDIRECTS + 1):
            if self.should_stop():
                raise StoppedError("Stopped.")
            RATE_LIMITER.wait(urllib.parse.urlsplit(current).hostname or "")
            try:
                response = self.session.request(
                    method, current, headers=headers, timeout=WEB_TIMEOUT_SECONDS, stream=True, allow_redirects=False
                )
            except DisallowedHostError as error:
                raise DataError(str(error), "refused") from error
            except requests.RequestException as error:
                raise DataError(f"Could not reach {host_of(current)}: {type(error).__name__}", "unreachable") from error
            if 300 <= response.status_code < 400:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise DataError(f"{host_of(current)} sent the request on to nowhere", "unreachable")
                current = self.check(urllib.parse.urljoin(current, location), via=True)
                continue
            try:
                yield response
            finally:
                response.close()

            return
        raise DataError(f"{host_of(current)} sent the request on too many times", "unreachable")

    def check_status(self, response: requests.Response, what: str) -> None:
        """
        :raises DataError: If the host did not answer with what was asked for, saying which it did.
        """
        status = response.status_code
        if 200 <= status < 300:
            return
        host = host_of(str(response.url))
        if status in (404, 410):
            raise DataError(f"{what} was not found at {host}", "missing")
        if status in (401, 403):
            raise DataError(
                f"{host} would not give {what}: it is not public, needs an account, or has been asked for too much by "
                "this address. Try again later, or get it in a browser and add it on the Data page.",
                "unavailable",
            )
        if status == 429:
            raise DataError(f"{host} has been asked for too much. Try again in a minute.", "unavailable")
        raise DataError(f"{host} answered {status} for {what}", "unreachable")

    def read(self, url: str, what: str, accept: str = "application/json") -> bytes:
        """The body of an address, as it was sent.

        :raises DataError: If it cannot be had, or is more than a listing is.
        """
        try:
            with self.request(url, accept=accept) as response:
                self.check_status(response, what)

                return read_bytes_capped(response, MAX_LISTING_BYTES, time.monotonic() + LISTING_SECONDS)
        except WebRequestError as error:
            raise DataError(f"Could not read {what}: {error}", "unreachable") from error
        except requests.RequestException as error:
            raise DataError(f"Could not read {what}: {type(error).__name__}", "unreachable") from error

    def json(self, url: str, what: str, accept: str = "application/json") -> Any:
        body = self.read(url, what, accept)
        try:
            return json.loads(body)
        except ValueError as error:
            raise DataError(f"{host_of(url)} did not answer with a listing of {what}", "unreachable") from error

    def size_of(self, url: str, what: str) -> int | None:
        """How big a file is, as the host says to a request for only that, or None if it does not say."""
        try:
            with self.request(url, method="HEAD", accept="*/*", identity=True) as response:
                self.check_status(response, what)
                declared = response.headers.get("Content-Length", "").strip()

                return int(declared) if declared.isdecimal() else None
        except requests.RequestException as error:
            raise DataError(f"Could not ask how big {what} is: {type(error).__name__}", "unreachable") from error


def host_of(url: str) -> str:
    try:
        return urllib.parse.urlsplit(url).hostname or "the host"
    except ValueError:
        return "the host"


def shown(url: str) -> str:
    """An address as it is said in a message, which is not given in full: it may have a long query, and what is there is
    for the host."""
    return url if len(url) <= 100 else f"{url[:97]}..."


def whole(value: Any) -> int | None:
    """A size that a listing says, or none if it does not say one that is."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def text_of(value: Any, limit: int = 300) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def name_of(value: Any) -> str:
    """A name that a host gives a file, exactly as it gave it, since the file is asked for by it. One that is not fit to
    keep is told by data.safe_path."""
    return value if isinstance(value, str) else ""


def checksum_of(algorithm: str, value: Any) -> tuple[str, str] | None:
    """A checksum as it is kept, if the host gave one that is of the right length."""
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()

    return (algorithm, lowered) if HEX[algorithm].fullmatch(lowered) else None


def prefixed_checksum(value: Any) -> tuple[str, str] | None:
    """A checksum that is given as "md5:..." or "sha256:...", as Zenodo and GitHub give them."""
    if not isinstance(value, str) or ":" not in value:
        return None
    algorithm, _, digest = value.partition(":")
    algorithm = algorithm.strip().lower().replace("-", "")

    return checksum_of(algorithm, digest) if algorithm in HEX else None


def finish(fetcher: Fetcher, files: list[DataFile]) -> list[DataFile]:
    """Says why a file cannot be fetched, if it cannot be: the source does not give it without an account, its name is
    not one that can be kept, its address is not one that is fetched from, or its size is not given, which the limit on
    what is fetched cannot be kept to without."""
    for file in files:
        if file.why is not None:
            continue
        if not fetcher.source.downloads:
            file.why = f"{fetcher.source.name} only gives its files to someone who is signed in"
        elif safe_path(file.name) is None:
            file.why = "its name is not one that can be kept safely"
        elif not fetcher.allows(file.url):
            file.why = "its address is not at a host that data is fetched from here"
        elif file.bytes is None:
            file.why = "its size is not given, so the limit on what is fetched cannot be kept to"

    return files


def listing_of(
    fetcher: Fetcher,
    reference: Reference,
    title: str,
    license: dict[str, str | None] | None,
    files: list[DataFile],
    total: int | None = None,
    notes: list[str] | None = None,
    cap: int = MAX_LISTED_FILES,
) -> Listing:
    """A listing, with the files cut to as many as are listed and checked."""
    kept = files[:cap]
    made = notes or []
    seen = max(total or 0, len(files))
    if seen > len(kept):
        made.append(f"It has more files than the {cap} that are listed here.")

    return Listing(reference, title, license, finish(fetcher, kept), seen, made)


def list_zenodo(fetcher: Fetcher, reference: Reference) -> Listing:
    record = fetcher.json(f"https://zenodo.org/api/records/{reference.id}", reference.label)
    if not isinstance(record, dict):
        raise DataError("Zenodo did not answer with a record", "unreachable")
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    kept = metadata.get("license")
    entries = record.get("files") if isinstance(record.get("files"), list) else []
    files = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        links = entry.get("links") if isinstance(entry.get("links"), dict) else {}
        files.append(
            DataFile(
                name_of(entry.get("key")),
                whole(entry.get("size")),
                str(links.get("self") or ""),
                prefixed_checksum(entry.get("checksum")),
            )
        )
    notes = [] if files else ["It has no files that are open to everyone."]
    license = {"name": text_of(kept.get("id")) or None, "url": None} if isinstance(kept, dict) else None

    return listing_of(
        fetcher, reference, text_of(metadata.get("title")) or reference.label, license, files, notes=notes
    )


def list_figshare(fetcher: Fetcher, reference: Reference) -> Listing:
    article = fetcher.json(f"https://api.figshare.com/v2/articles/{reference.id}", reference.label)
    if not isinstance(article, dict):
        raise DataError("Figshare did not answer with an item", "unreachable")
    listed = fetcher.json(
        f"https://api.figshare.com/v2/articles/{reference.id}/files?limit={MAX_LISTED_FILES + 1}",
        f"the files of {reference.label}",
    )
    files = []
    for entry in listed if isinstance(listed, list) else []:
        if not isinstance(entry, dict):
            continue
        file = DataFile(
            name_of(entry.get("name")),
            whole(entry.get("size")),
            str(entry.get("download_url") or ""),
            checksum_of("md5", entry.get("computed_md5")) or checksum_of("md5", entry.get("supplied_md5")),
        )
        if entry.get("is_link_only"):
            file.why = "it is a link to a file held elsewhere, and not a file that Figshare holds"
        files.append(file)
    kept = article.get("license")
    license = (
        {"name": text_of(kept.get("name")) or None, "url": text_of(kept.get("url")) or None}
        if isinstance(kept, dict)
        else None
    )

    return listing_of(fetcher, reference, text_of(article.get("title")) or reference.label, license, files)


def list_dryad(fetcher: Fetcher, reference: Reference) -> Listing:
    quoted = urllib.parse.quote(f"doi:{reference.id}", safe="")
    dataset = fetcher.json(f"https://datadryad.org/api/v2/datasets/{quoted}", reference.label)
    links = dataset.get("_links") if isinstance(dataset, dict) else None
    version = ((links or {}).get("stash:version") or {}).get("href") if isinstance(links, dict) else None
    if not isinstance(version, str) or re.fullmatch(r"/api/v2/versions/\d+", version) is None:
        raise DataError("Dryad did not say which version of the dataset is current", "unreachable")
    files: list[DataFile] = []
    total = 0
    page = 1
    while len(files) <= MAX_LISTED_FILES:
        listed = fetcher.json(
            f"https://datadryad.org{version}/files?page={page}&per_page={PAGE_FILES}", f"the files of {reference.label}"
        )
        entries = (listed.get("_embedded") or {}).get("stash:files") if isinstance(listed, dict) else None
        total = whole(listed.get("total")) or total if isinstance(listed, dict) else total
        if not isinstance(entries, list) or not entries:
            break
        for entry in entries:
            if isinstance(entry, dict):
                files.append(
                    DataFile(
                        name_of(entry.get("path")),
                        whole(entry.get("size")),
                        "https://datadryad.org/",
                        checksum_of("sha256", entry.get("digest")) if entry.get("digestType") == "sha-256" else None,
                    )
                )
        if len(files) >= total:
            break
        page += 1
    kept = dataset.get("license") if isinstance(dataset, dict) else None
    license = (
        {"name": text_of(kept).rstrip("/").rsplit("/", 1)[-1].removesuffix(".html") or None, "url": text_of(kept)}
        if isinstance(kept, str) and kept
        else None
    )

    return listing_of(fetcher, reference, text_of(dataset.get("title")) or reference.label, license, files, total)


def list_github(fetcher: Fetcher, reference: Reference) -> Listing:
    name, _, tag = reference.id.partition("@")
    where = f"tags/{urllib.parse.quote(tag, safe='')}" if tag else "latest"
    release = fetcher.json(
        f"https://api.github.com/repos/{name}/releases/{where}",
        "the release" if tag else f"the latest release of {name}",
        "application/vnd.github+json",
    )
    if not isinstance(release, dict):
        raise DataError("GitHub did not answer with a release", "unreachable")
    prefix = f"https://github.com/{name}/releases/download/".lower()
    files = []
    for asset in release.get("assets") if isinstance(release.get("assets"), list) else []:
        if not isinstance(asset, dict):
            continue
        url = str(asset.get("browser_download_url") or "")
        file = DataFile(
            name_of(asset.get("name")), whole(asset.get("size")), url, prefixed_checksum(asset.get("digest"))
        )
        if not url.lower().startswith(prefix):
            file.why = "its address is not one of this release's"
        files.append(file)
    license = None
    with contextlib.suppress(DataError):
        repo = fetcher.json(f"https://api.github.com/repos/{name}", name, "application/vnd.github+json")
        kept = repo.get("license") if isinstance(repo, dict) else None
        if isinstance(kept, dict):
            license = {"name": text_of(kept.get("spdx_id")) or text_of(kept.get("name")) or None, "url": None}
    released = text_of(release.get("tag_name"))
    notes = [] if files else ["This release has no files attached to it, only the source code."]

    return listing_of(fetcher, reference, f"{name} {released}".strip(), license, files, notes=notes)


def list_huggingface(fetcher: Fetcher, reference: Reference) -> Listing:
    info = fetcher.json(f"https://huggingface.co/api/datasets/{reference.id}?blobs=true", reference.label)
    if not isinstance(info, dict):
        raise DataError("Hugging Face did not answer with a dataset", "unreachable")
    named = info.get("id")
    resolved = named if isinstance(named, str) and re.fullmatch(r"[\w.-]+/[\w.-]+", named) else reference.id
    revision = info.get("sha") if isinstance(info.get("sha"), str) and COMMIT.fullmatch(info["sha"]) else "main"
    files = []
    for entry in info.get("siblings") if isinstance(info.get("siblings"), list) else []:
        if not isinstance(entry, dict):
            continue
        name = name_of(entry.get("rfilename"))
        large = entry.get("lfs") if isinstance(entry.get("lfs"), dict) else {}
        files.append(
            DataFile(
                name,
                whole(entry.get("size")),
                f"https://huggingface.co/datasets/{resolved}/resolve/{revision}/{urllib.parse.quote(name, safe='/')}",
                checksum_of("sha256", large.get("sha256")),
            )
        )
    if info.get("gated") or info.get("private"):
        for file in files:
            file.why = "the dataset is gated or private, and is only given to someone who is signed in"
    card = info.get("cardData") if isinstance(info.get("cardData"), dict) else {}
    kept = card.get("license")
    kept = kept[0] if isinstance(kept, list) and kept else kept
    license = {"name": text_of(kept) or None, "url": None} if isinstance(kept, str) and kept else None
    notes = [f"Files are fetched at the revision {revision[:12]}."] if revision != "main" else []

    return listing_of(fetcher, reference, resolved, license, files, notes=notes)


def geo_directory(accession: str, folder: str) -> str:
    """Where NCBI keeps the files of a series or a sample: in a folder named from the accession with its last three
    digits taken off."""
    prefix, digits = accession[:3], accession[3:]
    kind = "series" if prefix == "GSE" else "samples"

    return f"https://ftp.ncbi.nlm.nih.gov/geo/{kind}/{prefix}{digits[:-3]}nnn/{accession}/{folder}/"


def geo_names(page: str, directory: str) -> list[str]:
    """The names of the files that a page of NCBI's lists, which are the links to a file of the folder itself."""
    names = []
    for href in re.findall(r'href="([^"]+)"', page):
        address = urllib.parse.urljoin(directory, href)
        name = urllib.parse.unquote(address[len(directory) :]) if address.startswith(directory) else ""
        if name and "/" not in name and not name.startswith("?") and name not in GEO_SKIPPED and name not in names:
            names.append(name)

    return names


def list_geo(fetcher: Fetcher, reference: Reference) -> Listing:
    files: list[DataFile] = []
    total = 0
    found = False
    for folder in GEO_FILE_FOLDERS:
        directory = geo_directory(reference.id, folder)
        try:
            page = fetcher.read(directory, f"the {folder} files of {reference.id}", "text/html").decode(
                "utf-8", errors="replace"
            )
        except DataError as error:
            if error.kind == "missing":
                continue
            raise
        found = True
        names = geo_names(page, directory)
        total += len(names)
        for name in names:
            if len(files) >= GEO_LISTED_FILES:
                break
            url = f"{directory}{urllib.parse.quote(name)}"
            try:
                size = fetcher.size_of(url, name)
            except DataError as error:
                if error.kind == "refused":
                    raise
                size = None
            files.append(DataFile(f"{folder}/{name}", size, url))
    if not found:
        raise DataError(f"NCBI has no files for {reference.id}", "missing")
    notes = [] if files else [f"NCBI has no supplementary files or series matrix for {reference.id}."]

    return listing_of(fetcher, reference, reference.label, None, files, total, notes, GEO_LISTED_FILES)


def list_ena(fetcher: Fetcher, reference: Reference) -> Listing:
    fields = "run_accession,fastq_bytes,fastq_md5,fastq_ftp"
    runs = fetcher.json(
        "https://www.ebi.ac.uk/ena/portal/api/filereport?"
        f"accession={reference.id}&result=read_run&fields={fields}&format=json&limit={MAX_LISTED_FILES}",
        reference.label,
    )
    if not isinstance(runs, list):
        raise DataError("ENA did not answer with a list of runs", "unreachable")
    files = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        paths = [path for path in str(run.get("fastq_ftp") or "").split(";") if path]
        sizes = str(run.get("fastq_bytes") or "").split(";")
        sums = str(run.get("fastq_md5") or "").split(";")
        if not (len(paths) == len(sizes) == len(sums)):
            continue
        for path, size, digest in zip(paths, sizes, sums, strict=True):
            files.append(
                DataFile(
                    path.rsplit("/", 1)[-1],
                    int(size) if size.isdecimal() else None,
                    f"https://{path}" if "://" not in path else path,
                    checksum_of("md5", digest),
                )
            )
    notes = [] if files else ["ENA has no read files for it. The data may be kept there as alignments, or not yet."]
    if len(runs) >= MAX_LISTED_FILES:
        notes.append(f"Only its first {MAX_LISTED_FILES} runs are listed.")

    return listing_of(fetcher, reference, reference.label, None, files, notes=notes)


ADAPTERS: dict[str, Callable[[Fetcher, Reference], Listing]] = {
    "zenodo": list_zenodo,
    "figshare": list_figshare,
    "dryad": list_dryad,
    "github": list_github,
    "huggingface": list_huggingface,
    "geo": list_geo,
    "ena": list_ena,
}


def list_files(reference: Reference, should_stop: Callable[[], bool] | None = None) -> Listing:
    """What a place has, as the place says: its files, how big each is, the checksum of each that is given, and what it
    is licensed as. Nothing is fetched of the files.

    :raises DataError: If the place cannot be asked, has no such thing, or does not answer as it should.
    """
    with Fetcher(SOURCES[reference.source], should_stop) as fetcher:
        return ADAPTERS[reference.source](fetcher, reference)


@dataclass(frozen=True)
class Fetched:
    """A file that was fetched, which is exactly as big as it was said to be, and matched the checksum the place gave if
    it gave one.

    :param bytes: How many bytes were written.
    :param sha256: The SHA-256 of what was written.
    :param checked: The checksum that the place gave and that it matched, as its algorithm and value, or None if the
        place gave none.
    """

    bytes: int
    sha256: str
    checked: tuple[str, str] | None


def fetch_file(
    reference: Reference,
    file: DataFile,
    target: Path,
    on_bytes: Callable[[int], None],
    should_stop: Callable[[], bool] | None = None,
) -> Fetched:
    """Fetches one file into a path, which is removed if what is received is not what was listed.

    :param on_bytes: Told how many bytes each chunk was, as it is written.
    :raises DataError: If the file cannot be fetched, is not as big as it was said to be, or does not match its
        checksum.
    :raises StoppedError: If the work was asked to stop.
    """
    if file.bytes is None or file.why is not None:
        raise DataError(f"{file.name} cannot be fetched: {file.why or 'its size is not given'}", "refused")
    summed = hashlib.sha256()
    other = hashlib.new(file.checksum[0]) if file.checksum is not None and file.checksum[0] != "sha256" else None
    written = 0
    deadline = time.monotonic() + DOWNLOAD_GRACE_SECONDS + file.bytes / SLOWEST_BYTES_PER_SECOND
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Fetcher(SOURCES[reference.source], should_stop) as fetcher:
            with fetcher.request(file.url, accept="*/*", identity=True) as response:
                if response.status_code != 200:
                    fetcher.check_status(response, file.name)
                    raise DataError(
                        f"{host_of(file.url)} answered {response.status_code} for {file.name}", "unreachable"
                    )
                if response.headers.get("Content-Encoding", "identity").strip().lower() not in ("", "identity"):
                    raise DataError(f"{host_of(file.url)} sent {file.name} compressed, which it is not kept as", "size")
                declared = response.headers.get("Content-Length", "").strip()
                if declared.isdecimal() and int(declared) != file.bytes:
                    raise DataError(
                        f"{host_of(file.url)} says {file.name} is {int(declared):,} bytes, and its listing said "
                        f"{file.bytes:,}",
                        "size",
                    )
                with open(target, "wb") as output:
                    for chunk in response.iter_content(CHUNK_BYTES):
                        if should_stop is not None and should_stop():
                            raise StoppedError("Stopped.")
                        if time.monotonic() > deadline:
                            raise DataError(f"{host_of(file.url)} was too slow to send {file.name}", "unreachable")
                        written += len(chunk)
                        if written > file.bytes:
                            raise DataError(
                                f"{file.name} is more than the {file.bytes:,} bytes it was said to be", "size"
                            )
                        output.write(chunk)
                        summed.update(chunk)
                        if other is not None:
                            other.update(chunk)
                        on_bytes(len(chunk))
        if written != file.bytes:
            raise DataError(f"Only {written:,} of the {file.bytes:,} bytes of {file.name} came", "size")
        if file.checksum is not None:
            algorithm, expected = file.checksum
            actual = (other or summed).hexdigest()
            if actual != expected:
                raise DataError(
                    f"{file.name} is not what {SOURCES[reference.source].name} says it is: its {algorithm.upper()} is "
                    f"{actual}, and the checksum given is {expected}. It was discarded.",
                    "checksum",
                )
    except requests.RequestException as error:
        target.unlink(missing_ok=True)
        raise DataError(f"{file.name} was cut off: {type(error).__name__}", "unreachable") from error
    except OSError as error:
        target.unlink(missing_ok=True)
        raise DataError(
            f"{file.name} could not be written: {error.strerror or type(error).__name__}", "failed"
        ) from error
    except BaseException:
        target.unlink(missing_ok=True)
        raise

    return Fetched(written, summed.hexdigest(), file.checksum)
