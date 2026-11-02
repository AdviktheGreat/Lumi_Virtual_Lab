"""Tests for the BixBench-Verified-50 questions, capsules, answers, and grading."""

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from conftest import TEST_MODEL, FakeClient, text_response

from virtual_lab import bixbench
from virtual_lab.bixbench import (
    LENIENT,
    LENIENT_GRADING_PROMPT,
    OFFICIAL,
    OPEN_ENDED_GRADING_PROMPT,
    OPEN_ENDED_RANGE_GRADING_PROMPT,
    BixBenchError,
    BixQuestion,
    ModelJudge,
    choose_questions,
    describe_files,
    download_bixbench,
    final_answer,
    grade_answer,
    grade_lenient,
    grade_official,
    load_questions,
    normalise_numbers,
    numbers_in,
    parse_range,
    pure_number,
    question_message,
    stage_capsule,
)


def question(ideal: str, mode: str = "str_verifier", **fields: Any) -> BixQuestion:
    return BixQuestion(
        id=fields.pop("id", "bix-1-q1"),
        question=fields.pop("question", "What is it?"),
        ideal=ideal,
        eval_mode=mode,
        capsule="uuid",
        archive="CapsuleFolder-uuid.zip",
        **fields,
    )


class RecordingJudge:
    """Stands in for the model that judges, saying what it was asked and answering as told."""

    def __init__(self, grade: str = "incorrect") -> None:
        self.grade = grade
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)

        return f"Thinking. <grade> {self.grade} </grade>"


def write_dataset(directory: Path, rows: list[dict[str, Any]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row) for row in rows]
    (directory / bixbench.QUESTIONS_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def row(question_id: str = "bix-1-q1", mode: str = "str_verifier", **fields: Any) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question": "How many genes?",
        "ideal": "42",
        "eval_mode": mode,
        "capsule_uuid": "abc",
        "data_folder": "CapsuleFolder-abc.zip",
        "categories": "RNA-seq",
        "hypothesis": "never given to the lead",
        **fields,
    }


class TestFinalAnswer:
    @pytest.mark.parametrize(
        ("reply", "answer", "source"),
        [
            ("I looked.\nFINAL ANSWER: 42", "42", "final_answer"),
            ("**FINAL ANSWER:** CDKN1A", "CDKN1A", "final_answer"),
            ("**FINAL ANSWER**: **0.73**", "0.73", "final_answer"),
            ("FINAL ANSWER: **0.73**", "0.73", "final_answer"),
            ("**FINAL ANSWER: 0.73**", "0.73", "final_answer"),
            ("**FINAL ANSWER:** **0.73**", "0.73", "final_answer"),
            ("**Final Answer:** 12 genes", "12 genes", "final_answer"),
            ("FINAL ANSWER: `TP53`", "TP53", "final_answer"),
            ("final answer: first\nmore\nFinal Answer: second", "second", "final_answer"),
            ("Done. <answer> 17.5 </answer>", "17.5", "answer_tag"),
            ("It was found.\n\nThe value is 3.2", "The value is 3.2", "last_line"),
            ("", "", "none"),
            ("  \n ", "", "none"),
        ],
    )
    def test_finds_the_answer(self, reply: str, answer: str, source: str) -> None:
        assert final_answer(reply) == (answer, source)

    def test_an_empty_final_answer_line_falls_back(self) -> None:
        assert final_answer("The result is 5.\nFINAL ANSWER: ")[1] != "final_answer"


class TestNumbers:
    @pytest.mark.parametrize(
        ("text", "numbers"),
        [
            ("1.128 × 10⁻⁷ (or 1.128256802312e-07)", [1.128e-7, 1.128256802312e-07]),
            ("1.5 x 10^-3", [1.5e-3]),
            ("2×10⁵", [2e5]),
            ("12,345 genes of 1,000,000", [12345.0, 1000000.0]),
            ("30/41 (≈ 0.7317, or 73.2%)", [30.0, 41.0, 0.7317, 73.2]),
            ("a minus sign − is a dash: −4", [-4.0]),
            ("TP53 and chr5 have 12 variants, IL-6 is up 3.2-fold", [12.0, 3.2]),
            ("R2 = 0.8, p < 1e-5", [0.8, 1e-5]),
            ("none here", []),
        ],
    )
    def test_reads_numbers_as_written(self, text: str, numbers: list[float]) -> None:
        assert numbers_in(text) == pytest.approx(numbers)

    def test_a_list_is_not_joined_into_a_number_when_the_groups_are_not_thousands(self) -> None:
        assert normalise_numbers("0.5,1.2") == "0.5,1.2"

    def test_a_range_is_read_from_either_way_it_is_written(self) -> None:
        assert parse_range("(0.74, 0.77)") == (0.74, 0.77)
        assert parse_range("(1.03E-07,1.23E-07)") == (1.03e-7, 1.23e-7)
        assert parse_range("(5, 1)") == (1.0, 5.0)
        assert parse_range("[2, 3]") == (2.0, 3.0)
        assert parse_range("between 7 and 9") is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("2118", (2118.0, True, 0)),
            ("5.83", (5.83, False, 2)),
            ("10%", (10.0, True, 0)),
            ("1.5e-2", (0.015, False, 3)),
            ("1.2e-7", (1.2e-7, False, 8)),
            ("1.5e3", (1500.0, False, -2)),
            ("nan", None),
            ("inf", None),
            ("1,234", (1234.0, True, 0)),
            ("5:1", None),
            ("8/49", None),
            ("CCND1", None),
            ("", None),
        ],
    )
    def test_a_pure_number_is_told_from_anything_else(self, text: str, expected: Any) -> None:
        assert pure_number(text) == expected


class TestOfficialGrading:
    @pytest.mark.parametrize("answer", ["CDKN1A", "cdkn1a", "  cdkn1a. ", "CDK-N1A"])
    def test_an_exact_match_ignores_case_and_everything_but_letters_and_digits(self, answer: str) -> None:
        judge = RecordingJudge()
        grade = grade_official(question("CDKN1A"), answer, judge)

        assert grade.correct
        assert grade.method == "exact"
        assert judge.prompts == []

    def test_a_str_verifier_that_does_not_match_goes_to_the_judge_with_the_benchmarks_prompt(self) -> None:
        judge = RecordingJudge("correct")
        asked = question("3.5%", question="What is the median?")

        grade = grade_official(asked, "3.54%", judge)

        assert grade.correct
        assert grade.method == "judge"
        assert judge.prompts == [
            OPEN_ENDED_GRADING_PROMPT.format(question="What is the median?", target="3.5%", predicted="3.54%")
        ]

    def test_an_answer_that_is_only_part_of_the_ideal_is_left_to_the_judge(self) -> None:
        judge = RecordingJudge("incorrect")

        assert not grade_official(question("CDKN1A"), "CDK", judge).correct
        assert len(judge.prompts) == 1

    def test_refused_and_a_response_without_a_grade_are_not_correct(self) -> None:
        assert not grade_official(question("x", "llm_verifier"), "y", RecordingJudge("refused")).correct
        assert not grade_official(question("x", "llm_verifier"), "y", lambda prompt: "I think it is fine").correct

    def test_a_number_in_the_range_needs_no_judge(self) -> None:
        judge = RecordingJudge()
        grade = grade_official(question("(0.74, 0.77)", "range_verifier"), "0.75", judge)

        assert grade.correct
        assert grade.method == "range"
        assert judge.prompts == []

    def test_a_range_answer_that_is_not_plainly_in_the_range_goes_to_the_range_judge(self) -> None:
        judge = RecordingJudge("incorrect")
        asked = question("(0.74, 0.77)", "range_verifier", question="What fraction?")

        for answer in ("0.9", "30/41 (0.7317)", "about 0.75"):
            assert not grade_official(asked, answer, judge).correct

        assert len(judge.prompts) == 3
        assert judge.prompts[0] == OPEN_ENDED_RANGE_GRADING_PROMPT.format(
            question="What fraction?", target="(0.74, 0.77)", predicted="0.9"
        )

    def test_an_llm_verifier_is_judged_whatever_the_answer_is(self) -> None:
        judge = RecordingJudge("correct")

        assert grade_official(question("It is up", "llm_verifier"), "Up-regulated", judge).correct
        assert len(judge.prompts) == 1

    def test_no_answer_is_not_correct_and_is_not_judged(self) -> None:
        judge = RecordingJudge("correct")

        assert grade_official(question("x", "llm_verifier"), "  ", judge) == bixbench.Grade(False, "none", "no answer")
        assert judge.prompts == []

    def test_without_a_judge_what_needs_one_is_not_correct(self) -> None:
        grade = grade_official(question("x", "llm_verifier"), "y", None)

        assert not grade.correct
        assert "no judge" in grade.note


class TestLenientGrading:
    def lenient(self, ideal: str, answer: str, mode: str = "str_verifier", judge: Any = None) -> bool:
        asked = question(ideal, mode)
        return grade_answer(asked, answer, judge or RecordingJudge())[LENIENT].correct

    def test_what_the_official_grading_accepts_is_accepted(self) -> None:
        grades = grade_answer(question("CCND1"), "ccnd1", RecordingJudge())

        assert grades[OFFICIAL].correct
        assert grades[LENIENT] is grades[OFFICIAL]

    @pytest.mark.parametrize(
        ("ideal", "answer", "accepted"),
        [
            ("2118", "2101", True),
            ("2118", "2117", True),
            ("2118", "2000", False),
            ("3.5", "3.54", True),
            ("3.5", "3.9", False),
            ("0.1", "0.2", False),
            ("42", "43", False),
            ("5:1", "5:0", False),
            ("8/49", "9/49", False),
            ("CDKN1A", "CCND1", False),
            ("0.1", "10.0", True),
            ("0.1", "50", False),
            ("2500", "25", False),
            ("1,234", "1240", True),
            ("1.2e-7", "1.23e-7", True),
            ("1.2e-7", "1.2 × 10⁻⁷", True),
            ("1.2e-7", "0", False),
            ("1.2e-7", "0.01", False),
            ("1.2e-7", "3e-7", False),
            ("1", "100", False),
            ("1", "There are 100 genes", False),
            ("5", "chr5 has 25 genes", False),
            ("12", "12 or 120", True),
            ("120", "12 or 120", False),
            ("0.73", "73%", True),
            ("0.73", "73.4%", True),
            ("0.73", "74%", False),
            ("0.73", "0.7317 (30/41)", True),
            ("0.001", "0", False),
        ],
    )
    def test_a_number_is_accepted_when_it_rounds_to_the_ideal_and_nothing_else_is(
        self, ideal: str, answer: str, accepted: bool
    ) -> None:
        assert self.lenient(ideal, answer) is accepted

    def test_a_number_among_words_is_found_when_it_is_the_first(self) -> None:
        assert self.lenient("2118", "2101 genes at padj < 0.05")
        assert not self.lenient("2118", "about 40 genes at padj < 0.05")
        assert not self.lenient("2118", "padj < 0.05 gave 2118 genes")

    def test_any_number_in_the_answer_that_is_in_the_range_is_accepted(self) -> None:
        assert self.lenient("(0.7, 0.8)", "30/41 (≈ 0.7317, or 73.2%)", "range_verifier")
        assert self.lenient("(1.03E-07, 1.23E-07)", "1.128 × 10⁻⁷ (or 1.128256802312e-07)", "range_verifier")
        assert not self.lenient("(0.7, 0.8)", "30/41 (0.9)", "range_verifier")

    def test_an_llm_verifier_the_official_grading_failed_is_asked_again_with_the_lenient_prompt(self) -> None:
        judge = RecordingJudge("incorrect")
        asked = question("3.5%", "llm_verifier", question="Median?")

        grades = grade_answer(asked, "3.54%", judge)

        assert [prompt.startswith("You are given") for prompt in judge.prompts] == [True, True]
        assert judge.prompts[1] == LENIENT_GRADING_PROMPT.format(question="Median?", target="3.5%", predicted="3.54%")
        assert not grades[LENIENT].correct

    def test_the_lenient_judge_can_accept_what_the_official_one_did_not(self) -> None:
        answers = iter(["<grade>incorrect</grade>", "<grade>correct</grade>"])
        grades = grade_answer(question("3.5%", "llm_verifier"), "3.54%", lambda prompt: next(answers))

        assert not grades[OFFICIAL].correct
        assert grades[LENIENT].correct

    def test_without_a_judge_the_lenient_grading_stands_on_the_official(self) -> None:
        official = grade_official(question("x", "llm_verifier"), "y", None)

        assert grade_lenient(question("x", "llm_verifier"), "y", official, None) is official


class TestQuestions:
    def test_the_questions_are_read_with_only_what_grading_and_asking_need(self, tmp_path: Path) -> None:
        write_dataset(tmp_path, [row("bix-1-q1"), row("bix-2-q1", "range_verifier", ideal="(1, 2)")])

        questions = load_questions(tmp_path)

        assert [item.id for item in questions] == ["bix-1-q1", "bix-2-q1"]
        assert questions[1].eval_mode == "range_verifier"
        assert questions[1].ideal == "(1, 2)"
        assert questions[0].archive == "CapsuleFolder-abc.zip"
        assert not hasattr(questions[0], "hypothesis")

    def test_a_missing_dataset_says_how_to_fetch_it(self, tmp_path: Path) -> None:
        with pytest.raises(BixBenchError, match="virtual-lab-bixbench fetch"):
            load_questions(tmp_path)

    @pytest.mark.parametrize(
        ("rows", "message"),
        [
            ([row(eval_mode="vibes")], "vibes"),
            ([{"question_id": "a", "question": "q"}], "Line 1"),
            ([row(), row()], "same id"),
            ([row(data_folder="../x.zip")], "zip file's name"),
            ([row(data_folder="capsule.tar")], "zip file's name"),
        ],
    )
    def test_a_question_that_is_not_one_is_refused(
        self, tmp_path: Path, rows: list[dict[str, Any]], message: str
    ) -> None:
        write_dataset(tmp_path, rows)

        with pytest.raises(BixBenchError, match=message):
            load_questions(tmp_path)

    def test_questions_are_chosen_by_id_and_by_count(self) -> None:
        questions = [question("1", id=f"bix-{number}-q1") for number in range(1, 6)]

        assert [item.id for item in choose_questions(questions)] == [item.id for item in questions]
        assert [item.id for item in choose_questions(questions, ["bix-4-q1", "bix-2-q1"])] == ["bix-2-q1", "bix-4-q1"]
        assert len(choose_questions(questions, limit=2)) == 2
        with pytest.raises(BixBenchError, match="no question bix-9-q1"):
            choose_questions(questions, ["bix-9-q1"])
        with pytest.raises(BixBenchError, match="at least 1"):
            choose_questions(questions, limit=0)

    def test_the_message_has_the_question_the_files_and_how_to_end(self) -> None:
        message = question_message(
            question("SECRET-IDEAL-7", question="How many genes are up?"), ["a.csv", "sub/b.tsv"]
        )

        assert "How many genes are up?" in message
        assert "- uploads/a.csv\n- uploads/sub/b.tsv" in message
        assert "FINAL ANSWER:" in message
        assert "SECRET-IDEAL-7" not in message

    def test_a_long_list_of_files_is_cut_short(self) -> None:
        names = [f"f{number}.txt" for number in range(bixbench.MAX_LISTED_FILES + 7)]

        listing = describe_files(names).splitlines()

        assert len(listing) == bixbench.MAX_LISTED_FILES + 1
        assert listing[-1] == "- and 7 more under uploads/"


def make_capsule(path: Path, entries: dict[str, bytes | None], links: tuple[str, ...] = ()) -> Path:
    with zipfile.ZipFile(path, "w") as capsule:
        for name, content in entries.items():
            if content is None:
                capsule.writestr(zipfile.ZipInfo(name), b"")
            else:
                capsule.writestr(name, content)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o120777 << 16
            capsule.writestr(info, "/etc/passwd")

    return path


class TestCapsules:
    def test_the_data_is_unpacked_without_the_notebook(self, tmp_path: Path) -> None:
        archive = make_capsule(
            tmp_path / "c.zip",
            {
                "CapsuleFolder-abc/": None,
                "CapsuleFolder-abc/CapsuleData-abc/counts.csv": b"a,b\n1,2\n",
                "CapsuleFolder-abc/CapsuleData-abc/meta/samples.tsv": b"x\n",
                "CapsuleFolder-abc/CapsuleNotebook-abc/analysis.ipynb": b"{}",
                "CapsuleFolder-abc/CapsuleNotebook-abc/figure.png": b"png",
                "CapsuleFolder-abc/CapsuleData-abc/notes.ipynb": b"{}",
                "__MACOSX/CapsuleData-abc/._counts.csv": b"junk",
                "CapsuleFolder-abc/CapsuleData-abc/.DS_Store": b"junk",
                "README.md": b"outside the data folder",
            },
        )
        destination = tmp_path / "out"

        staged = stage_capsule(archive, destination)

        assert staged.files == ("counts.csv", "meta/samples.tsv")
        assert (destination / "counts.csv").read_bytes() == b"a,b\n1,2\n"
        assert sorted(
            path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()
        ) == [
            "counts.csv",
            "meta/samples.tsv",
        ]
        assert staged.size == len(b"a,b\n1,2\n") + len(b"x\n")
        assert "CapsuleFolder-abc/CapsuleNotebook-abc/analysis.ipynb" in staged.withheld
        assert "CapsuleFolder-abc/CapsuleData-abc/notes.ipynb" in staged.withheld

    def test_an_archive_without_a_data_folder_is_refused_rather_than_guessed_at(self, tmp_path: Path) -> None:
        archive = make_capsule(tmp_path / "c.zip", {"CapsuleFolder-abc/other/file.csv": b"1"})

        with pytest.raises(BixBenchError, match="CapsuleData"):
            stage_capsule(archive, tmp_path / "out")
        assert not (tmp_path / "out").exists()

    @pytest.mark.parametrize("name", ["../evil.txt", "/abs/evil.txt", "CapsuleData-abc/../../evil.txt", "a\\b.txt"])
    def test_a_path_that_leaves_the_directory_is_refused(self, tmp_path: Path, name: str) -> None:
        archive = make_capsule(tmp_path / "c.zip", {"CapsuleData-abc/ok.txt": b"1", name: b"x"})

        with pytest.raises(BixBenchError, match="outside"):
            stage_capsule(archive, tmp_path / "out")
        assert not (tmp_path / "evil.txt").exists()

    def test_a_notebook_is_withheld_whatever_the_case_of_its_name_and_wherever_it_is(self, tmp_path: Path) -> None:
        data = "CapsuleFolder-abc/CapsuleData-abc/"
        archive = make_capsule(
            tmp_path / "c.zip",
            {
                f"{data}ok.csv": b"1",
                f"{data}N.IPYNB": b"{}",
                f"{data}sub/x.Ipynb": b"{}",
                f"{data}.ipynb_checkpoints/x-checkpoint.ipynb": b"{}",
                f"{data}CapsuleNotebook-abc/y.txt": b"answer",
                "CapsuleFolder-abc/CAPSULENOTEBOOK-abc/z.txt": b"answer",
            },
        )

        staged = stage_capsule(archive, tmp_path / "out")

        assert staged.files == ("ok.csv",)
        assert len(staged.withheld) == 5

    def test_a_symbolic_link_is_not_unpacked(self, tmp_path: Path) -> None:
        archive = make_capsule(tmp_path / "c.zip", {"CapsuleData-abc/ok.txt": b"1"}, links=("CapsuleData-abc/passwd",))

        staged = stage_capsule(archive, tmp_path / "out")

        assert staged.files == ("ok.txt",)

    def test_more_data_than_allowed_is_refused_before_any_is_written(self, tmp_path: Path) -> None:
        archive = make_capsule(tmp_path / "c.zip", {"CapsuleData-abc/big.bin": b"x" * 100})

        with pytest.raises(BixBenchError, match="more than 50 bytes"):
            stage_capsule(archive, tmp_path / "out", max_bytes=50)
        assert not (tmp_path / "out").exists()

    def test_a_file_that_is_not_a_zip_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "c.zip").write_bytes(b"not a zip")

        with pytest.raises(BixBenchError, match="not a zip file"):
            stage_capsule(tmp_path / "c.zip", tmp_path / "out")


class FakeHub:
    """Stands in for huggingface_hub, serving files from a directory."""

    def __init__(self, source: Path, error: Exception | None = None) -> None:
        self.source = source
        self.error = error
        self.fetched: list[tuple[str, str | None]] = []

    def hf_hub_download(self, repo: str, name: str, repo_type: str, local_dir: str, token: str | None) -> str:
        assert repo_type == "dataset"
        if self.error is not None:
            raise self.error
        self.fetched.append((name, token))
        target = Path(local_dir) / name
        target.write_bytes((self.source / name).read_bytes())

        return str(target)


class TestDownload:
    def test_only_the_capsules_of_the_questions_asked_for_are_fetched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = tmp_path / "hub"
        write_dataset(
            source,
            [row("bix-1-q1", data_folder="CapsuleFolder-a.zip"), row("bix-2-q1", data_folder="CapsuleFolder-b.zip")],
        )
        make_capsule(source / "CapsuleFolder-a.zip", {"CapsuleData-a/x.csv": b"1"})
        make_capsule(source / "CapsuleFolder-b.zip", {"CapsuleData-b/y.csv": b"2"})
        hub = FakeHub(source)
        monkeypatch.setattr(bixbench, "optional_module", lambda name: hub)

        questions = download_bixbench(tmp_path / "data", token="hf_x", only=["bix-2-q1"])

        assert [item.id for item in questions] == ["bix-2-q1"]
        assert hub.fetched == [(bixbench.QUESTIONS_FILE, "hf_x"), ("CapsuleFolder-b.zip", "hf_x")]
        assert (tmp_path / "data" / "CapsuleFolder-b.zip").is_file()
        assert not (tmp_path / "data" / "CapsuleFolder-a.zip").exists()

    def test_a_capsule_shared_by_questions_is_fetched_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = tmp_path / "hub"
        write_dataset(source, [row("bix-1-q1"), row("bix-1-q2")])
        make_capsule(source / "CapsuleFolder-abc.zip", {"CapsuleData-abc/x.csv": b"1"})
        hub = FakeHub(source)
        monkeypatch.setattr(bixbench, "optional_module", lambda name: hub)

        download_bixbench(tmp_path / "data")

        assert [name for name, _ in hub.fetched] == [bixbench.QUESTIONS_FILE, "CapsuleFolder-abc.zip"]

    def test_a_dataset_whose_terms_have_not_been_accepted_says_what_to_do(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class GatedRepoError(Exception):
            response = type("Response", (), {"status_code": 403})()

        monkeypatch.setattr(bixbench, "optional_module", lambda name: FakeHub(tmp_path, GatedRepoError("gated")))

        with pytest.raises(BixBenchError, match="Accept its terms.*hf auth login"):
            download_bixbench(tmp_path / "data")

    def test_another_failure_is_reported_with_what_it_was(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bixbench, "optional_module", lambda name: FakeHub(tmp_path, OSError("disk full")))

        with pytest.raises(BixBenchError, match="OSError: disk full"):
            download_bixbench(tmp_path / "data")


class TestModelJudge:
    def test_it_asks_the_model_and_counts_what_that_cost(self) -> None:
        client = FakeClient()
        client.completions.responses.append(text_response("<grade> correct </grade>"))
        judge = ModelJudge(TEST_MODEL, client=client)

        assert judge("Is it?") == "<grade> correct </grade>"
        assert client.completions.calls[0]["messages"][-1]["content"] == "Is it?"
        cost = judge.cost()
        assert cost is not None and cost > 0

    def test_an_unpriced_model_has_no_cost(self) -> None:
        client = FakeClient()
        judge = ModelJudge("some-unpriced-model-xyz", client=client)

        judge("Is it?")

        assert judge.cost() is None
