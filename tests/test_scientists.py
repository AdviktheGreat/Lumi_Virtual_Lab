"""Tests for the library of scientists."""

import pytest

from virtual_lab.scientists import SCIENTISTS, scientist


def test_scientists_are_found_by_title_and_have_distinct_ones() -> None:
    titles = [agent.title for agent in SCIENTISTS]

    assert len(set(titles)) == len(titles)
    assert scientist("Biostatistician").title == "Biostatistician"
    with pytest.raises(KeyError):
        scientist("Astrologer")
