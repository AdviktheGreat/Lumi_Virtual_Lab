"""The skills a conversation can be given (see virtual_lab.skills): those in the workspace's skills/ folder, those in
the person's own ~/.agents/skills, which Claude Code, Codex, and other tools that read skills look in too, so that a
skill installed for one of them is here as well, and those that come with the lab. Where two have a skill of one name,
the first of these is used, so that a person's own skill takes the place of one that came with the lab.

A conversation is given the skills that were there when it was made, by name, and goes on with those of them that are
still there.

The person's skills are kept from the Skills page: listed, turned off for new conversations, put in from a Git
repository, a folder on this machine, or the library that comes with the lab (see virtual_lab.skill_library), and
deleted. A skill is put in as a copy in the workspace's skills/, so that it stays as it was when it was put in, and what
is deleted is only what is there.
"""

import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.workspace import Workspace
from virtual_lab.skill_library import check_library_names, files_of, library_directory, read_library
from virtual_lab.skills import (
    BUILTIN_SOURCE,
    MAX_COPIED_BYTES,
    MAX_COPIED_FILES,
    MAX_SKILLS,
    SKIPPED_DIRECTORIES,
    Skill,
    SkillError,
    SkillLibrary,
    builtin_skills_directory,
    catalog_use,
    copy_skill,
    discover_skills,
    files_in,
    listing,
    parse_skill,
    read_body,
    search_skill_files,
)

# Names a folder to look in beside the workspace's, in place of ~/.agents/skills, which a person may keep their skills
# somewhere else for, and which the tests use so that what is on the machine they run on does not change them
USER_SKILLS_DIR_VARIABLE = "VIRTUAL_LAB_USER_SKILLS_DIR"

# Names a folder to read the skills that come with the lab from, in place of the ones shipped with it, which an empty
# folder does away with, and which the tests use so that what ships does not change what they count
BUILTIN_SKILLS_DIR_VARIABLE = "VIRTUAL_LAB_BUILTIN_SKILLS_DIR"

# Names a folder to read the library of skills that can be put in from, in place of the one shipped with the lab, which
# the tests use so that they work with a few skills and not the hundred and more that ship
SKILL_LIBRARY_DIR_VARIABLE = "VIRTUAL_LAB_SKILL_LIBRARY_DIR"

# What of a folder that is uploaded is not kept, beside the folders a repository holds that a skill does not need
UPLOAD_SKIPPED_FILES = frozenset({".DS_Store"})
UPLOAD_PATH_CHARS = 500
UPLOAD_PATH_PARTS = 12
UPLOAD_FOLDER_CHARS = 100

# How long to give Git to fetch a repository of skills, how much of the disk it may take while it does, how often that
# is looked at, how many folders to search for skills in a folder on this machine, which may be a whole disk, and how
# much of a skill's instructions and its files to show
GIT_SECONDS = 300
GIT_BYTES = 1_000_000_000
GIT_WATCH_SECONDS = 1.0
MAX_SEARCHED_FOLDERS = 5_000
PREVIEW_CHARS = 20_000
PREVIEW_FILES = 200
PREVIEW_FILE_CHARS = 6_000


def user_skills_dir() -> Path:
    """The person's own folder of skills."""
    named = os.environ.get(USER_SKILLS_DIR_VARIABLE)

    return Path(named).expanduser() if named else Path.home() / ".agents" / "skills"


def builtin_skills_dir() -> Path:
    """The folder of the skills that come with the lab."""
    named = os.environ.get(BUILTIN_SKILLS_DIR_VARIABLE)

    return Path(named).expanduser() if named else builtin_skills_directory()


def skill_library_dir() -> Path:
    """The folder of the library of skills that can be put in."""
    named = os.environ.get(SKILL_LIBRARY_DIR_VARIABLE)

    return Path(named).expanduser() if named else library_directory()


def skill_roots(workspace: Workspace) -> list[tuple[str, Path]]:
    """The folders skills are looked for in, the most important first, each with what its skills are said to come
    from."""
    return [("workspace", workspace.skills_dir), ("user", user_skills_dir()), (BUILTIN_SOURCE, builtin_skills_dir())]


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


def size_of(folder: Path) -> int:
    """The bytes in the files in a folder and below it."""
    total = 0
    for directory, _, files in os.walk(folder):
        for file in files:
            try:
                total += os.lstat(os.path.join(directory, file)).st_size
            except OSError:
                continue

    return total


def stop_git(process: "subprocess.Popen[str]") -> None:
    """Stops Git and what it started, such as the program that talks https for it, which a kill of Git alone leaves
    going."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except OSError:
        pass
    try:
        process.communicate(timeout=10)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def fetch_repository(address: str, scratch: Path) -> Path:
    """A repository as it is now, without its history, in a folder of the scratch folder.

    :raises ApiError: If Git is not there, or cannot fetch it, or is not done in time, or it is too big.
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
        process = subprocess.Popen(
            command,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError:
        raise ApiError(
            422, "git_missing", "Git is not installed on this machine, and fetching a repository takes it"
        ) from None
    deadline = time.monotonic() + GIT_SECONDS
    try:
        while True:
            try:
                _, said = process.communicate(timeout=max(0.0, min(GIT_WATCH_SECONDS, deadline - time.monotonic())))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    stop_git(process)
                    raise ApiError(
                        504, "timeout", f"Git did not finish fetching {address} in {GIT_SECONDS} seconds"
                    ) from None
                if size_of(destination) > GIT_BYTES:
                    stop_git(process)
                    raise ApiError(
                        422,
                        "too_big",
                        f"{address} is more than {GIT_BYTES // 1_000_000:,} MB, which is more than a library of skills "
                        "needs. Clone it yourself and give the folder the skills are in.",
                    ) from None
    except BaseException:
        if process.poll() is None:
            stop_git(process)
        raise
    if process.returncode != 0:
        detail = " ".join((said or "").split())[-300:] or f"it stopped with status {process.returncode}"
        raise ApiError(422, "fetch_failed", f"Git could not fetch {address}: {detail}")

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


def check_upload_path(path: Any) -> PurePosixPath | None:
    """Where a file of an uploaded folder is in it, as a path from the folder, or None for one that is not kept: what a
    repository's folders hold that a skill does not need.

    :raises ApiError: If it is not the path of a file in the folder, which one that leads out of it, or is written
        with backslashes, is not.
    """
    if not isinstance(path, str) or not path or len(path) > UPLOAD_PATH_CHARS:
        raise ApiError(422, "invalid", f"A file of the folder is named {path!r}, which is not a path that can be kept")
    parts = path.split("/")
    if (
        path.startswith("/")
        or "\\" in path
        or any(part in ("", ".", "..") or "\x00" in part for part in parts)
        or len(parts) > UPLOAD_PATH_PARTS
    ):
        raise ApiError(422, "invalid", f"{path!r} is not a path in the folder: it must lead down into it")
    if UPLOAD_SKIPPED_FILES.intersection(parts[-1:]) or SKIPPED_DIRECTORIES.intersection(parts[:-1]):
        return None

    return PurePosixPath(path)


def check_upload_folder(name: Any) -> str:
    """The name to give a folder that is uploaded, which is the last of what it was called, as it is what a skill is
    called where its SKILL.md does not say.

    :raises ApiError: If it is not text.
    """
    if not isinstance(name, str):
        raise ApiError(422, "invalid", "Say what the folder is called")
    last = name.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    kept = "".join(character for character in last if character.isprintable())[:UPLOAD_FOLDER_CHARS].strip()

    return kept if kept not in ("", ".", "..") else "skill"


class Skills:
    """The skills the person keeps from the Skills page."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._lock = threading.Lock()

    def describe(self) -> dict[str, Any]:
        """The skills there are, each with whether a new conversation is given it and whether it can be deleted from
        here, what was wrong with the SKILL.md files that could not be used, the folders skills are looked in, and what
        listing the skills that are on takes of every conversation."""
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
            "catalog": catalog_use([skill for skill in library.skills if skill.name not in turned_off]),
        }

    def taken_names(self, library: SkillLibrary) -> set[str]:
        """The names, in lower case, that a skill put in cannot have, which are those of a skill in the workspace's
        skills/ and of any folder there."""
        taken = {skill.name.casefold() for skill in library.skills if skill.source == "workspace"}
        if self.workspace.skills_dir.is_dir():
            taken |= {entry.name.casefold() for entry in self.workspace.skills_dir.iterdir()}

        return taken

    def library(self) -> dict[str, Any]:
        """The skills that come with the lab to be put in, each with whether it has been, the categories they are in,
        and where they came from."""
        offered = read_library(skill_library_dir())
        taken = self.taken_names(load_skills(self.workspace))

        return {
            "source": offered.source,
            "skills": [
                {**entry.describe(), "installed": entry.skill.name.casefold() in taken} for entry in offered.skills
            ],
            "categories": offered.categories(),
            "problems": list(offered.problems),
        }

    def install_from_library(self, names: Any) -> dict[str, Any]:
        """Puts in copies of skills of the library that comes with the lab, leaving those whose names are taken, and
        says which it did and which it left.

        :raises ValueError: If it is not a list of the names of skills the library has.
        :raises ApiError: If the list is empty.
        """
        offered = read_library(skill_library_dir())
        asked = check_library_names(names, offered)
        if not asked:
            raise ApiError(422, "invalid", "Choose at least one skill to put in")
        with self._lock:
            result = self._copy_in(files_of(offered, asked))

        return {**self.describe(), **result}

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
        with self._lock:
            library = load_skills(self.workspace)
            asked = check_skill_names(names, library)
            found = {skill.name for skill in library.skills}
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
        if git is not None:
            address = check_git_address(git)
            with tempfile.TemporaryDirectory(prefix="lumi-skills-") as scratch:
                result = self._put_in(fetch_repository(address, Path(scratch)), address)
        else:
            assert path is not None
            folder = check_folder(path)
            result = self._put_in(folder, str(folder))

        return {**self.describe(), **result}

    def upload(self, folder: Any, files: Sequence[tuple[Any, BinaryIO]]) -> dict[str, Any]:
        """Puts in the skills of a folder that was sent as its files, each with where it is in the folder, as copies,
        leaving those whose names are taken, and says which it did and which it left. A folder with a SKILL.md at its
        top is a skill, and one without is searched for skills, as a folder on this machine is.

        :raises ApiError: If a path leads out of the folder, or the folder has too many files or is too big, or has no
            skill in it.
        """
        name = check_upload_folder(folder)
        with tempfile.TemporaryDirectory(prefix="lumi-skills-") as scratch:
            root = Path(scratch) / name
            root.mkdir()
            kept: set[PurePosixPath] = set()
            size = 0
            for sent, content in files:
                relative = check_upload_path(sent)
                if relative is None:
                    continue
                if relative in kept:
                    raise ApiError(422, "invalid", f"The folder has {sent!r} twice")
                if len(kept) >= MAX_COPIED_FILES:
                    raise ApiError(
                        422,
                        "too_many_files",
                        f"The folder has more than {MAX_COPIED_FILES:,} files, which is more than a skill needs. "
                        "Upload fewer skills at once.",
                    )
                kept.add(relative)
                target = root.joinpath(*relative.parts)
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    out = open(target, "wb")
                except OSError as error:
                    # A file that is also a folder of the others, for one
                    raise ApiError(
                        422, "invalid", f"{sent!r} cannot be kept with the other files: {error.strerror or error}"
                    ) from error
                with out:
                    while chunk := content.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_COPIED_BYTES:
                            raise ApiError(
                                413,
                                "too_large",
                                f"The folder is more than {MAX_COPIED_BYTES // 1_000_000} MB, which is more than a "
                                "skill needs.",
                            )
                        out.write(chunk)
            result = self._put_in(root, f"the folder {name}")

        return {**self.describe(), **result}

    def _put_in(self, root: Path, where: str) -> dict[str, Any]:
        # Searching can take a while, so only the copying is done under the lock
        files, searched_all = search_skill_files(root, MAX_SEARCHED_FOLDERS)
        if not searched_all:
            raise ApiError(
                422,
                "too_many_folders",
                f"There are more than {MAX_SEARCHED_FOLDERS:,} folders in {where}, which is too many to search for "
                "skills. Give the folder the skills are in.",
            )
        if not files:
            raise ApiError(422, "no_skills", f"There is no skill in {where}: a skill is a folder with a SKILL.md in it")
        with self._lock:
            return self._copy_in(files)

    def _copy_in(self, files: list[Path]) -> dict[str, Any]:
        folder = self.workspace.skills_dir
        library = load_skills(self.workspace)
        # What is used counts toward the most there can be wherever a skill is found, and what is taken is a name that a
        # folder of the workspace's has, or is called
        used = {skill.name.casefold() for skill in library.skills}
        taken = self.taken_names(library)
        installed: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for file in files:
            try:
                skill = parse_skill(file, "workspace")
            except SkillError as error:
                skipped.append({"name": file.parent.name, "reason": str(error)})
                continue
            key = skill.name.casefold()
            if key in taken:
                skipped.append({"name": skill.name, "reason": "you already have a skill with that name"})
                continue
            if key not in used and len(used) >= MAX_SKILLS:
                skipped.append({"name": skill.name, "reason": f"only {MAX_SKILLS} skills are used"})
                continue
            try:
                folder.mkdir(parents=True, exist_ok=True)
                left_out = copy_skill(skill.directory, folder / skill.name)
            except OSError as error:
                skipped.append({"name": skill.name, "reason": f"it could not be copied: {error.strerror or error}"})
                continue
            taken.add(key)
            used.add(key)
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
            if target is None and skill.source == BUILTIN_SOURCE:
                raise ApiError(
                    409,
                    "not_yours",
                    f"{name} comes with the lab, so it cannot be deleted. Turn it off here to leave it out of new "
                    "programs, or put in a skill of the same name, which is used in its place.",
                )
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
            # One in ~/.agents/skills or that comes with the lab, which this one hid, is now in the list, and is as it
            # was turned on or off
            if load_skills(self.workspace).named(name) is None:
                self.workspace.save_disabled_skills(
                    [each for each in self.workspace.load_disabled_skills() if each != name]
                )

        return self.describe()

    def preview(self, name: str) -> dict[str, Any]:
        """What a skill tells the lead and the files that come with it, to read before it is trusted."""
        skill = load_skills(self.workspace).named(name)
        if skill is None:
            raise not_found(f"skill called {name!r}")

        return self.preview_of(skill)

    def preview_library(self, name: str) -> dict[str, Any]:
        """What a skill of the library tells the lead and its files, to read before it is put in."""
        entry = read_library(skill_library_dir()).named(name)
        if entry is None:
            raise not_found(f"skill called {name!r} in the library")

        return self.preview_of(entry.skill)

    @staticmethod
    def preview_of(skill: Skill) -> dict[str, Any]:
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
