"""BixBench-Verified-50: the questions, the data each is asked with, the message that asks it, and the grading.

BixBench (Mitchener et al., FutureHouse, https://arxiv.org/abs/2503.00096; Apache License 2.0) asks an agent
questions that need real analysis of real data: each comes with a "capsule" of the files from a published study.
Phylo's BixBench-Verified-50 (https://huggingface.co/datasets/phylobio/BixBench-Verified-50) is 50 of the questions,
over 33 capsules, whose wording and answers experts checked. Its files are gated: accept its terms on Hugging Face and
log in (hf auth login) before fetching them.

Each question says how it is graded, with its eval_mode:

- str_verifier: the answer is the ideal once everything but letters and digits is dropped and case is ignored, or a
  model judges it to be the same.
- range_verifier: the ideal is a range, (lower, upper), and the answer is a number in it.
- llm_verifier: a model judges whether the answer says what the ideal does.

That is how FutureHouse's own grader reads an open answer (bixbench/graders.py), except that an answer which is only
part of the ideal is left to the judge, as FutureHouse's lets "CDK" pass for "CDKN1A". The prompts the judge is given
are FutureHouse's, from bixbench/prompts.py, word for word. Every answer is also graded a second, more lenient way,
which accepts what a benchmark author's rounding or an R-versus-Python difference in the last digits would otherwise
fail, as others who report scores on this set have done. The two are kept apart and always reported together, because
only the first is the benchmark's own.
"""

import ast
import json
import re
import threading
import zipfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from virtual_lab.benchmarks import optional_module
from virtual_lab.constants import CONSISTENT_TEMPERATURE
from virtual_lab.llm import ModelSource, ask, resolve_chat_models
from virtual_lab.utils import CostUnknownError, MeetingUsage

DATASET_REPO = "phylobio/BixBench-Verified-50"
QUESTIONS_FILE = "BixBench-Verified-50.jsonl"
EVAL_MODES = ("str_verifier", "range_verifier", "llm_verifier")

# What a capsule's archive holds: the data a question is asked with, and the notebook of the analysis that its answer
# was taken from, which would give the answer away and is never handed to the lab
DATA_FOLDER_PREFIX = "CapsuleData-"
NOTEBOOK_FOLDER_PREFIX = "CapsuleNotebook-"
NOTEBOOK_SUFFIX = ".ipynb"

# Where a question's files are put in the working directory of the conversation that answers it
UPLOADS_DIRECTORY = "uploads"
MAX_CAPSULE_BYTES = 20 * 1024**3
MAX_LISTED_FILES = 150

OFFICIAL = "official"
LENIENT = "lenient"
PROFILES = (OFFICIAL, LENIENT)

# FutureHouse's prompts for the model that judges an answer, from bixbench/prompts.py, unchanged
OPEN_ENDED_GRADING_PROMPT = """You are given a question, target answer and a predicted answer. Your task is to compare the target answer with the predicted and assess if the predicted answer is correct, incorrect or it refused to answer.
Question: {question}
Target Answer: {target}
Predicted Answer: {predicted}

Important: You must only output one from `correct`, `incorrect` or `refused` between <grade> tags.
Example Output: <grade> correct </grade>
"""  # noqa: E501

OPEN_ENDED_RANGE_GRADING_PROMPT = """You are given a question, target range using the format (lower,upper) and a predicted answer. Your task is to compare the target range with the predicted and assess if the predicted answer falls within the specified range. If it falls within the range, it is correct, otherwise it is incorrect. If the predicted answer cannot be compared to the target range, it is refused to answer.
Question: {question}
Target Range: {target}
Predicted Answer: {predicted}

Important: You must only output one from `correct`, `incorrect` or `refused` between <grade> tags.
Example Output: <grade> correct </grade>
"""  # noqa: E501

# The lenient grading's own prompt: the same task, told how much a number may differ and what may not
LENIENT_GRADING_PROMPT = """You are given a question, target answer and a predicted answer. Your task is to compare the target answer with the predicted and assess if the predicted answer is correct, incorrect or it refused to answer.
A numerical target is often rounded by the person who wrote it, so accept a predicted number that agrees with it within 3% relative error, or within one unit of the target's last digit. A named thing, such as a gene, species, chromosome or condition, must be the same one: a synonym is not acceptable unless the target lists it. A fraction given where the target is a percentage, or the other way round, is incorrect.
Question: {question}
Target Answer: {target}
Predicted Answer: {predicted}

Important: You must only output one from `correct`, `incorrect` or `refused` between <grade> tags.
Example Output: <grade> correct </grade>
"""  # noqa: E501

# The bold that closes "**FINAL ANSWER:**" is followed by a space, unlike the bold that opens an answer, "**0.73**"
FINAL_ANSWER_LINE = re.compile(r"final\s+answer\s*(?:\*\*)?\s*[:：]\s*(?:\*\*(?=\s|$))?\s*(.+)", re.IGNORECASE)
ANSWER_TAG = re.compile(r"<answer>\s*(.*?)\s*</answer>", re.IGNORECASE | re.DOTALL)
GRADE_TAG = re.compile(r"<grade>\s*(.*?)\s*</grade>", re.IGNORECASE | re.DOTALL)
NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
RANGE = re.compile(r"\(?\s*(" + NUMBER.pattern + r")\s*,\s*(" + NUMBER.pattern + r")\s*\)?")
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")

# How far a lenient grading lets a number differ from the pure number it is to equal, as a fraction of it
RELATIVE_TOLERANCE = 0.01

Judge = Callable[[str], str]
# A file of a capsule's data: its place in the archive, and its path within the data folder
CapsuleFile = tuple[zipfile.ZipInfo, tuple[str, ...]]


class BixBenchError(ValueError):
    """Raised when the dataset is not there, cannot be read, or is not what the grading expects."""


@dataclass(frozen=True)
class BixQuestion:
    """One question of the benchmark.

    :param id: Its name, such as bix-12-q2.
    :param question: What is asked.
    :param ideal: The answer, or for a range_verifier the range, as "(lower, upper)".
    :param eval_mode: How it is graded: one of EVAL_MODES.
    :param capsule: The id of the capsule of data it is asked with.
    :param archive: The name of the capsule's file in the dataset.
    :param categories: The kinds of analysis it is, as the dataset names them.
    """

    id: str
    question: str
    ideal: str
    eval_mode: str
    capsule: str
    archive: str
    categories: str = ""


@dataclass(frozen=True)
class Grade:
    """How an answer was graded.

    :param correct: Whether it was right.
    :param method: How that was settled: "exact", "range", "numeric", "percent", "judge", or "none" for an answer that
        was missing or could not be judged.
    :param note: What the judge said, or the numbers that were compared.
    """

    correct: bool
    method: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"correct": self.correct, "method": self.method, "note": self.note}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Grade":
        return cls(correct=bool(data["correct"]), method=str(data["method"]), note=str(data.get("note", "")))


@dataclass(frozen=True)
class StagedCapsule:
    """What putting a capsule's data in place did.

    :param files: The paths of the files written, relative to where they were put.
    :param withheld: The paths in the archive that were left out because they are the notebook of the analysis.
    :param size: The bytes written.
    """

    files: tuple[str, ...]
    withheld: tuple[str, ...]
    size: int


def load_questions(directory: Path) -> list[BixQuestion]:
    """The questions in a directory the dataset was fetched into.

    :raises BixBenchError: If the file is missing, a line cannot be read, or a question is not as expected.
    """
    path = Path(directory) / QUESTIONS_FILE
    if not path.is_file():
        raise BixBenchError(f"{path} is not there. Fetch the dataset with: virtual-lab-bixbench fetch {directory}")

    questions: list[BixQuestion] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            question = BixQuestion(
                id=str(row["question_id"]),
                question=str(row["question"]),
                ideal=str(row["ideal"]),
                eval_mode=str(row["eval_mode"]),
                capsule=str(row.get("capsule_uuid", "")),
                archive=str(row["data_folder"]),
                categories=str(row.get("categories") or ""),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise BixBenchError(f"Line {number} of {path} is not a question: {error!r}") from error
        if question.eval_mode not in EVAL_MODES:
            raise BixBenchError(f"{question.id} is graded by {question.eval_mode!r}, not {', '.join(EVAL_MODES)}")
        if Path(question.archive).name != question.archive or not question.archive.endswith(".zip"):
            raise BixBenchError(f"{question.id} has {question.archive!r} for its data, which is not a zip file's name")
        questions.append(question)

    if len({question.id for question in questions}) != len(questions):
        raise BixBenchError(f"{path} has two questions with the same id")

    return questions


def choose_questions(
    questions: Sequence[BixQuestion], only: Iterable[str] = (), limit: int | None = None
) -> list[BixQuestion]:
    """Some of the questions: those with these ids, or by default all, and the first few of them if limit is given.

    :raises BixBenchError: If an id is not one of the questions.
    """
    chosen = list(questions)
    if wanted := list(dict.fromkeys(only)):
        known = {question.id for question in questions}
        if unknown := [name for name in wanted if name not in known]:
            raise BixBenchError(f"There is no question {', '.join(unknown)}")
        chosen = [question for question in questions if question.id in wanted]
    if limit is not None:
        if limit < 1:
            raise BixBenchError(f"limit must be at least 1, not {limit}")
        chosen = chosen[:limit]

    return chosen


def download_bixbench(
    directory: Path,
    token: str | None = None,
    only: Iterable[str] = (),
    limit: int | None = None,
    repo: str = DATASET_REPO,
) -> list[BixQuestion]:
    """Fetches the questions and the capsules they need from Hugging Face.

    A file already there is not fetched again.

    :param directory: Where to put them.
    :param token: A Hugging Face token, or None for the one hf auth login saved.
    :param only: The ids of the questions to fetch the capsules of, or by default all of them.
    :param limit: Fetch the capsules of only the first this many of them.
    :param repo: The dataset.
    :raises BixBenchError: If the dataset cannot be reached or its terms have not been accepted.
    :return: The questions that were asked for.
    """
    hub = optional_module("huggingface_hub")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    def fetch(name: str) -> None:
        try:
            hub.hf_hub_download(repo, name, repo_type="dataset", local_dir=str(directory), token=token)
        except Exception as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status in (401, 403) or type(error).__name__ in ("GatedRepoError", "RepositoryNotFoundError"):
                raise BixBenchError(
                    f"{repo} could not be read. Accept its terms at https://huggingface.co/datasets/{repo} while "
                    f"logged in, then log in here with: hf auth login. ({type(error).__name__})"
                ) from error
            raise BixBenchError(f"{name} could not be fetched from {repo}: {type(error).__name__}: {error}") from error

    fetch(QUESTIONS_FILE)
    questions = choose_questions(load_questions(directory), only, limit)
    for archive in dict.fromkeys(question.archive for question in questions):
        fetch(archive)

    return questions


def plan_capsule(capsule: zipfile.ZipFile, name: str) -> tuple[list[CapsuleFile], list[str]]:
    """What of a capsule's archive is data, and what is left out because it is the notebook of the analysis.

    :param name: The archive's name, for what is said of it.
    :raises BixBenchError: If something in it would be written outside where it is unpacked.
    :return: Each file of data with its path inside the data folder, and the paths withheld.
    """
    plans: list[CapsuleFile] = []
    withheld: list[str] = []
    for member in capsule.infolist():
        if member.is_dir():
            continue
        parts = tuple(part for part in member.filename.split("/") if part not in ("", "."))
        if ".." in parts or member.filename.startswith("/") or "\\" in member.filename:
            raise BixBenchError(f"{name} holds {member.filename!r}, which is outside where it is unpacked")
        if not parts or parts[0] == "__MACOSX" or parts[-1] == ".DS_Store":
            continue
        if any(part.startswith(NOTEBOOK_FOLDER_PREFIX) for part in parts) or parts[-1].endswith(NOTEBOOK_SUFFIX):
            withheld.append("/".join(parts))
            continue
        data_at = next((index for index, part in enumerate(parts) if part.startswith(DATA_FOLDER_PREFIX)), None)
        # A symbolic link in a zip is a file holding where it points to, which unpacked as a file would read as data,
        # and as a link would lead out of the directory
        if data_at is None or data_at == len(parts) - 1 or (member.external_attr >> 28) == 0xA:
            continue
        plans.append((member, parts[data_at + 1 :]))

    return plans, withheld


def stage_capsule(archive: Path, destination: Path, max_bytes: int = MAX_CAPSULE_BYTES) -> StagedCapsule:
    """Puts a capsule's data in a directory, with the notebook of its analysis left out.

    :param archive: The capsule's zip file.
    :param destination: Where its data goes, as it is laid out in the capsule.
    :param max_bytes: The most to write.
    :raises BixBenchError: If the archive is not a zip file, has no data folder in it, or writes outside destination
        or more than max_bytes.
    """
    destination = Path(destination)
    root = destination.resolve()
    written: list[str] = []
    size = 0
    try:
        with zipfile.ZipFile(archive) as capsule:
            plans, withheld = plan_capsule(capsule, archive.name)
            if not plans:
                raise BixBenchError(f"{archive.name} has no {DATA_FOLDER_PREFIX}* folder with files in it")
            if sum(member.file_size for member, _ in plans) > max_bytes:
                raise BixBenchError(f"{archive.name} holds more than {max_bytes} bytes of data")
            for member, parts in plans:
                target = destination.joinpath(*parts)
                if not target.resolve().is_relative_to(root):
                    raise BixBenchError(f"{archive.name} holds {member.filename!r}, which is outside where it is put")
                target.parent.mkdir(parents=True, exist_ok=True)
                with capsule.open(member) as source, open(target, "wb") as sink:
                    while block := source.read(1 << 20):
                        sink.write(block)
                written.append("/".join(parts))
                size += member.file_size
    except zipfile.BadZipFile as error:
        raise BixBenchError(f"{archive} is not a zip file: {error}") from error

    return StagedCapsule(files=tuple(sorted(written)), withheld=tuple(sorted(withheld)), size=size)


def describe_files(files: Sequence[str]) -> str:
    """The files a question comes with as a list for the message that asks it, shortened if there are many."""
    shown = [f"- {UPLOADS_DIRECTORY}/{name}" for name in files[:MAX_LISTED_FILES]]
    if len(files) > MAX_LISTED_FILES:
        shown.append(f"- and {len(files) - MAX_LISTED_FILES} more under {UPLOADS_DIRECTORY}/")

    return "\n".join(shown)


def question_message(question: BixQuestion, files: Sequence[str]) -> str:
    """What the lead is told to have it answer a question."""
    return (
        f"This is a bioinformatics analysis task. The data for it is in the folder `{UPLOADS_DIRECTORY}/` of your "
        "working directory. Analyse it with code, then answer the question.\n\n"
        "Nobody is available to answer questions or to choose for you. Where the question leaves a detail open, "
        "choose as an expert analyst would, and say what you chose.\n\n"
        f"Question: {question.question}\n\n"
        f"Files:\n{describe_files(files)}\n\n"
        "End your reply with one line, written exactly like this:\n"
        "FINAL ANSWER: <the answer alone: a number, a name, or a short phrase, in the form the question asks for>"
    )


def clean_answer(text: str) -> str:
    """An answer without the emphasis and quoting a reply puts round it."""
    text = text.strip()
    previous = None
    while text != previous:
        previous = text
        for mark in ("**", "__", "`", "*", "_", '"', "'"):
            if len(text) > 2 * len(mark) and text.startswith(mark) and text.endswith(mark):
                text = text[len(mark) : -len(mark)].strip()
    # Bold opened before "FINAL ANSWER" and closed after the answer leaves only its closing marks
    if text.endswith("**") and "**" not in text[:-2]:
        text = text[:-2].strip()

    return text


def final_answer(reply: str) -> tuple[str, str]:
    """The answer in a reply, and where it was found.

    :return: The text of the last "FINAL ANSWER:" line, or of an <answer> tag, or the last line there is, and which of
        the three it was: "final_answer", "answer_tag", or "last_line". Empty, with "none", for a reply with nothing
        in it.
    """
    if found := FINAL_ANSWER_LINE.findall(reply):
        if answer := clean_answer(found[-1]):
            return answer, "final_answer"
    if found := ANSWER_TAG.findall(reply):
        if answer := clean_answer(found[-1]):
            return answer, "answer_tag"
    lines = [line.strip() for line in reply.splitlines() if line.strip()]
    if lines:
        return clean_answer(lines[-1]), "last_line"

    return "", "none"


def letters_and_digits(text: str) -> str:
    """Text as the benchmark's exact match reads it: lower case, with everything but letters and digits dropped."""
    return re.sub(r"[^a-zA-Z0-9]", "", text).lower()


def normalise_numbers(text: str) -> str:
    """Text with its numbers written the way Python reads them: thousands separators gone, a minus sign that is a
    dash made one, and powers of ten written as 1.5 x 10^-7 or with superscripts made 1.5e-7."""
    text = text.replace("−", "-")
    text = re.sub(r"10([⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "10^" + m.group(1).translate(SUPERSCRIPTS), text)
    text = re.sub(r"(?<=\d)\s*[×x*]\s*10\s*\^\s*\(?([-+]?\d+)\)?", r"e\1", text)

    return re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)


def numbers_in(text: str) -> list[float]:
    """Every number in a text, in order."""
    found: list[float] = []
    for match in NUMBER.findall(normalise_numbers(text)):
        try:
            found.append(float(match))
        except ValueError:
            continue

    return found


def parse_range(ideal: str) -> tuple[float, float] | None:
    """The bounds of a range written as (lower, upper), or None if it is not one."""
    try:
        value = ast.literal_eval(ideal.strip())
        if isinstance(value, (tuple, list)) and len(value) == 2:
            lower, upper = float(value[0]), float(value[1])
            return (min(lower, upper), max(lower, upper))
    except (ValueError, SyntaxError, TypeError):
        pass
    if match := RANGE.search(ideal):
        lower, upper = float(match.group(1)), float(match.group(2))
        return (min(lower, upper), max(lower, upper))

    return None


def pure_number(text: str) -> tuple[float, bool, int] | None:
    """A text that is one number, as its value, whether it is a whole number, and its decimal places; None for any
    other, including a ratio such as 5:1 or 8/49, which a lenient grading does not give any leeway."""
    stripped = text.strip().rstrip("%").replace(",", "").strip()
    if not stripped or ":" in stripped or "/" in stripped:
        return None
    try:
        value = float(stripped)
    except ValueError:
        return None
    mantissa = re.split(r"[eE]", stripped, maxsplit=1)[0]
    places = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0

    return value, "." not in stripped and "e" not in stripped.lower(), places


def parse_grade(response: str) -> bool:
    """Whether a judge's response grades the answer correct. A response with no grade in it is not."""
    match = GRADE_TAG.search(response)

    return match is not None and match.group(1).strip().lower() == "correct"


def ask_judge(judge: Judge, template: str, question: BixQuestion, answer: str) -> Grade:
    """Has a model judge an answer, with a template that says how."""
    response = judge(template.format(question=question.question, target=question.ideal, predicted=answer))
    verdict = GRADE_TAG.search(response)

    return Grade(parse_grade(response), "judge", verdict.group(1).strip() if verdict else response.strip()[:200])


def single_number(answer: str) -> float | None:
    """The number an answer is, if that is all it is, as a range is checked against."""
    normalised = normalise_numbers(answer.strip()).rstrip("%").strip()
    try:
        return float(normalised)
    except ValueError:
        return None


def grade_official(question: BixQuestion, answer: str, judge: Judge | None) -> Grade:
    """Grades an answer as FutureHouse's grader does for an open answer.

    :param judge: Sends a prompt to the model that judges, and returns what it said. Without one, an answer that
        only a judge can grade is not correct.
    """
    if not answer.strip():
        return Grade(False, "none", "no answer")

    if question.eval_mode == "str_verifier":
        wanted, given = letters_and_digits(question.ideal), letters_and_digits(answer)
        if given and given == wanted:
            return Grade(True, "exact")
        template = OPEN_ENDED_GRADING_PROMPT
    elif question.eval_mode == "range_verifier":
        bounds = parse_range(question.ideal)
        value = single_number(answer)
        # A number that is plainly in the range needs no judge. One outside it, or an answer that is more than a
        # number, is left to the judge, as it is in the benchmark.
        if bounds is not None and value is not None and bounds[0] <= value <= bounds[1]:
            return Grade(True, "range", f"{value} is in {bounds}")
        template = OPEN_ENDED_RANGE_GRADING_PROMPT
    else:
        template = OPEN_ENDED_GRADING_PROMPT

    if judge is None:
        return Grade(False, "none", "no judge was given to grade it")

    return ask_judge(judge, template, question, answer)


def grade_lenient(question: BixQuestion, answer: str, official: Grade, judge: Judge | None) -> Grade:
    """Grades an answer more leniently than the benchmark does.

    What the official grading accepts is accepted. Beyond it, a number in the answer that is a pure-number ideal to
    within 1% or the rounding of its last digit, or 100 times an ideal that is a fraction, is accepted for a
    str_verifier; any number in the answer that is in the range is accepted for a range_verifier; and a judge that
    allows 3% is asked about a llm_verifier. A named thing and a ratio get no leeway.
    """
    if official.correct or not answer.strip():
        return official

    if question.eval_mode == "str_verifier":
        wanted = pure_number(question.ideal)
        if wanted is not None and (numbers := numbers_in(answer)):
            value, whole, places = wanted
            # The ideal is a number someone rounded, so an answer that rounds to it is the same number: within half
            # a unit of its last digit, or 1% of it, whichever is more
            allowed = max(0.0 if whole else 0.5 * 10.0**-places, RELATIVE_TOLERANCE * abs(value))
            if close := [number for number in numbers if abs(number - value) <= allowed]:
                return Grade(True, "numeric", f"{close[0]} is within {allowed:.4g} of {value}")
            if 0 < abs(value) <= 1:
                percent = value * 100
                if close := [number for number in numbers if abs(number - percent) <= max(0.01 * percent, 0.5)]:
                    return Grade(True, "percent", f"{close[0]} is the ideal {value} as a percentage")
    elif question.eval_mode == "range_verifier":
        bounds = parse_range(question.ideal)
        numbers = numbers_in(answer)
        if bounds is not None and (inside := [value for value in numbers if bounds[0] <= value <= bounds[1]]):
            return Grade(True, "range", f"{inside[0]} is in {bounds}")
    elif judge is not None:
        return ask_judge(judge, LENIENT_GRADING_PROMPT, question, answer)

    return official


def grade_answer(question: BixQuestion, answer: str, judge: Judge | None) -> dict[str, Grade]:
    """An answer graded both ways, by the name of the grading."""
    official = grade_official(question, answer, judge)

    return {OFFICIAL: official, LENIENT: grade_lenient(question, answer, official, judge)}


class ModelJudge:
    """A model that judges answers, and what it has cost.

    :param model: The model to ask.
    :param chat_models: The chat models to ask, as hold_meeting takes them.
    :param client: An OpenAI client, as hold_meeting takes it.
    """

    def __init__(self, model: str, chat_models: ModelSource | None = None, client: Any = None) -> None:
        self.model = model
        self._llm = resolve_chat_models([model], chat_models=chat_models, client=client)[model]
        self._usage = MeetingUsage()
        self._lock = threading.Lock()

    def __call__(self, prompt: str) -> str:
        reply = ask(self._llm, [{"role": "user", "content": prompt}], temperature=CONSISTENT_TEMPERATURE)
        with self._lock:
            self._usage.add(model=self.model, usage=reply.usage)

        return reply.content

    def cost(self) -> float | None:
        """What the judging has cost in USD, or None if the model's price is not known."""
        with self._lock:
            try:
                return self._usage.compute_cost()
            except CostUnknownError:
                return None
