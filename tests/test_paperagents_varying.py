"""Tests of trying a claim's calculation again with something changed, which a person asks for: that what may be changed
is held to the arguments that the call was given and to values that an argument can be given as, that a claim that was
not attempted or was held to a printed line has no call to make again, that the call is made as the code's own function
with nothing changed and with the changes, that what comes of each is said as it is (a number at the place, no number
there, not the same each time, an error, not made), that a variant is comparable only if the call with nothing changed
gave what the tutorial got, that whether it rounds to the paper's number is said and is not a reproduction, and that the
claim's own result is never touched.

Some runs are made on this machine by the same runner that runs in a container, so that real calls of real functions are
tested without an image; the rest are made with a stand-in for the runner, so that each way a call can end is.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from test_paperagents_checking import ok, stopped
from test_paperagents_reproducing import Scripted, claim, detail_of
from test_paperagents_toolmaking import LocalRunner, recorded

from virtual_lab.paperagents import reproducing, varying, written
from virtual_lab.paperagents import toolmaking as making

__all__ = ["recorded"]

QUOTE = "The mean of the shifted values was 6.0 (Fig. 3)."
PLACE = "[2.5, 3.5]"
CAUSE_WORDS = ("because", "caused", "due to", "the reason", "proves", "verified")


def detail_of_run(recorded: tuple[Path, list[dict[str, Any]], Any]) -> dict[str, Any]:
    _, details, _ = recorded

    return {**detail_of(details[0]["calls"]), "id": details[0]["id"], "path": details[0]["path"]}


def tried(recorded: tuple[Path, list[dict[str, Any]], Any]) -> dict[str, Any]:
    """The claim of 6.0, held to what the second call of the script gave, as the trying of the claims keeps it."""
    detail = detail_of_run(recorded)
    run = reproducing.Tutorial(detail["path"], "script", detail["id"], detail, None, ("figure 3",))
    [entry] = reproducing.reproduce([claim("6.0", QUOTE, "m")], [run], Scripted({QUOTE: PLACE})).claims
    assert entry["status"] == "reproduced" and entry["link"]["call"] == 2, entry

    return entry


def planned(recorded: Any, changes: Any, entry: dict[str, Any] | None = None, detail: Any = ...) -> varying.Plan:
    repo, _, _ = recorded

    return varying.plan(entry or tried(recorded), detail_of_run(recorded) if detail is ... else detail, repo, changes)


class Standing:
    """Stands in for the runner: what it is given is kept, and what the calls gave is what it is told."""

    def __init__(
        self,
        control: list[Any] | None = None,
        variant: list[Any] | None = None,
        ended: str = "done",
        repeats: int = 2,
    ) -> None:
        self.tools = making.ToolLimits(repeats=repeats)
        self.results = [control or [ok(6.0), ok(6.0)], variant or [ok(9.0), ok(9.0)]]
        self.ended = ended
        self.seen: list[dict[str, Any]] = []

    def replay(self, source: str, function: str, cases: Any, seconds: float) -> making.Replay:
        self.seen.append({"source": source, "function": function, "cases": list(cases), "seconds": seconds})

        return making.Replay(self.ended, 0, self.results, [])


def gave(value: Any, kind: str = "float") -> dict[str, Any]:
    return ok(value, kind)


class TestWhatMayBeChanged:
    ARGS = {"values": [2.5, 3.5], "scale": 2, "name": "x"}

    @pytest.mark.parametrize(
        "value",
        [None, True, "text", 3, 2.5, [1, 2.5, "x", None], {"a": [1, {"b": 2}]}, {}, []],
    )
    def test_text_a_truth_value_nothing_a_finite_number_and_lists_and_tables_of_those_are_plain(
        self, value: Any
    ) -> None:
        assert varying.is_plain(value) is True

    @pytest.mark.parametrize(
        "value",
        [float("nan"), float("inf"), {1: 2}, {"$float": "nan"}, {"a": {"$float": "inf"}}, {1, 2}, object(), (1, 2)],
    )
    def test_anything_else_is_not(self, value: Any) -> None:
        assert varying.is_plain(value) is False

    def test_a_value_that_is_too_deep_is_not_plain(self) -> None:
        deep: Any = 1
        for _ in range(varying.MAX_DEPTH + 1):
            deep = [deep]
        assert varying.is_plain(deep) is False
        assert varying.is_plain(deep[0]) is True

    def test_each_change_is_named_with_what_the_argument_was_and_what_it_is_to_be(self) -> None:
        found = varying.check_changes({"scale": 3, "values": [1.5]}, self.ARGS)
        assert found == [
            {"name": "scale", "was": 2, "now": 3},
            {"name": "values", "was": [2.5, 3.5], "now": [1.5]},
        ]

    @pytest.mark.parametrize(
        ("changes", "said"),
        [
            (None, "Name the arguments"),
            ({}, "Name the arguments"),
            ([("scale", 3)], "Name the arguments"),
            ({"nothing": 3}, "was not given an argument called nothing. It was given name, scale, values"),
            ({"scale": 2}, "scale was given that value, so it is not a change"),
            ({"values": [2.5, 3.5]}, "values was given that value"),
            ({"scale": float("nan")}, "not one that an argument is given as"),
            ({"scale": {1, 2}}, "not one that an argument is given as"),
            ({"name": "x" * (varying.MAX_VALUE_CHARS + 1)}, "of at most"),
            ({1: 3}, "The name of an argument is text"),
        ],
    )
    def test_what_is_not_a_change_of_an_argument_that_the_call_was_given_is_refused(
        self, changes: Any, said: str
    ) -> None:
        with pytest.raises(varying.Refused) as refused:
            varying.check_changes(changes, self.ARGS)
        assert refused.value.code == "invalid" and said in refused.value.message

    def test_a_whole_number_in_place_of_the_same_number_as_a_fraction_is_a_change_and_a_truth_value_for_one_is(
        self,
    ) -> None:
        assert varying.check_changes({"scale": 2.0}, self.ARGS)[0]["now"] == 2.0
        assert varying.check_changes({"scale": True}, {"scale": 1})[0]["now"] is True

    def test_no_more_than_the_most_are_changed_at_once(self) -> None:
        args = {f"a{number}": 0 for number in range(varying.MOST_CHANGES + 1)}
        assert len(varying.check_changes({name: 1 for name in list(args)[: varying.MOST_CHANGES]}, args)) == 5
        with pytest.raises(varying.Refused, match="At most 5"):
            varying.check_changes({name: 1 for name in args}, args)

    def test_the_longest_name_and_the_longest_value_that_are_allowed_are_taken(self) -> None:
        name = "n" * varying.MAX_NAME_CHARS
        value = "v" * (varying.MAX_VALUE_CHARS - 2)
        assert len(json.dumps(value)) == varying.MAX_VALUE_CHARS
        assert varying.check_changes({name: value}, {name: "was"}) == [{"name": name, "was": "was", "now": value}]
        with pytest.raises(varying.Refused, match="of at most"):
            varying.check_changes({name: value + "v"}, {name: "was"})

    def test_a_table_with_its_keys_in_another_order_is_the_same_value_and_not_a_change(self) -> None:
        with pytest.raises(varying.Refused, match="so it is not a change"):
            varying.check_changes({"options": {"b": 2, "a": 1}}, {"options": {"a": 1, "b": 2}})

    def test_a_name_that_is_too_long_is_refused(self) -> None:
        name = "n" * (varying.MAX_NAME_CHARS + 1)
        with pytest.raises(varying.Refused, match="text"):
            varying.check_changes({name: 1}, {name: 0})


class TestWhatCanBeMadeAgain:
    def test_a_claim_that_was_held_to_a_call_is_planned_with_what_the_call_was_given_and_what_it_is_to_be(
        self, recorded: Any
    ) -> None:
        found = planned(recorded, {"scale": 3})
        assert (found.module, found.function, found.positional) == ("fixture.core", "mean", [])
        assert found.case.args == {"values": [2.5, 3.5], "scale": 2}
        assert found.changed == {"values": [2.5, 3.5], "scale": 3}
        assert found.changes == [{"name": "scale", "was": 2, "now": 3}]

    @pytest.mark.parametrize("status", ["reproduced", "partly", "not_reproduced"])
    def test_a_claim_that_was_tried_is_planned_whatever_came_of_it(self, recorded: Any, status: str) -> None:
        assert planned(recorded, {"scale": 3}, {**tried(recorded), "status": status}).changes

    def test_a_claim_that_was_not_attempted_has_no_call_that_it_was_held_to(self, recorded: Any) -> None:
        entry = {**tried(recorded), "status": "not_attempted", "reason": "no_code", "link": None}
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, entry)
        assert refused.value.code == "not_attempted"
        entry = {**tried(recorded), "link": None}
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, entry)
        assert refused.value.code == "not_attempted"
        entry = {**tried(recorded), "status": "not_attempted", "reason": "no_code"}
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, entry)
        assert refused.value.code == "not_attempted"

    def test_a_claim_that_was_held_to_a_line_that_was_printed_has_no_call_to_make_again(self, recorded: Any) -> None:
        entry = tried(recorded)
        printed = {**entry, "link": {**entry["link"], "source": "line", "call": None}}
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, printed)
        assert refused.value.code == "not_a_call" and "printed" in refused.value.message
        printed_with_a_call = {**entry, "link": {**entry["link"], "source": "line"}}
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, printed_with_a_call)
        assert refused.value.code == "not_a_call"
        odd = {**entry, "link": {**entry["link"], "call": "2"}}
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, odd)
        assert refused.value.code == "not_a_call"

    def test_a_tutorial_whose_record_is_gone_or_did_not_run_to_its_end_has_nothing_to_make_again(
        self, recorded: Any
    ) -> None:
        for detail in (None, {**detail_of_run(recorded), "status": "failed"}):
            with pytest.raises(varying.Refused) as refused:
                planned(recorded, {"scale": 3}, detail=detail)
            assert refused.value.code == "no_record"

    def test_a_call_that_is_not_in_the_record_is_refused(self, recorded: Any) -> None:
        entry = tried(recorded)
        gone = {**entry, "link": {**entry["link"], "call": 99}}
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, gone)
        assert refused.value.code == "no_call"

    @pytest.mark.parametrize(
        ("change", "said"),
        [
            ({"method": True}, "method of a class"),
            ({"qualname": "Counter.mean"}, "inside another function or a class"),
            ({"variadic": True}, "*args or **kwargs"),
        ],
    )
    def test_a_call_of_a_method_a_nested_function_or_one_with_args_and_kwargs_cannot_be_called_alone(
        self, recorded: Any, change: dict[str, Any], said: str
    ) -> None:
        detail = copy.deepcopy(detail_of_run(recorded))
        detail["calls"][1].update(change)
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, detail=detail)
        assert refused.value.code == "cannot_call" and said in refused.value.message

    def test_a_call_that_was_given_an_object_cannot_be_made_again_from_what_json_has(self, recorded: Any) -> None:
        detail = copy.deepcopy(detail_of_run(recorded))
        detail["calls"][1]["args"]["values"] = {"type": "DataFrame", "plain": False}
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, detail=detail)
        assert refused.value.code == "cannot_call" and "DataFrame" in refused.value.message

    def test_a_function_that_cannot_be_read_from_the_code_cannot_be_called_directly(self, recorded: Any) -> None:
        detail = copy.deepcopy(detail_of_run(recorded))
        detail["calls"][1]["module"] = "fixture.nowhere"
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"scale": 3}, detail=detail)
        assert refused.value.code == "cannot_call" and "cannot be read from the code" in refused.value.message

    def test_what_is_asked_that_is_not_fit_is_refused_after_the_rest(self, recorded: Any) -> None:
        with pytest.raises(varying.Refused) as refused:
            planned(recorded, {"nothing": 3})
        assert refused.value.code == "invalid"


class TestWhatAPersonMayChoose:
    def test_a_claim_that_was_held_to_a_call_offers_the_function_and_each_argument_as_it_was(
        self, recorded: Any
    ) -> None:
        repo, _, _ = recorded
        found = varying.options_of(tried(recorded), detail_of_run(recorded), repo)
        assert found["claim"] == "claim-m" and found["can"] is True and found["refused"] is None
        assert found["function"] == "fixture.core.mean"
        assert found["arguments"] == [
            {"name": "values", "text": "[2.5, 3.5]", "value": [2.5, 3.5], "plain": True},
            {"name": "scale", "text": "2", "value": 2, "plain": True},
        ]

    def test_an_argument_that_is_long_is_shown_cut_and_one_that_is_not_plain_is_said_not_to_be(
        self, recorded: Any
    ) -> None:
        repo, _, _ = recorded
        detail = copy.deepcopy(detail_of_run(recorded))
        detail["calls"][1]["args"]["values"]["value"] = list(range(2000))
        detail["calls"][1]["args"]["scale"]["value"] = {"$float": "nan"}
        found = varying.options_of(tried(recorded), detail, repo)
        values, scale = found["arguments"]
        assert values["value"] is None and values["plain"] is True and len(values["text"]) < 200
        assert scale["plain"] is False and scale["value"] == {"$float": "nan"}

    def test_a_value_is_offered_if_its_json_is_the_most_that_is_offered_and_is_not_if_it_is_more(
        self, recorded: Any
    ) -> None:
        repo, _, _ = recorded
        detail = copy.deepcopy(detail_of_run(recorded))
        detail["calls"][1]["args"]["values"]["value"] = "v" * (varying.MAX_OFFERED_CHARS - 2)
        detail["calls"][1]["args"]["scale"]["value"] = "s" * (varying.MAX_OFFERED_CHARS - 1)
        values, scale = varying.options_of(tried(recorded), detail, repo)["arguments"]
        assert values["value"] == "v" * (varying.MAX_OFFERED_CHARS - 2) and scale["value"] is None

    def test_a_claim_that_cannot_be_made_again_says_why_and_offers_nothing(self, recorded: Any) -> None:
        repo, _, _ = recorded
        entry = {**tried(recorded), "status": "not_attempted", "reason": "no_code", "link": None}
        found = varying.options_of(entry, detail_of_run(recorded), repo)
        assert found["can"] is False and found["refused"]["code"] == "not_attempted"
        assert "arguments" not in found and "function" not in found
        assert varying.options_of(tried(recorded), None, repo)["refused"]["code"] == "no_record"


class TestMakingItAgain:
    def test_the_call_is_made_as_the_code_s_own_function_with_nothing_changed_and_with_the_changes(
        self, recorded: Any
    ) -> None:
        runner = Standing()
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        [seen] = runner.seen
        assert seen["function"] == "lumi_direct" and "import_module('fixture.core')" in seen["source"]
        assert seen["seconds"] == 60
        control, variant = seen["cases"]
        assert (control.args, variant.args) == ({"values": [2.5, 3.5], "scale": 2}, {"values": [2.5, 3.5], "scale": 3})
        assert control.expected != {} and variant.expected == {}
        assert found["changes"] == [{"name": "scale", "was": 2, "now": 3}]

    def test_a_variant_that_gave_a_number_at_the_place_is_said_with_the_claim_s_own_and_the_paper_s(
        self, recorded: Any
    ) -> None:
        found = varying.run(planned(recorded, {"scale": 3}), Standing(), 60)  # type: ignore[arg-type]
        assert (found["claim"], found["number"], found["claim_run"]) == ("claim-m", "6.0", 6.0)
        assert found["variant"]["status"] == "gave" and found["variant"]["gave"] == 9.0
        assert found["control"] == {"verdict": "match", "gave": 6.0, "differences": [], "error": None}
        assert found["comparable"] is True and found["rounds_to_paper"] is False
        assert found["tutorial"] == {"id": "01-examples-demo-py", "path": "examples/demo.py"}
        assert (found["call"], found["function"], found["path"]) == (2, "fixture.core.mean", [])
        text = found["text"]
        assert "With scale = 3 in place of 2" in text and "gave 9.0 at result" in text
        assert "where the tutorial's call gave 6.0 and the paper reports 6.0" in text
        assert (
            "gave what the tutorial got" in text and "That number does not round to the one the paper reports." in text
        )
        assert text.endswith(
            "This is a variant. It is not the paper's result, and the claim's own result is as it was."
        )

    def test_a_variant_that_rounds_to_the_paper_s_number_is_said_to_and_is_not_a_reproduction(
        self, recorded: Any
    ) -> None:
        found = varying.run(planned(recorded, {"scale": 3}), Standing(variant=[gave(6.04), gave(6.04)]), 60)  # type: ignore[arg-type]
        assert found["rounds_to_paper"] is True and found["comparable"] is True
        assert "rounds to the one the paper reports, which is not a reproduction of the paper's result" in found["text"]

    def test_the_numbers_at_the_place_that_the_claim_was_held_to_are_read_in_a_result_that_is_a_table(
        self, recorded: Any
    ) -> None:
        entry = tried(recorded)
        entry = {**entry, "link": {**entry["link"], "path": ["mean"]}}
        table = {"mean": 9.0, "other": 1.0}
        runner = Standing(control=[gave({"mean": 6.0}, "dict")] * 2, variant=[gave(table, "dict")] * 2)
        found = varying.run(planned(recorded, {"scale": 3}, entry), runner, 60)  # type: ignore[arg-type]
        assert found["variant"]["gave"] == 9.0 and found["path"] == ["mean"] and "result['mean']" in found["text"]

    def test_a_result_with_no_number_at_the_place_is_said_so_and_no_number_is_given(self, recorded: Any) -> None:
        entry = tried(recorded)
        entry = {**entry, "link": {**entry["link"], "path": ["missing"]}}
        found = varying.run(planned(recorded, {"scale": 3}, entry), Standing(), 60)  # type: ignore[arg-type]
        assert found["variant"]["status"] == "no_place" and found["variant"]["gave"] is None
        assert found["variant"]["type"] == "float" and found["comparable"] is False
        assert found["rounds_to_paper"] is None and "no number at result['missing']" in found["text"]
        assert "the call ran and gave a float with no number" in found["text"]

    def test_a_call_that_gave_something_else_each_time_is_not_given_one_number(self, recorded: Any) -> None:
        runner = Standing(variant=[gave(9.0), gave(9.5)])
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert found["variant"]["status"] == "unstable" and found["variant"]["gave"] is None
        assert found["variant"]["values"] == [9.0, 9.5] and found["variant"]["differences"]
        assert found["comparable"] is False and found["rounds_to_paper"] is None
        assert "something else each time" in found["text"]

    def test_a_result_that_is_not_the_same_each_time_is_compared_each_time_with_the_first(self, recorded: Any) -> None:
        runner = Standing(variant=[gave(9.0), gave(9.0), gave(8.0)], repeats=3)
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert found["variant"]["status"] == "unstable" and found["variant"]["values"] == [9.0, 9.0, 8.0]
        assert found["repeats"] == 3

    def test_how_much_is_said_of_how_a_result_was_not_the_same_is_cut(self, recorded: Any) -> None:
        first = {f"k{number}": number for number in range(10)}
        other = {f"k{number}": number + 1 for number in range(10)}
        runner = Standing(variant=[gave(first, "dict"), gave(other, "dict"), gave(other, "dict")], repeats=3)
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert found["variant"]["status"] == "unstable"
        assert len(found["variant"]["differences"]) == varying.MAX_DIFFERENCES

    def test_the_type_is_that_of_the_first_result_and_the_number_is_the_first_one_that_was_given(
        self, recorded: Any
    ) -> None:
        runner = Standing(variant=[gave(1.0), gave("x", "str")])
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert (found["variant"]["status"], found["variant"]["type"]) == ("unstable", "float")
        runner = Standing(variant=[gave(9.0), gave(9.0 + 1e-9)])
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert found["variant"]["gave"] == 9.0 and found["variant"]["values"] == [9.0, 9.0 + 1e-9]

    def test_a_number_that_the_paper_wrote_in_a_way_that_cannot_be_read_is_not_said_to_round_or_not(
        self, recorded: Any
    ) -> None:
        entry = {**tried(recorded), "value": "about six"}
        found = varying.run(planned(recorded, {"scale": 3}, entry), Standing(), 60)  # type: ignore[arg-type]
        assert found["variant"]["gave"] == 9.0 and found["rounds_to_paper"] is None
        assert "round" not in found["text"]

    def test_only_a_variant_that_gave_a_number_is_said_to_round_to_the_paper_s_or_not(self, recorded: Any) -> None:
        plan_ = planned(recorded, {"scale": 3})
        link = plan_.link
        control = {"verdict": "match", "gave": 6.0, "differences": [], "error": None}
        stopped_ = {"status": "error", "gave": None, "values": [], "type": None, "differences": []}
        stopped_["error"] = {"type": "ValueError", "message": "bad"}
        for rounds in (True, False):
            text = varying.text_of(link, link["number"]["text"], plan_.changes, control, stopped_, rounds)
            assert "round" not in text and text.endswith(varying.CLOSING)

    def test_a_call_that_stopped_with_an_error_says_which_and_gives_no_number(self, recorded: Any) -> None:
        runner = Standing(variant=[stopped("ZeroDivisionError", "division by zero")] * 2)
        found = varying.run(planned(recorded, {"values": [1.0]}), runner, 60)  # type: ignore[arg-type]
        assert found["variant"]["status"] == "error" and found["variant"]["gave"] is None
        assert found["variant"]["error"] == {"type": "ZeroDivisionError", "message": "division by zero"}
        assert "stopped with ZeroDivisionError: division by zero" in found["text"] and found["comparable"] is False

    def test_a_call_that_was_not_made_in_the_time_is_said_not_to_have_been(self, recorded: Any) -> None:
        runner = Standing(control=[gave(6.0), None], variant=[None, None], ended="timed_out")
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert found["variant"]["status"] == "not_run" and found["control"]["verdict"] == "not_run"
        assert "was not made in the time that was given" in found["text"] and found["comparable"] is False

    def test_a_container_that_gave_no_result_at_all_is_said_to_have_given_none(self, recorded: Any) -> None:
        runner = Standing(control=[None, None], variant=[None, None], ended="too_big")
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert found["variant"]["status"] == "not_run" and found["control"]["verdict"] == "not_run"
        assert "more than is allowed" in found["variant"]["differences"][0]

    def test_a_variant_is_not_comparable_if_the_call_alone_did_not_give_what_the_tutorial_got(
        self, recorded: Any
    ) -> None:
        runner = Standing(control=[gave(7.0), gave(7.0)])
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert found["control"]["verdict"] == "differs" and found["control"]["gave"] is None
        assert found["variant"]["gave"] == 9.0 and found["comparable"] is False
        assert "did not give what the tutorial got" in found["text"]
        assert "cannot be held to what it got" in found["text"]
        assert f" ({found['control']['differences'][0]})" in found["text"]

    def test_a_variant_is_not_comparable_if_the_call_alone_stopped_with_an_error(self, recorded: Any) -> None:
        runner = Standing(control=[stopped("FileNotFoundError", "no such file")] * 2)
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert found["control"]["verdict"] == "error" and found["comparable"] is False
        assert found["control"]["error"] == {"type": "FileNotFoundError", "message": "no such file"}
        assert "(FileNotFoundError)" in found["text"]

    def test_an_error_s_words_are_cut_to_the_most(self, recorded: Any) -> None:
        runner = Standing(variant=[stopped("ValueError", "w" * 1000)] * 2)
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert len(found["variant"]["error"]["message"]) == varying.MAX_MESSAGE

    def test_a_control_s_error_words_are_cut_to_the_most_too(self, recorded: Any) -> None:
        runner = Standing(control=[stopped("ValueError", "w" * 1000)] * 2)
        found = varying.run(planned(recorded, {"scale": 3}), runner, 60)  # type: ignore[arg-type]
        assert len(found["control"]["error"]["message"]) == varying.MAX_MESSAGE

    def test_the_claim_s_own_result_is_not_touched(self, recorded: Any) -> None:
        entry = tried(recorded)
        before = copy.deepcopy(entry)
        found = varying.run(planned(recorded, {"scale": 3}, entry), Standing(), 60)  # type: ignore[arg-type]
        assert entry == before and entry["status"] == "reproduced" and "status" not in found
        assert found["claim_run"] == entry["link"]["got"]

    def test_nothing_that_is_said_is_a_cause_or_a_verification(self, recorded: Any) -> None:
        for runner in (
            Standing(),
            Standing(variant=[gave(6.04)] * 2),
            Standing(control=[gave(7.0)] * 2),
            Standing(variant=[stopped()] * 2),
            Standing(variant=[gave(1.0), gave(2.0)]),
        ):
            text = varying.run(planned(recorded, {"scale": 3}), runner, 60)["text"].lower()  # type: ignore[arg-type]
            assert not any(word in text for word in CAUSE_WORDS), text
        assert "not the paper's" in varying.MEANING and "not a reproduction" in varying.MEANING

    def test_what_is_kept_is_json(self, recorded: Any) -> None:
        json.dumps(varying.run(planned(recorded, {"scale": 3}), Standing(), 60))  # type: ignore[arg-type]


class TestInARealProcess:
    """The same function, called by the runner that a container runs, on this machine."""

    def runner(self, recorded: Any, tmp_path: Path) -> LocalRunner:
        repo, _, _ = recorded
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        return LocalRunner(repo, scratch)

    def test_the_call_with_nothing_changed_gives_what_the_tutorial_got_and_the_changed_call_gives_another(
        self, recorded: Any, tmp_path: Path
    ) -> None:
        found = varying.run(planned(recorded, {"scale": 3}), self.runner(recorded, tmp_path), 90)
        assert found["control"]["verdict"] == "match" and found["control"]["gave"] == 6.0
        assert found["variant"]["status"] == "gave" and found["variant"]["gave"] == 9.0
        assert found["comparable"] is True and found["rounds_to_paper"] is False

    def test_a_change_to_a_list_that_is_the_same_mean_gives_the_paper_s_number_again(
        self, recorded: Any, tmp_path: Path
    ) -> None:
        found = varying.run(planned(recorded, {"values": [1.5, 4.5]}), self.runner(recorded, tmp_path), 90)
        assert found["variant"]["gave"] == 6.0 and found["rounds_to_paper"] is True

    def test_a_change_that_makes_the_function_raise_is_an_error_and_the_unchanged_call_still_matches(
        self, recorded: Any, tmp_path: Path
    ) -> None:
        found = varying.run(planned(recorded, {"values": []}), self.runner(recorded, tmp_path), 90)
        assert found["control"]["verdict"] == "match"
        assert found["variant"]["status"] == "error" and found["variant"]["error"]["type"] == "ZeroDivisionError"
        assert found["comparable"] is False

    def test_a_function_that_gives_something_else_each_time_is_not_one_number(
        self, recorded: Any, tmp_path: Path
    ) -> None:
        entry = tried(recorded)
        _, details, _ = recorded
        jitter = next(call for call in details[0]["calls"] if call["function"] == "jitter")
        entry = {**entry, "link": {**entry["link"], "call": jitter["id"], "path": []}}
        found = varying.run(planned(recorded, {"x": 2.0}, entry), self.runner(recorded, tmp_path), 90)
        assert found["variant"]["status"] == "unstable" and found["control"]["verdict"] == "differs"
        assert found["comparable"] is False and len(found["variant"]["values"]) == 2

    def test_the_number_that_was_parsed_is_the_one_the_paper_wrote(self) -> None:
        assert written.parse("6.0") is not None
