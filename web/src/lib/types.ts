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
  // The ids of the PaperAgents it was given
  paperagents?: string[];
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
  // The PaperAgents that have a seat on its team, each with the title of the scientist that speaks for it
  papers: PaperSeat[];
}

// A PaperAgent that a conversation has, and the scientist of its team that speaks for its paper, whom /lab names
export interface PaperSeat {
  id: string;
  title: string;
  seat: string;
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
  // The ids of the PaperAgents it is given, in place of those that are given to conversations
  paperagents?: string[];
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

// A resource an MCP server lists: something to read, such as a table or a document, or, for a template, a family of them
export interface McpResource {
  name: string;
  title: string | null;
  uri: string;
  description: string;
  mime_type: string | null;
  // Whether its address is a pattern to be filled in, which is not one thing to read
  template: boolean;
}

export interface McpPromptArgument {
  name: string;
  description: string;
  required: boolean;
}

// A prompt an MCP server lists: words to begin a message with, written out by the server for the arguments it takes
export interface McpPrompt {
  // Its name on the server
  name: string;
  // What it is written as after a slash
  command: string;
  title: string | null;
  description: string;
  arguments: McpPromptArgument[];
}

// What an MCP server lists besides its tools, as it was when it was last connected to
export interface McpHolds {
  resources: McpResource[];
  prompts: McpPrompt[];
  // What the server said of what it could not list
  problems: string[];
  // Whether it has more than it was asked for, which are not listed
  more: boolean;
  // When it was connected to, ISO 8601 in UTC: not said of what a check has just found
  seen?: string | null;
}

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
  // What it listed when it was last connected to, as it is set up now: null where it has not been, or has been changed since
  holds: McpHolds | null;
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
  // What it listed besides its tools, where it was connected to
  holds?: McpHolds;
}

// A prompt of an MCP server written out for some arguments, as the words to begin a message with
export interface RenderedPrompt {
  text: string;
  // Each part of it, with who says it
  messages: { role: string; text: string }[];
  description?: string;
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
  // What making an agent in one go counts: its steps, the one it is at, and what that step is doing
  steps?: number;
  step?: string | null;
  detail?: string;
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
  // The files that came with the paper, which are read with it, in the order they were added. A server from before them does not say.
  supplementary?: PaperAgentFile[];
  // Where the paper's code is, if that is known, and once it is fetched the commit that was, with what was asked for to get it
  repo: PaperAgentRepo | null;
  steps: Record<PaperAgentStep, PaperAgentStatus>;
  // Whether the conversations that are made from now on are given the agent, which only the person says
  given: boolean;
  // What it was imported from, for an agent that someone else made of the paper, and null for one that was made here
  imported: PaperAgentImported | null;
  // The job that is making it in one go, if one is, which nothing else is done to it meanwhile. A server from before
  // making in one go does not say.
  onego?: Job | null;
  // The title of the scientist that speaks for it on a conversation's team, where no other there has the title, which
  // only the list gives
  seat?: string;
}

// How making an agent in one go stands: not asked for, going, waiting for the person to say something, done, failed,
// stopped, or interrupted, as it is when the server stopped while it went
export type OneGoState = "none" | "running" | "waiting" | "done" | "failed" | "stopped" | "interrupted";

export type OneGoStepState = "pending" | "running" | "done" | "skipped" | "waiting" | "failed" | "stopped";

export type OneGoStepName = "repository" | "reading" | "look" | "environment" | "reference" | "tools" | "checks" | "given";

export interface OneGoStep {
  step: OneGoStepName;
  title: string;
  state: OneGoStepState;
  // How it came out, or why it was skipped, in a sentence
  note: string | null;
}

// What was asked of it, which is what is asked again unless it is said otherwise
export interface OneGoSettings {
  max_cost: number | null;
  repo: string | null;
  ref: string | null;
  give: boolean;
  without_code: boolean;
  // The commit of the code that the person said to go on with, after looking at it
  go_on: string | null;
}

// A place that the paper points to, which is not taken for its code until the person says so
export interface OneGoCandidate {
  url: string;
  role: RepositoryCandidate["role"];
  quote: string;
}

// What stands in the way, on the step it stands at, with what a page needs to show the person what to decide
export interface OneGoStuck {
  step: OneGoStepName;
  // What it is: code, preflight, limit, paper_file, paper_text, docker, git, or model when it is for the person to say,
  // and failed, refused, error, no_code, or stopped otherwise
  kind: string;
  reason: string;
  candidates?: OneGoCandidate[];
  verdict?: PreflightVerdict;
  commit?: string;
  checks?: { title: string; status: PreflightStatus; detail: string }[];
  spent?: number | null;
  limit?: number | null;
}

export interface PaperAgentOneGo {
  id: string;
  state: OneGoState;
  started_at: string | null;
  finished_at: string | null;
  settings: OneGoSettings;
  steps: OneGoStep[];
  stuck: OneGoStuck | null;
  // What it came to, once every step has been got to
  summary: string | null;
  // The job that is making it, if one is, or the one that was just started
  job: Job | null;
}

// What is asked when it is started, or gone on with: what is left out is what it was before
export interface PaperAgentMakeOptions {
  max_cost?: number;
  repo?: string;
  ref?: string;
  give?: boolean;
  without_code?: boolean;
  go_on?: boolean;
}

// One tool that the server of an imported agent listed when it was last connected to
export interface ImportedTool {
  // Its name on the server
  name: string;
  // What it is for, in a line
  summary: string;
  // The names of what it is passed
  parameters: string[];
}

// An agent that someone else made, reached at a server that they run. Nothing of the lab's has been done to it, which is its tier.
export interface PaperAgentImported {
  kind: "hosted";
  // Who made it, as far as is known: only the servers that Paper2Agent hosts say so, since a host's name does not show who made what it holds
  origin: string | null;
  url: string;
  // The machine that runs it, which is not this one
  host: string;
  imported_at: string;
  // When its server was last connected to, which is when its tools were listed
  checked_at: string;
  tier: string;
  checked: false;
  // Whether each call waits for the person's approval, which it always does
  asks: true;
  // What the tier says, in words
  meaning: string;
  tools: ImportedTool[];
}

// A server that others host, which is known to be an agent of a paper, and that can be imported with a click
export interface ImportableAgent {
  key: string;
  title: string;
  about: string;
  made_by: string;
  url: string;
  // Where to read more of it
  site: string;
  paper: { kind: "doi"; doi: string };
  // The paper's code, which it was made from
  repo: string;
  // The agent that has this server already, if one does
  agent: string | null;
  // The agent of its paper, if there is one, which the server could be added to
  paper_agent: string | null;
}

// What to ask of the server to import an agent: the server and either the paper it is of, or the agent to add it to
export interface NewImport {
  url: string;
  title?: string;
  paper?: NewPaperAgent["paper"];
  repo?: string;
  agent?: string;
}

// Whether the server of an imported agent could be connected to again, and why not, with the agent as it is kept now
export interface PaperAgentImportCheck {
  ok: boolean;
  reason: string | null;
  agent: PaperAgent;
}

export interface PaperAgentRepo {
  url: string;
  // The other addresses of the code, which are tried in this order if it cannot be fetched from the one before. Only one is fetched.
  also?: string[];
  ref?: string;
  commit?: string;
}

export interface PaperAgentsList {
  agents: PaperAgent[];
  max_agents: number;
  max_paper_bytes: number;
  // What a paper uploaded may end in, with the dot, which a supplementary file may as well
  suffixes: string[];
  // The most supplementary files a paper keeps. A server from before them does not say.
  max_supplementary?: number;
  // The hosts the code of a paper may be at
  repo_hosts: string[];
  // The servers that others host, which can be imported
  importable: ImportableAgent[];
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

// What a statement of the scope of a method may be about
export type ScopeAspect = "species" | "tissue" | "assay" | "sample size" | "input" | "other";

// Whose a fact of the method card is: what the model read, or what a person changed or added
export type CardBy = "reading" | "person";

// A fact of the method card. One that a person added has their own words, if they gave any, and no place in the paper. One that a
// person changed keeps the paper's words and where they are, and says what it was read as.
export interface CardFact {
  id: string;
  quote: string;
  anchor: ReadAnchor | null;
  by: CardBy;
  // What a fact that a person changed was read as, by field. It is null for one that was added, and the server leaves it out of one
  // that is as it was read.
  read_as?: Record<string, string> | null;
  // When a person changed or added it, which a fact that is as it was read does not say
  at?: string;
}

export interface CardMethod extends CardFact {
  name: string;
}

export interface CardDataset extends CardFact {
  name: string;
  accession: string;
}

export interface CardScope extends CardFact {
  aspect: ScopeAspect;
  value: string;
}

export type CardKind = "methods" | "datasets" | "scope" | "limitations";

// What the method was done with and tested on, as it is now: what the reading made with what a person did to it put over, and
// whether a person approved it as it is
export interface MethodCard {
  status: "draft" | "approved";
  // When it was approved, which is null unless it is as it was then
  approved_at: string | null;
  // Whether it was approved and has changed since
  changed_since_approval: boolean;
  // Whether any of it is a person's
  edited: boolean;
  methods: CardMethod[];
  datasets: CardDataset[];
  scope: CardScope[];
  limitations: CardFact[];
  // What a person took off, which they can put back
  removed: { methods: CardMethod[]; datasets: CardDataset[]; scope: CardScope[]; limitations: CardFact[] };
}

// What a person says of a fact of the card, by field, with the words of a fact that is their own as quote
export type CardFields = Record<string, string>;

// Whether data is inside what the card says the method was used on, outside it, or the card does not say enough to tell. Only outside
// is warned of.
export type ScopeOutcome = "inside" | "outside" | "not covered";

// What a person says their data is, any of it, to be put against the card. The size is a whole number, and unit is what it counts.
export interface ScopeData {
  species?: string;
  tissue?: string;
  assay?: string;
  input_format?: string;
  sample_size?: number;
  sample_unit?: string;
}

// A statement of scope on the card that data was put against, as the answer gives it, with the place in the paper that it has if
// it has one
export interface ScopeStatement {
  id: string;
  value: string;
  quote: string;
  by: CardBy;
  // Whether a person changed it, which has it say what they say with the paper's words beside it
  changed: boolean;
  page: number | null;
  section: string | null;
}

// The answer for one thing that was said of the data
export interface ScopeAnswer {
  aspect: ScopeAspect;
  // What was said of the data, as the server has it
  given: string;
  outcome: ScopeOutcome;
  // The statements it was put against: those that cover it if it is inside, and those of its sort otherwise
  says: ScopeStatement[];
  reason: string;
}

// What the card says of a sort that nothing was said of
export interface ScopeNotChecked {
  aspect: ScopeAspect;
  says: ScopeStatement[];
}

// What an answer of a scope check says: what each thing that was said is against the card, and how far the card is to be trusted
export interface ScopeView {
  outcome: ScopeOutcome;
  aspects: ScopeAnswer[];
  // One for each thing that is outside, with the card's words and the paper's
  warnings: string[];
  not_checked: ScopeNotChecked[];
  // How far the card is to be trusted
  card: Pick<MethodCard, "status" | "approved_at" | "changed_since_approval" | "edited"> & { scope_facts: number };
  // How far the paper was read, where chunks is null if it was not
  reading: { complete: boolean; chunks: number | null; read: number; failed: number };
  notes: string[];
}

// Data put against the card. The whole is outside if anything is, and inside only if everything that was said is.
export interface ScopeCheck extends ScopeView {
  id: string;
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
  // What the method was done with and tested on: a draft until a person has approved it
  card: MethodCard;
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
  // The other addresses of the code, in the order they are tried, which are said again whole
  also?: string[];
  // Whether the conversations that are made from now on are given the agent
  given?: boolean;
}

// One tool that a conversation is given of an agent: one that reads what was kept of its paper, one that runs the authors' code,
// or one that runs a function that a model wrote from the paper
export interface GivenTool {
  name: string;
  // One of an imported agent calls the server that someone else runs, and was not checked here
  kind: "reading" | "run" | "reimplementation" | "imported";
  // D for one that reads, for one that runs, the tier it was made as, C for a re-implementation, and Imported for one of an imported
  // agent
  tier: string;
  // What it does, in a line
  summary: string;
  // The names of what it is passed
  parameters: string[];
  // What a re-implementation is labelled wherever it is shown, and null for any other tool
  label: string | null;
}

// What an agent gives a conversation, worked out from what is kept now
export interface PaperAgentGiven {
  id: string;
  given: boolean;
  // A or B if it has tools that run the authors' code, C if what runs is a re-implementation, D if it has only tools that read, Imported
  // if it has only those of the server it was imported from, and null if it has none
  tier: string | null;
  tools: GivenTool[];
  // Why the tools that run are not given, if they would be and cannot be, such as Docker not running
  problem: string | null;
  // What the tiers say, in words
  meaning: string;
  // What the agent was imported from, if it was
  imported: PaperAgentImported | null;
  limits: { call_seconds: number; memory: string; cpus: string };
  // The title of the scientist that speaks for it on a conversation's team, where no other there has the title
  seat: string;
  // What that scientist is told, which is its system prompt, and has nothing that the paper says
  told: string;
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
  // Whether the person added it to the agent. A server from before that could be does not say.
  added?: boolean;
  // How many of its files are kept
  fetched: number;
}

// A place for the data that the person added, as they wrote it
export interface DataLink {
  key: string;
  text: string;
  added_at: string;
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

// A dataset on the method card, which the paper names or a person put there, with the place its accession points to, and what stands in for it
export interface DataDataset {
  key: string;
  name: string;
  accession: string;
  quote: string;
  // Where in the paper it is, which is null for a dataset that a person added
  anchor: ReadAnchor | null;
  by: CardBy;
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
  // The places that the person added, which are among the candidates. A server from before them does not say.
  links?: DataLink[];
  own: OwnDataSummary[];
  kept: { files: number; bytes: number; sources: KeptDataSource[] };
  sources: DataSourceInfo[];
  // The fetching that is at work, if one is
  job: Job | null;
  limits: {
    default_megabytes: number;
    min_megabytes: number;
    max_megabytes: number;
    max_kept_megabytes: number;
    max_files: number;
    max_links?: number;
  };
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

// Why a function that a tutorial called was not made a tool, in a word
export type ToolDroppedKind =
  | "method"
  | "nested"
  | "variadic"
  | "no_usable_call"
  | "source_not_found"
  | "source_mismatch"
  | "too_many_parameters"
  | "wrapper"
  | "replay_error"
  | "replay_differs"
  | "timed_out"
  | "out_of_time"
  | "over_limit";

// A function that was not made a tool, with why
export interface ToolDropped {
  name: string;
  module: string;
  function: string;
  kind: ToolDroppedKind;
  reason: string;
  // What was found, such as how what a call gave was not what the tutorial got
  details: string[];
  // How many calls the tutorials made to it
  calls: number;
}

// A tutorial whose calls were not looked at, with why
export interface ToolUnused {
  tutorial: string;
  reason: string;
}

// A call that cannot be made again, with why
export interface ToolSkipped {
  call: number;
  tutorial: string;
  reason: string;
}

// A function that would be made a tool
export interface ToolCandidate {
  name: string;
  module: string;
  function: string;
  file: string;
  line: number;
  // How many calls can be made again
  cases: number;
  tutorials: string[];
  skipped: ToolSkipped[];
}

// A tool that was made, in a list: it is of tier A, which says that it gave again what the tutorial got
export interface ToolSummary {
  name: string;
  tier: string;
  module: string;
  function: string;
  parameters: string[];
  // How many calls were made again, of how many that were recorded, and how many times each
  checked: number;
  recorded: number;
  repeats: number;
  tutorials: string[];
}

// What making tools was allowed, and what each call that is made again is given of the machine
export interface ToolsLimits {
  minutes: number;
  total_minutes: number;
  tools: number;
  repeats: number;
  repairs: number;
  gigabytes: number;
  memory: string;
  cpus: string;
  pids: number;
}

// What was kept of the making of tools, which is of one commit, one image, and one reference run
export interface ToolsKept {
  commit: string;
  image_id: string;
  reference: { started_at: string; finished_at: string };
  started_at: string;
  finished_at: string | null;
  // Whether it came to its end, and was not stopped or failed on the way
  complete: boolean;
  limits: ToolsLimits;
  // Whether the calls were given the data that the tutorials were
  data: boolean;
  tools: ToolSummary[];
  dropped: ToolDropped[];
  unused: ToolUnused[];
}

// What there is of the making of an agent's tools: what would be made and what would not, what was made, and what is allowed
export interface PaperAgentTools {
  id: string;
  docker: { ready: boolean; message: string | null };
  // The run of the tutorials that tools are made from, or null if there is none that came to its end
  reference: { complete: boolean; tutorials: number; finished_at: string; data: boolean } | null;
  preview: { candidates: ToolCandidate[]; dropped: ToolDropped[]; unused: ToolUnused[] } | null;
  kept: ToolsKept | null;
  // The making that is at work, if there is one
  job: Job | null;
  // What a tool of tier A is, in words, which is said wherever it is shown
  meaning: string;
  limits: {
    default_minutes: number;
    max_minutes: number;
    default_total_minutes: number;
    max_total_minutes: number;
    default_tools: number;
    max_tools: number;
    default_repeats: number;
    max_repeats: number;
    default_repairs: number;
    max_repairs: number;
    default_gigabytes: number;
    max_gigabytes: number;
    memory: string;
    cpus: string;
    pids: number;
  };
}

// What to say of making tools: the most time for the calls of one and for all, how many, how many times each call is made again, how
// many times a wrapper is rewritten, and the most one may write. What is left out is what the server defaults to
export interface PaperAgentToolsOptions {
  minutes?: number;
  total_minutes?: number;
  tools?: number;
  repeats?: number;
  repairs?: number;
  gigabytes?: number;
}

// What came of calling a tool again with the arguments of one call of a tutorial
export interface ToolCase {
  call: number;
  tutorial: string;
  cell: number | null;
  origin: { file: string; line: number };
  cwd: string;
  // What the tutorial passed, as JSON, by parameter
  args: Record<string, unknown>;
  // What the tutorial got
  expected: TutorialValue;
  repeats: number;
  // How many of the times it was made again gave what the tutorial got
  matched: number;
  verdict: "match" | "differs" | "error" | "not_run";
  differences: string[];
  got: TutorialValue | null;
  error: { type: string; message: string; traceback?: string[] } | null;
}

// One tool: its wrapper, its signature, and the evidence for its tier, which is each call that was made again
export interface ToolDetail {
  name: string;
  tier: string;
  repo: { module: string; function: string; file: string; line: number };
  signature: { name: string; type: string; required: boolean; default: unknown }[];
  description: string;
  wrapper_sha256: string;
  // The wrapper's code
  source: string;
  evidence: {
    kind: string;
    image_id: string;
    tolerance: { relative: number; absolute: number };
    repeats: number;
    checked: number;
    recorded: number;
    cases: ToolCase[];
    skipped: ToolSkipped[];
    // The steps by which the wrapper was rewritten until it passed its checks, each with what it was for
    repairs: { change: string; because: string[] }[];
  };
}

// How one kind of check of a tool stands: it passed, failed, or could not be made (not obtained), it was made for something that is not
// kept now (stale, which counts for nothing), or it has not been made
export type CheckStatus = "passed" | "failed" | "not_obtained" | "stale" | "not_run";

// One kind of check of one tool, with how it went
export interface CheckEvidence {
  kind: string;
  title: string;
  // What it holds the tool to: the code's own function, the code's own tests, or the numbers that the paper reports
  basis: string;
  // What it shows, and what it does not
  what: string;
  status: CheckStatus;
  summary: string;
  // Where it is kept, relative to the agent, or null if it was not made
  file: string | null;
  checked_at: string | null;
  // What a stale check came to when it was made
  was: string | null;
  // What it was made of, which is only given when one tool's checks are asked for
  details?: Record<string, unknown>;
  limits?: Record<string, number>;
  seconds?: number;
}

// A tool as the checks list it: the tier it was made as, the tier that its checks come to now, and each kind of check
export interface CheckedTool {
  name: string;
  module: string;
  function: string;
  made_as: string;
  tier: string;
  // The kinds of check that passed, and the bases that they are against
  passed: string[];
  bases: string[];
  evidence: CheckEvidence[];
}

// One tool's checks, with what each was made of and what the tier means
export interface CheckedToolDetail extends CheckedTool {
  meaning: string;
}

// A kind of check that can be asked for
export interface CheckKind {
  kind: string;
  title: string;
  // What a tool that passed it is said to have done, in words that follow "passed checks that its tutorial did not give it ("
  said: string;
  what: string;
  basis: string;
  // Whether it is made when no kind is named, which is so of those that need no model and cost nothing
  default: boolean;
  // Whether it asks a model, which costs what the model charges
  model: boolean;
}

// What there is of the checks of an agent's tools: each tool and how its checks went, what can be asked for, and what is allowed
export interface PaperAgentChecks {
  id: string;
  docker: { ready: boolean; message: string | null };
  // Whether the tools were made to their end, which is what is checked
  made: boolean;
  tools: CheckedTool[];
  // The model in the settings, and whose it is, which a model that chooses inputs must not be of, or null if that is not known
  settings_model: string;
  settings_family: string | null;
  kinds: CheckKind[];
  // How many numbers of the paper have digits enough to be looked for in what the tools gave
  numbers: number;
  // The checking that is at work, if there is one
  job: Job | null;
  // What tier B is, in words, which is said wherever it is shown
  meaning: string;
  // What a check can be against, by name, with what each is
  bases: Record<string, string>;
  // How many bases a tool must have a check that passed against to be of tier B
  bases_for_b: number;
  limits: {
    default_minutes: number;
    max_minutes: number;
    default_total_minutes: number;
    max_total_minutes: number;
    default_repeats: number;
    max_repeats: number;
    default_gigabytes: number;
    max_gigabytes: number;
    memory: string;
    cpus: string;
    pids: number;
  };
}

// What to say of checking tools. What is left out is what the server defaults to, which is the kinds that need no model; the most
// that asking a model may spend is said if one of them is asked for, and the model that chooses inputs if that kind is
export interface PaperAgentChecksOptions {
  minutes?: number;
  total_minutes?: number;
  repeats?: number;
  gigabytes?: number;
  kinds?: string[];
  max_cost?: number;
  verifier_model?: string;
}

// How one claim of a paper came out when it was held to what the tutorials gave. Stale is what a claim is shown as when what was said
// of it is of another run of the tutorials, or of other claims, than are kept now, and is not said to be anything else
export type ClaimStatus = "reproduced" | "partly" | "not_reproduced" | "not_attempted" | "stale";

// Where a claim was held to, which is a place in what a tutorial gave: the result of a call, or a line that it printed
export interface ClaimLink {
  // How the place was found: by the number, by the figure that the sentence and the tutorial both refer to, or by both
  basis: string;
  tutorial: { id: string; path: string; kind: string; runs: number; stable: boolean | null };
  source: "call" | "line";
  // The place in words
  where: string;
  // The call that gave it, if it was a call
  call: number | null;
  got: number;
  // The number as the paper wrote it
  number: { text: string; value: number; decimals: number; percent: boolean };
  // How far what was got is from the number, as a share of it
  share: number;
  // The figures and tables that the sentence and the tutorial both refer to
  figures: string[];
  chosen_by: string;
  // Other places that hold the number, which were not chosen
  others: { tutorial: string; where: string; value: number }[];
}

// One claim of a paper, and what came of trying it
export interface ClaimOutcome {
  id: string;
  kind: string;
  // The number as the paper writes it, or nothing for a claim that states none
  value: string;
  quote: string;
  anchor: ReadAnchor | null;
  figures: string[];
  status: ClaimStatus;
  // Why it was not attempted, for one that was not
  reason: string | null;
  summary: string;
  link: ClaimLink | null;
  // What a stale claim was before
  was?: ClaimStatus;
}

// What there is of the trying of an agent's claims: each claim of the paper and how it came out, and what is needed to try them again
export interface PaperAgentReproduction {
  id: string;
  ready: boolean;
  problem: { code: string; message: string } | null;
  settings_model: string;
  // How many numbers of the paper have digits enough to be tried
  numbers: number;
  reference: { commit: string; image_id: string; reference: { started_at: string; finished_at: string } } | null;
  kept: {
    started_at: string;
    finished_at: string | null;
    complete: boolean;
    model: string;
    cost: number | null;
    requests: number;
    limit: string | null;
    notes: string[];
  } | null;
  // Whether what is kept is of the run of the tutorials and the claims that are kept now
  current: boolean;
  claims: ClaimOutcome[];
  // How many claims of the paper come after the most that are listed, which are not listed or tried
  more: number;
  counts: Record<ClaimStatus, number>;
  job: Job | null;
  meaning: string;
  limits: { partly_share: number; most_claims: number; most_asked: number; batch: number };
}

// What to say of trying the claims: the most that asking a model may spend
export interface PaperAgentReproductionOptions {
  max_cost: number;
}

// A difference found between what the paper says and what was used here. It is not said to be why a number differs.
export interface DivergenceDifference {
  kind: "python" | "package" | "data" | "runs" | "seed" | "argument";
  text: string;
  evidence: Record<string, unknown>;
  // The paper's words that it is held to, if there are any
  quote: string | null;
}

// The first output of a tutorial that parts from a number of the paper, and the outputs before it that agreed
export interface DivergencePoint {
  first: { claim: string; quote: string; number: string; got: number; where: string; call: number | null };
  // False if it is in a printed line, whose order among the calls is not known
  ordered: boolean;
  agreed: { claim: string; quote: string; number: string; got: number; where: string; call: number | null }[];
  agreed_count: number;
  text: string;
}

// A claim that did not reproduce, or only partly, with where its tutorial first parts from the paper and what differs that was found
export interface DivergenceClaim {
  id: string;
  quote: string;
  value: string;
  status: ClaimStatus;
  tutorial: string;
  point: DivergencePoint | null;
  differences: DivergenceDifference[];
}

// Software that the paper names, with the version that is installed here
export interface DivergenceSoftware {
  name: string;
  paper: string;
  installed: string | null;
  state: "same" | "differs" | "no_version" | "not_comparable" | "not_installed";
  quote: string;
}

// Where the tutorials first part from the paper for each claim that did not reproduce, made from what is kept
export interface PaperAgentDivergence {
  id: string;
  ready: boolean;
  problem: { code: string; message: string } | null;
  current: boolean;
  run: { python: string | null; packages: number; data: unknown; tutorials: number } | null;
  claims: DivergenceClaim[];
  software: DivergenceSoftware[];
  // Those of the whole run
  differences: DivergenceDifference[];
  counts: { claims: number; points: number; differences: Record<string, number> };
  meaning: string;
}

// An argument of the call that a claim was held to, as it was given
export interface VariantArgument {
  name: string;
  // The value in words, cut if it is long
  text: string;
  // The value, if it is short enough to be offered. It is also null for a value that is nothing
  value: unknown;
  // Whether it is a value that an argument can be given as, which a change can be of
  plain: boolean;
}

// What a person may change of the call that a claim was held to, or why no variant of the claim can be made
export type VariantOption =
  | { claim: string; can: true; refused: null; function: string; arguments: VariantArgument[] }
  | { claim: string; can: false; refused: { code: string; message: string } };

export type VariantStatus = "gave" | "no_place" | "unstable" | "error" | "not_run";
export type ControlVerdict = "match" | "differs" | "error" | "not_run";

// A variant of a claim: its call made again with arguments changed, and what came of it. It is never the paper's result.
export interface Variant {
  id: string;
  made_at: string;
  seconds: number;
  limits: { minutes: number; repeats: number; gigabytes: number };
  note: string | null;
  claim: string;
  quote: string;
  // The number as the paper writes it
  number: string;
  tutorial: { id: string; path: string };
  call: number;
  function: string;
  where: string;
  path: (string | number)[];
  changes: { name: string; was: unknown; now: unknown }[];
  // What the tutorial's call gave at the place that the claim was held to
  claim_run: number;
  // The same call with nothing changed, made in the same way
  control: { verdict: ControlVerdict; gave: number | null; differences: string[]; error: { type: string; message: string } | null };
  variant: {
    status: VariantStatus;
    gave: number | null;
    values: (number | null)[];
    type: string | null;
    error: { type: string; message: string } | null;
    differences: string[];
  };
  // Whether the call with nothing changed gave what the tutorial got, and the variant gave a number
  comparable: boolean;
  // Whether the number it gave rounds to the paper's, if it gave one. That is not a reproduction.
  rounds_to_paper: boolean | null;
  repeats: number;
  tolerance: { relative: number; absolute: number };
  text: string;
}

// What there is of the variants of an agent's claims: what may be changed of each claim's call, and the variants that were made
export interface PaperAgentVariants {
  id: string;
  ready: boolean;
  problem: { code: string; message: string } | null;
  reproduction: { commit: string; image_id: string; reference: { started_at: string; finished_at: string } } | null;
  claims: VariantOption[];
  variants: Variant[];
  // How many variants are kept that are of another run, other claims, or another trying, and are not shown
  stale: number;
  counts: { variants: number; comparable: number; rounds_to_paper: number };
  job: Job | null;
  meaning: string;
  limits: {
    most_changes: number;
    max_value_chars: number;
    max_note_chars: number;
    most_kept: number;
    default_minutes: number;
    max_minutes: number;
    default_repeats: number;
    max_repeats: number;
    default_gigabytes: number;
    max_gigabytes: number;
  };
}

// What to say of making a variant: the claim, the new value of each argument to change, and what the two calls may take
export interface PaperAgentVariantOptions {
  claim: string;
  changes: Record<string, unknown>;
  minutes: number;
  repeats: number;
  gigabytes: number;
  note?: string;
}

// The trying of the claims, where each first parts from the paper, and the variants made of them, which are looked at together
export interface PaperAgentClaims {
  reproduction: PaperAgentReproduction;
  divergence: PaperAgentDivergence;
  variants: PaperAgentVariants;
}

// A heading of the paper and the words under it, which can be chosen to be given to the model that writes a function
export interface ReimplementationSpan {
  index: number;
  title: string;
  start: number;
  end: number;
  chars: number;
  page: number | null;
}

// A place in the paper whose words the model is given
export interface ReimplementationPlace {
  start: number;
  end: number;
  section: string | null;
  page: number | null;
  chars: number;
}

// What a person is shown, and agrees to, before a function is written: the words of the paper that a program chose from what they said,
// what the function is called, the model that would write it, and a key that is bound to all of that
export interface ReimplementationOffer {
  name: string;
  goal: string | null;
  search: string | null;
  sections: number[];
  places: ReimplementationPlace[];
  // Whether the words were cut to the most that is given
  cut: boolean;
  // All that the model is given of the paper, as it is sent
  brief: string;
  chars: number;
  model: string;
  file_sha256: string;
  key: string;
}

export type ReimplementationStatus = "written" | "failed" | "stopped";

// What was kept of writing a function from the paper, with its code if one was written
export interface ReimplementationKept {
  name: string;
  paper_sha256: string;
  agreed_at: string;
  model: string;
  limit: number;
  started_at: string;
  finished_at: string;
  status: ReimplementationStatus;
  error: string | null;
  // What was wrong with each answer that could not be used
  problems: string[];
  attempts: number;
  cost: number | null;
  task: {
    goal: string | null;
    search: string | null;
    sections: number[];
    places: ReimplementationPlace[];
    cut: boolean;
    chars: number;
    brief_sha256: string;
  };
  // Verified if it was imported in a container with no network, unverified if it was only read
  function: { status: "verified" | "unverified"; source_sha256: string; modules: string[] } | null;
  // Whether it is of the paper's file that the agent has now
  current: boolean;
  // The code, if there is a function and its file is the one that was written
  source: string | null;
}

export type MatchingStatus = "matched" | "not_found" | "ambiguous" | "unstable" | "error" | "not_run" | "hard_coded" | "no_inputs";

// What one claim came to when the function was checked: what it was called with and whose that was, and what it gave
export interface MatchingEntry {
  claim: string;
  value: string;
  quote: string;
  by: "model" | "person" | null;
  arguments: Record<string, unknown> | null;
  // The words of the passage that the model said give the inputs
  where: string | null;
  // Why there were no inputs, and in words
  reason: string | null;
  note: string | null;
  // The literals of the code that round to the claim's number
  hard_coded: string[];
  status: MatchingStatus;
  found: { path: (string | number)[]; text: string; value: number; how: string } | null;
  places: number;
  error: string | null;
  // What it gave, in words, cut if it is long
  gave: string | null;
  seconds: number | null;
}

// The inputs that the person gave for a claim, which the function is called with in place of what a model reads
export interface MatchingInputs {
  claim: string;
  arguments: Record<string, unknown>;
  given_at: string;
}

// A claim of the paper that the function is checked against, with the passage around it
export interface MatchingClaim {
  id: string;
  value: string;
  quote: string;
  passage: string | null;
  inputs: MatchingInputs | null;
  entry: MatchingEntry | null;
}

// A parameter of the function, which inputs are given for
export interface MatchingParameter {
  name: string;
  hint: string;
  required: boolean;
  default: string | null;
}

// What there is of checking the function against the numbers that the paper reports
export interface PaperAgentMatching {
  kept: {
    started_at: string;
    finished_at: string;
    status: "done" | "stopped" | "failed";
    error: string | null;
    model: string | null;
    limit: number | null;
    cost: number | null;
    requests: number;
    minutes: number;
    ended: string | null;
    output: string[];
  } | null;
  // Whether what is kept is of this function, the paper's file, and the claims that are kept now
  current: boolean;
  // C if it matched a number of the paper, and null otherwise
  tier: string | null;
  label: string;
  claims: MatchingClaim[];
  counts: Record<MatchingStatus, number> | null;
  parameters: MatchingParameter[] | null;
  meaning: Record<MatchingStatus, string>;
  limits: { most_tried: number; repeats: number; default_minutes: number; most_minutes: number; most_arguments_chars: number };
  job: Job | null;
}

// What there is of writing a function from an agent's paper, which has none of its code: whether it can be, what the person would be
// shown and agree to, what was kept of a writing, and of checking it against the paper
export interface PaperAgentReimplementation {
  id: string;
  ready: boolean;
  problem: { code: string; message: string } | null;
  settings_model: string;
  tier: string;
  label: string;
  meaning: string;
  sections: ReimplementationSpan[];
  default_sections: number[];
  offer: ReimplementationOffer | null;
  // Why what was asked for cannot be offered, such as a name that is not one
  choice_problem: string | null;
  kept: ReimplementationKept | null;
  job: Job | null;
  checks: PaperAgentMatching;
  limits: { most_chars: number; most_goal_chars: number; most_search_chars: number; most_searched: number; most_sections: number };
}

// What the offer is to be made of: the sections by their numbers, words to search for, the function's name, and what is wanted of it.
// What is left out is what the server chooses
export interface ReimplementationChoice {
  sections?: number[];
  search?: string;
  name?: string;
  goal?: string;
}

// What to say to write the function: the key of what was agreed to, what was chosen, and the most that asking the model may spend
export interface PaperAgentReimplementationOptions extends ReimplementationChoice {
  agreed: string;
  max_cost: number;
}

// What to say to check the function: whether a model reads the inputs, the most it may spend if so, and the most minutes for the calls
export interface PaperAgentMatchingOptions {
  ask: boolean;
  max_cost?: number;
  minutes: number;
}

// A bake-off: which method of the literature is best for a task on the person's own data, with one limit on what the whole of it
// may spend. This is a bake-off as a list of them shows it.
export interface BakeoffSummary {
  id: string;
  title: string;
  task: string;
  created_at: string;
  // How many methods are in the running
  candidates: number;
  // The most it may spend, and what has been, in dollars
  limit: number;
  spent: number;
  // Whether every request that was paid for said what it used. If one did not, what was spent is not known, and nothing more is spent.
  cost_known: boolean;
  // The job that is finding, building, or running its methods, if one is
  job: Job | null;
}

// What the server takes of a bake-off
export interface BakeoffLimits {
  max_bakeoffs: number;
  max_candidates: number;
  max_task_chars: number;
  max_title_chars: number;
  max_name_chars: number;
  max_queries: number;
  most_found: number;
  most_chosen: number;
}

export interface BakeoffsList {
  bakeoffs: BakeoffSummary[];
  // The person's own data, from the Data page, which a bake-off may be run on and may take its right answers from
  own: OwnDataSummary[];
  limits: BakeoffLimits;
  // The model that reading papers and proposing calls is paid for with
  settings_model: string;
}

// The data that a bake-off is run on, as it is now: its name, what the Data page says of it, and whether it is gone
export type BakeoffData = { own: string; missing: boolean } & Partial<OwnDataSummary>;

// Where the right answers are, which is a table of the person's on the Data page, and whether it can be used as it is now. They
// are the person's word, and nothing checks them.
export interface BakeoffLabels {
  own: string;
  column: string;
  id_column: string | null;
  ok: boolean;
  // Why it cannot be used now, as a short name and in words
  why: string | null;
  problem: string | null;
  bytes: number | null;
  // Whether the methods are able to read the answers, as the file is the data they are run on, or is in it
  in_data: boolean;
  says: string;
}

// What a person said of their data, as a bake-off keeps it: every part, with what was not said an empty text or a size of none, and
// when it was said
export interface BakeoffDescribed {
  species: string;
  tissue: string;
  assay: string;
  input_format: string;
  sample_unit: string;
  sample_size: number;
  at: string;
}

// The paper of a method, which is given by its DOI or a link to it
export type BakeoffPaper = { kind: "doi"; doi: string } | { kind: "url"; url: string };

// Who put a method in the running: a search, which is a model's reading of abstracts, or the person
export type BakeoffBy = "search" | "person";

// Where a method that a search found was found, as the service gave it. A link is the service's own page for it, or empty.
export interface BakeoffFound {
  source: string;
  url: string;
  credit: string;
  venue: string;
  year: number | null;
  cited_by: number;
  preprint: boolean;
  // Whether Europe PMC holds its full text, which reading it needs. Null for a paper of arXiv, which is read from its PDF.
  full_text: boolean | null;
}

// The words of the abstract that the model went by in choosing a method, which a program found in it, and which model
export interface BakeoffFit {
  quote: string;
  model: string;
}

// Where a method stands: not gone at, being built, built, or stood in the way of, which is for the person to say (waiting), so of the
// method (blocked), a step that went wrong (failed), or not got to (pending)
export type BakeoffState = "new" | "building" | "built" | "waiting" | "blocked" | "failed" | "pending";

export interface BakeoffStanding {
  state: BakeoffState;
  // Which step it is at, or was at when it was stood in the way of
  step: string | null;
  reason: string;
  // A short name for the reason, which is only given with what stood in the way
  why?: string;
  at?: string;
}

// The PaperAgent that a method's paper has, which building the method makes if there is none
export interface BakeoffAgent {
  id: string;
  title: string;
  repo: string | null;
  steps: PaperAgent["steps"];
}

// A method's data put against the card of its paper: the answer of a scope check, or why there is none. It is worked out each time and
// is not kept. What is kept is that the person goes on, with the key of what they were shown.
export interface BakeoffScope {
  checked: boolean;
  // Why it was not put against a card, as a short name, and in words
  why: string | null;
  reason: string;
  outcome: ScopeOutcome | null;
  of: ScopeAnswer[];
  not_checked: ScopeNotChecked[];
  warnings: string[];
  card: ScopeView["card"] | null;
  reading: ScopeView["reading"] | null;
  notes: string[];
  // What the person was shown, which going on is said by. Null where it was not put against a card.
  key: string | null;
  // Whether the person goes on with it on this data, outside as it is, and when they said so
  went_on: boolean;
  went_on_at: string | null;
}

// How a call ended: it gave an answer, it was made and did not give one, or it was not made
export type BakeoffRunState = "ran" | "failed" | "not_run";

// Why a call that was made did not give an answer, and why one was not made, as short names. A name that is not here is shown as the
// server says it.
export type BakeoffRunWhy =
  | "error"
  | "timed_out"
  | "too_big"
  | "no_answer"
  | "outside"
  | "no_data"
  | "data_missing"
  | "cannot_mount"
  | "not_built"
  | "no_tool"
  | "bad_call"
  | "not_proposed"
  | "limit";

// The tool that a call was of: its name, the function of the authors' code that it calls, and the tier it had when it was called
export interface BakeoffRunTool {
  name: string;
  called: string;
  tier: string;
}

// The data a call was made on, as it was listed then. The fingerprint is of the names, sizes and times of change of its files, and is not
// a hash of what is in them.
export interface BakeoffRunData {
  own: string;
  path: string;
  files: number;
  bytes: number;
  fingerprint: string;
  // Whether every file was listed, which is not so if there were very many
  complete: boolean;
}

// What a call was proposed by a model as: which model, what it said of why, what asking it cost, and what it proposed before a
// program checked it
export interface BakeoffRunProposed {
  model: string;
  reason: string;
  cost: number | null;
  tool: string | null;
  arguments: string | null;
}

// What the data was put against the card of the method's paper as when the call was made
export interface BakeoffRunScope {
  checked: boolean;
  why: string | null;
  outcome: ScopeOutcome | null;
  key: string | null;
  went_on: boolean;
  warnings: string[];
}

// The PaperAgent that a call was made with, and the commit and image that its tools were made of
export interface BakeoffRunMethod {
  agent: string;
  commit: string;
  image_id: string;
}

// A call that was made, as it is kept: what it was, what it was on, and what it gave, took, or failed with. It does not say that what
// it gave is right. The result is the start of it in a list of methods, and all of it, or what was kept of it, when the run is asked for.
export interface BakeoffRunOf<Result> {
  schema: number;
  candidate: string;
  state: BakeoffRunState;
  why: BakeoffRunWhy | null;
  // In words, why it failed or was not made
  reason: string;
  at: string;
  by: "person" | "model";
  proposed: BakeoffRunProposed | null;
  tool: BakeoffRunTool | null;
  arguments: Record<string, unknown> | null;
  seconds: number | null;
  result: Result | null;
  // The last of what it printed
  printed: string | null;
  data: BakeoffRunData | null;
  scope: BakeoffRunScope;
  method: BakeoffRunMethod | null;
  // What is not as it was when it ran, which is the data, or the method if it was built again
  since: ("data" | "method")[];
}

// The start of a result, which a list of methods shows before the whole of it is asked for. It is plain data if `plain`, and otherwise
// a look at what was too much to be kept as it was.
export interface BakeoffRunPreview {
  type: string;
  plain: boolean;
  chars: number;
  start: string;
  cut: boolean;
}

export type BakeoffRunSummary = BakeoffRunOf<BakeoffRunPreview>;

// What a run kept of a result: the value if it was plain data that fitted, and otherwise a look at it, or only its size and a hash
export type BakeoffRunResult = { type: string } & Record<string, unknown>;

export type BakeoffRun = BakeoffRunOf<BakeoffRunResult>;

// A method that is in the running
export interface BakeoffMethod {
  id: string;
  name: string;
  paper: BakeoffPaper;
  // The title of its paper, if a search found it
  title: string;
  // Where its code is, as the person said, and what its abstract pointed to, which is not the code until they say so
  repo: string | null;
  suggested: string[];
  added_by: BakeoffBy;
  added_at: string;
  found: BakeoffFound | null;
  fit: BakeoffFit | null;
  agent: BakeoffAgent | null;
  standing: BakeoffStanding;
  scope: BakeoffScope;
  // What came of running it the last time, with only the start of its result, or null if it has not been run
  run: BakeoffRunSummary | null;
}

// Why choices that a model made were thrown away, and how many of each
export type BakeoffDropped = Record<"not_shown" | "twice" | "quote" | "more" | "already" | "no_room", number>;

// What finding methods in the literature came to
export interface BakeoffShortlist {
  started_at: string;
  finished_at: string;
  model: string;
  // Whether a model wrote the searches or the person did
  written_by: "model" | "person";
  queries: string[];
  // How many papers were found to choose from, of how many were found before there were more than a model is shown
  found: number;
  total: number;
  chosen: number;
  added: number;
  dropped: BakeoffDropped;
  notes: string[];
  // Whether it came to its end, and what stopped it if it did not
  complete: boolean;
  note: string | null;
  cost: number;
}

// A bake-off as one is looked at: its methods are given, and not counted as the list of them has it
export interface Bakeoff extends Omit<BakeoffSummary, "candidates"> {
  candidates: BakeoffMethod[];
  shortlist: BakeoffShortlist | null;
  // What the methods that a search found are, and are not, which is said beside them
  meaning: string;
  data: BakeoffData | null;
  // What the person says the data is, if they do
  described: BakeoffDescribed | null;
  labels: BakeoffLabels | null;
  // What may still be spent, which is nothing if what was spent is not known
  left: number;
  limits: BakeoffLimits;
  settings_model: string;
}

export interface BakeoffLabelsBody {
  own?: string;
  column?: string;
  id_column?: string;
}

export interface NewBakeoff {
  task: string;
  title?: string;
  data?: string;
  described?: ScopeData;
  labels?: BakeoffLabelsBody;
  limit: number;
}

// What to say again of a bake-off: what is left out is left as it was, empty data takes the data away, and an empty object for what
// the data is, or for where the right answers are, takes that away
export interface BakeoffChange {
  task?: string;
  title?: string;
  data?: string;
  described?: ScopeData;
  labels?: BakeoffLabelsBody;
  limit?: number;
}

// A method to put in the running: its paper, what it is called, and where its code is
export interface NewBakeoffMethod {
  paper: BakeoffPaper;
  name?: string;
  repo?: string;
}

// What to say again of a method: any of these, and an empty address takes the code away
export interface BakeoffMethodChange {
  name?: string;
  repo?: string;
}

// How to find methods: the searches, if the person says them and a model does not write them
export interface BakeoffShortlistBody {
  queries?: string[];
}

// How to build methods: which, all that are not built if left out, and which of those that are waiting to be gone on with
export interface BakeoffBuildBody {
  candidates?: string[];
  go_on?: string[];
}

// What one method is called with: the name of one of its tools and the arguments, by the names of the tool's parameters, or for a model
// to propose the call. Whoever chose it, a program checks it against the tool before it is made.
export type BakeoffCallBody = { tool: string; arguments: Record<string, unknown> } | { propose: true };

// How to run methods: the call of each, by the id of the method, and the most minutes that one call may take
export interface BakeoffRunBody {
  calls: Record<string, BakeoffCallBody>;
  minutes?: number;
}

// How a method came out when the methods were put side by side. A method that was not built is a row of the table too.
export type BakeoffComparedState = BakeoffRunState | "not_built";

// How much of a result was kept, which decides what it can be compared by: all of it, a look at it, or only a hash of it
export type BakeoffKept = "whole" | "look" | "hash";

// Why a method was not held to the right answers
export type BakeoffUnscoredWhy =
  | "labels_unusable"
  | "no_answer"
  | "data_changed"
  | "not_kept"
  | "not_a_list_or_object"
  | "not_values"
  | "length"
  | "no_id_column"
  | "ids_unusable"
  | "none_in_common";

// How a method did against the right answers, which is its score if it was held to them and why it was not if it was not. A score is
// null in the table of a bake-off that has no right answers.
export interface BakeoffScore {
  scored: boolean;
  why: BakeoffUnscoredWhy | null;
  reason: string;
  // Whether its answers were matched to the labels by their place in the data or by what each is the answer to
  by: "position" | "id" | null;
  matched: number | null;
  of: number | null;
  score: number | null;
  // How many of the labels it gave no answer to, and how many answers it gave that there is no label for
  missing: number | null;
  extra: number | null;
  examples: string[];
  // Its place among the methods that were scored, which methods that matched the same number share
  rank: number | null;
}

// A method as the table puts it: where it stands, what running it came to, what it cost, and which of the others it agrees with
export interface BakeoffComparedMethod {
  id: string;
  name: string;
  title: string;
  agent: BakeoffAgent | null;
  state: BakeoffComparedState;
  // Why it failed or was not run, as a short name, which is for a method that was not built the name that it stood in the way of
  why: string | null;
  reason: string;
  // The tier of the tool that was called, when it was called
  tier: string | null;
  tool: string | null;
  seconds: number | null;
  // What it cost: reading its paper, which may have been paid before the bake-off was made, and asking a model for the call, which
  // is nothing if the person chose it. Either is null if it is not known, or the method was not run.
  cost: { reading: number | null; asking: number | null };
  by: "person" | "model" | null;
  kept: BakeoffKept | null;
  // What is not as it was when it ran
  since: ("data" | "method")[];
  score: BakeoffScore | null;
  // The ids of the methods that it gave the same answer as, another answer than, and whose answer is not known to be the same or not
  agrees: string[];
  differs: string[];
  unknown: string[];
}

// Whether two methods gave the same answer, as far as what was kept of each shows, which is that it is not known if it does not show it
export type BakeoffVerdict = "agree" | "differ" | "unknown";

export interface BakeoffPair {
  first: string;
  second: string;
  verdict: BakeoffVerdict;
  how: string;
  differences: string[];
  // How much was kept of the answer of each
  kept: [BakeoffKept, BakeoffKept];
}

// The right answers, as the table holds the methods to them: where they are, whether they could be used, and how many there are. They are
// the person's word, and nothing checks them.
export interface BakeoffGroundTruth {
  own: string;
  column: string;
  id_column: string | null;
  ok: boolean;
  why: string | null;
  problem: string | null;
  bytes: number | null;
  in_data: boolean;
  says: string;
  rows: number | null;
  labelled: number | null;
  unlabelled: number | null;
  sha256: string | null;
}

// How closely two numbers must be to be the same
export interface BakeoffTolerance {
  relative: number;
  absolute: number;
}

// The methods of a bake-off side by side, as of now: how each came out, what it cost, whether they agree, and, if the person gave right
// answers, how each did against them
export interface BakeoffComparison {
  id: string;
  title: string;
  task: string;
  limit: number;
  spent: number;
  cost_known: boolean;
  tolerance: BakeoffTolerance;
  ground_truth: BakeoffGroundTruth | null;
  // Whether any method was ranked
  ranked: boolean;
  // What the table is of, in words: that there are or are not right answers to hold the methods to
  says: string;
  // What agreeing, and being scored, mean and do not
  meaning: string;
  methods: BakeoffComparedMethod[];
  pairs: BakeoffPair[];
}
