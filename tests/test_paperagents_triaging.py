"""Tests of the triage of a listing of papers by their code: which addresses of code a text gives, which one is a
paper's, what is kept of a paper whose code was looked at and of one whose code was not, and the order they come in."""

from pathlib import Path
from typing import Any

from test_paperagents_stock import MIT, notebook, stock_of

from virtual_lab.paperagents import triaging
from virtual_lab.paperagents.preflight import preflight

HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org")


def as_repo(address: str) -> str | None:
    """Stands in for the server's: the project at an address at a host of code, or None if it is a page of the host."""
    text = address if "://" in address else f"https://{address}"
    scheme, _, rest = text.partition("://")
    host, _, path = rest.partition("/")
    segments = [part for part in path.split("/") if part]
    if scheme not in ("http", "https") or host.removeprefix("www.").lower() not in HOSTS:
        return None
    if len(segments) < 2 or segments[0] in ("orgs", "sponsors", "topics"):
        return None
    name = segments[1].removesuffix(".git")

    return f"https://{host.removeprefix('www.').lower()}/{segments[0]}/{name}"


def entry(doi: str = "10.1101/2025.01.01.000001", **fields: Any) -> dict[str, Any]:
    return {"doi": doi, "title": f"Paper {doi}", "abstract": "", "code": None, **fields}


GOOD = {
    "README.md": "# Tool\n\n## Usage\n\nSee the tutorial.\n",
    "LICENSE": MIT,
    "requirements.txt": "numpy==1.26.4\n",
    "tool/__init__.py": "def run(x):\n    return x\n",
    "tests/test_tool.py": "def test_run():\n    assert True\n",
    "tutorials/quickstart.ipynb": notebook(["import tool\ntool.run(1)\n"], ["# Quickstart"]),
}
MORE_TUTORIALS = {**GOOD, "tutorials/second.ipynb": notebook(["import tool\ntool.run(2)\n"], ["# Second"])}
UNPINNED = {**GOOD, "requirements.txt": "numpy\n"}
NO_LICENSE = {key: value for key, value in GOOD.items() if key != "LICENSE"}
NO_TUTORIALS = {"README.md": "# Tool\n", "tool/__init__.py": "def run(x):\n    return x\n"}
NO_CODE = {"README.md": "# Notes\n\nNothing runs here.\n", "data.csv": "a,b\n1,2\n"}
WITH_GPU = {**GOOD, "tool/model.py": "import torch\n\nmodel = torch.nn.Linear(1, 1).cuda()\n"}

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def looked_at(tmp_path: Path, files: dict[str, Any], position: int = 1, **fields: Any) -> dict[str, Any]:
    stock = stock_of(tmp_path / f"p{position}", files)

    return triaging.looked(
        entry(f"10.1101/x.{position}", **fields),
        position,
        "https://github.com/example/tool",
        "abstract",
        [],
        COMMIT,
        stock,
        preflight(stock),
    )


class TestTheAddressesOfCode:
    def test_the_projects_that_a_text_gives_are_found_with_or_without_the_scheme(self) -> None:
        text = (
            "Code is at https://github.com/lab/tool, and at gitlab.com/lab/other.git. A third, "
            "www.github.com/lab/third. is at the end of a sentence (https://codeberg.org/lab/fourth)."
        )

        assert triaging.project_links(text, as_repo) == [
            "https://github.com/lab/tool",
            "https://gitlab.com/lab/other",
            "https://github.com/lab/third",
            "https://codeberg.org/lab/fourth",
        ]

    def test_a_host_is_found_in_any_case(self) -> None:
        assert triaging.project_links("Code: https://GitHub.COM/Lab/One.", as_repo) == ["https://github.com/Lab/One"]

    def test_a_host_that_is_the_end_of_another_word_or_address_is_not_one(self) -> None:
        text = (
            "Not notgithub.com/lab/one nor https://evil.example/github.com/lab/two "
            "nor https://user@github.com/lab/three nor see-github.com/lab/four, "
            "and not https://example.org/?u=https://evil.example/gitlab.com/lab/five."
        )

        assert triaging.project_links(text, as_repo) == []

    def test_a_host_after_a_bracket_a_quote_a_colon_or_a_line_is_one(self) -> None:
        text = (
            'Code:github.com/lab/one, ("gitlab.com/lab/two") <https://www.github.com/lab/three>\ncodeberg.org/lab/four'
        )

        assert triaging.project_links(text, as_repo) == [
            f"https://{host}/lab/{name}"
            for host, name in (
                ("github.com", "one"),
                ("gitlab.com", "two"),
                ("github.com", "three"),
                ("codeberg.org", "four"),
            )
        ]

    def test_what_ends_a_sentence_or_a_bracket_is_not_part_of_the_address(self) -> None:
        text = "Code (https://github.com/lab/one), https://github.com/lab/two; https://github.com/lab/three!?"

        assert triaging.project_links(text, as_repo) == [
            f"https://github.com/lab/{name}" for name in ("one", "two", "three")
        ]

    def test_an_address_that_is_not_a_project_or_is_given_twice_is_left_out(self) -> None:
        text = "See https://github.com/orgs/lab/people and https://github.com/lab and https://example.org/lab/tool."
        repeated = "https://github.com/lab/tool then https://github.com/lab/tool.git and https://github.com/lab/tool/"

        assert triaging.project_links(text, as_repo) == []
        assert triaging.project_links(repeated, as_repo) == ["https://github.com/lab/tool"]

    def test_the_first_address_of_the_abstract_is_the_code_and_the_others_are_said(self) -> None:
        abstract = (
            "Code: https://github.com/lab/one. Benchmarks: https://github.com/lab/two, https://github.com/lab/three, "
            "https://github.com/lab/four, https://github.com/lab/five."
        )

        code, source, others = triaging.choose_code(None, abstract, as_repo)

        assert (code, source) == ("https://github.com/lab/one", "abstract")
        assert others == [f"https://github.com/lab/{name}" for name in ("two", "three", "four")]

    def test_an_address_that_a_person_gave_is_the_code_before_those_of_the_abstract(self) -> None:
        abstract = "Code: https://github.com/lab/one and https://github.com/lab/given."

        code, source, others = triaging.choose_code("https://github.com/lab/given", abstract, as_repo)

        assert (code, source, others) == ("https://github.com/lab/given", "person", ["https://github.com/lab/one"])

    def test_the_abstracts_other_addresses_are_few_beside_a_persons_too(self) -> None:
        names = ("one", "two", "three", "four", "five")
        abstract = " ".join(f"https://github.com/lab/{name}" for name in names)

        code, source, others = triaging.choose_code("https://github.com/lab/given", abstract, as_repo)

        assert source == "person" and others == [f"https://github.com/lab/{name}" for name in names[:3]]

    def test_a_paper_that_gives_none_has_none(self) -> None:
        assert triaging.choose_code(None, "Code on request.", as_repo) == (None, None, [])
        assert triaging.choose_code(None, "", as_repo) == (None, None, [])


class TestWhatIsKeptOfAPaper:
    def test_a_paper_whose_code_was_looked_at_has_what_the_preflight_said_and_what_was_found(
        self, tmp_path: Path
    ) -> None:
        found = looked_at(tmp_path, GOOD, 3, title="A tool", date="2025-01-06", category="bioinformatics")

        assert found["tier"] == found["verdict"] == "go" and found["position"] == 3
        assert found["title"] == "A tool" and found["date"] == "2025-01-06" and found["category"] == "bioinformatics"
        assert found["paper"] == {"kind": "doi", "doi": "10.1101/x.3"}
        assert found["code"] == "https://github.com/example/tool" and found["code_from"] == "abstract"
        assert found["tutorials"] == 1 and found["why"].startswith("Go")
        assert {item["id"] for item in found["checks"]} >= {"code", "license", "tutorials", "environment", "gpu"}
        assert all(set(item) == {"id", "status", "detail"} for item in found["checks"])
        assert found["stock"]["commit"] == COMMIT and found["stock"]["license"] == "MIT"
        assert found["stock"]["languages"][0] == "Python" and found["stock"]["files"] >= 5
        assert set(found["estimate"]) == {"low", "high", "tutorials"}

    def test_what_a_check_says_is_kept_short(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setattr(triaging, "MAX_DETAIL_CHARS", 20)

        found = looked_at(tmp_path, GOOD)

        assert max(len(item["detail"]) for item in found["checks"]) == 20

    def test_no_more_than_a_few_languages_are_named(self, tmp_path: Path, monkeypatch: Any) -> None:
        monkeypatch.setattr(triaging, "MAX_LANGUAGES", 1)

        found = looked_at(tmp_path, {**GOOD, "run.R": "x <- 1\n"})

        assert len(found["stock"]["languages"]) == 1

    def test_a_paper_with_no_address_is_of_no_code_and_one_whose_code_was_not_looked_at_is_not(self) -> None:
        none = triaging.unlooked(entry(), 1, None, None, [], "No address.")
        left = triaging.unlooked(entry(), 2, "https://github.com/lab/tool", "person", ["x"], "Too large.")

        assert (none["tier"], left["tier"]) == ("no_code", "not_looked_at")
        assert none["why"] == "No address." and left["why"] == "Too large."
        assert left["code"] == "https://github.com/lab/tool" and left["code_from"] == "person"
        assert left["other_codes"] == ["x"]
        for record in (none, left):
            assert record["verdict"] is None and record["checks"] == [] and record["stock"] is None
            assert record["tutorials"] is None and record["estimate"] is None

    def test_a_paper_with_no_license_says_none_of_it(self, tmp_path: Path) -> None:
        assert looked_at(tmp_path, NO_LICENSE)["stock"]["license"] is None

    def test_a_paper_that_is_without_a_doi_has_no_paper_to_point_to(self) -> None:
        record = triaging.unlooked({"title": "A title", "doi": None}, 1, None, None, [], "None.")

        assert record["doi"] is None and record["paper"] is None

    def test_a_paper_with_no_date_or_category_says_none(self) -> None:
        record = triaging.unlooked(entry(date="", category=""), 1, None, None, [], "None.")

        assert record["date"] is None and record["category"] is None


def shaped(position: int, tier: str, *statuses: str, tutorials: int = 0, high: float | None = None) -> dict[str, Any]:
    """A record that has the checks that are said and nothing else, for what the order goes by."""
    return {
        "position": position,
        "tier": tier,
        "checks": [{"id": f"c{number}", "status": status, "detail": ""} for number, status in enumerate(statuses)],
        "tutorials": tutorials,
        "estimate": {"low": None, "high": high, "tutorials": tutorials},
    }


class TestTheOrder:
    def test_the_answer_of_the_preflight_comes_first_then_what_was_not_looked_at_then_those_with_no_code(
        self, tmp_path: Path
    ) -> None:
        records = [
            triaging.unlooked(entry("a"), 1, None, None, [], "none"),
            looked_at(tmp_path, NO_CODE, 2),
            triaging.unlooked(entry("c"), 3, "https://github.com/lab/c", None, [], "too large"),
            looked_at(tmp_path, NO_LICENSE, 4),
            looked_at(tmp_path, GOOD, 5),
        ]

        ranked = triaging.rank(records)

        assert [item["tier"] for item in ranked] == ["go", "ask", "no-go", "not_looked_at", "no_code"]
        assert [item["position"] for item in ranked] == [5, 4, 2, 3, 1]
        assert [item["rank"] for item in ranked] == [1, 2, 3, 4, 5]

    def test_among_those_with_the_same_answer_the_one_with_less_to_weigh_comes_first(self, tmp_path: Path) -> None:
        both_unwarned = looked_at(tmp_path, UNPINNED, 1)
        one_warning = looked_at(tmp_path, NO_LICENSE, 2)
        two_warnings = looked_at(tmp_path, NO_TUTORIALS, 3)

        ranked = triaging.rank([two_warnings, one_warning, both_unwarned])

        assert [item["tier"] for item in ranked] == ["go", "ask", "ask"]
        assert [item["position"] for item in ranked] == [1, 2, 3]

    def test_a_block_outweighs_warnings(self) -> None:
        two_blocks = shaped(1, "no-go", "block", "block")
        one_block_and_warnings = shaped(2, "no-go", "block", "warn", "warn", "warn")
        many_warnings = shaped(3, "ask", "warn", "warn", "warn")
        one_warning_and_unknowns = shaped(4, "ask", "warn", "unknown", "unknown")
        one_warning = shaped(5, "ask", "warn", "ok")
        unknown_only = shaped(6, "go", "unknown", "unknown")
        nothing = shaped(7, "go", "ok", "note")

        ranked = triaging.rank(
            [
                two_blocks,
                one_block_and_warnings,
                many_warnings,
                one_warning_and_unknowns,
                one_warning,
                unknown_only,
                nothing,
            ]
        )

        assert [item["position"] for item in ranked] == [7, 6, 5, 4, 3, 2, 1]

    def test_more_tutorials_come_first_and_then_the_lower_cost_and_then_the_order_of_the_listing(
        self, tmp_path: Path
    ) -> None:
        one = looked_at(tmp_path, GOOD, 1)
        two = looked_at(tmp_path, MORE_TUTORIALS, 2)
        same = looked_at(tmp_path, GOOD, 3)
        dear = {**looked_at(tmp_path, GOOD, 4), "estimate": {"low": 1.0, "high": 9.0, "tutorials": 1}}
        cheap = {**looked_at(tmp_path, GOOD, 5), "estimate": {"low": 0.1, "high": 0.9, "tutorials": 1}}

        ranked = triaging.rank([dear, same, one, two, cheap])

        assert [item["position"] for item in ranked] == [2, 5, 4, 1, 3]

    def test_the_cost_is_that_of_the_dearer_end_of_the_guess(self, tmp_path: Path) -> None:
        wide = {**looked_at(tmp_path, GOOD, 1), "estimate": {"low": 0.1, "high": 9.0, "tutorials": 1}}
        narrow = {**looked_at(tmp_path, GOOD, 2), "estimate": {"low": 0.5, "high": 0.9, "tutorials": 1}}

        assert [item["position"] for item in triaging.rank([wide, narrow])] == [2, 1]

    def test_what_has_no_estimate_comes_after_what_has_one(self, tmp_path: Path) -> None:
        priced = {**looked_at(tmp_path, GOOD, 2), "estimate": {"low": 1.0, "high": 2.0, "tutorials": 1}}
        unpriced = {**looked_at(tmp_path, GOOD, 1), "estimate": {"low": None, "high": None, "tutorials": 1}}

        assert [item["position"] for item in triaging.rank([unpriced, priced])] == [2, 1]

    def test_what_was_not_looked_at_stays_in_the_order_of_the_listing(self) -> None:
        records = [triaging.unlooked(entry(str(n)), n, None, None, [], "none") for n in (3, 1, 2)]

        assert [item["position"] for item in triaging.rank(records)] == [1, 2, 3]

    def test_a_paper_whose_checks_are_not_known_comes_after_one_that_has_them_all(self, tmp_path: Path) -> None:
        known = looked_at(tmp_path, GOOD, 2)
        unknown = looked_at(tmp_path, GOOD, 1)
        unknown["checks"] = [
            {**item, "status": "unknown"} if item["id"] == "data" else item for item in unknown["checks"]
        ]
        known["checks"] = [{**item, "status": "ok"} if item["id"] == "data" else item for item in known["checks"]]

        assert [item["position"] for item in triaging.rank([unknown, known])] == [2, 1]

    def test_ranking_does_not_change_the_records_it_is_given(self, tmp_path: Path) -> None:
        records = [looked_at(tmp_path, GOOD, 1)]

        triaging.rank(records)

        assert "rank" not in records[0]

    def test_papers_are_counted_by_where_they_came_to(self, tmp_path: Path) -> None:
        records = [
            looked_at(tmp_path, GOOD, 1),
            looked_at(tmp_path, GOOD, 2),
            looked_at(tmp_path, NO_LICENSE, 3),
            triaging.unlooked(entry("d"), 4, None, None, [], "none"),
        ]

        assert triaging.counts_of(records) == {
            "papers": 4,
            "go": 2,
            "ask": 1,
            "no-go": 0,
            "not_looked_at": 0,
            "no_code": 1,
        }
        assert triaging.counts_of([])["papers"] == 0
