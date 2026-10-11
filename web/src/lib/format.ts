const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

// When something happened, as a person says it: "just now", "5 min ago", "3 h ago", "yesterday", "4 days ago", then
// the date. Nothing is said for a time that is not one.
export function timeAgo(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const elapsed = now.getTime() - then.getTime();
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)} min ago`;
  if (elapsed < DAY) return `${Math.floor(elapsed / HOUR)} h ago`;
  if (elapsed < 2 * DAY) return "yesterday";
  if (elapsed < 7 * DAY) return `${Math.floor(elapsed / DAY)} days ago`;

  return then.toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    year: then.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}

// What something cost, in dollars, where it is known
export function formatCost(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return "";
  if (cost === 0) return "$0.00";
  if (cost < 0.01) return "<$0.01";

  return `$${cost.toFixed(2)}`;
}

// How long something took: milliseconds under a second, then seconds, then minutes. It is rounded once, to what is
// shown, so that no time is shown as a unit it is not (59.6 seconds is a minute, not "60 s").
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const milliseconds = Math.round(seconds * 1000);
  if (milliseconds < 1) return "<1 ms";
  if (milliseconds < 1000) return `${milliseconds} ms`;
  if (seconds < 9.95) return `${(milliseconds / 1000).toFixed(1)} s`;
  const whole = Math.round(seconds);
  if (whole < 60) return `${whole} s`;
  const minutes = Math.floor(whole / 60);
  const rest = whole % 60;

  return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
}

// Output that was written for a terminal has its colours as escape sequences, which a page shows as litter
const ESCAPE = String.fromCharCode(27);
const ANSI = new RegExp(`${ESCAPE}\\[[0-9;?]*[ -/]*[@-~]`, "g");

export function stripAnsi(text: string): string {
  return text.replace(ANSI, "");
}

// When a file was changed, from the seconds since the epoch that the server gives, as timeAgo says it
export function timeAgoFromEpoch(seconds: number, now: Date = new Date()): string {
  const then = new Date(seconds * 1000);

  return Number.isNaN(then.getTime()) ? "" : timeAgo(then.toISOString(), now);
}
