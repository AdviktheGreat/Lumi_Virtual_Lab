// How many conversations there must be before the list can be searched, which is more than are seen at a glance
export const SEARCH_FROM = 8;

// The most a title may be, which is what the server keeps, in characters
export const TITLE_LIMIT = 80;

// What a conversation is called in the list, where it has no title yet
export const UNTITLED = "New chat";

// Text cut to the most a title may be, in characters, which are more than the units that a box counts for its length
// where there are any that are written with two
export function capTitle(typed: string): string {
  return [...typed].slice(0, TITLE_LIMIT).join("");
}

// A title as the server will keep it: its words, one space apart, cut to the most there may be, which is nothing for a
// title with nothing in it
export function cleanTitle(typed: string): string | null {
  const title = capTitle(typed.split(/\s+/).filter(Boolean).join(" ")).trimEnd();

  return title === "" ? null : title;
}

// The conversations whose titles have all the words that were typed, in any order and whatever their case
export function matchingTitles<T extends { title: string }>(chats: T[], typed: string): T[] {
  const words = typed.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return chats;

  return chats.filter((chat) => {
    const title = (chat.title || UNTITLED).toLowerCase();

    return words.every((word) => title.includes(word));
  });
}

export type DayName = "Today" | "Yesterday" | "Previous 7 days" | "Earlier";

export interface Day<T> {
  name: DayName;
  chats: T[];
}

function dayStart(date: Date, daysBefore = 0): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() - daysBefore).getTime();
}

const DAY_NAMES: DayName[] = ["Today", "Yesterday", "Previous 7 days", "Earlier"];

// Conversations by how long ago they were last at work, by the days of the reader's own calendar, with today first and
// each day's conversations in the order they were given, which is the latest first. A day with none is left out. One
// with no date that can be read is earlier than the rest, and one that is dated after now, which is a clock that is out,
// is today's.
export function inDays<T extends { updated_at: string | null; created_at: string | null }>(chats: T[], now: Date = new Date()): Day<T>[] {
  const today = dayStart(now);
  const yesterday = dayStart(now, 1);
  const week = dayStart(now, 7);
  const days = new Map<DayName, T[]>(DAY_NAMES.map((name) => [name, []]));

  for (const chat of chats) {
    const when = new Date(chat.updated_at ?? chat.created_at ?? Number.NaN).getTime();
    let name: DayName;
    if (Number.isNaN(when)) name = "Earlier";
    else if (when >= today) name = "Today";
    else if (when >= yesterday) name = "Yesterday";
    else if (when >= week) name = "Previous 7 days";
    else name = "Earlier";
    days.get(name)?.push(chat);
  }

  return DAY_NAMES.map((name) => ({ name, chats: days.get(name) ?? [] })).filter((day) => day.chats.length > 0);
}
