import { characters, sentence, type Checked } from "./checks";
import { timeAgo } from "./format";
import { tidy } from "./scientists";
import type { CardFact, CardFields, CardKind, MethodCard, ScopeAspect } from "./types";

// The sorts of fact on the card, in the order a person reads them
export const CARD_KINDS: readonly CardKind[] = ["methods", "datasets", "scope", "limitations"];

// What a statement of scope may be about, as the server takes it
export const ASPECTS: readonly ScopeAspect[] = ["species", "tissue", "assay", "sample size", "input", "other"];

// How long a name, an accession, or a value may be, and the words of a fact, as the server counts them
export const MAX_DETAIL_CHARS = 300;
export const MAX_QUOTE_CHARS = 1000;

// How many facts of a sort are shown before the rest are asked for
export const CARD_FACTS_SHOWN = 10;

export interface CardKindText {
  // What the facts are called, which names their list
  label: string;
  // What adding one is called
  add: string;
  // What is said where there is none
  none: string;
}

export const CARD_TEXT: Record<CardKind, CardKindText> = {
  methods: { label: "Methods", add: "Add a method", none: "No method is on the card." },
  datasets: { label: "Data used", add: "Add a dataset", none: "No dataset is on the card." },
  scope: { label: "What the method was tested on", add: "Add what it was tested on", none: "Nothing it was tested on is on the card." },
  limitations: { label: "Where the authors say it falls short", add: "Add a limit", none: "No limit is on the card." },
};

// A fact of the card as it is shown: what it says in a few words, and its fields as a person may change them
export interface CardLine {
  fact: CardFact;
  title: string | null;
  tag: string | null;
  fields: CardFields;
  // Whether a person changed it, so that it can be changed back to what was read
  changed: boolean;
  // What a fact that a person changed was read as, in words, or null if it was not changed
  readAs: string | null;
}

// What fields of a kind of fact say, in a few words
function describeFields(kind: CardKind, fields: CardFields): string | null {
  const said = (name: string) => fields[name] ?? "";
  switch (kind) {
    case "methods":
      return said("name") || null;
    case "datasets":
      return [said("name"), said("accession")].filter(Boolean).join(", ") || null;
    case "scope":
      return said("value") ? `${said("aspect")}: ${said("value")}` : null;
    default:
      return null;
  }
}

// Whether a fact is one that a person changed, which says what it was read as
function wasChanged(fact: CardFact): fact is CardFact & { read_as: Record<string, string> } {
  return fact.by === "person" && typeof fact.read_as === "object" && fact.read_as !== null;
}

function lineOf(kind: CardKind, fact: CardFact, title: string | null, tag: string | null, fields: CardFields): CardLine {
  const changed = wasChanged(fact);

  return { fact, title, tag, fields, changed, readAs: changed ? describeFields(kind, fact.read_as) : null };
}

// The facts of each sort, as they are shown. Those that were taken off are of the same shape, so the same is made of them.
export function cardLines(facts: MethodCard["removed"]): Record<CardKind, CardLine[]> {
  return {
    methods: facts.methods.map((fact) => lineOf("methods", fact, fact.name, null, { name: fact.name })),
    datasets: facts.datasets.map((fact) =>
      lineOf("datasets", fact, fact.name, fact.accession || null, { name: fact.name, accession: fact.accession }),
    ),
    scope: facts.scope.map((fact) => lineOf("scope", fact, fact.value, sentence(fact.aspect), { aspect: fact.aspect, value: fact.value })),
    limitations: facts.limitations.map((fact) => lineOf("limitations", fact, null, null, {})),
  };
}

// How many facts the card has
export function cardSize(card: MethodCard): number {
  return CARD_KINDS.reduce((sum, kind) => sum + card[kind].length, 0);
}

// Whose a fact is, in words: what the model read, or what a person changed or added
export function describeWhose(fact: CardFact): string {
  if (fact.by === "reading") return "Read by the model";

  return wasChanged(fact) ? "Changed by you" : "Added by you";
}

// Whether a fact is one that a person added, which has their words and no place in the paper
export function isAdded(fact: CardFact): boolean {
  return fact.by === "person" && fact.anchor === null;
}

// Whether the words of a fact may be changed, which they are only if they are a person's own. A limit that was read is the
// authors' sentence, and is not changed at all.
export function canChange(kind: CardKind, fact: CardFact): boolean {
  return kind !== "limitations" || isAdded(fact);
}

export interface CardStatusText {
  label: "Approved" | "Draft";
  text: string;
}

// What the card is, as it is: a draft that nobody has approved, an approval of the card as it is, or a draft that was approved
// and has changed. An approval is said to be a person's reading and letting it stand, and never that the card is right.
export function describeStatus(card: MethodCard, now: Date = new Date()): CardStatusText {
  if (card.status === "approved") {
    const when = timeAgo(card.approved_at, now);

    return {
      label: "Approved",
      text: `You approved this card${when ? ` ${when}` : ""}. That says you read it as it is and let it stand, which is not that it is right.`,
    };
  }
  if (card.changed_since_approval) {
    return {
      label: "Draft",
      text: "You approved this card, and it has changed since, so it is a draft again. Read it, and approve it again if you let it stand.",
    };
  }

  return {
    label: "Draft",
    text: "A model made this from the paper, and all that was checked of a fact is that its words are in the paper, not that the model read them right. Read it, put right what is wrong, and approve it.",
  };
}

// What a person did to the card, in a few words, or null if they did nothing
export function describeEdits(card: MethodCard): string | null {
  const own = CARD_KINDS.flatMap((kind): CardFact[] => card[kind]).filter((fact) => fact.by === "person");
  const changed = own.filter(wasChanged).length;
  const added = own.length - changed;
  const off = CARD_KINDS.reduce((sum, kind) => sum + card.removed[kind].length, 0);
  const parts = [
    ...(changed > 0 ? [`${changed} changed`] : []),
    ...(added > 0 ? [`${added} added`] : []),
    ...(off > 0 ? [`${off} taken off`] : []),
  ];

  return parts.length > 0 ? `What you did to it: ${parts.join(", ")}.` : null;
}

// Why the card is not approved now, in a sentence, or null if it may be
export function approvalBlock(card: MethodCard, reading: boolean): string | null {
  if (reading) return "The paper is being read, so the card is not finished.";
  if (cardSize(card) === 0) return "There is nothing on the card to approve.";

  return null;
}

// What a person typed of a fact: each of the fields it may have, and the words
export interface CardDraft {
  aspect: string;
  name: string;
  accession: string;
  value: string;
  quote: string;
}

export const EMPTY_CARD_DRAFT: CardDraft = { aspect: "species", name: "", accession: "", value: "", quote: "" };

// What a person typed of a fact that is on the card, to change it
export function draftOf(line: CardLine): CardDraft {
  return {
    ...EMPTY_CARD_DRAFT,
    aspect: line.fields.aspect ?? EMPTY_CARD_DRAFT.aspect,
    name: line.fields.name ?? "",
    accession: line.fields.accession ?? "",
    value: line.fields.value ?? "",
    quote: line.fact.quote,
  };
}

export type CardKey = keyof CardDraft;

// What a person may say of a fact of a kind, which of its parts are filled in, and what each is called
export const CARD_PARTS: Record<CardKind, readonly CardKey[]> = {
  methods: ["name"],
  datasets: ["name", "accession"],
  scope: ["aspect", "value"],
  limitations: [],
};

// What a kind of fact must have filled in, and what is said when it is not
const REQUIRED: Record<CardKind, Partial<Record<CardKey, string>>> = {
  methods: { name: "Say what the method is called." },
  datasets: { name: "Say what the dataset is called." },
  scope: { value: "Say what it was tested on." },
  limitations: { quote: "Say the limit in words." },
};

// What is sent of a fact that a person typed, or what is wrong with it. The words are only sent of a fact that is the
// person's own, since the words of one that was read are the paper's, and for a limit they are the fact.
export function checkCardFact(kind: CardKind, draft: CardDraft, ownWords: boolean): Checked<CardFields, CardKey> {
  const problems: Partial<Record<CardKey, string>> = {};
  const fields: CardFields = {};
  for (const part of CARD_PARTS[kind]) {
    const text = tidy(draft[part]);
    fields[part] = text;
    if (characters(text) > MAX_DETAIL_CHARS) problems[part] = `That is at most ${MAX_DETAIL_CHARS} characters.`;
  }
  const words = tidy(draft.quote);
  if (ownWords) {
    fields.quote = words;
    if (characters(words) > MAX_QUOTE_CHARS) problems.quote = `That is at most ${MAX_QUOTE_CHARS.toLocaleString("en-US")} characters.`;
  }
  for (const [part, problem] of Object.entries(REQUIRED[kind]) as [CardKey, string][]) {
    const given = part === "quote" ? words : fields[part];
    if (!given && problems[part] === undefined) problems[part] = problem;
  }
  if (kind === "scope" && !ASPECTS.includes(fields.aspect as ScopeAspect)) problems.aspect = `Say what it is about: ${ASPECTS.join(", ")}.`;

  return Object.keys(problems).length > 0 ? { value: null, problems } : { value: fields, problems: {} };
}

// How many of the facts of a sort a person took off, said as it is on the button that puts them back
export function describeTakenOff(facts: readonly CardFact[]): string {
  return `Taken off (${facts.length})`;
}
