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

export interface KeyStatuses {
  // The keys that can be given
  settable: string[];
  providers: ProviderStatus[];
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
