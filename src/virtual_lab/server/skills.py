"""The skills a conversation can be given (see virtual_lab.skills): those in the workspace's skills/ folder, and those
in the person's own ~/.agents/skills, which Claude Code, Codex, and other tools that read skills look in too, so that a
skill installed for one of them is here as well. Where both have a skill of one name, the workspace's is used.

A conversation is given the skills that were there when it was made, by name, and goes on with those of them that are
still there.
"""

import os
from pathlib import Path
from typing import Any

from virtual_lab.server.workspace import Workspace
from virtual_lab.skills import SkillLibrary, discover_skills

# Names a folder to look in beside the workspace's, in place of ~/.agents/skills, which a person may keep their skills
# somewhere else for, and which the tests use so that what is on the machine they run on does not change them
USER_SKILLS_DIR_VARIABLE = "VIRTUAL_LAB_USER_SKILLS_DIR"


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
