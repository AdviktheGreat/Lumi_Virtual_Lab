"""Tests of what a reader of a paper would hit when they take its code, said to the person who wrote it: which imports
no file names, what each check, build, tutorial, dataset, and claim says to a reader, where a project stands, and the
card and the statement that are made from the same facts."""

import json
from typing import Any

from virtual_lab.paperagents import authoring


def notebook(*cells: tuple[str, str | list[str]]) -> str:
    return json.dumps({"cells": [{"cell_type": kind, "source": source} for kind, source in cells]})


class TestWhatIsSaidOnOneLine:
    def test_what_the_code_or_the_paper_says_is_one_line_that_cannot_break_a_table(self) -> None:
        assert authoring.cell("a | b\n\n c\t d") == "a / b c d"
        assert authoring.cell(None) == "" and authoring.cell(12) == "12"

    def test_it_is_cut_to_the_length_that_is_asked(self) -> None:
        assert authoring.cell("x" * 500) == "x" * 159 + "…"
        assert authoring.cell("abcdef", 4) == "abc…"
        assert authoring.cell("abcd", 4) == "abcd"


class TestWhichFilesAreRead:
    def test_code_that_a_reader_runs_is_read(self) -> None:
        assert all(authoring.is_read(path) for path in ("run.py", "src/pkg/mod.py", "notebooks/a.ipynb"))

    def test_tests_documents_and_set_up_scripts_are_not(self) -> None:
        skipped = (
            "tests/test_a.py",
            "pkg/tests/helper.py",
            "test_a.py",
            "a_test.py",
            "conftest.py",
            "setup.py",
            "docs/conf.py",
            "docs/example.ipynb",
            "noxfile.py",
            ".github/scripts/a.py",
            "README.md",
            "analysis.R",
        )
        assert not any(authoring.is_read(path) for path in skipped)

    def test_a_folder_is_only_a_test_folder_by_its_name_in_full(self) -> None:
        assert authoring.is_read("latest/run.py") and authoring.is_read("contest/run.py")


class TestWhatIsImported:
    def test_each_import_is_by_the_first_part_of_its_name_with_the_files_that_have_it(self) -> None:
        found = authoring.imports_in(
            [
                ("a.py", "import numpy as np\nimport os.path\nfrom scipy.stats import norm\nfrom . import b\n"),
                ("src/b.py", "import numpy\nfrom .c import d\nfrom ..e import f\nif True:\n    import torch\n"),
            ]
        )

        assert found == {"numpy": ["a.py", "src/b.py"], "os": ["a.py"], "scipy": ["a.py"], "torch": ["src/b.py"]}

    def test_a_notebook_is_read_by_its_code_cells_without_its_magics_and_shell_lines(self) -> None:
        text = notebook(
            ("code", ["%matplotlib inline\n", "import pandas as pd\n", "!pip install tqdm\n", "x = 1"]),
            ("markdown", "import never_code"),
            ("raw", "import not_a_cell_of_code"),
            ("code", "%%bash\nimport also_not_python"),
            ("code", "from sklearn import svm"),
        )

        assert authoring.imports_in([("n.ipynb", text)]) == {"pandas": ["n.ipynb"], "sklearn": ["n.ipynb"]}

    def test_what_is_not_python_is_left_out_and_does_not_stop_the_others(self) -> None:
        found = authoring.imports_in(
            [
                ("broken.py", "def (:\n"),
                ("python2.py", "print 'x'\nimport old\n"),
                ("n.ipynb", "not json"),
                ("m.ipynb", json.dumps({"cells": "no"})),
                ("k.ipynb", json.dumps([1, 2])),
                ("tests/t.py", "import pytest\n"),
                ("fine.py", "import yaml\n"),
            ]
        )

        assert found == {"yaml": ["fine.py"]}

    def test_a_file_is_read_as_far_as_the_limit_and_only_so_many_files_are_read(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(authoring, "MAX_FILES_READ", 2)
        files = [(f"f{number}.py", f"import mod{number}\n") for number in range(5)]

        assert sorted(authoring.imports_in(files)) == ["mod0", "mod1"]

    def test_only_the_start_of_a_file_that_is_larger_than_the_limit_is_read(self, monkeypatch: Any) -> None:
        text = "import first\n"
        monkeypatch.setattr(authoring, "MAX_FILE_CHARS", len(text))

        assert authoring.imports_in([("big.py", text + "import second\n")]) == {"first": ["big.py"]}

    def test_code_too_deep_to_parse_is_left_out_and_does_not_stop_the_others(self) -> None:
        deep = "import deep\nx = " + "+".join(["1"] * 20_000) + "\n"

        found = authoring.imports_in([("deep.py", deep), ("fine.py", "import yaml\n")])

        assert found["yaml"] == ["fine.py"]

    def test_the_names_of_the_project_itself_are_its_files_and_the_folders_that_have_code(self) -> None:
        names = authoring.local_names(["cellmapper/__init__.py", "src/tool/core.py", "run.py", "data/a.csv", "x.R"])

        assert names == {"cellmapper", "__init__", "src", "tool", "core", "run"}


class TestWhatNoFileNames:
    def declared(self, *texts: str) -> set[str]:
        return authoring.declared_words(texts)

    def test_every_word_of_the_files_is_a_name_that_is_declared_in_one_form(self) -> None:
        words = self.declared("numpy==1.26.4\nScikit_Learn>=1.0  # fast\n- pip:\n  - Torch_Geometric\n")

        assert {"numpy", "scikit-learn", "fast", "pip", "torch-geometric"} <= words

    def test_what_is_in_a_file_that_says_what_to_install_is_not_reported(self) -> None:
        found = authoring.undeclared(
            {"numpy": ["a.py"], "pandas": ["a.py"], "torch_geometric": ["b.py"]},
            set(),
            self.declared("numpy\ntorch-geometric==2.0\n"),
        )

        assert found == [{"name": "pandas", "files": ["a.py"], "count": 1}]

    def test_the_standard_library_the_project_itself_and_private_names_are_not_reported(self) -> None:
        found = authoring.undeclared(
            {"os": ["a.py"], "json": ["a.py"], "mypkg": ["a.py"], "_thread": ["a.py"], "__main__": ["a.py"]},
            {"mypkg"},
            set(),
        )

        assert found == []

    def test_a_name_is_also_declared_as_python_or_py_with_it(self) -> None:
        for declared in ("python-widget", "widget-python", "pywidget"):
            assert authoring.undeclared({"widget": ["a.py"]}, set(), self.declared(declared)) == []
        assert [
            item["name"] for item in authoring.undeclared({"widget": ["a.py"]}, set(), self.declared("widgets"))
        ] == ["widget"]

    def test_a_name_is_declared_by_a_family_that_begins_with_it_and_only_by_a_name_that_is_long_enough(self) -> None:
        names = {"google": ["a.py"], "ab": ["a.py"], "foo": ["a.py"]}

        found = authoring.undeclared(names, set(), self.declared("google-cloud-storage\nab-cd\nfoobar\n"))

        assert [item["name"] for item in found] == ["ab", "foo"]

    def test_what_is_installed_under_another_name_is_not_reported(self) -> None:
        imports = {name: ["a.py"] for name in ("sklearn", "cv2", "PIL", "yaml", "Bio", "dateutil", "dotenv")}
        declared = self.declared(
            "scikit-learn\nopencv-python\npillow\npyyaml\nbiopython\npython-dateutil\npython-dotenv\n"
        )

        assert authoring.undeclared(imports, set(), declared) == []

    def test_the_name_with_python_or_py_beside_it_is_the_same_package(self) -> None:
        declared = self.declared("python-docx\nhdf5plugin-python\npyserial\n")

        assert (
            authoring.undeclared({"docx": ["a.py"], "hdf5plugin": ["a.py"], "serial": ["a.py"]}, set(), declared) == []
        )

    def test_a_family_that_is_named_from_the_import_is_the_package_of_it(self) -> None:
        declared = self.declared("google-cloud-storage\nazure-storage-blob\n")

        assert authoring.undeclared({"google": ["a.py"], "azure": ["a.py"]}, set(), declared) == []

    def test_a_short_name_is_not_the_family_of_what_starts_with_it(self) -> None:
        assert authoring.undeclared({"py": ["a.py"], "ab": ["a.py"]}, set(), self.declared("py-spy\nab-testing\n")) == [
            {"name": "ab", "files": ["a.py"], "count": 1},
            {"name": "py", "files": ["a.py"], "count": 1},
        ]

    def test_the_ones_that_most_files_import_are_first_and_the_files_are_few(self) -> None:
        imports = {"rare": ["z.py"], "often": [f"f{number}.py" for number in range(9)], "also": ["y.py"]}

        found = authoring.undeclared(imports, set(), set())

        assert [item["name"] for item in found] == ["often", "also", "rare"]
        assert found[0]["count"] == 9 and len(found[0]["files"]) == authoring.MAX_WHERE

    def test_only_so_many_names_are_given(self) -> None:
        imports = {f"mod{number:03d}": ["a.py"] for number in range(authoring.MAX_NAMES + 10)}

        assert len(authoring.undeclared(imports, set(), set())) == authoring.MAX_NAMES

    def test_it_says_in_a_finding_that_it_may_be_wrong(self) -> None:
        [found] = authoring.requirement_findings(
            [{"name": "pandas", "files": ["a.py", "b.py", "c.py"], "count": 3}, {"name": "tqdm", "files": ["a.py"]}]
        )

        assert (found["id"], found["area"], found["severity"]) == ("requirements", "environment", "warn")
        assert "2 imports are named" in found["detail"] and "pandas, tqdm" in found["detail"]
        assert "false alarm" in found["detail"]
        assert found["where"] == ["pandas: a.py, b.py", "tqdm: a.py"] and found["fix"]
        assert authoring.requirement_findings([]) == []
        [one] = authoring.requirement_findings([{"name": "joblib", "files": ["a.py"]}])
        assert one["detail"].startswith("1 import is named by no file")


def check(name: str, status: str, detail: str = "It is so.") -> dict[str, str]:
    return {"id": name, "title": name, "status": status, "detail": detail}


STOCK: dict[str, Any] = {
    "absolute_paths": {"count": 2, "listed": [{"path": "run.py", "example": "/Users/me/data.csv"}]},
    "license": {"files": ["LICENSE.md"], "name": None, "kind": "other", "from": "file"},
}


class TestWhatTheChecksSayToAReader:
    def test_a_check_that_is_fine_says_nothing(self) -> None:
        assert authoring.check_findings([check("code", "ok"), check("license", "ok")], STOCK) == []

    def test_a_check_that_is_not_known_is_a_note_and_the_others_keep_how_bad_they_are(self) -> None:
        found = authoring.check_findings(
            [check("data", "unknown"), check("tests", "warn"), check("environment", "block")], STOCK
        )

        assert [(item["id"], item["severity"], item["area"]) for item in found] == [
            ("data", "note", "data"),
            ("tests", "warn", "examples"),
            ("environment", "block", "environment"),
        ]
        assert all(item["fix"] and item["detail"] == "It is so." for item in found)

    def test_a_check_that_says_nothing_to_a_reader_is_left_out(self) -> None:
        assert authoring.check_findings([check("something_else", "block"), check("estimate", "warn")], STOCK) == []

    def test_the_paths_that_are_the_authors_own_are_said_where_they_are(self) -> None:
        [found] = authoring.check_findings([check("portability", "warn")], STOCK)

        assert found["where"] == ["run.py: /Users/me/data.csv"]
        assert "path" in found["title"].lower()

    def test_the_license_that_was_not_recognized_says_which_file(self) -> None:
        [found] = authoring.check_findings([check("license", "warn")], STOCK)

        assert found["where"] == ["LICENSE.md"]
        [none] = authoring.check_findings([check("license", "warn")], {**STOCK, "license": None})
        assert none["where"] == []

    def test_each_of_the_checks_has_a_title_an_area_and_what_to_change(self) -> None:
        for name, (area, title, fix) in authoring.CHECKS.items():
            assert area in authoring.AREAS and title and fix, name


BUILT = {"pip_check": {"ok": True}}
DOCKER = {"ready": True, "message": None}


def failure(kind: str, **more: Any) -> dict[str, Any]:
    return {"kind": kind, "title": "A system library is missing.", "detail": "zlib.h was not found.", **more}


class TestWhatTheBuildSaysToAReader:
    def test_nothing_is_said_of_a_build_when_there_is_no_code_or_when_it_is_clean(self) -> None:
        assert authoring.build_findings(None, None, None, DOCKER, False) == []
        assert authoring.build_findings(BUILT, None, None, DOCKER, True) == []

    def test_packages_that_conflict_are_a_thing_to_mend_even_when_it_built(self) -> None:
        [found] = authoring.build_findings({"pip_check": {"ok": False}}, None, None, DOCKER, True)

        assert (found["id"], found["severity"], found["area"]) == ("pip_check", "warn", "environment")

    def test_a_build_that_failed_stops_a_reader_and_says_what_to_do_by_why(self) -> None:
        [found] = authoring.build_findings(
            None,
            failure("missing_system_library", package="h5py", system_packages=["zlib1g-dev"]),
            None,
            DOCKER,
            True,
        )

        assert (found["id"], found["severity"], found["where"]) == ("build", "block", ["h5py"])
        assert found["title"] == "The environment does not build: A system library is missing."
        assert "apt" in found["fix"] and "zlib1g-dev" in found["fix"]

    def test_each_kind_of_failure_has_advice_and_one_that_is_not_known_has_the_general_one(self) -> None:
        for kind in authoring.BUILD_ADVICE:
            [found] = authoring.build_findings(None, failure(kind), None, DOCKER, True)
            assert found["fix"].startswith(authoring.BUILD_ADVICE[kind]), kind
        [other] = authoring.build_findings(None, failure("never_heard_of"), None, DOCKER, True)
        assert other["fix"] == authoring.BUILD_ADVICE["failed"]

    def test_docker_failing_is_not_said_to_stop_a_reader(self) -> None:
        [found] = authoring.build_findings(None, failure("docker"), None, DOCKER, True)

        assert found["severity"] == "note"

    def test_a_project_that_is_not_built_here_is_said_not_to_have_been(self) -> None:
        [found] = authoring.build_findings(None, None, {"kind": "r", "message": "It is R."}, DOCKER, True)

        assert (found["id"], found["severity"], found["detail"]) == ("build_unsupported", "note", "It is R.")

    def test_one_that_is_not_built_yet_says_why_if_it_is_docker(self) -> None:
        [off] = authoring.build_findings(None, None, None, {"ready": False, "message": "Docker is off."}, True)
        [plain] = authoring.build_findings(None, None, None, DOCKER, True)

        assert (off["id"], off["severity"], off["detail"]) == ("build_not_built", "note", "Docker is off.")
        assert plain["id"] == "build_not_built" and "Docker" not in plain["detail"]


def tutorial(name: str, status: str = "ok", **more: Any) -> dict[str, Any]:
    return {
        "id": name,
        "path": f"tutorials/{name}.ipynb",
        "status": status,
        "failure": None,
        "stable": True,
        "differs": [],
        **more,
    }


def reference(*tutorials: dict[str, Any], **more: Any) -> dict[str, Any]:
    return {"complete": True, "tutorials": list(tutorials), "skipped": [], "not_run": [], "more": 0, **more}


class TestWhatTheTutorialsSayToAReader:
    def test_nothing_is_said_before_there_is_an_environment_to_run_them_in(self) -> None:
        assert authoring.tutorial_findings(None, False) == []

    def test_when_they_were_not_run_in_a_built_environment_it_is_said(self) -> None:
        [found] = authoring.tutorial_findings(None, True)

        assert (found["id"], found["severity"]) == ("tutorials_not_run", "note")

    def test_ones_that_ran_to_the_end_alike_say_nothing(self) -> None:
        assert authoring.tutorial_findings(reference(tutorial("a"), tutorial("b")), True) == []

    def test_one_that_did_not_run_to_the_end_is_a_warning_with_why_it_ended(self) -> None:
        found = authoring.tutorial_findings(
            reference(
                tutorial("a", "failed", failure={"kind": "import", "title": "A module is missing"}),
                tutorial("b", "timeout"),
            ),
            True,
        )

        assert [(item["id"], item["severity"], item["where"]) for item in found] == [
            ("tutorial:a", "warn", ["tutorials/a.ipynb"]),
            ("tutorial:b", "warn", ["tutorials/b.ipynb"]),
        ]
        assert "a module is missing" in found[0]["title"] and "timeout" in found[1]["title"]

    def test_one_that_gives_different_output_each_time_is_a_note_with_what_differed(self) -> None:
        [found] = authoring.tutorial_findings(
            reference(tutorial("a", stable=False, differs=["a printed line", "out/table.csv"]), tutorial("b")), True
        )

        assert (found["id"], found["severity"]) == ("unstable:a", "note")
        assert "a printed line, out/table.csv" in found["detail"]

    def test_one_that_did_not_run_to_the_end_is_not_also_said_to_be_unstable(self) -> None:
        found = authoring.tutorial_findings(reference(tutorial("a", "failed", stable=False)), True)

        assert [item["id"] for item in found] == ["tutorial:a"]

    def test_one_whose_stability_was_not_looked_at_is_not_said_to_be_unstable(self) -> None:
        assert authoring.tutorial_findings(reference(tutorial("a", stable=None)), True) == []

    def test_what_was_skipped_or_left_out_is_said(self) -> None:
        found = authoring.tutorial_findings(
            reference(
                tutorial("a"),
                skipped=[{"path": "plots.R", "kind": "r", "reason": "R"}],
                not_run=[{"path": "late.ipynb", "reason": "limit"}],
                more=3,
            ),
            True,
        )

        assert [item["id"] for item in found] == ["tutorials_skipped", "tutorials_not_all_run"]
        assert found[0]["title"].startswith("1 examples") and "plots.R" in found[0]["detail"]
        assert "4 were left out" in found[1]["detail"] and found[1]["where"] == ["late.ipynb"]

    def test_what_was_left_out_is_said_whether_it_is_named_or_only_counted(self) -> None:
        [named] = authoring.tutorial_findings(reference(not_run=[{"path": "late.ipynb", "reason": "limit"}]), True)
        [counted] = authoring.tutorial_findings(reference(more=5), True)

        assert named["id"] == counted["id"] == "tutorials_not_all_run"
        assert "1 were left out" in named["detail"] and "5 were left out" in counted["detail"]

    def test_a_run_that_did_not_come_to_its_end_is_said(self) -> None:
        [found] = authoring.tutorial_findings(reference(tutorial("a"), complete=False), True)

        assert found["id"] == "tutorials_stopped"

    def test_a_run_that_goes_on_is_said_for_what_is_kept_of_it(self) -> None:
        [found] = authoring.tutorial_findings(reference(tutorial("a", "failed"), complete=False), True, running=True)

        assert found["id"] == "tutorials_running" and found["severity"] == "note" and found["fix"] is None

    def test_only_so_many_are_named_and_what_they_print_does_not_run_on(self) -> None:
        many = [tutorial(f"t{number}", "failed") for number in range(authoring.MAX_EACH + 5)]
        found = authoring.tutorial_findings(reference(*many), True)

        assert len(found) == authoring.MAX_EACH
        shaky = [tutorial(f"u{number}", stable=False) for number in range(authoring.MAX_EACH + 5)]
        assert len(authoring.tutorial_findings(reference(*shaky), True)) == authoring.MAX_EACH
        [long] = authoring.tutorial_findings(reference(tutorial("x", "failed", path="a" * 400 + ".ipynb")), True)
        assert len(long["title"]) < 200


def dataset(name: str, accession: str = "", candidate: str | None = None) -> dict[str, Any]:
    return {"key": name, "name": name, "accession": accession, "quote": f"We used {name}.", "candidate": candidate}


def place(key: str, supported: bool = True, facts: int = 1) -> dict[str, Any]:
    return {
        "key": key,
        "label": f"Label of {key}",
        "url": f"https://example.org/{key}",
        "supported": supported,
        "reason": None if supported else "Not fetched from here.",
        "facts": [{"id": "f"}] * facts,
        "in_code": False,
    }


class TestWhatTheDataSaysToAReader:
    def test_nothing_is_said_when_the_data_is_given_a_place(self) -> None:
        data = {"datasets": [dataset("A", "GSE1"), dataset("B", "", "zenodo:1")], "candidates": [place("zenodo:1")]}

        assert authoring.data_findings(data, True) == []

    def test_a_paper_that_was_not_read_says_so_and_nothing_more(self) -> None:
        [found] = authoring.data_findings({"datasets": [], "candidates": []}, False)

        assert (found["id"], found["severity"]) == ("data_unread", "note")

    def test_a_dataset_with_no_place_is_a_warning_that_has_what_the_paper_said(self) -> None:
        [found] = authoring.data_findings({"datasets": [dataset("The lost set")], "candidates": []}, True)

        assert (found["id"], found["severity"], found["area"]) == ("dataset:The lost set", "warn", "data")
        assert "We used The lost set." in found["detail"]

    def test_a_place_that_is_not_fetched_from_here_is_a_note_and_one_nothing_points_to_is_not_said(self) -> None:
        data = {
            "datasets": [],
            "candidates": [place("odd", supported=False), place("odd2", supported=False, facts=0), place("fine")],
        }
        [found] = authoring.data_findings(data, True)

        assert (found["id"], found["severity"]) == ("place:odd", "note")
        assert found["where"] == ["https://example.org/odd"] and "Not fetched" in found["detail"]

    def test_only_so_many_are_listed(self) -> None:
        data = {"datasets": [dataset(f"d{number}") for number in range(60)], "candidates": []}

        assert len(authoring.data_findings(data, True)) == authoring.MAX_EACH

    def test_the_datasets_and_the_places_together_are_limited_too(self) -> None:
        data = {
            "datasets": [dataset(f"d{number}") for number in range(60)],
            "candidates": [place(f"p{number}", supported=False) for number in range(60)],
        }

        assert len(authoring.data_findings(data, True)) == authoring.MAX_EACH * 2


def claim(name: str, status: str) -> dict[str, Any]:
    return {"id": name, "value": f"{name}%", "quote": f"The value is {name}%.", "status": status}


class TestWhatTheNumbersSayToAReader:
    def test_the_ones_that_were_found_again_and_the_ones_not_tried_say_nothing(self) -> None:
        entries = [claim("a", "reproduced"), claim("b", "not_attempted"), claim("c", "stale")]

        assert authoring.claim_findings(entries) == []

    def test_a_number_that_was_not_found_is_a_warning_and_one_found_in_part_is_a_note(self) -> None:
        found = authoring.claim_findings([claim("a", "not_reproduced"), claim("b", "partly")])

        assert [(item["id"], item["severity"], item["area"]) for item in found] == [
            ("claim:a", "warn", "claims"),
            ("claim:b", "note", "claims"),
        ]
        assert "a%" in found[0]["title"] and "The value is a%." in found[0]["detail"]

    def test_only_so_many_are_listed(self) -> None:
        entries = [claim(f"c{number}", "not_reproduced") for number in range(100)]

        assert len(authoring.claim_findings(entries)) == authoring.MAX_EACH * 2


def finding(severity: str, area: str = "code", name: str = "x") -> dict[str, Any]:
    return authoring.finding(name, area, severity, name, "detail")


class TestWhereTheProjectStands:
    def test_the_worst_thing_comes_first_and_then_by_where_in_the_reader_s_path_it_is(self) -> None:
        found = authoring.ordered(
            [
                finding("note", "data", "a"),
                finding("warn", "claims", "b"),
                finding("block", "examples", "c"),
                finding("warn", "environment", "d"),
                finding("block", "code", "e"),
            ]
        )

        assert [item["id"] for item in found] == ["e", "c", "d", "b", "a"]

    def test_without_code_nothing_is_known(self) -> None:
        verdict, said = authoring.verdict_of([], False, 3)

        assert verdict == "not_checked" and "not been fetched" in said

    def test_a_thing_that_would_stop_a_reader_blocks(self) -> None:
        verdict, said = authoring.verdict_of([finding("block"), finding("warn"), finding("warn")], True)

        assert verdict == "blocked" and said == "1 thing would stop a reader, and 2 more may."
        assert authoring.verdict_of([finding("block")] * 2, True)[1] == "2 things would stop a reader, and 0 more may."

    def test_a_thing_that_may_is_to_fix(self) -> None:
        assert authoring.verdict_of([finding("warn"), finding("note")], True) == (
            "to_fix",
            "1 thing a reader will probably meet.",
        )
        assert authoring.verdict_of([finding("warn")] * 2, True)[1] == "2 things a reader will probably meet."

    def test_nothing_found_with_steps_not_run_is_not_ready(self) -> None:
        assert authoring.verdict_of([finding("note")], True, 1) == (
            "unfinished",
            "Nothing was found in what was looked at, and 1 step has not been run.",
        )
        assert authoring.verdict_of([], True, 2)[1].endswith("2 steps have not been run.")

    def test_nothing_found_with_every_step_run_is_ready(self) -> None:
        verdict, said = authoring.verdict_of([finding("note")], True, 0)

        assert verdict == "ready" and said == "Nothing that was looked at stands in a reader's way."

    def test_each_verdict_is_one_that_is_listed(self) -> None:
        said = {
            authoring.verdict_of([], False)[0],
            authoring.verdict_of([finding("block")], True)[0],
            authoring.verdict_of([finding("warn")], True)[0],
            authoring.verdict_of([], True, 1)[0],
            authoring.verdict_of([], True)[0],
        }

        assert said == set(authoring.VERDICTS)


class TestWhatWasNotLookedAt:
    def steps(self, **done: bool) -> dict[str, bool]:
        return {"read": False, "code": False, "environment": False, "tutorials": False, "claims": False, **done}

    def test_the_first_step_that_was_not_run_is_said_with_how_to_run_it(self) -> None:
        found = authoring.not_checked(self.steps(read=True, code=True), "abc")

        assert found == [
            {
                "id": "environment",
                "title": "The environment was not built",
                "how": "POST /api/paperagents/abc/environment",
            }
        ]

    def test_the_paper_and_the_code_are_each_said_and_the_rest_wait_for_the_code(self) -> None:
        assert [item["id"] for item in authoring.not_checked(self.steps(), "abc")] == ["reading", "repository"]

    def test_each_step_after_the_code_follows_the_one_before(self) -> None:
        done = {"read": True, "code": True}
        order = ("environment", "tutorials", "claims")
        for number, expected in enumerate(("environment", "reference", "reproduction")):
            steps = self.steps(**done, **{name: True for name in order[:number]})
            assert [item["id"] for item in authoring.not_checked(steps, "x")] == [expected]

    def test_the_numbers_are_not_to_be_tried_of_a_paper_that_was_not_read(self) -> None:
        steps = self.steps(code=True, environment=True, tutorials=True)

        assert [item["id"] for item in authoring.not_checked(steps, "x")] == ["reading"]

    def test_everything_run_leaves_nothing(self) -> None:
        every = {"read": True, "code": True, "environment": True, "tutorials": True, "claims": True}

        assert authoring.not_checked(every, "x") == []


def facts(**more: Any) -> dict[str, Any]:
    return {
        "title": "CellMapper | maps cells",
        "doi": "10.1000/xyz",
        "url": None,
        "made_at": "2026-01-02T03:04:05Z",
        "code": {"url": "https://github.com/example/cellmapper", "commit": "a" * 40, "ref": "main"},
        "license": {"name": "MIT", "kind": "permissive"},
        "environment": {
            "kind": "conda",
            "python": "3.11",
            "base_image": "python:3.11-slim",
            "lock": {"name": "pip-freeze.txt", "packages": 42, "sha256": "b" * 64},
            "pip_check": True,
        },
        "tutorials": {"ran": 3, "ok": 2, "failed": 1, "unstable": 1},
        "claims": {
            "counts": {"reproduced": 1, "partly": 0, "not_reproduced": 1, "not_attempted": 2},
            "rows": [
                {"value": "91%", "status": "reproduced", "quote": "Accuracy | was 91%."},
                {"value": "3x", "status": "not_reproduced", "quote": "It is 3x\nfaster."},
            ],
        },
        "datasets": [{"name": "Atlas", "accession": "GSE1", "place": None}],
        "places": [{"label": "Zenodo", "url": "https://zenodo.org/records/1"}],
        "tools": [{"name": "map_cells", "tier": "A"}],
        "package": {"file": "cellmapper-aaaaaaa.zip", "bytes": 12345, "sha256": "c" * 64},
        "findings": {"block": 1, "warn": 2, "note": 3},
        "top": [{"severity": "block", "title": "The environment does not build"}],
        **more,
    }


def nothing() -> dict[str, Any]:
    return facts(
        code=None,
        license={"name": None, "kind": None},
        environment=None,
        tutorials=None,
        claims=None,
        datasets=[],
        places=[],
        tools=[],
        package=None,
        doi=None,
        findings={"block": 0, "warn": 0, "note": 0},
        top=[],
    )


class TestTheCard:
    def test_it_says_what_was_found_by_section(self) -> None:
        card = authoring.card_of(facts())

        assert card.startswith("# Reproducibility card: CellMapper / maps cells\n")
        for heading in (
            "Paper and code",
            "Environment",
            "Tutorials",
            "The paper's numbers",
            "Data",
            "Tools",
            "Package",
        ):
            assert f"\n## {heading}\n" in card
        assert "made on 2026-01-02" in card and "DOI 10.1000/xyz" in card
        assert f"at commit `{'a' * 40}` (main)" in card and "License: MIT (permissive)" in card
        assert "conda on Python 3.11 from `python:3.11-slim`" in card
        assert f"42 packages, in `pip-freeze.txt` (sha256 `{'b' * 16}`)" in card and "`pip check`: clean" in card
        assert "3 run in the environment with no network" in card and "2 to the end, 1 not; 1 gave" in card
        assert "1 reproduced, 0 partly, 1 not reproduced, 2 not attempted" in card
        assert (
            "| 91% | reproduced | Accuracy / was 91%. |" in card
            and "| 3x | not reproduced | It is 3x faster. |" in card
        )
        assert "- Atlas: GSE1" in card and "- Zenodo: https://zenodo.org/records/1" in card
        assert "| map_cells | A |" in card and "not that what it gives is right" in card
        assert f"`cellmapper-aaaaaaa.zip` (12,345 bytes, sha256 `{'c' * 16}`)" in card
        assert "1 would stop them, 2 may, 3 to know" in card and "  - block: The environment does not build" in card

    def test_a_table_cannot_be_broken_by_what_the_paper_says(self) -> None:
        card = authoring.card_of(
            facts(claims={"counts": {}, "rows": [{"value": "a|b", "status": "partly", "quote": "x|y\n|z"}]})
        )

        rows = [line for line in card.splitlines() if line.startswith("| a")]
        assert rows == ["| a/b | partly | x/y /z |"]

    def test_what_was_not_done_is_said_so_and_not_left_out(self) -> None:
        card = authoring.card_of(nothing())

        assert "Code: not fetched, so nothing below is known." in card
        assert "Not built here, so what a reader's install would meet is not known." in card
        assert "- Not run here." in card and "- Not tried against the code." in card
        assert "The paper and the code do not say where the data is." in card
        assert "No tools were made of this code." in card and "## Package" not in card
        assert "Paper: not given" in card and "0 would stop them" in card

    def test_tutorials_that_are_being_run_are_said_to_be_and_not_to_be_unrun(self) -> None:
        card = authoring.card_of(facts(tutorials=None, tutorials_running=True))

        assert "- Being run here now" in card and "- Not run here." not in card

    def test_a_pair_of_a_license_that_is_not_known_says_so(self) -> None:
        assert "License: none was recognized" in authoring.card_of(facts(license={"name": None, "kind": None}))

    def test_what_a_reader_would_hit_is_few_and_one_line_each(self) -> None:
        top = [{"severity": "warn", "title": "line\nbreak " + "w" * 300}]
        card = authoring.card_of(facts(top=top))

        [line] = [item for item in card.splitlines() if item.startswith("  - warn")]
        assert len(line) < 160


class TestTheStatement:
    def test_it_says_where_the_code_and_the_data_and_the_software_are(self) -> None:
        said = authoring.statement_of(facts())

        assert "## Code availability" in said and "## Data availability" in said
        assert (
            f"The code is available at https://github.com/example/cellmapper (commit {'a' * 12}) under the MIT license."
            in said
        )
        assert "It was run with Python 3.11; the exact versions of its 42 packages are in pip-freeze.txt." in said
        assert "The data are available: Atlas (GSE1)." in said
        assert "[" not in said

    def test_what_is_not_known_is_a_bracket_for_the_authors_and_is_not_made_up(self) -> None:
        said = authoring.statement_of(nothing())

        assert "[Code availability: give where the code can be had.]" in said
        assert "[Software: say the version of Python and of each package that was used.]" in said
        assert "[Data availability: give an accession or a link for each dataset" in said

    def test_a_license_that_was_not_found_is_for_the_authors_to_add(self) -> None:
        said = authoring.statement_of(facts(license={"name": None, "kind": None}))

        assert "under the [license: none was found, add one] license" in said

    def test_a_dataset_with_nowhere_is_named_for_the_authors_to_place(self) -> None:
        said = authoring.statement_of(
            facts(
                datasets=[
                    {"name": "Atlas", "accession": "", "place": "https://zenodo.org/records/1"},
                    {"name": "Lost", "accession": "", "place": None},
                ]
            )
        )

        assert "The data are available: Atlas (https://zenodo.org/records/1)." in said
        assert "[Data availability: say where Lost can be had.]" in said

    def test_places_with_no_dataset_to_go_with_them_are_the_data(self) -> None:
        said = authoring.statement_of(facts(datasets=[]))

        assert "The data are available at https://zenodo.org/records/1." in said

    def test_only_so_many_datasets_are_named(self) -> None:
        named = [{"name": f"Set{number}", "accession": f"ACC{number}", "place": None} for number in range(10)]
        lost = [{"name": f"Gone{number}", "accession": "", "place": None} for number in range(10)]

        said = authoring.statement_of(facts(datasets=named + lost))

        assert "Set5 (ACC5)" in said and "Set6" not in said
        assert "Gone5" in said and "Gone6" not in said

    def test_what_the_paper_says_is_one_line(self) -> None:
        said = authoring.statement_of(facts(datasets=[{"name": "A\n# Heading", "accession": "X|1", "place": None}]))

        assert "\n# Heading" not in said and "A # Heading (X/1)" in said
