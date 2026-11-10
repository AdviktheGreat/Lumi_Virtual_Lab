// What the server's API says, as virtual_lab.server answers it. Its events are in virtual_lab.events.

export type ChatState = "idle" | "running" | "pausing" | "paused" | "stopping";

// What the list of conversations says: one that was running when the server stopped was cut off
export type ListedChatState = ChatState | "interrupted";

export interface Usage {
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  max_input_tokens: number;
  num_calls: number;
  unreported_calls: number;
  // Null where a model used has no known price
  cost: number | null;
  per_model: Record<string, Record<string, number>>;
}

export interface Scientist {
  title: string;
  expertise: string;
  goal: string;
  role: string;
}

export interface CodeSetup {
  where: string;
  sandbox: string;
  network: boolean;
  python: string;
  resources: string;
  data_lake: string;
  forward_env: string[];
}

// What a program is begun as: a quick task is a conversation with the lead, a custom program is a named one with
// instructions of its own, and one that builds a skill is a conversation in which the lead writes a skill with code and
// saves it when the person agrees
export type ProgramKind = "quick_task" | "custom" | "build_skill";

export interface ChatConfig {
  kind: ProgramKind;
  // What a custom program was told to do in all that it does, which a program of any other kind has none of
  instructions: string;
  model: string;
  lead: Scientist;
  team: Scientist[];
  code: CodeSetup;
  max_cost: number | null;
  // How many team sessions the lead may start in answering a message, and how many rounds it may ask one for, or null
  // for what the lead is given unless it is told otherwise
  max_delegations: number | null;
  max_rounds: number | null;
  // How many tool calls and runs of code the lead may make in answering a message, which only a request can set
  max_tool_iterations?: number | null;
  stream: boolean;
  commercial_mode: boolean;
  // The names of the library's tools the lead may call
  tools: string[];
  // The names of the MCP servers whose tools the lead may be given, which it connects to with its first message
  mcp: string[];
  // The names of the data and software the person gave the lab that the conversation is given, where there is code
  data: string[];
  software: string[];
  // The names of the skills the lead may read, as they were when the conversation began
  skills: string[];
  // The id of the campaign the program is one of, or "" for one that is not part of any
  campaign: string;
}

// A conversation as the list of them shows it
export interface ChatSummary {
  id: string;
  title: string;
  // ISO 8601, in UTC
  created_at: string | null;
  updated_at: string | null;
  state: ListedChatState;
  kind: ProgramKind;
  turns: number;
  spent: number | null;
  max_cost: number | null;
  model: string | null;
  // The id of the campaign it is one of, or null for one that is not part of any
  campaign: string | null;
}

// A campaign: programs that work toward one goal, which the lead of each is told in every message
export interface Campaign {
  id: string;
  name: string;
  // The goal and background that the lead is given, which may be empty
  brief: string;
  // ISO 8601, in UTC
  created_at: string;
  updated_at: string;
}

// What a new campaign is made of, and what of one may be changed
export interface NewCampaign {
  name: string;
  brief: string;
}

export type CampaignChange = Partial<NewCampaign>;

// A conversation as it is opened
export interface ChatInfo {
  id: string;
  title: string;
  created_at: string;
  state: ChatState;
  turns: number;
  lab_calls: number;
  spent: number | null;
  max_cost: number | null;
  // What the lead may ask of the team, as it stands
  max_delegations: number;
  max_rounds: number;
  usage: Usage;
  last_event_id: number;
  lead: string;
  team: string[];
  can_run_code: boolean;
  // Why each command that is given with a message cannot be given to it, in words, or null if it can
  directives: Record<string, string | null>;
  config: ChatConfig;
}

// Who is to work on a message given with /lab, and how: by title, any scientist of the library. A team is several
// scientists discussing it with the lead leading, and an individual is one working on it with the Scientific Critic
// reviewing, for the rounds that are said.
export interface LabChoice {
  mode: "team" | "individual";
  members: string[];
  rounds: number;
  questions: string[];
}

// What a new conversation is set up with: anything left out is what the settings say
export interface NewChat {
  title?: string;
  kind?: ProgramKind;
  instructions?: string;
  model?: string;
  lead?: string | Scientist;
  team?: (string | Scientist)[];
  code?: Partial<CodeSetup>;
  max_cost?: number | null;
  max_delegations?: number | null;
  max_rounds?: number | null;
  stream?: boolean;
  commercial_mode?: boolean;
  tools?: string[];
  mcp?: string[];
  data?: string[];
  software?: string[];
  // The names of the skills the lead may read, in place of those that are on for new conversations
  skills?: string[];
  // The id of the campaign the program is to be one of
  campaign?: string | null;
}

// What a conversation may be changed to while it goes on: any of these, where null is no spending limit, or what the
// lead is given of the team's time unless it is told otherwise
export interface LimitsChange {
  max_cost?: number | null;
  max_delegations?: number | null;
  max_rounds?: number | null;
}

// What the lead is given of the team's time unless it is told otherwise, and the most it can be given
export interface ChatLimits {
  max_delegations: { default: number; ceiling: number };
  max_rounds: { default: number; ceiling: number };
}

export interface Settings {
  model: string;
  stream: boolean;
  max_cost: number | null;
  code: string;
  sandbox: string;
  network: boolean;
  python: string;
  data_lake: string;
  forward_keys: string[];
  workspace: string;
  // The largest file that can be attached to a message
  max_upload_bytes: number;
  chat_limits: ChatLimits;
}

// What a request to change the settings may hold: any of them, each as it is to be
export type SettingsChange = Partial<Omit<Settings, "workspace" | "max_upload_bytes" | "chat_limits">>;

export interface ModelChoice {
  id: string;
  // Null for a model whose provider the server does not know
  provider: string | null;
  // Whether the keys its provider needs are set
  ready: boolean;
}

export interface Models {
  default: string;
  models: ModelChoice[];
}

// A model OpenRouter serves, which one key of OpenRouter's reaches. Its id is as it is named here, openrouter/<author>/<model>.
export interface OpenRouterModel {
  id: string;
  name: string;
  // How many tokens it reads and writes in all, where that is said
  context_length: number | null;
  // What it costs per million tokens in US dollars, or null where that depends on what it is asked, as it does for a router
  input_per_million: number | null;
  output_per_million: number | null;
}

// OpenRouter's models, with what went wrong in reading them if that is why they are not as new as they should be
export interface OpenRouterList {
  models: OpenRouterModel[];
  problem: string | null;
}

// Whether a provider's models can be reached, which is by whether the variables it needs are set. No key is ever sent.
export interface ProviderStatus {
  provider: string;
  variables: string[];
  missing: string[];
  ready: boolean;
}

// How a key that is set came to be: from the keychain, given in the page for the session alone, or in the environment the
// server was started with
export type KeySource = "keychain" | "session" | "environment";

export interface Keychain {
  // Whether the server has a keychain to keep keys in, and what it is called, as "macOS Keychain"
  available: boolean;
  name: string | null;
  // Why there is none, or why the keys kept in it were not read
  problem: string | null;
}

export interface KeyStatuses {
  // The keys that can be given
  settable: string[];
  providers: ProviderStatus[];
  keychain: Keychain;
  // Where each key that is set came from
  sources: Record<string, KeySource>;
  // What went wrong with the keychain in a change that was made all the same, which only a change says
  problem: string | null;
}

// A scientist of the library: the lab's own, or one that the person described
export interface LibraryScientist extends Scientist {
  builtin: boolean;
}

// One of the library's tools that the lead can be given, as the settings list them
export interface ToolInfo {
  name: string;
  // What the tools it is listed with are for
  group: string;
  // What it does, in a sentence
  summary: string;
  // Whether it is only given where code can run
  needs_code: boolean;
  // Whether a new conversation is given it
  enabled: boolean;
}

// A key an MCP server asks for, which is the name of the environment variable it is kept in
export interface McpKey {
  name: string;
  // Whether this page may give it, which it may for the keys of the services of the presets and no other
  settable: boolean;
}

export type McpAuth = "key" | "oauth";

// One of the MCP servers a conversation can be given the tools of, as the settings list it: a preset of the library's,
// or one the person described
export interface McpServer {
  name: string;
  // What to call it
  title: string;
  // What it is for, which only a preset says
  about: string | null;
  preset: boolean;
  // Whether it is set up, which a preset need not be to be listed
  added: boolean;
  enabled: boolean;
  // How it is signed in to or given a key, and how a preset may be: null where it takes neither
  auth: McpAuth | null;
  auth_choices: McpAuth[];
  transport: "stdio" | "http" | "sse" | null;
  // Where it is reached: its address, or the program that is started
  target: string | null;
  // Whether some of its tools wait for the researcher's approval of each call
  asks: boolean;
  // Whether a sign-in to it is kept, which a conversation then uses and refreshes without asking anyone: null where it is
  // not signed in to, or where its address is not known
  signed_in: boolean | null;
  // The keys it asks for that are not set, and those of them this page may give
  missing: McpKey[];
  keys_set: string[];
  // Why it cannot work as it is, if it cannot
  problem: string | null;
  // What to do before it can be connected to, which only a preset says
  setup: string | null;
}

// One of the servers of the catalog, which others run and which are added with a click
export interface McpCatalogServer {
  // What its tools' names start with, and what it is kept under once it is added
  name: string;
  title: string;
  about: string;
  // What it is for, which is how the catalog is grouped
  group: string;
  // Who runs it
  maker: string;
  // Where to read more of it
  site: string;
  // Its address, which what the lead asks of it is sent to
  target: string;
  // Whether it is signed in to, in the browser, as a program that has it on is first sent a message
  signs_in: boolean;
  // Whether its calls wait for the researcher's approval
  asks: boolean;
  // Whether it is set up
  added: boolean;
}

// What an MCP server of one's own is set up with, as a config gives it
export type McpEntry = Record<string, unknown>;

// A change to a server that is set up, or is a preset: any of these, and the rest is left as it was
// What connecting to a server to look at it came to: the names of the tools the lead would be given, or why not
export interface McpCheck {
  ok: boolean;
  tools: string[];
  reason: string | null;
}

export interface McpChange {
  enabled?: boolean;
  auth?: McpAuth;
}

export interface Health {
  status: string;
  version: string;
}

export type ChatEventKind =
  | "user"
  | "withdrawn"
  | "title"
  | "resources"
  | "writing"
  | "tool_calls"
  | "tool_output"
  | "cell"
  | "lab"
  | "note"
  | "connection"
  | "approval"
  | "question"
  | "usage"
  | "answer"
  | "stopped"
  | "failed"
  | "status";

export interface ChatEvent {
  kind: ChatEventKind;
  id: number;
  turn: number;
  speaker: string | null;
  text: string;
  data: Record<string, unknown>;
  time: number;
}

export interface Attachment {
  name: string;
  path: string;
  size: number;
}

// A file of a conversation, as the list of them shows it
export interface ChatFile {
  // From the conversation's files
  path: string;
  size: number;
  // Seconds since the epoch
  modified: number;
  // What the server sends it as, which is never a type that a browser would run
  type: string;
}

export interface ChatFiles {
  files: ChatFile[];
  // Whether there were more files than the list gives
  truncated: boolean;
}

// Whether Docker is there, as the setup finds it
export interface DockerStatus {
  installed: boolean;
  running: boolean;
  version: string | null;
  // What is wrong, when it is not running
  message: string | null;
}

// A stage of the image that code runs in, each adding to the one before
export interface ImageStage {
  target: string;
  tag: string;
  summary: string;
  // About how long it takes to build, in words
  estimate: string;
  // Not known while Docker is not running
  built: boolean | null;
  building: boolean;
}

export interface Images {
  platform: string;
  // Whether this computer runs the image by pretending to be another, which is slow
  emulated: boolean;
  stages: ImageStage[];
}

export interface DataLakeSummary {
  directory: string;
  // Whether the settings name the folder, and not the workspace
  custom: boolean;
  files: number;
  present: number;
  complete: boolean;
  bytes: number;
  free_bytes: number | null;
}

export interface DataLakeFile {
  name: string;
  description: string;
  present: boolean;
  bytes: number | null;
  // Whether Biomni's commercial mode uses it, which is whether it may be used commercially
  commercial: boolean;
}

export interface DataLake {
  data_lake: DataLakeSummary;
  files: DataLakeFile[];
}

export type JobState = "running" | "stopping" | "succeeded" | "failed" | "stopped";

// How far a job has got, of what it is counting: a fetch of the data lake counts files and bytes
export interface JobProgress {
  done?: number;
  total?: number;
  // What reading papers, or writing functions, counts: how many there are, and how many have been dealt with. Reading
  // one paper counts the chunks it is cut into.
  papers?: number;
  functions?: number;
  chunks?: number;
  finished?: number;
  current?: string | null;
  bytes?: number;
  bytes_total?: number | null;
  fetched?: number;
  // What fetching an agent's data counts: the files, and the bytes written so far, of how many there are
  files_done?: number;
  files_total?: number;
  bytes_done?: number;
}

// A piece of work the server does in the background: building an image, or fetching the data lake
export interface Job {
  id: string;
  kind: string;
  subject: string;
  title: string;
  state: JobState;
  // What it is doing, or did
  message: string;
  progress: JobProgress;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  // How many lines it has printed, which are not given with the list of jobs
  log_total: number;
  log?: { from: number; lines: string[] };
}

export type StepState = "done" | "todo" | "running" | "blocked";

// What there is to do to be ready to run code, one step at a time
export interface SetupStep {
  id: string;
  title: string;
  state: StepState;
  detail: string;
  // Whether code cannot run without it
  required: boolean;
}

export interface SetupStatus {
  docker: DockerStatus;
  images: Images;
  data_lake: DataLakeSummary;
  jobs: Job[];
  steps: SetupStep[];
}

// A piece of data the person gave the lab: a file or folder that was uploaded, and so is kept in the workspace, or one
// that is pointed to where it is on the server's machine, which is left there
export interface OwnData {
  // What code finds it by: the name of its file
  name: string;
  // What it is, which the lead is told
  description: string;
  source: "uploaded" | "path";
  // Where it is, for what was pointed to
  path: string | null;
  kind: "file" | "folder" | "missing";
  bytes: number | null;
  // Seconds since the epoch
  modified: number | null;
}

export interface OwnSoftware {
  name: string;
  description: string;
}

// What the person gave the lab to use in every conversation that runs code
export interface Own {
  data: OwnData[];
  software: OwnSoftware[];
  // The most bytes of a file that can be uploaded
  max_upload_bytes: number;
}

// A skill: written guidance on a kind of work, as the Skills page lists it
export interface SkillInfo {
  name: string;
  // What it is for and when to use it, which the lead is told
  description: string;
  // Where it was found: the lab's own skills folder (workspace), or the person's own, which other tools read too (user)
  source: string;
  directory: string;
  license: string | null;
  compatibility: string | null;
  metadata: Record<string, string>;
  // Ways it departs from the standard that did not stop it being used
  notes: string[];
  // Whether a new conversation is given it, and whether it can be deleted from here
  enabled: boolean;
  removable: boolean;
}

// A SKILL.md that was found and could not be used, and why
export interface SkillProblem {
  path: string;
  message: string;
}

// A folder skills are looked for in
export interface SkillFolder {
  source: string;
  path: string;
  exists: boolean;
}

// What listing the skills that are on takes of every conversation, since the lead is told what each is for before it begins:
// the characters there are, the most there can be, how long each description may be, and how many skills have none
export interface SkillsCatalog {
  skills: number;
  chars: number;
  budget: number;
  description_chars: number;
  without_description: number;
}

export interface Skills {
  skills: SkillInfo[];
  problems: SkillProblem[];
  folders: SkillFolder[];
  catalog: SkillsCatalog;
}

// What a skill's license means for a person: only noncommercial use is allowed (noncommercial), it is a GPL license
// (copyleft), it says none (none), or it is some other, which is shown as it is written (other)
export type LicenseKind = "noncommercial" | "copyleft" | "none" | "other";

// A skill of the library that comes with the lab, which is not used until it is put in
export interface LibrarySkill {
  name: string;
  description: string;
  group: string;
  category: string;
  license: string | null;
  license_kind: LicenseKind;
  compatibility: string | null;
  files: number;
  bytes: number;
  // Whether a skill of this name is already in the lab's own skills
  installed: boolean;
}

export interface LibraryCategory {
  name: string;
  group: string;
  count: number;
}

// The library that comes with the lab: where it came from, its skills in the order of its catalog, and the categories
export interface SkillLibrary {
  source: { name?: string; author?: string; url?: string; license?: string; version?: string; ref?: string };
  skills: LibrarySkill[];
  categories: LibraryCategory[];
  problems: string[];
}

// Where skills are put in from: the address of a Git repository, or the full path of a folder on the server's machine
export type SkillsFrom = { git: string } | { path: string };

// What putting in skills did: those that were put in, with how many of their files were too many or too big to copy, and
// those that were left with why, beside the skills as they now are
export interface SkillsPutIn extends Skills {
  installed: { name: string; left_out: number }[];
  skipped: { name: string; reason: string }[];
}

// What a skill tells the lead, as far as it is worth showing, and the files that come with it
export interface SkillPreview {
  name: string;
  instructions: string;
  characters: number;
  files: string[];
  more_files: number;
}

// The start of a piece of data, as far as it is worth showing
export type OwnPreview =
  | { kind: "text"; lines: string[]; truncated: boolean }
  | { kind: "binary" }
  | { kind: "folder"; entries: { name: string; folder: boolean }[]; more: number }
  | { kind: "missing" };

// Where a run's papers come from, and what it is told about itself for each
export type PaperSource =
  | { kind: "files" }
  | { kind: "folder"; path: string; recursive: boolean }
  | {
      kind: "biorxiv";
      since: string;
      until: string | null;
      subject: string;
      limit: number;
      random: boolean;
      include_unpublished: boolean;
    };

export type PaperSourceKind = PaperSource["kind"];

// A run of papers as a list shows it: what it is, and how far the reading has got. What the report says of it is null
// until the papers have been read.
export interface PaperRunEntry {
  id: string;
  title: string;
  source: PaperSource;
  created_at: string;
  // How many papers are uploaded, for a run whose papers are
  files: number | null;
  papers: number | null;
  // How many papers have been dealt with, whether they were read or not
  finished: number;
  read: number | null;
  unavailable: number | null;
  failed: number | null;
  spent: number | null;
  stopped: string | null;
  function_count: number;
  // Whether its functions are given to the conversations that are made from now on
  given: boolean;
  // The job at work on it, which is reading its papers or writing its functions
  job: string | null;
  job_kind: "papers" | "functions" | null;
}

export interface PapersList {
  runs: PaperRunEntry[];
  // The subjects of bioRxiv that papers may be asked of
  subjects: string[];
  max_paper_bytes: number;
  max_files: number;
  // What a paper uploaded may end in, with the dot
  suffixes: string[];
}

export type PaperStatus = "pending" | "read" | "unavailable" | "failed";

export interface PaperResult {
  key: string;
  title: string;
  doi: string | null;
  status: PaperStatus;
  tasks: number;
  databases: number;
  software: number;
  cost: number | null;
  error: string | null;
}

export type FindingKind = "tasks" | "databases" | "software";

// Something found in the papers, and how many of them it is found in
export interface PaperCount {
  name: string;
  papers: number;
}

export interface PaperSummary {
  // How many papers were counted
  papers: number;
  tasks: PaperCount[];
  databases: PaperCount[];
  software: PaperCount[];
  // How many more of each there are than are shown
  more: Record<FindingKind, number>;
}

export type FunctionStatus = "verified" | "unverified" | "failed";

export interface PaperFunctionRow {
  name: string;
  task: string;
  papers: number;
  status: FunctionStatus;
  modules: string[];
  error: string | null;
  cost: number | null;
  attempts: number;
}

export interface PaperRun extends PaperRunEntry {
  // The papers uploaded to it, for a run whose papers are
  uploads: { name: string; bytes: number }[] | null;
  results: PaperResult[];
  summary: PaperSummary;
  functions: PaperFunctionRow[];
}

// A function with what it was written for, and its code
export interface PaperFunction extends PaperFunctionRow {
  brief: string;
  problems: string[];
  source: string | null;
}

// What reading a run's papers, or writing its functions, may spend, in dollars
export interface PaperReadOptions {
  max_cost: number;
  max_cost_per_paper: number | null;
  retry_failed: boolean;
}

export interface PaperFunctionsOptions {
  max_cost: number;
  max_cost_per_function: number | null;
  min_papers: number;
  limit: number;
  retry_failed: boolean;
  verify: boolean;
}

// What a new run is asked for: its title, and where its papers come from
export interface NewPaperRun {
  title: string;
  source: PaperSource;
}

// Where the text of a paper was fetched from, which a file that was uploaded does not say: Europe PMC, or a link
export interface PaperAgentSource {
  kind: "europepmc" | "link";
  // How to say it, such as "Europe PMC, PMC3258128"
  label: string;
  // Where to see it
  url: string;
}

// The file of a paper that was uploaded to an agent, or the text of it that was fetched, which says where from
export interface PaperAgentFile {
  name: string;
  bytes: number;
  sha256: string;
  source?: PaperAgentSource | null;
}

// Which paper a PaperAgent is of: a DOI, a link, or a file that is uploaded to it, which has not been until it says so.
// A DOI or a link may have the file beside it, which is what is read: uploaded, or the text that was fetched when the paper
// was first read. It has none until one of those.
export type PaperAgentPaper =
  | { kind: "doi"; doi: string; file?: PaperAgentFile | null }
  | { kind: "url"; url: string; file?: PaperAgentFile | null }
  | { kind: "file"; file: PaperAgentFile | null };

export type PaperAgentPaperKind = PaperAgentPaper["kind"];

// The steps of making an agent, in the order they are done, and how far each has got
export type PaperAgentStep = "reading" | "repository" | "environment" | "data" | "tools";
export type PaperAgentStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface PaperAgent {
  id: string;
  title: string;
  created_at: string;
  paper: PaperAgentPaper;
  // Where the paper's code is, if that is known, and once it is fetched the commit that was, with what was asked for to get it
  repo: PaperAgentRepo | null;
  steps: Record<PaperAgentStep, PaperAgentStatus>;
}

export interface PaperAgentRepo {
  url: string;
  ref?: string;
  commit?: string;
}

export interface PaperAgentsList {
  agents: PaperAgent[];
  max_agents: number;
  max_paper_bytes: number;
  // What a paper uploaded may end in, with the dot
  suffixes: string[];
  // The hosts the code of a paper may be at
  repo_hosts: string[];
}

// Where a fact was found in the paper: the characters it is from and to in the text that was read, and the page of a PDF
// and the section it begins in, where those are known
export interface ReadAnchor {
  start: number;
  end: number;
  page: number | null;
  section: string | null;
}

// A fact that was read in a paper, with the paper's own words for it, which are in the paper, and where
export interface ReadFact {
  id: string;
  quote: string;
  anchor: ReadAnchor;
}

export interface ReadClaim extends ReadFact {
  kind: "number" | "comparison" | "qualitative";
  value: string;
}

export interface ReadMethod extends ReadFact {
  name: string;
}

export interface ReadDataset extends ReadFact {
  name: string;
  accession: string;
}

export interface ReadScope extends ReadFact {
  aspect: "species" | "tissue" | "assay" | "sample size" | "input" | "other";
  value: string;
}

export interface ReadSoftware extends ReadFact {
  name: string;
  version: string;
}

export interface ReadLink extends ReadFact {
  url: string;
  role: "code" | "data" | "other";
}

export interface ReadAvailability extends ReadFact {
  kind: "data" | "code";
}

export interface ReadLicense extends ReadFact {
  name: string;
  covers: "code" | "data" | "paper" | "unknown";
}

// What has been read of an agent's paper, as far as it has been: how far it has got, what it cost, and what it found
export interface PaperAgentReading {
  id: string;
  // Whether the paper has a file, which is what is read, and whether the text that was read of it is kept
  has_paper: boolean;
  has_text: boolean;
  // Whether the paper is a DOI or a link that has no file, so that reading it fetches its text first
  fetchable: boolean;
  // Where the text was fetched from, if the file is that
  source: PaperAgentSource | null;
  // The reading that is at work, if one is
  job: Job | null;
  // How many chunks the paper is cut into, or null if it has not been read
  chunks: number | null;
  read: number;
  skipped: number;
  failed: number;
  // Whether every chunk has come to something, which it has not if the reading was stopped or reached its limit
  complete: boolean;
  // How many facts were left out, because their quote was not in the paper, or something they say was not in the quote
  dropped: { quote: number; detail: number };
  // What the reading has cost, which is null if that cannot be told
  cost: number | null;
  calls: number;
  models: string[];
  characters: number | null;
  // How long the paper was, if only the first of it was read
  truncated_from: number | null;
  finished_at: string | null;
  claims: ReadClaim[];
  // A draft of what the method was done with and tested on, which nobody has checked
  card: {
    status: "draft";
    methods: ReadMethod[];
    datasets: ReadDataset[];
    scope: ReadScope[];
    limitations: ReadFact[];
  };
  resources: {
    software: ReadSoftware[];
    links: ReadLink[];
    availability: ReadAvailability[];
    licenses: ReadLicense[];
  };
}

// What to say of reading a paper: the most it may spend, which is always said, and whether to read again the chunks that
// could not be read
export interface PaperAgentReadOptions {
  max_cost: number;
  retry_failed: boolean;
}

// The words of the paper at a place, with some of what is around them
export interface PaperAgentPassage extends ReadAnchor {
  before: string;
  text: string;
  after: string;
}

// What a new agent is asked for: what it is called, which paper, and where the code is, if that is known
export interface NewPaperAgent {
  title: string;
  paper: { kind: "doi"; doi: string } | { kind: "url"; url: string } | { kind: "file" };
  repo?: string;
}

// What to say again of an agent: any of these, and an empty repo takes the code away
export interface PaperAgentChange {
  title?: string;
  repo?: string;
}

// What was found in a project's files, by looking at them: nothing in it was run
export interface RepositoryStock {
  schema: number;
  files: number;
  bytes: number;
  // Whether all of it was looked at, which it was not if it has more files than are looked at
  complete: boolean;
  languages: { name: string; files: number; bytes: number }[];
  notebooks: { count: number; listed: { path: string; bytes: number; code_cells: number | null; language: string | null }[] };
  // What tools are made from: notebooks, and scripts in a folder of examples or tutorials
  tutorials: { count: number; characters: number; listed: { path: string; kind: string; bytes: number; characters: number }[] };
  tests: { count: number; listed: string[] };
  // The files that say what to install, and whether each gives the versions: "locked", "all", "some", or none
  environment: { path: string; kind: string; pins: string | null }[];
  license: { files: string[]; name: string | null; kind: string; from: string } | null;
  readme: { path: string; example: boolean } | null;
  gpu: { required: RepositorySignal[]; optional: RepositorySignal[] };
  data: {
    count: number;
    bytes: number;
    listed: { path: string; bytes: number; kind: string }[];
    lfs: boolean;
    lfs_pointers: number;
    dvc: boolean;
    links: string[];
    accessions: string[];
  };
  submodules: { path: string; url: string }[];
  absolute_paths: { count: number; listed: { path: string; example: string }[] };
}

export interface RepositorySignal {
  path: string;
  signal: string;
  kind: string;
}

// How a check of whether to go on came out: fine, a thing to know, a thing to weigh, a reason to stop, or not known
export type PreflightStatus = "ok" | "note" | "warn" | "block" | "unknown";

// Go on, ask first, or do not
export type PreflightVerdict = "go" | "ask" | "no-go";

export interface PreflightCheck {
  id: string;
  title: string;
  status: PreflightStatus;
  detail: string;
}

// A guess at what making tools from the code's tutorials would cost in model requests, which is null if it cannot be told
export interface PreflightEstimate {
  low: number | null;
  high: number | null;
  tutorials: number;
  basis: string;
}

// Whether it is worth going on with a project's code, from its files alone, which is advice
export interface Preflight {
  verdict: PreflightVerdict;
  summary: string;
  checks: PreflightCheck[];
  estimate: PreflightEstimate;
}

// A project that the paper's links lead to, which a person says is the code or is not
export interface RepositoryCandidate {
  url: string;
  // What the paper says the first of its places is: its code, its data, or neither; the code first if any of them says so
  role: "code" | "data" | "other";
  // Whether it is where the agent's code is now
  chosen: boolean;
  facts: ReadFact[];
}

// What there is of an agent's code: where it is, the projects the paper points to, and once it is fetched what was found
export interface PaperAgentRepository {
  id: string;
  repo: PaperAgentRepo | null;
  cloned: boolean;
  intake: { url: string; ref: string; commit: string; cloned_at: string; limit_bytes: number } | null;
  stock: RepositoryStock | null;
  preflight: Preflight | null;
  candidates: RepositoryCandidate[];
  // The fetching that is at work, if one is
  job: Job | null;
  // Whether Git is installed, which fetching takes
  git: boolean;
  limits: { default_megabytes: number; min_megabytes: number; max_megabytes: number };
}

// What to say of fetching code: where from if it is not what the agent has, which branch, tag, or commit, and the most of
// it to fetch, in megabytes
export interface PaperAgentFetchOptions {
  repo?: string;
  ref?: string;
  max_megabytes?: number;
}

// What an environment is built from and how, which is from the code's own files and what a person asked for
export interface EnvironmentRecipe {
  kind: "pip" | "conda";
  // The version of Python, or null for a conda file that says its own
  python: string | null;
  python_from: string;
  base_image: string;
  files: string[];
  system_packages: string[];
  steps: { id: string; title: string; command: string[] }[];
  notes: string[];
}

// What a build is allowed
export interface EnvironmentLimits {
  minutes: number;
  gigabytes: number;
  memory: string;
  cpus: string;
  pids: number;
}

export type EnvironmentFailureKind =
  | "missing_system_library"
  | "version_conflict"
  | "python_mismatch"
  | "not_found"
  | "network"
  | "private_dependency"
  | "build_failed"
  | "out_of_memory"
  | "too_big"
  | "timeout"
  | "does_not_run"
  | "docker"
  | "failed";

// Why a build did not come to an environment, as far as its output says
export interface EnvironmentFailure {
  kind: EnvironmentFailureKind;
  title: string;
  detail: string;
  // The step it was at, by its id
  step: string | null;
  package: string | null;
  // Debian packages that would most likely mend it, and a Python to try, which a person may ask for
  system_packages: string[];
  python: string | null;
  // The last lines of the step's output
  tail: string[];
}

// An environment that was built, of the code at one commit
export interface EnvironmentBuilt {
  commit: string;
  url: string;
  built_at: string;
  recipe: EnvironmentRecipe;
  limits: EnvironmentLimits;
  image: {
    tag: string;
    // What the image is, as Docker says it: the hash of its contents, which is the pin
    id: string;
    base_id: string;
    base_digests: string[];
    architecture: string;
    size_bytes: number;
    added_bytes: number;
  };
  python: string;
  lock: { name: string; packages: number };
  pip_check: { ok: boolean; problems: string[] };
  steps: { id: string; title: string; seconds: number; exit_code: number }[];
  duration: number;
  // Whether Docker still has the image, or null if Docker could not be asked
  image_present: boolean | null;
}

// The last build of the code at one commit, which did not come to an environment
export interface EnvironmentFailed {
  commit: string;
  failed_at: string;
  recipe: EnvironmentRecipe;
  limits: EnvironmentLimits;
  failure: EnvironmentFailure;
}

// What there is of an agent's environment: what would be built from its code and how, or why it cannot be, what was built,
// and why the last build failed
export interface PaperAgentEnvironment {
  id: string;
  docker: { ready: boolean; message: string | null };
  commit: string | null;
  recipe: EnvironmentRecipe | null;
  // Why the code is not one that is built here: no_environment, r, julia, docker, pipfile, or python_mismatch
  unsupported: { kind: string; message: string } | null;
  built: EnvironmentBuilt | null;
  failure: EnvironmentFailed | null;
  // Whether the output of the last build is kept
  has_log: boolean;
  // The build that is at work, if one is
  job: Job | null;
  limits: {
    default_minutes: number;
    max_minutes: number;
    default_gigabytes: number;
    max_gigabytes: number;
    memory: string;
    cpus: string;
    pids: number;
  };
  python_versions: string[];
  max_system_packages: number;
}

// What to say of building an environment: which Python in place of what the code says, which Debian packages to install
// first, and the most time and disk it may take
export interface PaperAgentBuildOptions {
  python?: string;
  system_packages?: string[];
  minutes?: number;
  gigabytes?: number;
}

// What a place says a dataset is licensed as, which it may not say
export interface DataLicense {
  name: string | null;
  url: string | null;
}

// A place that the paper or its code says its data is at: one that data is fetched from, or one that is not and is only shown
export interface DataCandidate {
  key: string;
  // Which place it is, and what names it there, which are null for one that is not fetched from
  source: string | null;
  reference: string | null;
  label: string;
  // A page where a person can see it
  url: string | null;
  supported: boolean;
  // Why it is not fetched from, if it is not
  reason: string | null;
  // Where in the paper it is said, and whether the code names it too
  facts: ReadFact[];
  in_code: boolean;
  // How many of its files are kept
  fetched: number;
}

// Some of a person's own data that stands in for a dataset the paper used, as a note of which: nothing is copied
export interface DataStandIn {
  key: string;
  name: string;
  own: string;
  set_at: string;
}

// A person's own data, as the Data page has it
export interface OwnDataSummary {
  name: string;
  description: string;
  kind: string;
  bytes: number;
}

// A dataset the paper names, with the place its accession points to, and what stands in for it
export interface DataDataset {
  key: string;
  name: string;
  accession: string;
  quote: string;
  anchor: ReadAnchor;
  candidate: string | null;
  stand_in: DataStandIn | null;
}

// A file that was fetched and is kept
export interface KeptDataFile {
  name: string;
  // Where it is under the agent's data
  path: string;
  bytes: number;
  sha256: string;
  // The checksum the place gave, which it matched, or null if the place gave none and only the size was checked
  checksum: { algorithm: "md5" | "sha256"; value: string } | null;
  url: string;
  fetched_at: string;
  // Whether it is on disk, as big as it was written
  present: boolean;
}

// The files fetched from one place, and what the place says of them
export interface KeptDataSource {
  key: string;
  source: string;
  reference: string;
  label: string;
  url: string;
  title: string;
  license: DataLicense | null;
  folder: string;
  files: KeptDataFile[];
}

// A place that data is fetched from, and the hosts it is asked at, which are all that data is fetched from
export interface DataSourceInfo {
  source: string;
  name: string;
  hosts: string[];
  via: string[];
  // Whether its files can be fetched without an account
  downloads: boolean;
  note: string;
}

// What there is of an agent's data: what the paper says it used and where, what was fetched, and what stands in
export interface PaperAgentData {
  id: string;
  // Whether the paper has been read to the end, which what it names is found from
  read: boolean;
  datasets: DataDataset[];
  candidates: DataCandidate[];
  stand_ins: (DataStandIn & { own_data: OwnDataSummary | null })[];
  own: OwnDataSummary[];
  kept: { files: number; bytes: number; sources: KeptDataSource[] };
  sources: DataSourceInfo[];
  // The fetching that is at work, if one is
  job: Job | null;
  limits: { default_megabytes: number; min_megabytes: number; max_megabytes: number; max_kept_megabytes: number; max_files: number };
}

// A file that a place has, as the place lists it
export interface DataFileListed {
  name: string;
  // How big it is, which is null if the place does not say, and then it is not fetched
  bytes: number | null;
  checksum: { algorithm: "md5" | "sha256"; value: string } | null;
  downloadable: boolean;
  // Why it is not, if it is not
  why: string | null;
  kept: boolean;
}

// What a place has, asked of the place and not fetched
export interface DataListing {
  key: string;
  source: string;
  reference: string;
  label: string;
  url: string;
  title: string;
  license: DataLicense | null;
  files: DataFileListed[];
  // How many files it has, of which files are listed
  total_files: number;
  truncated: boolean;
  notes: string[];
  // Whether its files can be fetched without an account
  downloads: boolean;
}

// What to say of fetching: which place, which of its files, what they came to when they were shown, and the most to fetch
export interface PaperAgentDataFetch {
  reference: string;
  files: string[];
  expected_bytes: number;
  max_megabytes: number;
}

// A tutorial of the code that can be run here, and one that cannot, with why
export interface ReferenceItem {
  // What its record is kept under
  id: string;
  path: string;
  kind: "script" | "notebook";
}

export interface ReferenceSkipped {
  path: string;
  kind: string;
  reason: string;
}

// What would be run, from what was found in the code
export interface ReferencePlan {
  runnable: ReferenceItem[];
  skipped: ReferenceSkipped[];
  // How many more tutorials the code has than were listed
  more: number;
}

export type TutorialStatus = "ok" | "failed" | "timed_out" | "too_big";

export type TutorialFailureKind =
  | "needs_network"
  | "missing_file"
  | "missing_package"
  | "needs_gpu"
  | "needs_notebook"
  | "notebook_unreadable"
  | "out_of_memory"
  | "timeout"
  | "too_big"
  | "no_result"
  | "error";

// What a reference run was allowed, and what each run of a tutorial was given of the machine
export interface ReferenceLimits {
  minutes: number;
  total_minutes: number;
  tutorials: number;
  repeats: number;
  gigabytes: number;
  memory: string;
  cpus: string;
  pids: number;
}

// How one tutorial ended, in a list
export interface TutorialSummary {
  id: string;
  path: string;
  kind: "script" | "notebook";
  status: TutorialStatus;
  failure: { kind: TutorialFailureKind; title: string } | null;
  seconds: number;
  // How many times it was run, and whether the runs agreed, which is null if it was run once or did not finish
  runs: number;
  stable: boolean | null;
  // What was not the same from one run to the next
  differs: string[];
  calls: number;
  files: number;
  cells: number;
  cells_total: number;
}

// What was kept of a run of the tutorials
export interface ReferenceKept {
  commit: string;
  image_id: string;
  started_at: string;
  finished_at: string | null;
  // Whether it came to its end, and was not stopped or failed on the way
  complete: boolean;
  limits: ReferenceLimits;
  // What the runs were given of the data that was fetched, or null if they were given none
  data: { files: number; bytes: number } | null;
  tutorials: TutorialSummary[];
  skipped: ReferenceSkipped[];
  more: number;
  not_run: { path: string; reason: string }[];
}

// What there is of the running of an agent's tutorials: which would be run, what is given, and what was kept
export interface PaperAgentReference {
  id: string;
  docker: { ready: boolean; message: string | null };
  commit: string | null;
  environment: { built: boolean; image_present: boolean | null };
  plan: ReferencePlan | null;
  // What a run would be given of the data, or null if there is none
  data: { files: number; bytes: number } | null;
  kept: ReferenceKept | null;
  // The run that is at work, if one is
  job: Job | null;
  // What a reference run is, in words, which is said wherever it is shown
  meaning: string;
  limits: {
    default_minutes: number;
    max_minutes: number;
    default_total_minutes: number;
    max_total_minutes: number;
    default_tutorials: number;
    max_tutorials: number;
    default_repeats: number;
    max_repeats: number;
    default_gigabytes: number;
    max_gigabytes: number;
    memory: string;
    cpus: string;
    pids: number;
  };
}

// What to say of running the tutorials: the most time for one and for all, how many, how many times each, the most one may write, and
// whether they are given the data. What is left out is what the server defaults to
export interface PaperAgentReferenceOptions {
  minutes?: number;
  total_minutes?: number;
  tutorials?: number;
  repeats?: number;
  gigabytes?: number;
  data?: boolean;
}

// A value that a tutorial passed to the code's function, or that it got back: itself if it is plain data, and otherwise what it was
// and a look at it
export interface TutorialValue {
  type: string;
  plain: boolean;
  value?: unknown;
  repr?: string;
  shape?: number[];
  dtype?: string;
  sha256?: string;
  values?: unknown;
}

// A call that a tutorial made to one of the code's own functions
export interface TutorialCall {
  id: number;
  module: string;
  function: string;
  qualname: string;
  method: boolean;
  file: string;
  line: number;
  args: Record<string, TutorialValue>;
  // The folder it was made from, which is where it has to be made from again
  cwd: string;
  variadic: boolean;
  result: TutorialValue | null;
  returned: boolean;
  cell: number | null;
  from: { file: string; line: number };
}

export interface TutorialFile {
  path: string;
  bytes: number;
  sha256: string | null;
  // Whether the tutorial made it, and did not find it
  new: boolean;
  // Whether its content is kept
  kept: boolean;
}

export interface TutorialCell {
  index: number;
  ok: boolean;
  seconds: number;
  output: string;
  result: string | null;
  // Which magics or shell lines were left out of it, as they are not Python
  skipped: string[];
  error: { type: string; message: string; traceback: string[]; cell: number | null } | null;
}

// What was kept of one tutorial: how it ended, what it printed, the calls it made, and the files it wrote
export interface TutorialDetail {
  id: string;
  path: string;
  kind: "script" | "notebook";
  status: TutorialStatus;
  failure: { kind: TutorialFailureKind; title: string; detail: string; tail: string[] } | null;
  python: string | null;
  seconds: number;
  runs: { status: string; seconds: number; digest: Record<string, unknown> | null }[];
  stable: boolean | null;
  differs: string[];
  // The end of what it printed, by line
  output: string[];
  cells: TutorialCell[];
  cells_total: number;
  calls: TutorialCall[];
  // How many calls it made in all, of which calls are kept
  calls_seen: number;
  files: TutorialFile[];
  files_more: number;
  packages: string[];
}
