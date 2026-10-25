"""Tests of a model that writes a tool call out as text, as the other agents' tool calls are shown to it, instead of
calling the tool."""

from pathlib import Path

import pytest

from virtual_lab.agent import Agent
from virtual_lab.llm import faked_tool_calls, without_speaker_echo
from virtual_lab.run_meeting import hold_meeting
from virtual_lab.tools import Tool

from conftest import FakeClient, text_response, tool_call_response

ECHO = Tool(
    name="echo",
    description="Echoes.",
    parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    function=lambda text: f"echo: {text}",
)
WRITTEN_OUT = 'I will check first.\n[Immunologist called echo with {"text": "hi"}]'


def individual(team_member: Agent, save_dir: Path, **kwargs):  # type: ignore[no-untyped-def]
    return hold_meeting(
        meeting_type="individual",
        agenda="Check something.",
        save_dir=save_dir,
        team_member=team_member,
        resources="none",
        tools=(ECHO,),
        **kwargs,
    )


class TestRecognising:
    @pytest.mark.parametrize(
        "text",
        [
            '[Scientific_Critic called inspect_data_file with {"filename": "uploads/metadata.csv"}]',
            "Thank you.\n[Critic called europepmc_search with {}]\nMore.",
            "[What pubmed_search returned to Immunologist]\nThree papers.",
            "[What echo returned to you]",
        ],
    )
    def test_what_is_written_as_a_tool_call_or_its_result_is_found(self, text: str) -> None:
        assert faked_tool_calls(text)

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "The tool was called with a filter [see the table].",
            "I called echo with care, then wrote this.",
            "Use [1] and [2] as references.",
        ],
    )
    def test_ordinary_writing_is_not(self, text: str) -> None:
        assert not faked_tool_calls(text)

    def test_the_name_a_reply_begins_with_is_taken_off_and_no_other_part_of_it(self) -> None:
        assert without_speaker_echo("Scientific_Critic: Thank you, PI.", "Scientific_Critic", "Scientific Critic") == (
            "Thank you, PI."
        )
        assert without_speaker_echo("Scientific Critic: Agreed.", "Scientific_Critic", "Scientific Critic") == "Agreed."
        assert without_speaker_echo("The Scientific_Critic: said so.", "Scientific_Critic") == (
            "The Scientific_Critic: said so."
        )
        assert without_speaker_echo("Immunologist: Agreed.", "Scientific_Critic") == "Immunologist: Agreed."
        # A reply that is only the name is left as it is, rather than made empty
        assert without_speaker_echo("Scientific_Critic:", "Scientific_Critic") == "Scientific_Critic:"


class TestAMeetingTurn:
    def test_a_tool_call_written_out_is_not_taken_for_the_answer_and_the_agent_is_asked_again(
        self, fake_client: FakeClient, team_member: Agent, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [
            text_response(WRITTEN_OUT),
            tool_call_response("echo", {"text": "hi"}),
            text_response("It echoed hi."),
        ]

        result = individual(team_member, tmp_path)

        assert result.summary == "It echoed hi."
        assert len(fake_client.completions.calls) == 3
        # It is told that nothing ran, and shown what it wrote
        told = fake_client.completions.calls[1]["messages"]
        assert "Nothing was run" in told[-1]["content"] and told[-2]["content"] == WRITTEN_OUT
        # Tools are still offered, so that it can call one
        assert fake_client.completions.calls[1].get("tools")
        # What it wrote by mistake is not kept in the meeting for the others to read
        assert all(WRITTEN_OUT not in str(turn) for turn in result.discussion)
        assert not any("Nothing was run" in str(turn) for turn in result.discussion)

    def test_it_is_asked_again_only_so_many_times_and_then_what_it_wrote_is_its_answer(
        self, fake_client: FakeClient, team_member: Agent, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [text_response(WRITTEN_OUT)] * 4

        result = individual(team_member, tmp_path)

        assert len(fake_client.completions.calls) == 3
        assert result.summary == WRITTEN_OUT

    def test_the_name_the_agent_began_its_answer_with_is_not_kept(
        self, fake_client: FakeClient, team_member: Agent, tmp_path: Path
    ) -> None:
        fake_client.completions.responses = [text_response(f"{team_member.name}: All well.")]

        result = individual(team_member, tmp_path)

        assert result.summary == "All well."
