"""The campaigns the researcher made: each a name and the goal that its programs work toward.

A program is one of at most one campaign, which is kept with the program (see ChatConfig.campaign), so that a program is
as it was set up wherever it is moved. What a campaign is kept as is in the workspace's campaigns.json. The lead of each
of its programs is told its goal, in every request it makes, so that what the programs make fits together.
"""

import secrets
from typing import Any

from virtual_lab.constants import MAX_CAMPAIGN_BRIEF_CHARS, MAX_CAMPAIGN_NAME_CHARS, MAX_CAMPAIGNS
from virtual_lab.provenance import utc_timestamp
from virtual_lab.server.errors import ApiError, not_found
from virtual_lab.server.workspace import CAMPAIGN_ID_PATTERN, Workspace, has_control_character, slug

# What follows a campaign's name in its id, so that an id is not one that a campaign that was deleted had
ID_SUFFIX_BYTES = 3


def check_campaign_name(name: Any) -> str:
    """A campaign's name on one line of words.

    :raises ApiError: If there is nothing in it, too much, or a character that is not text.
    """
    if not isinstance(name, str):
        raise ApiError(422, "invalid", "A campaign's name is text")
    named = " ".join(name.split())
    if not named:
        raise ApiError(422, "invalid", "A campaign needs a name with something in it")
    if len(named) > MAX_CAMPAIGN_NAME_CHARS:
        raise ApiError(422, "invalid", f"A campaign's name can be at most {MAX_CAMPAIGN_NAME_CHARS} characters")
    if has_control_character(named):
        raise ApiError(422, "invalid", "A campaign's name is text, with no control characters in it")

    return named


def check_campaign_brief(brief: Any) -> str:
    """A campaign's goal, trimmed, which may be empty, and then tells the lead nothing.

    :raises ApiError: If it is not text or there is too much of it.
    """
    if brief is None:
        return ""
    if not isinstance(brief, str):
        raise ApiError(422, "invalid", "A campaign's goal is text")
    written = brief.strip()
    if len(written) > MAX_CAMPAIGN_BRIEF_CHARS:
        raise ApiError(
            422,
            "invalid",
            f"A campaign's goal is at most {MAX_CAMPAIGN_BRIEF_CHARS:,} characters, and this is {len(written):,}",
        )

    return written


def taken(campaigns: list[dict[str, str]], name: str, except_id: str | None = None) -> bool:
    """Whether another campaign has this name, which is so whatever the case it is written in."""
    return any(item["name"].casefold() == name.casefold() and item["id"] != except_id for item in campaigns)


class Campaigns:
    """The campaigns in a workspace.

    :param workspace: Where they are kept. Changes are made under its lock, so that any number of these may be made
        for one workspace.
    """

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def load(self) -> list[dict[str, str]]:
        """The campaigns, in the order they were made."""
        return self.workspace.load_campaigns()

    def find(self, campaign_id: str) -> dict[str, str] | None:
        """A campaign, or None if there is none with this id."""
        if not CAMPAIGN_ID_PATTERN.fullmatch(campaign_id):
            return None

        return next((item for item in self.load() if item["id"] == campaign_id), None)

    def get(self, campaign_id: str) -> dict[str, str]:
        """A campaign.

        :raises ApiError: If there is none with this id.
        """
        found = self.find(campaign_id)
        if found is None:
            raise not_found("campaign with that id")

        return found

    def create(self, name: Any, brief: Any = "") -> dict[str, str]:
        """Makes a campaign.

        :param name: What to call it, which no other campaign is called, whatever the case.
        :param brief: The goal its programs work toward, which may be left empty.
        :raises ApiError: If the name or the goal cannot be used, another campaign has the name, or there are as many
            campaigns as there may be.
        """
        named = check_campaign_name(name)
        written = check_campaign_brief(brief)

        def add(campaigns: list[dict[str, str]]) -> dict[str, str]:
            if len(campaigns) >= MAX_CAMPAIGNS:
                raise ApiError(409, "too_many", f"There can be at most {MAX_CAMPAIGNS} campaigns. Delete one first.")
            if taken(campaigns, named):
                raise ApiError(409, "exists", f"There is a campaign called {named} already")
            ids = {item["id"] for item in campaigns}
            while True:
                # The suffix is random so that a campaign made after one of the same name was deleted has another id,
                # which a program that was left pointing at the deleted one is not taken for a member of
                campaign_id = f"{slug(named)}-{secrets.token_hex(ID_SUFFIX_BYTES)}"
                if campaign_id not in ids:
                    break
            now = utc_timestamp()
            made = {"id": campaign_id, "name": named, "brief": written, "created_at": now, "updated_at": now}
            campaigns.append(made)

            return made

        return self.workspace.update_campaigns(add)

    def update(self, campaign_id: str, changes: dict[str, Any]) -> dict[str, str]:
        """Changes a campaign's name or its goal, as `changes` says by "name" and "brief". What it does not say is
        left as it was.

        :raises ApiError: If there is no such campaign, there is nothing to change, a value cannot be used, or another
            campaign has the name.
        """
        if not changes.keys() & {"name", "brief"}:
            raise ApiError(422, "invalid", "Say what to change: name or brief")
        if not CAMPAIGN_ID_PATTERN.fullmatch(campaign_id):
            raise not_found("campaign with that id")
        named = check_campaign_name(changes["name"]) if "name" in changes else None
        written = check_campaign_brief(changes["brief"]) if "brief" in changes else None

        def change(campaigns: list[dict[str, str]]) -> dict[str, str]:
            entry = next((item for item in campaigns if item["id"] == campaign_id), None)
            if entry is None:
                raise not_found("campaign with that id")
            if named is not None and taken(campaigns, named, campaign_id):
                raise ApiError(409, "exists", f"There is a campaign called {named} already")
            if (named is None or named == entry["name"]) and (written is None or written == entry["brief"]):
                return dict(entry)
            if named is not None:
                entry["name"] = named
            if written is not None:
                entry["brief"] = written
            entry["updated_at"] = utc_timestamp()

            return dict(entry)

        return self.workspace.update_campaigns(change)

    def remove(self, campaign_id: str) -> None:
        """Forgets a campaign. Its programs are not deleted: they are left, and are not part of any campaign, which is
        for Conversations.leave_campaign to do for those it keeps.

        :raises ApiError: If there is no such campaign.
        """
        if not CAMPAIGN_ID_PATTERN.fullmatch(campaign_id):
            raise not_found("campaign with that id")

        def forget(campaigns: list[dict[str, str]]) -> None:
            at = next((index for index, item in enumerate(campaigns) if item["id"] == campaign_id), None)
            if at is None:
                raise not_found("campaign with that id")
            del campaigns[at]

        self.workspace.update_campaigns(forget)
