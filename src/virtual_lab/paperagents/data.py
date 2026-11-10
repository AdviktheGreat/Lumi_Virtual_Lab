"""Where the data of a paper can be had from, and what is known of it before any of it is fetched.

A paper says where its data is in a few ways: the accession of a dataset (GSE, SRP, PRJNA, ...), a link, a DOI of a
repository, or a statement of availability. What is found there is a candidate: a place, with where the paper or the
code says so. A candidate is only a place. Nothing is fetched from it until the person has seen what it holds and said
which files to take, and how much may be taken.

Data is only fetched from the places in SOURCES, at the hosts each names and no others. A place that the paper names
and that is not one of these is still listed, so that the person sees it, and is told that it is not fetched here, so
that they can get it themselves and give it to the lab as their own data.
"""

import re
import urllib.parse
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from typing import Any

from virtual_lab.paperagents.stock import URL, leads_to_data

MEGABYTE = 1024 * 1024
DEFAULT_MEGABYTES = 500
MIN_MEGABYTES = 1
MAX_MEGABYTES = 20_000
# The most that is kept of the data of one agent, in all, so that a series of downloads that are each within their limit
# cannot fill the disk
MAX_KEPT_MEGABYTES = 50_000
# The most files that are listed of one place, and that are taken at once
MAX_LISTED_FILES = 200
MAX_CHOSEN_FILES = 100
MAX_NAME_CHARS = 400


class DataError(Exception):
    """Something that kept data from being listed or fetched, said so that a person can read it.

    :param message: What went wrong.
    :param kind: Which sort of thing it was, for what is done about it: invalid (not something that can be asked for),
        unsupported (a place that is not fetched from here), refused (an address that is not one that is fetched from),
        missing (the place has no such thing), unavailable (the place will not give it, as it asks for an account or
        for the person to wait), unreachable (it could not be reached or did not answer as it should), changed (what is
        there is not what was shown), too_big, kept (it is already there), size and checksum (what was received is not
        what was listed).
    """

    def __init__(self, message: str, kind: str = "failed") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class Source:
    """A place that data is fetched from.

    :param key: What it is called in a record.
    :param name: What it is called to a person.
    :param hosts: The hosts that it is asked, and that its files are fetched from, as a host or as "*." and the end of
        one. The first address of every request is at one of these.
    :param via: The hosts that a request may be sent on to, which a download is by the host it was asked of, and which
        are not asked directly.
    :param downloads: Whether its files can be fetched without an account, which it is listed without if not.
    :param note: What a person should know of it.
    """

    key: str
    name: str
    hosts: tuple[str, ...]
    via: tuple[str, ...] = ()
    downloads: bool = True
    note: str = ""


SOURCES: dict[str, Source] = {
    source.key: source
    for source in (
        Source("zenodo", "Zenodo", ("zenodo.org",), note="Gives an MD5 checksum for each file."),
        Source(
            "figshare",
            "Figshare",
            ("api.figshare.com", "ndownloader.figshare.com", "figshare.com"),
            via=("*.r2.cloudflarestorage.com",),
            note="Gives an MD5 checksum for each file.",
        ),
        Source(
            "dryad",
            "Dryad",
            ("datadryad.org",),
            downloads=False,
            note="Its files can be listed, but are only given to someone who has an account, so they are fetched in a "
            "browser and put on the Data page.",
        ),
        Source(
            "github",
            "GitHub releases",
            ("api.github.com", "github.com"),
            via=("release-assets.githubusercontent.com", "objects.githubusercontent.com"),
            note="The files attached to a release, not the source code of it, which is fetched with the code. Gives a "
            "SHA-256 checksum for files that were attached since 2025.",
        ),
        Source(
            "huggingface",
            "Hugging Face datasets",
            ("huggingface.co",),
            via=("*.hf.co", "*.huggingface.co"),
            note="Fetched at the revision that was listed. Gives a SHA-256 checksum for large files.",
        ),
        Source(
            "geo",
            "GEO (NCBI)",
            ("ftp.ncbi.nlm.nih.gov",),
            note="The supplementary files and the series matrix. It gives no checksum, so a download is only checked "
            "against the size.",
        ),
        Source(
            "ena",
            "ENA (SRA)",
            ("www.ebi.ac.uk", "ftp.sra.ebi.ac.uk"),
            via=("*.ebi.ac.uk",),
            note="The read files of a study or a run, which are often gigabytes each. Gives an MD5 checksum for each "
            "file.",
        ),
    )
}

# What is not fetched from here, and why, for the accessions that say so
CONTROLLED = re.compile(r"\b(EGA[SDN]\d{6,})\b", re.IGNORECASE)
ARRAYEXPRESS = re.compile(r"\b(E-[A-Z]{4}-\d+)\b", re.IGNORECASE)
GEO_ACCESSION = re.compile(r"\b(GS[EM]\d{1,9})\b", re.IGNORECASE)
ENA_ACCESSION = re.compile(r"\b(PRJ(?:NA|EB|DB)\d{1,9}|[SED]R[PRXS]\d{4,9})\b", re.IGNORECASE)
ANY_ACCESSION = re.compile(
    r"\b(GS[EM]\d{1,9}|PRJ(?:NA|EB|DB)\d{1,9}|[SED]R[PRXS]\d{4,9}|E-[A-Z]{4}-\d+|EGA[SDN]\d{6,})\b", re.IGNORECASE
)
ZENODO_DOI = re.compile(r"10\.5281/zenodo\.(\d+)", re.IGNORECASE)
FIGSHARE_DOI = re.compile(r"10\.6084/m9\.figshare\.(\d+)", re.IGNORECASE)
DRYAD_DOI = re.compile(r"10\.5061/dryad\.([A-Za-z0-9]+)", re.IGNORECASE)
DOIS = re.compile(r"10\.(?:5281/zenodo\.\d+|6084/m9\.figshare\.\d+|5061/dryad\.[A-Za-z0-9]+)", re.IGNORECASE)
GITHUB_SEGMENT = re.compile(r"[A-Za-z0-9_.-]{1,100}")
GITHUB_TAG = re.compile(r"[A-Za-z0-9_.+@-][A-Za-z0-9_./+@-]{0,199}")
HUGGINGFACE_SEGMENT = re.compile(r"[A-Za-z0-9_.-]{1,96}")
HUGGINGFACE_PAGES = frozenset(
    {"tree", "blob", "resolve", "viewer", "discussions", "commits", "settings", "raw", "edit", "embed", "tabs"}
)
# Where the data of a project is not, on the host that it is: its pages and its people
GITHUB_PAGES = frozenset({"orgs", "sponsors", "topics", "collections", "marketplace", "settings", "search", "users"})

SAFE_SEGMENT = re.compile(r"\w[\w .,+=@~()-]*")


@dataclass(frozen=True)
class Reference:
    """One place that data is kept at, in a form that is the same however the paper wrote it down.

    :param source: Which of SOURCES it is at.
    :param id: What names it there: the record or article number, the DOI, owner/name and perhaps @tag, or the
        accession.
    """

    source: str
    id: str

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"

    @property
    def label(self) -> str:
        if self.source == "github":
            name, _, tag = self.id.partition("@")
            return f"Files of a release of {name}" + (f", {tag}" if tag else "")
        if self.source == "geo":
            return f"GEO {'sample' if self.id.startswith('GSM') else 'series'} {self.id}"

        return {
            "zenodo": f"Zenodo record {self.id}",
            "figshare": f"Figshare item {self.id}",
            "dryad": f"Dryad dataset doi:{self.id}",
            "huggingface": f"Hugging Face dataset {self.id}",
            "ena": f"ENA {self.id}",
        }[self.source]

    @property
    def url(self) -> str:
        """A page that a person can open to see it."""
        quoted = urllib.parse.quote
        if self.source == "zenodo":
            return f"https://zenodo.org/records/{self.id}"
        if self.source == "figshare":
            return f"https://doi.org/10.6084/m9.figshare.{self.id}"
        if self.source == "dryad":
            return f"https://doi.org/{quoted(self.id, safe='/')}"
        if self.source == "github":
            name, _, tag = self.id.partition("@")
            return f"https://github.com/{name}/releases" + (f"/tag/{quoted(tag, safe='/')}" if tag else "")
        if self.source == "huggingface":
            return f"https://huggingface.co/datasets/{self.id}"
        if self.source == "geo":
            return f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={self.id}"

        return f"https://www.ebi.ac.uk/ena/browser/view/{self.id}"

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "source": self.source, "reference": self.id, "label": self.label, "url": self.url}


@dataclass(frozen=True)
class Unsupported:
    """A place that the paper names, which data is not fetched from here, and why."""

    key: str
    label: str
    url: str | None
    reason: str


def approved() -> list[dict[str, Any]]:
    """The places that data is fetched from, with the hosts of each, for a person to see."""
    return [
        {
            "source": source.key,
            "name": source.name,
            "hosts": list(source.hosts),
            "via": list(source.via),
            "downloads": source.downloads,
            "note": source.note,
        }
        for source in SOURCES.values()
    ]


def approved_names() -> str:
    return ", ".join(source.name for source in SOURCES.values())


def host_matches(host: str, patterns: Iterable[str]) -> bool:
    """Whether a host is one of those named: the host itself, or, for a pattern of "*." and the end of a host, any that
    ends so."""
    host = host.lower().rstrip(".")

    return any(
        host == pattern.lower() or (pattern.startswith("*.") and host.endswith(pattern[1:].lower()))
        for pattern in patterns
    )


def not_fetched(host: str) -> str:
    return (
        f"{host} is not one of the places that data is fetched from here ({approved_names()}). Get the data there "
        "yourself, and add it on the Data page."
    )


def accession_reference(accession: str) -> Reference | Unsupported | None:
    """The place an accession is of, or None if it is not one."""
    text = accession.strip()
    if (found := GEO_ACCESSION.fullmatch(text)) is not None:
        return Reference("geo", found.group(1).upper())
    if (found := ENA_ACCESSION.fullmatch(text)) is not None:
        return Reference("ena", found.group(1).upper())
    if (found := ARRAYEXPRESS.fullmatch(text)) is not None:
        name = found.group(1).upper()
        return Unsupported(
            f"accession:{name}",
            f"ArrayExpress {name}",
            None,
            "ArrayExpress is not one of the places that data is fetched from here. Get it there yourself, and add it "
            "on the Data page.",
        )
    if (found := CONTROLLED.fullmatch(text)) is not None:
        name = found.group(1).upper()
        return Unsupported(
            f"accession:{name}",
            f"EGA {name}",
            None,
            "EGA holds data that is only given to people it approves, so it is not fetched here. Apply for it there, "
            "and add it on the Data page.",
        )

    return None


def doi_reference(text: str) -> Reference | None:
    """The place a DOI is of, if it is one of a repository that data is fetched from."""
    if (found := ZENODO_DOI.search(text)) is not None:
        return Reference("zenodo", found.group(1))
    if (found := FIGSHARE_DOI.search(text)) is not None:
        return Reference("figshare", found.group(1))
    if (found := DRYAD_DOI.search(text)) is not None:
        return Reference("dryad", f"10.5061/dryad.{found.group(1)}")

    return None


def github_reference(segments: list[str], from_paper: bool) -> Reference | Unsupported | None:
    """The place the files of a release are at, from the parts of a path at github.com."""
    if len(segments) < 2 or segments[0].lower() in GITHUB_PAGES:
        return None
    owner, name = segments[0], segments[1].removesuffix(".git")
    if not (GITHUB_SEGMENT.fullmatch(owner) and GITHUB_SEGMENT.fullmatch(name)):
        return None
    tag = ""
    if len(segments) >= 4 and segments[2] == "releases" and segments[3] in ("tag", "download") and len(segments) >= 5:
        tag = urllib.parse.unquote(segments[4])
    if tag and GITHUB_TAG.fullmatch(tag) is None:
        return None
    if from_paper and "releases" not in segments:
        return Unsupported(
            f"link:github.com/{owner}/{name}",
            f"{owner}/{name} on GitHub",
            f"https://github.com/{owner}/{name}",
            "This is a project's page. Its files are fetched with its code. Only the files attached to a release are "
            "fetched here, and the paper does not point to a release.",
        )

    return Reference("github", f"{owner}/{name}" + (f"@{tag}" if tag else ""))


def url_reference(url: str, from_paper: bool = False) -> Reference | Unsupported | None:
    """The place an address is of: None if it is not at a place that data is kept at, a Reference if it is one that is
    fetched from, and Unsupported if it is at a place that data is kept at and is not fetched from here.

    :param from_paper: Whether the address was found in a paper, where a project's page on GitHub is its code and not a
        release of it.
    """
    try:
        parts = urllib.parse.urlsplit(url if "://" in url else f"https://{url}")
        host = (parts.hostname or "").lower().removeprefix("www.")
    except ValueError:
        return None
    path = urllib.parse.unquote(parts.path)
    segments = [segment for segment in path.split("/") if segment]

    if host in ("doi.org", "dx.doi.org"):
        return doi_reference(path)
    if host == "zenodo.org":
        found = re.search(r"/(?:records?|uploads|api/records|badge/latestdoi)/(\d+)", path)
        if found is not None:
            return Reference("zenodo", found.group(1))
        return doi_reference(path) or Unsupported(
            f"link:{host}{path}", "A page of Zenodo", url, "This address does not name one Zenodo record."
        )
    if host in ("figshare.com", "api.figshare.com") or host.endswith(".figshare.com"):
        if "articles" in segments:
            digits = [segment for segment in segments[segments.index("articles") + 1 :] if segment.isdecimal()]
            if digits:
                return Reference("figshare", digits[0])
        return doi_reference(path) or Unsupported(
            f"link:{host}{path}", "A page of Figshare", url, "This address does not name one Figshare item."
        )
    if host == "datadryad.org":
        found = DRYAD_DOI.search(path)
        if found is not None:
            return Reference("dryad", f"10.5061/dryad.{found.group(1)}")
        return Unsupported(
            f"link:{host}{path}", "A page of Dryad", url, "This address does not name one Dryad dataset."
        )
    if host == "github.com":
        return github_reference(segments, from_paper)
    if host == "huggingface.co" and segments[:1] == ["datasets"] and len(segments) >= 2:
        names = segments[1:3] if len(segments) >= 3 and segments[2] not in HUGGINGFACE_PAGES else segments[1:2]
        if all(HUGGINGFACE_SEGMENT.fullmatch(name) for name in names):
            return Reference("huggingface", "/".join(names))
        return None
    if host in ("ncbi.nlm.nih.gov", "ftp.ncbi.nlm.nih.gov", "ebi.ac.uk") or host.endswith(".ebi.ac.uk"):
        found = ANY_ACCESSION.search(f"{path} {parts.query}")
        if found is not None and (reference := accession_reference(found.group(1))) is not None:
            return reference
        if leads_to_data(url):
            return Unsupported(
                f"link:{host}{path}",
                f"A page of {host}",
                url,
                "This address does not name a GEO series or an SRA or ENA study that can be fetched here.",
            )
        return None
    if leads_to_data(url):
        return Unsupported(f"link:{host}{path}", f"Data at {host}", url, not_fetched(host))

    return None


def references_in(text: str, from_paper: bool = True) -> list[Reference | Unsupported]:
    """The places that a text names, by an address, a DOI, or an accession, each once, in the order they are given."""
    found: dict[str, Reference | Unsupported] = {}
    spans = []
    for match in URL.finditer(text):
        address = match.group(0).rstrip(".,;:")
        spans.append(match.span())
        if (reference := url_reference(address, from_paper)) is not None:
            found.setdefault(reference.key, reference)
    outside = text
    for start, end in reversed(spans):
        outside = f"{outside[:start]} {outside[end:]}"
    for match in DOIS.finditer(outside):
        if (reference := doi_reference(match.group(0))) is not None:
            found.setdefault(reference.key, reference)
    for match in ANY_ACCESSION.finditer(outside):
        if (reference := accession_reference(match.group(0))) is not None:
            found.setdefault(reference.key, reference)

    return list(found.values())


def parse_reference(text: Any) -> Reference:
    """The place a person has pointed to, which is an address, a DOI, or an accession.

    :raises DataError: If it is not something that names one, or names a place that is not fetched from here.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 500:
        raise DataError("Say where the data is: an address, a DOI, or an accession such as GSE12345", "invalid")
    stripped = text.strip()
    reference: Reference | Unsupported | None
    if "://" in stripped:
        reference = url_reference(stripped)
    elif stripped.lower().startswith(("doi:", "10.")):
        reference = doi_reference(stripped)
    elif (reference := accession_reference(stripped)) is None and "." in stripped.split("/")[0]:
        reference = url_reference(stripped)
    if isinstance(reference, Unsupported):
        raise DataError(reference.reason, "unsupported")
    if reference is None:
        raise DataError(
            "That is not an address or an accession of one of the places that data is fetched from here "
            f"({approved_names()}).",
            "unsupported",
        )

    return reference


def place(fact: dict[str, Any]) -> dict[str, Any]:
    """Where in the paper a fact is."""
    return {"id": fact["id"], "quote": fact["quote"], "anchor": fact["anchor"]}


def find(card: dict[str, Any], resources: dict[str, Any], stock_data: dict[str, Any] | None) -> dict[str, Any]:
    """The places that the paper and its code point to for the data, and the data that the paper says it used.

    :param card: The draft method card of the reading, which has the datasets the paper names.
    :param resources: What reading found of the links and statements of where data is.
    :param stock_data: What was found of the data in the code, which is none if the code was not fetched.
    :return: "candidates", each place once, with the places in the paper that give it and whether the code does; and
        "datasets", each dataset the paper names, with the candidate it points to, if its accession does.
    """
    candidates: dict[str, dict[str, Any]] = {}

    def add(item: Reference | Unsupported, fact: dict[str, Any] | None = None, in_code: bool = False) -> None:
        if item.key not in candidates:
            shown = (
                {**item.to_dict(), "supported": True, "reason": None}
                if isinstance(item, Reference)
                else {
                    "key": item.key,
                    "source": None,
                    "reference": None,
                    "label": item.label,
                    "url": item.url,
                    "supported": False,
                    "reason": item.reason,
                }
            )
            candidates[item.key] = {**shown, "facts": [], "in_code": False}
        entry = candidates[item.key]
        if fact is not None and all(known["id"] != fact["id"] for known in entry["facts"]):
            entry["facts"].append(place(fact))
        entry["in_code"] = entry["in_code"] or in_code

    datasets = []
    for fact in card.get("datasets", []):
        pointed = None
        for item in references_in(fact.get("accession", ""), from_paper=False):
            add(item, fact)
            pointed = pointed or item.key
        datasets.append(
            {
                "key": fact["id"],
                "name": fact["name"],
                "accession": fact["accession"],
                "quote": fact["quote"],
                "anchor": fact["anchor"],
                "candidate": pointed,
            }
        )
    for fact in resources.get("links", []):
        item = url_reference(fact["url"], from_paper=True)
        # A link that is not to data is not a place for it, and a place that is not fetched from is only shown if the
        # paper says it is data or it is at one of the places data is kept
        if item is None or (
            isinstance(item, Unsupported) and fact.get("role") != "data" and not leads_to_data(fact["url"])
        ):
            continue
        add(item, fact)
    for fact in resources.get("availability", []):
        if fact.get("kind") == "data":
            for item in references_in(fact["quote"]):
                add(item, fact)
    if stock_data is not None:
        for address in stock_data.get("links", []):
            if (item := url_reference(address, from_paper=True)) is not None:
                add(item, in_code=True)
        for accession in stock_data.get("accessions", []):
            if (item := accession_reference(accession)) is not None:
                add(item, in_code=True)

    def order(entry: dict[str, Any]) -> tuple[bool, bool, int, str]:
        facts = entry["facts"]

        return (not entry["supported"], not facts, facts[0]["anchor"]["start"] if facts else 0, entry["key"])

    return {"candidates": sorted(candidates.values(), key=order), "datasets": datasets}


def safe_path(name: Any) -> str | None:
    """A name that a place gives a file, as it may be kept under, or None if it may not be. The place chose it, so it is
    not trusted: it may not go up a folder, start with a dot, be empty, be long, or have anything in it but letters,
    digits, and a few marks."""
    if not isinstance(name, str) or not name or len(name) > MAX_NAME_CHARS:
        return None
    segments = name.split("/")
    if len(segments) > 8:
        return None
    for segment in segments:
        if (
            len(segment) > 200
            or SAFE_SEGMENT.fullmatch(segment) is None
            or segment.endswith((" ", "."))
            or segment in (".", "..")
        ):
            return None

    return name


def folder_of(reference: Reference) -> str:
    """Where, under the data of an agent, the files of a place are kept, named from the place and not from its files."""
    slug = re.sub(r"[^A-Za-z0-9._@-]+", "_", reference.id).strip("._")

    return f"{reference.source}/{slug or 'data'}"


@dataclass
class DataFile:
    """A file that a place has.

    :param name: Where it is in the place, as the place says.
    :param bytes: How big it is, as the place says, or None if it does not.
    :param url: Where it is fetched from.
    :param checksum: The algorithm and the value that the place gives for it, if it gives one.
    :param why: Why it cannot be fetched, if it cannot be.
    """

    name: str
    bytes: int | None
    url: str
    checksum: tuple[str, str] | None = None
    why: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bytes": self.bytes,
            "checksum": {"algorithm": self.checksum[0], "value": self.checksum[1]} if self.checksum else None,
            "downloadable": self.why is None,
            "why": self.why,
        }


@dataclass
class Listing:
    """What a place has: what it is, what it is licensed as, and its files."""

    reference: Reference
    title: str
    license: dict[str, str | None] | None
    files: list[DataFile]
    total_files: int
    notes: list[str] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return self.total_files > len(self.files)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.reference.to_dict(),
            "title": self.title,
            "license": self.license,
            "files": [file.to_dict() for file in self.files],
            "total_files": self.total_files,
            "truncated": self.truncated,
            "notes": self.notes,
            "downloads": SOURCES[self.reference.source].downloads,
        }


def clash(names: Iterable[str], kept: Iterable[str]) -> str | None:
    """Why files cannot be kept under these names, beside each other and what is kept already, or None if they can. On
    a disk that does not tell capital letters apart two names that differ only in them are one file, and a file cannot
    have the name of a folder that another is in."""
    held: dict[str, str] = {}
    folders: dict[str, str] = {}

    def parents(folded: str) -> list[str]:
        parts = folded.split("/")

        return ["/".join(parts[:end]) for end in range(1, len(parts))]

    for name in kept:
        held[name.casefold()] = name
        folders.update({parent: name for parent in parents(name.casefold())})
    for name in names:
        folded = name.casefold()
        if folded in held:
            return f"{name} and {held[folded]} differ only in their capital letters, and are one file on some disks"
        if folded in folders:
            return f"{name} is the name of a folder that {folders[folded]} is in"
        for parent in parents(folded):
            if parent in held:
                return f"{name} is to be in a folder that has the name of the file {held[parent]}"
        held[folded] = name
        folders.update({parent: name for parent in parents(folded)})

    return None


def choose(
    listing: Listing, names: Collection[Any], expected_bytes: int, max_bytes: int, kept: Collection[str] = ()
) -> list[DataFile]:
    """The files of a listing that were asked for, if they are what the person was shown, and are within the limit.

    :param names: The names of the files, as the listing has them.
    :param expected_bytes: What the files came to when the person was shown them, which is what they agreed to.
    :param max_bytes: The most that may be fetched.
    :param kept: The names of the files of this place that are kept already.
    :raises DataError: If none is asked for, too many, one that the listing does not have, that cannot be fetched, or
        that is kept already, if two cannot be kept together or beside what is kept (see clash), if what they come to is
        not what was shown, or is more than may be fetched.
    """
    if not all(isinstance(name, str) for name in names):
        raise DataError("The names of the files are text", "invalid")
    wanted = list(dict.fromkeys(names))
    if not wanted:
        raise DataError("Say which files to fetch", "invalid")
    if len(wanted) > MAX_CHOSEN_FILES:
        raise DataError(f"At most {MAX_CHOSEN_FILES} files can be fetched at once", "invalid")
    by_name = {file.name: file for file in listing.files}
    chosen = []
    for name in wanted:
        file = by_name.get(name)
        if file is None:
            raise DataError(f"{listing.reference.label} has no file called {name!r}", "invalid")
        if file.why is not None:
            raise DataError(f"{name} cannot be fetched: {file.why}", "refused")
        if name in kept:
            raise DataError(f"{name} is kept already. Remove it first to fetch it again.", "kept")
        chosen.append(file)
    if (why := clash([file.name for file in chosen], kept)) is not None:
        raise DataError(f"These files cannot be kept together: {why}", "invalid")
    total = sum(file.bytes or 0 for file in chosen)
    if total != expected_bytes:
        raise DataError(
            f"These files are {total:,} bytes now, and not the {expected_bytes:,} that were shown. Look at them again "
            "before fetching.",
            "changed",
        )
    if total > max_bytes:
        raise DataError(
            f"These files are {total:,} bytes, which is more than the {max_bytes:,} that may be fetched. Choose fewer, "
            "or raise the limit.",
            "too_big",
        )

    return chosen
