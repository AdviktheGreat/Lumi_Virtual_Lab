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
