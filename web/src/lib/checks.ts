export function count(number: number, noun: string): string {
  return `${number} ${noun}${number === 1 ? "" : "s"}`;
}

// A phrase as it begins a sentence
export function sentence(text: string): string {
  return text === "" ? text : `${text[0].toUpperCase()}${text.slice(1)}`;
}

// How many characters there are, as the server counts them: a character of more than one UTF-16 unit is one
export function characters(text: string): number {
  return [...text].length;
}

export interface Checked<T, K extends string> {
  // What to send, or null while there is something wrong
  value: T | null;
  problems: Partial<Record<K, string>>;
}

// An amount of dollars as it was typed, with or without the sign. It is nothing if it is blank where it may be.
export function dollars(text: string, what: string, optional: boolean): { value: number | null; problem?: string } {
  const typed = text.trim().replace(/^\$/, "").trim();
  if (typed === "") return optional ? { value: null } : { value: null, problem: `Say ${what}.` };
  const value = /^(\d+(\.\d*)?|\.\d+)$/.test(typed) ? Number(typed) : Number.NaN;
  if (!Number.isFinite(value)) {
    return { value: null, problem: `${sentence(what)} is an amount in dollars, such as 1 or 0.50.` };
  }

  return { value };
}

// A whole number as it was typed, from the least to the most
export function whole(text: string, what: string, least: number, most: number): { value: number | null; problem?: string } {
  const typed = text.trim();
  const value = /^\d+$/.test(typed) ? Number(typed) : Number.NaN;
  if (!Number.isSafeInteger(value) || value < least || value > most) {
    return { value: null, problem: `${what} is a whole number from ${least} to ${most}.` };
  }

  return { value };
}
