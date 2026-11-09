"""Tests of the check of whether it is worth going on with a paper's code: what each check says of what was found, how
they make a verdict, and the rough guess of what making tools would cost."""

from pathlib import Path
from typing import Any

import pytest
from test_paperagents_stock import APACHE, GPL3, MIT, NONCOMMERCIAL, UNRECOGNIZED, notebook, stock_of

from virtual_lab.paperagents import preflight as checking
from virtual_lab.paperagents.preflight import estimate, preflight
from virtual_lab.utils import CostUnknownError

USAGE = "# Tool\n\n## Usage\n\n```python\nimport tool\n```\n\nData: https://zenodo.org/records/1234567\n"

GOOD: dict[str, str | bytes | dict[str, Any]] = {
    "README.md": USAGE,
    "LICENSE": MIT,
    "requirements.txt": "numpy==1.26.0\npandas==2.1.0\n",
    "tool/core.py": "def run(x): return x\n",
    "examples/intro.ipynb": notebook(["import tool", "tool.run(1)"]),
    "tests/test_core.py": "def test_run(): ...\n",
}


def checks_of(result: dict[str, Any]) -> dict[str, dict[str, str]]:
    return {item["id"]: item for item in result["checks"]}


def statuses(result: dict[str, Any]) -> dict[str, str]:
    return {name: item["status"] for name, item in checks_of(result).items()}


def checked(tmp_path: Path, files: dict[str, str | bytes | dict[str, Any]], **options: Any) -> dict[str, Any]:
    return preflight(stock_of(tmp_path, files), **options)


class TestAProjectThatIsFineToGoOn:
    def test_says_go_and_every_check_is_ok(self, tmp_path: Path) -> None:
        result = checked(tmp_path, GOOD)

        assert result["verdict"] == "go"
        assert set(statuses(result).values()) == {"ok"}
        assert list(statuses(result)) == [
            "code",
            "license",
            "tutorials",
            "tests",
            "environment",
            "gpu",
            "data",
            "portability",
            "size",
        ]
        assert result["summary"].startswith("Go:")

    def test_the_checks_give_their_reasons_in_words(self, tmp_path: Path) -> None:
        found = checks_of(checked(tmp_path, GOOD))

        assert found["license"]["detail"] == "MIT."
        assert "1 tutorial or example, of which 1 notebook" in found["tutorials"]["detail"]
        assert found["environment"]["detail"].startswith("requirements.txt, with versions given")
        assert all(item["title"] and item["detail"] for item in found.values())


class TestTheCasesThatAreAskedAbout:
    def test_no_license_is_a_thing_to_weigh_and_says_why(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {key: value for key, value in GOOD.items() if key != "LICENSE"})

        assert result["verdict"] == "ask"
        assert statuses(result)["license"] == "warn"
        assert "not free to use or to share" in checks_of(result)["license"]["detail"]
        assert "it has a license to use it under" in result["summary"].lower()

    def test_no_tutorial_is_a_thing_to_weigh_and_says_what_is_missing(self, tmp_path: Path) -> None:
        files = {key: value for key, value in GOOD.items() if key != "examples/intro.ipynb"}
        files["README.md"] = "# Tool\n\nIt does things.\n"

        result = checked(tmp_path, files)

        assert result["verdict"] == "ask"
        assert statuses(result)["tutorials"] == "warn"
        assert "nothing to run as a reference" in checks_of(result)["tutorials"]["detail"]
        assert "portability" not in statuses(result)

    def test_a_readme_that_shows_use_without_a_tutorial_is_said_to_be_all_there_is(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {key: value for key, value in GOOD.items() if key != "examples/intro.ipynb"})

        assert statuses(result)["tutorials"] == "warn"
        assert "only a README that shows its use" in checks_of(result)["tutorials"]["detail"]

    def test_nothing_that_says_what_to_install_is_a_thing_to_weigh(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {key: value for key, value in GOOD.items() if key != "requirements.txt"})

        assert result["verdict"] == "ask"
        assert statuses(result)["environment"] == "warn"
        assert "guessed from what the code imports" in checks_of(result)["environment"]["detail"]

    def test_files_that_are_pointers_to_lfs_are_a_thing_to_weigh(self, tmp_path: Path) -> None:
        pointer = "version https://git-lfs.github.com/spec/v1\noid sha256:" + "c" * 64 + "\nsize 5\n"

        result = checked(tmp_path, {**GOOD, "data/cells.h5ad": pointer})

        assert result["verdict"] == "ask"
        assert statuses(result)["data"] == "warn"
        assert "Git LFS" in checks_of(result)["data"]["detail"]

    def test_examples_that_read_from_someones_computer_are_a_thing_to_weigh(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {**GOOD, "examples/run.py": 'read("/home/jsmith/data.csv")\n'})

        assert result["verdict"] == "ask"
        assert statuses(result)["portability"] == "warn"
        assert "/home/jsmith/data.csv in examples/run.py" in checks_of(result)["portability"]["detail"]

    def test_a_license_that_is_there_and_not_recognized_is_a_thing_to_weigh(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {**GOOD, "LICENSE": UNRECOGNIZED})

        assert statuses(result)["license"] == "warn"
        assert "not recognized" in checks_of(result)["license"]["detail"]

    def test_mostly_code_that_the_sandbox_does_not_run_is_a_thing_to_weigh(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {**GOOD, "src/big.cpp": "int main() {}\n" * 500})

        assert statuses(result)["code"] == "warn"
        assert "Most of it is C++" in checks_of(result)["code"]["detail"]

    def test_several_things_to_weigh_are_all_named_in_the_summary(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {"a.py": "x = 1\n"})

        assert result["verdict"] == "ask"
        assert result["summary"].startswith("Ask first. 3 things to weigh")
        for title in ("license", "shows how it is used", "says what it needs installed"):
            assert title in result["summary"]


class TestTheCasesThatAreStoppedAt:
    def test_a_need_for_a_gpu_is_no_go_and_says_what_needs_it(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {**GOOD, "requirements.txt": "cupy-cuda12x==13.0\nnumpy==1.26.0\n"})

        assert result["verdict"] == "no-go"
        assert statuses(result)["gpu"] == "block"
        assert "cupy (requirements.txt)" in checks_of(result)["gpu"]["detail"]
        assert result["summary"].startswith("No-go: It needs a GPU")

    def test_code_that_uses_a_gpu_only_if_there_is_one_is_a_thing_to_know_and_not_a_stop(self, tmp_path: Path) -> None:
        result = checked(
            tmp_path,
            {**GOOD, "tool/dev.py": "use = torch.cuda.is_available()\n", "tool/net.py": "model = Net().cuda()\n"},
        )

        assert result["verdict"] == "go"
        assert statuses(result)["gpu"] == "note"

    def test_a_project_with_no_code_is_no_go(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {"README.md": "# data\n", "LICENSE": MIT, "table.csv": "a,b\n1,2\n"})

        assert result["verdict"] == "no-go"
        assert statuses(result)["code"] == "block"
        assert "No code was found in its 3 files" in checks_of(result)["code"]["detail"]

    def test_a_project_in_languages_the_sandbox_does_not_run_is_no_go(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {"main.rs": "fn main() {}\n", "lib.cpp": "int x;\n", "LICENSE": MIT})

        assert result["verdict"] == "no-go"
        assert "the sandbox runs Python and R" in checks_of(result)["code"]["detail"]

    def test_a_stop_is_said_before_the_things_to_weigh(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {"main.rs": "fn main() {}\n"})

        assert result["verdict"] == "no-go"
        assert "to weigh" not in result["summary"]


class TestWhatIsOnlyANote:
    def test_a_copyleft_license_is_a_note_and_a_noncommercial_one_too(self, tmp_path: Path) -> None:
        copyleft = checked(tmp_path / "a", {**GOOD, "LICENSE": GPL3})
        research = checked(
            tmp_path / "b", {**GOOD, "LICENSE": f"Creative Commons Attribution-NonCommercial\n{NONCOMMERCIAL}"}
        )

        assert copyleft["verdict"] == "go" and statuses(copyleft)["license"] == "note"
        assert "on the same terms" in checks_of(copyleft)["license"]["detail"]
        assert research["verdict"] == "go" and statuses(research)["license"] == "note"
        assert "non-commercial" in checks_of(research)["license"]["detail"]

    def test_versions_that_are_not_given_are_a_note(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {**GOOD, "requirements.txt": "numpy\npandas\n"})

        assert result["verdict"] == "go"
        assert statuses(result)["environment"] == "note"
        assert "may not be what the authors used" in checks_of(result)["environment"]["detail"]

    def test_no_tests_is_a_note(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {key: value for key, value in GOOD.items() if key != "tests/test_core.py"})

        assert result["verdict"] == "go" and statuses(result)["tests"] == "note"

    def test_submodules_not_fetched_are_a_note_that_says_which(self, tmp_path: Path) -> None:
        result = checked(
            tmp_path, {**GOOD, ".gitmodules": '[submodule "e"]\n\tpath = ext/lib\n\turl = https://github.com/o/lib\n'}
        )

        assert result["verdict"] == "go"
        assert statuses(result)["submodules"] == "note"
        assert "ext/lib" in checks_of(result)["submodules"]["detail"]

    def test_a_project_that_was_not_all_looked_at_is_a_note(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stock = stock_of(tmp_path, GOOD)
        stock["complete"] = False

        assert statuses(preflight(stock))["size"] == "note"

    def test_the_paper_saying_what_the_code_is_licensed_as_is_added_to_the_license_check(self, tmp_path: Path) -> None:
        said = {"licenses": [{"name": "Apache-2.0", "covers": "code"}, {"name": "CC-BY", "covers": "paper"}]}

        result = checked(tmp_path, {key: value for key, value in GOOD.items() if key != "LICENSE"}, paper=said)

        assert "The paper says the code is under Apache-2.0." in checks_of(result)["license"]["detail"]
        assert "CC-BY" not in checks_of(result)["license"]["detail"]


class TestWhetherTheDataCanBeFound:
    BARE: dict[str, str | bytes | dict[str, Any]] = {key: value for key, value in GOOD.items() if key != "README.md"}

    def test_nothing_known_with_the_paper_not_read_through_says_it_may_say(self, tmp_path: Path) -> None:
        result = checked(tmp_path, self.BARE)

        assert statuses(result)["data"] == "unknown"
        assert "has not been read through" in checks_of(result)["data"]["detail"]
        assert result["verdict"] == "go"
        assert "1 thing not known yet: its data can be found" in result["summary"]

    def test_nothing_known_with_the_paper_read_says_it_is_to_be_found(self, tmp_path: Path) -> None:
        result = checked(tmp_path, self.BARE, paper={"datasets": [], "links": [], "availability": [], "licenses": []})

        assert statuses(result)["data"] == "unknown"
        assert "Nothing in the code or the paper says" in checks_of(result)["data"]["detail"]

    def test_what_the_paper_says_of_where_the_data_is_makes_it_ok(self, tmp_path: Path) -> None:
        said = {
            "datasets": [{"name": "PBMC", "accession": "GSE12345"}, {"name": "other", "accession": ""}],
            "links": [
                {"url": "https://zenodo.org/records/1", "role": "data"},
                {"url": "https://x.org", "role": "other"},
            ],
            "availability": [{"kind": "data", "quote": "The data is at Zenodo."}],
            "licenses": [],
        }

        result = checked(tmp_path, self.BARE, paper=said)

        assert statuses(result)["data"] == "ok"
        detail = checks_of(result)["data"]["detail"]
        assert "1 accession in the paper" in detail and "1 link to data in the paper" in detail
        assert "statement of where the data is in the paper" in detail

    def test_data_in_the_code_and_links_in_it_make_it_ok_with_the_size(self, tmp_path: Path) -> None:
        result = checked(tmp_path, {**self.BARE, "data/cells.h5ad": bytes(2_000_000)})

        assert statuses(result)["data"] == "ok"
        assert "1 data or model file in the code (1.9 MB)" in checks_of(result)["data"]["detail"]

    def test_the_code_is_ok_with_a_link_to_data_in_its_readme(self, tmp_path: Path) -> None:
        assert statuses(checked(tmp_path, GOOD))["data"] == "ok"


class TestTheCost:
    def price(self, tokens_in: int, tokens_out: int) -> float:
        return tokens_in * 2e-6 + tokens_out * 8e-6

    def test_a_guess_is_given_as_a_low_and_a_high_with_what_it_is_from(self, tmp_path: Path) -> None:
        stock = stock_of(tmp_path, GOOD)
        characters = stock["tutorials"]["characters"]
        tokens_in = characters // 4 + 3_000
        tokens_out = 2_000

        guess = estimate(stock, self.price)

        assert guess["tutorials"] == 1
        assert guess["low"] == round(self.price(tokens_in, tokens_out), 4)
        assert guess["high"] == round(self.price(tokens_in * 3, tokens_out * 3), 4)
        assert "A guess from 1 tutorial" in guess["basis"]
        assert "cost time, not model requests" in guess["basis"]

    def test_it_is_part_of_the_check(self, tmp_path: Path) -> None:
        result = checked(tmp_path, GOOD, price=self.price)

        assert result["estimate"]["low"] is not None and result["estimate"]["low"] < result["estimate"]["high"]

    def test_no_more_tutorials_are_counted_than_the_limit_and_each_is_cut_to_its_limit(self, tmp_path: Path) -> None:
        stock = stock_of(tmp_path, GOOD)
        stock["tutorials"] = {"count": 100, "characters": 100 * 10_000_000, "listed": []}

        guess = estimate(stock, self.price)

        assert guess["tutorials"] == 20
        tokens_in = 20 * 60_000 // 4 + 20 * 3_000
        assert guess["low"] == round(self.price(tokens_in, 20 * 2_000), 4)

    def test_there_is_none_with_no_tutorials(self, tmp_path: Path) -> None:
        guess = estimate(stock_of(tmp_path, {"a.py": "x"}), self.price)

        assert guess["low"] is None and guess["high"] is None and guess["tutorials"] == 0
        assert "no tutorials" in guess["basis"]

    def test_there_is_none_when_the_model_has_no_price_and_it_says_so(self, tmp_path: Path) -> None:
        def unknown(tokens_in: int, tokens_out: int) -> float:
            raise CostUnknownError('Cost of model "x" not known')

        guess = estimate(stock_of(tmp_path, GOOD), unknown)

        assert guess["low"] is None and 'Cost of model "x" not known' in guess["basis"]

    def test_there_is_none_when_there_is_no_model(self, tmp_path: Path) -> None:
        guess = estimate(stock_of(tmp_path, GOOD), None)

        assert guess["low"] is None and "price is not known" in guess["basis"]


class TestTheVerdicts:
    def test_the_statuses_and_verdicts_are_the_ones_there_are(self, tmp_path: Path) -> None:
        for files in (GOOD, {"a.py": "x"}, {"main.rs": "x"}, {**GOOD, "LICENSE": APACHE}):
            result = checked(tmp_path / str(len(str(files))), files)

            assert result["verdict"] in checking.VERDICTS
            assert {item["status"] for item in result["checks"]} <= set(checking.STATUSES)
