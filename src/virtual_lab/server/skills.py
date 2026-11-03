"""The skills a conversation can be given (see virtual_lab.skills): those in the workspace's skills/ folder, and those
in the person's own ~/.agents/skills, which Claude Code, Codex, and other tools that read skills look in too, so that a
skill installed for one of them is here as well. Where both have a skill of one name, the workspace's is used.

A conversation is given the skills that were there when it was made, by name, and goes on with those of them that are
still there.

The person's skills are kept from the Data page: listed, turned off for new conversations, put in from a Git repository
or a folder on this machine, and deleted. A skill is put in as a copy in the workspace's skills/, so that it stays as it
was when it was put in, and what is deleted is only what is there.
"""

import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.workspace import Workspace
from virtual_lab.skills import (
    MAX_SKILLS,
    Skill,
    SkillError,
    SkillLibrary,
    copy_skill,
    discover_skills,
    files_in,
    find_skill_files,
    listing,
    parse_skill,
    read_body,
)

# Names a folder to look in beside the workspace's, in place of ~/.agents/skills, which a person may keep their skills
# somewhere else for, and which the tests use so that what is on the machine they run on does not change them
USER_SKILLS_DIR_VARIABLE = "VIRTUAL_LAB_USER_SKILLS_DIR"

# How long to give Git to fetch a repository of skills, and how much of a skill's instructions and its files to show
GIT_SECONDS = 180
PREVIEW_CHARS = 20_000
PREVIEW_FILES = 200
PREVIEW_FILE_CHARS = 6_000


def user_skills_dir() -> Path:
    """The person's own folder of skills."""
    named = os.environ.get(USER_SKILLS_DIR_VARIABLE)

    return Path(named).expanduser() if named else Path.home() / ".agents" / "skills"


def skill_roots(workspace: Workspace) -> list[tuple[str, Path]]:
    """The folders skills are looked for in, the most important first, each with what its skills are said to come
    from."""
    return [("workspace", workspace.skills_dir), ("user", user_skills_dir())]


def load_skills(workspace: Workspace) -> SkillLibrary:
    """The skills there are now, and what is wrong with the rest."""
    return discover_skills(skill_roots(workspace))


def check_skill_names(names: Any, library: SkillLibrary) -> list[str]:
    """The skills to give a conversation, without repeats.

    :raises ValueError: If it is not a list of the names of skills there are.
    """
    if not isinstance(names, (list, tuple)):
        raise ValueError(f"The skills to give are a list of their names, not {names!r}")
    known = {skill.name for skill in library.skills}
    if unknown := [name for name in names if not isinstance(name, str) or name not in known]:
        raise ValueError(f"There is no skill called {', '.join(map(repr, unknown))}")

    return list(dict.fromkeys(names))


def check_git_address(address: str) -> str:
    """The address of a repository to fetch skills from.

    Only https is fetched, and no name or password in it: the other ways Git can fetch from include ones that run a
    command, and a password in an address is shown in what Git prints and is kept in the shell's history.

    :raises ApiError: If it is not an address that can be fetched from.
    """
    text = address.strip()
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        parts, host = None, None
    if parts is None or parts.scheme != "https" or not host or any(character.isspace() for character in text):
        raise ApiError(422, "invalid", "Give the address of a Git repository, which begins with https://")
    if parts.username is not None or parts.password is not None:
        raise ApiError(422, "invalid", "The address of the repository cannot have a name or a password in it")

    return text


def fetch_repository(address: str, scratch: Path) -> Path:
    """A repository as it is now, without its history, in a folder of the scratch folder.

    :raises ApiError: If Git is not there, or cannot fetch it, or is not done in time.
    """
    destination = scratch / "repository"
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "https", "GIT_LFS_SKIP_SMUDGE": "1"}
    command = [
        "git",
        "-c",
        "core.symlinks=false",
        "clone",
        "--depth",
        "1",
        "--single-branch",
        "--no-tags",
        "--quiet",
        "--",
        address,
        str(destination),
    ]
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=GIT_SECONDS,
            env=environment,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        raise ApiError(
            422, "git_missing", "Git is not installed on this machine, and fetching a repository takes it"
        ) from None
    except subprocess.TimeoutExpired:
        raise ApiError(504, "timeout", f"Git did not finish fetching {address} in {GIT_SECONDS} seconds") from None
    if done.returncode != 0:
        said = " ".join(done.stderr.split())[-300:] or f"it stopped with status {done.returncode}"
        raise ApiError(422, "fetch_failed", f"Git could not fetch {address}: {said}")

    return destination


def check_folder(path: str) -> Path:
    """A folder on this machine to put skills in from.

    :raises ApiError: If it is not the full path of a folder.
    """
    text = path.strip()
    source = Path(text).expanduser()
    if not text or not source.is_absolute():
        raise ApiError(422, "invalid", f"Give the full path of a folder, which {text!r} is not")
    if not source.is_dir():
        raise ApiError(422, "invalid", f"There is no folder at {source}")

    return source


class Skills:
    """The skills the person keeps from the Data page."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._lock = threading.Lock()

    def describe(self) -> dict[str, Any]:
        """The skills there are, each with whether a new conversation is given it and whether it can be deleted from
        here, what was wrong with the SKILL.md files that could not be used, and the folders skills are looked in."""
        library = load_skills(self.workspace)
        turned_off = set(self.workspace.load_disabled_skills())

        return {
            "skills": [
                {
                    **skill.describe(),
                    "enabled": skill.name not in turned_off,
                    "removable": self.deletion_of(skill) is not None,
                }
                for skill in library.skills
            ],
            "problems": [{"path": str(problem.path), "message": problem.message} for problem in library.problems],
            "folders": [
                {"source": source, "path": str(path), "exists": path.is_dir()}
                for source, path in skill_roots(self.workspace)
            ],
        }

    def deletion_of(self, skill: Skill) -> Path | None:
        """What deleting a skill removes, which is its folder in the workspace's skills/, or None for one that is
        elsewhere or is the folder itself. A link to a folder is removed, and not what it leads to."""
        if skill.source != "workspace":
            return None
        try:
            root = self.workspace.skills_dir.resolve()
            target = skill.directory.parent.resolve() / skill.directory.name
        except (OSError, RuntimeError):
            return None

        return target if target != root and target.is_relative_to(root) else None

    def set_disabled(self, names: Any) -> dict[str, Any]:
        """Says which skills a new conversation is not given. A skill turned off that cannot be found now stays turned
        off, for when it is put back.

        :raises ValueError: If it is not a list of the names of skills there are.
        """
        library = load_skills(self.workspace)
        asked = check_skill_names(names, library)
        found = {skill.name for skill in library.skills}
        with self._lock:
            kept = [name for name in self.workspace.load_disabled_skills() if name not in found]
            self.workspace.save_disabled_skills(list(dict.fromkeys([*asked, *kept])))

        return self.describe()

    def install(self, git: str | None, path: str | None) -> dict[str, Any]:
        """Puts in the skills of a Git repository or of a folder on this machine, as copies, leaving those whose names
        are taken, and says which it did and which it left.

        :raises ApiError: If it is not one of the two, or cannot be fetched, or has no skill in it.
        """
        if (git is None) == (path is None):
            raise ApiError(422, "invalid", "Give the address of a Git repository or the path of a folder, and not both")
        with self._lock:
            if git is not None:
                address = check_git_address(git)
                with tempfile.TemporaryDirectory(prefix="lumi-skills-") as scratch:
                    result = self._put_in(fetch_repository(address, Path(scratch)), address)
            else:
                assert path is not None
                folder = check_folder(path)
                result = self._put_in(folder, str(folder))

        return {**self.describe(), **result}

    def _put_in(self, root: Path, where: str) -> dict[str, Any]:
        files = find_skill_files(root)
        if not files:
            raise ApiError(422, "no_skills", f"There is no skill in {where}: a skill is a folder with a SKILL.md in it")
        folder = self.workspace.skills_dir
        taken = {skill.name.casefold() for skill in load_skills(self.workspace).skills if skill.source == "workspace"}
        if folder.is_dir():
            taken |= {entry.name.casefold() for entry in folder.iterdir()}
        installed: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for file in files:
            try:
                skill = parse_skill(file, "workspace")
            except SkillError as error:
                skipped.append({"name": file.parent.name, "reason": str(error)})
                continue
            if skill.name.casefold() in taken:
                skipped.append({"name": skill.name, "reason": "you already have a skill with that name"})
                continue
            if len(taken) >= MAX_SKILLS:
                skipped.append({"name": skill.name, "reason": f"only {MAX_SKILLS} skills are used"})
                continue
            try:
                folder.mkdir(parents=True, exist_ok=True)
                left_out = copy_skill(skill.directory, folder / skill.name)
            except OSError as error:
                skipped.append({"name": skill.name, "reason": f"it could not be copied: {error.strerror or error}"})
                continue
            taken.add(skill.name.casefold())
            installed.append({"name": skill.name, "left_out": left_out})

        return {"installed": installed, "skipped": skipped}

    def remove(self, name: str) -> dict[str, Any]:
        """Deletes a skill that is in the workspace's skills/.

        :raises ApiError: If there is no such skill, or it is somewhere that other tools read too.
        """
        with self._lock:
            skill = load_skills(self.workspace).named(name)
            if skill is None:
                raise not_found(f"skill called {name!r}")
            target = self.deletion_of(skill)
            if target is None:
                raise ApiError(
                    409,
                    "not_yours",
                    f"{name} is in {skill.directory}, which is not where the lab keeps the skills it was given, and "
                    "may be read by other tools too. Turn it off here, or delete its folder yourself.",
                )
            try:
                if target.is_symlink():
                    target.unlink()
                else:
                    shutil.rmtree(target)
            except OSError as error:
                raise ApiError(500, "files", f"{name} could not be deleted: {error.strerror or error}") from error
            self.workspace.save_disabled_skills(
                [each for each in self.workspace.load_disabled_skills() if each != name]
            )

        return self.describe()

    def preview(self, name: str) -> dict[str, Any]:
        """What a skill tells the lead and the files that come with it, to read before it is trusted."""
        skill = load_skills(self.workspace).named(name)
        if skill is None:
            raise not_found(f"skill called {name!r}")
        try:
            instructions = read_body(skill)
        except SkillError as error:
            raise ApiError(409, "unreadable", str(error)) from error
        files, more = listing(files_in(skill.directory, skill.directory), PREVIEW_FILES, PREVIEW_FILE_CHARS)

        return {
            "name": skill.name,
            "instructions": instructions[:PREVIEW_CHARS],
            "characters": len(instructions),
            "files": files,
            "more_files": more,
        }
