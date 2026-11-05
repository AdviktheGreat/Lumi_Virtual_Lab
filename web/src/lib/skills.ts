import type { LibrarySkill, LicenseKind, SkillInfo, SkillsCatalog, SkillsFrom, SkillsPutIn } from "./types";

// How many skills are listed before the rest are asked for, so that a library of hundreds does not fill the page
export const SKILLS_SHOWN = 40;

// The skills whose name or description has every word that was written, whatever its case
export function matching<T extends Pick<SkillInfo, "name" | "description">>(skills: T[], query: string): T[] {
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
  if (source === "builtin") return "The skills that come with the lab";

  return source;
}

// The names of the skills that new conversations are given
export function enabledNames(skills: SkillInfo[]): string[] {
  return skills.filter((skill) => skill.enabled).map((skill) => skill.name);
}

// The skills a conversation is to begin with as the choice stands: those that were chosen, or where none has been, those
// that are on, which are not any that are no longer there
export function choiceStart(skills: SkillInfo[], chosen: string[] | null): Set<string> {
  const there = new Set(skills.map((skill) => skill.name));

  return new Set((chosen ?? enabledNames(skills)).filter((name) => there.has(name)));
}

// What a choice is kept as: nothing where it is what new conversations are given anyway, so that a skill turned on later on
// the Skills page is still given to the conversation, and the names, in the order the skills are listed, where it is not
export function choiceKept(skills: SkillInfo[], picked: ReadonlySet<string>): string[] | null {
  const names = skills.filter((skill) => picked.has(skill.name)).map((skill) => skill.name);
  const on = enabledNames(skills);

  return names.length === on.length && names.every((name, index) => name === on[index]) ? null : names;
}

// The names that were chosen of skills that are not there any more, since one may be taken away before the conversation is begun
export function vanished(skills: SkillInfo[], chosen: string[]): string[] {
  const there = new Set(skills.map((skill) => skill.name));

  return chosen.filter((name) => !there.has(name));
}

// The choice once each of the names given is chosen or not, with the rest as they were
export function pickedWhen(picked: ReadonlySet<string>, names: string[], chosen: boolean): Set<string> {
  const next = new Set(picked);
  for (const name of names) {
    if (chosen) next.add(name);
    else next.delete(name);
  }

  return next;
}

// How many are chosen, as a person reads it
export function howManyChosen(chosen: number, total: number): string {
  if (total === 0) return "No skills";
  if (chosen === 0) return `No skill chosen, of ${total}`;
  if (chosen === total) return total === 1 ? "The 1 skill is chosen" : `All ${total} skills are chosen`;

  return `${chosen} of ${total} skills chosen`;
}

// What the button beside the composer says of the choice: nothing is said of what new conversations are given anyway
export function choiceButtonText(chosen: string[] | null): string {
  if (chosen === null) return "Skills";

  return chosen.length === 0 ? "Skills · none" : `Skills · ${chosen.length}`;
}

// The skills a conversation was given, each with what it is for as they are now, or null for one that is not there any more.
// Those are listed too, since the conversation goes on without them and the person may wonder where they went.
export function givenSkills(skills: SkillInfo[], names: string[]): { name: string; description: string | null }[] {
  const by = new Map(skills.map((skill) => [skill.name, skill.description]));

  return names.map((name) => ({ name, description: by.get(name) ?? null }));
}

// The skills of the library that are in the category chosen, if one was ("" is every category), and have every word that
// was written in their name, description, or category, whatever its case
export function matchingLibrary(skills: LibrarySkill[], query: string, category: string): LibrarySkill[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);

  return skills.filter((skill) => {
    if (category !== "" && skill.category !== category) return false;
    const text = `${skill.name} ${skill.description} ${skill.category}`.toLowerCase();

    return words.every((word) => text.includes(word));
  });
}

// What a person ought to know of a skill's license before it is put in, or null where there is nothing to say
export function licenseNote(kind: LicenseKind): string | null {
  if (kind === "noncommercial") return "Its license allows noncommercial use only.";
  if (kind === "copyleft") return "Its license is a GPL license, which sets conditions on sharing it and what is made from it.";
  if (kind === "none") return "It states no license of its own, so only the library's MIT license covers it.";

  return null;
}

const LICENSE_LABEL_CHARS = 28;

// A skill's license as a badge says it: as written, without the word license after it, and cut where it is long, since some
// are a sentence and some are the address of a license
export function licenseLabel(skill: Pick<LibrarySkill, "license" | "license_kind">): string {
  if (skill.license_kind === "none") return "No license stated";
  const written = (skill.license ?? "").trim();
  if (/^https?:\/\//i.test(written)) return "License at a link";
  const named = written.replace(/\s+license$/i, "");

  return named.length > LICENSE_LABEL_CHARS ? `${named.slice(0, LICENSE_LABEL_CHARS - 1).trimEnd()}…` : named;
}

function listed(names: string[]): string {
  if (names.length <= 3) return names.length <= 1 ? (names[0] ?? "") : `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;

  return `${names.slice(0, 3).join(", ")} and ${names.length - 3} more`;
}

// What to say of the licenses of skills that are about to be put in, a sentence for each kind that has something to say:
// those for noncommercial use, those under a GPL license, and those that state none
export function licenseWarnings(skills: Pick<LibrarySkill, "name" | "license_kind">[]): string[] {
  const named = (kind: LicenseKind) => skills.filter((skill) => skill.license_kind === kind).map((skill) => skill.name);
  const warnings: string[] = [];
  const noncommercial = named("noncommercial");
  const copyleft = named("copyleft");
  const none = named("none");
  if (noncommercial.length > 0) {
    warnings.push(`${listed(noncommercial)} ${noncommercial.length === 1 ? "allows" : "allow"} noncommercial use only.`);
  }
  if (copyleft.length > 0) {
    warnings.push(
      copyleft.length === 1
        ? `${copyleft[0]} is under a GPL license, which sets conditions on sharing it.`
        : `${listed(copyleft)} are under GPL licenses, which set conditions on sharing them.`,
    );
  }
  if (none.length > 0) {
    warnings.push(
      none.length === 1
        ? `${none[0]} states no license, so only the library's MIT license covers it.`
        : `${listed(none)} state no license, so only the library's MIT license covers them.`,
    );
  }

  return warnings;
}

// How big something is, as a person reads it
export function sizeSaid(bytes: number): string {
  if (bytes < 1000) return `${bytes} bytes`;
  if (bytes < 1_000_000) return `${Math.round(bytes / 1000)} KB`;

  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

// How many tokens a number of characters comes to, as a person reads it: about four characters to a token, and rounded
// where there are many, since it is only a guide
export function tokensSaid(chars: number): string {
  const tokens = Math.round(chars / 4);

  return `about ${(tokens >= 1000 ? Math.round(tokens / 100) * 100 : tokens).toLocaleString("en-US")} tokens`;
}

// What listing the skills that are on takes of every conversation, as a person reads it, and whether there is too little
// room for it, so that descriptions are cut
export function catalogSaid(catalog: SkillsCatalog): { text: string; tight: boolean } {
  if (catalog.skills === 0) return { text: "No skill is on, so no conversation begins with a list of skills.", tight: false };
  const takes = catalog.skills === 1 ? "The skill that is on takes" : `The ${catalog.skills.toLocaleString("en-US")} skills that are on take`;
  const text = `${takes} ${tokensSaid(catalog.chars)} of the start of every conversation.`;
  const tight = catalog.without_description > 0 || catalog.description_chars < 250;
  if (!tight) return { text, tight };
  const without =
    catalog.without_description > 0
      ? `, and ${catalog.without_description.toLocaleString("en-US")} ${catalog.without_description === 1 ? "skill is" : "skills are"} listed by name only`
      : "";

  return {
    text: `${text} The list has room for ${catalog.budget.toLocaleString("en-US")} characters, so descriptions are cut to ${catalog.description_chars} characters${without}. Turn some off to give the rest more room.`,
    tight,
  };
}

// How much of the lead's list the skills that are on fill, from 0 to 1
export function catalogFilled(catalog: SkillsCatalog): number {
  return catalog.budget === 0 ? 0 : Math.min(1, catalog.chars / catalog.budget);
}

// About how many characters putting in these skills adds to the list the lead is given, each with its name and the first of
// its description, which is as much as is listed of one where there is room
export function catalogAdded(skills: Pick<LibrarySkill, "name" | "description">[]): number {
  return skills.reduce((total, skill) => total + skill.name.length + 5 + Math.min(skill.description.length, 250), 0);
}
