"""Replaces the skills that come in src/virtual_lab/scientific_skills/ with those of a release of K-Dense's Scientific
Agent Skills, and writes the index that says which category each is in.

    git clone --depth 1 --branch v2.72.0 https://github.com/K-Dense-AI/scientific-agent-skills /tmp/sas
    python scripts/update_scientific_skills.py /tmp/sas

The skills are copied as they are, with their own files and notices, and nothing is edited. Only a skill's category is
added, which is read from the catalog in the release's docs/skills.md. A folder given without a .git folder, such as
one made by git archive, needs --ref, since the commit is what says which release was copied.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

DESTINATION = Path(__file__).resolve().parent.parent / "src" / "virtual_lab" / "scientific_skills"
SOURCE = {
    "name": "Scientific Agent Skills",
    "author": "K-Dense Inc.",
    "url": "https://github.com/K-Dense-AI/scientific-agent-skills",
    "license": "MIT",
}
LEFT_OUT = shutil.ignore_patterns(".git", ".DS_Store", "__pycache__", "*.pyc")
GROUP = re.compile(r"^## (.+?)\s*$")
CATEGORY = re.compile(r"^### (.+?)\s*$")
ENTRY = re.compile(r"^- \*\*\[[^\]]+\]\(\.\./skills/([^/)]+)/(?:SKILL\.md)?\)\*\*")
GROUP_PREFIX = "Scientific "


def categories_of(catalog: str) -> dict[str, dict[str, str]]:
    """Each skill's group and category, in the order the catalog lists them. A group with no categories in it, such as
    the databases, is its own category, named without the word the groups begin with."""
    found: dict[str, dict[str, str]] = {}
    group = category = None
    for line in catalog.splitlines():
        if match := GROUP.match(line):
            group, category = match.group(1), None
        elif match := CATEGORY.match(line):
            category = match.group(1)
        elif (match := ENTRY.match(line)) and group is not None:
            found[match.group(1)] = {
                "group": group,
                "category": category or group.removeprefix(GROUP_PREFIX),
            }

    return found


def size_of(folder: Path) -> tuple[int, int]:
    """The number of files in a folder and below it, and their bytes."""
    files = [path for path in folder.rglob("*") if path.is_file()]

    return len(files), sum(path.stat().st_size for path in files)


def commit_of(release: Path) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(release), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None

    return done.stdout.strip() or None


def build_index(release: Path, ref: str) -> dict[str, Any]:
    """The index of the skills in a release's skills/ folder.

    :raises SystemExit: If a skill is not in the catalog, or the catalog lists one that is not there.
    """
    plugin = json.loads((release / "plugin.json").read_text(encoding="utf-8"))
    categories = categories_of((release / "docs" / "skills.md").read_text(encoding="utf-8"))
    folders = sorted(path.name for path in (release / "skills").iterdir() if (path / "SKILL.md").is_file())
    if missing := sorted(set(folders) - set(categories)):
        raise SystemExit(f"These skills are not in docs/skills.md, so they have no category: {', '.join(missing)}")
    if extra := sorted(set(categories) - set(folders)):
        raise SystemExit(f"docs/skills.md lists skills that are not in skills/: {', '.join(extra)}")
    skills = {}
    for name in categories:
        files, size = size_of(release / "skills" / name)
        skills[name] = {**categories[name], "files": files, "bytes": size}

    return {"source": {**SOURCE, "version": plugin["version"], "ref": ref}, "skills": skills}


def update(release: Path, ref: str | None, destination: Path = DESTINATION) -> dict[str, Any]:
    """Copies a release's skills and licence into the destination and writes the index beside them."""
    commit = ref or commit_of(release)
    if commit is None:
        raise SystemExit("Say which commit this is with --ref, since the folder is not a Git clone")
    index = build_index(release, commit)
    if any(path.is_symlink() for path in (release / "skills").rglob("*")):
        raise SystemExit("The release has links in its skills, which are not copied")
    if (skills := destination / "skills").exists():
        shutil.rmtree(skills)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(release / "skills", skills, ignore=LEFT_OUT)
    shutil.copy2(release / "LICENSE.md", destination / "LICENSE.md")
    (destination / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("release", type=Path, help="a checkout of a release of the Scientific Agent Skills")
    parser.add_argument("--ref", help="the release's commit, where the folder is not a Git clone")
    arguments = parser.parse_args()
    index = update(arguments.release.resolve(), arguments.ref)
    print(f"{len(index['skills'])} skills of version {index['source']['version']} are in {DESTINATION}")


if __name__ == "__main__":
    sys.exit(main())
