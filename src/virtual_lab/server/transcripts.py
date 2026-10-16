"""What was said in a meeting, read from the transcript the library saved, to be sent to a page."""

from pathlib import Path

from virtual_lab.server.workspace import read_json

# The most characters of a transcript a page is sent
MAX_TRANSCRIPT_CHARS = 200_000


def read_turns(directory: Path, relative: str) -> tuple[list[dict[str, str]] | None, bool]:
    """What was said in a meeting, from the transcript the library saved, and whether it was cut short to be sent.

    :param directory: The directory the transcript is kept in.
    :param relative: Where it is in that directory, as the library recorded it.
    """
    path = (directory / relative).resolve()
    # What a record names is read only if it is in the directory, which a file edited by hand may not be
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        return None, False
    saved = read_json(path)
    if not isinstance(saved, list):
        return None, False
    turns: list[dict[str, str]] = []
    used = 0
    for turn in saved:
        if (
            not isinstance(turn, dict)
            or not isinstance(turn.get("agent"), str)
            or not isinstance(turn.get("message"), str)
        ):
            continue
        room = MAX_TRANSCRIPT_CHARS - used
        if room <= 0:
            return turns, True
        turns.append({"agent": turn["agent"], "message": turn["message"][:room]})
        used += len(turn["message"])
        if len(turn["message"]) > room:
            return turns, True

    return turns, False
