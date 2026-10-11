// Where an address in an answer may take the reader: out to the web or to an email, either of which opens apart from
// this page, or to a place in this page. Nothing else is a link, so that an address that would run a script, or open
// something on this machine, is left as its text however it is written.
export type LinkKind = "web" | "place" | "none";

export function linkKind(address: string): LinkKind {
  if (/^(https?:|mailto:)/i.test(address)) return "web";
  if (address.startsWith("#")) return "place";

  return "none";
}
