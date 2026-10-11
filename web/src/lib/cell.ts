import { asNumber, asStrings, asText } from "./read";

// Code that ran in the session, as the server tells of it
export interface Cell {
  language: string;
  code: string;
  // "ok", "error", "timeout", or "lost"; anything else the server may one day say is shown as it is
  status: string;
  output: string;
  error: string | null;
  duration: number;
  // Figures, and every file that appeared while it ran, relative to the conversation's files
  plots: string[];
  producedFiles: string[];
  // Bytes dropped from the middle of the output to bound it
  outputDropped: number;
  value: unknown;
}

// A run as the server gives it, which is the same where the lead ran the code and where a scientist in a team session did
export function cellOf(data: Record<string, unknown>): Cell {
  return {
    language: asText(data.language, "python"),
    code: asText(data.code),
    status: asText(data.status, "ok"),
    output: asText(data.output),
    error: typeof data.error === "string" && data.error !== "" ? data.error : null,
    duration: asNumber(data.duration),
    plots: asStrings(data.plots),
    producedFiles: asStrings(data.produced_files),
    outputDropped: asNumber(data.output_dropped),
    value: data.value ?? null,
  };
}
