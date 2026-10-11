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

export interface ModelChoice {
  id: string;
  provider: string;
  ready: boolean;
}

export interface Models {
  default: string;
  models: ModelChoice[];
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
