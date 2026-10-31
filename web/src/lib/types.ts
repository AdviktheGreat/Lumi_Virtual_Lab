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
  // How many team sessions the lead may start in answering a message, and how many rounds it may ask one for, or null
  // for what the lead is given unless it is told otherwise
  max_delegations: number | null;
  max_rounds: number | null;
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
  // What reading papers, writing functions, or answering a benchmark's questions counts: how many there are, and how
  // many have been dealt with
  papers?: number;
  functions?: number;
  questions?: number;
  finished?: number;
  // What working on a project counts: the round it is in, of the most it may take, and what it has spent, of the most it
  // may spend
  round?: number;
  max_rounds?: number;
  spent?: number;
  max_cost?: number;
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

export type BenchmarkId = "biomni_eval1" | "lab_bench_dbqa" | "lab_bench_seqqa" | "hle";

export type BenchmarkSolver = "single" | "team";

export type BenchmarkSubset = "test" | "sampled" | "all";

// A benchmark, with what the files that were fetched say of it, which is null until they are there
export interface BenchmarkInfo {
  id: BenchmarkId;
  title: string;
  summary: string;
  // The tasks of Biomni-Eval1, and how many questions each has
  tasks: { name: string; questions: number }[] | null;
  // The files of LAB-Bench that can be asked, and how many questions each has
  subsets: { id: BenchmarkSubset; summary: string; questions: number }[] | null;
  // How many questions of Humanity's Last Exam refer to an image
  images: number | null;
  // How many questions it has before a run narrows them
  questions: number | null;
}

// A run as a list shows it: what it is, who answers, and how far the answering has got. What the report says of it is
// null until some questions have been answered.
export interface BenchmarkRunEntry {
  id: string;
  title: string;
  benchmark: BenchmarkId;
  solver: BenchmarkSolver;
  rounds: number;
  model: string | null;
  created_at: string;
  questions: number;
  finished: number;
  failed: number | null;
  accuracy: number | null;
  cost: number | null;
  spent: number | null;
  stopped: string | null;
  // The job at work on it
  job: string | null;
}

export interface BenchmarksList {
  runs: BenchmarkRunEntry[];
  benchmarks: BenchmarkInfo[];
  files: {
    ready: boolean;
    directory: string;
    // The files that are not there, or are not the ones that are pinned
    missing: string[];
    // Why the files that are there cannot be read
    problem: string | null;
  };
  solvers: { id: BenchmarkSolver; title: string; summary: string }[];
  max_rounds: number;
  max_questions: number;
  // The model that answers a run made now, and where its code runs
  model: string;
  code: { where: string; sandbox: string };
}

export type QuestionState = "unanswered" | "answered" | "failed";

// A question as a list shows it, and how it was answered if it was
export interface BenchmarkQuestionRow {
  key: string;
  task: string;
  id: number;
  // The start of what was asked, which is null where the benchmark's files cannot be read
  prompt: string | null;
  state: QuestionState;
  answer: string | null;
  correct_answer: string | null;
  // From 0, wrong, to 1, right
  score: number | null;
  cost: number | null;
  elapsed: number | null;
  error: string | null;
}

export interface BenchmarkTaskRow {
  task: string;
  questions: number;
  finished: number;
  accuracy: number | null;
}

// What a run is asked of its benchmark, of which only what is for the benchmark is kept
export interface BenchmarkOptions {
  tasks?: string[];
  subset?: BenchmarkSubset;
  leave_out_images?: boolean;
}

export interface BenchmarkRun extends BenchmarkRunEntry {
  options: BenchmarkOptions;
  // How many questions were asked for, or null for all
  limit: number | null;
  code: { where: string | null; sandbox: string | null; network: string | null; resources: string | null };
  lead: string | null;
  team: string[];
  // The benchmark's measures over the questions answered, such as accuracy, or accuracy/task for one of Biomni-Eval1's
  metrics: Record<string, number | null>;
  tasks: BenchmarkTaskRow[];
  results: BenchmarkQuestionRow[];
  // Why what was answered is shown without its questions
  problem: string | null;
}

export interface BenchmarkTurn {
  agent: string;
  message: string;
}

// One question, with what was asked, what was said in answering it, and what that cost
export interface BenchmarkQuestion extends BenchmarkQuestionRow {
  // What was read out of what the model said, in the form the benchmark asks answers in
  output: Record<string, unknown> | null;
  usage: {
    input_tokens?: number;
    output_tokens?: number;
    reasoning_tokens?: number;
    num_calls?: number;
    cost?: number | null;
  } | null;
  turns: BenchmarkTurn[] | null;
  // Whether what was said is cut short
  truncated: boolean;
}

// What a new run is asked for
export interface NewBenchmarkRun extends BenchmarkOptions {
  title: string;
  benchmark: BenchmarkId;
  solver: BenchmarkSolver;
  rounds?: number;
  limit?: number;
}

// What answering a run's questions may spend, in dollars
export interface BenchmarkStartOptions {
  max_cost: number;
  max_cost_per_question: number | null;
  retry_failed: boolean;
}

export type ProjectState =
  | "new"
  | "running"
  | "finished"
  | "out_of_budget"
  | "out_of_rounds"
  | "stalled"
  | "stopped"
  | "failed"
  | "interrupted";

export type ProjectTeam = "chosen" | "lab";

export type ProjectMemory = "pick" | "bm25" | "summaries";

export type ProjectLimitName = "max_team_size" | "meeting_rounds" | "findings_per_step" | "max_rounds" | "max_stalled_rounds";

// A project as a list shows it: what it is for, how it stands, and what it has spent
export interface ProjectEntry {
  id: string;
  title: string;
  goal: string;
  created_at: string;
  model: string | null;
  state: ProjectState;
  rounds_taken: number;
  tasks: number;
  tasks_done: number;
  spent: number;
  // The most it may spend over all the times it is worked on, which is null until it is first worked on
  max_cost: number | null;
  // The job at work on it
  job: string | null;
}

export interface ProjectsList {
  projects: ProjectEntry[];
  teams: { id: ProjectTeam; title: string; summary: string }[];
  memories: { id: ProjectMemory; title: string; summary: string }[];
  limits: Record<ProjectLimitName, { label: string; default: number; least: number; most: number }>;
  default_team: ProjectTeam;
  default_memory: ProjectMemory;
  max_goal_chars: number;
  // The model that works on a project made now, where its code runs, who leads it, and the scientists of the lab
  model: string;
  code: { where: string; sandbox: string };
  lead: string | null;
  team: string[];
}

export interface ProjectMember {
  title: string;
  expertise: string;
}

export interface ProjectTask {
  task: string;
  status: string;
}

export type ProjectAction = "team_meeting" | "individual_meeting" | "write_code" | "change_team" | "finish";

// A round: what the lead decided to do, and how it went
export interface ProjectRound {
  number: number;
  action: ProjectAction | "";
  participants: string[];
  agenda: string;
  questions: string[];
  rationale: string;
  progress: string;
  // The answer the lead proposed to end with, if it did
  answer: string;
  outcome: string;
  note: string;
  steps: string[];
  tasks_done: number;
  // The findings the round's step was given, and the findings it made, by id
  findings: string[];
  found: string[];
}

export interface ProjectFinding {
  id: string;
  claim: string;
  evidence: string;
  source: string;
  round: number | null;
}

// A step as a list shows it: a meeting, or code that was written and run
export interface ProjectStepRow {
  name: string;
  kind: string;
  status: string;
  round: number | null;
  cost: number | null;
  elapsed: number | null;
  started_at: string | null;
  error: string | null;
}

export interface Project extends ProjectEntry {
  team_mode: ProjectTeam;
  max_team_size: number;
  meeting_rounds: number;
  memory: ProjectMemory;
  findings_per_step: number;
  code: { where: string | null; sandbox: string | null; network: string | null; resources: string | null };
  lead: ProjectMember | null;
  critic: ProjectMember | null;
  team: ProjectMember[];
  plan: ProjectTask[];
  rounds: ProjectRound[];
  findings: ProjectFinding[];
  // The answer the critic accepted, or the last it did not, with what it objected to
  answer: string | null;
  proposed_answer: string | null;
  objections: string[];
  // Why it ended, in a sentence
  reason: string | null;
  // Whether there is a report of how it ended, to save
  report: boolean;
  error: string | null;
  steps: ProjectStepRow[];
}

export interface ProjectStepCode {
  filename: string;
  language: string;
  contents: string;
  output: string | null;
}

// One step, with what it produced, and what was said in it, or the code that was run
export interface ProjectStep extends ProjectStepRow {
  usage: {
    input_tokens?: number;
    output_tokens?: number;
    reasoning_tokens?: number;
    num_calls?: number;
    cost?: number | null;
  } | null;
  turns: { agent: string; message: string }[] | null;
  // Whether what was said is cut short
  truncated: boolean;
  output: unknown;
  code: ProjectStepCode[] | null;
  attempts: number | null;
  succeeded: boolean | null;
}

// What a new project is asked for: its goal, and how it is worked on, of which what is not given is the default
export interface NewProject {
  goal: string;
  title?: string;
  team?: ProjectTeam;
  max_team_size?: number;
  meeting_rounds?: number;
  memory?: ProjectMemory;
  findings_per_step?: number;
}

// What working on a project may spend, in dollars, over all the times it is worked on, and how many rounds it may take
export interface ProjectStartOptions {
  max_cost: number;
  max_rounds?: number;
  max_stalled_rounds?: number;
}
