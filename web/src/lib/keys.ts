import type { KeyStatuses } from "./types";

export interface KeyRow {
  // The environment variable the key is kept in
  name: string;
  // Whose key it is
  provider: string;
  set: boolean;
}

// The keys that can be given, each with whose it is and whether it is set. A provider that needs more than the key,
// as Azure does, is not whose it is while there is one that needs the key alone.
export function keyRows(statuses: KeyStatuses): KeyRow[] {
  return statuses.settable.map((name) => {
    const whose =
      statuses.providers.find((status) => status.variables.length === 1 && status.variables[0] === name) ??
      statuses.providers.find((status) => status.variables.includes(name));

    return { name, provider: whose?.provider ?? name, set: whose !== undefined && !whose.missing.includes(name) };
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
