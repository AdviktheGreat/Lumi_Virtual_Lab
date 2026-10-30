import { initialsOf, speakerTone } from "@/lib/lab";
import { cn } from "@/lib/utils";

// A tone for each of the scientists the lab names, which a name keeps; the critic is always the one that is red
const TONES = [
  "bg-tone-bio/15 text-tone-bio",
  "bg-tone-ml/15 text-tone-ml",
  "bg-tone-violet/15 text-tone-violet",
  "bg-tone-lead/15 text-tone-lead",
  "bg-tone-teal/15 text-tone-teal",
];
const CRITIC = "bg-tone-critic/15 text-tone-critic";
const LEAD = "bg-tone-lead/20 text-tone-lead";

function toneOf(name: string, lead: boolean): string {
  if (lead) return LEAD;

  return /critic/i.test(name) ? CRITIC : TONES[speakerTone(name) % TONES.length];
}

// The initials of a scientist in a circle of their tone. The name is beside it where it is read, so it is not said twice.
export function Avatar({ name, lead = false, className }: { name: string; lead?: boolean; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("flex size-6 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold", toneOf(name, lead), className)}
    >
      {initialsOf(name)}
    </span>
  );
}
