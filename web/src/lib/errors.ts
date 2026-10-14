import { ApiError, NetworkError } from "./api";

// What to tell a person of an error from the server. The server's own messages say what is wrong in words they can
// act on, so they are kept; what it cannot say is told here.
export function describeError(error: unknown): string {
  if (error instanceof ApiError || error instanceof NetworkError) return error.message;
  if (error instanceof Error) return error.message;

  return "Something went wrong.";
}

// What a page tells of an error, and where the person can put it right, if there is such a place
export interface Problem {
  text: string;
  fix: "keys" | "setup" | null;
}

export function plainProblem(text: string): Problem {
  return { text, fix: null };
}

// What the server's error codes are put right by: a model whose provider's key is not set, by giving the key, and code in
// Docker that has no Docker or no image to run in, by setting them up
const FIXES = new Map<string, NonNullable<Problem["fix"]>>([
  ["missing_keys", "keys"],
  ["setup_needed", "setup"],
]);

export function problemOf(error: unknown): Problem {
  return { text: describeError(error), fix: (error instanceof ApiError && FIXES.get(error.code)) || null };
}
