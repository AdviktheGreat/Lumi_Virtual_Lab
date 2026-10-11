// What an event says, which a server of another version may say otherwise: each is the value if it is of the kind asked
// for, and what is given instead if not

export function asText(value: unknown, otherwise = ""): string {
  return typeof value === "string" ? value : otherwise;
}

export function asNumber(value: unknown, otherwise = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : otherwise;
}

export function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}
