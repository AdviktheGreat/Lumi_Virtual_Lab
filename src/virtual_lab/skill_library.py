"""The library of skills that comes with the lab, to be put in when a person chooses: K-Dense's Scientific Agent Skills
(https://github.com/K-Dense-AI/scientific-agent-skills, MIT License, Copyright 2025 K-Dense Inc.).

They are kept in scientific_skills/, beside the code, as they were released, each with its own files, and are not used
until they are put in: a skill that is put in is copied into the workspace's skills/, and from then on is one of the
person's own. Each is listed with the category K-Dense gives it, which scripts/update_scientific_skills.py reads from
the release and keeps in index.json, so that a page can offer them by topic.

Each skill says in its SKILL.md what license it is under. Most say MIT, BSD, or Apache, a few say GPL, two say that only
noncommercial use is allowed, and some say nothing, which is why a page shows the license of each beside it.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from virtual_lab.skills import SKILL_FILE_NAME, Skill, SkillError, parse_skill

LIBRARY_DIR_NAME = "scientific_skills"
INDEX_FILE_NAME = "index.json"
LIBRARY_SKILLS_DIR_NAME = "skills"
LIBRARY_SOURCE = "library"

# What a license says when it names none, in the words a skill's author used
NO_LICENSE = frozenset({"", "none", "unknown"})

# A license of more words than this is a sentence about the skill and not the name of a license, in which a mention of
# noncommercial use may be of the data the skill reads and not of the skill
LICENSE_NAME_CHARS = 60
NONCOMMERCIAL = re.compile(r"non-?commercial|\bnc\b", re.IGNORECASE)
COPYLEFT = re.compile(r"gpl", re.IGNORECASE)


def library_directory() -> Path:
    """The folder the library comes in."""
    return Path(__file__).resolve().parent / LIBRARY_DIR_NAME


def license_kind(license: str | None) -> str:
    """What a person ought to know of a skill's license before using it: "noncommercial" where it allows only that,
    "copyleft" where it is a GPL license, "none" where the skill says nothing, so that the library's own MIT license is
    what is left, and "other" for the rest, which a page shows as it is written."""
    text = " ".join((license or "").split())
    if text.lower() in NO_LICENSE:
        return "none"
    if len(text) <= LICENSE_NAME_CHARS:
        if NONCOMMERCIAL.search(text):
            return "noncommercial"
        if COPYLEFT.search(text):
            return "copyleft"

    return "other"


@dataclass(frozen=True)
class LibrarySkill:
    """A skill of the library: the skill itself, where K-Dense puts it, and how much there is of it."""

    skill: Skill
    group: str
    category: str
    files: int
    bytes: int

    @property
    def kind(self) -> str:
        return license_kind(self.skill.license)

    def describe(self) -> dict[str, Any]:
        """The skill in JSON's types, for a page that offers it, without where it is kept on this machine."""
        return {
            "name": self.skill.name,
            "description": self.skill.description,
            "group": self.group,
            "category": self.category,
            "license": self.skill.license,
            "license_kind": self.kind,
            "compatibility": self.skill.compatibility,
            "files": self.files,
            "bytes": self.bytes,
        }


@dataclass(frozen=True)
class Library:
    """The skills of a library, in the order its catalog lists them, where they came from, and the SKILL.md files that
    could not be used."""

    source: dict[str, str]
    skills: tuple[LibrarySkill, ...] = ()
    problems: tuple[str, ...] = ()

    def named(self, name: str) -> LibrarySkill | None:
        return next((entry for entry in self.skills if entry.skill.name == name), None)

    def categories(self) -> list[dict[str, Any]]:
        """Each category, with its group and how many skills are in it, in the order they are first listed."""
        found: dict[str, dict[str, Any]] = {}
        for entry in self.skills:
            found.setdefault(entry.category, {"name": entry.category, "group": entry.group, "count": 0})["count"] += 1

        return list(found.values())


def text_of(value: Any) -> str:
    return value if isinstance(value, str) else ""


def read_library(directory: Path) -> Library:
    """The library in a folder, which is empty where the folder has no index. A skill that cannot be used is left out
    and said of in the problems, and a skill the index does not list is not offered."""
    try:
        index = json.loads((directory / INDEX_FILE_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Library(source={})
    except (OSError, ValueError) as error:
        return Library(source={}, problems=(f"{directory / INDEX_FILE_NAME} cannot be read: {error}",))
    if not isinstance(index, dict) or not isinstance(index.get("skills"), dict):
        return Library(source={}, problems=(f"{directory / INDEX_FILE_NAME} does not list skills",))
    source = index.get("source")
    skills: list[LibrarySkill] = []
    problems: list[str] = []
    for name, entry in index["skills"].items():
        if not isinstance(entry, dict):
            problems.append(f"{name}: its entry in the index is not an object")
            continue
        file = directory / LIBRARY_SKILLS_DIR_NAME / str(name) / SKILL_FILE_NAME
        try:
            skill = parse_skill(file, LIBRARY_SOURCE)
        except SkillError as error:
            problems.append(f"{name}: {error}")
            continue
        skills.append(
            LibrarySkill(
                skill=skill,
                group=text_of(entry.get("group")),
                category=text_of(entry.get("category")) or text_of(entry.get("group")),
                files=entry["files"] if isinstance(entry.get("files"), int) else 0,
                bytes=entry["bytes"] if isinstance(entry.get("bytes"), int) else 0,
            )
        )

    return Library(
        source={key: text_of(value) for key, value in source.items()} if isinstance(source, dict) else {},
        skills=tuple(skills),
        problems=tuple(problems),
    )


def check_library_names(names: Any, library: Library) -> list[str]:
    """The skills of the library to put in, without repeats.

    :raises ValueError: If it is not a list of the names of skills the library has.
    """
    if not isinstance(names, (list, tuple)):
        raise ValueError(f"The skills to put in are a list of their names, not {names!r}")
    known = {entry.skill.name for entry in library.skills}
    if unknown := [name for name in names if not isinstance(name, str) or name not in known]:
        raise ValueError(f"The library has no skill called {', '.join(map(repr, unknown))}")

    return list(dict.fromkeys(names))


def files_of(library: Library, names: Sequence[str]) -> list[Path]:
    """The SKILL.md of each of the skills, in the order given."""
    return [entry.skill.file for name in names if (entry := library.named(name)) is not None]
