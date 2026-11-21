"""The stand-ins that the scripted server of the browser tests puts in place of Docker's containers take what the real
functions take, so that a parameter that is added to one of them is not found missing only when a browser test makes a
call that the unit tests' own stand-ins do not reach."""

import importlib.util
import inspect
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from virtual_lab.paperagents import matching
from virtual_lab.paperagents import reference as referencing

SCRIPTED_SERVER = Path(__file__).resolve().parent.parent / "web" / "e2e" / "scripted_server.py"


@pytest.fixture(scope="module")
def scripted() -> Any:
    spec = importlib.util.spec_from_file_location("scripted_server_under_test", SCRIPTED_SERVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(spec.name, None)


def names_of(function: Callable[..., Any]) -> list[str]:
    return list(inspect.signature(function).parameters)


@pytest.mark.parametrize(
    ("real", "stand_in"),
    [
        (matching.runner_for, "stand_in_calling_runner"),
        (matching.run_calls, "stand_in_calling"),
        (referencing.remove_runs, "stand_in_remove_runs"),
    ],
)
def test_a_stand_in_of_the_scripted_server_takes_the_parameters_of_what_it_replaces(
    scripted: ModuleType, real: Callable[..., Any], stand_in: str
) -> None:
    assert names_of(getattr(scripted, stand_in)) == names_of(real)
