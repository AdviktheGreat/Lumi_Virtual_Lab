import type { Call, Resources } from "./transcript";

// What a call to a tool is shown as: a line saying what is being done, and what it was asked
export interface CallSummary {
  title: string;
  // Beside the title, what it was for
  detail: string | null;
  // The code a call to run code was given, which is shown before it has run
  code: { language: string; text: string } | null;
}

const DETAIL_CHARS = 160;

const LANGUAGES: Record<string, string> = { python: "Python", r: "R", bash: "shell" };

export function languageLabel(language: string): string {
  return LANGUAGES[language.toLowerCase()] ?? language;
}

// The arguments of a call, which are JSON where the model wrote them well, and nothing where it did not
export function parseArguments(text: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(text);

    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function oneLine(value: unknown, limit = DETAIL_CHARS): string | null {
  if (typeof value !== "string") return null;
  const text = value.split(/\s+/).filter(Boolean).join(" ");
  if (text === "") return null;

  return text.length > limit ? `${text.slice(0, limit - 1).trimEnd()}…` : text;
}

function titles(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim() !== "") : [];
}

// What each of the library's tools is shown as: what it does as it is called and once it has been, and which of what it
// was given says what it is about
interface Lookup {
  now: string;
  done: string;
  about: (args: Record<string, unknown>) => string | null;
}

const asked = (field: string) => (args: Record<string, unknown>) => oneLine(args[field], 120);

function lookup(now: string, done: string, about: Lookup["about"]): Lookup {
  return { now, done, about };
}

const LOOKUPS: Record<string, Lookup> = {
  pubmed_search: lookup("Searching PubMed", "Searched PubMed", asked("query")),
  europepmc_search: lookup("Searching Europe PMC", "Searched Europe PMC", asked("query")),
  europepmc_lookup: lookup("Looking up an article", "Looked up an article", asked("identifier")),
  europepmc_fulltext: lookup("Reading an article", "Read an article", asked("pmcid")),
  arxiv_search: lookup("Searching arXiv", "Searched arXiv", asked("query")),
  uniprot_search: lookup("Searching UniProt", "Searched UniProt", asked("query")),
  uniprot_lookup: lookup("Looking up a protein", "Looked up a protein", asked("accession")),
  pdb_lookup: lookup("Looking up a structure", "Looked up a structure", asked("pdb_id")),
  alphafold_lookup: lookup("Looking up a predicted structure", "Looked up a predicted structure", asked("accession")),
  fetch_structure_file: lookup("Downloading a structure", "Downloaded a structure", (args) => {
    const identifier = oneLine(args.identifier, 60);
    const source = oneLine(args.source, 20);

    return identifier === null ? null : source === null ? identifier : `${identifier} from ${source}`;
  }),
  pubchem_lookup: lookup("Looking up a molecule", "Looked up a molecule", asked("identifier")),
  chembl_search: lookup("Searching ChEMBL", "Searched ChEMBL", asked("query")),
  chembl_lookup: lookup("Looking up a compound", "Looked up a compound", asked("chembl_id")),
  chembl_target_search: lookup("Searching ChEMBL for a target", "Searched ChEMBL for a target", asked("query")),
  chembl_activities: lookup("Getting measured activities", "Got measured activities", (args) => {
    const subject = oneLine(args.target_chembl_id, 60) ?? oneLine(args.molecule_chembl_id, 60);
    const type = oneLine(args.activity_type, 30);

    return [subject, type].filter(Boolean).join(" · ") || null;
  }),
  data_files: lookup("Listing the attached files", "Listed the attached files", () => null),
  inspect_data_file: lookup("Inspecting a data file", "Inspected a data file", (args) => {
    const file = oneLine(args.filename, 100);
    const sheet = oneLine(args.sheet, 40);

    return file === null ? null : sheet === null ? file : `${file} · ${sheet}`;
  }),
};

export function summarize(call: Pick<Call, "name" | "arguments" | "status">): CallSummary {
  const args = parseArguments(call.arguments) ?? {};
  const now = call.status === "running";

  switch (call.name) {
    case "run_code": {
      const language = typeof args.language === "string" && args.language !== "" ? args.language : "python";
      const text = typeof args.code === "string" ? args.code : null;
      const label = languageLabel(language);

      return {
        title: `${now ? "Running" : "Ran"} ${label} code`,
        detail: null,
        code: text === null ? null : { language, text },
      };
    }
    case "find_resources":
      return { title: now ? "Looking up resources" : "Looked up resources", detail: oneLine(args.task), code: null };
    case "convene_team": {
      const members = titles(args.members);

      return {
        title: now ? "Convening the team" : "Convened the team",
        detail: [members.join(", "), oneLine(args.agenda, 120)].filter(Boolean).join(" · ") || null,
        code: null,
      };
    }
    case "consult": {
      const member = oneLine(args.member, 60);

      return {
        title: `${now ? "Consulting" : "Consulted"} ${member ?? "a scientist"}`,
        detail: oneLine(args.agenda),
        code: null,
      };
    }
    default: {
      const known = LOOKUPS[call.name];
      if (known !== undefined) {
        return { title: now ? known.now : known.done, detail: known.about(args), code: null };
      }
      const given = oneLine(call.arguments, 100);

      return {
        title: `${now ? "Calling" : "Called"} ${call.name || "a tool"}`,
        detail: given === "{}" ? null : given,
        code: null,
      };
    }
  }
}

// The kinds of resource, as the server names them, and what each is called
const KINDS = [
  { key: "tools", one: "tool", many: "tools", label: "Tools" },
  { key: "data_lake", one: "data file", many: "data files", label: "Data files" },
  { key: "libraries", one: "software package", many: "software packages", label: "Software" },
  { key: "know_how", one: "know-how document", many: "know-how documents", label: "Know-how" },
] as const;

function counted(counts: (key: string) => number): string | null {
  const parts = KINDS.flatMap((kind) => {
    const count = counts(kind.key);

    return count > 0 ? [`${count} ${count === 1 ? kind.one : kind.many}`] : [];
  });

  return parts.length > 0 ? parts.join(", ") : null;
}

export interface ResourcesSummary {
  title: string;
  detail: string | null;
  // The names the lead was told of, by kind, for those that are named
  groups: { label: string; names: string[] }[];
}

// What the lead was told it has to work with, or what it asked for
export function describeResources(resources: Resources): ResourcesSummary {
  const groups = KINDS.flatMap((kind) => {
    const names = resources.selected[kind.key] ?? [];

    return names.length > 0 ? [{ label: kind.label, names }] : [];
  });
  const selected = counted((key) => resources.selected[key]?.length ?? 0);

  if (resources.task !== null) {
    return {
      title: "Chose resources for a task",
      detail: [oneLine(resources.task, 120), selected].filter(Boolean).join(" · ") || null,
      groups,
    };
  }
  if (resources.mode === "none") {
    return { title: "No resources", detail: null, groups };
  }
  if (resources.mode === "retrieve" && selected === null) {
    const available = counted((key) => resources.available[key] ?? 0);

    return { title: "Resources it can look up", detail: available, groups };
  }

  return { title: "Resources it can use", detail: selected ?? counted((key) => resources.available[key] ?? 0), groups };
}
