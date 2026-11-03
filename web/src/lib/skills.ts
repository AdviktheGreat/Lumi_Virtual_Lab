import type { SkillInfo, SkillsFrom, SkillsPutIn } from "./types";

// How many skills are listed before the rest are asked for, so that a library of hundreds does not fill the page
export const SKILLS_SHOWN = 40;

// The skills whose name or description has every word that was written, whatever its case
export function matching(skills: SkillInfo[], query: string): SkillInfo[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return skills;

  return skills.filter((skill) => {
    const text = `${skill.name} ${skill.description}`.toLowerCase();

    return words.every((word) => text.includes(word));
  });
}

// The names of those that are off once each of the names given is turned on or off, with the rest as they were. The
// server is told which are off and not which are on, so that a skill that is put in later is on.
export function disabledWhen(skills: SkillInfo[], names: string[], enabled: boolean): string[] {
  const chosen = new Set(names);

  return skills.filter((skill) => (chosen.has(skill.name) ? !enabled : !skill.enabled)).map((skill) => skill.name);
}

// How many are turned on, as a person reads it
export function howManyOn(skills: SkillInfo[]): string {
  const on = skills.filter((skill) => skill.enabled).length;
  const many = `${skills.length} skill${skills.length === 1 ? "" : "s"}`;
  if (on === skills.length) return skills.length === 1 ? "1 skill, on" : `${many}, all on`;
  if (on === 0) return `${many}, none on`;

  return `${many}, ${on} on`;
}

export const NOTHING_TO_PUT_IN_FROM =
  "Give the address of a Git repository, which begins with https://, or the full path of a folder on this machine, which begins with / or ~.";

// What was written to put skills in from, as the server asks for it, or what is wrong with it
export function skillsFrom(text: string): { from: SkillsFrom } | { problem: string } {
  const written = text.trim();
  if (written === "") return { problem: NOTHING_TO_PUT_IN_FROM };
  if (/\s/.test(written)) return { problem: "An address or a path is written without spaces in it." };
  if (/^https:\/\//i.test(written)) return { from: { git: written } };
  if (/^[a-z][a-z0-9+.-]*:/i.test(written) && !/^[a-z]:[\\/]/i.test(written)) {
    return { problem: "Only an address that begins with https:// can be fetched from." };
  }
  if (/^[/~]/.test(written) || /^[a-z]:[\\/]/i.test(written)) return { from: { path: written } };

  return { problem: NOTHING_TO_PUT_IN_FROM };
}

// What putting in skills did, as a person reads it
export function putInSaid({ installed, skipped }: Pick<SkillsPutIn, "installed" | "skipped">): string {
  const put = `${installed.length} skill${installed.length === 1 ? "" : "s"}`;
  const left = `${skipped.length} left`;
  if (installed.length === 0) return skipped.length === 0 ? "Nothing was put in." : `Nothing new was put in: ${left}.`;

  return skipped.length === 0 ? `Put in ${put}.` : `Put in ${put}. ${left}.`;
}

// How many files of the skills put in were too many or too big to copy, which the skills may need
export function filesLeftOut({ installed }: Pick<SkillsPutIn, "installed">): { name: string; left_out: number }[] {
  return installed.filter((skill) => skill.left_out > 0);
}

// Where a skill was found, in words
export function whereFound(source: string): string {
  if (source === "workspace") return "The lab's skills";
  if (source === "user") return "Your skills, which other tools read too";

  return source;
}
