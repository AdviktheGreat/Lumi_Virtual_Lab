import type { KeySource, Keychain, KeyStatuses } from "./types";

export interface KeyRow {
  // The environment variable the key is kept in
  name: string;
  // Whose key it is
  provider: string;
  set: boolean;
  // Where the key is kept, if it is set and that is known
  source: KeySource | null;
}

// The keys that can be given, each with whose it is and whether it is set. A provider that needs more than the key,
// as Azure does, is not whose it is while there is one that needs the key alone.
export function keyRows(statuses: KeyStatuses): KeyRow[] {
  return statuses.settable.map((name) => {
    const whose =
      statuses.providers.find((status) => status.variables.length === 1 && status.variables[0] === name) ??
      statuses.providers.find((status) => status.variables.includes(name));

    return {
      name,
      provider: whose?.provider ?? name,
      set: whose !== undefined && !whose.missing.includes(name),
      source: statuses.sources[name] ?? null,
    };
  });
}

// What is wrong with a key as it was typed, which the server would refuse: a key is on one line, with nothing else
// in it. Null if there is nothing wrong.
export function keyProblem(typed: string): string | null {
  const key = typed.trim();
  if (key === "") return "Paste the key first.";
  if (/[\u0000-\u001f\u007f]/.test(key)) return "A key is on one line, with nothing else in it.";

  return null;
}

// What was chosen of keeping the keys given in the page in the server's keychain. It is for this browser, and is that they
// are kept unless it was said they are not.
const KEEP_KEYS = "virtual-lab.keep-keys";

export function keepKeys(): boolean {
  try {
    return localStorage.getItem(KEEP_KEYS) !== "no";
  } catch {
    return true;
  }
}

export function chooseKeepKeys(keep: boolean): void {
  try {
    if (keep) localStorage.removeItem(KEEP_KEYS);
    else localStorage.setItem(KEEP_KEYS, "no");
  } catch {
    // The choice is for this visit alone, which is as long as the page is open
  }
}

// What to tell of a key that was given: where it is kept, and what went wrong if it was not kept where it was meant to be
export function describeSaved(statuses: KeyStatuses, name: string): { done: string; warning: string | null } {
  const source = statuses.sources[name];
  const done =
    source === "keychain" ? `Saved in the ${statuses.keychain.name ?? "keychain"}.` : "Saved until the server stops.";

  return { done, warning: statuses.problem };
}

// What to tell of a key that was taken away
export function describeRemoved(statuses: KeyStatuses): { done: string; warning: string | null } {
  return { done: "Removed.", warning: statuses.problem };
}

// Where a key that is set is kept, for beside its state; null where that is not known
export function describeSource(source: KeySource | undefined, keychain: Keychain): string | null {
  if (source === "keychain") return `In the ${keychain.name ?? "keychain"}`;
  if (source === "session") return "Until the server stops";
  if (source === "environment") return "From the server's environment";

  return null;
}
