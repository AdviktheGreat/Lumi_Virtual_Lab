import { ApiError, NetworkError } from "./api";

// What to tell a person of an error from the server. The server's own messages say what is wrong in words they can
// act on, so they are kept; what it cannot say is told here.
export function describeError(error: unknown): string {
  if (error instanceof ApiError || error instanceof NetworkError) return error.message;
  if (error instanceof Error) return error.message;

  return "Something went wrong.";
}
