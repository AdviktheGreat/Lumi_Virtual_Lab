"""Tests for saving a conversation with the head of a lab as a document, in HTML and as a PDF."""

import base64
import html
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from virtual_lab import export
from virtual_lab.chat import Chat
from virtual_lab.events import ChatEvent
from virtual_lab.export_chat import (
    Call,
    Figures,
    cell_html,
    chat_html,
    describe_call,
    describe_resources,
    how_it_went,
    load_chat,
    save_chat_html,
    save_chat_pdf,
    team_sessions_of,
    turns_of,
)

from conftest import FakeClient, text_response, tool_call_response
from test_chat import LEAD, TEAM, make_chat, team_meeting
from test_export import PNG, DrawingSession, in_order, needs_weasyprint, section
from test_export import text_of as marked_text_of


def text_of(document: str) -> str:
    """The text of a document as a person reads it, with the characters HTML escapes."""
    return html.unescape(marked_text_of(document))


@pytest.fixture
def session(tmp_path: Path):
    with DrawingSession(tmp_path / "work", warn=False, timeout=20) as opened:
        yield opened


def saved_chat(directory: Path, events: list[ChatEvent], **info: Any) -> Path:
    """A conversation as it would have been saved, for a test that needs events no conversation would make."""
    directory.mkdir(parents=True, exist_ok=True)
    chat_info = {
        "id": directory.name,
        "title": "A saved conversation",
        "created_at": "2025-03-04T05:06:07+00:00",
        "lead": {"title": "Lead", "expertise": "everything", "model": "gpt-test"},
        "team": [],
        "session": None,
        "spent": 0.0123,
        **info,
    }
    (directory / "chat.json").write_text(json.dumps(chat_info), encoding="utf-8")
    (directory / "events.jsonl").write_text("".join(json.dumps(event.to_dict()) + "\n" for event in events))

    return directory


_numbers = itertools.count(1)


def happened(kind: str, turn: int = 1, text: str = "", speaker: str | None = None, **data: Any) -> ChatEvent:
    return ChatEvent(kind=kind, id=next(_numbers), turn=turn, speaker=speaker, text=text, data=data, time=0.0)  # type: ignore[arg-type]


def cell(code: str = "print(1)", **made: Any) -> dict[str, Any]:
    return {"language": "python", "code": code, "status": "ok", "output": "1\n", "duration": 0.5, "plots": [], **made}


def call_events(name: str, arguments: dict[str, Any] | str, call: str = "call_1", said: str = "") -> ChatEvent:
    given = arguments if isinstance(arguments, str) else json.dumps(arguments)

    return happened("tool_calls", text=said, calls=[{"id": call, "name": name, "arguments": given}])


class TestTurns:
    def test_a_conversation_is_laid_out_turn_by_turn(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [
            text_response("Nanobodies are small antibodies."),
            text_response("**Yes**, and <script>alert(1)</script> is shown as text."),
        ]
        chat = make_chat(tmp_path)
        chat.send("What is a nanobody?")
        chat.send("Can *I* make one?\nIn a week?")
        chat.close()

        document = chat_html(tmp_path / "chat")
        text = text_of(document)

        assert "<title>What is a nanobody?</title>" in document
        assert "<h1>What is a nanobody?</h1>" in document
        assert "Virtual Lab · Conversation" in text
        assert "2 turns" in text and re.search(r"cost \$0\.\d{4}", text)
        # The lead is marked and every scientist of the team named, as the ones the lead can call on
        assert "The lead and the team it can call on" in text
        assert f"{LEAD.title} (lead)" in text
        assert all(agent.title in text for agent in TEAM)
        assert in_order(
            text,
            "Turn 1",
            "Researcher What is a nanobody?",
            f"{LEAD.title} Nanobodies are small antibodies.",
            "Turn 2",
            "Can *I* make one?",
            "Yes , and",
        )
        # What the researcher wrote is shown as it was written, and what the lead wrote as the Markdown it is
        assert "Can *I* make one?\nIn a week?" in document
        assert "<strong>Yes</strong>" in document
        assert "<script>" not in document.split("</style>", 1)[1]
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in document

    def test_what_the_researcher_attached_is_listed(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)
        data = chat.save_upload("data.csv", b"a,b\n1,2\n")
        notes = chat.save_upload("notes.txt", b"x" * 3000)
        chat.send("Look at these", [data, notes])
        chat.send("", [chat.save_upload("only.txt", b"y")])
        chat.close()

        text = text_of(chat_html(tmp_path / "chat"))

        assert in_order(text, "Look at these", "Attached", "data.csv (8 bytes)", "notes.txt (2.9 KB)")
        assert "only.txt (1 bytes)" in text

    def test_a_conversation_with_nothing_said_has_nothing_to_show(self, fake_client: FakeClient, tmp_path: Path) -> None:
        make_chat(tmp_path).close()

        text = text_of(chat_html(tmp_path / "chat"))

        assert "0 turns" in text
        assert "Nothing has been said in this conversation yet." in text
        assert "Turn 1" not in text

    def test_a_conversation_without_a_title_is_called_so(self, tmp_path: Path) -> None:
        chat_dir = saved_chat(tmp_path / "chat", [], title="")

        assert "<h1>Conversation</h1>" in chat_html(chat_dir)

    def test_a_turn_is_ended_as_it_ended(self, fake_client: FakeClient, tmp_path: Path) -> None:
        events = [
            happened("user", turn=1, text="One"),
            happened("answer", turn=1, text="Done."),
            happened("user", turn=2, text="Two"),
            happened("stopped", turn=2, text="I was stopped by the researcher before I finished."),
            happened("user", turn=3, text="Three"),
            happened("failed", turn=3, text="RuntimeError: The server went away", type="RuntimeError"),
            happened("user", turn=4, text="Four"),
            happened("stopped", turn=4),
            happened("user", turn=5, text="Five"),
            happened("failed", turn=5),
            happened("user", turn=6, text="Six"),
        ]
        document = chat_html(saved_chat(tmp_path / "chat", events))

        callouts = re.findall(r'<div class="callout( error)?">(.*?)</div>', document)
        assert callouts == [
            ("", "I was stopped by the researcher before I finished."),
            (" error", "RuntimeError: The server went away"),
            ("", "The researcher stopped this turn."),
            (" error", "This turn ended with an error."),
            ("", "This turn had not ended when the conversation was saved."),
        ]

    def test_a_turn_with_the_lead_doing_nothing_shows_no_lead(self, tmp_path: Path) -> None:
        events = [happened("user", text="One"), happened("failed", text="Boom")]

        document = chat_html(saved_chat(tmp_path / "chat", events))

        assert '<div class="speaker">Lead</div>' not in document

    def test_a_conversation_that_is_going_is_read_without_changing_it(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        chat = make_chat(tmp_path)
        chat.send("What is a nanobody?")
        chat.close()
        path = tmp_path / "chat" / "events.jsonl"
        with path.open("a") as file:
            file.write('{"kind": "tool_calls", "id"')
        before = path.read_bytes()

        document = chat_html(tmp_path / "chat")

        assert "What is a nanobody?" in document
        assert path.read_bytes() == before

    def test_events_that_were_written_out_of_order_are_read_in_the_order_they_happened(self, tmp_path: Path) -> None:
        chat_dir = saved_chat(tmp_path / "chat", [])
        events = [
            ChatEvent("answer", id=3, turn=1, text="Second."),
            ChatEvent("user", id=1, turn=1, text="First?"),
        ]
        (chat_dir / "events.jsonl").write_text("".join(json.dumps(event.to_dict()) + "\n" for event in events))

        assert [event.id for event in load_chat(chat_dir).events] == [1, 3]
        assert in_order(text_of(chat_html(chat_dir)), "First?", "Second.")

    def test_what_is_not_a_conversation_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            chat_html(tmp_path / "nowhere")
        (tmp_path / "chat").mkdir()
        (tmp_path / "chat" / "chat.json").write_text("[]")
        with pytest.raises(ValueError, match="is not a conversation's"):
            chat_html(tmp_path / "chat")
        (tmp_path / "chat" / "chat.json").write_text('{"title": "No id"}')
        with pytest.raises(ValueError, match="is not a conversation's"):
            load_chat(tmp_path / "chat")


class TestWhatTheLeadDid:
    def test_code_that_ran_is_shown_with_what_it_printed_and_the_figures_it_drew(
        self, fake_client: FakeClient, session: DrawingSession, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            tool_call_response("run_code", {"code": 'print("\\x1b[31m42\\x1b[0m")'}),
            text_response("It is 42, as the figure shows."),
        ]
        chat = make_chat(tmp_path, session=session)
        chat.send("What is 6 times 7?")
        chat.close()

        document = chat_html(tmp_path / "chat")
        text = text_of(document)

        assert in_order(
            text,
            "Turn 1",
            f"{LEAD.title} Python code ran in",
            'print("\\x1b[31m42\\x1b[0m")',
            "Output 42",
            "Figure 1. Drawn by the code above (plots/figure_1.png).",
            "It is 42, as the figure shows.",
        )
        assert '<span class="badge ok">ran in ' in document
        # What the code printed is shown without what a terminal would do with it
        assert "\x1b" not in document
        # The figure is in the document, which fetches nothing, and the call's own answer is not said again
        assert document.count(f'src="data:image/png;base64,{base64.b64encode(PNG).decode()}"') == 1
        assert "What it returned" not in text and "Ran in" not in text

    def test_code_that_failed_says_so_and_the_traceback_is_not_said_twice(
        self, fake_client: FakeClient, session: DrawingSession, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            tool_call_response("run_code", {"code": "1 / 0"}),
            text_response("That cannot be done."),
        ]
        chat = make_chat(tmp_path, session=session)
        chat.send("Divide by zero")
        chat.close()

        document = chat_html(tmp_path / "chat")

        assert '<span class="badge bad">failed after ' in document
        assert "ZeroDivisionError" in document
        assert document.count("division by zero") == 1
        assert 'class="callout error"' not in document

    def test_a_team_session_is_linked_to_from_what_brought_it_in_and_follows_the_conversation(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            team_meeting(agenda="Design a nanobody.\nMind the epitope.", members=("Immunologist", "Scientific Critic"), rounds=1),
            text_response("Opening thoughts."),
            text_response("An immunology view."),
            text_response("A critique."),
            text_response("The summary of the team."),
            text_response("The lab found a summary."),
        ]
        chat = make_chat(tmp_path)
        chat.send("Design a nanobody.")
        chat.close()

        document = chat_html(tmp_path / "chat")
        text = text_of(document)

        assert in_order(
            text,
            "Turn 1",
            "Convened the team",
            "Immunologist, Scientific Critic",
            "Design a nanobody. Mind the epitope.",
            "What the team told the lead",
            "The summary you reached with them: The summary of the team.",
            "Read the discussion",
            "The lab found a summary.",
            "Virtual Lab · Team meeting",
            "Lab 001",
            "An immunology view.",
        )
        assert "Mind the epitope." in document and "Design a nanobody.\nMind the epitope." in document
        assert '<a href="#team-session-lab_001">Read the discussion</a>' in document
        assert document.count('id="team-session-lab_001"') == 1
        # The session is a meeting laid out as one, from a page of its own
        assert '<section class="meeting" id="team-session-lab_001">' in document
        assert "A critique." in section(document, "Discussion", level=3)

    def test_a_team_session_can_be_left_out(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [
            team_meeting(rounds=0),
            text_response("The summary of the team."),
            text_response("The lab found a summary."),
        ]
        chat = make_chat(tmp_path)
        chat.send("Design a nanobody.")
        chat.close()

        document = chat_html(tmp_path / "chat", team_sessions=False)

        assert "Convened the team" in document
        assert "Read the discussion" not in document and "team-session" not in document
        assert "Virtual Lab · Team meeting" not in document
        assert "What the team told the lead" in document

    def test_a_consultation_says_who_was_asked(self, fake_client: FakeClient, tmp_path: Path) -> None:
        fake_client.completions.responses = [
            tool_call_response(
                "consult", {"member": "Immunologist", "agenda": "Is it immunogenic?", "rounds": 0}
            ),
            text_response("A draft."),
            text_response("Done consulting."),
        ]
        chat = make_chat(tmp_path)
        chat.send("Ask them")
        chat.close()

        text = text_of(chat_html(tmp_path / "chat"))

        assert in_order(text, "Consulted Immunologist", "Is it immunogenic?", "What the team told the lead")
        assert "Virtual Lab · Individual meeting" in text

    def test_a_session_that_was_stopped_is_there_as_far_as_it_got(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [team_meeting(rounds=1), text_response("Opening.")]
        chat: Chat

        def on_event(event: ChatEvent) -> None:
            if event.kind == "lab" and event.data["event"] == "message" and event.text == "Opening.":
                chat.stop()

        chat = make_chat(tmp_path, on_event=on_event)
        chat.send("Go")
        chat.close()

        document = chat_html(tmp_path / "chat")
        text = text_of(document)

        assert in_order(text, "Turn 1", "Convened the team", "The researcher stopped the team before it finished", "Read the discussion")
        assert "Stopped by you. What was done is kept." in text
        assert 'id="team-session-lab_001"' in document
        assert "Last said before it stopped" in document and "Opening." in text.split("Lab 001")[1]

    def test_a_session_that_cannot_be_read_is_said_so_and_the_rest_is_still_saved(
        self, fake_client: FakeClient, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            team_meeting(rounds=0),
            text_response("The summary of the team."),
            text_response("The lab found a summary."),
        ]
        chat = make_chat(tmp_path)
        chat.send("Design a nanobody.")
        chat.close()
        transcript = team_sessions_of(tmp_path / "chat")["lab_001"]
        transcript.write_text('[{"agent": "Immunologist"', encoding="utf-8")

        document = chat_html(tmp_path / "chat")

        assert document.count('id="team-session-lab_001"') == 1
        # It is a section like the others, headed as a meeting is, with what is wrong said as the sessions say it
        assert (
            '<div class="eyebrow">Virtual Lab · Team meeting</div><h2>Lab 001</h2>'
            '<div class="callout error">This session could not be read, so what was said in it is not here.</div>'
        ) in document
        assert '<a href="#team-session-lab_001">Read the discussion</a>' in document
        assert "The lab found a summary." in document

    @pytest.mark.parametrize("damage", [b"{not json", b"\xff\xfe{", b'{"agent": "x"}', b"[1]"])
    def test_a_session_that_is_not_what_it_should_be_does_not_stop_the_others_being_shown(
        self, damage: bytes, tmp_path: Path
    ) -> None:
        events = [happened("user", text="Go"), happened("answer", text="Done.")]
        chat_dir = saved_chat(tmp_path / "chat", events)
        lab = chat_dir / "lab"
        lab.mkdir()
        (lab / "lab_001.json").write_bytes(damage)
        (lab / "lab_002.json").write_text(json.dumps([{"agent": "Immunologist", "message": "An immunology view."}]))
        steps = [
            {"kind": "meeting", "name": name, "files": {"transcript": f"{name}.json"}} for name in ("lab_001", "lab_002")
        ]
        (lab / "project.json").write_text(json.dumps({"steps": steps}))

        document = chat_html(chat_dir)

        assert document.count("This session could not be read") == 1
        assert in_order(text_of(document), "Lab 001", "could not be read", "Lab 002", "An immunology view.")

    def test_a_session_that_cannot_be_opened_is_said_so(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        chat_dir = saved_chat(tmp_path / "chat", [happened("user", text="Go"), happened("answer", text="Done.")])
        lab = chat_dir / "lab"
        lab.mkdir()
        name = "lab_<img src=x>"
        (lab / "lab_001.json").write_text("[]")
        (lab / "project.json").write_text(
            json.dumps({"steps": [{"kind": "meeting", "name": name, "files": {"transcript": "lab_001.json"}}]})
        )

        def refuse(path: Path) -> None:
            raise PermissionError(path)

        monkeypatch.setattr("virtual_lab.export_chat.load_meeting", refuse)

        document = chat_html(chat_dir)

        assert "This session could not be read" in document
        assert "<img" not in document

    def test_a_note_is_shown_with_who_read_it(self, tmp_path: Path) -> None:
        events = [
            happened("user", text="Go"),
            happened("note", speaker="Human researcher", text="Use the other file.", to="lead", read=True),
            happened("note", speaker="Human researcher", text="Mind the epitope.", to="lab", read=True),
            happened("note", speaker="Human researcher", text="Also KP.3.", to=None, read=False),
            happened("answer", text="Done."),
        ]

        text = text_of(chat_html(saved_chat(tmp_path / "chat", events)))

        assert in_order(
            text,
            "A note to Lead Use the other file.",
            "A note to the team Mind the epitope.",
            "A note that came too late for anyone to read Also KP.3.",
            "Done.",
        )

    def test_what_the_lead_said_beside_its_calls_is_said_in_order(self, tmp_path: Path) -> None:
        events = [
            happened("user", text="Go"),
            call_events("run_code", {"code": "print(1)"}, "a", said="Let me **run** that."),
            happened("cell", **cell("print(1)"), call="a"),
            happened("tool_output", text="Ran in 0.5 seconds.", call="a", name="run_code"),
            call_events("run_code", {"code": "print(2)"}, "b", said="   "),
            happened("cell", **cell("print(2)", output="2\n"), call="b"),
            happened("tool_output", text="Ran.", call="b", name="run_code"),
            happened("answer", text="Both ran."),
        ]

        document = chat_html(saved_chat(tmp_path / "chat", events))

        assert in_order(
            text_of(document), "Let me run that.", "print(1)", "Output 1", "print(2)", "Output 2", "Both ran."
        )
        assert "<strong>run</strong>" in document
        # Whitespace is nothing that was said
        assert document.count('<div class="body"><p>') == 2

    def test_calls_made_together_each_have_their_own_answer(self, tmp_path: Path) -> None:
        events = [
            happened("user", text="Go"),
            happened(
                "tool_calls",
                calls=[
                    {"id": "a", "name": "run_code", "arguments": json.dumps({"code": "print('A')"})},
                    {"id": "b", "name": "find_resources", "arguments": json.dumps({"task": "Find a gene"})},
                ],
            ),
            happened("cell", **cell("print('A')", output="A\n"), call="a"),
            happened("tool_output", text="Ran.", call="a", name="run_code"),
            happened("tool_output", text="Use find_gene.", call="b", name="find_resources"),
            # Told of twice, as a stream that starts again would
            happened("tool_calls", calls=[{"id": "b", "name": "find_resources", "arguments": "{}"}]),
            happened("answer", text="Done."),
        ]

        text = text_of(chat_html(saved_chat(tmp_path / "chat", events)))

        assert in_order(
            text, "Python code ran in", "print('A')", "Output A", "Looked up resources", "Find a gene", "What it returned Use find_gene."
        )
        assert text.count("Looked up resources") == 1

    def test_a_tool_that_the_lead_made_up_or_called_with_nonsense_shows_what_it_was_given(self, tmp_path: Path) -> None:
        events = [
            happened("user", text="Go"),
            call_events("mystery_tool", {"target": "TP53", "depth": 2}, "a"),
            happened("tool_output", text="No such tool.", call="a", name="mystery_tool"),
            call_events("other_tool", "not json at all", "b"),
            happened("tool_output", text="Bad arguments.", call="b", name="other_tool"),
            call_events("empty_tool", {}, "c"),
            call_events("list_tool", "[1, 2]", "d"),
            happened("answer", text="Done."),
        ]

        document = chat_html(saved_chat(tmp_path / "chat", events))
        text = text_of(document)

        assert in_order(text, "Called mystery_tool", '"target": "TP53"', '"depth": 2', "What it returned No such tool.")
        assert in_order(text, "Called other_tool", "not json at all", "What it returned Bad arguments.")
        assert "language-json" in document
        # Nothing was given to the third, and what is not an object is shown as it was written
        assert text.count("Called empty_tool") == 1
        assert not re.search(r"Called empty_tool\s*{}", text)
        assert in_order(text, "Called list_tool", "[1, 2]")

    def test_an_answer_whose_call_was_not_told_of_is_shown_alone(self, tmp_path: Path) -> None:
        events = [
            happened("user", text="Go"),
            happened("tool_output", text="It ran.", call="lost", name="run_code"),
            happened("tool_output", text="Nameless.", call="", name=""),
            happened("cell", **cell(), call="unknown"),
            happened("lab", call="unknown", event="started", meeting="lab_009", details={}),
            happened("answer", text="Done."),
        ]

        text = text_of(chat_html(saved_chat(tmp_path / "chat", events)))

        assert in_order(text, "Ran Python code", "What it returned It ran.", "Called a tool", "Nameless.")
        assert "print(1)" not in text

    def test_code_that_did_not_run_is_shown_as_it_was_given(self, tmp_path: Path) -> None:
        events = [
            happened("user", text="Go"),
            call_events("run_code", {"code": "print(3)", "language": "r"}, "a"),
            happened("tool_output", text="Not run. The process stopped.", call="a", name="run_code"),
            call_events("run_code", "{broken", "b"),
            happened("failed", text="Interrupted", type="Interrupted"),
        ]

        text = text_of(chat_html(saved_chat(tmp_path / "chat", events)))

        assert in_order(text, "Ran R code", "print(3)", "What it returned Not run. The process stopped.")
        assert "Ran Python code" in text

    def test_resources_are_said_in_a_line(self, tmp_path: Path) -> None:
        events = [
            happened("user", text="Go"),
            happened("resources", mode="retrieve", available={"tools": 3, "data_lake": 2}, selected={}, retrieval={}),
            happened(
                "resources",
                mode="retrieve",
                available={},
                selected={"tools": ["a.b"], "libraries": ["samtools", "blast"]},
                retrieval={"task": "Find a gene"},
            ),
            happened("answer", text="Done."),
        ]

        text = text_of(chat_html(saved_chat(tmp_path / "chat", events)))

        assert in_order(
            text,
            "Resources it can look up: 3 tools, 2 data files",
            "Chose resources for a task: Find a gene · 1 tool, 2 software packages",
        )


class TestFigures:
    def test_a_figure_that_is_missing_or_outside_the_session_is_not_embedded(self, tmp_path: Path) -> None:
        (tmp_path / "work").mkdir()
        (tmp_path / "secret.png").write_bytes(PNG)
        (tmp_path / "work" / "notes.txt").write_text("not a picture")
        figures = Figures(tmp_path / "work")

        shown = [figures.html(path) for path in ("gone.png", "../secret.png", "notes.txt")]

        assert all("<img" not in html and "could not be found" in html for html in shown)
        assert [f"Figure {number}." in html for number, html in enumerate(shown, start=1)] == [True] * 3
        assert "<em>../secret.png could not be found.</em>" in shown[1]

    def test_where_the_session_is_not_known_the_figures_are_not_found(self) -> None:
        assert "could not be found" in Figures(None).html("plots/figure_1.png")

    def test_the_figures_are_looked_for_in_the_directory_the_caller_names(
        self, fake_client: FakeClient, session: DrawingSession, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            tool_call_response("run_code", {"code": "print(1)"}),
            text_response("Done."),
        ]
        chat = make_chat(tmp_path, session=session)
        chat.send("Go")
        chat.close()
        moved = tmp_path / "moved"
        session.directory.rename(moved)

        assert "could not be found" in chat_html(tmp_path / "chat")
        assert "data:image/png;base64," in chat_html(tmp_path / "chat", files_dir=moved)

    def test_a_cell_says_how_it_went_and_what_it_made(self, tmp_path: Path) -> None:
        figures = Figures(None)
        html = cell_html(
            cell(
                "run()",
                status="timeout",
                duration=5.0,
                output="partial\n",
                error="Stopped after 5 seconds",
                output_dropped=1234,
                value={"score": 0.9},
                plots=["a.png"],
                produced_files=["a.png", *(f"out/{number}.csv" for number in range(33))],
            ),
            figures,
            1000,
        )
        text = text_of(html)

        assert '<span class="badge warn">stopped at its time limit (5.0 s)</span>' in html
        assert "The middle of the output, 1,234 bytes, is left out." in text
        # The error is not in what was printed, so it is said
        assert '<div class="callout error">Stopped after 5 seconds</div>' in html
        assert in_order(text, "Output partial", "Value", '"score": 0.9', "Figure 1.", "Files it made:", "out/0.csv")
        # The figure is not one of the files it made, and only so many files are named
        assert "<code>a.png</code>" not in html
        assert "out/29.csv" in text and "out/30.csv" not in text and "and 3 more" in text
        assert figures.count == 1

    def test_long_output_is_cut_from_the_middle(self) -> None:
        text = text_of(cell_html(cell(output="a" * 500 + "b" * 500), Figures(None), 100))

        assert "characters left out" in text and "a" * 50 in text and "b" * 50 in text and "a" * 51 not in text

    @pytest.mark.parametrize(
        ("status", "duration", "said", "badge"),
        [
            ("ok", 1.25, "ran in 1.2 s", "ok"),
            ("ok", None, "ran", "ok"),
            ("ok", True, "ran", "ok"),
            ("error", 2.0, "failed after 2.0 s", "bad"),
            ("error", "x", "failed", "bad"),
            ("timeout", 3.0, "stopped at its time limit (3.0 s)", "warn"),
            ("timeout", None, "stopped at its time limit", "warn"),
            ("lost", 1.0, "the session ended while it ran", "warn"),
            ("something new", 1.0, "something new", "neutral"),
        ],
    )
    def test_how_it_went(self, status: str, duration: Any, said: str, badge: str) -> None:
        assert how_it_went(status, duration) == (said, badge)


class TestSayingWhatWasDone:
    @pytest.mark.parametrize(
        ("name", "arguments", "title", "details"),
        [
            ("run_code", {}, "Ran Python code", []),
            ("run_code", {"language": "bash"}, "Ran shell code", []),
            ("run_code", {"language": "Julia"}, "Ran Julia code", []),
            ("run_code", {"language": ""}, "Ran Python code", []),
            ("find_resources", {"task": "  Find\n a gene  "}, "Looked up resources", ["Find a gene"]),
            ("find_resources", {"task": "  "}, "Looked up resources", []),
            ("find_resources", {}, "Looked up resources", []),
            ("convene_team", {"members": ["A", " B ", "", 3], "agenda": " Go\nnow "}, "Convened the team", ["A, B", "Go\nnow"]),
            ("convene_team", {"members": "A", "agenda": 3}, "Convened the team", []),
            ("convene_team", {"members": ["A"]}, "Convened the team", ["A"]),
            ("consult", {"member": "Immunologist", "agenda": "Why?"}, "Consulted Immunologist", ["Why?"]),
            ("consult", {"agenda": ""}, "Consulted a scientist", []),
            ("consult", {"member": 4}, "Consulted a scientist", []),
            ("mystery", {"a": 1}, "Called mystery", []),
            ("", {}, "Called a tool", []),
        ],
    )
    def test_what_a_call_was(self, name: str, arguments: dict[str, Any], title: str, details: list[str]) -> None:
        assert describe_call(Call("x", name, ""), arguments) == (title, details)

    def test_a_scientists_name_and_a_task_are_kept_short(self) -> None:
        _, task = describe_call(Call("x", "find_resources", ""), {"task": "word " * 100})
        title, _ = describe_call(Call("x", "consult", ""), {"member": "N" * 100})

        assert len(task[0]) == 120 and task[0].endswith("…")
        assert title == f"Consulted {'N' * 59}…"

    @pytest.mark.parametrize(
        ("data", "said"),
        [
            ({"mode": "none"}, "No resources"),
            ({"mode": "retrieve", "available": {"tools": 1, "know_how": 2}}, "Resources it can look up: 1 tool, 2 know-how documents"),
            ({"mode": "retrieve", "available": {}}, "Resources it can look up"),
            ({"mode": "retrieve", "selected": {"tools": ["a"]}}, "Resources it can use: 1 tool"),
            ({"mode": "all", "available": {"tools": 4, "libraries": 1}}, "Resources it can use: 4 tools, 1 software package"),
            ({"mode": "all"}, "Resources it can use"),
            ({"mode": "given", "selected": {"data_lake": ["a", "b"]}, "available": {"tools": 9}}, "Resources it can use: 2 data files"),
            ({"mode": "all", "retrieval": {"task": "A task"}}, "Chose resources for a task: A task"),
            ({"mode": "all", "selected": "nonsense", "available": [], "retrieval": None}, "Resources it can use"),
            ({"mode": "all", "available": {"tools": True, "libraries": "3"}}, "Resources it can use"),
        ],
    )
    def test_what_the_lead_was_told_it_has(self, data: dict[str, Any], said: str) -> None:
        assert describe_resources(data) == said

    def test_events_outside_a_turn_are_not_part_of_one(self) -> None:
        events = [
            happened("title", turn=0, text="Named"),
            happened("user", turn=2, text="Second"),
            happened("user", turn=1, text="First"),
        ]

        assert [(turn.number, turn.user.text if turn.user else None) for turn in turns_of(events)] == [
            (1, "First"),
            (2, "Second"),
        ]


class TestSaving:
    def test_a_conversation_is_saved_beside_itself_or_where_told(self, fake_client: FakeClient, tmp_path: Path) -> None:
        chat = make_chat(tmp_path)
        chat.send("Hello")
        chat.close()
        directory = tmp_path / "chat"

        saved = save_chat_html(directory)
        elsewhere = save_chat_html(directory, tmp_path / "out" / "talk.html", team_sessions=False)

        assert saved == directory / "conversation.html"
        assert elsewhere == tmp_path / "out" / "talk.html"
        assert saved.read_text(encoding="utf-8") == chat_html(directory)
        assert elsewhere.read_text(encoding="utf-8") == chat_html(directory, team_sessions=False)

    def test_a_pdf_is_made_of_the_document(
        self, fake_client: FakeClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chat = make_chat(tmp_path)
        chat.send("Hello")
        chat.close()
        directory = tmp_path / "chat"
        made: list[str] = []

        def make_pdf(document: str) -> bytes:
            made.append(document)

            return b"%PDF-chat"

        monkeypatch.setattr(export, "make_pdf", make_pdf)

        saved = save_chat_pdf(directory)
        elsewhere = save_chat_pdf(directory, tmp_path / "out" / "talk.pdf")

        assert saved == directory / "conversation.pdf" and elsewhere == tmp_path / "out" / "talk.pdf"
        assert saved.read_bytes() == elsewhere.read_bytes() == b"%PDF-chat"
        assert made == [chat_html(directory)] * 2

    def test_a_pdf_without_weasyprint_says_how_to_install_it(
        self, fake_client: FakeClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chat = make_chat(tmp_path)
        chat.send("Hello")
        chat.close()
        monkeypatch.setitem(sys.modules, "weasyprint", None)

        with pytest.raises(export.PDFExportError, match=r"pip install 'virtual-lab\[pdf\]'"):
            save_chat_pdf(tmp_path / "chat")

        assert not (tmp_path / "chat" / "conversation.pdf").exists()

    @needs_weasyprint
    def test_a_conversation_is_saved_as_a_pdf_with_its_figures(
        self, fake_client: FakeClient, session: DrawingSession, tmp_path: Path
    ) -> None:
        from pypdf import PdfReader

        fake_client.completions.responses = [
            tool_call_response("run_code", {"code": "print(6 * 7)"}),
            text_response("The answer is 42, as the figure shows."),
        ]
        chat = make_chat(tmp_path, session=session)
        chat.send("What is 6 times 7?")
        chat.close()

        path = save_chat_pdf(tmp_path / "chat")

        reader = PdfReader(path)
        text = " ".join(page.extract_text() for page in reader.pages)
        assert "VIRTUAL LAB · CONVERSATION" in text
        assert "What is 6 times 7?" in text and "print(6 * 7)" in text
        assert "The answer is 42" in text
        assert len({image.data for page in reader.pages for image in page.images}) == 1


def test_a_conversation_made_of_attachments_alone_names_them(tmp_path: Path) -> None:
    events = [happened("user", text="", attachments=[{"name": "a.csv", "path": "uploads/a.csv"}])]

    text = text_of(chat_html(saved_chat(tmp_path / "chat", events)))

    assert "Attached a.csv" in text and "bytes" not in text


def test_what_the_researcher_wrote_and_attached_is_shown_as_text_and_never_as_a_page(tmp_path: Path) -> None:
    events = [
        happened(
            "user",
            text="<script>alert(1)</script> & <b>bold</b>",
            attachments=[{"name": "<img src=x onerror=alert(2)>.csv", "size": 3}],
        ),
        happened("answer", text="Done."),
    ]

    document = chat_html(saved_chat(tmp_path / "chat", events))

    body = document.split("</style>", 1)[1]
    assert "<script>" not in body and "<img" not in body and "<b>" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &lt;b&gt;bold&lt;/b&gt;" in body
    assert "&lt;img src=x onerror=alert(2)&gt;.csv (3 bytes)" in body


def test_a_step_that_says_nothing_is_not_shown_as_the_lead_having_begun(tmp_path: Path) -> None:
    events = [happened("user", text="Go"), happened("tool_calls", text="  \n", calls=[])]

    document = chat_html(saved_chat(tmp_path / "chat", events))

    assert "This turn had not ended when the conversation was saved." in document
    assert '<div class="turn" style=' not in document


@pytest.mark.parametrize(("made", "more"), [(29, None), (30, None), (31, "and 1 more")])
def test_the_files_a_piece_of_code_made_are_named_up_to_a_limit_and_the_rest_counted(made: int, more: str | None) -> None:
    files = [f"out/{number}.csv" for number in range(made)]

    text = text_of(cell_html(cell("run()", produced_files=files), Figures(None), 1000))

    assert "out/0.csv" in text and f"out/{min(made, 30) - 1}.csv" in text
    assert "out/30.csv" not in text
    assert ("and 1 more" in text) is (more is not None)
    assert text.count("more") == (1 if more else 0)


def test_code_whose_output_lost_nothing_does_not_say_that_any_was_left_out() -> None:
    kept = text_of(cell_html(cell(output="x\n", output_dropped=0), Figures(None), 1000))
    lost = text_of(cell_html(cell(output="x\n", output_dropped=2048), Figures(None), 1000))

    assert "left out" not in kept
    assert "The middle of the output, 2,048 bytes, is left out." in lost


def test_only_the_meetings_in_a_ledger_are_team_sessions(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    for name in ("fix", "lab_001"):
        (lab / name).mkdir(parents=True)
        (lab / name / "transcript.json").write_text("{}")
    ledger = {
        "steps": [
            {"kind": "repair", "name": "fix", "files": {"transcript": "fix/transcript.json"}},
            {"kind": "meeting", "name": "lab_001", "files": {"transcript": "lab_001/transcript.json"}},
            {"kind": "meeting", "name": "lab_002", "files": {"transcript": "lab_002/transcript.json"}},
            {"kind": "meeting", "name": "lab_003", "files": {}},
        ]
    }
    (lab / "project.json").write_text(json.dumps(ledger))

    assert team_sessions_of(tmp_path) == {"lab_001": lab / "lab_001" / "transcript.json"}


@pytest.mark.parametrize(
    "ledger",
    [None, "", "{not json", "[]", "null", '"steps"', "{}", '{"steps": null}', '{"steps": {"a": 1}}', '{"steps": "meeting"}', '{"steps": 3}'],
)
def test_a_ledger_that_cannot_be_read_is_taken_as_no_team_sessions(tmp_path: Path, ledger: str | None) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    if ledger is not None:
        (lab / "project.json").write_text(ledger)

    assert team_sessions_of(tmp_path) == {}


@pytest.mark.parametrize("kind", ["not text", "a directory"])
def test_a_ledger_that_cannot_be_read_as_text_is_taken_as_no_team_sessions(tmp_path: Path, kind: str) -> None:
    ledger = tmp_path / "lab" / "project.json"
    ledger.parent.mkdir()
    if kind == "not text":
        ledger.write_bytes(b"\xff\xfe{")
    else:
        ledger.mkdir()

    assert team_sessions_of(tmp_path) == {}


def test_a_step_that_is_not_made_as_it_should_be_is_passed_over_and_the_rest_are_kept(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    (lab / "ok").mkdir(parents=True)
    (lab / "ok" / "transcript.json").write_text("[]")
    steps = [
        "meeting",
        None,
        {"kind": "meeting"},
        {"kind": "meeting", "name": 7, "files": {"transcript": "ok/transcript.json"}},
        {"kind": "meeting", "name": "no_files"},
        {"kind": "meeting", "name": "files_list", "files": ["ok/transcript.json"]},
        {"kind": "meeting", "name": "path_is_not_text", "files": {"transcript": 3}},
        {"kind": "meeting", "name": "path_is_a_list", "files": {"transcript": ["ok/transcript.json"]}},
        {"kind": "meeting", "name": "ok", "files": {"transcript": "ok/transcript.json"}},
    ]
    (lab / "project.json").write_text(json.dumps({"steps": steps}))

    assert team_sessions_of(tmp_path) == {"ok": lab / "ok" / "transcript.json"}
