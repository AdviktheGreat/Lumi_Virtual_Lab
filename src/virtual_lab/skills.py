"""Skills: folders of written guidance that tell the lead how to do a kind of work well, in the format of the Agent
Skills standard (agentskills.io), which Claude Code, Codex, and others read too, so that a skill written for one of
them works here.

A skill is a folder with a SKILL.md: a block of YAML at the top that gives its name and says what it is for, then the
instructions. Scripts, references, and templates may sit beside it. The lead is told the name and purpose of every
skill, which is little, and reads the rest of one only when a task calls for it: the instructions when it activates the
skill, and the files beside them as it needs them. A skill that comes with scripts has its folder copied into the
session, so that code can run them.

Skills are found in folders the person keeps them in, as discover_skills reads them, and a folder may hold a whole
repository of them, which is searched a few levels down. What is wrong with one skill leaves out that skill and not the
others, and is reported as a problem rather than raised. Some skills come with the lab, in builtin_skills/ beside this
file (see builtin_skills).
"""

import difflib
import errno
import os
import re
import shutil
import threading
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from virtual_lab.session import Session
from virtual_lab.tools import Tool

SKILL_FILE_NAME = "SKILL.md"

ACTIVATE_SKILL_TOOL_NAME = "activate_skill"
READ_SKILL_FILE_TOOL_NAME = "read_skill_file"
SKILL_TOOL_NAMES = frozenset({ACTIVATE_SKILL_TOOL_NAME, READ_SKILL_FILE_TOOL_NAME})

# Where in a session's directory a skill that is activated is put, a folder for each by its name
SESSION_SKILLS_DIR_NAME = "skills"

# The folder, beside this file, of the skills that come with the lab, and what they are said to be found in. They are
# read from there and never copied, so that they are the same in every workspace and a new release's are the ones used.
BUILTIN_SKILLS_DIR_NAME = "builtin_skills"
BUILTIN_SOURCE = "builtin"

# How many levels below a folder to look for skills, so that a repository of them can be put there whole, and the most
# skills to use, which is far more than anyone has, so that a folder of something else cannot fill a prompt
MAX_SKILL_DEPTH = 5
MAX_SKILLS = 500

# The most bytes a SKILL.md may have, which is many times more than what the standard recommends of its instructions
MAX_SKILL_FILE_BYTES = 1_000_000

# What of a repository's folders a skill is not searched or copied for
SKIPPED_DIRECTORIES = frozenset({".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv"})

# The characters of what the lead is told of every skill, which is about 5,000 tokens in each request it makes. A
# library of 170 skills does not fit with a description for each as long as they are written, so each is cut short to
# what fits, and the lead reads all of a skill when it activates it
CATALOG_CHARS = 20_000
CATALOG_DESCRIPTION_CHARS = 250
CATALOG_MIN_DESCRIPTION_CHARS = 60
NAMES_ONLY = "Also available, by name only:"

# The characters of a skill's instructions or of a file that are given at a time. A tool's output is cut at 25,000
# characters as a whole, so a longer one is given in parts, each saying where the next starts
PAGE_CHARS = 18_000
MAX_READ_BYTES = 4_000_000

# The files an activated skill lists, and the most that a folder's listing shows, each also limited in characters so
# that what a tool gives, with the instructions or a page of a file, stays under its 25,000
MAX_LISTED_FILES = 40
MAX_FOLDER_LISTING = 200
MAX_LISTING_CHARS = 3_000
MAX_FOLDER_LISTING_CHARS = 6_000
MAX_COMPATIBILITY_CHARS = 500

# The most files, and bytes of them, copied into a session for a skill, so that one that came with a dataset is not
# copied whole
MAX_COPIED_FILES = 2_000
MAX_COPIED_BYTES = 50_000_000

# What a skill's name may be to be used here: a little more than the standard allows, which is lowercase letters,
# digits, and single hyphens, since it is a folder name inside a session and so cannot be anything else than a plain
# name
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
STANDARD_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
FRONTMATTER = re.compile(r"\A\ufeff?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.DOTALL)
TOP_LEVEL_FIELD = re.compile(r"([A-Za-z][\w-]*):[ \t]*(.*)$")


class SkillError(ValueError):
    """What is wrong with a skill that cannot be used."""


@dataclass(frozen=True)
class Skill:
    """A skill that was found.

    :param name: What it is called, which is what the lead activates it by.
    :param description: What it is for and when to use it, on one line.
    :param directory: Its folder, where SKILL.md and what comes with it are.
    :param source: Where it was found, as the folders were named to discover_skills.
    :param license: Its license, if it says.
    :param compatibility: What it needs, if it says, such as a package or network access.
    :param metadata: Whatever else it says of itself, such as an author and a version.
    :param notes: Ways it departs from the standard that did not stop it being used.
    """

    name: str
    description: str
    directory: Path
    source: str
    license: str | None = None
    compatibility: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def file(self) -> Path:
        return self.directory / SKILL_FILE_NAME

    def describe(self) -> dict[str, Any]:
        """The skill in JSON's types, for a page that lists it."""
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "directory": str(self.directory),
            "license": self.license,
            "compatibility": self.compatibility,
            "metadata": dict(self.metadata),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class SkillProblem:
    """A SKILL.md that was found and could not be used, and why."""

    path: Path
    message: str


@dataclass(frozen=True)
class SkillLibrary:
    """The skills that were found, by name, and what was wrong with the rest."""

    skills: tuple[Skill, ...] = ()
    problems: tuple[SkillProblem, ...] = ()

    def named(self, name: str) -> Skill | None:
        return next((skill for skill in self.skills if skill.name == name), None)

    def only(self, names: Sequence[str]) -> tuple[Skill, ...]:
        """The skills of these names that there are, in the library's order."""
        wanted = set(names)

        return tuple(skill for skill in self.skills if skill.name in wanted)


def one_line(value: Any) -> str:
    """What a field says, on one line of words."""
    return "" if value is None else " ".join(str(value).split())


def split_frontmatter(text: str) -> tuple[str, str]:
    """A SKILL.md as the YAML at its top and the instructions after it.

    :raises SkillError: If it does not begin with YAML between two lines of three hyphens.
    """
    match = FRONTMATTER.match(text)
    if match is None:
        raise SkillError("it has no YAML between lines of --- at the top, which says what it is called and for")

    return match.group(1), match.group(2)


def lenient_fields(block: str) -> dict[str, Any]:
    """The top-level fields of YAML that is not valid, as a line of each: what authors most often get wrong is a colon
    in a description they did not quote, which another client would read the same way."""
    fields: dict[str, Any] = {}
    key: str | None = None
    for line in block.splitlines():
        match = TOP_LEVEL_FIELD.match(line)
        if match is not None:
            key, value = match.group(1), match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            fields[key] = value
        elif key is not None and line[:1] in (" ", "\t") and line.strip():
            fields[key] = f"{fields[key]} {line.strip()}".strip()

    return fields


def read_fields(block: str) -> dict[str, Any]:
    """The fields a SKILL.md's YAML gives.

    :raises SkillError: If there are none to be read.
    """
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        data = lenient_fields(block)
    if not data:
        raise SkillError("the YAML at its top has no fields")

    return {str(key): value for key, value in data.items()}


def parse_skill(file: Path, source: str) -> Skill:
    """A skill from its SKILL.md.

    :param file: The SKILL.md.
    :param source: Where it was found.
    :raises SkillError: If it cannot be read, or has no description, or its name cannot be used.
    """
    if not is_inside(file, file.parent):
        raise SkillError("its SKILL.md is a link to a file outside its folder")
    try:
        size = file.stat().st_size
        if size > MAX_SKILL_FILE_BYTES:
            raise SkillError(f"it is {size:,} bytes, and a SKILL.md can be at most {MAX_SKILL_FILE_BYTES:,}")
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SkillError(f"it cannot be read: {error}") from error

    fields = read_fields(split_frontmatter(text)[0])
    directory = file.parent
    notes: list[str] = []

    name = one_line(fields.get("name"))
    if not name:
        name = directory.name
        notes.append(f"it has no name, so its folder's is used, {name}")
    if not NAME.fullmatch(name):
        raise SkillError(
            f"its name, {name!r}, cannot be used: it is letters, digits, hyphens, dots, and underscores, at most 64"
        )
    if not STANDARD_NAME.fullmatch(name):
        notes.append("its name is not lowercase letters, digits, and single hyphens, as the standard has it")
    if name != directory.name:
        notes.append(f"its name is not that of its folder, {directory.name}")

    description = one_line(fields.get("description"))
    if not description:
        raise SkillError("it has no description, which is what tells the lead when to use it")
    if len(description) > 1024:
        notes.append("its description is longer than the 1,024 characters the standard allows")

    compatibility = one_line(fields.get("compatibility")) or None
    if compatibility and len(compatibility) > MAX_COMPATIBILITY_CHARS:
        notes.append(f"its compatibility is longer than the {MAX_COMPATIBILITY_CHARS} characters the standard allows")
        compatibility = shorten(compatibility, MAX_COMPATIBILITY_CHARS)

    metadata = fields.get("metadata")

    return Skill(
        name=name,
        description=description,
        directory=directory,
        source=source,
        license=one_line(fields.get("license")) or None,
        compatibility=compatibility,
        metadata={one_line(key): one_line(value) for key, value in metadata.items()}
        if isinstance(metadata, dict)
        else {},
        notes=tuple(notes),
    )


def search_skill_files(root: Path, most_folders: int | None = None) -> tuple[list[Path], bool]:
    """The SKILL.md files in a folder and in the folders below it. A folder that has one is a skill, and what is in it
    is not searched, since it may hold examples of skills that are not. Links to folders are followed, once each, as the
    tools that install skills make them.

    :param most_folders: How many folders to look in at most, for a folder that may be a whole disk. None looks in all.
    :return: The files, and whether every folder was searched, which is False where it stopped at most_folders.
    """
    found: list[Path] = []
    seen: set[Path] = set()
    searched_all = True

    def search(directory: Path, depth: int) -> None:
        nonlocal searched_all
        if not searched_all:
            return
        try:
            real = directory.resolve()
        except (OSError, RuntimeError):
            return
        if real in seen:
            return
        if most_folders is not None and len(seen) >= most_folders:
            searched_all = False
            return
        seen.add(real)
        file = directory / SKILL_FILE_NAME
        if file.is_file():
            found.append(file)
            return
        if depth >= MAX_SKILL_DEPTH:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError:
            return
        for entry in entries:
            if entry.name in SKIPPED_DIRECTORIES or entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    search(entry, depth + 1)
            except OSError:
                continue

    search(root, 0)

    return found, searched_all


def find_skill_files(root: Path) -> list[Path]:
    """The SKILL.md files in a folder and in the folders below it (see search_skill_files)."""
    return search_skill_files(root)[0]


def discover_skills(roots: Sequence[tuple[str, Path]]) -> SkillLibrary:
    """The skills in some folders.

    :param roots: Each folder with what to call where its skills were found, the most important first: of two skills
        of one name, the first found is used, and the other is reported.
    :return: The skills by name, and a problem for each SKILL.md that could not be used or was hidden by another.
    """
    skills: dict[str, Skill] = {}
    problems: list[SkillProblem] = []
    for source, root in roots:
        for file in find_skill_files(Path(root)):
            try:
                skill = parse_skill(file, source)
            except SkillError as error:
                problems.append(SkillProblem(file, str(error)))
                continue
            if (earlier := skills.get(skill.name.casefold())) is not None:
                problems.append(
                    SkillProblem(
                        file, f"another skill is called {skill.name}, in {earlier.directory}, and is used instead"
                    )
                )
            elif len(skills) >= MAX_SKILLS:
                problems.append(SkillProblem(file, f"only {MAX_SKILLS} skills are used, and there are more"))
            else:
                skills[skill.name.casefold()] = skill

    ordered = sorted(skills.values(), key=lambda skill: (skill.name.casefold(), skill.name))

    return SkillLibrary(tuple(ordered), tuple(problems))


def builtin_skills_directory() -> Path:
    """The folder of the skills that come with the lab."""
    return Path(__file__).parent / BUILTIN_SKILLS_DIR_NAME


def builtin_skills() -> tuple[Skill, ...]:
    """The skills that come with the lab, which are general practice for kinds of analysis where a number is easy to get
    wrong. A conversation is given them as it is given any skill: `Chat(skills=builtin_skills())`."""
    return discover_skills([(BUILTIN_SOURCE, builtin_skills_directory())]).skills


def shorten(text: str, limit: int) -> str:
    """A text cut to at most `limit` characters, at the end of a sentence or at a word where there is one not too far
    back."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    sentence = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if sentence >= limit // 2:
        return cut[: sentence + 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]

    return cut.rstrip(" ,;:.") + "…"


def catalog_lines(skills: Sequence[Skill], budget: int) -> list[str]:
    """A line for each skill that fits in a budget: its name and what it is for, with each description cut to the same
    length when the whole does not fit, and the names of those that still do not left for the end of one line."""
    overhead = sum(len(skill.name) + 5 for skill in skills)
    cap = CATALOG_DESCRIPTION_CHARS
    if overhead + sum(min(len(skill.description), cap) for skill in skills) > budget:
        cap = max(CATALOG_MIN_DESCRIPTION_CHARS, (budget - overhead) // max(len(skills), 1))
    lines = [f"- {skill.name}: {shorten(skill.description, cap)}" for skill in skills]

    count = 0
    used = 0
    while count < len(lines) and used + len(lines[count]) + 1 <= budget:
        used += len(lines[count]) + 1
        count += 1
    if count == len(lines):
        return lines

    # The rest by name alone, in a line that has to fit as well, which takes room back from those with descriptions
    while True:
        names = f"{NAMES_ONLY} " + ", ".join(skill.name for skill in skills[count:])
        if used + len(names) <= budget or count == 0:
            break
        count -= 1
        used -= len(lines[count]) + 1
    if len(names) > budget:
        names = names_that_fit([skill.name for skill in skills[count:]], budget)

    return [*lines[:count], names]


def names_that_fit(names: Sequence[str], budget: int) -> str:
    """As many of the names as fit in a budget, with how many there is no room for said."""
    for shown in range(len(names), -1, -1):
        left = len(names) - shown
        line = f"{NAMES_ONLY} " + ", ".join(names[:shown]) + (f" and {left} more not listed" if left else "")
        if len(line) <= budget or shown == 0:
            return line if len(line) <= budget else line[: max(budget - 1, 0)] + "…"

    return NAMES_ONLY


def skills_prompt(skills: Sequence[Skill], budget: int = CATALOG_CHARS) -> str:
    """What the lead is told of its skills, which is nothing if it has none.

    :param skills: The skills.
    :param budget: The most characters to list them in.
    """
    if not skills:
        return ""

    listed = "\n".join(catalog_lines(skills, budget))

    return (
        "You have skills: folders of written guidance from specialists on particular kinds of work, with scripts and "
        "reference files where they help. Each is listed here with what it is for. At the start of a task, look "
        f"through the list. When a skill suits the task, call {ACTIVATE_SKILL_TOOL_NAME} with its name before you "
        "begin, and follow what it says: how the work is done, which tools and conventions to use, and what to "
        "check. Activate each skill that suits the task and none that does not. A description here may be cut "
        "short, and what you are given when you activate the skill is the whole of it. What the researcher asks "
        f"for comes before what a skill says.\n\n<available_skills>\n{listed}\n</available_skills>"
    )


def read_body(skill: Skill) -> str:
    """A skill's instructions, without the YAML at the top.

    :raises SkillError: If the file cannot be read or has changed so that it can no longer be used.
    """
    try:
        text = skill.file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SkillError(f"{skill.name} cannot be read any more: {error}") from error

    return split_frontmatter(text)[1].strip()


def page_of(text: str, offset: int) -> tuple[str, int | None]:
    """The part of a text that starts at an offset and is at most PAGE_CHARS long, ended at the end of a line where one
    is near, and where the next part starts, or None if this is the last."""
    end = offset + PAGE_CHARS
    if end >= len(text):
        return text[offset:], None
    cut = text.rfind("\n", offset + PAGE_CHARS * 4 // 5, end)
    if cut != -1:
        end = cut + 1

    return text[offset:end], end


def is_inside(path: Path, folder: Path) -> bool:
    try:
        return path.resolve().is_relative_to(folder.resolve())
    except (OSError, RuntimeError):
        return False


def listing(paths: Sequence[str], most: int, characters: int) -> tuple[list[str], int]:
    """The first of some paths that are at most a number, and at most a number of characters together, and how many are
    left out."""
    shown: list[str] = []
    used = 0
    for path in paths[:most]:
        if used + len(path) + 1 > characters:
            break
        shown.append(path)
        used += len(path) + 1

    return shown, len(paths) - len(shown)


def files_in(folder: Path, root: Path) -> list[str]:
    """The files in a folder and below it, as paths from a root, sorted, leaving out links, since they may lead out of
    the skill, SKILL.md at the root, and what a repository's folders hold that is not the skill's."""
    found: list[str] = []
    for directory, names, files in os.walk(folder):
        names[:] = sorted(
            name for name in names if name not in SKIPPED_DIRECTORIES and not (Path(directory) / name).is_symlink()
        )
        for file in sorted(files):
            path = Path(directory) / file
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file() or relative == SKILL_FILE_NAME:
                continue
            found.append(relative)

    return sorted(found)


def copy_skill(source: Path, target: Path) -> int:
    """Copies a skill's folder, without links, which may lead out of it, or what a repository's folders hold that a
    skill does not need. It stops at MAX_COPIED_FILES files or MAX_COPIED_BYTES bytes, and is whole or not there at all.
    The SKILL.md is copied first and always, as a file even where it is a link to one inside the folder, since a skill
    is not one without it.

    :param source: The skill's folder.
    :param target: Where to put it, which must not be there.
    :raises OSError: If it cannot be copied.
    :return: The number of files that were left out for being too many or too big.
    """
    staging = target.with_name(f"{target.name}.{uuid.uuid4().hex[:8]}.part")
    copied = 0
    size = 0
    left_out = 0
    try:
        for directory, names, files in os.walk(source):
            names[:] = sorted(
                name for name in names if name not in SKIPPED_DIRECTORIES and not (Path(directory) / name).is_symlink()
            )
            destination = staging / Path(directory).relative_to(source)
            destination.mkdir(parents=True, exist_ok=True)
            at_root = Path(directory) == source
            for file in sorted(files, key=lambda name: (not (at_root and name == SKILL_FILE_NAME), name)):
                path = Path(directory) / file
                is_instructions = at_root and file == SKILL_FILE_NAME
                if path.is_symlink() and not (is_instructions and is_inside(path, source)):
                    continue
                if not path.is_file():
                    continue
                length = path.stat().st_size
                if copied >= MAX_COPIED_FILES or size + length > MAX_COPIED_BYTES:
                    left_out += 1
                    continue
                shutil.copy2(path, destination / file)
                copied += 1
                size += length
        if not (staging / SKILL_FILE_NAME).is_file():
            raise OSError(errno.ENOENT, f"there is no {SKILL_FILE_NAME} in {source.name} to copy")
        try:
            staging.rename(target)
        except OSError:
            if not target.is_dir():
                raise
            # A copy put there meanwhile is as good as this one
            shutil.rmtree(staging, ignore_errors=True)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return left_out


def skill_tools(skills: Sequence[Skill], session: Session | None = None) -> tuple[Tool, ...]:
    """The tools that let the lead read its skills: one to activate a skill, and one to read the files that come with
    it.

    :param skills: The skills, which is what the tools can be asked for.
    :param session: The session code runs in, if there is one. An activated skill is copied into its directory, so that
        code can run the skill's scripts and read its files.
    """
    by_name = {skill.name: skill for skill in skills}
    placing = threading.Lock()
    left_out_of: dict[str, int] = {}

    def find(name: Any) -> Skill:
        asked = str(name).strip()
        if (skill := by_name.get(asked)) is not None:
            return skill
        for skill in skills:
            if skill.name.casefold() == asked.casefold():
                return skill
        close = difflib.get_close_matches(asked, list(by_name), n=3, cutoff=0.5)
        hint = f" Did you mean {', '.join(close)}?" if close else ""

        raise ValueError(f"There is no skill called {asked!r}.{hint} The skills are listed in your instructions.")

    def place(skill: Skill) -> tuple[str | None, int]:
        """Where the skill's folder is in the session, copied there if it was not, and how many files could not be."""
        if session is None:
            return None, 0
        target = session.directory / SESSION_SKILLS_DIR_NAME / skill.name
        shown = f"{session.where_code_runs().rstrip('/')}/{SESSION_SKILLS_DIR_NAME}/{skill.name}"
        with placing:
            if target.exists():
                return shown, left_out_of.get(skill.name, 0)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                left_out_of[skill.name] = copy_skill(skill.directory, target)
            except OSError:
                return None, 0

            return shown, left_out_of[skill.name]

    def activate(name: str) -> str:
        skill = find(name)
        try:
            body = read_body(skill)
        except SkillError as error:
            raise ValueError(str(error)) from error
        shown, left_out = place(skill)
        text, more = page_of(body, 0)
        files = files_in(skill.directory, skill.directory)

        lines = [f'<skill_content name="{skill.name}">', text]
        if more is not None:
            lines.append(
                f"[These are the first {more:,} of {len(body):,} characters of the instructions. Read the rest with "
                f'{READ_SKILL_FILE_TOOL_NAME}, name "{skill.name}", path "{SKILL_FILE_NAME}", offset {more}.]'
            )
        lines.append("")
        if skill.compatibility:
            lines.append(f"Compatibility: {skill.compatibility}")
        if shown is not None:
            lines.append(
                f"Skill folder in the session: {shown}. Paths in the instructions are relative to it, so code can run "
                "its scripts and read its files from there."
            )
        elif session is None:
            lines.append(
                "There is no session to run code in, so its scripts cannot be run, but "
                f"{READ_SKILL_FILE_TOOL_NAME} reads them."
            )
        else:
            lines.append(
                f"Its folder could not be copied into the session, so read its files with {READ_SKILL_FILE_TOOL_NAME}."
            )
        if left_out:
            lines.append(f"{left_out} of its files were too many or too large to copy there.")
        if files:
            listed, unlisted = listing(files, MAX_LISTED_FILES, MAX_LISTING_CHARS)
            lines.append(f"Files that come with it, which {READ_SKILL_FILE_TOOL_NAME} reads:")
            lines.extend(f"<file>{path}</file>" for path in listed)
            if unlisted:
                lines.append(
                    f"... and {unlisted} more. Give {READ_SKILL_FILE_TOOL_NAME} a folder's path to list what is in it."
                )
        lines.append("</skill_content>")

        return "\n".join(lines)

    def read_file(name: str, path: str, offset: int = 0) -> str:
        skill = find(name)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError(f"offset is a number of characters, zero or more, not {offset!r}")
        asked = str(path).strip().replace("\\", "/")
        while asked.startswith("./"):
            asked = asked[2:]
        parts = [part for part in asked.split("/") if part not in ("", ".")]
        if asked.startswith("/") or ".." in parts:
            raise ValueError("A path is relative to the skill's folder, and stays inside it")
        relative = "/".join(parts)
        target = skill.directory / relative
        if not is_inside(target, skill.directory):
            raise ValueError("A path is relative to the skill's folder, and stays inside it")

        cut_off = False
        if relative == SKILL_FILE_NAME:
            try:
                text = read_body(skill)
            except SkillError as error:
                raise ValueError(str(error)) from error
        elif target.is_dir():
            shown, unlisted = listing(files_in(target, skill.directory), MAX_FOLDER_LISTING, MAX_FOLDER_LISTING_CHARS)
            more = f"\n... and {unlisted} more" if unlisted else ""

            return (
                f'<skill_folder name="{skill.name}" path="{relative}">\n'
                + "\n".join(shown)
                + f"{more}\n</skill_folder>"
            )
        elif not target.is_file():
            nearby = difflib.get_close_matches(relative, files_in(skill.directory, skill.directory), n=3, cutoff=0.4)
            hint = f" Did you mean {', '.join(nearby)}?" if nearby else ""
            raise ValueError(f"The skill {skill.name} has no file {relative!r}.{hint}")
        else:
            try:
                with target.open("rb") as handle:
                    data = handle.read(MAX_READ_BYTES)
                size = target.stat().st_size
                cut_off = size > MAX_READ_BYTES
            except OSError as error:
                raise ValueError(f"{relative} cannot be read: {error}") from error
            if b"\0" in data[:8192]:
                where = (
                    f", which code in the session can use at {SESSION_SKILLS_DIR_NAME}/{skill.name}/{relative}"
                    if session
                    else ""
                )
                return f"{relative} is a binary file of {size:,} bytes, which cannot be read as text{where}."
            text = data.decode("utf-8", errors="replace")

        if offset >= len(text) and offset > 0:
            raise ValueError(
                f"{relative} is only {len(text):,} characters long, so there is nothing at offset {offset}"
            )
        part, more_at = page_of(text, offset)
        end = offset + len(part)
        header = f'<skill_file name="{skill.name}" path="{relative}" characters="{offset}-{end} of {len(text)}">'
        if more_at is not None:
            footer = f"[More follows. Read it with offset {more_at}.]"
        elif cut_off:
            footer = f"[That is as much of the file as can be read here, its first {MAX_READ_BYTES:,} bytes.]"
        else:
            footer = "[That is the end of the file.]"

        return f"{header}\n{part}\n{footer}\n</skill_file>"

    return (
        Tool(
            name=ACTIVATE_SKILL_TOOL_NAME,
            description=(
                "Read a skill: the written guidance from specialists on a kind of work, one of those your instructions "
                "list. Call it by name before you start a task that one is for, and follow what it says. It gives "
                "the skill's instructions and lists the files that come with it, which read_skill_file reads and code "
                "can run. It does not run anything."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The skill's name, as your instructions list it."}
                },
                "required": ["name"],
            },
            function=activate,
        ),
        Tool(
            name=READ_SKILL_FILE_TOOL_NAME,
            description=(
                "Read a file that comes with a skill you have activated, such as a reference, a script, or a "
                "template, by its path in the skill's folder as activating it listed it. Give a folder's path to list "
                "what is in it. A long file is given in parts, and each says where the next starts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The skill's name."},
                    "path": {"type": "string", "description": "The file's path in the skill's folder."},
                    "offset": {
                        "type": "integer",
                        "description": "The character to start at, for the next part of a long file. Default 0.",
                    },
                },
                "required": ["name", "path"],
            },
            function=read_file,
        ),
    )
