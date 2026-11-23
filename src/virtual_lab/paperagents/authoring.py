"""What a reader of a paper would hit when they take its code, said to the person who wrote it or who is reviewing it.

Everything here is made from what was kept of the code, the environment that was built of it, the tutorials that were
run, and the paper that was read: the same checks that are made before a paper's code is built from, put as what would
stop a reader and what to change, and then, from the same facts, a card of what was found, a short statement of where
the code and the data are, and an environment file. It runs nothing and asks no model.

A finding is a thing that a reader may hit, with how bad (`block`: they cannot get going, `warn`: they will probably be
stopped or misled, `note`: they should know), where it is, and what would mend it. It is found from files, from words,
and from what the steps kept, so it can be wrong in both directions, and a thing that was not looked at is said so and
is not a good sign.
"""

import ast
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

SEVERITIES = ("block", "warn", "note")
VERDICTS = ("not_checked", "blocked", "to_fix", "unfinished", "ready")
MEANING = (
    "A finding is something that a reader who takes the code as a stranger may hit, found from the files, from words, "
    "and from what the steps kept, so it can be wrong both ways. `ready` says that nothing that was looked at stood in "
    "a reader's way and that every step was looked at: not that the code is right or that what the paper reports is. "
    "`unfinished` says that nothing was found and that some steps have not been run."
)

# How much is read and said: the code files looked at for what they import, how much of each, what is named of one kind,
# and how many places are given for a finding
MAX_FILES_READ = 400
MAX_FILE_CHARS = 200_000
MAX_NAMES = 20
MAX_WHERE = 5
MAX_EACH = 12
MAX_CLAIM_ROWS = 20
MAX_CELL_CHARS = 160

# What an import is called when it is installed under another name, as far as the name does not say it
ALIASES = {
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "cv2": "opencv-python",
    "pil": "pillow",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "bio": "biopython",
    "umap": "umap-learn",
    "dateutil": "python-dateutil",
    "attr": "attrs",
    "igraph": "python-igraph",
    "serial": "pyserial",
    "jwt": "pyjwt",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "magic": "python-magic",
    "git": "gitpython",
    "faiss": "faiss-cpu",
    "tables": "pytables",
    "mpl_toolkits": "matplotlib",
    "pkg_resources": "setuptools",
    "psycopg2": "psycopg2-binary",
}
# The shortest import that a package with more in its name is taken to be the one of
MIN_PREFIX = 3
# Files whose imports are not what a reader runs
SKIPPED_PARTS = frozenset({"tests", "test", "docs", "doc", "docs_src", ".github", "benchmarks", "build", "dist"})
SKIPPED_NAMES = re.compile(r"(?:^test_.*|.*_test|conftest|setup|noxfile|conf)\.py$")
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

# What a build that failed would be mended by, by the kind of failure that the build gave
BUILD_ADVICE = {
    "missing_system_library": "Say which system packages (apt) have to be installed first, in the README or a "
    "Dockerfile.",
    "version_conflict": "Loosen or correct the pins that conflict, or give a lock file from an environment that works.",
    "python_mismatch": "Say which Python the code needs (`python_requires`, `requires-python`, or `.python-version`).",
    "not_found": "A pinned package cannot be had for this Python or machine: update the pin, or say what to use.",
    "network": "Something it installs cannot be reached: link to a place that stays up, or carry it in the repository.",
    "private_dependency": "A dependency needs a sign-in: make it public, or carry it in the repository.",
    "build_failed": "A package has to be compiled: pin a version that has a ready-made wheel, or say what it needs.",
    "out_of_memory": "The install needs more memory than a reader's machine may have: say how much, or lighten it.",
    "too_big": "The install is very large: say how much room it takes, or lighten it.",
    "timeout": "The install takes very long: say how long, or lighten it.",
    "does_not_run": "It installs and does not start: look at what it imports when it starts.",
    "docker": "Docker did not do what the build needed, which says nothing of the code: try again.",
    "failed": "Read the log of the build for what stopped it.",
}
# What each check of the code is, said as what a reader would hit, and what to change
CHECKS = {
    "code": ("code", "A reader may find nothing that they can run", "Say which language it is, and how to run it."),
    "license": (
        "license",
        "A reader may not know what they are allowed to do with the code",
        "Add a LICENSE file with a license that says what a reader may do (MIT or BSD-3-Clause for open code), and "
        "name it in the paper.",
    ),
    "tutorials": (
        "examples",
        "Nothing shows a reader how to run it",
        "Add a notebook or an example script that runs from the README's steps on a small input that is in the "
        "repository or can be downloaded.",
    ),
    "tests": (
        "examples",
        "It has no tests of its own",
        "Add tests of the functions that the paper's results come from.",
    ),
    "environment": (
        "environment",
        "Nothing says what to install",
        "Add a requirements.txt or an environment.yml with versions (`pip freeze` from an environment that works).",
    ),
    "gpu": (
        "environment",
        "It needs or can use a GPU",
        "Say which GPU and driver it needs, or add a path that runs on a CPU, even on a small input.",
    ),
    "data": (
        "data",
        "A reader may not be able to get the data",
        "Deposit the data at a public archive (Zenodo, Figshare, GEO, ENA) and link it in the README, with its size.",
    ),
    "portability": (
        "examples",
        "Examples read from a path on the authors' computer",
        "Read paths from a setting or a path relative to the project, and say in the README what to put there.",
    ),
    "size": (
        "code",
        "The repository is very large",
        "Leave out data and models that can be fetched, and say where they are.",
    ),
    "submodules": (
        "code",
        "Some code is in submodules that a plain download does not have",
        "Say to clone with `--recursive`, or carry that code in the repository.",
    ),
}
AREAS = ("code", "license", "environment", "examples", "data", "claims", "steps")


def finding(
    name: str, area: str, severity: str, title: str, detail: str, where: Sequence[str] = (), fix: str | None = None
) -> dict[str, Any]:
    return {
        "id": name,
        "area": area,
        "severity": severity,
        "title": title,
        "detail": detail,
        "where": list(where)[:MAX_WHERE],
        "fix": fix,
    }


def cell(text: Any, limit: int = MAX_CELL_CHARS) -> str:
    """Text that is of one line and can be in a table: what the papers and the code say is not trusted to be."""
    one = " ".join(str(text if text is not None else "").split()).replace("|", "/")

    return one if len(one) <= limit else one[: limit - 1].rstrip() + "…"


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def is_read(path: str) -> bool:
    """Whether the imports of a file of code are ones that a reader needs: not a test, a document, or a set-up
    script."""
    parts = path.split("/")
    return (
        not SKIPPED_PARTS & {part.lower() for part in parts[:-1]}
        and SKIPPED_NAMES.fullmatch(parts[-1]) is None
        and parts[-1].endswith((".py", ".ipynb"))
    )


def roots_in(tree: ast.AST) -> set[str]:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(name.name.split(".")[0] for name in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])

    return found


def code_of_notebook(text: str) -> str:
    """The code of a notebook's cells, without its magics and shell lines, which are not Python."""
    try:
        record = json.loads(text)
    except ValueError:
        return ""
    cells = record.get("cells") if isinstance(record, dict) else None
    pieces = []
    for each in cells if isinstance(cells, list) else []:
        if not isinstance(each, dict) or each.get("cell_type") != "code":
            continue
        source = each.get("source")
        lines = source if isinstance(source, list) else str(source or "").splitlines()
        lines = [line for line in lines if isinstance(line, str)]
        if lines and lines[0].lstrip().startswith("%%"):
            continue
        pieces.append("\n".join(line.rstrip("\n") for line in lines if not line.lstrip().startswith(("%", "!", "?"))))

    return "\n\n".join(pieces)


def imports_in(files: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    """What the code of a project imports, by the first part of the name, with the files that import it.

    :param files: Each file of the project by its place in it, with its text. Only those that a reader runs are read.
    """
    found: dict[str, list[str]] = defaultdict(list)
    for count, (path, text) in enumerate(item for item in files if is_read(item[0])):
        if count >= MAX_FILES_READ:
            break
        source = code_of_notebook(text) if path.endswith(".ipynb") else text[:MAX_FILE_CHARS]
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            continue
        for root in sorted(roots_in(tree)):
            found[root].append(path)

    return dict(found)


def local_names(paths: Iterable[str]) -> set[str]:
    """What an import may be of the project itself: the name of each file of Python, and of each folder that has one."""
    names = set()
    for path in paths:
        parts = path.split("/")
        if parts[-1].endswith(".py"):
            names.add(parts[-1][:-3])
            names.update(parts[:-1])

    return names


def declared_words(texts: Iterable[str]) -> set[str]:
    """Every name that the files that say what to install have in them, which is what an import is looked for among."""
    return {normalize(word) for text in texts for word in WORD.findall(text)}


def is_declared(root: str, declared: set[str]) -> bool:
    """Whether a file that says what to install names what an import is of: by its name, under the name that it is
    known to be installed as, as `python-` or `py` with it, or as one of a family that is named from it (`google-cloud`
    for `google`)."""
    name = normalize(root)
    names = {name, normalize(ALIASES.get(root.lower(), root)), f"python-{name}", f"py{name}"}
    if names & declared:
        return True

    return len(name) >= MIN_PREFIX and any(word.startswith(f"{name}-") for word in declared)


def undeclared(imports: Mapping[str, Sequence[str]], local: set[str], declared: set[str]) -> list[dict[str, Any]]:
    """The imports that no file saying what to install names, as they are or under another name, most files first."""
    standard = sys.stdlib_module_names
    found = []
    for root, files in imports.items():
        if root in standard or root in local or root.startswith("_") or is_declared(root, declared):
            continue
        found.append({"name": root, "files": sorted(files)[:MAX_WHERE], "count": len(files)})
    found.sort(key=lambda item: (-item["count"], item["name"]))

    return found[:MAX_NAMES]


def check_findings(checks: Sequence[Mapping[str, Any]], stock: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What the checks made of the code before anything is built say to a reader, as findings.

    :param checks: The `checks` of the go or no-go check.
    :param stock: What was found of the code.
    """
    found = []
    for each in checks:
        if each["status"] == "ok" or each["id"] not in CHECKS:
            continue
        area, title, fix = CHECKS[each["id"]]
        severity = "note" if each["status"] == "unknown" else each["status"]
        where: list[str] = []
        if each["id"] == "portability":
            where = [f"{item['path']}: {cell(item['example'], 80)}" for item in stock["absolute_paths"]["listed"]]
        elif each["id"] == "license":
            where = list((stock.get("license") or {}).get("files") or [])
        found.append(finding(each["id"], area, severity, title, each["detail"], where, fix))

    return found


def requirement_findings(missing: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not missing:
        return []
    names = ", ".join(item["name"] for item in missing[:8])
    detail = (
        f"{len(missing)} import{'s are' if len(missing) != 1 else ' is'} named by no file that says what to install ({names}). A reader who installs "
        "from those files will meet an ImportError when the code gets there. This is found by name, so an import that "
        "is installed under another name, or is only tried, may be a false alarm."
    )
    where = [f"{item['name']}: {', '.join(item['files'][:2])}" for item in missing]

    return [
        finding(
            "requirements",
            "environment",
            "warn",
            "The code imports what no requirement file names",
            detail,
            where,
            "Add each package that the code needs to the requirements file, with a version.",
        )
    ]


def build_findings(
    built: Mapping[str, Any] | None,
    failure: Mapping[str, Any] | None,
    unsupported: Mapping[str, Any] | None,
    docker: Mapping[str, Any],
    has_code: bool,
) -> list[dict[str, Any]]:
    """What the building of the environment says to a reader."""
    if not has_code:
        return []
    if built is not None:
        if built["pip_check"]["ok"] is False:
            return [
                finding(
                    "pip_check",
                    "environment",
                    "warn",
                    "The packages that were installed conflict with one another",
                    "`pip check` reported that some installed packages need versions that are not the ones installed.",
                    (),
                    "Correct the pins so that `pip check` is clean.",
                )
            ]
        return []
    if failure is not None:
        kind = failure["kind"]
        where = [failure["package"]] if failure.get("package") else []
        advice = BUILD_ADVICE.get(kind, BUILD_ADVICE["failed"])
        if failure.get("system_packages"):
            advice += f" It looks as if it needs: {', '.join(failure['system_packages'][:5])}."
        severity = "note" if kind == "docker" else "block"

        return [
            finding(
                "build",
                "environment",
                severity,
                f"The environment does not build: {failure['title']}",
                failure["detail"],
                where,
                advice,
            )
        ]
    if unsupported is not None:
        return [
            finding(
                "build_unsupported",
                "environment",
                "note",
                "The environment was not built here",
                unsupported["message"],
                (),
                "Lumi builds Python projects that have a pip or a conda file; a reader of this one is on their own for "
                "the steps that it did not check.",
            )
        ]
    if not docker["ready"]:
        return [
            finding(
                "build_not_built",
                "environment",
                "note",
                "The environment has not been built, and Docker is not running",
                docker["message"] or "Docker is not running.",
                (),
                "Start Docker and build the environment, to see what a reader would meet.",
            )
        ]

    return [
        finding(
            "build_not_built",
            "environment",
            "note",
            "The environment has not been built",
            "What a reader's install would meet is not known until it is built.",
            (),
            "Build the environment.",
        )
    ]


def tutorial_findings(reference: Mapping[str, Any] | None, built: bool, running: bool = False) -> list[dict[str, Any]]:
    """What the running of the tutorials says to a reader.

    :param running: Whether the tutorials are being run now, when what is kept of them is the run so far and is not
        given.
    """
    if running:
        return [
            finding(
                "tutorials_running",
                "examples",
                "note",
                "The tutorials are being run",
                "What a reader would see when they run the examples is known once the run ends.",
            )
        ]
    if reference is None:
        if not built:
            return []
        return [
            finding(
                "tutorials_not_run",
                "examples",
                "note",
                "The tutorials have not been run",
                "What a reader would see when they run the examples is not known until they are run.",
                (),
                "Run the tutorials here.",
            )
        ]
    found = []
    if not reference["complete"]:
        found.append(
            finding(
                "tutorials_stopped",
                "examples",
                "note",
                "The run of the tutorials did not come to its end",
                "It was stopped, or ended early, so what a reader would see of the ones that were not reached is not "
                "known.",
                (),
                "Run the tutorials again.",
            )
        )
    failed = [each for each in reference["tutorials"] if each["status"] != "ok"]
    for each in failed[:MAX_EACH]:
        why = each["failure"] or {"title": each["status"].replace("_", " "), "kind": each["status"]}
        found.append(
            finding(
                f"tutorial:{each['id']}",
                "examples",
                "warn",
                f"{cell(each['path'], 80)} does not run to the end: {why['title'].lower()}",
                f"It was run in the environment that was built, with no network. It ended as: {why['title'].lower()}.",
                [each["path"]],
                "Make it run from a fresh clone with the README's steps, or say what else it needs.",
            )
        )
    unstable = [each for each in reference["tutorials"] if each["status"] == "ok" and each["stable"] is False]
    for each in unstable[:MAX_EACH]:
        found.append(
            finding(
                f"unstable:{each['id']}",
                "examples",
                "note",
                f"{cell(each['path'], 80)} gives different output when it is run twice",
                "It ran to the end both times and what it did was not the same, so a reader cannot compare what they "
                f"get with what the paper shows. It differed in: {cell(', '.join(each['differs'][:5]), 120)}.",
                [each["path"]],
                "Set the random seeds, sort what is printed, and leave out times and paths.",
            )
        )
    if reference["skipped"]:
        found.append(
            finding(
                "tutorials_skipped",
                "examples",
                "note",
                f"{len(reference['skipped'])} examples were not run",
                "They are not Python, or are of a kind that is not run here: "
                + ", ".join(cell(item["path"], 60) for item in reference["skipped"][:5])
                + ".",
                [item["path"] for item in reference["skipped"]],
                None,
            )
        )
    if reference["not_run"] or reference["more"]:
        found.append(
            finding(
                "tutorials_not_all_run",
                "examples",
                "note",
                "Not every tutorial was run",
                f"{len(reference['not_run']) + reference['more']} were left out by the limits of the run.",
                [item["path"] for item in reference["not_run"]],
                None,
            )
        )

    return found


def data_findings(data: Mapping[str, Any], read: bool) -> list[dict[str, Any]]:
    """What the places of the data say to a reader, from where the paper and the code say it is: nothing is asked of any
    of them."""
    found = []
    if not read:
        found.append(
            finding(
                "data_unread",
                "data",
                "note",
                "The paper was not read, so its data was not looked for",
                "What the paper says of where its data is, and which datasets it used, is not known.",
                (),
                "Read the paper here.",
            )
        )
    lost = [item for item in data["datasets"] if not item["accession"] and item["candidate"] is None]
    for item in lost[:MAX_EACH]:
        found.append(
            finding(
                f"dataset:{item['key']}",
                "data",
                "warn",
                f"The paper names the dataset {cell(item['name'], 60)} and nothing says where to get it",
                f"Its words are: {cell(item['quote'], 200)}",
                (),
                "Give an accession or a link to the data, and say how large it is.",
            )
        )
    for item in data["candidates"]:
        if not item["supported"] and item["facts"]:
            found.append(
                finding(
                    f"place:{item['key']}",
                    "data",
                    "note",
                    f"Data is at {cell(item['label'], 60)}, which is not fetched here",
                    cell(item["reason"] or "It is not one of the places that data is fetched from here.", 200),
                    [item["url"]] if item.get("url") else [],
                    "Say in the README how a reader fetches it.",
                )
            )

    return found[: MAX_EACH * 2]


def claim_findings(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """What the trying of the paper's numbers against its code says to a reader.

    :param entries: Each claim as the trying of them gives it, with its value, its sentence, and what came of it.
    """
    found = []
    for each in entries:
        if each["status"] not in ("not_reproduced", "partly"):
            continue
        severity = "warn" if each["status"] == "not_reproduced" else "note"
        title = {"not_reproduced": "A number of the paper was not found again", "partly": "A number was found in part"}
        found.append(
            finding(
                f"claim:{each['id']}",
                "claims",
                severity,
                f"{title[each['status']]}: {cell(each['value'], 40)}",
                f"The paper says: {cell(each['quote'], 200)}",
                (),
                "Check the seed, the data version, and the setting that the paper used, or say in the paper how the "
                "code differs.",
            )
        )

    return found[: MAX_EACH * 2]


def ordered(found: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(found, key=lambda item: (SEVERITIES.index(item["severity"]), AREAS.index(item["area"])))


def verdict_of(found: Sequence[Mapping[str, Any]], has_code: bool, unchecked: int = 0) -> tuple[str, str]:
    """Where the code stands for a reader, and a sentence that says it.

    :param unchecked: How many steps that would look at more have not been run.
    """
    if not has_code:
        return "not_checked", "The code has not been fetched, so nothing is known of what a reader would hit."
    blocks = sum(1 for item in found if item["severity"] == "block")
    warns = sum(1 for item in found if item["severity"] == "warn")
    if blocks:
        return "blocked", f"{blocks} thing{'s' if blocks != 1 else ''} would stop a reader, and {warns} more may."
    if warns:
        return "to_fix", f"{warns} thing{'s' if warns != 1 else ''} a reader will probably meet."
    if unchecked:
        return "unfinished", (
            f"Nothing was found in what was looked at, and {unchecked} step{'s have' if unchecked != 1 else ' has'} "
            "not been run."
        )

    return "ready", "Nothing that was looked at stands in a reader's way."


def not_checked(steps: Mapping[str, bool], agent_id: str) -> list[dict[str, str]]:
    """What was not looked at, from what is kept, and how it would be.

    :param steps: Whether the paper was read (`read`), the code fetched (`code`), the environment built
        (`environment`), the tutorials run (`tutorials`), and the paper's numbers tried (`claims`).
    """
    base = f"/api/paperagents/{agent_id}"
    items = []
    if not steps["read"]:
        items.append({"id": "reading", "title": "The paper was not read", "how": f"POST {base}/reading"})
    if not steps["code"]:
        items.append({"id": "repository", "title": "The code was not fetched", "how": f"POST {base}/repository"})
    elif not steps["environment"]:
        items.append({"id": "environment", "title": "The environment was not built", "how": f"POST {base}/environment"})
    elif not steps["tutorials"]:
        items.append({"id": "reference", "title": "The tutorials were not run", "how": f"POST {base}/reference"})
    elif not steps["claims"] and steps["read"]:
        items.append(
            {"id": "reproduction", "title": "The paper's numbers were not tried", "how": f"POST {base}/reproduction"}
        )

    return items


def table(rows: Sequence[Sequence[Any]], head: Sequence[str]) -> list[str]:
    lines = [f"| {' | '.join(head)} |", f"| {' | '.join('---' for _ in head)} |"]
    lines += [f"| {' | '.join(cell(item, 80) for item in row)} |" for row in rows]

    return lines


def card_of(facts: Mapping[str, Any]) -> str:
    """The reproducibility card: what was found of the code and its environment, the tutorials, the paper's numbers,
    and the data, with how far each was looked at, as Markdown to put in the repository."""
    code = facts["code"]
    lines = [f"# Reproducibility card: {cell(facts['title'], 120)}", ""]
    lines.append(
        "This card says what Lumi found when it took the code of this paper as a stranger would, and what it did not "
        f"look at. It was made on {facts['made_at'][:10]} from what Lumi kept. It does not say that what the paper "
        "reports is right."
    )
    lines += ["", "## Paper and code", ""]
    paper = facts.get("doi") and f"DOI {cell(facts['doi'], 80)}" or facts.get("url") or "not given"
    lines.append(f"- Paper: {cell(paper, 120)}")
    if code is None:
        lines.append("- Code: not fetched, so nothing below is known.")
    else:
        lines.append(f"- Code: {cell(code['url'], 120)}, at commit `{code['commit']}` ({cell(code['ref'], 60)})")
        license_ = facts["license"]
        lines.append(
            f"- License: {cell(license_['name'] or 'none was recognized', 60)}"
            + (f" ({license_['kind']})" if license_["kind"] else "")
        )
    lines += ["", "## Environment", ""]
    environment = facts["environment"]
    if environment is None:
        lines.append("- Not built here, so what a reader's install would meet is not known.")
    else:
        lock = environment["lock"]
        lines += [
            f"- Built with {environment['kind']} on Python {cell(environment['python'], 20)} from "
            f"`{cell(environment['base_image'], 60)}`",
            f"- Exact versions: {lock['packages']} packages, in `{lock['name']}` (sha256 `{lock['sha256'][:16]}`)",
            f"- `pip check`: {'clean' if environment['pip_check'] else 'reported conflicts'}",
        ]
    lines += ["", "## Tutorials", ""]
    tutorials = facts["tutorials"]
    if facts.get("tutorials_running"):
        lines.append("- Being run here now: what came of them is known once the run ends.")
    elif tutorials is None:
        lines.append("- Not run here.")
    else:
        lines.append(
            f"- {tutorials['ran']} run in the environment with no network, as a stranger's computer would be: "
            f"{tutorials['ok']} to the end, {tutorials['failed']} not; {tutorials['unstable']} gave different output "
            "when run twice."
        )
    lines += ["", "## The paper's numbers", ""]
    claims = facts["claims"]
    if claims is None:
        lines.append("- Not tried against the code.")
    else:
        counts = claims["counts"]
        lines.append(
            "- "
            + ", ".join(
                f"{counts.get(status, 0)} {status.replace('_', ' ')}"
                for status in ("reproduced", "partly", "not_reproduced", "not_attempted")
            )
        )
        if claims["rows"]:
            lines += [
                "",
                *table(
                    [[row["value"], row["status"].replace("_", " "), row["quote"]] for row in claims["rows"]],
                    ["Number", "Result", "Where the paper says it"],
                ),
            ]
    lines += ["", "## Data", ""]
    if facts["datasets"] or facts["places"]:
        for dataset in facts["datasets"]:
            where = dataset["accession"] or dataset["place"] or "no place given"
            lines.append(f"- {cell(dataset['name'], 80)}: {cell(where, 80)}")
        for place in facts["places"]:
            lines.append(f"- {cell(place['label'], 60)}: {cell(place['url'], 120)}")
    else:
        lines.append("- The paper and the code do not say where the data is.")
    lines += ["", "## Tools", ""]
    if facts["tools"]:
        lines += table([[tool["name"], tool["tier"]] for tool in facts["tools"]], ["Tool", "Tier"])
        lines.append("")
        lines.append("A tier says what a tool was checked against, and not that what it gives is right.")
    else:
        lines.append("- No tools were made of this code.")
    package = facts["package"]
    if package is not None:
        lines += [
            "",
            "## Package",
            "",
            f"- `{package['file']}` ({package['bytes']:,} bytes, sha256 `{package['sha256'][:16]}`), a server of the "
            "Model Context Protocol made of the tools above.",
        ]
    counts = facts["findings"]
    lines += [
        "",
        "## What a reader would hit",
        "",
        f"- {counts['block']} would stop them, {counts['warn']} may, {counts['note']} to know (see `findings.json`).",
    ]
    for item in facts["top"]:
        lines.append(f"  - {item['severity']}: {cell(item['title'], 140)}")

    return "\n".join(lines) + "\n"


def statement_of(facts: Mapping[str, Any]) -> str:
    """A short statement of where the code, the data, and the software are, as the authors would put it in the paper.
    What is not known is left as a bracket for them to fill, and is not made up."""
    code = facts["code"]
    if code is None:
        where = "[Code availability: give where the code can be had.]"
    else:
        said = cell(facts["license"]["name"], 60) or "[license: none was found, add one]"
        where = f"The code is available at {code['url']} (commit {code['commit'][:12]}) under the {said} license."
    environment = facts["environment"]
    if environment is None:
        software = "[Software: say the version of Python and of each package that was used.]"
    else:
        lock = environment["lock"]
        software = (
            f"It was run with Python {cell(environment['python'], 20)}; the exact versions of its {lock['packages']} "
            f"packages are in {lock['name']}."
        )
    datasets = facts["datasets"]
    located = [item for item in datasets if item["accession"] or item["place"]]
    lost = [item for item in datasets if item not in located]
    places = [place["url"] for place in facts["places"]]
    sentences = []
    if located:
        sentences.append(
            "The data are available: "
            + "; ".join(
                f"{cell(item['name'], 80)} ({cell(item['accession'] or item['place'], 120)})" for item in located[:6]
            )
            + "."
        )
    elif places:
        sentences.append(f"The data are available at {', '.join(cell(url, 120) for url in places[:4])}.")
    if lost:
        names = ", ".join(cell(item["name"], 80) for item in lost[:6])
        sentences.append(f"[Data availability: say where {names} can be had.]")
    if not sentences:
        sentences.append(
            "[Data availability: give an accession or a link for each dataset, or say why it cannot be shared.]"
        )

    return "\n".join(
        [
            "# Availability",
            "",
            "## Code availability",
            "",
            where,
            software,
            "",
            "## Data availability",
            "",
            *sentences,
            "",
        ]
    )
