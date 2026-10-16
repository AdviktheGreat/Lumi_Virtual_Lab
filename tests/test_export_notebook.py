"""Tests for saving a conversation with the head of a lab as a Jupyter notebook."""

import base64
import json
from pathlib import Path
from typing import Any

import pytest

from virtual_lab.export_notebook import chat_notebook, fenced, notebook_text, save_chat_notebook
from virtual_lab.session import CODE_TOOL_NAME

from test_export import PNG
from test_export_chat import call_events, cell, happened, saved_chat


def source_of(item: dict[str, Any]) -> str:
    return "".join(item["source"])


def kinds_of(notebook: dict[str, Any]) -> list[str]:
    return [item["cell_type"] for item in notebook["cells"]]


def ran(output: str = "1\n", **made: Any) -> list[Any]:
    """The events of a turn in which the lead ran code, which the researcher asked for and the lead answered."""
    return [
        happened("user", text="Plot it"),
        call_events(CODE_TOOL_NAME, {"code": "print(1)"}),
        happened("cell", call="call_1", **cell(output=output, **made)),
        happened("tool_output", call="call_1", name=CODE_TOOL_NAME, text="Ran in 0.5 seconds."),
        happened("answer", text="Done."),
    ]


class TestNotebook:
    def test_a_conversation_is_a_notebook_of_what_was_said_and_what_ran(self, tmp_path: Path) -> None:
        chat_dir = saved_chat(tmp_path / "chat", ran())

        notebook = chat_notebook(chat_dir)

        assert (notebook["nbformat"], notebook["nbformat_minor"]) == (4, 5)
        assert notebook["metadata"]["kernelspec"]["name"] == "python3"
        assert kinds_of(notebook) == ["markdown", "markdown", "code", "markdown"]
        title, turn, code, answer = notebook["cells"]
        assert source_of(title).startswith("# A saved conversation\n")
        assert "1 turn" in source_of(title) and "Led by **Lead**" in source_of(title)
        assert source_of(turn) == "## Turn 1\n\n> **Researcher**\n>\n> Plot it"
        assert source_of(code) == "print(1)"
        assert code["execution_count"] == 1
        assert code["outputs"] == [{"output_type": "stream", "name": "stdout", "text": ["1\n"]}]
        assert source_of(answer) == "Done."
        assert len({item["id"] for item in notebook["cells"]}) == len(notebook["cells"])

    def test_it_is_text_that_reads_back_as_the_same_notebook(self, tmp_path: Path) -> None:
        chat_dir = saved_chat(tmp_path / "chat", ran(output="café ✓\n"))

        notebook = chat_notebook(chat_dir)
        text = notebook_text(notebook)

        assert "café ✓" in text
        assert json.loads(text) == notebook
        assert save_chat_notebook(chat_dir) == chat_dir / "conversation.ipynb"
        assert json.loads((chat_dir / "conversation.ipynb").read_text(encoding="utf-8")) == notebook

    def test_a_conversation_with_nothing_said_has_nothing_to_show(self, tmp_path: Path) -> None:
        notebook = chat_notebook(saved_chat(tmp_path / "chat", []))

        assert kinds_of(notebook) == ["markdown", "markdown"]
        assert "Nothing has been said" in source_of(notebook["cells"][1])

    def test_figures_are_embedded_and_the_files_made_are_named(self, tmp_path: Path) -> None:
        work = tmp_path / "work"
        work.mkdir()
        (work / "plot.png").write_bytes(PNG)
        (work / "table.csv").write_text("a\n1\n")
        chat_dir = saved_chat(
            tmp_path / "chat",
            ran(plots=["plot.png", "gone.png", "../outside.png"], produced_files=["plot.png", "table.csv"]),
            session={"directory": str(work)},
        )

        notebook = chat_notebook(chat_dir)

        outputs = notebook["cells"][2]["outputs"]
        figure = next(output for output in outputs if output["output_type"] == "display_data")
        assert figure["data"]["image/png"] == base64.b64encode(PNG).decode()
        said = [output["text"] for output in outputs if output["output_type"] == "stream"]
        assert said[-2:] == [["gone.png could not be found.\n"], ["../outside.png could not be found.\n"]]
        assert source_of(notebook["cells"][3]) == "*Files it made: `table.csv`*"

    def test_where_the_session_is_not_known_a_figure_is_said_to_be_missing(self, tmp_path: Path) -> None:
        notebook = chat_notebook(saved_chat(tmp_path / "chat", ran(plots=["plot.png"])))

        assert notebook["cells"][2]["outputs"][-1]["text"] == ["plot.png could not be found.\n"]

    def test_code_that_failed_is_an_error_unless_its_traceback_was_printed(self, tmp_path: Path) -> None:
        chat_dir = saved_chat(
            tmp_path / "chat",
            [
                call_events(CODE_TOOL_NAME, {"code": "1/0"}, call="a"),
                happened(
                    "cell",
                    call="a",
                    **cell("1/0", status="error", output="", error="ZeroDivisionError: division by zero"),
                ),
                call_events(CODE_TOOL_NAME, {"code": "stop()"}, call="b"),
                happened(
                    "cell",
                    call="b",
                    **cell("stop()", status="timeout", output="", error="Stopped at its time limit"),
                ),
                call_events(CODE_TOOL_NAME, {"code": "boom()"}, call="c"),
                happened(
                    "cell",
                    call="c",
                    **cell("boom()", status="error", output="Traceback\nValueError: no\n", error="ValueError: no"),
                ),
            ],
        )

        code = [item for item in chat_notebook(chat_dir)["cells"] if item["cell_type"] == "code"]
        first, second, third = [item["outputs"] for item in code]

        assert first == [
            {
                "output_type": "error",
                "ename": "ZeroDivisionError",
                "evalue": "division by zero",
                "traceback": ["ZeroDivisionError: division by zero"],
            }
        ]
        assert (second[0]["ename"], second[0]["evalue"]) == ("Error", "Stopped at its time limit")
        assert [output["output_type"] for output in third] == ["stream"]

    def test_what_a_cell_printed_and_came_to_is_kept_to_a_size(self, tmp_path: Path) -> None:
        chat_dir = saved_chat(
            tmp_path / "chat",
            ran(output="\x1b[31m" + "x" * 500 + "\x1b[0m\n", value={"n": [1, 2]}, output_dropped=42),
        )

        outputs = chat_notebook(chat_dir, max_output_chars=100)["cells"][2]["outputs"]

        printed = "".join(outputs[0]["text"])
        assert printed.startswith("[The middle of the output, 42 bytes, is left out.]\n")
        assert "\x1b" not in printed and "characters left out" in printed
        assert outputs[1]["output_type"] == "execute_result"
        assert json.loads("".join(outputs[1]["data"]["text/plain"])) == {"n": [1, 2]}

    def test_r_and_shell_code_starts_with_the_magic_that_runs_it(self, tmp_path: Path) -> None:
        chat_dir = saved_chat(
            tmp_path / "chat",
            [
                call_events(CODE_TOOL_NAME, {"code": "x"}, call="a"),
                happened("cell", call="a", **cell("print(1)", language="r")),
                call_events(CODE_TOOL_NAME, {"code": "x"}, call="b"),
                happened("cell", call="b", **cell("ls", language="bash")),
            ],
        )

        notebook = chat_notebook(chat_dir)

        code = [item for item in notebook["cells"] if item["cell_type"] == "code"]
        assert [source_of(item) for item in code] == ["%%R\nprint(1)", "%%bash\nls"]
        assert [item["execution_count"] for item in code] == [1, 2]
        assert "rpy2" in source_of(notebook["cells"][0])

    def test_what_the_lead_called_other_than_code_is_told_in_markdown(self, tmp_path: Path) -> None:
        chat_dir = saved_chat(
            tmp_path / "chat",
            [
                happened("user", text="Ask the team"),
                call_events(
                    "consult", {"member": "Immunologist", "agenda": "Is it safe?"}, call="a", said="Let me ask."
                ),
                happened("tool_output", call="a", name="consult", text="It is *safe*."),
                call_events("mystery", {"x": 1}, call="b"),
                happened("tool_output", call="b", name="mystery", text="a ``` fence"),
                happened("resources", mode="none"),
                happened("note", text="Hurry", speaker="Ada", to="lead"),
                happened("failed", text="The model was not reachable."),
            ],
        )

        cells = [source_of(item) for item in chat_notebook(chat_dir)["cells"][2:]]

        assert cells[0] == "Let me ask."
        assert "**Consulted Immunologist**" in cells[1] and "> It is *safe*." in cells[1]
        assert cells[2].startswith("**Called mystery**") and '"x": 1' in cells[2]
        assert "````\na ``` fence\n````" in cells[2]
        assert cells[3] == "*No resources*"
        assert cells[4] == "> **Ada** · A note to Lead\n>\n> Hurry"
        assert cells[5] == "*The model was not reachable.*"

    def test_code_that_did_not_run_is_shown_as_it_was_given(self, tmp_path: Path) -> None:
        chat_dir = saved_chat(
            tmp_path / "chat",
            [call_events(CODE_TOOL_NAME, {"code": "print(2)", "language": "r"}), happened("answer", text="No.")],
        )

        notebook = chat_notebook(chat_dir)

        assert kinds_of(notebook) == ["markdown", "markdown", "markdown", "markdown"]
        assert "```r\nprint(2)\n```" in source_of(notebook["cells"][2])

    def test_a_turn_that_had_not_ended_says_so(self, tmp_path: Path) -> None:
        notebook = chat_notebook(saved_chat(tmp_path / "chat", [happened("user", text="Hi")]))

        assert source_of(notebook["cells"][-1]) == "*This turn had not ended when the conversation was saved.*"

    def test_what_is_not_a_conversation_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            chat_notebook(tmp_path / "nowhere")


def test_a_fence_is_longer_than_any_run_of_backticks_in_what_it_holds() -> None:
    assert fenced("a") == "```\na\n```"
    assert fenced("```\nb\n```", "md") == "````md\n```\nb\n```\n````"
