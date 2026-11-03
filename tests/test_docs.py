"""Tests that the README and docs pages link correctly and that the license notices stay in place."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DOC_FILES = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
ADAPTED_NOTICE_LINE = re.compile(r"^\s{3,}(src/virtual_lab/\S+)\s{2,}", re.MULTILINE)


def prose_lines(path: Path) -> list[str]:
    """The lines of a markdown file outside code fences."""
    lines, in_fence = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence:
            lines.append(line)
    return lines


def anchors_of(path: Path) -> set[str]:
    """GitHub's anchor for each heading, with -1, -2 suffixes on repeats."""
    seen: dict[str, int] = {}
    anchors = set()
    for line in prose_lines(path):
        match = HEADING.match(line)
        if not match:
            continue
        text = re.sub(r"`|\*|_", "", re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", match.group(2)))
        slug = re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def header_of(path: Path) -> str:
    """The module docstring of a Python file, or the comment block that opens any other file."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        return ast.get_docstring(ast.parse(text)) or ""
    lines = []
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines)


def relative_links(path: Path) -> list[str]:
    links = []
    for line in prose_lines(path):
        links += [target for target in LINK.findall(line) if not re.match(r"[a-z][a-z0-9+.-]*:", target)]
    return links


def test_the_docs_pages_exist() -> None:
    assert (ROOT / "README.md").is_file()
    assert len(DOC_FILES) > 1


@pytest.mark.parametrize("doc", DOC_FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_relative_links_resolve(doc: Path) -> None:
    for target in relative_links(doc):
        file_part, _, fragment = target.partition("#")
        destination = (doc.parent / file_part).resolve() if file_part else doc
        assert destination.exists(), f"{doc.name} links to {target}, which does not exist"
        if fragment and destination.suffix == ".md":
            assert fragment in anchors_of(destination), f"{doc.name} links to {target}, which has no such heading"


def test_the_anchor_check_can_fail(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text("# Title\n\n## Two words\n\n## Two words\n\n```\n# not a heading\n```\n", encoding="utf-8")

    assert anchors_of(page) == {"title", "two-words", "two-words-1"}


def test_the_readme_names_the_project_it_is() -> None:
    first_line = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]

    assert first_line == "# Lumi Virtual Lab"


def test_license_keeps_the_original_notice_beside_lumis() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    assert text.startswith("MIT License")
    assert "Copyright (c) 2026 Kyle Swanson" in text
    assert "Copyright (c) 2026 Advik Anand" in text
    assert "Permission is hereby granted, free of charge" in text


def test_notice_credits_what_lumi_builds_on() -> None:
    text = (ROOT / "NOTICE").read_text(encoding="utf-8")

    for credit in [
        "github.com/zou-group/virtual-lab",
        "snap-stanford/Biomni",
        "Apache License, Version 2.0",
        "Future-House/BixBench",
        "BixBench-Verified-50",
        "SIL Open Font License",
    ]:
        assert credit in text, f"NOTICE does not mention {credit}"


def test_notice_names_files_that_exist_and_say_they_are_adapted() -> None:
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    adapted = ADAPTED_NOTICE_LINE.findall(notice.split("Adapted.", 1)[1].split("Not included.", 1)[0])

    assert len(adapted) >= 8
    for name in adapted:
        path = ROOT / name
        assert path.is_file(), f"NOTICE lists {name}, which does not exist"
        assert "biomni" in header_of(path).lower(), f"{name} does not name Biomni in its header"


def test_notice_lists_the_unmodified_biomni_paths() -> None:
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")

    for name in [
        "src/virtual_lab/sandbox/biomni_package/biomni/",
        "src/virtual_lab/sandbox/biomni_package/license_info.md",
        "src/virtual_lab/sandbox/biomni_package/LICENSE",
        "src/virtual_lab/sandbox/biomni_env/",
        "src/virtual_lab/biomni_env_desc.py",
    ]:
        assert name in notice, f"NOTICE does not list {name}"
        assert (ROOT / name).exists(), f"NOTICE lists {name}, which does not exist"


def test_the_vendored_biomni_license_is_the_apache_text() -> None:
    text = (ROOT / "src/virtual_lab/sandbox/biomni_package/LICENSE").read_text(encoding="utf-8")

    assert "Apache License" in text
    assert "Version 2.0, January 2004" in text


def test_the_sandbox_notice_points_to_the_license_and_the_root_notice() -> None:
    text = (ROOT / "src/virtual_lab/sandbox/NOTICE").read_text(encoding="utf-8")

    assert "biomni_package/LICENSE" in text
    assert "NOTICE" in text
