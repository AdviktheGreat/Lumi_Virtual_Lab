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

export interface ChatConfig {
  model: string;
  lead: Scientist;
  team: Scientist[];
  code: CodeSetup;
  max_cost: number | null;
  stream: boolean;
  commercial_mode: boolean;
  // The names of the library's tools the lead may call
  tools: string[];
  // The names of the MCP servers whose tools the lead may be given, which it connects to with its first message
  mcp: string[];
  // The names of the data and software the person gave the lab that the conversation is given, where there is code
  data: string[];
  software: string[];
}

// A conversation as the list of them shows it
export interface ChatSummary {
  id: string;
  title: string;
  // ISO 8601, in UTC
  created_at: string | null;
  updated_at: string | null;
  state: ListedChatState;
  turns: number;
  spent: number | null;
  max_cost: number | null;
  model: string | null;
}

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
  usage: Usage;
  last_event_id: number;
  lead: string;
  team: string[];
  can_run_code: boolean;
  config: ChatConfig;
}

// What a new conversation is set up with: anything left out is what the settings say
export interface NewChat {
  title?: string;
  model?: string;
  lead?: string | Scientist;
  team?: (string | Scientist)[];
  code?: Partial<CodeSetup>;
  max_cost?: number | null;
  stream?: boolean;
  commercial_mode?: boolean;
  tools?: string[];
  mcp?: string[];
  data?: string[];
  software?: string[];
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
}

// What a request to change the settings may hold: any of them, each as it is to be
export type SettingsChange = Partial<Omit<Settings, "workspace" | "max_upload_bytes">>;

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
  current?: string | null;
  bytes?: number;
  bytes_total?: number | null;
  fetched?: number;
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

// The start of a piece of data, as far as it is worth showing
export type OwnPreview =
  | { kind: "text"; lines: string[]; truncated: boolean }
  | { kind: "binary" }
  | { kind: "folder"; entries: { name: string; folder: boolean }[]; more: number }
  | { kind: "missing" };
