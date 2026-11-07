import { describe, expect, it } from "vitest";
import {
  BRIEF_LIMIT,
  campaignAddress,
  changesTo,
  checkCampaign,
  countPrograms,
  draftOf,
  groupByCampaign,
  lastActive,
  newProgramIn,
  spentBetween,
} from "./campaigns";
import type { Campaign, ChatSummary } from "./types";

function campaign(id: string, extra: Partial<Campaign> = {}): Campaign {
  return {
    id,
    name: id,
    brief: "",
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:00+00:00",
    ...extra,
  };
}

function chat(id: string, member: string | null, extra: Partial<ChatSummary> = {}): ChatSummary {
  return {
    id,
    title: id,
    created_at: "2026-02-01T00:00:00+00:00",
    updated_at: "2026-02-01T00:00:00+00:00",
    state: "idle",
    kind: "quick_task",
    turns: 1,
    spent: null,
    max_cost: null,
    model: null,
    campaign: member,
    ...extra,
  };
}

describe("checkCampaign", () => {
  it("keeps the name as a title is and the goal trimmed", () => {
    expect(checkCampaign({ name: "  Nanobody   screen ", brief: "\n Find a binder. \n" })).toEqual({
      campaign: { name: "Nanobody screen", brief: "Find a binder." },
      problems: {},
    });
  });

  it("needs a name, and not a goal", () => {
    expect(checkCampaign({ name: "Just a group", brief: "  " }).campaign).toEqual({ name: "Just a group", brief: "" });
    expect(checkCampaign({ name: "  ", brief: "Goal." })).toEqual({ campaign: null, problems: { name: "A campaign needs a name." } });
  });

  it("refuses a goal that is longer than the server keeps, counted in characters, and takes one at the limit", () => {
    expect(checkCampaign({ name: "A", brief: "x".repeat(BRIEF_LIMIT) }).problems).toEqual({});
    expect(checkCampaign({ name: "A", brief: "x".repeat(BRIEF_LIMIT + 1) })).toEqual({
      campaign: null,
      problems: { brief: "The goal is at most 8,000 characters, and this is 8,001." },
    });
    expect(checkCampaign({ name: "A", brief: "😀".repeat(BRIEF_LIMIT) }).problems).toEqual({});
  });

  it("says everything that is wrong at once", () => {
    expect(Object.keys(checkCampaign({ name: "", brief: "x".repeat(BRIEF_LIMIT + 1) }).problems)).toEqual(["name", "brief"]);
  });
});

describe("draftOf and changesTo", () => {
  it("starts from nothing, or from what the campaign is", () => {
    expect(draftOf(null)).toEqual({ name: "", brief: "" });
    expect(draftOf(campaign("a", { name: "Screen", brief: "Goal." }))).toEqual({ name: "Screen", brief: "Goal." });
  });

  it("changes only what differs", () => {
    const kept = campaign("a", { name: "Screen", brief: "Goal." });

    expect(changesTo(kept, { name: "Screen", brief: "Goal." })).toEqual({});
    expect(changesTo(kept, { name: "Other", brief: "Goal." })).toEqual({ name: "Other" });
    expect(changesTo(kept, { name: "Screen", brief: "" })).toEqual({ brief: "" });
    expect(changesTo(kept, { name: "Other", brief: "New." })).toEqual({ name: "Other", brief: "New." });
  });
});

describe("groupByCampaign", () => {
  it("puts programs with the campaign they are one of, and the rest alone, each in the order they were given", () => {
    const { groups, alone } = groupByCampaign(
      [chat("p1", "a"), chat("p2", null), chat("p3", "b"), chat("p4", "a")],
      [campaign("a"), campaign("b")],
    );

    expect(groups.map((group) => [group.campaign.id, group.programs.map((program) => program.id)])).toEqual([
      ["a", ["p1", "p4"]],
      ["b", ["p3"]],
    ]);
    expect(alone.map((program) => program.id)).toEqual(["p2"]);
  });

  it("keeps a campaign with no programs", () => {
    const { groups, alone } = groupByCampaign([], [campaign("empty")]);

    expect(groups).toEqual([{ campaign: campaign("empty"), programs: [] }]);
    expect(alone).toEqual([]);
  });

  it("takes a program that names a campaign there is none of to be one of none", () => {
    const { groups, alone } = groupByCampaign([chat("p1", "gone")], [campaign("a")]);

    expect(groups[0].programs).toEqual([]);
    expect(alone.map((program) => program.id)).toEqual(["p1"]);
  });

  it("puts the campaign that was at work last first, and the names in order among those that were at work together", () => {
    const old = { updated_at: "2026-01-01T00:00:00+00:00" };
    const { groups } = groupByCampaign(
      [chat("p1", "quiet", { updated_at: "2026-02-01T00:00:00+00:00" }), chat("p2", "busy", { updated_at: "2026-03-01T00:00:00+00:00" })],
      [campaign("quiet", old), campaign("zeta", old), campaign("alpha", old), campaign("busy", old)],
    );

    expect(groups.map((group) => group.campaign.id)).toEqual(["busy", "quiet", "alpha", "zeta"]);
  });

  it("counts a campaign that was changed after its programs worked as at work then", () => {
    const group = { campaign: campaign("a", { updated_at: "2026-05-01T00:00:00+00:00" }), programs: [chat("p", "a")] };

    expect(lastActive(group)).toBe(new Date("2026-05-01T00:00:00+00:00").getTime());
  });

  it("is not thrown by a time that cannot be read", () => {
    const group = { campaign: campaign("a", { updated_at: "not a time" }), programs: [chat("p", "a", { updated_at: null, created_at: null })] };

    expect(lastActive(group)).toBe(0);
  });
});

describe("what a campaign is counted as", () => {
  it("adds what its programs have spent, and counts what is not said as nothing", () => {
    expect(spentBetween([])).toBe(0);
    expect(spentBetween([chat("a", null, { spent: 0.25 }), chat("b", null), chat("c", null, { spent: 1.5 })])).toBe(1.75);
  });

  it("counts programs", () => {
    expect(countPrograms(0)).toBe("0 programs");
    expect(countPrograms(1)).toBe("1 program");
    expect(countPrograms(2)).toBe("2 programs");
  });

  it("names the pages of a campaign by its id, as an address holds it", () => {
    expect(campaignAddress("a b&c")).toBe("/campaign?id=a%20b%26c");
    expect(newProgramIn(campaign("a b&c"))).toBe("/?campaign=a%20b%26c");
  });
});
