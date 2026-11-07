import { cleanTitle } from "./history";
import { lengthOf } from "./programs";
import type { Campaign, CampaignChange, ChatSummary, NewCampaign } from "./types";

// The most that the goal of a campaign may be, which is what the server keeps, in characters
export const BRIEF_LIMIT = 8000;

// What is typed of a campaign, and what is wrong with it, which is shown once it has been tried to keep it
export interface CampaignDraft {
  name: string;
  brief: string;
}

export interface CampaignProblems {
  name?: string;
  brief?: string;
}

export interface CheckedCampaign {
  // What the server is asked to keep, or null while something is wrong
  campaign: NewCampaign | null;
  problems: CampaignProblems;
}

export function draftOf(campaign: Campaign | null): CampaignDraft {
  return { name: campaign?.name ?? "", brief: campaign?.brief ?? "" };
}

// A campaign from what was typed: its name is kept as a title is, and its goal trimmed, which may be empty, and then
// tells the lead nothing
export function checkCampaign(draft: CampaignDraft): CheckedCampaign {
  const problems: CampaignProblems = {};
  const name = cleanTitle(draft.name);
  if (name === null) problems.name = "A campaign needs a name.";
  const brief = draft.brief.trim();
  const length = lengthOf(brief);
  if (length > BRIEF_LIMIT) {
    problems.brief = `The goal is at most ${BRIEF_LIMIT.toLocaleString("en-US")} characters, and this is ${length.toLocaleString("en-US")}.`;
  }
  if (name === null || Object.keys(problems).length > 0) return { campaign: null, problems };

  return { campaign: { name, brief }, problems };
}

// What of a campaign is to be changed to be what was typed, which is nothing where it is the same
export function changesTo(campaign: Campaign, kept: NewCampaign): CampaignChange {
  return {
    ...(kept.name === campaign.name ? {} : { name: kept.name }),
    ...(kept.brief === campaign.brief ? {} : { brief: kept.brief }),
  };
}

export interface CampaignGroup {
  campaign: Campaign;
  // Its programs, in the order they were given, which is the latest first
  programs: ChatSummary[];
}

function when(iso: string | null | undefined): number {
  const time = new Date(iso ?? Number.NaN).getTime();

  return Number.isNaN(time) ? 0 : time;
}

// When a campaign was last at work: when it was changed, or when the last of its programs was
export function lastActive(group: CampaignGroup): number {
  return Math.max(when(group.campaign.updated_at), ...group.programs.map((program) => when(program.updated_at ?? program.created_at)));
}

// The programs by the campaign they are one of, with the campaigns that were at work last first, and a campaign with no
// programs as well, and the programs that are one of none, which are in the order they were given. A program that names a
// campaign there is none of is one of none.
export function groupByCampaign(chats: ChatSummary[], campaigns: Campaign[]): { groups: CampaignGroup[]; alone: ChatSummary[] } {
  const members = new Map<string, ChatSummary[]>(campaigns.map((campaign) => [campaign.id, []]));
  const alone: ChatSummary[] = [];
  for (const chat of chats) {
    const group = chat.campaign === null ? undefined : members.get(chat.campaign);
    if (group === undefined) alone.push(chat);
    else group.push(chat);
  }
  const groups = campaigns
    .map((campaign) => ({ campaign, programs: members.get(campaign.id) ?? [] }))
    .sort((a, b) => lastActive(b) - lastActive(a) || a.campaign.name.localeCompare(b.campaign.name));

  return { groups, alone };
}

// What the programs have spent between them, which is nothing for those that have not said
export function spentBetween(programs: ChatSummary[]): number {
  return programs.reduce((sum, program) => sum + (program.spent ?? 0), 0);
}

// What a campaign's programs are counted as, in words
export function countPrograms(count: number): string {
  return count === 1 ? "1 program" : `${count} programs`;
}

// The address of the page that begins a program in a campaign
export function newProgramIn(campaign: Campaign): string {
  return `/?campaign=${encodeURIComponent(campaign.id)}`;
}

// The address of a campaign's own page
export function campaignAddress(id: string): string {
  return `/campaign?id=${encodeURIComponent(id)}`;
}
