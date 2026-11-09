"""Taking stock of a project's code: what is in it, found by looking at the files and never by running any of them.

Nothing here imports, executes, builds, or installs what it looks at. A file is read as text, up to a limit, and what is
looked for in it is words: the names of what a project depends on, the license's wording, the paths that a script
reads. The result is facts about the project, in a form that is kept and shown, and is the ground that the go or no-go
check stands on.

A project is read within limits (how many files, how much of each, how much in all) so that a large or odd one cannot
make this take long or use much memory, and what was not looked at is said.
"""

import json
import os
import re
import stat
import tomllib
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

SCHEMA = 1

# How much of a project is looked at: the most files that are walked, how deep, how much of a file is read, of a
# notebook (which holds its outputs), and how much is read in all
MAX_FILES = 20_000
MAX_DEPTH = 12
MAX_READ_BYTES = 400_000
MAX_NOTEBOOK_BYTES = 20_000_000
MAX_TOTAL_READ = 80_000_000
MAX_CODE_FILES_SCANNED = 400
MAX_SMALL_FILES_CHECKED = 2_000
MAX_TEXT_CHARS = 200
MAX_DOCUMENT_BYTES = 100_000
MAX_ENVIRONMENT_DEPTH = 3
MAX_LISTED = 25
MAX_SIGNALS = 10

# Folders that hold what others made or what a tool leaves behind, and are not the project's own
SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".ipynb_checkpoints",
        ".venv",
        "venv",
        "site-packages",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".eggs",
    }
)

LANGUAGES = {
    ".py": "Python",
    ".r": "R",
    ".jl": "Julia",
    ".sh": "Shell",
    ".bash": "Shell",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".cu": "CUDA",
    ".cuh": "CUDA",
    ".rs": "Rust",
    ".java": "Java",
    ".scala": "Scala",
    ".go": "Go",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".m": "MATLAB",
    ".nf": "Nextflow",
    ".smk": "Snakemake",
}
# What a notebook says its kernel is, as the name of a language above
NOTEBOOK_LANGUAGES = {"python": "Python", "r": "R", "julia": "Julia", "matlab": "MATLAB", "bash": "Shell"}
SCRIPT_SUFFIXES = (".py", ".r", ".jl", ".sh")
DOCUMENT_SUFFIXES = (".rmd", ".qmd")

# Folders and file names that say a file is there to show how the code is used
TUTORIAL_DIRECTORIES = frozenset({"tutorial", "example", "demo", "vignette", "walkthrough", "notebook", "quickstart"})
TUTORIAL_NAMES = ("example", "demo", "tutorial", "quickstart", "walkthrough")
TEST_DIRECTORIES = frozenset({"test", "tests", "testthat"})

# Files whose names say what a project is set up from, by what kind of environment
ENVIRONMENT_LOCKS = {
    "poetry.lock": "pip",
    "uv.lock": "pip",
    "pdm.lock": "pip",
    "pipfile.lock": "pip",
    "renv.lock": "renv",
    "manifest.toml": "julia",
    "conda-lock.yml": "conda",
    "conda-lock.yaml": "conda",
}
ENVIRONMENT_FILES = {
    "pipfile": "pip",
    "setup.py": "pip",
    "setup.cfg": "pip",
    "project.toml": "julia",
    "install.r": "renv",
}
TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".cfg", ".rst"})
REQUIREMENT_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

DATA_SUFFIXES = frozenset(
    {
        ".h5ad", ".h5", ".hdf5", ".loom", ".rds", ".rdata", ".rda", ".csv", ".tsv", ".parquet", ".feather", ".fa",
        ".fasta", ".fna", ".fastq", ".fq", ".bam", ".cram", ".vcf", ".bcf", ".gtf", ".gff", ".bed", ".mtx", ".npy",
        ".npz", ".xlsx", ".sqlite", ".db", ".pkl", ".pickle", ".gz", ".zip", ".tar", ".tgz", ".bz2", ".xz", ".7z",
        ".nc", ".tif", ".tiff",
    }
)  # fmt: skip
MODEL_SUFFIXES = frozenset({".pt", ".pth", ".ckpt", ".safetensors", ".onnx", ".pb", ".joblib", ".gguf"})
# The smallest a file is to be listed as data or a model that the project holds
MIN_DATA_BYTES = 50_000
LFS_SIGNATURE = b"version https://git-lfs.github.com/spec/v1"
LFS_POINTER_BYTES = (100, 300)

# Where data that a project points to is kept, as the part of an address that says it
DATA_HOSTS = (
    "zenodo.org",
    "figshare.com",
    "datadryad.org",
    "osf.io",
    "dataverse.harvard.edu",
    "huggingface.co/datasets",
    "ncbi.nlm.nih.gov/geo",
    "ncbi.nlm.nih.gov/sra",
    "ncbi.nlm.nih.gov/bioproject",
    "ebi.ac.uk/arrayexpress",
    "ebi.ac.uk/biostudies",
    "ebi.ac.uk/ena",
    "ebi.ac.uk/pride",
    "synapse.org",
    "10xgenomics.com/datasets",
    "cellxgene.cziscience.com",
)
URL = re.compile(r"https?://[^\s<>\"'`)\]}]+", re.IGNORECASE)
ACCESSION = re.compile(
    r"\b(GSE\d{3,}|GSM\d{3,}|SRP\d{4,}|SRR\d{5,}|ERP\d{4,}|PRJNA\d{3,}|PRJEB\d{3,}|E-MTAB-\d+|EGAS\d+)\b"
)

# What says a project needs a GPU, which is stronger when it is what is installed than when it is what the code does
GPU_DEPENDENCIES = (
    (r"\bcupy(?:-cuda\d+\w*)?\b", "cupy"),
    (r"\bcudatoolkit\b", "cudatoolkit"),
    (r"\bcuda-toolkit\b", "cuda-toolkit"),
    (r"nvidia/cuda", "an NVIDIA CUDA base image"),
    (r"\btensorflow-gpu\b", "tensorflow-gpu"),
    (r"\bfaiss-gpu\b", "faiss-gpu"),
    (r"\bonnxruntime-gpu\b", "onnxruntime-gpu"),
    (r"\b(?:cudf|cuml|cugraph|cuspatial)\b", "RAPIDS"),
    (r"\bjax\[cuda", "jax with CUDA"),
    (r"\bpytorch-cuda\b", "pytorch-cuda"),
    (r"\+cu\d{2,3}\b", "a CUDA build of PyTorch"),
    (r"\bmxnet-cu\d+", "mxnet for CUDA"),
    (r"\bflash[-_]attn\b", "flash-attn"),
    (r"\bbitsandbytes\b", "bitsandbytes"),
)
GPU_CODE = (
    (r"\.cuda\(\)", ".cuda()"),
    (r"\bdevice\s*=\s*[\"']cuda", 'device="cuda"'),
    (r"torch\.device\(\s*[\"']cuda", 'torch.device("cuda")'),
    (r"^\s*(?:import|from)\s+cupy\b", "cupy"),
    (r"\bnumba\.cuda\b|from\s+numba\s+import\s+cuda\b|@cuda\.jit", "numba CUDA"),
)
# What says that the code looks for a GPU and goes on without one
GPU_FALLBACK = re.compile(
    r"cuda\.is_available\(\)|[\"']cuda[\"']\s+if\b|torch\.device\(\s*[\"']cpu|list_physical_devices"
)
GPU_README = re.compile(
    r"\b(?:requires?|needs?|necessary|must have|only (?:runs|works) on)\b[^.\n]{0,80}\b(?:nvidia\s+)?gpus?\b",
    re.IGNORECASE,
)

# Where a script reads from that is a particular person's computer or a cluster's, which no one else has
ABSOLUTE_PATH = re.compile(
    r"(?<![\w.])(?:/Users/[A-Za-z0-9_.-]+/|/home/[A-Za-z0-9_.-]+/|[A-Za-z]:\\\\?Users\\\\?|/mnt/[a-z]/|/scratch/|"
    r"/gpfs/|/lustre/|/nfs/)[^\s\"'`)\]},;]*"
)

EXAMPLE_HEADING = re.compile(
    r"^#{1,6}\s*(?:usage|quick\s*start|getting started|examples?|tutorials?|how to use)\b", re.I | re.M
)
EXAMPLE_WORDS = re.compile(r"\b(?:usage|quick\s*start|getting started|examples?|tutorial)\b", re.IGNORECASE)

# What the wording of a license says it is: its name, what kind it is, and the phrases it has, all of them. Tried in
# order, so that a license that quotes another (the Lesser GPL quotes the GPL) is told first
LICENSES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("AGPL-3.0", "copyleft", ("gnu affero general public license",)),
    ("LGPL", "copyleft", ("gnu lesser general public license",)),
    ("GPL-3.0", "copyleft", ("gnu general public license", "version 3")),
    ("GPL-2.0", "copyleft", ("gnu general public license", "version 2")),
    ("MPL-2.0", "copyleft", ("mozilla public license", "2.0")),
    ("Apache-2.0", "permissive", ("apache license", "version 2.0")),
    ("MIT", "permissive", ("permission is hereby granted, free of charge", "the software is provided")),
    (
        "BSD-3-Clause",
        "permissive",
        ("redistribution and use in source and binary forms", "neither the name"),
    ),
    ("BSD-2-Clause", "permissive", ("redistribution and use in source and binary forms", "this list of conditions")),
    (
        "ISC",
        "permissive",
        ("permission to use, copy, modify, and/or distribute this software for any purpose with or without fee",),
    ),
    ("Unlicense", "public domain", ("this is free and unencumbered software released into the public domain",)),
    ("CC0-1.0", "public domain", ("cc0 1.0 universal",)),
    ("CC-BY-NC", "noncommercial", ("creative commons", "noncommercial")),
    ("CC-BY-4.0", "permissive", ("creative commons attribution 4.0",)),
)
# What a license is called in a manifest, which says its name and not its text
LICENSE_NAMES: tuple[tuple[str, str, str], ...] = (
    (r"\bagpl", "AGPL-3.0", "copyleft"),
    (r"\blgpl", "LGPL", "copyleft"),
    (r"\bgpl[- v]*3|gnu general public license.*3", "GPL-3.0", "copyleft"),
    (r"\bgpl[- v]*2|gnu general public license.*2", "GPL-2.0", "copyleft"),
    (r"\bgpl\b|gnu general public license", "GPL", "copyleft"),
    (r"\bmpl|mozilla public", "MPL-2.0", "copyleft"),
    (r"apache", "Apache-2.0", "permissive"),
    (r"^mit\b|\bmit license|\bmit$", "MIT", "permissive"),
    (r"\bbsd[- ]?3|3-clause|new bsd", "BSD-3-Clause", "permissive"),
    (r"\bbsd[- ]?2|2-clause|simplified bsd", "BSD-2-Clause", "permissive"),
    (r"\bbsd\b", "BSD", "permissive"),
    (r"^isc\b", "ISC", "permissive"),
    (r"unlicense", "Unlicense", "public domain"),
    (r"\bcc0\b", "CC0-1.0", "public domain"),
    (r"\bnc\b|non-?commercial", "non-commercial", "noncommercial"),
)
LICENSE_STEMS = ("license", "licence", "copying", "unlicense")
LICENSE_SUFFIXES = ("", ".md", ".txt", ".rst")
MAX_LICENSE_CHARS = 30_000


def clean(text: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """Text from a project, made fit to be kept and shown on one line: no control characters, and not long."""
    return re.sub(r"[\x00-\x1f\x7f]", "?", str(text))[:limit]


class Reader:
    """Reads files as text within what may be read in all, and says when that has run out."""

    def __init__(self, total: int | None = None) -> None:
        self.left = MAX_TOTAL_READ if total is None else total
        self.exhausted = False

    def text(self, path: Path, limit: int = MAX_READ_BYTES) -> str | None:
        """The start of a file as text, or None if it is not text, cannot be read, or too much has been read."""
        if self.left <= 0:
            self.exhausted = True
            return None
        try:
            with path.open("rb") as file:
                data = file.read(min(limit, self.left))
        except OSError:
            return None
        self.left -= len(data)
        if b"\x00" in data[:2048]:
            return None

        return data.decode("utf-8", errors="replace")


def identify_license(text: str) -> tuple[str | None, str]:
    """What license a text is, by its wording: its name if it is one that is known, and what kind it is, which is
    `other` for one that is not."""
    lowered = " ".join(text.lower().split())
    for name, kind, phrases in LICENSES:
        if all(phrase in lowered for phrase in phrases):
            return name, kind
    if re.search(r"non-?commercial|academic (?:use )?only|research (?:use )?only", lowered):
        return None, "noncommercial"

    return None, "other"


def identify_license_name(name: str) -> tuple[str | None, str]:
    """What license a name in a manifest is: its name as it is known, and its kind, or the name as it was written and
    `other` if it is not known."""
    lowered = " ".join(name.lower().split())
    for pattern, known, kind in LICENSE_NAMES:
        if re.search(pattern, lowered):
            return known, kind

    return clean(name, 80), "other"


def manifest_license(root: Path, reader: Reader) -> str | None:
    """The name of the license that the project's manifest gives, if it does: pyproject.toml, setup.cfg, setup.py,
    DESCRIPTION for R, or package.json."""
    for name in ("pyproject.toml", "setup.cfg", "setup.py", "DESCRIPTION", "package.json"):
        path = root / name
        if not path.is_file() or path.is_symlink() or (text := reader.text(path)) is None:
            continue
        found: str | None = None
        if name == "pyproject.toml":
            try:
                project = tomllib.loads(text).get("project", {})
            # A file nested deeper than the parser goes raises RecursionError, which is not a ValueError
            except (tomllib.TOMLDecodeError, RecursionError):
                project = {}
            value = project.get("license") if isinstance(project, dict) else None
            if isinstance(value, dict):
                value = value.get("text") or value.get("file")
            found = value if isinstance(value, str) else None
            if found is None and isinstance(project, dict):
                classifiers = [c for c in project.get("classifiers", []) if isinstance(c, str)]
                found = next((c.split("::")[-1].strip() for c in classifiers if c.startswith("License ::")), None)
        elif name == "package.json":
            try:
                value = json.loads(text).get("license")
            except (ValueError, AttributeError, RecursionError):
                value = None
            found = value if isinstance(value, str) else None
        elif name == "DESCRIPTION":
            match = re.search(r"^License:\s*(.+)$", text, re.MULTILINE)
            found = match.group(1) if match else None
        else:
            match = re.search(r"^\s*license\s*=\s*[\"']?([^\"'\n,)]+)", text, re.MULTILINE | re.IGNORECASE)
            found = match.group(1) if match else None
        if found and found.strip():
            return found.strip()

    return None


def find_license(root: Path, names: list[str], reader: Reader) -> dict[str, Any] | None:
    """The license of a project: what its license files say, and where they do not say which it is, what its manifest
    says. None if there is nothing that says.

    :param names: The names of the files that are in the project's top folder.
    """
    files = [
        name
        for name in names
        if PurePosixPath(name).stem.lower().startswith(LICENSE_STEMS)
        and PurePosixPath(name).suffix.lower() in LICENSE_SUFFIXES
    ]
    name: str | None = None
    kind = "other"
    for file in files[:3]:
        if (text := reader.text(root / file, MAX_LICENSE_CHARS)) is not None:
            name, kind = identify_license(text)
            if name is not None:
                break
    if name is None and (written := manifest_license(root, reader)) is not None:
        listed, manifest_kind = identify_license_name(written)
        if listed is not None and (manifest_kind != "other" or not files):
            return {
                "files": [clean(file) for file in files[:3]],
                "name": listed,
                "kind": manifest_kind,
                "from": "manifest",
            }
    if not files:
        return None

    return {"files": [clean(file) for file in files[:3]], "name": name, "kind": kind, "from": "file"}


def pins_of(text: str, kind: str) -> str | None:
    """How many of the packages that a file asks for are given a version: all, some, or none. None if it asks for
    none.

    :param kind: conda for an environment file, and pip for a file of requirements.
    """
    pinned = total = 0
    section = ""
    for raw in text.splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        if kind == "conda":
            if not raw[0].isspace() and (heading := re.match(r"([A-Za-z_][\w-]*)\s*:", raw)):
                section = heading.group(1)
                continue
            if section != "dependencies" or not line.startswith("- ") or line.endswith(":"):
                continue
            requirement = line[2:].strip()
            total += 1
            pinned += bool(re.search(r"(?<![<>!~])=\s*\d|==", requirement))
        else:
            if line.startswith(("-", "git+", "http", "[")) or not REQUIREMENT_LINE.match(line):
                continue
            total += 1
            pinned += bool(re.search(r"===?\s*\d|@\s*\S", line))
    if total == 0:
        return None

    return "all" if pinned == total else "some" if pinned else "none"


def environment_kind(parts: list[str], read: Callable[[], str | None]) -> tuple[str, str | None] | None:
    """What a file is for setting up an environment, if it is: its kind, and how far it gives versions (a lock, or all,
    some, or none of the packages it asks for, or None if it does not say). None for a file that is not one.

    :param parts: The folders of the file's path, and its name last.
    :param read: Reads the file's text, which is done only for a file that is one that is looked into.
    """
    name = parts[-1].lower()
    if name in ENVIRONMENT_LOCKS:
        return ENVIRONMENT_LOCKS[name], "locked"
    if name.startswith("dockerfile") or name.endswith(".dockerfile"):
        return "docker", None
    if len(parts) > MAX_ENVIRONMENT_DEPTH:
        return None
    if re.fullmatch(r"(?:requirements|constraints)[\w.-]*\.(?:txt|in)", name) or (
        name.endswith(".txt") and len(parts) > 1 and parts[-2].lower() in ("requirements", "reqs")
    ):
        text = read()
        return "pip", pins_of(text, "pip") if text is not None else None
    if re.fullmatch(r"(?:environment|conda)[\w.-]*\.ya?ml", name):
        text = read()
        return "conda", pins_of(text, "conda") if text is not None else None
    if name == "pyproject.toml":
        text = read()
        return ("pip", None) if text is not None and re.search(r"^\[(?:project|tool\.poetry)\]", text, re.M) else None
    if name == "description" and len(parts) == 1:
        text = read()
        return ("r-package", None) if text is not None and re.search(r"^Package:", text, re.MULTILINE) else None
    if name in ENVIRONMENT_FILES:
        return ENVIRONMENT_FILES[name], None

    return None


def notebook_cells(text: str) -> tuple[str | None, list[tuple[str, str]]] | None:
    """The language a notebook says it is of, and its code and text cells as their kind and their source, or None if
    what is given is not a notebook."""
    try:
        notebook = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if not isinstance(notebook, dict) or not isinstance(notebook.get("cells"), list):
        return None
    metadata = notebook.get("metadata")
    kernel = metadata.get("kernelspec") if isinstance(metadata, dict) else None
    language = kernel.get("language") if isinstance(kernel, dict) else None
    cells = []
    for cell in notebook["cells"]:
        if not isinstance(cell, dict):
            continue
        source = cell.get("source", "")
        source = "".join(part for part in source if isinstance(part, str)) if isinstance(source, list) else source
        if isinstance(source, str) and cell.get("cell_type") in ("code", "markdown"):
            cells.append((cell["cell_type"], source))

    return language if isinstance(language, str) else None, cells


def leads_to_data(address: str) -> bool:
    """Whether a web address is at one of the places where data is kept: the host, or a host of that, and the start of
    the path that the place is given with."""
    try:
        parts = urlsplit(address)
        host = (parts.hostname or "").removeprefix("www.")
    except ValueError:
        return False
    path = parts.path.lower().lstrip("/")
    for place in DATA_HOSTS:
        place_host, _, place_path = place.partition("/")
        if (host == place_host or host.endswith(f".{place_host}")) and path.startswith(place_path):
            return True

    return False


def data_links(text: str) -> list[str]:
    """The addresses in a text that lead to where data is kept, as they are written."""
    found = (match.group(0).rstrip(".,;:") for match in URL.finditer(text))

    return [address for address in found if leads_to_data(address)]


class Inspector:
    """A project as it is looked at: what each file shows is added to what the others did, and what is found is given
    as the stock.

    :param root: The project's folder.
    :param files: Each file's path from the folder, with its size, which are the ones to look at.
    :param complete: Whether these are all of the files, and not only those before the walk was stopped.
    """

    def __init__(self, root: Path, files: list[tuple[str, int]], complete: bool) -> None:
        self.root = root
        self.files = files
        self.complete = complete
        self.reader = Reader()
        self.languages: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        self.notebooks: list[dict[str, Any]] = []
        self.tutorials: list[dict[str, Any]] = []
        self.tests: list[str] = []
        self.environment: list[dict[str, Any]] = []
        self.gpu: list[dict[str, str]] = []
        self.looks_for_gpu = False
        self.absolute: list[dict[str, str]] = []
        self.absolute_count = 0
        self.data: list[dict[str, Any]] = []
        self.data_bytes = 0
        self.lfs_pointers = 0
        self.lfs_attributes = False
        self.small_checked = 0
        self.code_scanned = 0
        self.dvc = False
        self.links: list[str] = []
        self.accessions: set[str] = set()
        self.submodules: list[dict[str, str]] = []

    def note_gpu(self, path: str, signal: str, kind: str) -> None:
        """Notes that something needs a GPU: where, what it is, and whether it is what is installed, what the code
        does, or what the README says."""
        if len(self.gpu) < MAX_SIGNALS * 3 and not any(
            item["signal"] == signal and item["kind"] == kind for item in self.gpu
        ):
            self.gpu.append({"path": clean(path), "signal": clean(signal, 100), "kind": kind})

    def code(self, path: str, text: str, tutorial: bool) -> None:
        """What a piece of code shows: whether it uses a GPU, and for a tutorial, whether it reads from a place that
        only one machine has."""
        if GPU_FALLBACK.search(text):
            self.looks_for_gpu = True
        for pattern, signal in GPU_CODE:
            if re.search(pattern, text, re.MULTILINE):
                self.note_gpu(path, signal, "code")
        if tutorial and (found := ABSOLUTE_PATH.search(text)) is not None:
            self.absolute_count += 1
            if len(self.absolute) < MAX_SIGNALS:
                self.absolute.append({"path": clean(path), "example": clean(found.group(0), 100)})

    def text_facts(self, text: str) -> None:
        self.links.extend(data_links(text))
        self.accessions.update(ACCESSION.findall(text))

    def notebook(self, path: str, size: int) -> None:
        record: dict[str, Any] = {"path": clean(path), "bytes": size, "code_cells": None, "language": None}
        parsed = None
        if size <= MAX_NOTEBOOK_BYTES and (text := self.reader.text(self.root / path, MAX_NOTEBOOK_BYTES)) is not None:
            parsed = notebook_cells(text)
        characters = size
        if parsed is not None:
            language, cells = parsed
            code = [source for kind, source in cells if kind == "code"]
            known = NOTEBOOK_LANGUAGES.get((language or "").lower()) or (
                clean(language, 30).title() if language else None
            )
            characters = sum(len(source) for _, source in cells)
            record.update(code_cells=len(code), language=known)
            if known is not None:
                self.languages[known][0] += 1
                self.languages[known][1] += sum(len(source) for source in code)
            self.code(path, "\n".join(code), tutorial=bool(code))
            for _, source in cells:
                self.text_facts(source)
        self.notebooks.append(record)
        if record["code_cells"] != 0:
            self.tutorials.append({"path": clean(path), "kind": "notebook", "bytes": size, "characters": characters})

    def file(self, path: str, size: int) -> None:
        """What one file shows."""
        parts = path.split("/")
        name = parts[-1]
        lowered = name.lower()
        suffix = PurePosixPath(name).suffix.lower()
        folders = [part.lower() for part in parts[:-1]]
        in_tests = any(part in TEST_DIRECTORIES for part in folders)
        in_tutorials = any(part.rstrip("s") in TUTORIAL_DIRECTORIES for part in folders) or lowered.startswith(
            TUTORIAL_NAMES
        )
        is_test = (
            in_tests
            or lowered.startswith("test_")
            or lowered.endswith(("_test.py", "_test.r"))
            or lowered == "conftest.py"
        )
        full = self.root / path

        if suffix == ".ipynb":
            if not in_tests:
                self.notebook(path, size)
            return
        if is_test and suffix in (".py", ".r"):
            self.tests.append(path)
        if lowered == ".gitattributes":
            if (text := self.reader.text(full)) is not None and "filter=lfs" in text:
                self.lfs_attributes = True
        elif lowered == ".gitmodules" and len(parts) == 1:
            if (text := self.reader.text(full)) is not None:
                for block in re.split(r"(?m)^\[submodule", text)[1:]:
                    where = re.search(r"path\s*=\s*(\S+)", block)
                    address = re.search(r"url\s*=\s*(\S+)", block)
                    if where and len(self.submodules) < MAX_LISTED:
                        self.submodules.append(
                            {"path": clean(where.group(1)), "url": clean(address.group(1), 300) if address else ""}
                        )
        elif suffix == ".dvc" or lowered == "dvc.yaml" or parts[0] == ".dvc":
            self.dvc = True

        language = LANGUAGES.get(suffix) or ("Snakemake" if name == "Snakefile" else None)
        if language is not None:
            self.languages[language][0] += 1
            self.languages[language][1] += size
        if suffix in (".cu", ".cuh"):
            self.note_gpu(path, "CUDA source code", "code")
        if (
            not is_test
            and lowered != "__init__.py"
            and (suffix in DOCUMENT_SUFFIXES or (suffix in SCRIPT_SUFFIXES and in_tutorials))
        ):
            self.tutorials.append(
                {
                    "path": clean(path),
                    "kind": "document" if suffix in DOCUMENT_SUFFIXES else "script",
                    "bytes": size,
                    "characters": size,
                }
            )
        if size <= MAX_READ_BYTES and (suffix in (".r", ".jl", ".sh", ".rmd", ".qmd") or suffix == ".py"):
            scanned_here = suffix == ".py" and not in_tests
            if scanned_here and self.code_scanned >= MAX_CODE_FILES_SCANNED:
                scanned_here = False
            if (scanned_here or (in_tutorials and not is_test)) and (text := self.reader.text(full)) is not None:
                self.code_scanned += scanned_here
                self.code(path, text, tutorial=in_tutorials and not is_test)

        if (kind := environment_kind(parts, lambda: self.reader.text(full))) is not None:
            if len(self.environment) < MAX_LISTED:
                self.environment.append({"path": clean(path), "kind": kind[0], "pins": kind[1]})

        if suffix in DATA_SUFFIXES | MODEL_SUFFIXES and size >= MIN_DATA_BYTES:
            self.data_bytes += size
            self.data.append(
                {"path": clean(path), "bytes": size, "kind": "model" if suffix in MODEL_SUFFIXES else "data"}
            )
        elif (
            LFS_POINTER_BYTES[0] <= size <= LFS_POINTER_BYTES[1]
            and self.small_checked < MAX_SMALL_FILES_CHECKED
            and suffix not in LANGUAGES
            and suffix not in TEXT_SUFFIXES
        ):
            self.small_checked += 1
            try:
                with full.open("rb") as file:
                    self.lfs_pointers += file.read(len(LFS_SIGNATURE)) == LFS_SIGNATURE
            except OSError:
                pass

    def top_folder(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The project's README, and what its license is, from the files in its top folder."""
        names = [path for path, _ in self.files if "/" not in path]
        readme = None
        readme_name = next((name for name in names if PurePosixPath(name).stem.lower() == "readme"), None)
        if readme_name is not None and (text := self.reader.text(self.root / readme_name)) is not None:
            example = bool(
                EXAMPLE_HEADING.search(text) or (EXAMPLE_WORDS.search(text) and ("```" in text or "::" in text))
            )
            readme = {"path": clean(readme_name), "example": example}
            self.text_facts(text)
            if (said := GPU_README.search(text)) is not None:
                self.note_gpu(readme_name, " ".join(said.group(0).split())[:80], "readme")
        for name in names:
            if name != readme_name and PurePosixPath(name).suffix.lower() in (".md", ".rst"):
                if (text := self.reader.text(self.root / name, MAX_DOCUMENT_BYTES)) is not None:
                    self.links.extend(data_links(text))

        return readme, find_license(self.root, names, self.reader)

    def stock(self) -> dict[str, Any]:
        """Looks at every file, and gives what was found."""
        for path, size in self.files:
            self.file(path, size)
        readme, license_found = self.top_folder()
        for item in self.environment:
            if (text := self.reader.text(self.root / item["path"])) is not None:
                for pattern, signal in GPU_DEPENDENCIES:
                    if re.search(pattern, text.lower()):
                        self.note_gpu(item["path"], signal, "dependency")

        # Code that asks for a GPU outright, in a project that also looks for one and goes on without it, is code that
        # uses one if there is one. It is only a need when what is installed or what the README says is one as well.
        required = [item for item in self.gpu if item["kind"] != "code" or not self.looks_for_gpu]
        optional = [item for item in self.gpu if item not in required]
        tutorials = self.tutorials
        links = list(dict.fromkeys(self.links))

        return {
            "schema": SCHEMA,
            "files": len(self.files),
            "bytes": sum(size for _, size in self.files),
            "complete": self.complete and not self.reader.exhausted,
            "languages": [
                {"name": name, "files": count[0], "bytes": count[1]}
                for name, count in sorted(self.languages.items(), key=lambda item: (-item[1][1], item[0]))[:8]
            ],
            "notebooks": {"count": len(self.notebooks), "listed": self.notebooks[:MAX_LISTED]},
            "tutorials": {
                "count": len(tutorials),
                "characters": sum(item["characters"] for item in tutorials),
                "listed": tutorials[:MAX_LISTED],
            },
            "tests": {"count": len(self.tests), "listed": [clean(path) for path in self.tests[:MAX_SIGNALS]]},
            "environment": self.environment,
            "license": license_found,
            "readme": readme,
            "gpu": {"required": required[:MAX_SIGNALS], "optional": optional[:MAX_SIGNALS]},
            "data": {
                "count": len(self.data),
                "bytes": self.data_bytes,
                "listed": sorted(self.data, key=lambda item: -item["bytes"])[:MAX_SIGNALS],
                "lfs": self.lfs_attributes or self.lfs_pointers > 0,
                "lfs_pointers": self.lfs_pointers,
                "dvc": self.dvc,
                "links": [clean(link, 300) for link in links[:MAX_SIGNALS]],
                "accessions": sorted(self.accessions)[:MAX_SIGNALS],
            },
            "submodules": self.submodules,
            "absolute_paths": {"count": self.absolute_count, "listed": self.absolute},
        }


# What a stock is made of, as the types of what it holds, for telling one that was kept from one that was edited: a
# dictionary has these keys, a list has only items of this shape, a tuple is any one of its shapes
SIGNAL = {"path": str, "signal": str, "kind": str}
SHAPE: dict[str, Any] = {
    "schema": int,
    "files": int,
    "bytes": int,
    "complete": bool,
    "languages": [{"name": str, "files": int, "bytes": int}],
    "notebooks": {
        "count": int,
        "listed": [{"path": str, "bytes": int, "code_cells": (int, None), "language": (str, None)}],
    },
    "tutorials": {
        "count": int,
        "characters": int,
        "listed": [{"path": str, "kind": str, "bytes": int, "characters": int}],
    },
    "tests": {"count": int, "listed": [str]},
    "environment": [{"path": str, "kind": str, "pins": (str, None)}],
    "license": ({"files": [str], "name": (str, None), "kind": str, "from": str}, None),
    "readme": ({"path": str, "example": bool}, None),
    "gpu": {"required": [SIGNAL], "optional": [SIGNAL]},
    "data": {
        "count": int,
        "bytes": int,
        "listed": [{"path": str, "bytes": int, "kind": str}],
        "lfs": bool,
        "lfs_pointers": int,
        "dvc": bool,
        "links": [str],
        "accessions": [str],
    },
    "submodules": [{"path": str, "url": str}],
    "absolute_paths": {"count": int, "listed": [{"path": str, "example": str}]},
}


def matches(shape: Any, value: Any) -> bool:
    """Whether a value is of a shape: a dictionary with the keys of a shape that is one, each of its shape, a list of
    items that are all of the shape a list is given, or of one of the shapes of a tuple, or of a type (a whole number is
    never a bool)."""
    if isinstance(shape, dict):
        return isinstance(value, dict) and all(
            key in value and matches(part, value[key]) for key, part in shape.items()
        )
    if isinstance(shape, list):
        return isinstance(value, list) and all(matches(shape[0], item) for item in value)
    if isinstance(shape, tuple):
        return any(matches(option, value) for option in shape)
    if shape is None:
        return value is None
    if shape is int:
        return isinstance(value, int) and not isinstance(value, bool)

    return isinstance(value, shape)


def is_stock(value: Any) -> bool:
    """Whether what is given is a stock, as take_stock makes one, which it is not if it was edited to be something
    else."""
    return matches(SHAPE, value) and value["schema"] == SCHEMA


def walk(root: Path) -> tuple[list[tuple[str, int]], bool]:
    """The regular files in a folder and below it, as their paths from it and their sizes, without following a link and
    without the folders that others made. The second is False if there were more files than are looked at."""
    files: list[tuple[str, int]] = []
    for directory, directories, names in os.walk(root, topdown=True, followlinks=False):
        here = Path(directory)
        directories[:] = sorted(
            name for name in directories if name not in SKIPPED_DIRECTORIES and not (here / name).is_symlink()
        )
        relative = here.relative_to(root)
        if len(relative.parts) >= MAX_DEPTH:
            directories[:] = []
        for name in sorted(names):
            try:
                status = (here / name).lstat()
            except OSError:
                continue
            if stat.S_ISREG(status.st_mode):
                files.append(((relative / name).as_posix(), status.st_size))
        if len(files) >= MAX_FILES:
            return files[:MAX_FILES], False

    return files, True


def take_stock(root: Path) -> dict[str, Any]:
    """What is in a project's folder: its languages, notebooks and tutorials, tests, the files that say how to set it
    up, its license, what in it needs a GPU, the data and models it holds or points to, and what would stop its
    examples running on another machine. Nothing in it is run.

    :param root: The folder of the project's files.
    :return: The facts, as a dictionary that is kept as it is.
    """
    files, complete = walk(root)

    return Inspector(root, files, complete).stock()
