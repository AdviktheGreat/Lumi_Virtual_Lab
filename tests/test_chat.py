"""Tests for a conversation with the head of a lab: answering, running code, bringing in the team,
steering, and keeping the conversation so that it can be carried on."""

import io
import json
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function

from virtual_lab import chat as chat_module
from virtual_lab import llm as llm_module
from virtual_lab.agent import Agent
from virtual_lab.chat import (
    STOPPED_REPLY,
    Attachment,
    Chat,
    ChatBusyError,
    ChatClosedError,
    ChatReply,
    UploadTooLargeError,
    describe_size,
    safe_filename,
    title_of,
)
from virtual_lab.constants import HUMAN_SPEAKER
from virtual_lab.events import ChatEvent
from virtual_lab import failures
from virtual_lab.failures import KEY_REFUSED, UNWELL
from virtual_lab.prompts import PRINCIPAL_INVESTIGATOR, SCIENTIFIC_CRITIC
from virtual_lab.session import LocalSession
from virtual_lab.tools import Tool
from virtual_lab.utils import ContextLengthExceededError, CostUnknownError, compute_token_cost

from conftest import TEST_MODEL, FakeClient, make_usage, text_response, tool_call_response
from test_events import PlottingSession
from test_resources import small_resources

LEAD = PRINCIPAL_INVESTIGATOR.with_model(TEST_MODEL)
CRITIC = SCIENTIFIC_CRITIC.with_model(TEST_MODEL)
IMMUNOLOGIST = Agent(
    title="Immunologist",
    expertise="antibody engineering",
    goal="design nanobodies",
    role="advise on immunogenicity",
    model=TEST_MODEL,
)
BIOLOGIST = Agent(
    title="Computational Biologist",
    expertise="protein structure prediction",
    goal="model complexes",
    role="run simulations",
    model=TEST_MODEL,
)
TEAM = (IMMUNOLOGIST, BIOLOGIST, CRITIC)

# What one of the fake model's responses costs, which every response here is
PER_RESPONSE = compute_token_cost(TEST_MODEL, 100, 20)


def make_chat(tmp_path: Path, **options: Any) -> Chat:
    return Chat(tmp_path / "chat", LEAD, TEAM, **{"resources": "none", "max_retries": 0, **options})


def kinds(events: list[ChatEvent], leave_out: tuple[str, ...] = ("status",)) -> list[str]:
    return [event.kind for event in events if event.kind not in leave_out]


def of(events: list[ChatEvent], kind: str) -> list[ChatEvent]:
    return [event for event in events if event.kind == kind]


def lab_events(events: list[ChatEvent], kind: str | None = None) -> list[ChatEvent]:
    return [event for event in of(events, "lab") if kind is None or event.data["event"] == kind]


def tool_calls_response(*calls: tuple[str, dict[str, Any]]) -> ChatCompletion:
    """A completion in which the model asks for several tool calls at once."""
    return ChatCompletion(
        id="test",
        model=TEST_MODEL,
        object="chat.completion",
        created=0,
        usage=make_usage(),
        choices=[
            Choice(
                finish_reason="tool_calls",
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ChatCompletionMessageToolCall(
                            id=f"call_{number}",
                            type="function",
                            function=Function(name=name, arguments=json.dumps(arguments)),
                        )
                        for number, (name, arguments) in enumerate(calls, start=1)
                    ],
                ),
            )
        ],
    )


def team_meeting(agenda: str = "Design a nanobody.", members: tuple[str, ...] = ("Immunologist",), **extra: Any) -> Any:
    return tool_call_response("convene_team", {"agenda": agenda, "members": list(members), **extra})


def provider_refusal(error_class: Any, status: int, message: str) -> Any:
    """What the OpenAI client raises when a provider answers with an error status."""
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.example.test/v1/chat/completions"))

    return error_class(message, response=response, body=None)


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def request_messages(fake_client: FakeClient, call: int) -> list[dict[str, Any]]:
    return fake_client.completions.calls[call]["messages"]


@pytest.fixture(autouse=True)
def model_client(fake_client: FakeClient) -> FakeClient:
    """A conversation builds its models when it is made, so every test needs the fake before that."""
    return fake_client


@pytest.fixture
def session(tmp_path: Path):
    with PlottingSession(tmp_path / "work", warn=False, timeout=20) as opened:
        yield opened


class TestAnswering:
    def test_the_lead_answers_a_message_and_the_conversation_is_kept(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [text_response("Nanobodies are small antibodies.")]
        chat = make_chat(tmp_path)

        reply = chat.send("What is a nanobody?")

        assert reply == chat.last_reply
        assert (reply.status, reply.text, reply.error) == ("answered", "Nanobodies are small antibodies.", None)
        assert reply.usage["num_calls"] == 1
        assert reply.usage["cost"] == pytest.approx(PER_RESPONSE)
        assert chat.state == "idle"
        assert chat.turns == 1

        events = chat.events_since()
        assert kinds(events) == ["user", "title", "usage", "answer"]
        user, title, usage, answer = (event for event in events if event.kind != "status")
        assert (user.speaker, user.text, user.data["attachments"]) == (HUMAN_SPEAKER, "What is a nanobody?", [])
        assert title.text == "What is a nanobody?"
        assert usage.data["num_calls"] == 1 and usage.data["max_cost"] is None
        assert (answer.text, answer.data["usage"]["num_calls"]) == ("Nanobodies are small antibodies.", 1)
        assert {event.turn for event in events} == {1}
        assert [event.id for event in events] == sorted(event.id for event in events)

        # What the lead is sent: its own prompt, as the system's, and the researcher's message
        sent = request_messages(fake_client, 0)
        assert sent[0]["role"] == "system" and "You are a Principal Investigator" in sent[0]["content"]
        assert "convene_team" in sent[0]["content"] and "Immunologist: antibody engineering" in sent[0]["content"]
        assert sent[1] == {"role": "user", "content": "What is a nanobody?"}
        assert [tool["function"]["name"] for tool in fake_client.completions.calls[0]["tools"]] == [
            "convene_team",
            "consult",
        ]

        assert chat.messages == [
            {"role": "user", "content": "What is a nanobody?"},
            {"role": "assistant", "name": "Principal_Investigator", "content": "Nanobodies are small antibodies."},
        ]
        assert lines(tmp_path / "chat" / "messages.jsonl") == chat.messages
        saved = [ChatEvent.from_dict(item) for item in lines(tmp_path / "chat" / "events.jsonl")]
        assert saved == [event for event in events if event.kind != "status"]

        info = json.loads((tmp_path / "chat" / "chat.json").read_text())
        assert info["title"] == "What is a nanobody?" and info["turns"] == 1 and info["running"] is False
        assert info["lead"]["title"] == "Principal Investigator"
        assert [member["title"] for member in info["team"]] == [
            "Immunologist",
            "Computational Biologist",
            "Scientific Critic",
        ]
        assert info["spent"] == pytest.approx(PER_RESPONSE) and info["usage"]["num_calls"] == 1

    def test_a_lead_with_no_team_works_alone(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [text_response("An answer.")]
        chat = Chat(tmp_path / "chat", LEAD, resources="none", max_retries=0)

        chat.send("Hello")

        assert "tools" not in fake_client.completions.calls[0]
        system = request_messages(fake_client, 0)[0]["content"]
        assert "convene_team" not in system and "Your team" not in system

    @pytest.mark.parametrize("options", [{"max_delegations": 0}, {"team": (CRITIC,)}])
    def test_the_team_cannot_be_brought_in_if_there_is_nobody_to_bring_or_no_way_to(
        self, fake_client: FakeClient, tmp_path: Path, options: dict[str, Any]
    ) -> None:
        fake_client.completions.responses = [text_response("An answer.")]
        team = options.pop("team", TEAM)
        chat = Chat(tmp_path / "chat", LEAD, team, resources="none", max_retries=0, **options)

        chat.send("Hello")

        assert "tools" not in fake_client.completions.calls[0]

    def test_a_reply_is_streamed_as_it_is_written_and_not_kept(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [text_response("Nanobodies are small.")]
        told: list[ChatEvent] = []
        chat = make_chat(tmp_path, stream=True, on_event=told.append)

        chat.send("What is a nanobody?")

        writing = of(told, "writing")
        assert [event.text for event in writing] == ["Nanobodies ", "Nanobodies are ", "Nanobodies are small."]
        assert {(event.speaker, event.data["request"], event.data["model"]) for event in writing} == {
            ("Principal Investigator", 1, TEST_MODEL)
        }
        # The answer says it whole, so what was being written is not what a page that comes later is shown
        assert of(chat.events_since(), "writing") == []
        assert "writing" not in {item["kind"] for item in lines(tmp_path / "chat" / "events.jsonl")}

    def test_a_page_that_comes_while_a_reply_is_written_is_shown_what_is_written(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [text_response("Nanobodies are small.")]
        seen: list[list[ChatEvent]] = []
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "writing" and event.text == "Nanobodies are ":
                seen.append(chat.events_since())

        chat = make_chat(tmp_path, stream=True, on_event=on_event)
        chat.send("What is a nanobody?")

        (during,) = seen
        assert kinds(during) == ["user", "title", "writing"]
        assert of(during, "writing")[0].text == "Nanobodies are "

    def test_a_message_needs_something_in_it(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)

        with pytest.raises(ValueError, match="something in it"):
            chat.send("   ")

        assert chat.state == "idle" and chat.turns == 0 and fake_client.completions.calls == []

    def test_a_closed_conversation_takes_no_messages(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)
        chat.close()

        with pytest.raises(ChatClosedError):
            chat.send("Hello")

    def test_a_conversation_describes_itself_for_a_page_that_lists_it(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path, session=session, max_cost=1.0)

        before = chat.describe()
        assert json.loads((tmp_path / "chat" / "chat.json").read_text())["title"] == ""
        chat.send("What is a nanobody?")
        after = chat.describe()

        assert (before["title"], before["state"], before["turns"], before["last_event_id"], before["spent"]) == (
            "",
            "idle",
            0,
            0,
            0.0,
        )
        assert (before["lead"], before["team"], before["can_run_code"]) == (
            "Principal Investigator",
            ["Immunologist", "Computational Biologist", "Scientific Critic"],
            True,
        )
        assert (after["title"], after["state"], after["turns"], after["max_cost"]) == (
            "What is a nanobody?",
            "idle",
            1,
            1.0,
        )
        assert after["spent"] == pytest.approx(PER_RESPONSE) and after["usage"]["num_calls"] == 1
        assert after["last_event_id"] == chat.events_since()[-1].id and after["created_at"] == before["created_at"]
        assert json.loads(json.dumps(after)) == after

    def test_the_title_is_the_first_message_unless_it_was_given(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat = make_chat(tmp_path, title="Nanobody design")
        chat.send("What is a nanobody?")
        chat.rename("  Better   title ")

        assert chat.title == "Better title"
        assert [event.text for event in of(chat.events_since(), "title")] == ["Better title"]
        assert json.loads((tmp_path / "chat" / "chat.json").read_text())["title"] == "Better title"

    def test_the_first_message_gives_the_title_when_none_was_given(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path)
        chat.send("What is a nanobody?\nAnd how is it made?")

        assert chat.title == "What is a nanobody?"
        assert [event.text for event in of(chat.events_since(), "title")] == ["What is a nanobody?"]

    def test_titles_are_made_from_the_first_line(self) -> None:
        assert title_of("\n  First   line here\nSecond", []) == "First line here"
        assert title_of("x" * 100, []) == "x" * 79 + "…"
        assert title_of("", [Attachment("counts.csv", "uploads/counts.csv", 3)]) == "counts.csv"


class TestCode:
    def test_the_lead_runs_code_and_the_figure_is_told_of(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        session.run("earlier = 1")
        fake_client.completions.responses = [
            tool_call_response("run_code", {"code": "print(6 * 7)"}),
            text_response("It is 42."),
        ]
        chat = make_chat(tmp_path, session=session)

        reply = chat.send("What is 6 times 7?")

        assert reply.text == "It is 42."
        events = chat.events_since()
        assert kinds(events) == ["user", "title", "usage", "tool_calls", "cell", "tool_output", "usage", "answer"]
        (calls,) = of(events, "tool_calls")
        assert calls.speaker == "Principal Investigator"
        assert calls.data["calls"] == [{"id": "call_1", "name": "run_code", "arguments": '{"code": "print(6 * 7)"}'}]

        # Only what the conversation ran, not what was run before it
        (cell,) = of(events, "cell")
        assert (cell.data["code"], cell.data["status"], cell.data["output"].strip()) == ("print(6 * 7)", "ok", "42")
        assert cell.data["plots"] == ["plots/figure_1.png"]
        assert cell.data["plot_paths"] == [str(session.directory / "plots" / "figure_1.png")]
        assert cell.data["call"] == "call_1"
        (output,) = of(events, "tool_output")
        assert (output.data["call"], output.data["name"]) == ("call_1", "run_code")
        assert "42" in output.text

        # The lead is told how to run code, and the second request has the result in it
        first = fake_client.completions.calls[0]
        assert "run_code" in [tool["function"]["name"] for tool in first["tools"]]
        assert f"The code runs in {session.directory}" in first["messages"][0]["content"]
        assert request_messages(fake_client, 1)[-1]["role"] == "tool"
        assert [message["role"] for message in chat.messages] == ["user", "assistant", "tool", "assistant"]
        assert chat.messages[1]["tool_calls"][0]["id"] == "call_1"

    def test_a_lead_without_a_session_is_told_it_cannot_run_code(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)

        chat.send("Hello")

        assert "There is no session to run code in" in request_messages(fake_client, 0)[0]["content"]

    def test_tools_are_withheld_when_the_lead_has_used_all_its_calls(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            tool_call_response("run_code", {"code": "print(1)"}),
            text_response("Done."),
        ]
        chat = make_chat(tmp_path, session=session, max_tool_iterations=1)

        chat.send("Go")

        assert "tools" in fake_client.completions.calls[0]
        assert "tools" not in fake_client.completions.calls[1]

    def test_a_tool_the_lead_makes_up_is_answered_with_an_error(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [tool_call_response("run_code", {"code": "1"}), text_response("Sorry.")]
        chat = make_chat(tmp_path)

        chat.send("Go")

        (output,) = of(chat.events_since(), "tool_output")
        assert output.text.startswith('Error: unknown tool "run_code"')

    def test_tools_given_to_the_conversation_are_the_leads_to_call(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        look_up = Tool(
            name="look_up",
            description="Looks something up.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            function=lambda query: f"Found {query}.",
            instructions="Look things up sparingly.",
        )
        fake_client.completions.responses = [tool_call_response("look_up", {"query": "KP.3"}), text_response("Done.")]
        chat = make_chat(tmp_path, tools=(look_up,))

        chat.send("Go")

        assert [tool["function"]["name"] for tool in fake_client.completions.calls[0]["tools"]][0] == "look_up"
        assert "Look things up sparingly." in request_messages(fake_client, 0)[0]["content"]
        assert of(chat.events_since(), "tool_output")[0].text == "Found KP.3."


def looking_up(name: str = "look_up", instructions: str | None = None) -> Tool:
    return Tool(
        name=name,
        description="Looks something up.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        function=lambda query: f"Found {query}.",
        instructions=instructions,
    )


class TestToolsThatCannotBeHadBeforeTheFirstMessage:
    def test_they_are_asked_for_once_with_the_first_message_and_the_lead_is_given_them(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        asked: list[int] = []

        def late() -> tuple[Tool, ...]:
            asked.append(1)

            return (looking_up(instructions="Look things up sparingly."),)

        fake_client.completions.responses = [
            tool_call_response("look_up", {"query": "KP.3"}),
            text_response("Done."),
            text_response("Again."),
        ]
        chat = make_chat(tmp_path, late_tools=late)
        assert asked == []

        chat.send("Go")
        chat.send("Once more")

        assert asked == [1]
        assert [tool["function"]["name"] for tool in fake_client.completions.calls[0]["tools"]][0] == "look_up"
        assert "Look things up sparingly." in request_messages(fake_client, 0)[0]["content"]
        assert of(chat.events_since(), "tool_output")[0].text == "Found KP.3."
        assert [tool.name for tool in chat.tools] == ["look_up"]

    def test_they_are_added_to_the_tools_the_conversation_was_given(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [text_response("Done.")]
        chat = make_chat(tmp_path, tools=(looking_up("first"),), late_tools=lambda: [looking_up("second")])

        chat.send("Go")

        names = [tool["function"]["name"] for tool in fake_client.completions.calls[0]["tools"]]
        assert names[:2] == ["first", "second"]

    def test_the_team_is_given_them_too(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [
            tool_call_response("consult", {"member": "Immunologist", "agenda": "Is it immunogenic?", "rounds": 1}),
            text_response("A first answer."),
            text_response("A critique."),
            text_response("A better answer."),
            text_response("Not immunogenic."),
        ]
        chat = make_chat(tmp_path, late_tools=lambda: (looking_up(),))

        chat.send("Is it immunogenic?")

        scientist = fake_client.completions.calls[1]
        assert [tool["function"]["name"] for tool in scientist["tools"]] == ["look_up"]

    def test_a_turn_fails_before_anything_is_spent_when_they_cannot_be_had_and_the_next_asks_again(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        attempts: list[int] = []

        def late() -> tuple[Tool, ...]:
            attempts.append(1)
            if len(attempts) == 1:
                raise ConnectionError("The server did not answer")

            return (looking_up(),)

        fake_client.completions.responses = [text_response("Done.")]
        chat = make_chat(tmp_path, late_tools=late)

        failed = chat.send("Go")

        assert failed.status == "failed"
        assert failed.error == "ConnectionError: The server did not answer"
        assert fake_client.completions.calls == []
        assert chat.tools == ()

        answered = chat.send("Try again")

        assert answered.status == "answered"
        assert len(attempts) == 2
        assert [tool.name for tool in chat.tools] == ["look_up"]

    def test_a_turn_ends_as_stopped_when_what_supplies_them_says_it_was(self, tmp_path: Path) -> None:
        def late() -> tuple[Tool, ...]:
            raise chat_module.ChatStopped()

        chat = make_chat(tmp_path, late_tools=late)

        reply = chat.send("Go")

        assert reply.status == "stopped"
        assert kinds(chat.events_since())[-1] == "stopped"

    @pytest.mark.parametrize(
        ("given", "message"),
        [
            (lambda: ("not a tool",), "A conversation's tools are Tools, not str"),
            (lambda: (looking_up("consult"),), "has tools of its own named consult"),
            (lambda: (looking_up("look_up"), looking_up("look_up")), "look_up is given more than once"),
        ],
    )
    def test_a_tool_that_cannot_be_given_fails_the_turn_and_none_of_them_is_kept(
        self, fake_client: FakeClient, tmp_path: Path, given: Any, message: str
    ) -> None:
        chat = make_chat(tmp_path, late_tools=given)

        reply = chat.send("Go")

        assert reply.status == "failed"
        assert message in (reply.error or "")
        assert chat.tools == ()
        assert fake_client.completions.calls == []

    def test_a_name_the_conversation_already_has_cannot_be_given_again(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path, tools=(looking_up(),), late_tools=lambda: (looking_up(),))

        reply = chat.send("Go")

        assert reply.status == "failed"
        assert "look_up is given more than once" in (reply.error or "")


class TestTellingOfWhatTheToolsDo:
    def test_an_event_is_numbered_kept_and_passed_on_like_the_others(self, tmp_path: Path) -> None:
        told: list[ChatEvent] = []
        chat = make_chat(tmp_path, on_event=told.append)

        event = chat.tell("approval", "Waits for you", request="a1", state="waiting")

        assert (event.kind, event.text, dict(event.data)) == (
            "approval",
            "Waits for you",
            {"request": "a1", "state": "waiting"},
        )
        assert told == [event]
        assert chat.events_since() == [event]
        saved = [json.loads(line) for line in (tmp_path / "chat" / "events.jsonl").read_text().splitlines()]
        assert [(item["kind"], item["id"]) for item in saved] == [("approval", event.id)]

    @pytest.mark.parametrize("kind", ["connection", "approval", "question"])
    def test_a_connection_an_approval_and_a_question_can_be_told_of(self, tmp_path: Path, kind: str) -> None:
        chat = make_chat(tmp_path)

        assert chat.tell(kind).kind == kind  # type: ignore[arg-type]

    @pytest.mark.parametrize("kind", ["user", "answer", "stopped", "failed", "status", "writing", "nonsense"])
    def test_what_the_researcher_and_the_lead_say_and_how_a_turn_ends_cannot_be_told_of_from_outside(
        self, tmp_path: Path, kind: str
    ) -> None:
        chat = make_chat(tmp_path)

        with pytest.raises(ValueError, match="can be told of from outside"):
            chat.tell(kind)  # type: ignore[arg-type]

        assert chat.events_since() == []


class TestFiles:
    def test_a_file_is_saved_where_the_session_finds_it_under_a_name_that_is_safe(
        self, session: LocalSession, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path, session=session)

        saved = chat.save_upload("..\\..//data/.counts.csv", b"a,b\n1,2\n")

        assert saved == Attachment(name="counts.csv", path="uploads/counts.csv", size=8)
        assert (session.directory / "uploads" / "counts.csv").read_bytes() == b"a,b\n1,2\n"
        assert chat.uploads_dir == session.directory / "uploads"
        assert session.run("print(open('uploads/counts.csv').read().strip().splitlines())").output.strip() == (
            "['a,b', '1,2']"
        )

    def test_without_a_session_files_are_kept_with_the_conversation(self, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)

        chat.save_upload("notes.txt", b"x")

        assert (tmp_path / "chat" / "uploads" / "notes.txt").read_bytes() == b"x"

    def test_a_file_is_never_replaced_but_the_same_file_is_not_kept_twice(self, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)

        first = chat.save_upload("counts.csv", b"one")
        same = chat.save_upload("counts.csv", io.BytesIO(b"one"))
        other = chat.save_upload("counts.csv", b"two")
        third = chat.save_upload("counts.csv", b"three")

        assert [first.name, same.name, other.name, third.name] == [
            "counts.csv",
            "counts.csv",
            "counts (2).csv",
            "counts (3).csv",
        ]
        assert (tmp_path / "chat" / "uploads" / "counts.csv").read_bytes() == b"one"
        assert sorted(path.name for path in (tmp_path / "chat" / "uploads").iterdir()) == [
            "counts (2).csv",
            "counts (3).csv",
            "counts.csv",
        ]

    def test_a_file_that_is_too_large_is_refused_and_leaves_nothing(self, tmp_path: Path) -> None:
        chat = make_chat(tmp_path, max_upload_bytes=10)

        with pytest.raises(UploadTooLargeError, match="larger than the 10 bytes"):
            chat.save_upload("big.bin", io.BytesIO(b"x" * 11))

        assert list((tmp_path / "chat" / "uploads").iterdir()) == []
        assert chat.save_upload("ok.bin", b"x" * 10).size == 10

    def test_names_are_made_safe(self) -> None:
        assert safe_filename("/etc/passwd") == "passwd"
        assert safe_filename("C:\\Users\\me\\data.csv") == "data.csv"
        assert safe_filename("..") == "upload"
        assert safe_filename("a\x00b\n.txt") == "ab.txt"
        assert safe_filename("") == "upload"
        long = safe_filename("n" * 400 + ".csv")
        assert len(long) == 200 and long.endswith(".csv")
        assert describe_size(8) == "8 bytes" and describe_size(1536) == "1.5 KB"
        assert describe_size(5 * 1024**2) == "5.0 MB" and describe_size(3 * 1024**3) == "3.0 GB"

    def test_a_name_is_kept_short_in_bytes_not_in_characters(self, tmp_path: Path) -> None:
        long = safe_filename("é" * 300 + ".csv")

        assert len(long.encode()) <= 200 and long.endswith(".csv") and set(long[:-4]) == {"é"}
        assert len(safe_filename("a" + "é" * 300 + ".tar" + "ü" * 40).encode()) <= 200

        # A file system takes it, and a number added to it
        chat = make_chat(tmp_path)
        first = chat.save_upload("é" * 300 + ".csv", b"one")
        second = chat.save_upload("é" * 300 + ".csv", b"two")
        assert second.name == f"{first.name[:-4]} (2).csv"
        assert [(tmp_path / "chat" / "uploads" / name).read_bytes() for name in (first.name, second.name)] == [
            b"one",
            b"two",
        ]

    def test_files_saved_at_once_under_one_name_all_keep_their_own(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chat = make_chat(tmp_path)
        replace = chat_module.os.replace

        def slowly(source: Any, target: Any) -> None:
            # Long enough for every upload to have looked for a free name before any takes it
            time.sleep(0.05)
            replace(source, target)

        monkeypatch.setattr(chat_module.os, "replace", slowly)
        saved: list[Attachment] = []
        threads = [
            threading.Thread(target=lambda number=number: saved.append(chat.save_upload("a.txt", f"{number}".encode())))
            for number in range(6)
        ]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert len({attachment.name for attachment in saved}) == 6
        assert sorted((chat.uploads_dir / attachment.name).read_bytes() for attachment in saved) == [
            f"{number}".encode() for number in range(6)
        ]

    def test_the_lead_is_told_of_the_files_attached_to_a_message(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path, session=session)
        counts = chat.save_upload("counts.csv", b"a,b\n1,2\n")
        chat.save_upload("other.csv", b"x")

        chat.send("Look at this.", attachments=[counts, "other.csv"])

        content = request_messages(fake_client, 0)[-1]["content"]
        assert content == (
            "Look at this.\n\nThe researcher attached these files, which are in the session's working directory:\n"
            "- uploads/counts.csv (8 bytes)\n- uploads/other.csv (1 bytes)"
        )
        (user,) = of(chat.events_since(), "user")
        assert user.data["attachments"] == [counts.to_dict(), Attachment("other.csv", "uploads/other.csv", 1).to_dict()]

    def test_a_message_can_be_only_a_file_and_without_a_session_the_lead_is_told_it_cannot_open_it(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path)
        chat.save_upload("counts.csv", b"abc")

        chat.send("", attachments=["counts.csv"])

        assert request_messages(fake_client, 0)[-1]["content"] == (
            "The researcher attached these files, but there is no session to open them in:\n"
            "- uploads/counts.csv (3 bytes)"
        )
        assert chat.title == "counts.csv"

    def test_without_a_session_the_lead_is_told_of_the_tool_that_looks_inside_a_table_if_it_has_it(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        inspect = Tool(
            name="inspect_data_file",
            description="Looks inside a table.",
            parameters={"type": "object", "properties": {}},
            function=lambda: "A table.",
        )
        chat = make_chat(tmp_path, tools=(inspect,))
        chat.save_upload("counts.csv", b"abc")

        chat.send("", attachments=["counts.csv"])

        assert request_messages(fake_client, 0)[-1]["content"] == (
            "The researcher attached these files. There is no session to run code on them, but inspect_data_file "
            "can look inside a table or a spreadsheet:\n- uploads/counts.csv (3 bytes)"
        )

    def test_with_a_session_the_lead_is_told_the_files_are_in_it_whether_or_not_it_has_that_tool(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        inspect = Tool(
            name="inspect_data_file",
            description="Looks inside a table.",
            parameters={"type": "object", "properties": {}},
            function=lambda: "A table.",
        )
        chat = make_chat(tmp_path, session=session, tools=(inspect,))
        chat.save_upload("counts.csv", b"abc")

        chat.send("", attachments=["counts.csv"])

        assert request_messages(fake_client, 0)[-1]["content"] == (
            "The researcher attached these files, which are in the session's working directory:\n"
            "- uploads/counts.csv (3 bytes)"
        )

    def test_a_link_that_code_made_is_not_a_file_that_was_attached(self, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)
        chat.save_upload("counts.csv", b"abc")
        (tmp_path / "secret.txt").write_text("secret")
        (chat.uploads_dir / "link.txt").symlink_to(tmp_path / "secret.txt")

        with pytest.raises(ValueError, match="was attached to this conversation"):
            chat.send("Look.", attachments=["link.txt"])

        assert chat.turns == 0

    @pytest.mark.parametrize("name", ["missing.csv", "../outside.csv", "uploads/counts.csv"])
    def test_a_file_that_was_not_attached_is_refused(self, name: str, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)
        chat.save_upload("counts.csv", b"abc")
        (tmp_path / "outside.csv").write_text("secret")

        with pytest.raises(ValueError, match="was attached to this conversation"):
            chat.send("Look.", attachments=[name])

        assert chat.turns == 0


class TestTeam:
    def test_the_lead_convenes_the_team_and_is_given_the_summary(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [
            team_meeting(members=("Immunologist", "Scientific Critic"), rounds=1),
            text_response("Opening thoughts."),
            text_response("An immunology view."),
            text_response("A critique."),
            text_response("The summary of the team."),
            text_response("The lab found a summary."),
        ]
        chat = make_chat(tmp_path)

        reply = chat.send("Design a nanobody.")

        assert reply.text == "The lab found a summary."
        events = chat.events_since()
        assert kinds(events)[:5] == ["user", "title", "usage", "tool_calls", "lab"]
        assert kinds(events)[-3:] == ["tool_output", "usage", "answer"]

        # The meeting's events, as the conversation's, told of with the call that started it
        assert {event.data["call"] for event in of(events, "lab")} == {"call_1"}
        assert {event.data["meeting"] for event in of(events, "lab")} == {"lab_001"}
        assert [event.data["event"] for event in of(events, "lab")][:2] == ["started", "turn"]
        assert [event.data["event"] for event in of(events, "lab")][-1] == "finished"
        assert [(event.speaker, event.data["round"]) for event in lab_events(events, "turn")] == [
            ("Principal Investigator", 1),
            ("Immunologist", 1),
            ("Scientific Critic", 1),
            ("Principal Investigator", 2),
        ]
        said = [(event.speaker, event.text) for event in lab_events(events, "message")]
        assert said == [
            ("Principal Investigator", "Opening thoughts."),
            ("Immunologist", "An immunology view."),
            ("Scientific Critic", "A critique."),
            ("Principal Investigator", "The summary of the team."),
        ]
        assert lab_events(events, "finished")[0].text == "The summary of the team."
        started = lab_events(events, "started")[0]
        assert started.data["details"]["meeting_type"] == "team"
        assert started.data["details"]["agenda"] == "Design a nanobody."

        # The lead is given the summary, and who took part
        (output,) = of(events, "tool_output")
        assert output.data == {"call": "call_1", "name": "convene_team"}
        assert output.text == (
            "Immunologist, Scientific Critic took part in a discussion that you led, for 1 round of discussion. "
            "The summary you reached with them:\n\nThe summary of the team."
        )
        assert request_messages(fake_client, 5)[-1] == {
            "role": "tool",
            "tool_call_id": "call_1",
            "content": output.text,
        }

        # It was held as a project holds a meeting, so it is saved, and counted
        (step,) = chat.project.steps
        assert (step.name, step.status) == ("lab_001", "completed")
        assert json.loads((tmp_path / "chat" / "lab" / "meetings" / "lab_001.json").read_text())[-1]["message"] == (
            "The summary of the team."
        )
        assert chat.usage.num_calls == 6 and chat.spent == pytest.approx(6 * PER_RESPONSE)
        assert [event.data["num_calls"] for event in of(events, "usage")] == [1, 2, 3, 4, 5, 6]

    def test_code_the_team_runs_is_the_meetings_to_tell_of_not_the_leads(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            team_meeting(members=("Immunologist",), rounds=1),
            text_response("Opening."),
            tool_call_response("run_code", {"code": "print(6 * 7)"}),
            text_response("It is 42."),
            text_response("Summary."),
            text_response("Done."),
        ]
        chat = make_chat(tmp_path, session=session)

        chat.send("Go")

        events = chat.events_since()
        assert of(events, "cell") == []
        (cell,) = lab_events(events, "cell")
        assert (cell.data["call"], cell.data["details"]["code"], cell.data["details"]["output"]) == (
            "call_1",
            "print(6 * 7)",
            "42\n",
        )
        assert cell.data["details"]["plot_paths"] == [str(session.directory / "plots" / "figure_1.png")]

    def test_a_meetings_prompts_and_usage_are_not_passed_on(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [team_meeting(rounds=0), text_response("Alone."), text_response("Done.")]
        chat = make_chat(tmp_path)

        chat.send("Design a nanobody.")

        events = chat.events_since()
        assert "usage" not in {event.data["event"] for event in of(events, "lab")}
        assert "prompt" not in {event.data["details"].get("kind") for event in lab_events(events, "message")}
        # The transcript has them
        transcript = json.loads((tmp_path / "chat" / "lab" / "meetings" / "lab_001.json").read_text())
        assert transcript[0]["agent"] == "User" and "Design a nanobody." in transcript[0]["message"]

    def test_the_lead_consults_one_scientist_who_is_reviewed_by_the_critic(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            tool_call_response("consult", {"member": "Immunologist", "agenda": "Is it immunogenic?", "rounds": 1}),
            text_response("A first answer."),
            text_response("A critique."),
            text_response("A better answer."),
            text_response("Not immunogenic."),
        ]
        chat = make_chat(tmp_path)

        chat.send("Is it immunogenic?")

        events = chat.events_since()
        assert [(event.speaker, event.data["round"]) for event in lab_events(events, "turn")] == [
            ("Immunologist", 1),
            ("Scientific Critic", 1),
            ("Immunologist", 2),
        ]
        assert lab_events(events, "started")[0].data["details"]["meeting_type"] == "individual"
        (output,) = of(events, "tool_output")
        assert output.text == (
            "Immunologist worked on it, with the Scientific Critic reviewing, for 1 round of review. "
            "Their answer:\n\nA better answer."
        )

    def test_the_agenda_and_questions_are_the_meetings(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [
            tool_call_response(
                "consult",
                {
                    "member": "immunologist",
                    "agenda": "Is it immunogenic?",
                    "questions": ["Where?", "How much?"],
                    "rounds": 0,
                },
            ),
            text_response("Yes."),
            text_response("Done."),
        ]
        chat = make_chat(tmp_path)

        chat.send("Go")

        prompt = request_messages(fake_client, 1)[-1]["content"]
        assert "Is it immunogenic?" in prompt and "1. Where?" in prompt and "2. How much?" in prompt

    def test_the_meetings_options_are_the_conversations(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [team_meeting(rounds=0), text_response("Alone."), text_response("Done.")]
        chat = make_chat(tmp_path, temperature=0.7, max_completion_tokens=500)

        chat.send("Go")

        assert [call["temperature"] for call in fake_client.completions.calls] == [0.7, 0.7, 0.7]
        assert [call["max_completion_tokens"] for call in fake_client.completions.calls] == [500, 500, 500]

    @pytest.mark.parametrize(
        ("call", "arguments", "refusal"),
        [
            (
                "convene_team",
                {"agenda": "Go", "members": ["Astrologer"]},
                'Not held: there is no "Astrologer" on your team',
            ),
            ("convene_team", {"agenda": "Go", "members": []}, "Not held: name at least one member"),
            ("convene_team", {"agenda": "Go", "members": ["Principal Investigator"]}, "you lead the discussion"),
            ("convene_team", {"agenda": "  ", "members": ["Immunologist"]}, "Not held: the agenda is empty"),
            (
                "consult",
                {"member": "Scientific Critic", "agenda": "Go"},
                'Not held: "Scientific Critic" cannot be consulted',
            ),
            ("consult", {"member": "Nobody", "agenda": "Go"}, 'Not held: "Nobody" cannot be consulted'),
        ],
    )
    def test_a_request_that_cannot_be_held_is_answered_and_costs_nothing(
        self, fake_client: FakeClient, tmp_path: Path, call: str, arguments: dict[str, Any], refusal: str
    ) -> None:
        fake_client.completions.responses = [tool_call_response(call, arguments), text_response("I see.")]
        chat = make_chat(tmp_path)

        reply = chat.send("Go")

        assert reply.text == "I see."
        assert refusal in of(chat.events_since(), "tool_output")[0].text
        assert chat.project.steps == () and len(fake_client.completions.calls) == 2

    def test_a_request_the_lead_got_wrong_is_answered_with_the_error(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            tool_call_response("convene_team", {"agenda": "Go"}),
            text_response("I see."),
        ]
        chat = make_chat(tmp_path)

        chat.send("Go")

        assert of(chat.events_since(), "tool_output")[0].text.startswith('Error running tool "convene_team": TypeError')

    def test_the_lead_may_start_only_so_many_sessions_for_one_message(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            team_meeting(rounds=0),
            text_response("Alone."),
            team_meeting(rounds=0),
            text_response("Done."),
        ]
        chat = make_chat(tmp_path, max_delegations=1)

        chat.send("Go")

        outputs = of(chat.events_since(), "tool_output")
        assert "which is the most allowed" in outputs[1].text and "worked 1 time on this message" in outputs[1].text
        assert [step.name for step in chat.project.steps] == ["lab_001"]

        # The next message has the team as it had at first
        fake_client.completions.responses = [team_meeting(rounds=0), text_response("Alone."), text_response("Done.")]
        chat.send("Again")

        assert [step.name for step in chat.project.steps] == ["lab_001", "lab_002"]

    def test_the_rounds_the_lead_asks_for_are_limited(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [
            tool_call_response("consult", {"member": "Immunologist", "agenda": "Go", "rounds": 9}),
            text_response("Alone."),
            text_response("Done."),
        ]
        chat = make_chat(tmp_path, max_rounds=0)

        chat.send("Go")

        # One answer, and no review
        assert len(fake_client.completions.calls) == 3
        assert "round" in of(chat.events_since(), "tool_output")[0].text

    def test_a_scientist_with_a_critic_of_the_rosters_own_is_reviewed_by_it(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        critic = Agent("Scientific Critic", "being a stickler", "find faults", "review", model=TEST_MODEL)
        fake_client.completions.responses = [
            tool_call_response("consult", {"member": "Immunologist", "agenda": "Go", "rounds": 1}),
            text_response("An answer."),
            text_response("A critique."),
            text_response("A better answer."),
            text_response("Done."),
        ]
        chat = Chat(tmp_path / "chat", LEAD, (IMMUNOLOGIST, critic), resources="none", max_retries=0)

        chat.send("Go")

        assert "being a stickler" in request_messages(fake_client, 2)[0]["content"]

    def test_a_failed_meeting_is_answered_with_the_error_and_the_lead_goes_on(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            team_meeting(rounds=0),
            RuntimeError("The server went away"),
            text_response("I could not ask the team."),
        ]
        chat = make_chat(tmp_path)

        reply = chat.send("Go")

        assert reply.status == "answered"
        (output,) = of(chat.events_since(), "tool_output")
        assert output.text == 'Error running tool "convene_team": RuntimeError: The server went away'
        assert lab_events(chat.events_since(), "failed")[0].text == "The server went away"
        assert [step.status for step in chat.project.steps] == ["failed"]

    def test_an_agent_cannot_have_the_title_of_the_researchers_notes(self, tmp_path: Path) -> None:
        impostor = Agent(HUMAN_SPEAKER, "x", "y", "z", model=TEST_MODEL)

        with pytest.raises(ValueError, match="no agent may have it"):
            Chat(tmp_path / "chat", LEAD, (impostor,))


class TestBudget:
    def test_the_leads_requests_and_the_teams_count_towards_one_limit(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            team_meeting(members=("Immunologist",), rounds=1),
            text_response("Opening."),
            text_response("A view."),
            text_response("Summary."),
            text_response("Done."),
        ]
        # Room for two requests, and the one that begins before the limit is reached
        chat = make_chat(tmp_path, max_cost=PER_RESPONSE * 2.5)

        reply = chat.send("Go")

        assert reply.status == "failed"
        assert reply.error is not None and reply.error.startswith("BudgetExceededError: The conversation has cost")
        assert len(fake_client.completions.calls) == 3
        events = chat.events_since()
        assert kinds(events)[-1] == "failed" and of(events, "failed")[0].data["type"] == "BudgetExceededError"
        assert of(events, "usage")[-1].data["max_cost"] == PER_RESPONSE * 2.5
        assert chat.spent == pytest.approx(3 * PER_RESPONSE)

        # The meeting was stopped by it, which the lead was told, and what it did is kept
        (output,) = of(events, "tool_output")
        assert output.text.startswith('Error running tool "convene_team": BudgetExceededError')
        assert [step.status for step in chat.project.steps] == ["failed"]
        assert chat.messages[-1]["role"] == "tool"

    def test_a_conversation_that_has_spent_its_limit_asks_for_nothing_more(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path, max_cost=PER_RESPONSE)
        assert chat.send("One").status == "answered"

        reply = chat.send("Two")

        assert reply.status == "failed" and reply.error is not None and "BudgetExceededError" in reply.error
        assert len(fake_client.completions.calls) == 1

    def test_a_limit_is_for_the_whole_conversation_and_every_run_of_it(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path, max_cost=PER_RESPONSE * 1.5)
        assert chat.send("One").status == "answered"
        chat.close()

        again = make_chat(tmp_path, max_cost=PER_RESPONSE * 1.5)
        assert again.send("Two").status == "answered"
        assert again.send("Three").status == "failed"

        # The second run began with what the first had spent, and the third was refused before it asked
        assert again.spent == pytest.approx(2 * PER_RESPONSE)
        assert len(fake_client.completions.calls) == 2

    def test_a_model_without_a_price_cannot_be_limited(self, fake_client: FakeClient, tmp_path: Path) -> None:
        unpriced = Agent("Immunologist", "x", "y", "z", model="not-a-priced-model")

        with pytest.raises(CostUnknownError, match="max_cost cannot be enforced"):
            Chat(tmp_path / "chat", LEAD, (unpriced,), max_cost=1.0)

        Chat(tmp_path / "chat", LEAD, (unpriced,))

    @pytest.mark.parametrize("limit", [-1.0, float("inf"), float("nan")])
    def test_a_limit_must_be_a_finite_amount(self, tmp_path: Path, limit: float) -> None:
        with pytest.raises(ValueError, match="max_cost must be a finite amount"):
            make_chat(tmp_path, max_cost=limit)


class Silence:
    """A model that says nothing to the nth request until it is let go, and then answers it as it would have."""

    def __init__(self, fake_client: FakeClient, number: int = 1) -> None:
        self.reached = threading.Event()
        self.finished = threading.Event()
        self._release = threading.Event()
        self._asked = 0
        create = fake_client.completions.create

        def create_when_let_go(**kwargs: Any) -> Any:
            self._asked += 1
            held = self._asked == number
            if held:
                self.reached.set()
                assert self._release.wait(20), "The model was never let go"
            try:
                return create(**kwargs)
            finally:
                if held:
                    self.finished.set()

        fake_client.completions.create = create_when_let_go  # type: ignore[method-assign]

    def release(self) -> None:
        self._release.set()
        assert self.finished.wait(10)


def sent_in_thread(chat: Chat, text: str) -> tuple[threading.Thread, list[ChatReply]]:
    replies: list[ChatReply] = []
    turn = threading.Thread(target=lambda: replies.append(chat.send(text)))
    turn.start()

    return turn, replies


class TestSteering:
    @pytest.fixture(autouse=True)
    def quick_polls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(llm_module, "INTERRUPT_POLL_SECONDS", 0.01)

    def test_a_stop_ends_a_request_to_a_model_that_says_nothing_and_what_it_says_later_is_dropped(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        silence = Silence(fake_client)
        chat = make_chat(tmp_path)
        turn, replies = sent_in_thread(chat, "Go")
        assert silence.reached.wait(10)

        assert chat.stop()
        turn.join(10)

        assert not turn.is_alive()
        assert replies[0].status == "stopped"
        assert chat.state == "idle"
        assert chat.messages[-1]["content"] == STOPPED_REPLY
        before = len(chat.events_since())

        silence.release()
        time.sleep(0.1)

        assert len(chat.events_since()) == before
        assert chat.usage.num_calls == 0
        # What it said was not kept, and the conversation goes on from where it was stopped
        fake_client.completions.responses = [text_response("Back again.")]
        assert chat.send("Hello again").text == "Back again."
        assert request_messages(fake_client, 1)[-2]["content"] == STOPPED_REPLY

    def test_a_stop_ends_a_reply_that_was_to_be_written_as_it_came_and_none_of_it_is_told_later(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [text_response("Nanobodies are small antibodies.")]
        silence = Silence(fake_client)
        chat = make_chat(tmp_path, stream=True)
        turn, replies = sent_in_thread(chat, "What is a nanobody?")
        assert silence.reached.wait(10)

        chat.stop()
        turn.join(10)
        silence.release()
        time.sleep(0.1)

        assert replies[0].status == "stopped"
        assert of(chat.events_since(), "writing") == []

    def test_a_stop_ends_a_team_session_whose_model_says_nothing_and_says_so_to_the_lead(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [team_meeting(rounds=1), text_response("Opening.")]
        silence = Silence(fake_client, number=2)
        chat = make_chat(tmp_path)
        turn, replies = sent_in_thread(chat, "Go")
        assert silence.reached.wait(10)

        chat.stop()
        turn.join(10)
        silence.release()

        assert not turn.is_alive()
        assert replies[0].status == "stopped"
        events = chat.events_since()
        assert lab_events(events, "failed")[0].data["details"]["type"] == "ChatStopped"
        assert of(events, "tool_output")[0].text == (
            "The researcher stopped the team before it finished, so there is no summary."
        )
        assert chat.state == "idle"

    def test_a_stopped_turn_ends_before_the_next_call_and_leaves_a_conversation_that_goes_on(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            tool_calls_response(("run_code", {"code": "print(1)"}), ("run_code", {"code": "print(2)"})),
        ]
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "tool_output":
                chat.stop()

        chat = make_chat(tmp_path, session=session, on_event=on_event)

        reply = chat.send("Go")

        assert reply.status == "stopped" and reply.text == "" and reply.error is None
        events = chat.events_since()
        assert kinds(events) == [
            "user",
            "title",
            "usage",
            "tool_calls",
            "cell",
            "tool_output",
            "tool_output",
            "stopped",
        ]
        outputs = of(events, "tool_output")
        assert [output.data["call"] for output in outputs] == ["call_1", "call_2"]
        assert outputs[1].text == "Not run: the researcher stopped the turn."
        assert of(events, "stopped")[0].text == "Stopped by you. What was done is kept."
        assert [cell.data["code"] for cell in of(events, "cell")] == ["print(1)"]
        assert chat.state == "idle"

        # Every call has its answer, so what is sent next is valid, and says what happened
        assert [message["role"] for message in chat.messages] == ["user", "assistant", "tool", "tool", "assistant"]
        assert chat.messages[-1]["content"] == STOPPED_REPLY

        fake_client.completions.responses = [text_response("Back again.")]
        chat.on_event = None
        assert chat.send("Hello again").text == "Back again."
        assert request_messages(fake_client, 1)[-2]["content"] == STOPPED_REPLY
        assert request_messages(fake_client, 1)[-1] == {"role": "user", "content": "Hello again"}

    def test_a_stop_before_anything_is_sent_ends_the_turn_without_a_request(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "user":
                chat.stop()

        chat = make_chat(tmp_path, on_event=on_event)

        assert chat.send("Go").status == "stopped"
        assert fake_client.completions.calls == []

    def test_a_stop_ends_a_reply_as_it_is_written(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [text_response("Nanobodies are small antibodies.")]
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "writing" and event.text.startswith("Nanobodies are"):
                chat.stop()

        chat = make_chat(tmp_path, stream=True, on_event=on_event)

        reply = chat.send("What is a nanobody?")

        assert reply.status == "stopped"
        assert chat.messages[-1]["content"] == STOPPED_REPLY
        assert chat.usage.num_calls == 0

    def test_a_stop_ends_a_team_session_where_it_is_and_keeps_what_was_said(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [team_meeting(rounds=1), text_response("Opening.")]
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "lab" and event.data["event"] == "message" and event.text == "Opening.":
                chat.stop()

        chat = make_chat(tmp_path, on_event=on_event)

        reply = chat.send("Go")

        assert reply.status == "stopped"
        assert len(fake_client.completions.calls) == 2
        events = chat.events_since()
        assert lab_events(events, "failed")[0].data["details"]["partial_path"] is not None
        # The chat page tells a session the researcher stopped from one that went wrong by this
        assert lab_events(events, "failed")[0].data["details"]["type"] == "ChatStopped"
        assert (tmp_path / "chat" / "lab" / "meetings" / "partial" / "lab_001.json").is_file()
        assert of(events, "tool_output")[0].text == (
            "The researcher stopped the team before it finished, so there is no summary."
        )
        assert [step.status for step in chat.project.steps] == ["failed"]
        assert [message["role"] for message in chat.messages] == ["user", "assistant", "tool", "assistant"]

    def test_a_note_is_read_by_the_lead_before_its_next_request(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            tool_call_response("run_code", {"code": "print(1)"}),
            text_response("Done."),
        ]
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "tool_calls":
                assert chat.add_note("  Use the other file.  ")

        chat = make_chat(tmp_path, session=session, on_event=on_event)

        chat.send("Go")

        assert request_messages(fake_client, 1)[-1] == {
            "role": "user",
            "content": "The human researcher added a note while you were working:\n\nUse the other file.",
        }
        assert [message["role"] for message in chat.messages] == ["user", "assistant", "tool", "user", "assistant"]
        (note,) = of(chat.events_since(), "note")
        assert (note.speaker, note.text, note.data) == (
            HUMAN_SPEAKER,
            "Use the other file.",
            {"to": "lead", "read": True},
        )

    def test_a_note_is_read_by_the_team_when_it_is_working_and_the_lead_is_told_so(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            team_meeting(rounds=1),
            text_response("Opening."),
            text_response("A view."),
            text_response("Summary."),
            text_response("Done."),
        ]
        chat: Chat
        added: list[bool] = []

        def on_event(event: ChatEvent) -> None:
            if event.kind == "lab" and event.data["event"] == "turn" and not added:
                added.append(chat.add_note("Mind the glycosylation."))

        chat = make_chat(tmp_path, on_event=on_event)

        chat.send("Go")

        assert added == [True]
        (note,) = of(chat.events_since(), "note")
        assert note.data == {"to": "lab", "read": True}
        transcript = json.loads((tmp_path / "chat" / "lab" / "meetings" / "lab_001.json").read_text())
        assert {"agent": HUMAN_SPEAKER, "message": "Mind the glycosylation."} in transcript
        assert of(chat.events_since(), "tool_output")[0].text.endswith(
            "While the team worked, the researcher told it:\n\nMind the glycosylation."
        )
        # The lead was not given it twice
        assert [m["role"] for m in chat.messages if "glycosylation" in str(m.get("content"))] == ["tool"]

    def test_a_note_that_comes_too_late_is_told_of_as_not_read(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat: Chat
        added: list[bool] = []

        def on_event(event: ChatEvent) -> None:
            if event.kind == "usage":
                added.append(chat.add_note("Also KP.3."))

        chat = make_chat(tmp_path, on_event=on_event)

        chat.send("Go")

        assert added == [True]
        (note,) = of(chat.events_since(), "note")
        assert (note.text, note.data) == ("Also KP.3.", {"to": None, "read": False})
        assert kinds(chat.events_since())[-2:] == ["note", "answer"]
        assert len(chat.messages) == 2

    def test_notes_are_only_taken_while_the_lead_is_working(self, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)

        assert chat.add_note("Hello?") is False
        assert (chat.pause(), chat.resume(), chat.stop()) == (False, False, False)

    def test_a_paused_turn_waits_before_its_next_request_until_it_is_resumed(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [text_response("Hello.")]
        states: list[str] = []
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "status":
                states.append(event.data["state"])
            if event.kind == "user":
                assert chat.pause()

        chat = make_chat(tmp_path, on_event=on_event)

        thread = chat.start("Hi")

        last = 0
        while chat.state != "paused":
            events = chat.wait_for_events(last, timeout=5)
            assert events, "The turn never reached the pause"
            last = events[-1].id
        assert fake_client.completions.calls == []
        assert thread.is_alive()

        # One message at a time
        with pytest.raises(ChatBusyError):
            chat.send("Another")
        with pytest.raises(ChatBusyError):
            chat.start("Another")

        assert chat.resume()
        thread.join(timeout=10)

        assert not thread.is_alive()
        assert chat.last_reply is not None and chat.last_reply.text == "Hello."
        assert states == ["running", "pausing", "paused", "running", "idle"]

    def test_a_paused_turn_can_be_stopped(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "user":
                chat.pause()

        chat = make_chat(tmp_path, on_event=on_event)
        thread = chat.start("Hi")
        while chat.state != "paused":
            chat.wait_for_events(0, timeout=0.01)

        assert chat.stop()
        thread.join(timeout=10)

        assert chat.last_reply is not None and chat.last_reply.status == "stopped"
        assert fake_client.completions.calls == []
        assert chat.state == "idle"

    def test_a_paused_team_session_waits_before_its_next_turn(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [team_meeting(rounds=0), text_response("Alone."), text_response("Done.")]
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "tool_calls":
                chat.pause()

        chat = make_chat(tmp_path, on_event=on_event)
        thread = chat.start("Go")
        while chat.state != "paused":
            chat.wait_for_events(0, timeout=0.01)

        # The meeting has been started, but not its first request
        assert len(fake_client.completions.calls) == 1
        assert lab_events(chat.events_since(), "turn") == []

        chat.resume()
        thread.join(timeout=10)

        assert chat.last_reply is not None and chat.last_reply.text == "Done."

    def test_a_page_waits_for_what_happens_next(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)

        assert chat.wait_for_events(0, timeout=0.01) == []

        thread = chat.start("Hi")
        thread.join(timeout=10)
        events = chat.wait_for_events(0, timeout=5)

        assert kinds(events, leave_out=()) == ["user", "title", "usage", "answer", "status"]
        later = chat.wait_for_events(events[-1].id, timeout=0.01)
        assert later == []

    def test_closing_the_conversation_stops_a_turn_and_wakes_those_waiting(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "user":
                chat.pause()

        chat = make_chat(tmp_path, on_event=on_event)
        chat.start("Hi")
        while chat.state != "paused":
            chat.wait_for_events(0, timeout=0.01)
        woken: list[Any] = []
        waiting = threading.Thread(target=lambda: woken.append(chat.wait_for_events(10**6, timeout=10)))
        waiting.start()

        chat.close(timeout=10)
        waiting.join(timeout=10)

        assert woken == [[]]
        assert chat.last_reply is not None and chat.last_reply.status == "stopped"


class TestCallbacks:
    def test_a_callback_that_fails_does_not_leave_the_conversation_running(
        self, fake_client: FakeClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake_client.completions.responses = [tool_call_response("look_up", {}), text_response("Back.")]

        def on_event(event: ChatEvent) -> None:
            if event.kind in ("tool_calls", "tool_output", "failed", "status"):
                raise RuntimeError("The page went away")

        chat = make_chat(tmp_path, on_event=on_event)

        reply = chat.send("Go")

        assert (reply.status, reply.error) == ("failed", "RuntimeError: The page went away")
        assert chat.state == "idle" and chat.last_reply == reply
        # Every call has its answer, and the ending is told of, and kept, though no one could be told
        reason = "Not run: RuntimeError: The page went away"
        assert [(m["role"], m.get("content")) for m in chat.messages][-1] == ("tool", reason)
        assert kinds(chat.events_since()) == ["user", "title", "usage", "tool_calls", "tool_output", "failed"]
        assert json.loads((tmp_path / "chat" / "chat.json").read_text())["running"] is False
        assert "Warning: on_event failed when told of the end of the turn" in capsys.readouterr().out

        # And it goes on
        chat.on_event = None
        fake_client.completions.responses = [text_response("Back.")]
        assert chat.send("Again").text == "Back."

    def test_a_turn_that_cannot_be_ended_properly_still_gives_the_conversation_back(
        self, fake_client: FakeClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_client.completions.responses = [tool_call_response("look_up", {}), text_response("Back.")]

        def on_event(event: ChatEvent) -> None:
            if event.kind == "tool_calls":
                raise RuntimeError("The page went away")

        append = chat_module.append_json_line

        def failing(path: Path, item: Any) -> None:
            if item.get("role") == "tool":
                raise OSError("No space left on device")
            append(path, item)

        chat = make_chat(tmp_path, on_event=on_event)
        monkeypatch.setattr(chat_module, "append_json_line", failing)

        with pytest.raises(OSError, match="No space left"):
            chat.send("Go")

        assert chat.state == "idle"
        assert json.loads((tmp_path / "chat" / "chat.json").read_text())["running"] is False

    def test_no_callback_is_called_with_the_conversations_lock_held(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        inside, go = threading.Event(), threading.Event()

        def work() -> str:
            inside.set()
            go.wait(20)
            return "Worked."

        working = Tool(name="work", description="Works", parameters={"type": "object", "properties": {}}, function=work)
        held: list[str] = []
        states: list[str] = []

        def on_event(event: ChatEvent) -> None:
            if chat._changed._is_owned():  # type: ignore[attr-defined]
                held.append(f"{event.kind} {event.data.get('state', '')}")
            if event.kind == "status":
                states.append(event.data["state"])

        chat = make_chat(tmp_path, tools=(working,), on_event=on_event)
        fake_client.completions.responses = [tool_call_response("work", {}), text_response("Done.")]
        turn = chat.start("First")
        assert inside.wait(10)
        chat.pause()
        go.set()
        while chat.state != "paused":
            chat.wait_for_events(0, timeout=0.01)
        chat.resume()
        turn.join(timeout=10)

        inside.clear()
        go.clear()
        fake_client.completions.responses = [tool_call_response("work", {}), text_response("Done.")]
        turn = chat.start("Second")
        assert inside.wait(10)
        chat.stop()
        go.set()
        turn.join(timeout=10)

        assert held == []
        assert states == ["running", "pausing", "paused", "running", "idle", "running", "stopping", "idle"]

    def test_a_callback_for_the_start_of_a_turn_that_is_slow_holds_up_no_one_either(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        entered, release = threading.Event(), threading.Event()

        def on_event(event: ChatEvent) -> None:
            if event.kind == "status" and event.data["state"] == "running":
                entered.set()
                release.wait(20)

        chat = make_chat(tmp_path, on_event=on_event)
        starting = threading.Thread(target=lambda: chat.start("Go").join(timeout=20))
        starting.start()
        assert entered.wait(10)

        following = threading.Thread(target=lambda: (chat.events_since(), chat.state, chat.wait_for_events(0, 0.01)))
        following.start()
        following.join(timeout=5)
        stuck = following.is_alive()
        release.set()
        starting.join(timeout=20)

        assert not stuck
        assert chat.last_reply is not None and chat.last_reply.status == "answered"

    def test_a_callback_that_is_slow_does_not_hold_up_those_following_the_conversation(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        inside, release, go = threading.Event(), threading.Event(), threading.Event()
        working = Tool(
            name="work",
            description="Works until told to stop",
            parameters={"type": "object", "properties": {}},
            function=lambda: (inside.set(), go.wait(20), "Worked.")[-1],
        )
        fake_client.completions.responses = [tool_call_response("work", {}), text_response("Done.")]
        entered = threading.Event()

        def on_event(event: ChatEvent) -> None:
            if event.kind == "status" and event.data["state"] == "pausing":
                entered.set()
                release.wait(20)

        chat = make_chat(tmp_path, tools=(working,), on_event=on_event)
        turn = chat.start("Go")
        assert inside.wait(10)

        pausing = threading.Thread(target=chat.pause)
        pausing.start()
        assert entered.wait(10)

        # The callback is waiting. Anyone else can still look at the conversation, and steer it
        following = threading.Thread(target=lambda: (chat.events_since(), chat.state, chat.add_note("Hi")))
        following.start()
        following.join(timeout=5)
        stuck = following.is_alive()
        release.set()
        go.set()
        pausing.join(timeout=10)

        assert not stuck
        while chat.state != "paused":
            chat.wait_for_events(0, timeout=0.01)
        assert chat.resume()
        turn.join(timeout=10)
        assert chat.last_reply is not None and chat.last_reply.text == "Done."


class TestResources:
    def test_resources_given_are_listed_to_the_lead(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path, session=session, resources=small_resources())

        chat.send("Hello")

        system = request_messages(fake_client, 0)[0]["content"]
        assert "These are the resources of Biomni's environment available in the session." in system
        assert "Method: find_gene" in system and "a.parquet: Table A." in system
        assert "find_resources" not in system
        (told,) = of(chat.events_since(), "resources")
        assert told.data["mode"] == "given"
        assert told.data["available"] == {"tools": 3, "data_lake": 2, "libraries": 2, "know_how": 1}
        assert told.data["selected"]["data_lake"] == ["a.parquet", "b.csv"]

    def test_the_lead_asks_which_resources_suit_a_task(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(chat_module, "available_resources", lambda session, commercial_mode: small_resources())
        fake_client.completions.responses = [
            tool_call_response("find_resources", {"task": "Find a gene linked to fever."}),
            text_response("TOOLS: [0]\nDATA_LAKE: []\nLIBRARIES: [1]\nKNOW_HOW: []"),
            text_response("Use find_gene."),
        ]
        chat = make_chat(tmp_path, session=session, resources="retrieve")

        reply = chat.send("Which gene?")

        assert reply.text == "Use find_gene."
        first = fake_client.completions.calls[0]
        assert "find_resources" in [tool["function"]["name"] for tool in first["tools"]]
        assert (
            "3 tool functions, 2 data lake files, 2 software libraries, 1 know-how documents"
            in (first["messages"][0]["content"])
        )
        assert "Method: find_gene" not in first["messages"][0]["content"]

        # The question of which resources suit it is asked on its own, as a meeting asks it
        retrieval = fake_client.completions.calls[1]
        assert len(retrieval["messages"]) == 1 and "tools" not in retrieval
        assert "USER QUERY: Find a gene linked to fever." in retrieval["messages"][0]["content"]

        events = chat.events_since()
        initial, chosen = of(events, "resources")
        assert initial.data["selected"] == {"tools": [], "data_lake": [], "libraries": [], "know_how": []}
        assert chosen.data["selected"]["tools"] == ["biomni.tool.genetics.find_gene"]
        assert chosen.data["selected"]["libraries"] == ["samtools"]
        assert chosen.data["retrieval"]["task"] == "Find a gene linked to fever."
        (output,) = of(events, "tool_output")
        assert "Method: find_gene" in output.text and "samtools: Alignments." in output.text
        assert "blast" not in output.text and "scanpy" not in output.text
        assert chat.usage.num_calls == 3

    def test_an_answer_that_names_nothing_is_not_a_choice(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(chat_module, "available_resources", lambda session, commercial_mode: small_resources())
        fake_client.completions.responses = [
            tool_call_response("find_resources", {"task": "Anything"}),
            text_response("I do not know."),
            text_response("Done."),
        ]
        chat = make_chat(tmp_path, session=session, resources="retrieve")

        chat.send("Go")

        assert "could not be worked out" in of(chat.events_since(), "tool_output")[0].text

    def test_nothing_is_listed_with_none_and_there_is_no_tool_to_ask(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path, session=session)

        chat.send("Hello")

        assert [tool["function"]["name"] for tool in fake_client.completions.calls[0]["tools"]] == [
            "run_code",
            "convene_team",
            "consult",
        ]
        assert of(chat.events_since(), "resources") == []

    def test_the_resources_are_the_teams_too(
        self, fake_client: FakeClient, session: LocalSession, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [team_meeting(rounds=0), text_response("Alone."), text_response("Done.")]
        chat = make_chat(tmp_path, session=session, resources=small_resources())

        chat.send("Go")

        # In what the team is first told of, not only what the lead is
        assert "Method: find_gene" in request_messages(fake_client, 1)[1]["content"]

    def test_resources_need_a_session(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="needs a session"):
            make_chat(tmp_path, resources=small_resources())

        with pytest.raises(ValueError, match="resources must be"):
            make_chat(tmp_path, resources="some")


class TestKeeping:
    def test_a_conversation_is_carried_on_from_where_it_was_left(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [team_meeting(rounds=0), text_response("Alone."), text_response("First.")]
        chat = make_chat(tmp_path)
        chat.send("One")
        before = chat.events_since()
        chat.close()

        fake_client.completions.responses = [
            team_meeting(rounds=0),
            text_response("Alone again."),
            text_response("Second."),
        ]
        again = make_chat(tmp_path)

        assert (again.title, again.turns, again.state) == ("One", 1, "idle")
        # Everything but the state it was in, which is not kept
        assert before[-1].kind == "status"
        assert again.events_since() == before[:-1]
        assert again.messages == chat.messages
        assert again.usage.num_calls == 3

        seen: list[ChatEvent] = []
        again.on_event = seen.append
        reply = again.send("Two")

        assert reply.text == "Second."
        # The lead reads what was said before, in order, with the new message last
        sent = request_messages(fake_client, 3)
        assert [message["role"] for message in sent] == ["system", "user", "assistant", "tool", "assistant", "user"]
        assert sent[-1]["content"] == "Two"
        events = again.events_since()
        assert [event.turn for event in events if event.kind == "user"] == [1, 2]
        assert len({event.id for event in events}) == len(events)
        assert [event.id for event in events] == sorted(event.id for event in events)
        # Numbered after the state the conversation was left in, which a page may have been told of
        assert (seen[0].kind, seen[0].id > before[-1].id) == ("status", True)
        # What it held is not held under the same name again
        assert [step.name for step in again.project.steps] == ["lab_001", "lab_002"]
        assert again.usage.num_calls == 6

    def test_a_turn_that_a_process_did_not_end_is_ended_when_the_conversation_is_opened(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path)
        chat.send("One")
        directory = tmp_path / "chat"
        info = json.loads((directory / "chat.json").read_text())
        (directory / "chat.json").write_text(json.dumps({**info, "running": True, "turns": 2}))
        with (directory / "messages.jsonl").open("a") as file:
            file.write(json.dumps({"role": "user", "content": "Two"}) + "\n")
            file.write(
                json.dumps(
                    {
                        "role": "assistant",
                        "name": "Principal_Investigator",
                        "content": None,
                        "tool_calls": [
                            {"id": "a", "type": "function", "function": {"name": "run_code", "arguments": "{}"}},
                            {"id": "b", "type": "function", "function": {"name": "run_code", "arguments": "{}"}},
                        ],
                    }
                )
                + "\n"
            )
            file.write(json.dumps({"role": "tool", "tool_call_id": "a", "content": "Done."}) + "\n")

        again = make_chat(tmp_path)

        reason = "The process running this conversation stopped before the turn ended."
        assert again.messages[-1] == {"role": "tool", "tool_call_id": "b", "content": f"Not run. {reason}"}
        last = again.events_since()[-1]
        assert (last.kind, last.text, last.data) == ("failed", reason, {"type": "Interrupted"})
        assert json.loads((directory / "chat.json").read_text())["running"] is False

        # It can be carried on, and is not ended again
        assert again.send("Three").status == "answered"
        assert kinds(make_chat(tmp_path).events_since()).count("failed") == 1

    def test_text_that_python_would_split_lines_at_is_kept_whole(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [text_response("An answer\u2028with\x85odd\x0bbreaks.")]
        chat = make_chat(tmp_path)
        chat.send("A line\u2028another\x85 and\x1ca third")
        chat.close()

        again = make_chat(tmp_path)

        assert again.messages == chat.messages
        assert again.messages[0]["content"] == "A line\u2028another\x85 and\x1ca third"
        assert again.events_since() == [event for event in chat.events_since() if event.kind != "status"]

    def test_a_last_line_that_is_whole_but_not_ended_is_not_run_into_the_next(self, tmp_path: Path) -> None:
        path = tmp_path / "lines.jsonl"
        path.write_text('{"a": 1}\n{"b": 2}', encoding="utf-8")

        assert chat_module.read_json_lines(path) == [{"a": 1}, {"b": 2}]
        chat_module.append_json_line(path, {"c": 3})

        assert chat_module.read_json_lines(path) == [{"a": 1}, {"b": 2}, {"c": 3}]

    def test_a_last_line_cut_in_the_middle_of_a_character_is_dropped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "lines.jsonl"
        path.write_bytes('{"a": "é"}\n{"b": "é'.encode()[:-1])

        assert chat_module.read_json_lines(path) == [{"a": "é"}]
        assert path.read_bytes() == '{"a": "é"}\n'.encode()
        assert "was cut short" in capsys.readouterr().out

    def test_a_reader_that_is_not_the_conversation_leaves_the_file_as_it_is(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "lines.jsonl"
        path.write_text('{"a": 1}\n{"b": ', encoding="utf-8")

        assert chat_module.read_json_lines(path, repair=False) == [{"a": 1}]
        assert path.read_text(encoding="utf-8") == '{"a": 1}\n{"b": '
        # The line may be one that is still being written, so it is not said to have been cut short
        assert capsys.readouterr().out == ""

        assert chat_module.read_json_lines(path) == [{"a": 1}]
        assert path.read_text(encoding="utf-8") == '{"a": 1}\n'
        assert "cut short" in capsys.readouterr().out

    def test_a_line_cut_short_by_a_crash_is_dropped_and_any_other_is_an_error(
        self, fake_client: FakeClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        make_chat(tmp_path).send("One")
        directory = tmp_path / "chat"
        with (directory / "events.jsonl").open("a") as file:
            file.write('{"kind": "usage", "id"')

        again = make_chat(tmp_path)

        assert "cut short" in capsys.readouterr().out
        assert kinds(again.events_since()) == ["user", "title", "usage", "answer"]
        assert lines(directory / "events.jsonl")[-1]["kind"] == "answer"

        text = (directory / "messages.jsonl").read_text()
        (directory / "messages.jsonl").write_text("not json\n" + text)
        with pytest.raises(ValueError, match="Line 1 of .*messages.jsonl is not JSON"):
            make_chat(tmp_path)

    @pytest.mark.parametrize("line", ["[]", "5", '"text"', "null", "true", "[1, 2]"])
    def test_a_line_that_is_json_but_not_an_object_is_an_error_that_names_it(self, tmp_path: Path, line: str) -> None:
        path = tmp_path / "lines.jsonl"
        path.write_text('{"a": 1}\n' + line + "\n", encoding="utf-8")

        with pytest.raises(ValueError, match="Line 2 of .*lines.jsonl is not a JSON object"):
            chat_module.read_json_lines(path)

        assert path.read_text(encoding="utf-8") == '{"a": 1}\n' + line + "\n"

    @pytest.mark.parametrize(
        ("name", "content", "message"),
        [
            ("chat.json", "[]", "chat.json cannot be used: it holds list, not an object"),
            ("chat.json", "null", "chat.json cannot be used: it holds NoneType, not an object"),
            ("chat.json", "{oops", "chat.json cannot be read: "),
            ("chat.json", '{"turns": "many"}', "its turns should be a whole number, not str"),
            ("chat.json", '{"turns": -1}', "its turns should be a whole number, not int"),
            ("chat.json", '{"events": true}', "its events should be a whole number, not bool"),
            ("chat.json", '{"lab_calls": 1.5}', "its lab_calls should be a whole number, not float"),
            ("chat.json", '{"title": 5}', "its title should be text, not int"),
            ("chat.json", '{"created_at": []}', "its created_at should be text, not list"),
            ("chat.json", '{"usage": []}', "its usage should be the usage a conversation saves, not list"),
            ("chat.json", '{"usage": {"per_model": []}}', "its usage should be the usage"),
            ("chat.json", '{"usage": {"per_model": {"m": 5}}}', "its usage should be the usage"),
            ("chat.json", '{"usage": {"per_model": {"m": {"input_tokens": "5"}}}}', "its usage should be the usage"),
            ("events.jsonl", "[]\n", "Line 1 of .*events.jsonl is not a JSON object"),
            ("events.jsonl", "{}\n", "Event 1 of .*events.jsonl cannot be used: An event has no kind"),
            (
                "events.jsonl",
                '{"kind": "user", "id": "1", "turn": 1, "speaker": null, "text": "", "data": {}, "time": 0}\n',
                "Event 1 of .*events.jsonl cannot be used: An event's id should be a whole number, not str",
            ),
            ("messages.jsonl", "[]\n", "Line 1 of .*messages.jsonl is not a JSON object"),
            ("messages.jsonl", '{"content": "hi"}\n', "Message 1 of .*messages.jsonl cannot be used: it has no role"),
            ("messages.jsonl", '{"role": 3}\n', "Message 1 of .*messages.jsonl cannot be used: it has no role"),
        ],
    )
    def test_a_file_that_holds_what_a_conversation_does_not_save_is_an_error_that_names_it(
        self, fake_client: FakeClient, tmp_path: Path, name: str, content: str, message: str
    ) -> None:
        make_chat(tmp_path).send("One")
        directory = tmp_path / "chat"
        kept = (directory / name).read_text()
        (directory / name).write_text(content)

        with pytest.raises(ValueError, match=message):
            make_chat(tmp_path)

        # What is not understood is left as it was, to be put right by whoever knows what it should be
        assert (directory / name).read_text() == content
        (directory / name).write_text(kept)
        assert kinds(make_chat(tmp_path).events_since()) == ["user", "title", "usage", "answer"]

    def test_what_a_later_version_saved_that_this_one_does_not_know_is_not_refused(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        make_chat(tmp_path).send("One")
        path = tmp_path / "chat" / "chat.json"
        info = json.loads(path.read_text())
        info["usage"]["per_model"][TEST_MODEL]["future_tokens"] = "many"
        info["something_new"] = [1]
        path.write_text(json.dumps(info))

        again = make_chat(tmp_path)

        assert again.usage.per_model[TEST_MODEL].input_tokens == info["usage"]["per_model"][TEST_MODEL]["input_tokens"]

    @pytest.mark.parametrize("part", ["id", "turn", "time"])
    def test_an_event_has_numbers_that_are_numbers_and_not_true_or_false(self, part: str) -> None:
        saved = ChatEvent(kind="user", id=1, turn=1, text="Hello").to_dict()
        saved[part] = True

        with pytest.raises(ValueError, match=f"An event's {part} should be a "):
            ChatEvent.from_dict(saved)

    def test_an_event_may_be_told_of_at_a_whole_number_of_seconds(self) -> None:
        saved = ChatEvent(kind="user", id=1, turn=1, text="Hello").to_dict()
        saved["time"] = 5

        assert ChatEvent.from_dict(saved).time == 5

    @pytest.mark.parametrize("event", ["", "kind", "speaker"])
    def test_an_event_may_have_no_speaker_but_not_lack_any_other_part(self, event: str) -> None:
        saved = ChatEvent(kind="user", id=1, turn=1, text="Hello").to_dict()
        if event:
            del saved[event]

        if event == "":
            assert ChatEvent.from_dict(saved) == ChatEvent(kind="user", id=1, turn=1, text="Hello")
        else:
            with pytest.raises(ValueError, match=f"An event has no {event}"):
                ChatEvent.from_dict(saved)

    def test_an_event_that_is_not_an_object_is_refused(self) -> None:
        with pytest.raises(ValueError, match="An event is an object, not list"):
            ChatEvent.from_dict([])  # type: ignore[arg-type]

    def test_the_project_the_conversation_keeps_its_meetings_in_is_not_another(self, tmp_path: Path) -> None:
        make_chat(tmp_path)

        assert json.loads((tmp_path / "chat" / "lab" / "project.json").read_text())["goal"] == (
            "Conversation with the head of a lab"
        )


class TestReplacingTheLastMessage:
    def test_a_failed_turn_is_taken_back_and_sent_again(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [
            text_response("One."),
            RuntimeError("The server went away"),
            text_response("Two."),
        ]
        chat = make_chat(tmp_path)
        chat.send("First")
        chat.send("Second")
        failed_ids = [event.id for event in chat.events_since() if event.turn == 2]
        seen: list[ChatEvent] = []
        chat.on_event = seen.append

        reply = chat.send("Second", replace_last=True)

        assert reply.text == "Two."
        assert chat.turns == 2
        # The lead is told of the first turn, and the message that is sent again, and nothing of the one that failed
        sent = request_messages(fake_client, 2)
        assert [(message["role"], message.get("content")) for message in sent[1:]] == [
            ("user", "First"),
            ("assistant", "One."),
            ("user", "Second"),
        ]
        assert [(message["role"], message["content"]) for message in chat.messages] == [
            ("user", "First"),
            ("assistant", "One."),
            ("user", "Second"),
            ("assistant", "Two."),
        ]

        events = chat.events_since()
        assert kinds(events) == ["user", "title", "usage", "answer", "withdrawn", "user", "usage", "answer"]
        assert not set(failed_ids) & {event.id for event in events}
        (withdrawn,) = of(events, "withdrawn")
        assert (withdrawn.turn, withdrawn.data) == (2, {"turn": 2})
        assert [event.turn for event in of(events, "user")] == [1, 2]
        assert [event.id for event in events] == sorted(event.id for event in events)
        assert [event.kind for event in seen if event.kind in ("withdrawn", "user")] == ["withdrawn", "user"]

        # What is kept is what is told of, and a conversation that is opened again reads the same
        directory = tmp_path / "chat"
        assert lines(directory / "messages.jsonl") == chat.messages
        assert [ChatEvent.from_dict(item) for item in lines(directory / "events.jsonl")] == [
            event for event in events if event.kind != "status"
        ]
        chat.close()
        again = make_chat(tmp_path)
        assert again.messages == chat.messages
        assert [event.id for event in again.events_since()] == [event.id for event in events if event.kind != "status"]
        assert again.turns == 2

    def test_an_answer_can_be_taken_back_and_the_message_changed(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [text_response("Nanobodies."), text_response("Antibodies.")]
        chat = make_chat(tmp_path)
        chat.save_upload("counts.csv", b"abc")
        chat.send("What is a nanobody?", attachments=["counts.csv"])
        assert chat.title == "What is a nanobody?"

        chat.send("What is an antibody?", attachments=["counts.csv"], replace_last=True)

        assert [message["role"] for message in chat.messages] == ["user", "assistant"]
        assert chat.messages[0]["content"].startswith("What is an antibody?")
        assert "nanobody" not in json.dumps(request_messages(fake_client, 1)[1:])
        events = chat.events_since()
        # The title was the first message's, and is the one that replaces it
        assert chat.title == "What is an antibody?"
        assert [event.text for event in of(events, "title")] == ["What is an antibody?"]
        (user,) = of(events, "user")
        assert user.data["attachments"][0]["name"] == "counts.csv"
        assert user.data["messages_before"] == 0

    def test_a_turn_that_left_nothing_to_the_lead_takes_nothing_else_with_it(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [text_response("One."), text_response("Two.")]
        chat = make_chat(tmp_path)
        chat.send("First")
        # A turn that failed before the lead was sent anything has no messages of its own
        chat._begin("Second", ())
        chat._end_turn()

        chat.send("Second again", replace_last=True)

        assert [message["content"] for message in chat.messages] == ["First", "One.", "Second again", "Two."]
        assert [event.turn for event in of(chat.events_since(), "user")] == [1, 2]

    def test_nothing_is_taken_back_if_the_message_cannot_be_sent(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)

        with pytest.raises(ValueError, match="There is no message to replace"):
            chat.send("Hello", replace_last=True)
        assert (chat.turns, chat.messages, chat.events_since()) == (0, [], [])

        fake_client.completions.responses = [text_response("One.")]
        chat.send("First")
        before = (chat.turns, chat.messages, chat.events_since())
        with pytest.raises(ValueError, match="needs something in it"):
            chat.send("  ", replace_last=True)
        with pytest.raises(ValueError, match="No file named"):
            chat.send("Again", attachments=["missing.csv"], replace_last=True)

        assert (chat.turns, chat.messages, chat.events_since()) == before

    def test_a_message_saved_before_messages_could_be_replaced_cannot_be(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [text_response("One.")]
        chat = make_chat(tmp_path)
        chat.send("First")
        chat.close()
        directory = tmp_path / "chat"
        old = [
            {**item, "data": {"attachments": []}} if item["kind"] == "user" else item
            for item in lines(directory / "events.jsonl")
        ]
        (directory / "events.jsonl").write_text("".join(json.dumps(item) + "\n" for item in old))

        again = make_chat(tmp_path)

        with pytest.raises(ValueError, match="before messages could be replaced"):
            again.send("Again", replace_last=True)
        assert again.messages == chat.messages and again.state == "idle"

    def test_it_waits_for_the_lead_like_any_message(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [text_response("One.")]
        chat = make_chat(tmp_path)
        chat.send("First")
        release = threading.Event()
        chat.on_event = lambda event: release.wait(10) if event.kind == "usage" else None
        fake_client.completions.responses = [text_response("Two.")]
        thread = chat.start("Second")

        with pytest.raises(ChatBusyError):
            chat.send("Third", replace_last=True)
        release.set()
        thread.join(timeout=20)

        assert [message["content"] for message in chat.messages] == ["First", "One.", "Second", "Two."]


class TestFailures:
    def test_a_failed_turn_is_told_of_and_the_conversation_goes_on(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [RuntimeError("The server went away"), text_response("Back.")]
        chat = make_chat(tmp_path)

        reply = chat.send("Hello")

        assert reply == ChatReply("failed", "", "RuntimeError: The server went away", reply.usage, reply.elapsed_time)
        events = chat.events_since()
        assert kinds(events) == ["user", "title", "failed"]
        (failed,) = of(events, "failed")
        assert (failed.text, failed.data["type"]) == ("RuntimeError: The server went away", "RuntimeError")
        assert chat.state == "idle"

        assert chat.send("Hello again").text == "Back."

    def test_a_safety_flag_is_told_with_what_to_do_and_editing_takes_the_flagged_step_out(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        flagged = openai.APIError(
            "This content was flagged for possible biological risk. If this seems wrong, try rephrasing your request.",
            request=httpx.Request("POST", "https://api.example.test/v1/chat/completions"),
            body=None,
        )
        fake_client.completions.responses = [tool_call_response("look_up", {}), flagged, text_response("Reworded.")]
        chat = make_chat(tmp_path)

        reply = chat.send("Look it up")

        assert reply.status == "failed"
        assert reply.error is not None and reply.error.startswith(failures.SAFETY_FLAGGED + " (")
        assert reply.error.endswith("try rephrasing your request.)")
        (failed,) = of(chat.events_since(), "failed")
        assert failed.text == reply.error and failed.data["type"] == "APIError"

        # What the provider flagged is in the conversation, so a reworded message that replaces the last is the way on
        assert chat.send("Reworded", replace_last=True).text == "Reworded."
        sent = request_messages(fake_client, 2)
        assert [message["role"] for message in sent] == ["system", "user"]
        assert sent[1]["content"] == "Reworded"

    def test_a_provider_that_refuses_the_key_is_told_with_what_to_do_about_it(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        refusal = provider_refusal(openai.AuthenticationError, 401, "Error code: 401 - Incorrect API key provided")
        fake_client.completions.responses = [refusal, text_response("Back.")]
        chat = make_chat(tmp_path)

        reply = chat.send("Hello")

        assert reply.status == "failed"
        assert reply.error is not None and reply.error.startswith(KEY_REFUSED + " (")
        assert reply.error.endswith("Error code: 401 - Incorrect API key provided)")
        (failed,) = of(chat.events_since(), "failed")
        assert failed.text == reply.error
        assert failed.data["type"].endswith("AuthenticationError")
        assert chat.state == "idle"

        assert chat.send("Hello again").text == "Back."

    def test_what_a_failure_leaves_unanswered_is_closed_with_the_providers_words_alone(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [tool_call_response("look_up", {}), text_response("Back.")]

        def on_event(event: ChatEvent) -> None:
            if event.kind == "tool_calls":
                raise provider_refusal(openai.InternalServerError, 502, "<html><body>502 Bad Gateway</body></html>")

        chat = make_chat(tmp_path, on_event=on_event)

        reply = chat.send("Go")

        assert reply.error is not None and reply.error.startswith(UNWELL.format(status=502) + " (")
        # What the model reads on the next turn is what happened, not what to click
        assert [(m["role"], m.get("content")) for m in chat.messages][-1] == (
            "tool",
            "Not run: InternalServerError: 502 Bad Gateway",
        )

    def test_a_reply_with_nothing_in_it_is_a_failure(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [text_response("   ")]
        chat = make_chat(tmp_path)

        reply = chat.send("Hello")

        assert reply.error == "RuntimeError: Principal Investigator sent no answer"

    def test_a_conversation_that_has_outgrown_the_model_says_so(
        self, fake_client: FakeClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def too_long(**kwargs: Any) -> None:
            raise ContextLengthExceededError("Reduce num_rounds")

        monkeypatch.setattr(chat_module, "check_context_length", too_long)
        chat = make_chat(tmp_path)

        reply = chat.send("Hello")

        assert reply.error is not None and "Start a new conversation" in reply.error and "num_rounds" not in reply.error
        assert fake_client.completions.calls == []

    def test_a_session_that_will_not_start_fails_the_turn_before_anything_is_spent(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        class Broken(LocalSession):
            def start(self) -> None:
                raise RuntimeError("The image was never built")

        chat = make_chat(tmp_path, session=Broken(tmp_path / "work", warn=False))

        reply = chat.send("Hello")

        assert reply.error == "RuntimeError: The image was never built"
        assert fake_client.completions.calls == []
        assert chat.messages == []

    def test_an_exception_from_on_event_ends_the_turn(self, fake_client: FakeClient, tmp_path: Path) -> None:
        def on_event(event: ChatEvent) -> None:
            if event.kind == "usage":
                raise ValueError("The page closed")

        chat = make_chat(tmp_path, on_event=on_event)

        reply = chat.send("Hello")

        assert reply.error == "ValueError: The page closed"

    def test_an_exception_when_told_of_the_end_does_not_hide_how_it_ended(
        self, fake_client: FakeClient, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def on_event(event: ChatEvent) -> None:
            if event.kind == "answer":
                raise ValueError("The page closed")

        chat = make_chat(tmp_path, on_event=on_event)

        reply = chat.send("Hello")

        assert reply.status == "answered"
        assert (
            "on_event failed when told of the end of the turn: ValueError('The page closed')" in capsys.readouterr().out
        )
        assert chat.state == "idle"

    def test_an_interruption_ends_the_turn_properly_and_is_raised(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [KeyboardInterrupt()]
        chat = make_chat(tmp_path)

        with pytest.raises(KeyboardInterrupt):
            chat.send("Hello")

        assert chat.state == "idle" and kinds(chat.events_since())[-1] == "failed"
        assert json.loads((tmp_path / "chat" / "chat.json").read_text())["running"] is False

    def test_a_turn_that_cannot_start_a_thread_gives_the_conversation_back(
        self, fake_client: FakeClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def refuse(self: threading.Thread) -> None:
            raise RuntimeError("can't start new thread")

        monkeypatch.setattr(threading.Thread, "start", refuse)
        chat = make_chat(tmp_path)

        with pytest.raises(RuntimeError, match="can't start new thread"):
            chat.start("Hello")

        assert chat.state == "idle"

    @pytest.mark.parametrize(
        ("options", "message"),
        [
            ({"temperature": 3.0}, "temperature must be between 0 and 2"),
            ({"max_completion_tokens": 0}, "max_completion_tokens must be at least 1"),
            ({"max_tool_iterations": 0}, "max_tool_iterations must be at least 1"),
            ({"max_delegations": -1}, "max_delegations must be zero or more"),
            ({"max_rounds": -1}, "max_rounds must be zero or more"),
            ({"max_upload_bytes": 0}, "max_upload_bytes must be at least 1"),
            ({"tools": ("run_code",)}, "A conversation's tools are Tools, not str"),
        ],
    )
    def test_arguments_that_cannot_be_used_are_refused(
        self, tmp_path: Path, options: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValueError if "Tools" not in message else TypeError, match=message):
            make_chat(tmp_path, **options)

    def test_titles_must_be_their_own(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="must have different titles"):
            Chat(tmp_path / "chat", LEAD, (LEAD,))
        with pytest.raises(ValueError, match="must have different titles"):
            Chat(tmp_path / "chat", LEAD, (IMMUNOLOGIST, IMMUNOLOGIST))
        with pytest.raises(ValueError, match="needs a title"):
            Chat(tmp_path / "chat", LEAD, (Agent(" ", "x", "y", "z", TEST_MODEL),))

    def test_the_tools_that_are_the_conversations_own_cannot_be_taken(self, tmp_path: Path) -> None:
        tool = Tool(
            name="consult", description="x", parameters={"type": "object", "properties": {}}, function=lambda: ""
        )

        with pytest.raises(ValueError, match="has tools of its own named consult"):
            make_chat(tmp_path, tools=(tool,))
