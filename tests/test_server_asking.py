"""Tests of what a conversation asks the researcher: whether a call may be made, and what an MCP server asks."""

import threading
from collections.abc import Callable
from typing import Any

import pytest

from virtual_lab.approval import ApprovalDeclined, ApprovalRequest, ServerQuestion
from virtual_lab.server.asking import Asker, check_answer, check_value, is_web_address
from virtual_lab.server.errors import ApiError

WAIT = 10.0

ORDER_FIELDS: dict[str, dict[str, Any]] = {
    "name": {"type": "string", "title": "Name"},
    "kind": {"enum": ["protein", "dna"], "title": "Kind"},
    "copies": {"type": "integer", "default": 1},
    "urgent": {"type": "boolean"},
    "weight": {"type": "number"},
    "tags": {"type": "array", "items": {"enum": ["a", "b"]}},
}


def call(**changes: Any) -> ApprovalRequest:
    given: dict[str, Any] = {
        "tool": "lab_order",
        "server": "lab",
        "server_tool": "order",
        "arguments": {"sequence": "MKV"},
        "description": "Orders a protein.\n\nIt is paid for.",
    }

    return ApprovalRequest(**{**given, **changes})


def question(**changes: Any) -> ServerQuestion:
    given: dict[str, Any] = {
        "server": "lab",
        "message": " What is to be ordered? ",
        "fields": ORDER_FIELDS,
        "required": ("name", "kind"),
    }

    return ServerQuestion(**{**given, **changes})


class Told:
    """What the conversation was told, which is what a test waits on."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []
        self.changed = threading.Condition()

    def __call__(self, kind: str, text: str = "", **data: Any) -> None:
        with self.changed:
            self.events.append((kind, text, data))
            self.changed.notify_all()

    def states(self, kind: str) -> list[str]:
        with self.changed:
            return [data["state"] for found, _, data in self.events if found == kind]

    def waiting(self, kind: str, number: int = 1) -> dict[str, Any]:
        """The data of the event that said a request was waiting, the number-th one, once there is one."""
        with self.changed:
            assert self.changed.wait_for(lambda: self.states(kind).count("waiting") >= number, WAIT)
            waits = [data for found, _, data in self.events if found == kind and data["state"] == "waiting"]

        return waits[number - 1]


class Running:
    """Something that runs in a thread, and what came of it."""

    def __init__(self, function: Callable[[], Any]) -> None:
        self.result: Any = None
        self.error: BaseException | None = None

        def run() -> None:
            try:
                self.result = function()
            except BaseException as error:  # noqa: BLE001
                self.error = error

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def finish(self) -> Any:
        self.thread.join(WAIT)
        assert not self.thread.is_alive(), "it did not finish"

        return self.result


def asker(told: Told, stopping: Callable[[], bool] = lambda: False, timeout: float = 30.0) -> Asker:
    return Asker(told, stopping, lambda name: name.title(), timeout)


class TestAskingWhetherACallMayBeMade:
    def test_the_call_waits_for_the_answer_and_is_made_when_it_is_allowed(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.approve(call()))

        waiting = told.waiting("approval")
        assert running.thread.is_alive()
        assert asking.approval(waiting["request"], True) == "approved"

        assert running.finish() is True
        assert running.error is None
        assert told.states("approval") == ["waiting", "approved"]
        assert asking.waiting() == []

    def test_what_is_told_of_it_is_the_server_the_tool_what_it_does_and_what_it_is_to_be_called_with(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.approve(call(arguments={"sequence": "MKV", "copies": 2})))

        waiting = told.waiting("approval")
        asking.approval(waiting["request"], False)
        running.finish()

        assert set(waiting) == {"request", "state", "server", "title", "tool", "description", "arguments"}
        assert waiting["server"] == "lab"
        assert waiting["title"] == "Lab"
        assert waiting["tool"] == "lab_order"
        assert waiting["description"] == "Orders a protein."
        assert '"sequence": "MKV"' in waiting["arguments"]
        assert '"copies": 2' in waiting["arguments"]

    def test_the_end_of_it_is_told_of_as_being_of_the_same_server(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.approve(call()))

        waiting = told.waiting("approval")
        asking.approval(waiting["request"], True)
        running.finish()

        settled = {"request": waiting["request"], "state": "approved", "server": "lab", "title": "Lab"}
        assert told.events[-1] == ("approval", "", settled)

    def test_a_call_that_is_declined_is_not_made(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.approve(call()))

        assert asking.approval(told.waiting("approval")["request"], False) == "declined"

        assert running.finish() is False
        assert told.states("approval") == ["waiting", "declined"]

    def test_calls_that_wait_at_the_same_time_are_answered_each_by_itself(self) -> None:
        told = Told()
        asking = asker(told)
        first = Running(lambda: asking.approve(call(tool="lab_first")))
        second = Running(lambda: asking.approve(call(tool="lab_second")))
        told.waiting("approval", 2)
        by_tool = {data["tool"]: data["request"] for kind, _, data in told.events if data["state"] == "waiting"}

        asking.approval(by_tool["lab_second"], True)
        asking.approval(by_tool["lab_first"], False)

        assert (first.finish(), second.finish()) == (False, True)

    def test_a_turn_that_is_ending_is_not_asked_anything_and_the_call_is_not_made(self) -> None:
        told = Told()

        with pytest.raises(ApprovalDeclined, match="turn was ending before a person approved the call to lab_order"):
            asker(told, stopping=lambda: True).approve(call())

        assert told.events == []

    def test_a_call_that_waits_when_the_turn_is_stopped_is_withdrawn_and_not_made(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.approve(call()))
        told.waiting("approval")

        asking.withdraw()
        running.finish()

        assert isinstance(running.error, ApprovalDeclined)
        assert "The turn ended before a person approved the call to lab_order" in str(running.error)
        assert told.states("approval") == ["waiting", "withdrawn"]
        assert asking.waiting() == []

    def test_a_call_that_is_not_answered_in_time_is_withdrawn_and_not_made(self) -> None:
        told = Told()

        with pytest.raises(ApprovalDeclined, match="No one approved the call to lab_order within 0.05 seconds"):
            asker(told, timeout=0.05).approve(call())

        assert told.states("approval") == ["waiting", "withdrawn"]

    def test_a_closed_conversation_asks_nothing_more_and_ends_what_waits(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.approve(call()))
        told.waiting("approval")

        asking.close()
        running.finish()

        assert isinstance(running.error, ApprovalDeclined)
        with pytest.raises(ApprovalDeclined):
            asking.approve(call())
        assert asking.answer(question()) is None
        assert told.states("approval") == ["waiting", "withdrawn"]

    def test_an_answer_that_comes_twice_is_taken_once(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.approve(call()))
        request = told.waiting("approval")["request"]
        asking.approval(request, True)
        running.finish()

        with pytest.raises(ApiError) as caught:
            asking.approval(request, False)

        assert (caught.value.status, caught.value.code) == (409, "not_waiting")
        assert told.states("approval") == ["waiting", "approved"]

    def test_an_answer_to_what_nothing_waits_for_is_refused(self) -> None:
        told = Told()
        asking = asker(told)

        with pytest.raises(ApiError) as caught:
            asking.approval("nothing", True)

        assert (caught.value.status, caught.value.code) == (409, "not_waiting")

    def test_a_question_cannot_be_answered_as_an_approval(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.answer(question()))
        request = told.waiting("question")["request"]

        with pytest.raises(ApiError) as caught:
            asking.approval(request, True)

        assert caught.value.code == "not_waiting"
        asking.reply(request, None)
        running.finish()


class TestAskingWhatAServerAsks:
    def test_the_answer_of_a_form_is_what_the_server_is_told(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.answer(question()))
        request = told.waiting("question")["request"]

        assert asking.reply(request, {"name": "KP.3", "kind": "dna", "copies": 2}) == "answered"

        assert running.finish() == {"name": "KP.3", "kind": "dna", "copies": 2}
        assert told.states("question") == ["waiting", "answered"]

    def test_what_is_told_of_it_is_what_it_asks_and_the_fields_of_the_form(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.answer(question()))

        waiting = told.waiting("question")
        asking.reply(waiting["request"], None)
        running.finish()

        assert set(waiting) == {"request", "state", "server", "title", "fields", "required", "url"}
        assert waiting["fields"] == ORDER_FIELDS
        assert waiting["required"] == ["name", "kind"]
        assert waiting["url"] is None
        assert (waiting["server"], waiting["title"]) == ("lab", "Lab")
        text = next(text for kind, text, data in told.events if kind == "question" and data["state"] == "waiting")
        assert text == "What is to be ordered?"

    def test_what_was_answered_is_not_kept_in_the_conversation(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.answer(question()))
        request = told.waiting("question")["request"]

        asking.reply(request, {"name": "A secret name", "kind": "dna"})
        running.finish()

        assert "secret" not in repr(told.events)
        settled = {"request": request, "state": "answered", "server": "lab", "title": "Lab"}
        assert told.events[-1] == ("question", "", settled)

    def test_a_question_that_is_declined_is_declined_to_the_server(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.answer(question()))

        assert asking.reply(told.waiting("question")["request"], None) == "declined"

        assert running.finish() is None
        assert told.states("question") == ["waiting", "declined"]

    def test_an_answer_that_is_not_one_the_form_takes_is_refused_and_the_question_goes_on_waiting(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.answer(question()))
        request = told.waiting("question")["request"]

        with pytest.raises(ApiError) as caught:
            asking.reply(request, {"name": "KP.3"})

        assert (caught.value.status, caught.value.code) == (422, "invalid")
        assert "kind must be filled in" in caught.value.message
        assert asking.waiting() == [request]
        assert running.thread.is_alive()

        asking.reply(request, {"name": "KP.3", "kind": "dna"})
        assert running.finish() == {"name": "KP.3", "kind": "dna"}

    def test_a_question_answered_at_a_web_page_is_offered_with_its_address_and_answered_with_nothing(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(
            lambda: asking.answer(question(fields={}, required=(), url="https://pay.example.org/test", message="Pay."))
        )

        waiting = told.waiting("question")
        assert waiting["url"] == "https://pay.example.org/test"
        assert waiting["fields"] == {}
        asking.reply(waiting["request"], {})

        assert running.finish() == {}

    def test_a_page_that_is_not_a_web_address_is_declined_without_being_offered(self) -> None:
        told = Told()

        answer = asker(told).answer(question(fields={}, required=(), url="javascript:alert(1)", message="Pay."))

        assert answer is None
        ((kind, text, data),) = told.events
        assert kind == "question"
        assert data["state"] == "declined"
        assert "url" not in data
        assert "declined without asking" in text
        assert "javascript:alert(1)" in text

    def test_a_question_asked_of_a_turn_that_is_ending_is_declined(self) -> None:
        told = Told()

        assert asker(told, stopping=lambda: True).answer(question()) is None
        assert told.events == []

    def test_a_question_that_waits_when_the_turn_is_stopped_is_withdrawn_and_declined(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.answer(question()))
        told.waiting("question")

        asking.withdraw()

        assert running.finish() is None
        assert told.states("question") == ["waiting", "withdrawn"]

    def test_a_question_that_is_not_answered_in_time_is_withdrawn_and_declined(self) -> None:
        told = Told()

        assert asker(told, timeout=0.05).answer(question()) is None
        assert told.states("question") == ["waiting", "withdrawn"]

    def test_an_approval_cannot_be_answered_as_a_question(self) -> None:
        told = Told()
        asking = asker(told)
        running = Running(lambda: asking.approve(call()))
        request = told.waiting("approval")["request"]

        with pytest.raises(ApiError) as caught:
            asking.reply(request, {})

        assert caught.value.code == "not_waiting"
        asking.approval(request, False)
        running.finish()


class TestWhatAnAnswerMayBe:
    def test_it_may_leave_out_what_is_not_required_and_fill_in_every_kind_of_field(self) -> None:
        answer = {
            "name": "KP.3",
            "kind": "protein",
            "copies": 3,
            "urgent": True,
            "weight": 1.5,
            "tags": ["a", "b"],
        }

        assert check_answer(question(), answer) == answer
        assert check_answer(question(), {"name": "KP.3", "kind": "dna"}) == {"name": "KP.3", "kind": "dna"}

    def test_a_form_with_no_fields_is_answered_with_nothing(self) -> None:
        assert check_answer(question(fields={}, required=()), {}) == {}

    @pytest.mark.parametrize("answer", [None, [], "KP.3", 3])
    def test_it_is_a_mapping_of_the_fields_by_name(self, answer: Any) -> None:
        with pytest.raises(ValueError, match="the form's fields, by name"):
            check_answer(question(), answer)

    def test_a_field_the_form_does_not_have_is_refused_and_the_fields_it_has_are_said(self) -> None:
        with pytest.raises(ValueError, match="There is no field colour: the fields are name, kind, copies"):
            check_answer(question(), {"name": "KP.3", "kind": "dna", "colour": "red"})

    def test_a_field_that_is_required_is_filled_in(self) -> None:
        with pytest.raises(ValueError, match="name, kind must be filled in"):
            check_answer(question(), {})

    def test_a_page_is_answered_with_nothing_to_fill_in(self) -> None:
        asked = question(fields={}, required=(), url="https://pay.example.org/test")

        assert check_answer(asked, {}) == {}
        with pytest.raises(ValueError, match="takes no fields"):
            check_answer(asked, {"name": "x"})

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        [
            ("name", 3, "Name is text"),
            ("name", None, "Name is text"),
            ("name", "x" * 20_001, "Name is text of at most 20,000 characters"),
            ("kind", "rna", "Kind is one of protein, dna"),
            ("kind", 1, "Kind is one of protein, dna"),
            ("copies", "2", "copies is a whole number"),
            ("copies", 2.5, "copies is a whole number"),
            ("copies", True, "copies is a whole number"),
            ("urgent", 1, "urgent is yes or no"),
            ("urgent", "yes", "urgent is yes or no"),
            ("weight", "1", "weight is a number"),
            ("weight", True, "weight is a number"),
            ("weight", float("inf"), "weight is a number"),
            ("weight", float("nan"), "weight is a number"),
            ("tags", "a", "tags is a list"),
            ("tags", ["c"], "tags is one of a, b"),
            ("tags", list("ab") * 501, "tags is a list"),
        ],
    )
    def test_a_value_that_is_not_what_the_field_takes_is_refused(self, field: str, value: Any, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            check_answer(question(required=()), {field: value})

    def test_a_number_may_be_whole(self) -> None:
        assert check_answer(question(required=()), {"weight": 2}) == {"weight": 2}

    def test_a_choice_of_numbers_is_not_taken_for_true(self) -> None:
        schema = {"enum": [1, 2]}

        assert check_value("n", schema, 1) == 1
        with pytest.raises(ValueError):
            check_value("n", schema, True)

    def test_a_choice_may_be_given_as_options_with_values_and_titles(self) -> None:
        schema = {"oneOf": [{"const": "a", "title": "A"}, {"const": "b", "title": "B"}]}

        assert check_value("x", schema, "b") == "b"
        with pytest.raises(ValueError, match="x is one of a, b"):
            check_value("x", schema, "c")


class TestWhatIsAWebAddress:
    @pytest.mark.parametrize("url", ["https://pay.example.org/test?a=1", "http://localhost:8000/x"])
    def test_a_page_may_be_sent_to_a_web_address(self, url: str) -> None:
        assert is_web_address(url)

    @pytest.mark.parametrize(
        "url",
        ["javascript:alert(1)", "data:text/html,<p>", "file:///etc/passwd", "https://", "//example.org", "", None, 3],
    )
    def test_it_may_not_be_sent_to_anything_else(self, url: Any) -> None:
        assert not is_web_address(url)
