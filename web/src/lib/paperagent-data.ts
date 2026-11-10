import { count, whole, type Checked } from "./checks";
import { formatBytes } from "./files";
import type {
  DataCandidate,
  DataFileListed,
  DataLicense,
  KeptDataFile,
  OwnDataSummary,
  PaperAgentData,
  PaperAgentDataFetch,
} from "./types";

export const MEGABYTE = 1024 * 1024;

// The longest that an address, a DOI, or an accession is that the server takes
export const MAX_REFERENCE_CHARS = 500;

export interface DataFetchDraft {
  // The most to fetch, in megabytes, as it was typed
  megabytes: string;
}

export function emptyDataFetch(limits: PaperAgentData["limits"]): DataFetchDraft {
  return { megabytes: String(limits.default_megabytes) };
}

// Whether a file can be chosen to fetch: the place gives it to anyone, says how big it is, and it is not kept already
export function fetchable(file: DataFileListed, kept: ReadonlySet<string>): boolean {
  return file.downloadable && file.bytes !== null && !kept.has(file.name);
}

// What the files come to, of those that say how big they are
export function totalBytes(files: readonly DataFileListed[]): number {
  return files.reduce((sum, file) => sum + (file.bytes ?? 0), 0);
}

// Why a file is not one to choose, in a few words, or null if it is
export function whyNot(file: DataFileListed, kept: ReadonlySet<string>): string | null {
  if (kept.has(file.name)) return "Kept already";
  if (!file.downloadable) return file.why ?? "The place does not give it";
  if (file.bytes === null) return "The place does not say how big it is";

  return null;
}

// How many of the files that were chosen are checked by a checksum that the place gave, and how many by their size only
export function checkedBy(files: readonly DataFileListed[]): { checksum: number; size: number } {
  const checksum = files.filter((file) => file.checksum !== null).length;

  return { checksum, size: files.length - checksum };
}

type FetchKey = "files" | "megabytes";

// What fetching is asked for: the place, the files that were chosen, what they came to when they were shown, which is what
// is agreed to, and the most to fetch. What the files come to is held to the most, so that it is not the server's refusal that
// says so.
export function checkDataFetch(
  reference: string,
  chosen: readonly DataFileListed[],
  draft: DataFetchDraft,
  limits: PaperAgentData["limits"],
): Checked<PaperAgentDataFetch, FetchKey> {
  const problems: Partial<Record<FetchKey, string>> = {};
  if (chosen.length === 0) problems.files = "Choose at least one file.";
  else if (chosen.length > limits.max_files) problems.files = `At most ${count(limits.max_files, "file")} can be fetched at once.`;
  const megabytes = whole(draft.megabytes, "The most to fetch, in megabytes,", limits.min_megabytes, limits.max_megabytes);
  if (megabytes.problem) problems.megabytes = megabytes.problem;
  const total = totalBytes(chosen);
  if (megabytes.value !== null && total > megabytes.value * MEGABYTE) {
    problems.megabytes = `These files come to ${formatBytes(total)}, which is more than the ${formatBytes(megabytes.value * MEGABYTE)} that may be fetched. Choose fewer, or raise the most.`;
  }
  if (Object.keys(problems).length > 0 || megabytes.value === null) return { value: null, problems };

  return {
    value: { reference, files: chosen.map((file) => file.name), expected_bytes: total, max_megabytes: megabytes.value },
    problems: {},
  };
}

// Why what was typed is not a place to look at, or null if it may be one, which the server says for certain
export function referenceProblem(text: string): string | null {
  const typed = text.trim();
  if (typed === "") return "Say where the data is: an address, a DOI, or an accession such as GSE12345.";
  if ([...typed].length > MAX_REFERENCE_CHARS) return `That is more than ${MAX_REFERENCE_CHARS} characters.`;

  return null;
}

// The names of the files that are kept of a place
export function keptNames(data: PaperAgentData, key: string): Set<string> {
  return new Set(data.kept.sources.filter((source) => source.key === key).flatMap((source) => source.files.map((file) => file.name)));
}

const ALGORITHMS: Record<string, string> = { md5: "MD5", sha256: "SHA-256" };

// What a place gives to check a file by, before it is fetched
export function describeChecksum(file: Pick<DataFileListed, "checksum">): string {
  if (file.checksum === null) return "No checksum is given, so it is checked by its size only";

  return `${ALGORITHMS[file.checksum.algorithm] ?? file.checksum.algorithm} checksum given, which it is checked by`;
}

// How far a file that was fetched was checked
export function describeKeptCheck(file: Pick<KeptDataFile, "checksum">): string {
  if (file.checksum === null) return "Checked by its size only, since the place gave no checksum";

  return `Matched the ${ALGORITHMS[file.checksum.algorithm] ?? file.checksum.algorithm} that the place gave`;
}

// The start of a checksum, which is enough to tell one from another
export function shortDigest(hex: string): string {
  return hex.slice(0, 12);
}

export function describeDataLicense(license: DataLicense | null): string {
  return license?.name ? `Licensed as ${license.name}` : "The place does not say how it is licensed";
}

export function describeKept(kept: Pick<PaperAgentData["kept"], "files" | "bytes">): string {
  return kept.files === 0 ? "No files are kept" : `${count(kept.files, "file")}, ${formatBytes(kept.bytes)}`;
}

// A person's own data, as it is told apart on the Data page, and by its kind and size
export function describeOwn(own: OwnDataSummary): string {
  return `${own.name} (${own.kind}, ${formatBytes(own.bytes)})`;
}

// The stand-ins for datasets that the paper does not name, or that it named when the stand-in was set and no longer does
export function otherStandIns(data: PaperAgentData): PaperAgentData["stand_ins"] {
  const named = new Set(data.datasets.map((dataset) => dataset.key));

  return data.stand_ins.filter((standIn) => !named.has(standIn.key));
}

// Whether the data a stand-in names is still on the Data page
export function standInPresent(standIn: { own_data?: OwnDataSummary | null }): boolean {
  return standIn.own_data != null;
}

// What a place that the paper names is, as it is first shown: whether it can be fetched from, and what has been
export function describeCandidate(candidate: DataCandidate): string {
  if (!candidate.supported) return "Not fetched from here";
  if (candidate.fetched > 0) return `${count(candidate.fetched, "file")} kept`;

  return "Nothing fetched yet";
}

// Where the places that the paper names are said: in the paper, in its code, or both
export function describeSaid(candidate: DataCandidate): string | null {
  const paper = candidate.facts.length;
  if (paper > 0 && candidate.in_code) return "Named in the paper and in its code";
  if (paper > 0) return "Named in the paper";
  if (candidate.in_code) return "Named in the code";

  return null;
}
