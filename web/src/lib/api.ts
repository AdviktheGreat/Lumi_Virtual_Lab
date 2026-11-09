import { exportNameOf, type ExportFormat } from "./export";
import { fileUrl } from "./files";
import type { PickedFolder } from "./skill-folder";
import type {
  Attachment,
  ChatFiles,
  ChatInfo,
  ChatSummary,
  Campaign,
  CampaignChange,
  DataLake,
  Health,
  Job,
  KeyStatuses,
  LabChoice,
  LibraryScientist,
  LimitsChange,
  McpCatalogServer,
  McpChange,
  McpCheck,
  McpEntry,
  McpServer,
  Models,
  NewCampaign,
  NewChat,
  NewPaperAgent,
  NewPaperRun,
  OpenRouterList,
  Own,
  OwnPreview,
  SkillLibrary,
  SkillPreview,
  Skills,
  SkillsFrom,
  SkillsPutIn,
  PaperAgent,
  PaperAgentChange,
  PaperAgentFetchOptions,
  PaperAgentPassage,
  PaperAgentReadOptions,
  PaperAgentReading,
  PaperAgentRepository,
  PaperAgentsList,
  PaperFunction,
  PaperFunctionsOptions,
  PaperReadOptions,
  PaperRun,
  PapersList,
  Scientist,
  Settings,
  SettingsChange,
  SetupStatus,
  ToolInfo,
} from "./types";

// What the server's error says: its code is a word to act on, its message is for a person, and the rest is
// whatever else the code carries, such as the keys that are missing
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

// Not the server's error: the server could not be reached at all
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super("The server cannot be reached. Is it still running?", { cause });
    this.name = "NetworkError";
  }
}

function errorFrom(status: number, body: unknown): ApiError {
  if (typeof body === "object" && body !== null && "error" in body) {
    const { code, message, ...details } = (body as { error: Record<string, unknown> }).error;
    if (typeof code === "string" && typeof message === "string") {
      return new ApiError(status, code, message, details);
    }
  }

  return new ApiError(status, "error", `The server answered ${status}`);
}

async function request<T>(method: string, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      signal,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new NetworkError(error);
  }
  // What has no body to read, as the answer to a removal, is read as nothing
  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    parsed = undefined;
  }
  if (!response.ok) {
    throw errorFrom(response.status, parsed);
  }

  return parsed as T;
}

function isAttachment(value: unknown): value is Attachment {
  if (typeof value !== "object" || value === null) return false;
  const { name, path, size } = value as Record<string, unknown>;

  return typeof name === "string" && typeof path === "string" && typeof size === "number";
}

interface UploadOptions {
  // Called with how much of the file has been sent, from 0 to 1
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

// Sends a file, or a form with files in it, as the body of a request, which is read by hand rather than with fetch, since
// fetch cannot say how much of a body has gone. What the server answers with is taken by `accept`, which gives back what it
// is, or undefined if it is not what was to be answered with, which `unclear` then says.
function sendFile<T>(
  address: string,
  body: File | FormData,
  accept: (parsed: unknown) => T | undefined,
  unclear: string,
  { onProgress, signal }: UploadOptions = {},
): Promise<T> {
  return new Promise((resolve, reject) => {
    const aborted = () => new DOMException("Aborted", "AbortError");
    if (signal?.aborted) {
      reject(aborted());

      return;
    }
    const upload = new XMLHttpRequest();
    upload.open("POST", address);
    upload.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress?.(Math.min(1, event.loaded / event.total));
    };
    upload.onload = () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(upload.responseText);
      } catch {
        parsed = undefined;
      }
      if (upload.status < 200 || upload.status >= 300) {
        reject(errorFrom(upload.status, parsed));
      } else {
        const accepted = accept(parsed);
        if (accepted !== undefined) resolve(accepted);
        else reject(new ApiError(upload.status, "error", unclear));
      }
    };
    // The browser says nothing of why, and a folder, which has nothing to read, fails the same way as a lost connection
    upload.onerror = () =>
      reject(
        new Error(
          body instanceof FormData
            ? "The folder could not be sent. The server may have stopped, or a file in it may have been changed or moved."
            : "The file could not be sent. It may be a folder, or the server may have stopped.",
        ),
      );
    upload.onabort = () => reject(aborted());
    signal?.addEventListener("abort", () => upload.abort(), { once: true });
    upload.send(body);
  });
}

function uploadFile(chatId: string, file: File, options: UploadOptions = {}): Promise<Attachment> {
  return sendFile(
    `/api/chats/${encodeURIComponent(chatId)}/uploads?name=${encodeURIComponent(file.name)}`,
    file,
    (parsed) => (isAttachment(parsed) ? parsed : undefined),
    "The server did not say where it kept the file",
    options,
  );
}

function isSkillsPutIn(value: unknown): value is SkillsPutIn {
  if (typeof value !== "object" || value === null) return false;
  const { skills, installed, skipped } = value as Record<string, unknown>;

  return Array.isArray(skills) && Array.isArray(installed) && Array.isArray(skipped);
}

// Puts in the skills of a folder that was given to the page, each file sent with where it is in the folder
function uploadSkillFolder(folder: PickedFolder, options: UploadOptions = {}): Promise<SkillsPutIn> {
  const form = new FormData();
  form.append("folder", folder.name);
  // The server pairs each path with the file that comes at the same place, so they are sent as two lists in one order
  for (const { path } of folder.files) form.append("paths", path);
  for (const { path, file } of folder.files) form.append("files", file, path.split("/").pop() ?? file.name);

  return sendFile(
    "/api/skills/upload",
    form,
    (parsed) => (isSkillsPutIn(parsed) ? parsed : undefined),
    "The server did not say what it put in",
    options,
  );
}

function isOwn(value: unknown): value is Own {
  if (typeof value !== "object" || value === null) return false;
  const { data, software, max_upload_bytes: limit } = value as Record<string, unknown>;

  return Array.isArray(data) && Array.isArray(software) && typeof limit === "number";
}

// Gives the lab a file, kept by the server under the name it has, and what the person gave is given back as it now is
function uploadOwnData(file: File, description: string, options: UploadOptions = {}): Promise<Own> {
  return sendFile(
    `/api/own/data/files?name=${encodeURIComponent(file.name)}&description=${encodeURIComponent(description)}`,
    file,
    (parsed) => (isOwn(parsed) ? parsed : undefined),
    "The server did not say what it kept",
    options,
  );
}

function isPaperRun(value: unknown): value is PaperRun {
  if (typeof value !== "object" || value === null) return false;
  const { id, results, functions } = value as Record<string, unknown>;

  return typeof id === "string" && Array.isArray(results) && Array.isArray(functions);
}

// Gives a run a paper, kept by the server under the name it has, and the run is given back as it now is
function uploadPaper(run: string, file: File, options: UploadOptions = {}): Promise<PaperRun> {
  return sendFile(
    `/api/papers/runs/${encodeURIComponent(run)}/files?name=${encodeURIComponent(file.name)}`,
    file,
    (parsed) => (isPaperRun(parsed) ? parsed : undefined),
    "The server did not say what the run holds",
    options,
  );
}

function isPaperAgent(value: unknown): value is PaperAgent {
  if (typeof value !== "object" || value === null) return false;
  const { id, paper, steps } = value as Record<string, unknown>;

  return typeof id === "string" && typeof paper === "object" && paper !== null && typeof steps === "object" && steps !== null;
}

// Gives an agent its paper, kept by the server under the name it has, and the agent is given back as it now is
function uploadAgentPaper(agent: string, file: File, options: UploadOptions = {}): Promise<PaperAgent> {
  return sendFile(
    `/api/paperagents/${encodeURIComponent(agent)}/paper?name=${encodeURIComponent(file.name)}`,
    file,
    (parsed) => (isPaperAgent(parsed) ? parsed : undefined),
    "The server did not say what the agent holds",
    options,
  );
}

// What a request that is not for JSON is answered with, once it is known to have gone well: what went wrong is told in
// the server's own shape, which is read, and what went well is left for the caller to read
async function fetchBody(address: string, signal?: AbortSignal): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(address, { signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError(error);
  }
  if (!response.ok) {
    let parsed: unknown;
    try {
      parsed = await response.json();
    } catch {
      parsed = undefined;
    }
    throw errorFrom(response.status, parsed);
  }

  return response;
}

export interface FileText {
  text: string;
  // Whether the file goes on after what was read
  truncated: boolean;
  // Whether it is not text, which is so for a file that has a null byte in what was read
  binary: boolean;
}

// The start of a file, as text. Only as much as the limit is taken from the server, whatever the size of the file.
async function readFileText(chatId: string, path: string, limit: number, signal?: AbortSignal): Promise<FileText> {
  const response = await fetchBody(fileUrl(chatId, path), signal);
  const reader = response.body?.getReader();
  if (!reader) return { text: await response.text(), truncated: false, binary: false };
  const chunks: Uint8Array[] = [];
  let length = 0;
  let truncated = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      length += value.length;
      if (length > limit) {
        truncated = true;
        void reader.cancel();
        break;
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError(error);
  }
  const bytes = new Uint8Array(Math.min(length, limit));
  let at = 0;
  for (const chunk of chunks) {
    const room = bytes.length - at;
    bytes.set(chunk.length > room ? chunk.subarray(0, room) : chunk, at);
    at += Math.min(chunk.length, room);
  }
  // A character that the limit cut in two is dropped by the decoder, which stops reading at what is not whole
  const text = new TextDecoder("utf-8", { fatal: false }).decode(bytes, { stream: truncated });

  return { text, truncated, binary: text.includes("\0") };
}

export interface ExportedChat {
  file: Blob;
  // What to save it as
  name: string;
}

// A conversation as a document, whole, which is made for it by the server. It is fetched here, and not by a link that
// downloads, so that what the server says when it cannot make it is told, and not saved as the file.
async function exportChat(id: string, format: ExportFormat, signal?: AbortSignal): Promise<ExportedChat> {
  const response = await fetchBody(`/api/chats/${encodeURIComponent(id)}/export?format=${format}`, signal);
  let file: Blob;
  try {
    file = await response.blob();
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new NetworkError(error);
  }

  return { file, name: exportNameOf(response.headers.get("Content-Disposition"), format) };
}

export const api = {
  health: (signal?: AbortSignal) => request<Health>("GET", "/health", undefined, signal),
  settings: (signal?: AbortSignal) => request<Settings>("GET", "/settings", undefined, signal),
  // Only what is given is changed, and the settings are given back as they now are
  changeSettings: (changes: SettingsChange) => request<Settings>("PATCH", "/settings", changes),
  models: (signal?: AbortSignal) => request<Models>("GET", "/models", undefined, signal),
  // Every model OpenRouter serves that a conversation can use, which the server reads from OpenRouter when it is asked
  openRouterModels: (signal?: AbortSignal) => request<OpenRouterList>("GET", "/models/openrouter", undefined, signal),
  keys: (signal?: AbortSignal) => request<KeyStatuses>("GET", "/keys", undefined, signal),
  // A key is kept in the server's keychain, or by the server until it stops, and is never given back: what comes back is
  // which are set. False for remember keeps it until the server stops alone; undefined is left out of the body, which is as the keychain allows.
  setKey: (name: string, value: string, remember?: boolean) =>
    request<KeyStatuses>("PUT", `/keys/${encodeURIComponent(name)}`, { value, remember }),
  removeKey: (name: string) => request<KeyStatuses>("DELETE", `/keys/${encodeURIComponent(name)}`),
  scientists: async (signal?: AbortSignal) =>
    (await request<{ scientists: LibraryScientist[] }>("GET", "/scientists", undefined, signal)).scientists,
  // One with the title of another takes its place, and the library is given back as it now is
  saveScientist: async (scientist: Scientist) =>
    (await request<{ scientists: LibraryScientist[] }>("PUT", "/scientists", scientist)).scientists,
  removeScientist: async (title: string) =>
    (await request<{ scientists: LibraryScientist[] }>("DELETE", `/scientists/${encodeURIComponent(title)}`)).scientists,
  tools: async (signal?: AbortSignal) => (await request<{ tools: ToolInfo[] }>("GET", "/tools", undefined, signal)).tools,
  // The tools a new conversation is not given, which is all that is turned off, and the tools are given back as they now are
  saveTools: async (disabled: string[]) => (await request<{ tools: ToolInfo[] }>("PUT", "/tools", { disabled })).tools,
  // The MCP servers: the presets, whether or not they are set up, and then those the person described
  mcp: async (signal?: AbortSignal) => (await request<{ servers: McpServer[] }>("GET", "/mcp", undefined, signal)).servers,
  // The servers others run that can be added with a click, and the adding of one, which gives the servers back as they now are
  mcpCatalog: async (signal?: AbortSignal) =>
    (await request<{ servers: McpCatalogServer[] }>("GET", "/mcp/catalog", undefined, signal)).servers,
  addCatalogServer: async (name: string) =>
    (await request<{ servers: McpServer[] }>("POST", `/mcp/catalog/${encodeURIComponent(name)}`)).servers,
  // Turns a server on or off, or chooses how a preset is signed in to, and gives the servers back as they now are
  changeMcpServer: async (name: string, change: McpChange) =>
    (await request<{ servers: McpServer[] }>("PATCH", `/mcp/servers/${encodeURIComponent(name)}`, change)).servers,
  // Sets a server up in full, in place of any it had under the name
  saveMcpServer: async (name: string, entry: McpEntry) =>
    (await request<{ servers: McpServer[] }>("PUT", `/mcp/servers/${encodeURIComponent(name)}`, { entry })).servers,
  removeMcpServer: async (name: string) =>
    (await request<{ servers: McpServer[] }>("DELETE", `/mcp/servers/${encodeURIComponent(name)}`)).servers,
  checkMcpServer: (name: string) => request<McpCheck>("POST", `/mcp/servers/${encodeURIComponent(name)}/check`),
  signOutMcpServer: async (name: string) =>
    (await request<{ servers: McpServer[] }>("DELETE", `/mcp/servers/${encodeURIComponent(name)}/sign-in`)).servers,
  // Docker, the images, the data lake, the jobs, and what is left to do. Asking is not quick, since Docker is asked.
  setup: (signal?: AbortSignal) => request<SetupStatus>("GET", "/setup", undefined, signal),
  // Starts building a stage of the image, which goes on as a job
  buildImage: (stage: string) => request<Job>("POST", `/setup/images/${encodeURIComponent(stage)}`),
  dataLake: (signal?: AbortSignal) => request<DataLake>("GET", "/setup/data-lake", undefined, signal),
  // Starts fetching the files named, or all of them if none are named, which goes on as a job
  fetchDataLake: (names?: string[]) => request<Job>("POST", "/setup/data-lake", names === undefined ? undefined : { names }),
  jobs: async (signal?: AbortSignal) => (await request<{ jobs: Job[] }>("GET", "/setup/jobs", undefined, signal)).jobs,
  // A job with what it printed from the line numbered, counting from 0
  job: (id: string, logFrom: number, signal?: AbortSignal) =>
    request<Job>("GET", `/setup/jobs/${encodeURIComponent(id)}?log_from=${logFrom}`, undefined, signal),
  stopJob: (id: string) => request<Job>("POST", `/setup/jobs/${encodeURIComponent(id)}/stop`),
  // The data and software the person gave the lab to use in every conversation that runs code. Each change gives back
  // all of it as it now is.
  own: (signal?: AbortSignal) => request<Own>("GET", "/own", undefined, signal),
  uploadOwnData,
  // Points to a file or folder where it is on the server's machine, by its full path, which is left there
  addOwnPath: (path: string, description: string) => request<Own>("POST", "/own/data/paths", { path, description }),
  describeOwnData: (name: string, description: string) =>
    request<Own>("PATCH", `/own/data/${encodeURIComponent(name)}`, { description }),
  // A file that was uploaded is deleted, and what was pointed to is left where it is
  removeOwnData: (name: string) => request<Own>("DELETE", `/own/data/${encodeURIComponent(name)}`),
  previewOwnData: (name: string, signal?: AbortSignal) =>
    request<OwnPreview>("GET", `/own/data/${encodeURIComponent(name)}/preview`, undefined, signal),
  // Some software and what it is for, in place of any with the name
  saveOwnSoftware: (name: string, description: string) => request<Own>("PUT", "/own/software", { name, description }),
  removeOwnSoftware: (name: string) => request<Own>("DELETE", `/own/software/${encodeURIComponent(name)}`),
  // The skills there are, which a new conversation is given unless they are turned off. A change gives back all of them.
  skills: (signal?: AbortSignal) => request<Skills>("GET", "/skills", undefined, signal),
  // The names of the skills a new conversation is not given
  saveSkills: (disabled: string[]) => request<Skills>("PUT", "/skills", { disabled }),
  // Puts in copies of the skills of a Git repository, or of a folder on the server's machine, which can take a while
  putInSkills: (from: SkillsFrom) => request<SkillsPutIn>("POST", "/skills/install", from),
  // Puts in the skills of a folder that a person chose or dropped on the page, as it is on their machine
  uploadSkillFolder,
  previewSkill: (name: string, signal?: AbortSignal) =>
    request<SkillPreview>("GET", `/skills/${encodeURIComponent(name)}`, undefined, signal),
  // The library of skills that comes with the lab, which are not used until they are put in
  skillLibrary: (signal?: AbortSignal) => request<SkillLibrary>("GET", "/skill-library", undefined, signal),
  putInLibrarySkills: (names: string[]) => request<SkillsPutIn>("POST", "/skill-library/install", { names }),
  previewLibrarySkill: (name: string, signal?: AbortSignal) =>
    request<SkillPreview>("GET", `/skill-library/${encodeURIComponent(name)}`, undefined, signal),
  // Only a skill in the lab's own folder is deleted
  removeSkill: (name: string) => request<Skills>("DELETE", `/skills/${encodeURIComponent(name)}`),
  // The runs that read papers, and what a new one is asked for
  papers: (signal?: AbortSignal) => request<PapersList>("GET", "/papers", undefined, signal),
  makePaperRun: (run: NewPaperRun) => request<PaperRun>("POST", "/papers/runs", run),
  paperRun: (id: string, signal?: AbortSignal) =>
    request<PaperRun>("GET", `/papers/runs/${encodeURIComponent(id)}`, undefined, signal),
  // Deletes a run with what was uploaded to it and what was found, and gives back the runs that are left
  deletePaperRun: (id: string) => request<PapersList>("DELETE", `/papers/runs/${encodeURIComponent(id)}`),
  uploadPaper,
  removePaper: (id: string, name: string) =>
    request<PaperRun>("DELETE", `/papers/runs/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`),
  // Starts reading the papers that are not read, or writing functions for what they share, which goes on as a job
  readPapers: (id: string, options: PaperReadOptions) =>
    request<Job>("POST", `/papers/runs/${encodeURIComponent(id)}/read`, options),
  writeFunctions: (id: string, options: PaperFunctionsOptions) =>
    request<Job>("POST", `/papers/runs/${encodeURIComponent(id)}/functions`, options),
  paperFunction: (id: string, name: string, signal?: AbortSignal) =>
    request<PaperFunction>(
      "GET",
      `/papers/runs/${encodeURIComponent(id)}/functions/${encodeURIComponent(name)}`,
      undefined,
      signal,
    ),
  removeFunction: (id: string, name: string) =>
    request<PaperRun>("DELETE", `/papers/runs/${encodeURIComponent(id)}/functions/${encodeURIComponent(name)}`),
  // Whether the functions of a run are given to the conversations that are made from now on
  giveFunctions: (id: string, given: boolean) => request<PaperRun>("PATCH", `/papers/runs/${encodeURIComponent(id)}`, { given }),
  // The PaperAgents, and what a new one is asked for
  paperAgents: (signal?: AbortSignal) => request<PaperAgentsList>("GET", "/paperagents", undefined, signal),
  makePaperAgent: (agent: NewPaperAgent) => request<PaperAgent>("POST", "/paperagents", agent),
  paperAgent: (id: string, signal?: AbortSignal) =>
    request<PaperAgent>("GET", `/paperagents/${encodeURIComponent(id)}`, undefined, signal),
  changePaperAgent: (id: string, change: PaperAgentChange) =>
    request<PaperAgent>("PATCH", `/paperagents/${encodeURIComponent(id)}`, change),
  // Deletes an agent with the paper uploaded to it, and gives back the agents that are left
  deletePaperAgent: (id: string) => request<PaperAgentsList>("DELETE", `/paperagents/${encodeURIComponent(id)}`),
  uploadAgentPaper,
  removeAgentPaper: (id: string) => request<PaperAgent>("DELETE", `/paperagents/${encodeURIComponent(id)}/paper`),
  // What has been read of an agent's paper, starting to read it, which goes on as a job, taking away what was read, and
  // the paper's words at a place in it
  paperAgentReading: (id: string, signal?: AbortSignal) =>
    request<PaperAgentReading>("GET", `/paperagents/${encodeURIComponent(id)}/reading`, undefined, signal),
  readPaperAgent: (id: string, options: PaperAgentReadOptions) =>
    request<Job>("POST", `/paperagents/${encodeURIComponent(id)}/reading`, options),
  clearPaperAgentReading: (id: string) => request<PaperAgentReading>("DELETE", `/paperagents/${encodeURIComponent(id)}/reading`),
  // What there is of an agent's code, fetching it, which goes on as a job, and taking away what was fetched
  paperAgentRepository: (id: string, signal?: AbortSignal) =>
    request<PaperAgentRepository>("GET", `/paperagents/${encodeURIComponent(id)}/repository`, undefined, signal),
  fetchPaperAgentRepository: (id: string, options: PaperAgentFetchOptions) =>
    request<Job>("POST", `/paperagents/${encodeURIComponent(id)}/repository`, options),
  clearPaperAgentRepository: (id: string) =>
    request<PaperAgentRepository>("DELETE", `/paperagents/${encodeURIComponent(id)}/repository`),
  paperAgentPassage: (id: string, start: number, end: number, signal?: AbortSignal) =>
    request<PaperAgentPassage>("GET", `/paperagents/${encodeURIComponent(id)}/passage?start=${start}&end=${end}`, undefined, signal),
  chats: async (signal?: AbortSignal) => (await request<{ chats: ChatSummary[] }>("GET", "/chats", undefined, signal)).chats,
  chat: (id: string, signal?: AbortSignal) => request<ChatInfo>("GET", `/chats/${encodeURIComponent(id)}`, undefined, signal),
  createChat: (chat: NewChat = {}) => request<ChatInfo>("POST", "/chats", chat),
  // Gives it another title, which the server tidies, and tells of to whoever follows the conversation
  renameChat: (id: string, title: string) => request<ChatInfo>("PATCH", `/chats/${encodeURIComponent(id)}`, { title }),
  // The conversation goes on from where it is with another model, for the lead and for the team
  switchModel: (id: string, model: string) =>
    request<ChatInfo>("PUT", `/chats/${encodeURIComponent(id)}/model`, { model }),
  // What the conversation may spend and what the lead may ask of the team, changed while it goes on, even while it works
  setLimits: (id: string, changes: LimitsChange) =>
    request<ChatInfo>("PUT", `/chats/${encodeURIComponent(id)}/limits`, changes),
  deleteChat: (id: string) => request<void>("DELETE", `/chats/${encodeURIComponent(id)}`),
  campaigns: async (signal?: AbortSignal) =>
    (await request<{ campaigns: Campaign[] }>("GET", "/campaigns", undefined, signal)).campaigns,
  makeCampaign: (campaign: NewCampaign) => request<Campaign>("POST", "/campaigns", campaign),
  changeCampaign: (id: string, changes: CampaignChange) =>
    request<Campaign>("PATCH", `/campaigns/${encodeURIComponent(id)}`, changes),
  // Its programs are kept, and are part of no campaign from then on
  deleteCampaign: (id: string) => request<void>("DELETE", `/campaigns/${encodeURIComponent(id)}`),
  // Makes the program one of a campaign, in place of the one it was, or with null one of none, even while it works
  setCampaign: (id: string, campaign: string | null) =>
    request<{ id: string; campaign: string | null }>("PUT", `/chats/${encodeURIComponent(id)}/campaign`, { campaign }),
  // Attachments are named as the server named them when it was sent the files. With replaceLast the message takes the
  // place of the last one, which is taken out of the conversation, to send it again or changed. With a directive the
  // message is given with a command, such as "ask", which says how the lead is to answer it, and with /lab, who is to work
  // on it. With a skill, one of the conversation's, it is given with that instead, and the lead is to read it first.
  send: (
    id: string,
    text: string,
    attachments: string[] = [],
    replaceLast = false,
    directive?: string | null,
    lab?: LabChoice | null,
    skill?: string | null,
  ) =>
    request<{ turn: number; state: string }>("POST", `/chats/${encodeURIComponent(id)}/messages`, {
      text,
      attachments,
      ...(replaceLast ? { replace_last: true } : {}),
      ...(directive ? { directive } : {}),
      ...(lab ? { lab } : {}),
      ...(skill ? { skill } : {}),
    }),
  // What steers a turn that is running is accepted or not: a turn that has ended meanwhile has nothing to steer
  note: (id: string, text: string) =>
    request<{ accepted: boolean }>("POST", `/chats/${encodeURIComponent(id)}/note`, { text }),
  pause: (id: string) => request<{ accepted: boolean }>("POST", `/chats/${encodeURIComponent(id)}/pause`),
  resume: (id: string) => request<{ accepted: boolean }>("POST", `/chats/${encodeURIComponent(id)}/resume`),
  stop: (id: string) => request<{ accepted: boolean }>("POST", `/chats/${encodeURIComponent(id)}/stop`),
  // Whether a call that waits for the researcher's approval is made. The answer says how it ended, which the
  // conversation tells of as well; one that was answered already, or withdrawn, is refused.
  approve: (id: string, requestId: string, allow: boolean) =>
    request<{ state: string }>("POST", `/chats/${encodeURIComponent(id)}/approvals/${encodeURIComponent(requestId)}`, { allow }),
  // What a server asked: the form's fields by name, {} for what was answered at a web page, or null to decline
  answer: (id: string, requestId: string, answer: Record<string, unknown> | null) =>
    request<{ state: string }>("POST", `/chats/${encodeURIComponent(id)}/questions/${encodeURIComponent(requestId)}`, { answer }),
  upload: uploadFile,
  // What the conversation made or was given
  files: (id: string, signal?: AbortSignal) => request<ChatFiles>("GET", `/chats/${encodeURIComponent(id)}/files`, undefined, signal),
  fileText: readFileText,
  exportChat,
};
