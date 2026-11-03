"""Tests of skills: reading a SKILL.md, finding skills in folders, telling the lead of them, and the tools that read
them."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from virtual_lab import skills as skills_module
from virtual_lab.constants import MAX_TOOL_OUTPUT_CHARS
from virtual_lab.session import LocalSession
from virtual_lab.skills import (
    ACTIVATE_SKILL_TOOL_NAME,
    CATALOG_CHARS,
    PAGE_CHARS,
    READ_SKILL_FILE_TOOL_NAME,
    Skill,
    SkillError,
    SkillLibrary,
    discover_skills,
    find_skill_files,
    lenient_fields,
    names_that_fit,
    parse_skill,
    shorten,
    skill_tools,
    skills_prompt,
)


def write_skill(
    root: Path,
    name: str = "dose-response",
    description: str = "Fits a dose-response curve. Use it when a drug's potency is asked for.",
    body: str = "# Dose response\n\n1. Fit a four-parameter logistic.\n2. Report the IC50 with its interval.\n",
    extra: str = "",
    files: dict[str, str | bytes] | None = None,
    folder: str | None = None,
) -> Path:
    directory = root / (folder or name)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n{extra}---\n\n{body}")
    for path, content in (files or {}).items():
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    return directory


def make_skill(tmp_path: Path, **options: Any) -> Skill:
    directory = write_skill(tmp_path / "skills", **options)

    return parse_skill(directory / "SKILL.md", "test")


def tools_of(*skills: Skill, session: Any = None) -> dict[str, Any]:
    return {tool.name: tool.function for tool in skill_tools(skills, session)}


class TestReadingASkill:
    def test_it_has_the_name_and_description_it_gives_and_the_rest_it_says_of_itself(self, tmp_path: Path) -> None:
        directory = write_skill(
            tmp_path,
            extra=(
                "license: MIT\ncompatibility: Needs scipy and the network.\n"
                "metadata:\n  author: A Lab\n  version: 1.2\n"
            ),
        )

        skill = parse_skill(directory / "SKILL.md", "workspace")

        assert skill.name == "dose-response"
        assert skill.description == "Fits a dose-response curve. Use it when a drug's potency is asked for."
        assert skill.directory == directory
        assert skill.file == directory / "SKILL.md"
        assert skill.source == "workspace"
        assert skill.license == "MIT"
        assert skill.compatibility == "Needs scipy and the network."
        assert skill.metadata == {"author": "A Lab", "version": "1.2"}
        assert skill.notes == ()

    def test_a_description_written_over_lines_is_one_line(self, tmp_path: Path) -> None:
        directory = tmp_path / "folded"
        directory.mkdir()
        (directory / "SKILL.md").write_text(
            "---\nname: folded\ndescription: >\n  Does a thing\n  over two lines.\n---\nBody\n", encoding="utf-8"
        )

        assert parse_skill(directory / "SKILL.md", "x").description == "Does a thing over two lines."

    def test_a_file_that_begins_with_a_byte_order_mark_is_read(self, tmp_path: Path) -> None:
        directory = tmp_path / "bom"
        directory.mkdir()
        (directory / "SKILL.md").write_text("\ufeff---\nname: bom\ndescription: Works.\n---\nBody\n", encoding="utf-8")

        assert parse_skill(directory / "SKILL.md", "x").name == "bom"

    def test_a_description_with_an_unquoted_colon_is_read_as_it_was_meant(self, tmp_path: Path) -> None:
        # Invalid YAML, which other clients accept, and which skills in the wild have
        skill = make_skill(tmp_path, description="Use when: a gene list is to be ranked", extra="license: MIT\n")

        assert skill.description == "Use when: a gene list is to be ranked"
        assert skill.license == "MIT"

    def test_the_fields_of_invalid_yaml_are_the_lines_that_name_one(self) -> None:
        fields = lenient_fields("name: x\ndescription: 'Quoted: yes'\nmetadata:\n  a: b\nlicense: MIT\n  with a tail")

        assert fields["name"] == "x"
        assert fields["description"] == "Quoted: yes"
        assert fields["license"] == "MIT with a tail"

    def test_a_skill_with_no_name_is_called_what_its_folder_is(self, tmp_path: Path) -> None:
        directory = tmp_path / "unnamed"
        directory.mkdir()
        (directory / "SKILL.md").write_text("---\ndescription: Does it.\n---\nBody\n")

        skill = parse_skill(directory / "SKILL.md", "x")

        assert skill.name == "unnamed"
        assert "no name" in skill.notes[0]

    def test_a_name_that_is_not_its_folders_or_not_lowercase_is_noted_and_used(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, name="Dose_Response", folder="somewhere-else")

        assert skill.name == "Dose_Response"
        assert any("lowercase" in note for note in skill.notes)
        assert any("somewhere-else" in note for note in skill.notes)

    @pytest.mark.parametrize("name", ["has space", "../escape", "a/b", "x" * 65, "-leading"])
    def test_a_name_that_cannot_be_a_folder_in_a_session_is_refused(self, tmp_path: Path, name: str) -> None:
        directory = write_skill(tmp_path, name="fine", folder="odd")
        (directory / "SKILL.md").write_text(f'---\nname: "{name}"\ndescription: Does it.\n---\nBody\n')

        with pytest.raises(SkillError, match="cannot be used"):
            parse_skill(directory / "SKILL.md", "x")

    def test_a_skill_without_a_description_is_refused(self, tmp_path: Path) -> None:
        directory = tmp_path / "bare"
        directory.mkdir()
        (directory / "SKILL.md").write_text("---\nname: bare\n---\nBody\n")

        with pytest.raises(SkillError, match="no description"):
            parse_skill(directory / "SKILL.md", "x")

    @pytest.mark.parametrize("text", ["Just instructions.\n", "---\n---\nBody\n", "---\nname: x\nno end\n"])
    def test_a_file_without_a_block_of_fields_is_refused(self, tmp_path: Path, text: str) -> None:
        directory = tmp_path / "plain"
        directory.mkdir()
        (directory / "SKILL.md").write_text(text)

        with pytest.raises(SkillError):
            parse_skill(directory / "SKILL.md", "x")

    def test_a_file_that_is_not_text_or_is_too_big_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / "binary"
        directory.mkdir()
        (directory / "SKILL.md").write_bytes(b"---\nname: binary\ndescription: \xff\xfe\n---\n")
        with pytest.raises(SkillError, match="cannot be read"):
            parse_skill(directory / "SKILL.md", "x")

        monkeypatch.setattr(skills_module, "MAX_SKILL_FILE_BYTES", 10)
        with pytest.raises(SkillError, match="can be at most"):
            parse_skill(write_skill(tmp_path, name="big") / "SKILL.md", "x")

    def test_a_description_longer_than_the_standard_allows_is_noted_and_used(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, description="Word. " * 300)

        assert len(skill.description) > 1024
        assert any("1,024" in note for note in skill.notes)

    def test_what_it_needs_is_cut_to_what_the_standard_allows(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, extra=f"compatibility: {'needs a lot ' * 5000}\n")

        assert skill.compatibility is not None and len(skill.compatibility) <= 500
        assert any("compatibility is longer" in note for note in skill.notes)

    def test_a_skill_file_that_is_a_link_to_a_file_outside_the_folder_is_refused(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside.md"
        outside.write_text("---\nname: leak\ndescription: Not in the folder.\n---\nsecret instructions")
        directory = tmp_path / "skills" / "leak"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").symlink_to(outside)

        with pytest.raises(SkillError, match="link to a file outside its folder"):
            parse_skill(directory / "SKILL.md", "test")
        library = discover_skills([("a", tmp_path / "skills")])
        assert library.skills == () and "outside its folder" in library.problems[0].message

    def test_a_skill_file_that_is_a_link_to_a_file_in_the_folder_is_used(self, tmp_path: Path) -> None:
        directory = write_skill(tmp_path / "skills", name="linked", files={"real.md": "x"})
        (directory / "SKILL.md").rename(directory / "REAL_SKILL.md")
        (directory / "SKILL.md").symlink_to("REAL_SKILL.md")

        assert parse_skill(directory / "SKILL.md", "test").name == "linked"

    def test_a_skill_describes_itself_in_json_types(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, extra="license: MIT\n")

        described = skill.describe()

        assert described["name"] == "dose-response"
        assert described["license"] == "MIT"
        assert described["directory"] == str(skill.directory)
        assert described["metadata"] == {} and described["notes"] == []


class TestFindingSkills:
    def test_skills_are_found_in_a_repository_of_them_put_in_a_folder_whole(self, tmp_path: Path) -> None:
        write_skill(tmp_path / "repo" / "skills", name="alpha")
        write_skill(tmp_path / "repo" / "skills", name="beta")
        (tmp_path / "repo" / "README.md").write_text("A repository of skills.")

        library = discover_skills([("workspace", tmp_path / "repo")])

        assert [skill.name for skill in library.skills] == ["alpha", "beta"]
        assert library.problems == ()
        assert {skill.source for skill in library.skills} == {"workspace"}

    def test_what_is_inside_a_skill_is_not_searched(self, tmp_path: Path) -> None:
        outer = write_skill(tmp_path, name="outer")
        write_skill(outer / "templates", name="example")

        assert [file.parent.name for file in find_skill_files(tmp_path)] == ["outer"]

    def test_hidden_folders_and_those_of_a_repository_that_are_not_skills_are_skipped(self, tmp_path: Path) -> None:
        write_skill(tmp_path / ".git", name="hidden")
        write_skill(tmp_path / "node_modules", name="package")
        write_skill(tmp_path / ".cache", name="cached")
        write_skill(tmp_path, name="real")

        assert [skill.name for skill in discover_skills([("a", tmp_path)]).skills] == ["real"]

    def test_a_link_to_a_folder_is_followed_and_a_loop_is_not(self, tmp_path: Path) -> None:
        target = write_skill(tmp_path / "elsewhere", name="linked")
        root = tmp_path / "root"
        root.mkdir()
        (root / "linked").symlink_to(target, target_is_directory=True)
        (root / "loop").symlink_to(root, target_is_directory=True)

        assert [skill.name for skill in discover_skills([("a", root)]).skills] == ["linked"]

    def test_a_skill_too_far_down_is_not_found(self, tmp_path: Path) -> None:
        write_skill(tmp_path.joinpath(*"abcdef"), name="deep")
        write_skill(tmp_path.joinpath(*"abc"), name="near")

        assert [skill.name for skill in discover_skills([("a", tmp_path)]).skills] == ["near"]

    def test_a_folder_that_is_not_there_has_no_skills(self, tmp_path: Path) -> None:
        assert discover_skills([("a", tmp_path / "nothing")]) == SkillLibrary()

    def test_a_folder_that_is_a_skill_itself_is_one(self, tmp_path: Path) -> None:
        directory = write_skill(tmp_path, name="itself")

        assert [skill.name for skill in discover_skills([("a", directory)]).skills] == ["itself"]

    def test_of_two_skills_of_one_name_the_one_in_the_first_folder_is_used(self, tmp_path: Path) -> None:
        mine = write_skill(tmp_path / "mine", name="shared", description="Mine.")
        write_skill(tmp_path / "theirs", name="shared", description="Theirs.")
        write_skill(tmp_path / "theirs", name="other")

        library = discover_skills([("workspace", tmp_path / "mine"), ("user", tmp_path / "theirs")])

        assert [(skill.name, skill.description, skill.source) for skill in library.skills] == [
            ("other", "Fits a dose-response curve. Use it when a drug's potency is asked for.", "user"),
            ("shared", "Mine.", "workspace"),
        ]
        (problem,) = library.problems
        assert problem.path == tmp_path / "theirs" / "shared" / "SKILL.md"
        assert f"in {mine}" in problem.message

    def test_names_that_differ_only_in_case_are_one_name_since_they_are_one_folder_in_a_session(
        self, tmp_path: Path
    ) -> None:
        write_skill(tmp_path / "mine", name="Fit", description="Mine.")
        write_skill(tmp_path / "theirs", name="fit", description="Theirs.")

        library = discover_skills([("a", tmp_path / "mine"), ("b", tmp_path / "theirs")])

        assert [(skill.name, skill.description) for skill in library.skills] == [("Fit", "Mine.")]
        assert "another skill is called fit" in library.problems[0].message

    def test_a_skill_that_cannot_be_used_is_reported_and_the_others_are_kept(self, tmp_path: Path) -> None:
        write_skill(tmp_path, name="good")
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "SKILL.md").write_text("No fields here.")

        library = discover_skills([("a", tmp_path)])

        assert [skill.name for skill in library.skills] == ["good"]
        (problem,) = library.problems
        assert problem.path == broken / "SKILL.md" and "YAML" in problem.message

    def test_skills_are_in_order_of_name_whatever_the_order_of_the_folders(self, tmp_path: Path) -> None:
        for name in ("zeta", "Alpha", "mid"):
            write_skill(tmp_path, name=name)

        assert [skill.name for skill in discover_skills([("a", tmp_path)]).skills] == ["Alpha", "mid", "zeta"]

    def test_only_so_many_skills_are_used(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(skills_module, "MAX_SKILLS", 2)
        for name in ("a", "b", "c"):
            write_skill(tmp_path, name=name)

        library = discover_skills([("a", tmp_path)])

        assert [skill.name for skill in library.skills] == ["a", "b"]
        assert "only 2 skills" in library.problems[0].message

    def test_a_library_is_asked_for_skills_by_name(self, tmp_path: Path) -> None:
        for name in ("a", "b", "c"):
            write_skill(tmp_path, name=name)
        library = discover_skills([("a", tmp_path)])

        assert library.named("b") is library.skills[1]
        assert library.named("missing") is None
        assert [skill.name for skill in library.only(["c", "a", "gone"])] == ["a", "c"]


class TestTellingTheLead:
    def test_with_no_skills_there_is_nothing_to_tell(self) -> None:
        assert skills_prompt([]) == ""

    def test_every_skill_is_listed_with_what_it_is_for(self, tmp_path: Path) -> None:
        first = make_skill(tmp_path, name="alpha", description="Does alpha things.")
        second = make_skill(tmp_path, name="beta", description="Does beta things.")

        prompt = skills_prompt([first, second])

        assert "You have skills" in prompt and ACTIVATE_SKILL_TOOL_NAME in prompt
        assert (
            "<available_skills>\n- alpha: Does alpha things.\n- beta: Does beta things.\n</available_skills>" in prompt
        )

    def test_a_long_description_is_cut_at_the_end_of_a_sentence(self, tmp_path: Path) -> None:
        sentence = (
            "Fits dose-response curves to titration data from plate readers, handles outliers and missing wells, "
            "and reports potency with its interval."
        )
        assert len(sentence) >= 125
        skill = make_skill(tmp_path, description=f"{sentence} {'and then it keeps going ' * 40}end.")

        listed = skills_prompt([skill]).split("<available_skills>\n")[1].splitlines()[0]

        assert listed == f"- dose-response: {sentence}"

    def test_descriptions_are_cut_to_fit_a_library_that_is_too_long_to_list_whole(self, tmp_path: Path) -> None:
        library = [
            make_skill(tmp_path, name=f"skill-{number:03d}", description="Word " * 100 + "end.")
            for number in range(100)
        ]

        prompt = skills_prompt(library, budget=CATALOG_CHARS)

        listed = prompt.split("<available_skills>\n")[1].split("\n</available_skills>")[0]
        assert len(listed) <= CATALOG_CHARS
        assert listed.count("\n- ") == 99
        # Every skill is still there, each with a share of the room
        assert "skill-099: Word" in listed

    def test_skills_that_cannot_be_listed_with_a_description_are_listed_by_name(self, tmp_path: Path) -> None:
        library = [make_skill(tmp_path, name=f"skill-{number:03d}") for number in range(40)]

        prompt = skills_prompt(library, budget=1000)

        listed = prompt.split("<available_skills>\n")[1].split("\n</available_skills>")[0]
        assert len(listed) <= 1000
        assert "Also available, by name only: skill-" in listed and "skill-039" in listed
        assert "- skill-000: Fits" in listed

    def test_names_that_do_not_all_fit_are_cut_and_the_number_left_out_is_said(self) -> None:
        names = [f"skill-{number:03d}" for number in range(100)]

        line = names_that_fit(names, 300)

        assert len(line) <= 300
        assert line.startswith("Also available, by name only: skill-000, skill-001")
        shown = line.split(": ")[1].split(" and ")[0].count("skill-")
        assert line.endswith(f" and {100 - shown} more not listed")
        assert names_that_fit(names[:3], 300) == "Also available, by name only: skill-000, skill-001, skill-002"
        assert len(names_that_fit(names, 10)) <= 10

    def test_a_budget_too_small_for_the_names_loses_no_skill_without_saying_so(self, tmp_path: Path) -> None:
        library = [make_skill(tmp_path, name=f"skill-{number:03d}") for number in range(40)]

        prompt = skills_prompt(library, budget=200)

        listed = prompt.split("<available_skills>\n")[1].split("\n</available_skills>")[0]
        assert len(listed) <= 200 and "more not listed" in listed

    @pytest.mark.parametrize(
        ("text", "limit", "expected"),
        [
            ("Short.", 20, "Short."),
            ("One sentence here. Then another one follows on.", 30, "One sentence here."),
            ("a b c d e f g h i j k l m n o p", 15, "a b c d e f g…"),
            ("x" * 40, 10, "xxxxxxxxx…"),
        ],
    )
    def test_a_text_is_cut_at_a_sentence_or_a_word_where_there_is_one(
        self, text: str, limit: int, expected: str
    ) -> None:
        assert shorten(text, limit) == expected


class TestActivating:
    def test_it_gives_the_instructions_without_the_fields_and_lists_the_files_that_come_with_it(
        self, tmp_path: Path
    ) -> None:
        skill = make_skill(
            tmp_path, files={"scripts/fit.py": "print(1)", "references/guide.md": "# Guide", "assets/logo.png": b"\0"}
        )

        output = tools_of(skill)[ACTIVATE_SKILL_TOOL_NAME]("dose-response")

        assert output.startswith('<skill_content name="dose-response">\n# Dose response')
        assert "Fit a four-parameter logistic." in output
        assert "description:" not in output and "---" not in output
        assert "<file>assets/logo.png</file>\n<file>references/guide.md</file>\n<file>scripts/fit.py</file>" in output
        assert "SKILL.md</file>" not in output
        assert "There is no session to run code in" in output
        assert output.endswith("</skill_content>")

    def test_it_says_what_the_skill_needs_if_it_says(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, extra="compatibility: Needs scipy.\n")

        assert "Compatibility: Needs scipy." in tools_of(skill)[ACTIVATE_SKILL_TOOL_NAME]("dose-response")

    def test_a_name_is_found_whatever_its_case_and_a_wrong_one_suggests_the_right(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path)
        activate = tools_of(skill)[ACTIVATE_SKILL_TOOL_NAME]

        assert "Fit a four-parameter" in activate("  Dose-Response ")
        with pytest.raises(ValueError, match="no skill called 'dose-respnse'. Did you mean dose-response"):
            activate("dose-respnse")
        with pytest.raises(ValueError, match="no skill called 'zzz'. The skills are listed in your instructions"):
            activate("zzz")

    def test_instructions_longer_than_a_page_are_given_in_parts_that_make_the_whole(self, tmp_path: Path) -> None:
        body = "".join(f"Line {number} of the instructions.\n" for number in range(2500))
        skill = make_skill(tmp_path, body=body)
        tools = tools_of(skill)

        first = tools[ACTIVATE_SKILL_TOOL_NAME]("dose-response")

        assert len(first) < 25_000
        assert "Read the rest with read_skill_file" in first and '"SKILL.md"' in first
        gathered = first.split("\n", 1)[1].split("[These are the first")[0][:-1]
        offset = int(first.split("offset ")[1].split(".]")[0])
        assert offset == len(gathered)
        while True:
            page = tools[READ_SKILL_FILE_TOOL_NAME]("dose-response", "SKILL.md", offset)
            gathered += page.split("\n", 1)[1].rsplit("\n[", 1)[0]
            if "[That is the end of the file.]" in page:
                break
            offset = int(page.split("offset ")[1].split(".]")[0])
        assert gathered.strip() == body.strip()

    def test_the_files_listed_are_few_and_a_folder_can_be_listed_for_the_rest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(skills_module, "MAX_LISTED_FILES", 3)
        skill = make_skill(tmp_path, files={f"references/r{number}.md": "x" for number in range(8)})
        tools = tools_of(skill)

        output = tools[ACTIVATE_SKILL_TOOL_NAME]("dose-response")
        listing = tools[READ_SKILL_FILE_TOOL_NAME]("dose-response", "references")

        assert output.count("<file>") == 3 and "and 5 more" in output
        assert listing.count("references/r") == 8
        assert listing.startswith('<skill_folder name="dose-response" path="references">')

    def test_what_it_gives_stays_under_what_a_tool_may_give_however_long_its_fields_and_file_names(
        self, tmp_path: Path
    ) -> None:
        body = "".join(f"line {number}\n" for number in range(10_000))
        files = {f"references/{'long-name-' * 20}{number}.md": "x" for number in range(100)}
        skill = make_skill(tmp_path, body=body, extra=f"compatibility: {'needs a lot ' * 5000}\n", files=files)
        tools = tools_of(skill)

        output = tools[ACTIVATE_SKILL_TOOL_NAME]("dose-response")
        folder = tools[READ_SKILL_FILE_TOOL_NAME]("dose-response", "references")

        assert len(output) < MAX_TOOL_OUTPUT_CHARS and output.endswith("</skill_content>")
        assert "Read the rest with read_skill_file" in output and "more. Give read_skill_file" in output
        assert len(folder) < MAX_TOOL_OUTPUT_CHARS and folder.endswith("</skill_folder>") and "more\n" in folder

    def test_the_skills_folder_is_copied_into_the_session_for_code_to_run_its_scripts(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"scripts/fit.py": "print('fit')", "references/guide.md": "Guide"})
        session = LocalSession(tmp_path / "work", warn=False)

        output = tools_of(skill, session=session)[ACTIVATE_SKILL_TOOL_NAME]("dose-response")

        copied = session.directory / "skills" / "dose-response"
        assert (copied / "scripts" / "fit.py").read_text() == "print('fit')"
        assert (copied / "SKILL.md").is_file()
        assert f"Skill folder in the session: {copied}." in output
        assert "Paths in the instructions are relative to it" in output

    def test_in_a_container_the_folder_is_said_to_be_where_the_container_sees_it(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"scripts/fit.py": "x"})
        session = SimpleNamespace(directory=tmp_path / "work", where_code_runs=lambda: "/workspace")

        output = tools_of(skill, session=session)[ACTIVATE_SKILL_TOOL_NAME]("dose-response")

        assert "Skill folder in the session: /workspace/skills/dose-response." in output
        assert (tmp_path / "work" / "skills" / "dose-response" / "scripts" / "fit.py").is_file()

    def test_a_folder_already_in_the_session_is_not_copied_again(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"scripts/fit.py": "original"})
        session = SimpleNamespace(directory=tmp_path / "work", where_code_runs=lambda: "/workspace")
        activate = tools_of(skill, session=session)[ACTIVATE_SKILL_TOOL_NAME]
        activate("dose-response")
        copied = tmp_path / "work" / "skills" / "dose-response" / "scripts" / "fit.py"
        copied.write_text("changed by the lead")

        activate("dose-response")

        assert copied.read_text() == "changed by the lead"

    def test_the_files_left_out_of_the_copy_are_said_each_time_it_is_activated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(skills_module, "MAX_COPIED_FILES", 3)
        skill = make_skill(tmp_path, files={f"data/d{number}.csv": "1" for number in range(6)})
        session = SimpleNamespace(directory=tmp_path / "work", where_code_runs=lambda: "/workspace")
        activate = tools_of(skill, session=session)[ACTIVATE_SKILL_TOOL_NAME]

        activate("dose-response")

        assert "4 of its files were too many or too large to copy there." in activate("dose-response")

    def test_skills_activated_at_once_are_each_copied_whole_once(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={f"data/d{number}.csv": "1" * 1000 for number in range(50)})
        session = SimpleNamespace(directory=tmp_path / "work", where_code_runs=lambda: "/workspace")
        activate = tools_of(skill, session=session)[ACTIVATE_SKILL_TOOL_NAME]

        with ThreadPoolExecutor(max_workers=8) as pool:
            outputs = list(pool.map(activate, ["dose-response"] * 8))

        assert all("could not be copied" not in output for output in outputs)
        skills_folder = tmp_path / "work" / "skills"
        assert [path.name for path in skills_folder.iterdir()] == ["dose-response"]
        assert len(list((skills_folder / "dose-response" / "data").iterdir())) == 50

    def test_a_copy_that_lost_a_race_to_another_is_not_an_error(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"data/d.csv": "1"})
        target = tmp_path / "work" / "skills" / "dose-response"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("the other copy")

        skills_module.copy_skill(skill.directory, target)

        assert (target / "SKILL.md").read_text() == "the other copy"
        assert [path.name for path in target.parent.iterdir()] == ["dose-response"]

    def test_a_copy_that_fails_leaves_nothing_behind(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        skill = make_skill(tmp_path, files={"data/d.csv": "1"})
        target = tmp_path / "work" / "skills" / "dose-response"
        target.parent.mkdir(parents=True)

        def fail(*args: Any, **kwargs: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(skills_module.shutil, "copy2", fail)

        with pytest.raises(OSError, match="disk full"):
            skills_module.copy_skill(skill.directory, target)

        assert list(target.parent.iterdir()) == []

    def test_links_and_a_repositorys_own_folders_are_not_copied(self, tmp_path: Path) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("private")
        skill = make_skill(tmp_path, files={"scripts/fit.py": "x", ".git/config": "repo", "node_modules/m.js": "m"})
        (skill.directory / "scripts" / "leak.txt").symlink_to(secret)
        (skill.directory / "leak-folder").symlink_to(tmp_path, target_is_directory=True)
        session = SimpleNamespace(directory=tmp_path / "work", where_code_runs=lambda: "/workspace")

        output = tools_of(skill, session=session)[ACTIVATE_SKILL_TOOL_NAME]("dose-response")

        copied = tmp_path / "work" / "skills" / "dose-response"
        assert sorted(path.relative_to(copied).as_posix() for path in copied.rglob("*") if path.is_file()) == [
            "SKILL.md",
            "scripts/fit.py",
        ]
        assert "leak" not in output and ".git" not in output and "node_modules" not in output

    def test_a_skill_with_too_many_files_is_copied_in_part_and_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(skills_module, "MAX_COPIED_FILES", 3)
        skill = make_skill(tmp_path, files={f"data/d{number}.csv": "1" for number in range(6)})
        session = SimpleNamespace(directory=tmp_path / "work", where_code_runs=lambda: "/workspace")

        output = tools_of(skill, session=session)[ACTIVATE_SKILL_TOOL_NAME]("dose-response")

        assert "4 of its files were too many or too large to copy there." in output
        assert not (tmp_path / "work" / "skills" / "dose-response.part").exists()

    def test_a_folder_that_cannot_be_copied_is_read_with_the_tool_instead(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        skill = make_skill(tmp_path)
        session = SimpleNamespace(directory=tmp_path / "work", where_code_runs=lambda: "/workspace")

        def refuse(source: Path, target: Path) -> int:
            raise OSError("disk full")

        monkeypatch.setattr(skills_module, "copy_skill", refuse)

        output = tools_of(skill, session=session)[ACTIVATE_SKILL_TOOL_NAME]("dose-response")

        assert "could not be copied into the session" in output

    def test_a_skill_that_was_removed_since_it_was_found_is_an_error_to_tell_the_lead_of(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path)
        (skill.directory / "SKILL.md").unlink()

        with pytest.raises(ValueError, match="cannot be read any more"):
            tools_of(skill)[ACTIVATE_SKILL_TOOL_NAME]("dose-response")


class TestReadingFiles:
    def test_a_file_that_comes_with_a_skill_is_read(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"references/guide.md": "# Guide\nUse the log scale.\n"})

        output = tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]("dose-response", "references/guide.md")

        assert output == (
            '<skill_file name="dose-response" path="references/guide.md" characters="0-27 of 27">\n'
            "# Guide\nUse the log scale.\n\n[That is the end of the file.]\n</skill_file>"
        )

    def test_a_path_is_read_the_same_with_a_leading_dot_or_backslashes(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"references/guide.md": "Guide"})
        read = tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]

        assert read("dose-response", "./references\\guide.md") == read("dose-response", "references/guide.md")

    def test_a_long_file_is_given_in_parts(self, tmp_path: Path) -> None:
        text = "".join(f"row {number}\n" for number in range(8000))
        skill = make_skill(tmp_path, files={"data/rows.txt": text})
        read = tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]

        first = read("dose-response", "data/rows.txt")
        offset = int(first.split("offset ")[1].split(".]")[0])
        second = read("dose-response", "data/rows.txt", offset)

        assert 0 < offset <= PAGE_CHARS and "[More follows." in first
        assert second.startswith(f'<skill_file name="dose-response" path="data/rows.txt" characters="{offset}-')
        assert second.split("\n", 1)[1].startswith(text[offset : offset + 20])

    def test_a_file_too_long_to_be_read_whole_says_where_what_is_given_stops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(skills_module, "MAX_READ_BYTES", 100)
        skill = make_skill(tmp_path, files={"data/big.txt": "0123456789" * 30})

        output = tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]("dose-response", "data/big.txt")

        assert 'characters="0-100 of 100"' in output
        assert "[That is as much of the file as can be read here, its first 100 bytes.]" in output
        assert "[That is the end of the file.]" not in output

    def test_a_binary_file_is_said_to_be_one(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"assets/logo.png": b"\x89PNG\0\0\0"})

        output = tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]("dose-response", "assets/logo.png")

        assert output == "assets/logo.png is a binary file of 7 bytes, which cannot be read as text."

    @pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", "references/../../outside.txt", "a/../../b"])
    def test_a_path_that_leaves_the_skills_folder_is_refused(self, tmp_path: Path, path: str) -> None:
        skill = make_skill(tmp_path)
        (tmp_path / "skills" / "outside.txt").write_text("outside")

        with pytest.raises(ValueError, match="stays inside it"):
            tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]("dose-response", path)

    def test_a_link_that_leads_out_of_the_skills_folder_is_refused(self, tmp_path: Path) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("private")
        skill = make_skill(tmp_path)
        (skill.directory / "leak.txt").symlink_to(secret)

        with pytest.raises(ValueError, match="stays inside it"):
            tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]("dose-response", "leak.txt")

    def test_a_file_that_is_not_there_is_said_not_to_be_and_the_near_one_suggested(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"references/guide.md": "Guide"})

        with pytest.raises(ValueError, match="no file 'references/guid.md'. Did you mean references/guide.md"):
            tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]("dose-response", "references/guid.md")

    def test_an_empty_path_lists_the_whole_folder(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"a.md": "A", "scripts/b.py": "B"})

        listing = tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]("dose-response", "")

        assert listing == '<skill_folder name="dose-response" path="">\na.md\nscripts/b.py\n</skill_folder>'

    @pytest.mark.parametrize("offset", [-1, 1.5, "3", True])
    def test_an_offset_that_is_not_a_place_in_a_file_is_refused(self, tmp_path: Path, offset: Any) -> None:
        skill = make_skill(tmp_path, files={"a.md": "A"})

        with pytest.raises(ValueError, match="offset is a number of characters"):
            tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]("dose-response", "a.md", offset)

    def test_an_offset_past_the_end_is_refused(self, tmp_path: Path) -> None:
        skill = make_skill(tmp_path, files={"a.md": "A"})

        with pytest.raises(ValueError, match="only 1 characters long"):
            tools_of(skill)[READ_SKILL_FILE_TOOL_NAME]("dose-response", "a.md", 5)

    def test_the_tools_say_what_they_are_for_and_what_they_need(self, tmp_path: Path) -> None:
        activate, read = skill_tools([make_skill(tmp_path)])

        assert (activate.name, read.name) == ("activate_skill", "read_skill_file")
        assert activate.parameters["required"] == ["name"]
        assert read.parameters["required"] == ["name", "path"]
        assert set(read.parameters["properties"]) == {"name", "path", "offset"}
