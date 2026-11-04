"""Tests that the declared environment can actually install and run the code."""

import sys
import tomllib
from pathlib import Path

PYPROJECT_PATH = Path(__file__).parent.parent / "pyproject.toml"


def load_pyproject() -> dict:
    with open(PYPROJECT_PATH, "rb") as f:
        return tomllib.load(f)


def test_python_floor_matches_the_syntax_used() -> None:
    # The library uses backslashes inside f-string expressions and PEP 695 type parameters,
    # neither of which parses before 3.12.
    assert load_pyproject()["project"]["requires-python"] == ">=3.12"


def test_no_classifiers_below_the_python_floor() -> None:
    classifiers = load_pyproject()["project"]["classifiers"]

    assert "Programming Language :: Python :: 3.10" not in classifiers
    assert "Programming Language :: Python :: 3.11" not in classifiers
    assert "Programming Language :: Python :: 3.12" in classifiers


def test_running_on_a_supported_interpreter() -> None:
    assert sys.version_info >= (3, 12)
