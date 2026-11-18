"""Tests of looking, with nothing run and no model asked, at the claims that did not reproduce: that the first output of
a tutorial that parts from a number the paper states is named, in the order that it made its calls, with the outputs
before it that agreed; that what differs between what the paper says it used and what was used here is found, in the
version of Python and of a package, in data, in runs that did not agree and a seed, and in an argument; and that what is
found is said to be a difference and never a cause."""

from collections.abc import Mapping
from typing import Any

import pytest
from test_paperagents_reference import call_of
from test_paperagents_reproducing import Scripted, claim, detail_of, tutorial

from virtual_lab.paperagents import diverging, reproducing

LOCK = "numpy==1.26.4\nScanpy==1.9.3\nscikit_learn==1.4.2\ntorch==2.1.0+cpu\n# a comment\n-e git+https://x#egg=y\n"
PAPER = (
    "Methods. We clustered the cells with n_neighbors = 30 and a resolution of 0.8, and set the seed to 7 "
    "(random_state = 7). Leiden was run with scanpy 1.8 and Python 3.8. Models were trained with scikit-learn 1.4, "
    "with alpha = 5."
)


def tried(
    claims: list[dict[str, Any]], choices: dict[str, str], tutorials: list[reproducing.Tutorial]
) -> list[dict[str, Any]]:
    """The claims as the trying of them keeps them, with the place that is chosen for each sentence by its name."""
    return reproducing.reproduce(claims, tutorials, Scripted(choices)).claims


def evidence(**changes: Any) -> diverging.Evidence:
    base: dict[str, Any] = {
        "python": "3.12.1",
        "lock": LOCK,
        "software": [],
        "datasets": [],
        "data": None,
        "paper": None,
        "details": {},
        "text_of": lambda path: "",
    }
    return diverging.Evidence(**{**base, **changes})


def detail_with(
    calls: list[dict[str, Any]] | None = None,
    stable: bool | None = True,
    output: list[str] | None = None,
    differs: list[str] | None = None,
) -> dict[str, Any]:
    """What was kept of a tutorial that ran to the end, with the parts in which its runs differed, which are the calls
    if they did not agree and none if they did."""
    shown = differs if differs is not None else (["calls"] if stable is False else [])

    return {**detail_of(calls, output=output, stable=stable), "differs": shown}


def details_of(*tutorials: reproducing.Tutorial) -> dict[str, Mapping[str, Any]]:
    return {each.path: each.detail for each in tutorials if each.detail is not None}


def software(name: str, version: str = "") -> dict[str, str]:
    return {"id": "sw-1", "name": name, "version": version, "quote": f"We used {name} {version}".strip()}


CALLS = [
    call_of("tally", {"counts": [1, 2], "resolution": 0.8}, 0.931, 1),
    call_of("auroc", {"method": "seurat", "n_neighbors": 15, "resolution": 0.8}, {"seurat": 0.71}, 2),
    call_of("recall", {"n_neighbors": 15, "alpha": 4}, {"recall": 0.5}, 3),
]
GOOD = "The AUC of CellMapper was 0.93 (Fig. 3)."
BAD = "Seurat reached an AUROC of 0.88 (Fig. 3)."
WORSE = "The recall of Seurat was 0.65 (Fig. 3)."


def three(stable: bool | None = True, text_calls: list[dict[str, Any]] | None = None) -> reproducing.Tutorial:
    return tutorial(detail=detail_with(text_calls or CALLS, stable=stable))


def three_entries(run: reproducing.Tutorial) -> list[dict[str, Any]]:
    claims = [claim("0.93", GOOD, "a"), claim("0.88", BAD, "b"), claim("0.65", WORSE, "c")]
    choices = {GOOD: "tally", BAD: "auroc", WORSE: "recall"}

    return tried(claims, choices, [run])


class TestWhatIsInstalled:
    def test_the_version_of_each_package_is_read_from_a_list_of_what_was_installed_however_its_name_is_written(
        self,
    ) -> None:
        found = diverging.installed_of(LOCK)
        assert found == {"numpy": "1.26.4", "scanpy": "1.9.3", "scikit-learn": "1.4.2", "torch": "2.1.0+cpu"}

    def test_the_links_of_an_explicit_list_of_conda_packages_are_read_as_well(self) -> None:
        lock = (
            "@EXPLICIT\nhttps://conda.anaconda.org/conda-forge/linux-64/numpy-1.26.4-py312h1_0.conda\n"
            "https://repo.anaconda.com/pkgs/main/noarch/scikit-learn-1.4.2-py312_0.tar.bz2\n"
        )
        assert diverging.installed_of(lock) == {"numpy": "1.26.4", "scikit-learn": "1.4.2"}

    def test_where_a_package_is_listed_twice_the_first_that_is_given_is_read(self) -> None:
        assert diverging.installed_of("numpy==1.0\nnumpy==2.0\n") == {"numpy": "1.0"}
        conda = "https://conda.anaconda.org/conda-forge/linux-64/numpy-3.0-py312_0.conda\n"
        assert diverging.installed_of(conda + "numpy==1.0\n") == {"numpy": "1.0"}

    @pytest.mark.parametrize("lock", [None, "", "no versions here"])
    def test_nothing_is_installed_if_there_is_no_list(self, lock: str | None) -> None:
        assert diverging.installed_of(lock) == {}

    @pytest.mark.parametrize(
        ("stated", "installed", "agree"),
        [
            ("1.4", "1.4.2", True),
            ("1.4.2", "1.4", False),
            ("1.4.0", "1.4", True),
            ("4.3", "5.0.1", False),
            ("v2", "2.1.0", True),
            ("3.8", "3.12.1", False),
            ("1.10", "1.1", False),
            (">=1.4", "1.5", None),
            ("1.4 or later", "1.4.2", None),
            ("", "1.4", None),
            ("1.4", "dev", None),
        ],
    )
    def test_a_version_that_a_paper_states_is_the_one_installed_as_far_as_it_states_it(
        self, stated: str, installed: str, agree: bool | None
    ) -> None:
        assert diverging.versions_agree(stated, installed) is agree

    def test_a_version_that_is_only_as_exact_as_it_is_given_is_not_held_to_more_than_it_says(self) -> None:
        assert diverging.versions_agree("3.12.1", "3.12", coarse=True) is True
        assert diverging.versions_agree("3.12.1", "3.12") is False
        assert diverging.versions_agree("3.11.4", "3.12", coarse=True) is False
        assert diverging.versions_agree("3.12", "3.12.4", coarse=True) is True

    def test_the_python_of_an_environment_is_of_its_minor_version_and_is_not_said_to_differ_by_its_patch(self) -> None:
        [found] = diverging.software_of([software("Python", "3.12.1")], {}, "3.12")
        assert found["state"] == "same"
        [found] = diverging.software_of([software("numpy", "1.26.9")], {"numpy": "1.26"}, "3.12")
        assert found["state"] == "differs"


class TestWhatThePaperSaysItUsed:
    def test_each_software_is_said_to_be_the_same_or_to_differ_or_to_be_one_that_cannot_be_compared_or_is_not_installed(
        self,
    ) -> None:
        installed = diverging.installed_of(LOCK)
        named = [
            software("scikit-learn", "1.4"),
            software("scanpy", "1.8"),
            software("Seurat", "4.3"),
            software("numpy"),
            software("torch", ">=2.0"),
            software("PyTorch", "2.1"),
            software("Python", "3.8"),
        ]
        found = diverging.software_of(named, installed, "3.12.1")
        assert {each["name"]: each["state"] for each in found} == {
            "scikit-learn": "same",
            "scanpy": "differs",
            "Seurat": "not_installed",
            "numpy": "no_version",
            "torch": "not_comparable",
            "PyTorch": "same",
            "Python": "differs",
        }
        assert next(each for each in found if each["name"] == "scanpy")["installed"] == "1.9.3"
        assert next(each for each in found if each["name"] == "Python")["installed"] == "3.12.1"

    def test_python_is_not_compared_when_the_version_it_was_built_with_is_not_known(self) -> None:
        [found] = diverging.software_of([software("Python", "3.8")], {}, None)
        assert (found["state"], found["installed"]) == ("not_installed", None)

    def test_only_a_version_that_differs_is_a_difference_and_it_says_which_and_that_it_is_not_a_cause(self) -> None:
        installed = diverging.installed_of(LOCK)
        named = [
            software("scanpy", "1.8"),
            software("Python", "3.8"),
            software("numpy", "1.26"),
            software("Seurat", "4"),
        ]
        found = diverging.software_differences(diverging.software_of(named, installed, "3.12.1"))
        assert [(each["kind"], each["evidence"]["name"]) for each in found] == [
            ("package", "scanpy"),
            ("python", "Python"),
        ]
        assert found[0]["text"] == "The paper names scanpy 1.8, and 1.9.3 is installed here."
        assert found[0]["quote"] == "We used scanpy 1.8"
        assert "cause" not in found[0]["text"] and "because" not in found[0]["text"]

    def test_data_that_the_paper_names_and_none_was_given_is_a_difference(self) -> None:
        datasets = [
            {"name": "PBMC", "accession": "GSE1", "quote": "PBMC (GSE1)"},
            {"name": "Atlas", "accession": "", "quote": "the Atlas"},
            {"name": "Liver", "accession": "GSE3", "quote": "Liver"},
            {"name": "Lung", "accession": "GSE4", "quote": "Lung"},
        ]
        [found] = diverging.data_differences(None, datasets)
        assert found["kind"] == "data" and found["quote"] == "PBMC (GSE1)"
        assert found["evidence"] == {"names": ["GSE1", "Atlas", "GSE3"], "named": 4, "given": None}
        assert "GSE1, Atlas, GSE3, and 1 more" in found["text"] and "none was given" in found["text"]

    def test_there_is_no_difference_of_data_if_some_was_given_or_the_paper_names_none(self) -> None:
        datasets = [{"name": "PBMC", "accession": "GSE1", "quote": "PBMC"}]
        assert diverging.data_differences({"files": 3, "bytes": 10}, datasets) == []
        assert diverging.data_differences(None, []) == []


class TestRunsAndSeeds:
    @pytest.mark.parametrize("stable", [True, None])
    def test_runs_that_agreed_or_could_not_be_compared_are_not_a_difference(self, stable: bool | None) -> None:
        assert diverging.runs_differences(detail_with(stable=stable), "") == []

    def test_runs_that_did_not_agree_are_a_difference_and_so_is_no_seed_set_in_the_tutorial(self) -> None:
        detail = detail_with(stable=False, differs=["status", "calls"])
        found = diverging.runs_differences(detail, "import numpy as np\nprint(np.random.rand())\n")
        assert [each["kind"] for each in found] == ["runs", "seed"]
        assert found[0]["text"] == "The 2 runs of the tutorial did not give the same calls."
        assert found[0]["evidence"] == {"runs": 2, "differs": ["status", "calls"]}
        assert "though what it calls may" in found[1]["text"]

    @pytest.mark.parametrize(
        "text",
        [
            "np.random.seed(0)",
            "import random\nrandom.seed(3)",
            "torch.manual_seed(1)",
            "set_seed(5)",
            "KMeans(random_state=0)",
            "rng = np.random.default_rng(2)",
            "sc.tl.leiden(adata, seed=1)",
            "pl.seed_everything(9)",
        ],
    )
    def test_a_seed_that_the_tutorial_sets_is_no_difference_of_seed(self, text: str) -> None:
        found = diverging.runs_differences(detail_with(stable=False), text)
        assert [each["kind"] for each in found] == ["runs"]

    def test_the_words_of_a_seed_that_are_part_of_another_word_are_not_a_seed(self) -> None:
        text = "seedling = 1\nreseed_later = 2\n# seeded"
        found = diverging.runs_differences(detail_with(stable=False, differs=["files"]), text)
        assert [each["kind"] for each in found] == ["runs", "seed"]


class TestWhatThePaperSaysOfAnArgument:
    @pytest.mark.parametrize(
        ("name", "text", "numbers"),
        [
            ("n_neighbors", "with n_neighbors = 30 and more", [30.0]),
            ("n_neighbors", "with n neighbors = 30", [30.0]),
            ("n_neighbors", "n-neighbors: 15, then n_neighbors of 20", [15.0, 20.0]),
            ("resolution", "a resolution of 0.8.", [0.8]),
            ("resolution", "the resolution was 1,000 here", [1000.0]),
            ("resolution", "resolution set to -2", [-2.0]),
            ("resolution", "the resolution matters", []),
            ("resolution", "resolutions = 3", []),
            ("resolution", "subresolution = 3", []),
            ("resolution", "resolution = three", []),
        ],
    )
    def test_the_number_is_found_where_the_paper_gives_it_for_the_argument_by_name(
        self, name: str, text: str, numbers: list[float]
    ) -> None:
        assert [number for number, _ in diverging.stated_for(name, text)] == numbers

    def test_the_words_round_the_number_are_kept_with_it(self) -> None:
        [(number, quote)] = diverging.stated_for(
            "resolution", "x" * 200 + " the resolution of 0.8 was used " + "y" * 200
        )
        assert number == 0.8 and "resolution of 0.8 was used" in quote and len(quote) < 160

    def test_an_argument_that_was_given_another_number_than_the_paper_gives_is_a_difference(self) -> None:
        run = three()
        found = diverging.argument_differences(run.detail or {}, None, PAPER)
        assert [(each["evidence"]["name"], each["evidence"]["call"]) for each in found] == [
            ("n_neighbors", 2),
            ("alpha", 3),
        ]
        one = found[0]
        assert one["text"] == "The paper gives n_neighbors as 30, and the call of auroc was given 15."
        assert one["evidence"]["paper"] == [30.0] and one["evidence"]["gave"] == 15.0
        assert one["evidence"]["function"] == "fixture.core.auroc" and "n_neighbors = 30" in one["quote"]

    def test_an_argument_that_was_given_what_the_paper_gives_is_not_one(self) -> None:
        found = diverging.argument_differences(three().detail or {}, None, PAPER)
        assert "resolution" not in [each["evidence"]["name"] for each in found]

    def test_an_argument_that_the_paper_gives_two_numbers_for_is_one_only_if_the_call_was_given_neither(self) -> None:
        detail = detail_with([call_of("run", {"alpha": 2}, 1.0, 1)])
        assert diverging.argument_differences(detail, None, "alpha = 2 here, and alpha = 3 there") == []
        found = diverging.argument_differences(detail, None, "alpha = 4 here, and alpha = 3 there, and alpha = 4")
        assert [each["evidence"]["paper"] for each in found] == [[4.0, 3.0]]
        assert found[0]["text"].startswith("The paper gives alpha as 4 or 3,")

    def test_only_the_calls_up_to_the_point_that_was_named_are_looked_at(self) -> None:
        detail = three().detail or {}
        assert diverging.argument_differences(detail, 1, PAPER) == []
        assert [each["evidence"]["call"] for each in diverging.argument_differences(detail, 3, PAPER)] == [2, 3]
        assert [each["evidence"]["call"] for each in diverging.argument_differences(detail, 2, PAPER)] == [2]

    def test_a_name_that_is_short_a_number_that_is_not_plain_and_a_paper_that_is_not_kept_are_not_looked_at(
        self,
    ) -> None:
        call = call_of("run", {"k": 4, "flag": True, "rows": [1, 2], "name": "x"}, 1.0, 1)
        call["args"]["big"] = {"type": "DataFrame", "plain": False}
        detail = detail_with([call])
        paper = "k = 3, flag = 0, rows = 5, name = 1, big = 7"
        assert diverging.argument_differences(detail, None, paper) == []
        assert diverging.argument_differences(three().detail or {}, None, None) == []
        assert diverging.argument_differences(three().detail or {}, None, "") == []

    def test_a_number_that_is_kept_for_what_was_not_given_as_one_is_not_a_number_that_the_call_was_given(self) -> None:
        call = call_of("run", {"alpha": 2}, 1.0, 1)
        call["args"]["alpha"] = {"type": "float", "plain": False, "value": 2.0}
        assert diverging.plain_numbers(call) == {}
        assert diverging.argument_differences(detail_with([call]), None, "alpha = 3") == []

    def test_only_the_first_of_the_calls_are_looked_at_for_what_the_paper_says_of_their_arguments(self) -> None:
        filler = [call_of("run", {"alpha": 5}, 1.0, number) for number in range(1, diverging.MOST_CALLS)]
        last = call_of("run", {"alpha": 6}, 1.0, diverging.MOST_CALLS)
        past = call_of("run", {"alpha": 7}, 1.0, diverging.MOST_CALLS + 1)
        found = diverging.argument_differences(detail_with([*filler, last, past]), None, "alpha = 5")
        assert [each["evidence"]["call"] for each in found] == [diverging.MOST_CALLS]

    def test_only_the_first_of_the_numbers_that_the_paper_gives_for_an_argument_are_named(self) -> None:
        detail = detail_with([call_of("run", {"alpha": 9}, 1.0, 1)])
        found = diverging.argument_differences(detail, None, "alpha = 1, alpha = 2, alpha = 3, alpha = 4")
        assert found[0]["evidence"]["paper"] == [1.0, 2.0, 3.0] and found[0]["text"].startswith(
            "The paper gives alpha as 1 or 2 or 3,"
        )

    def test_a_call_that_did_not_return_is_not_looked_at(self) -> None:
        call = {**call_of("run", {"alpha": 2}, 1.0, 1), "returned": False}
        assert diverging.argument_differences(detail_with([call]), None, "alpha = 3") == []

    def test_what_a_call_was_given_that_is_a_number_in_a_list_or_a_word_is_not_a_number(self) -> None:
        call = call_of("run", {"alpha": 2, "beta": [1, 2], "gamma": "3"}, 1.0, 1)
        assert diverging.plain_numbers(call) == {"alpha": 2.0}


class TestWhereATutorialFirstParts:
    def test_the_first_output_that_parts_is_named_with_the_one_before_it_that_agreed(self) -> None:
        entries = three_entries(three())
        assert [each["status"] for each in entries] == ["reproduced", "not_reproduced", "not_reproduced"]
        [point] = diverging.points_of(entries).values()
        assert point["ordered"] is True and point["agreed_count"] == 1
        assert (point["first"]["got"], point["first"]["number"], point["first"]["call"]) == (0.71, "0.88", 2)
        assert [(each["got"], each["number"]) for each in point["agreed"]] == [(0.931, "0.93")]

    def test_a_claim_that_comes_after_it_has_the_same_point_and_one_before_it_has_none(self) -> None:
        run = three()
        done = diverging.diverge(three_entries(run), evidence(details=details_of(run)))
        assert [each["quote"] for each in done.claims] == [BAD, WORSE]
        assert done.claims[0]["point"] == done.claims[1]["point"]
        first = done.claims[0]["point"]["first"]
        assert first["claim"] == "claim-b" and first["quote"] == BAD

    def test_it_is_said_in_words_with_where_it_is_and_what_was_given_and_what_the_paper_says(self) -> None:
        run = three()
        done = diverging.diverge(three_entries(run), evidence(details=details_of(run)))
        text = done.claims[0]["point"]["text"]
        assert text.startswith(
            "In examples/figure3.py, the first output, in the order that it made its calls, that parts"
        )
        assert "a call of fixture.core.auroc(" in text and "it gave 0.71, and the paper reports 0.88." in text
        assert "1 output before it agreed with the paper, the last a call of fixture.core.tally(" in text
        assert "which gave 0.931 for the paper's 0.93." in text

    def test_when_the_first_call_that_was_held_to_a_number_is_the_one_that_parts_nothing_before_it_is_said_to_agree(
        self,
    ) -> None:
        run = three()
        claims = [claim("0.88", BAD, "b"), claim("0.65", WORSE, "c")]
        entries = tried(claims, {BAD: "auroc", WORSE: "recall"}, [run])
        [point] = diverging.points_of(entries).values()
        assert point["agreed"] == [] and point["agreed_count"] == 0 and point["first"]["call"] == 2
        assert "No output of the tutorial before it was held to a number of the paper." in diverging.point_text(
            "t.py", point
        )

    def test_only_the_last_of_the_outputs_that_agreed_are_named_and_all_of_them_are_counted(self) -> None:
        values = ["0.411", "0.522", "0.633", "0.744", "0.855", "0.966", "0.377", "0.288"]
        many = [call_of("tally", {"n": number}, float(value), number) for number, value in enumerate(values, 1)]
        many.append(call_of("auroc", {}, {"seurat": 0.99}, 9))
        run = tutorial(detail=detail_with(many))
        claims = [
            claim(value, f"Tally {number} was {value} (Fig. 3).", f"t{number}")
            for number, value in enumerate(values, 1)
        ]
        claims.append(claim("0.88", BAD, "z"))
        choices = {
            f"Tally {number} was {value} (Fig. 3).": f"tally(n={number})" for number, value in enumerate(values, 1)
        }
        entries = tried(claims, {**choices, BAD: "auroc"}, [run])
        [point] = diverging.points_of(entries).values()
        assert point["agreed_count"] == 8 and len(point["agreed"]) == diverging.MOST_AGREED
        assert [each["call"] for each in point["agreed"]] == [4, 5, 6, 7, 8]

    def test_the_order_is_that_of_the_calls_and_not_of_the_claims(self) -> None:
        claims = [claim("0.65", WORSE, "c"), claim("0.88", BAD, "b"), claim("0.93", GOOD, "a")]
        entries = tried(claims, {GOOD: "tally", BAD: "auroc", WORSE: "recall"}, [three()])
        [point] = diverging.points_of(entries).values()
        assert point["ordered"] is True and point["first"]["claim"] == "claim-b" and point["first"]["call"] == 2
        assert point["agreed_count"] == 1 and point["agreed"][0]["claim"] == "claim-a"

    def test_only_a_claim_that_was_tried_and_got_a_number_that_does_not_round_to_the_paper_s_parts(self) -> None:
        run = three()
        reproduced, far, _ = three_entries(run)
        assert diverging.parts(far) is True
        assert diverging.parts({**far, "status": "partly"}) is True
        assert diverging.parts({**far, "status": "reproduced"}) is False
        assert diverging.parts({**far, "status": "not_attempted"}) is False
        assert diverging.parts({**far, "link": None}) is False
        assert diverging.parts({**far, "value": "high"}) is False
        assert diverging.parts({**far, "value": "0.71"}) is False
        assert diverging.parts(reproduced) is False

    def test_a_number_that_rounds_to_the_paper_s_in_a_run_that_did_not_agree_does_not_part_from_it(self) -> None:
        run = tutorial(detail=detail_with([call_of("tally", {}, 0.931, 1)], stable=False))
        entries = tried([claim("0.93", GOOD)], {GOOD: "tally"}, [run])
        assert entries[0]["status"] == "partly" and diverging.parts(entries[0]) is False
        assert diverging.points_of(entries) == {}

    def test_a_number_that_is_near_the_paper_s_and_not_what_it_rounds_from_parts_from_it(self) -> None:
        run = tutorial(detail=detail_with([call_of("tally", {}, 0.94, 1)]))
        entries = tried([claim("0.93", GOOD)], {GOOD: "tally"}, [run])
        assert entries[0]["status"] == "partly" and diverging.parts(entries[0]) is True
        assert [each["first"]["got"] for each in diverging.points_of(entries).values()] == [0.94]

    def test_a_claim_that_is_reproduced_or_not_attempted_has_no_point_and_is_not_listed(self) -> None:
        run = three()
        claims = [
            claim("0.93", GOOD, "a"),
            claim("0.31", "A figure of 0.31 (Fig. 9).", "n"),
            claim("", "Words.", "w", "qualitative"),
        ]
        entries = tried(claims, {GOOD: "tally"}, [run])
        assert [each["status"] for each in entries] == ["reproduced", "not_attempted", "not_attempted"]
        assert diverging.points_of(entries) == {}
        assert diverging.diverge(entries, evidence(details=details_of(run))).claims == []

    def test_each_tutorial_has_its_own_first_point(self) -> None:
        first = tutorial("examples/figure3.py", detail_with([call_of("auroc", {}, {"seurat": 0.71}, 5)]))
        second = tutorial(
            "examples/figure4.py", detail_with([call_of("recall", {}, {"recall": 0.5}, 1)]), ("figure 3",)
        )
        entries = tried(
            [claim("0.88", BAD, "b"), claim("0.65", WORSE, "c")], {BAD: "auroc", WORSE: "recall"}, [first, second]
        )
        points = diverging.points_of(entries)
        assert {path: point["first"]["call"] for path, point in points.items()} == {
            "examples/figure3.py": 5,
            "examples/figure4.py": 1,
        }

    def test_a_place_in_a_line_that_was_printed_has_no_known_order_and_comes_after_the_calls(self) -> None:
        run = tutorial(
            detail=detail_with(
                [call_of("tally", {}, 0.931, 1), call_of("auroc", {}, {"seurat": 0.71}, 2)],
                output=["Seurat AUROC was 0.77", "done"],
            )
        )
        printed = "The AUROC of Seurat printed was 0.88 (Fig. 3)."
        claims = [claim("0.88", printed, "line"), claim("0.93", GOOD, "a"), claim("0.88", BAD, "b")]
        entries = tried(claims, {printed: "printed line", GOOD: "tally", BAD: "auroc"}, [run])
        assert [each["status"] for each in entries] == ["not_reproduced", "reproduced", "not_reproduced"]
        [point] = diverging.points_of(entries).values()
        assert point["ordered"] is True and point["first"]["call"] == 2 and point["first"]["claim"] == "claim-b"
        assert point["agreed_count"] == 1

    def test_when_only_a_line_that_was_printed_parts_the_point_says_that_its_order_is_not_known(self) -> None:
        run = tutorial(detail=detail_with([call_of("tally", {}, 0.931, 1)], output=["Seurat AUROC was 0.77"]))
        claims = [claim("0.93", GOOD, "a"), claim("0.88", "AUROC of Seurat was 0.88 (Fig. 3).", "line")]
        entries = tried(claims, {GOOD: "tally", claims[1]["quote"]: "printed line"}, [run])
        [point] = diverging.points_of(entries).values()
        assert point["ordered"] is False and point["first"]["call"] is None
        text = diverging.point_text("t.py", point)
        assert "whose order among its calls is not known" in text and "a printed line" in text


class TestPuttingItTogether:
    def test_a_claim_that_did_not_reproduce_is_listed_with_its_point_and_the_differences_that_were_found(self) -> None:
        run = three(stable=False)
        found = diverging.diverge(
            three_entries(run),
            evidence(
                details=details_of(run),
                paper=PAPER,
                software=[software("scanpy", "1.8"), software("Python", "3.8")],
                datasets=[{"name": "PBMC", "accession": "GSE1", "quote": "PBMC"}],
                text_of=lambda path: "import numpy as np\n",
            ),
        )
        assert [each["id"] for each in found.claims] == ["claim-a", "claim-b", "claim-c"]
        assert found.claims[0]["point"] is None and found.claims[1]["point"] is not None
        assert [each["kind"] for each in found.claims[0]["differences"]] == ["runs", "seed"]
        assert [each["kind"] for each in found.claims[1]["differences"]] == ["runs", "seed", "argument"]
        assert [each["kind"] for each in found.differences] == ["package", "python", "data"]
        assert [each["state"] for each in found.software] == ["differs", "differs"]
        assert diverging.counts_of(found.differences) == {
            "python": 1,
            "package": 1,
            "data": 1,
            "runs": 0,
            "seed": 0,
            "argument": 0,
        }

    def test_the_arguments_that_are_looked_at_are_those_of_the_calls_up_to_the_point_of_the_claim(self) -> None:
        run = three()
        found = diverging.diverge(three_entries(run), evidence(details=details_of(run), paper=PAPER))
        # The call of the third claim has an argument that the paper gives another number for, which is after the point
        assert [each["evidence"]["call"] for each in found.claims[0]["differences"]] == [2]
        assert [each["evidence"]["call"] for each in found.claims[1]["differences"]] == [2]

    def test_the_paper_is_read_once_for_a_name_however_many_claims_come_to_the_same_arguments(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        read: list[str] = []
        original = diverging.stated_for

        def counting(name: str, paper: str) -> list[tuple[float, str]]:
            read.append(name)
            return original(name, paper)

        monkeypatch.setattr(diverging, "stated_for", counting)
        run = three()
        found = diverging.diverge(three_entries(run), evidence(details=details_of(run), paper=PAPER))

        assert len(found.claims) == 2 and found.claims[0]["differences"] == found.claims[1]["differences"] != []
        assert read and len(read) == len(set(read))

    def test_the_paper_is_read_once_for_a_name_that_two_tutorials_are_both_given(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        read: list[str] = []
        original = diverging.stated_for
        monkeypatch.setattr(diverging, "stated_for", lambda name, paper: read.append(name) or original(name, paper))
        first = tutorial("examples/figure3.py", detail_with([call_of("auroc", {"alpha": 4}, {"seurat": 0.71}, 1)]))
        second = tutorial(
            "examples/figure4.py", detail_with([call_of("recall", {"alpha": 4}, {"recall": 0.5}, 1)]), ("figure 3",)
        )
        entries = tried(
            [claim("0.88", BAD, "b"), claim("0.65", WORSE, "c")], {BAD: "auroc", WORSE: "recall"}, [first, second]
        )

        found = diverging.diverge(entries, evidence(details=details_of(first, second), paper=PAPER))

        assert [len(claim["differences"]) for claim in found.claims] == [1, 1]
        assert read == ["alpha"]

    def test_the_arguments_of_a_tutorial_are_looked_at_once_for_the_claims_that_come_to_the_same_point(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        looked: list[tuple[int | None]] = []
        original = diverging.argument_differences
        monkeypatch.setattr(
            diverging,
            "argument_differences",
            lambda detail, until, *rest: looked.append((until,)) or original(detail, until, *rest),
        )
        run = three()

        diverging.diverge(three_entries(run), evidence(details=details_of(run), paper=PAPER))

        assert looked == [(2,)]

    def test_what_is_found_for_one_claim_is_not_the_same_object_as_what_is_found_for_another(self) -> None:
        run = three()
        found = diverging.diverge(three_entries(run), evidence(details=details_of(run), paper=PAPER))
        first, second = (claim["differences"][0] for claim in found.claims)
        assert first == second and first is not second and first["evidence"] is not second["evidence"]

    def test_a_claim_that_is_partly_for_runs_that_did_not_agree_has_the_runs_and_no_point(self) -> None:
        run = tutorial(detail=detail_with([call_of("tally", {}, 0.931, 1)], stable=False))
        entries = tried([claim("0.93", GOOD)], {GOOD: "tally"}, [run])
        found = diverging.diverge(entries, evidence(details=details_of(run)))
        [one] = found.claims
        assert one["status"] == "partly" and one["point"] is None
        assert [each["kind"] for each in one["differences"]] == ["runs", "seed"]

    def test_a_tutorial_whose_run_is_not_kept_is_looked_at_for_its_point_and_for_nothing_else(self) -> None:
        run = three()
        found = diverging.diverge(three_entries(run), evidence(details={}, paper=PAPER))
        assert found.claims[0]["point"] is not None and found.claims[0]["differences"] == []

    def test_nothing_that_is_said_is_a_cause(self) -> None:
        run = three(stable=False)
        found = diverging.diverge(
            three_entries(run),
            evidence(details=details_of(run), paper=PAPER, software=[software("scanpy", "1.8")]),
        )
        said = [each["text"] for each in found.differences]
        said += [each["text"] for each in found.claims[0]["differences"]]
        said += [found.claims[1]["point"]["text"]]
        assert said and not any(
            word in text.lower() for text in said for word in ("because", "caused", "due to", "the reason")
        )
        assert "not a cause" in diverging.MEANING

    def test_a_trying_that_has_none_to_look_at_says_nothing(self) -> None:
        found = diverging.diverge([], evidence())
        assert (found.claims, found.software, found.differences) == ([], [], [])

    def test_the_numbers_a_difference_is_made_of_are_in_what_it_says(self) -> None:
        found = diverging.diverge(
            [],
            evidence(software=[software("numpy", "1.20")], datasets=[]),
        )
        assert [each["text"] for each in found.differences] == [
            "The paper names numpy 1.20, and 1.26.4 is installed here."
        ]

    def test_a_tutorial_that_is_all_that_is_said_of_is_looked_at_by_its_path(self) -> None:
        first = tutorial("a/one.py", detail_with([call_of("auroc", {"resolution": 5.0}, {"seurat": 0.71}, 1)]))
        second = tutorial("b/two.py", detail_with([call_of("auroc", {"resolution": 0.8}, {"seurat": 0.71}, 1)]))
        claims = [claim("0.88", BAD, "b")]
        paper = "resolution of 0.8"
        entries = tried(claims, {BAD: "a/one.py: a call"}, [first, second])
        found = diverging.diverge(entries, evidence(details=details_of(first, second), paper=paper))
        assert found.claims[0]["tutorial"] == "a/one.py"
        assert [each["evidence"]["gave"] for each in found.claims[0]["differences"]] == [5.0]
