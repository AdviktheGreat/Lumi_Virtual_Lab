import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, NetworkError } from "./api";

function answer(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status });
}

function stub(response: Response | Error) {
  const fetch = vi.fn(async () => {
    if (response instanceof Error) throw response;

    return response;
  });
  vi.stubGlobal("fetch", fetch);

  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("the API", () => {
  it("asks for what it wants from the address under /api, and reads the answer", async () => {
    const fetch = stub(answer({ status: "ok", version: "1.2.0" }));

    expect(await api.health()).toEqual({ status: "ok", version: "1.2.0" });
    expect(fetch).toHaveBeenCalledWith("/api/health", expect.objectContaining({ method: "GET", headers: undefined, body: undefined }));
  });

  it("lists the conversations from what the server wraps them in", async () => {
    stub(answer({ chats: [{ id: "a" }, { id: "b" }] }));

    expect((await api.chats()).map((chat) => chat.id)).toEqual(["a", "b"]);
  });

  it("sends what it is given as JSON", async () => {
    const fetch = stub(answer({ turn: 1, state: "running" }, 202));

    await api.send("a b", "Hello there");

    expect(fetch).toHaveBeenCalledWith(
      "/api/chats/a%20b/messages",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "Hello there", attachments: [] }),
      }),
    );
  });

  it("sends the names of the files that go with a message", async () => {
    const fetch = stub(answer({ turn: 1, state: "running" }, 202));

    await api.send("a", "Look at these", ["data.csv", "data (2).csv"]);

    const [, options] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(options.body).toBe(JSON.stringify({ text: "Look at these", attachments: ["data.csv", "data (2).csv"] }));
  });

  it("asks for a message to take the place of the last one only when it is meant to", async () => {
    const fetch = stub(answer({ turn: 1, state: "running" }, 202));

    await api.send("a", "Again", ["data.csv"], true);

    const [, options] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(options.body).toBe(JSON.stringify({ text: "Again", attachments: ["data.csv"], replace_last: true }));
  });

  it("gives a message with a command only when it has one", async () => {
    const fetch = stub(answer({ turn: 1, state: "running" }, 202));

    await api.send("a", "Why?", [], false, "ask");
    await api.send("a", "Why?", [], true, null);
    await api.send("a", "", [], true, "review");
    await api.send("a", "Design", [], false, "lab", { mode: "individual", members: ["Immunologist"], rounds: 1, questions: [] });

    const bodies = (fetch.mock.calls as unknown as [string, RequestInit][]).map(([, options]) => options.body);
    expect(bodies).toEqual([
      JSON.stringify({ text: "Why?", attachments: [], directive: "ask" }),
      JSON.stringify({ text: "Why?", attachments: [], replace_last: true }),
      JSON.stringify({ text: "", attachments: [], replace_last: true, directive: "review" }),
      JSON.stringify({
        text: "Design",
        attachments: [],
        directive: "lab",
        lab: { mode: "individual", members: ["Immunologist"], rounds: 1, questions: [] },
      }),
    ]);
  });

  it("steers a turn with a note, a pause, a resume, or a stop, and says whether it was taken", async () => {
    // A response can be read once, so each request is given its own
    const fetch = vi.fn(async () => answer({ accepted: true }));
    vi.stubGlobal("fetch", fetch);

    expect(await api.note("a b", "Look at B cells")).toEqual({ accepted: true });
    expect(await api.pause("a b")).toEqual({ accepted: true });
    expect(await api.resume("a b")).toEqual({ accepted: true });
    expect(await api.stop("a b")).toEqual({ accepted: true });

    const calls = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([address, options]) => [address, options.method, options.body])).toEqual([
      ["/api/chats/a%20b/note", "POST", JSON.stringify({ text: "Look at B cells" })],
      ["/api/chats/a%20b/pause", "POST", undefined],
      ["/api/chats/a%20b/resume", "POST", undefined],
      ["/api/chats/a%20b/stop", "POST", undefined],
    ]);
  });

  it("makes a conversation of what the settings say unless it is told", async () => {
    const fetch = stub(answer({ id: "new" }, 201));

    await api.createChat();
    await api.createChat({ model: "gpt-5.2" });

    const bodies = fetch.mock.calls.map((call) => (call as unknown as [string, RequestInit])[1].body);
    expect(bodies).toEqual(["{}", JSON.stringify({ model: "gpt-5.2" })]);
  });

  it("renames a conversation by what the server's PATCH is given, and gives back the conversation", async () => {
    const fetch = stub(answer({ id: "a b", title: "Kept" }));

    expect(await api.renameChat("a b", "Kept")).toMatchObject({ title: "Kept" });
    expect(fetch).toHaveBeenCalledWith("/api/chats/a%20b", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ title: "Kept" }) }));
  });

  it("changes the settings by the PATCH it is given only what changes, and gives back the settings", async () => {
    const fetch = stub(answer({ model: "gpt-5.2", max_cost: 5 }));

    expect(await api.changeSettings({ max_cost: 5 })).toMatchObject({ max_cost: 5 });
    expect(fetch).toHaveBeenCalledWith(
      "/api/settings",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ max_cost: 5 }) }),
    );
  });

  it("gives a key to the server as the body of a PUT, and names it in the address and not in the body", async () => {
    const fetch = stub(answer({ settable: ["OPENAI_API_KEY"], providers: [] }));

    await api.setKey("OPENAI_API_KEY", "sk-secret");

    expect(fetch).toHaveBeenCalledWith(
      "/api/keys/OPENAI_API_KEY",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ value: "sk-secret" }) }),
    );
  });

  it("says whether a key is to be kept in the keychain only when it is said, and then in the body", async () => {
    const fetch = stub(answer({ settable: [], providers: [] }));

    await api.setKey("OPENAI_API_KEY", "sk-secret", false);
    await api.setKey("OPENAI_API_KEY", "sk-secret", true);

    const bodies = (fetch.mock.calls as unknown as [string, RequestInit][]).map(([, init]) => init.body);
    expect(bodies).toEqual([
      JSON.stringify({ value: "sk-secret", remember: false }),
      JSON.stringify({ value: "sk-secret", remember: true }),
    ]);
  });

  it("names a key in the address as it is, whatever is in its name", async () => {
    const fetch = stub(answer({ settable: [], providers: [] }));

    await api.setKey("MY KEY/2", "sk-secret");
    await api.removeKey("MY KEY/2");

    const addresses = (fetch.mock.calls as unknown as [string, RequestInit][]).map(([address]) => address);
    expect(addresses).toEqual(["/api/keys/MY%20KEY%2F2", "/api/keys/MY%20KEY%2F2"]);
  });

  it("takes a key away by naming it, and reads which keys are set from what comes back", async () => {
    const fetch = stub(answer({ settable: ["OPENAI_API_KEY"], providers: [{ provider: "OpenAI", variables: ["OPENAI_API_KEY"], missing: [], ready: true }] }));

    const statuses = await api.removeKey("OPENAI_API_KEY");

    expect(statuses.providers[0].ready).toBe(true);
    expect(fetch).toHaveBeenCalledWith("/api/keys/OPENAI_API_KEY", expect.objectContaining({ method: "DELETE", body: undefined }));
  });

  it("lists the scientists from what the server wraps them in, and takes the library from what a change gives back", async () => {
    const scientist = { title: "Chemist", expertise: "Bonds", goal: "Make", role: "Bench", builtin: false };
    const fetch = vi.fn(async () => answer({ scientists: [scientist] }));
    vi.stubGlobal("fetch", fetch);

    expect(await api.scientists()).toEqual([scientist]);
    expect(await api.saveScientist({ title: "Chemist", expertise: "Bonds", goal: "Make", role: "Bench" })).toEqual([scientist]);
    expect(await api.removeScientist("Chemist / Physicist")).toEqual([scientist]);

    const calls = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([address, options]) => [address, options.method])).toEqual([
      ["/api/scientists", "GET"],
      ["/api/scientists", "PUT"],
      ["/api/scientists/Chemist%20%2F%20Physicist", "DELETE"],
    ]);
    expect(calls[1][1].body).toBe(JSON.stringify({ title: "Chemist", expertise: "Bonds", goal: "Make", role: "Bench" }));
  });

  it("lists the tools from what the server wraps them in, and takes them from what a change gives back", async () => {
    const tool = { name: "pubmed_search", group: "Literature", summary: "Find", needs_code: false, enabled: false };
    const fetch = vi.fn(async () => answer({ tools: [tool] }));
    vi.stubGlobal("fetch", fetch);

    expect(await api.tools()).toEqual([tool]);
    expect(await api.saveTools(["pubmed_search"])).toEqual([tool]);

    const calls = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([address, options]) => [address, options.method])).toEqual([
      ["/api/tools", "GET"],
      ["/api/tools", "PUT"],
    ]);
    expect(calls[1][1].body).toBe(JSON.stringify({ disabled: ["pubmed_search"] }));
  });

  it("asks for what was given to the lab, and takes what it is as it now is from what each change gives back", async () => {
    const given = { data: [], software: [{ name: "Cell Ranger", description: "Counts" }], max_upload_bytes: 20480 };
    const fetch = vi.fn(async () => answer(given));
    vi.stubGlobal("fetch", fetch);

    expect(await api.own()).toEqual(given);
    expect(await api.addOwnPath("/data/my counts.csv", "Counts")).toEqual(given);
    expect(await api.describeOwnData("my counts.csv", "Raw counts")).toEqual(given);
    expect(await api.removeOwnData("my counts.csv")).toEqual(given);
    expect(await api.saveOwnSoftware("Cell Ranger", "Counts")).toEqual(given);
    expect(await api.removeOwnSoftware("Cell Ranger")).toEqual(given);

    const calls = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([address, options]) => [address, options.method, options.body])).toEqual([
      ["/api/own", "GET", undefined],
      ["/api/own/data/paths", "POST", JSON.stringify({ path: "/data/my counts.csv", description: "Counts" })],
      ["/api/own/data/my%20counts.csv", "PATCH", JSON.stringify({ description: "Raw counts" })],
      ["/api/own/data/my%20counts.csv", "DELETE", undefined],
      ["/api/own/software", "PUT", JSON.stringify({ name: "Cell Ranger", description: "Counts" })],
      ["/api/own/software/Cell%20Ranger", "DELETE", undefined],
    ]);
  });

  it("names data in the address as it is, whatever is in its name", async () => {
    const fetch = vi.fn(async () => answer({ kind: "text", lines: [], truncated: false }));
    vi.stubGlobal("fetch", fetch);

    await api.previewOwnData("a/b #1?.csv");

    expect(fetch).toHaveBeenCalledWith(
      "/api/own/data/a%2Fb%20%231%3F.csv/preview",
      expect.objectContaining({ method: "GET", body: undefined }),
    );
  });

  it("asks for the setup, and for the data lake, with nothing in the request", async () => {
    const fetch = vi.fn(async () => answer({ steps: [], files: [] }));
    vi.stubGlobal("fetch", fetch);

    await api.setup();
    await api.dataLake();

    const calls = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([address, options]) => [address, options.method, options.body])).toEqual([
      ["/api/setup", "GET", undefined],
      ["/api/setup/data-lake", "GET", undefined],
    ]);
  });

  it("starts a build by the stage in the address, and says nothing else", async () => {
    const fetch = stub(answer({ id: "abc", kind: "image" }));

    expect(await api.buildImage("base")).toMatchObject({ id: "abc" });
    expect(fetch).toHaveBeenCalledWith("/api/setup/images/base", expect.objectContaining({ method: "POST", body: undefined }));

    await api.buildImage("a/b c");
    expect(fetch).toHaveBeenLastCalledWith("/api/setup/images/a%2Fb%20c", expect.objectContaining({ method: "POST" }));
  });

  it("starts the fetching of all the data lake with no names, and of some with the names", async () => {
    const fetch = vi.fn(async () => answer({ id: "abc" }));
    vi.stubGlobal("fetch", fetch);

    await api.fetchDataLake();
    await api.fetchDataLake(["a.csv", "b c.tsv"]);

    const calls = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([address, options]) => [address, options.method, options.body])).toEqual([
      ["/api/setup/data-lake", "POST", undefined],
      ["/api/setup/data-lake", "POST", JSON.stringify({ names: ["a.csv", "b c.tsv"] })],
    ]);
  });

  it("lists the jobs from what the server wraps them in, and asks for one with what it printed from a line", async () => {
    const fetch = vi.fn(async (address: string) =>
      answer(address === "/api/setup/jobs" ? { jobs: [{ id: "abc" }, { id: "def" }] } : { id: "abc", log: { from: 4, lines: [] } }),
    );
    vi.stubGlobal("fetch", fetch);

    expect(await api.jobs()).toEqual([{ id: "abc" }, { id: "def" }]);
    expect(await api.job("a/b c", 4)).toMatchObject({ log: { from: 4 } });

    const addresses = (fetch.mock.calls as unknown as [string, RequestInit][]).map(([address]) => address);
    expect(addresses).toEqual(["/api/setup/jobs", "/api/setup/jobs/a%2Fb%20c?log_from=4"]);
  });

  it("asks a job to stop by its id", async () => {
    const fetch = stub(answer({ id: "a b", state: "stopping" }));

    expect(await api.stopJob("a b")).toMatchObject({ state: "stopping" });
    expect(fetch).toHaveBeenCalledWith("/api/setup/jobs/a%20b/stop", expect.objectContaining({ method: "POST", body: undefined }));
  });

  it("takes no answer for the answer to a removal", async () => {
    const fetch = stub(new Response(null, { status: 204 }));

    expect(await api.deleteChat("a")).toBeUndefined();
    expect(fetch).toHaveBeenCalledWith("/api/chats/a", expect.objectContaining({ method: "DELETE" }));
  });

  it("raises the server's error with its code and message, and whatever else the code carries", async () => {
    stub(answer({ error: { code: "missing_keys", message: "gpt needs OPENAI_API_KEY", missing: ["OPENAI_API_KEY"] } }, 422));

    const error = await api.createChat().catch((failure: unknown) => failure);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 422,
      code: "missing_keys",
      message: "gpt needs OPENAI_API_KEY",
      details: { missing: ["OPENAI_API_KEY"] },
    });
  });

  it("raises an error for an answer that is not the server's own, whatever it holds", async () => {
    stub(new Response("<html>Bad gateway</html>", { status: 502 }));

    await expect(api.chats()).rejects.toMatchObject({ status: 502, code: "error", message: "The server answered 502" });

    stub(answer({ error: "a string" }, 500));

    await expect(api.chats()).rejects.toMatchObject({ status: 500, code: "error" });
  });

  it("raises its own error when the server cannot be reached", async () => {
    stub(new TypeError("Failed to fetch"));

    await expect(api.health()).rejects.toBeInstanceOf(NetworkError);
  });

  it("lets a request that was called off be seen as that", async () => {
    stub(new DOMException("Aborted", "AbortError"));

    await expect(api.chat("a")).rejects.toMatchObject({ name: "AbortError" });
  });
});

interface Progress {
  lengthComputable: boolean;
  loaded: number;
  total: number;
}

// What the browser's request for sending a file does, as far as the upload needs
class FakeRequest {
  static made: FakeRequest[] = [];
  method = "";
  url = "";
  sent: unknown = undefined;
  status = 0;
  responseText = "";
  aborted = false;
  upload: { onprogress: ((event: Progress) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;

  constructor() {
    FakeRequest.made.push(this);
  }

  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }

  send(body: unknown) {
    this.sent = body;
  }

  abort() {
    this.aborted = true;
    this.onabort?.();
  }

  finish(status: number, body: string) {
    this.status = status;
    this.responseText = body;
    this.onload?.();
  }
}

describe("sending a file", () => {
  const attachment = { name: "data.csv", path: "uploads/data.csv", size: 3 };
  const file = new File(["a,b"], "my data.csv");

  function begin(options?: Parameters<typeof api.upload>[2]) {
    FakeRequest.made = [];
    vi.stubGlobal("XMLHttpRequest", FakeRequest);
    const result = api.upload("a b", file, options);

    return { result, request: FakeRequest.made[0] };
  }

  it("sends the file itself as the body, to the conversation, named as it was", async () => {
    const { result, request } = begin();

    expect(request).toMatchObject({ method: "POST", url: "/api/chats/a%20b/uploads?name=my%20data.csv" });
    expect(request.sent).toBe(file);
    request.finish(201, JSON.stringify(attachment));

    expect(await result).toEqual(attachment);
  });

  it("says how much has gone, as a fraction, once the browser knows the size", async () => {
    const seen: number[] = [];
    const { result, request } = begin({ onProgress: (fraction) => seen.push(fraction) });

    request.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 4 });
    request.upload.onprogress?.({ lengthComputable: false, loaded: 2, total: 0 });
    request.upload.onprogress?.({ lengthComputable: false, loaded: 2, total: 4 });
    request.upload.onprogress?.({ lengthComputable: true, loaded: 0, total: 0 });
    request.upload.onprogress?.({ lengthComputable: true, loaded: 9, total: 4 });
    request.finish(201, JSON.stringify(attachment));
    await result;

    expect(seen).toEqual([0.25, 1]);
  });

  it("raises the server's error for a file it turned away", async () => {
    const { result, request } = begin();
    request.finish(413, JSON.stringify({ error: { code: "too_large", message: "my data.csv is larger than the 5 bytes that can be attached" } }));

    await expect(result).rejects.toMatchObject({ status: 413, code: "too_large", message: "my data.csv is larger than the 5 bytes that can be attached" });
  });

  it("raises an error for an answer that is not the server's own", async () => {
    const { result, request } = begin();
    request.finish(502, "<html>Bad gateway</html>");

    await expect(result).rejects.toMatchObject({ status: 502, code: "error", message: "The server answered 502" });
  });

  it("raises an error for an answer that does not say where the file was kept", async () => {
    const bodies = [
      "not json",
      JSON.stringify({ name: "a.csv" }),
      JSON.stringify(null),
      JSON.stringify([1]),
      JSON.stringify({ path: "uploads/a.csv", size: 3 }),
      JSON.stringify({ name: "a.csv", size: 3 }),
      JSON.stringify({ name: "a.csv", path: "uploads/a.csv" }),
      JSON.stringify({ name: "a.csv", path: "uploads/a.csv", size: "3" }),
    ];
    for (const body of bodies) {
      const { result, request } = begin();
      request.finish(201, body);

      await expect(result).rejects.toMatchObject({ code: "error", message: "The server did not say where it kept the file" });
    }
  });

  it("raises an error for an answer that is not a success, whatever it says", async () => {
    for (const status of [199, 300, 304, 400]) {
      const { result, request } = begin();
      request.finish(status, JSON.stringify(attachment));

      await expect(result).rejects.toMatchObject({ status });
    }
  });

  it("says in words that a file could not be sent when the browser fails it, which a folder does", async () => {
    const { result, request } = begin();
    request.onerror?.();

    await expect(result).rejects.toThrow("The file could not be sent. It may be a folder, or the server may have stopped.");
  });

  it("stops sending a file when it is called off, and says that it was", async () => {
    const abort = new AbortController();
    const { result, request } = begin({ signal: abort.signal });

    abort.abort();

    expect(request.aborted).toBe(true);
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
  });

  it("does not begin to send a file that was called off already", async () => {
    const abort = new AbortController();
    abort.abort();
    FakeRequest.made = [];
    vi.stubGlobal("XMLHttpRequest", FakeRequest);

    await expect(api.upload("a", file, { signal: abort.signal })).rejects.toMatchObject({ name: "AbortError" });
    expect(FakeRequest.made).toEqual([]);
  });
});

describe("giving the lab a file", () => {
  const given = { data: [{ name: "my data.csv", description: "Counts" }], software: [], max_upload_bytes: 20480 };
  const file = new File(["a,b"], "my data.csv");

  function begin(options?: Parameters<typeof api.uploadOwnData>[2]) {
    FakeRequest.made = [];
    vi.stubGlobal("XMLHttpRequest", FakeRequest);
    const result = api.uploadOwnData(file, "Raw counts & more", options);

    return { result, request: FakeRequest.made[0] };
  }

  it("sends the file itself as the body, named as it was and with what it is, and takes what the lab was given", async () => {
    const { result, request } = begin();

    expect(request).toMatchObject({
      method: "POST",
      url: "/api/own/data/files?name=my%20data.csv&description=Raw%20counts%20%26%20more",
    });
    expect(request.sent).toBe(file);
    request.finish(201, JSON.stringify(given));

    expect(await result).toEqual(given);
  });

  it("says how much has gone, as a fraction", async () => {
    const seen: number[] = [];
    const { result, request } = begin({ onProgress: (fraction) => seen.push(fraction) });

    request.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 4 });
    request.upload.onprogress?.({ lengthComputable: true, loaded: 9, total: 4 });
    request.finish(201, JSON.stringify(given));
    await result;

    expect(seen).toEqual([0.25, 1]);
  });

  it("raises the server's error for a file it turned away", async () => {
    const { result, request } = begin();
    request.finish(409, JSON.stringify({ error: { code: "name_taken", message: "There is data named my data.csv already" } }));

    await expect(result).rejects.toMatchObject({ status: 409, code: "name_taken", message: "There is data named my data.csv already" });
  });

  it("raises an error for an answer that does not say what the lab was given", async () => {
    const bodies = [
      "not json",
      JSON.stringify(null),
      JSON.stringify({ name: "a.csv", path: "uploads/a.csv", size: 3 }),
      JSON.stringify({ data: [], software: [] }),
      JSON.stringify({ data: {}, software: [], max_upload_bytes: 1 }),
      JSON.stringify({ data: [], software: "none", max_upload_bytes: 1 }),
      JSON.stringify({ data: [], software: [], max_upload_bytes: "1" }),
    ];
    for (const body of bodies) {
      const { result, request } = begin();
      request.finish(201, body);

      await expect(result).rejects.toMatchObject({ code: "error", message: "The server did not say what it kept" });
    }
  });

  it("stops sending a file when it is called off, and says that it was", async () => {
    const abort = new AbortController();
    const { result, request } = begin({ signal: abort.signal });

    abort.abort();

    expect(request.aborted).toBe(true);
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("the files of a conversation", () => {
  it("are listed from what the server wraps them in", async () => {
    const fetch = stub(answer({ files: [{ path: "a.csv", size: 3, modified: 1, type: "text/csv" }], truncated: true }));

    expect(await api.files("a b")).toEqual({ files: [{ path: "a.csv", size: 3, modified: 1, type: "text/csv" }], truncated: true });
    expect(fetch).toHaveBeenCalledWith("/api/chats/a%20b/files", expect.objectContaining({ method: "GET" }));
  });

  it("are not listed for a conversation that is not there", async () => {
    stub(answer({ error: { code: "not_found", message: "No such conversation" } }, 404));

    await expect(api.files("gone")).rejects.toMatchObject({ status: 404, code: "not_found" });
  });
});

// A response whose body comes in the pieces it is given, and says if it was cancelled
function pieces(parts: (string | Uint8Array)[], status = 200) {
  const encoder = new TextEncoder();
  const cancelled = vi.fn();
  let sent = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (sent >= parts.length) {
        controller.close();

        return;
      }
      const part = parts[sent++];
      controller.enqueue(typeof part === "string" ? encoder.encode(part) : part);
    },
    cancel: cancelled,
  });

  return { response: new Response(body, { status }), cancelled };
}

describe("the text of a file", () => {
  it("is all of a file that is under the limit, asked for by its path", async () => {
    const { response, cancelled } = pieces(["gene,count\n", "TP53,12\n"]);
    const fetch = stub(response);

    expect(await api.fileText("a b", "dir/x y.csv", 1000)).toEqual({ text: "gene,count\nTP53,12\n", truncated: false, binary: false });
    expect(fetch).toHaveBeenCalledWith("/api/chats/a%20b/files/dir/x%20y.csv", { signal: undefined });
    expect(cancelled).not.toHaveBeenCalled();
  });

  it("is read whole from a response that gives no stream, which is a browser that has none", async () => {
    const response = new Response("gene,count\n");
    Object.defineProperty(response, "body", { value: null });
    stub(response);

    expect(await api.fileText("a", "x.csv", 3)).toEqual({ text: "gene,count\n", truncated: false, binary: false });
  });

  it("is nothing for a file with nothing in it", async () => {
    stub(pieces([]).response);

    expect(await api.fileText("a", "empty.txt", 10)).toEqual({ text: "", truncated: false, binary: false });
  });

  it("is the start of a file that goes on past the limit, which the server is then told to stop sending", async () => {
    const { response, cancelled } = pieces(["abcd", "efgh", "ijkl", "mnop"]);
    stub(response);

    expect(await api.fileText("a", "big.txt", 6)).toEqual({ text: "abcdef", truncated: true, binary: false });
    expect(cancelled).toHaveBeenCalledTimes(1);
  });

  it("is all of a file that is as long as the limit, which does not go on", async () => {
    stub(pieces(["abc", "def"]).response);

    expect(await api.fileText("a", "x.txt", 6)).toEqual({ text: "abcdef", truncated: false, binary: false });
  });

  it("does not show half a character where the limit cuts one", async () => {
    // "é" is two bytes, of which the limit leaves one
    stub(pieces(["abé"]).response);

    expect(await api.fileText("a", "x.txt", 3)).toEqual({ text: "ab", truncated: true, binary: false });
  });

  it("reads a character that comes in two pieces as one", async () => {
    const bytes = new TextEncoder().encode("é");
    stub(pieces([bytes.slice(0, 1), bytes.slice(1)]).response);

    expect(await api.fileText("a", "x.txt", 10)).toEqual({ text: "é", truncated: false, binary: false });
  });

  it("is said not to be text when it has a null byte in it", async () => {
    stub(pieces([new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0, 1, 2])]).response);

    expect(await api.fileText("a", "x.png", 100)).toMatchObject({ binary: true, truncated: false });
  });

  it("fails as the server says it did, or with what it sent if it said nothing", async () => {
    stub(answer({ error: { code: "not_found", message: "No such file there" } }, 404));
    await expect(api.fileText("a", "x.txt", 10)).rejects.toMatchObject({ status: 404, code: "not_found", message: "No such file there" });

    stub(new Response("<html>", { status: 502 }));
    await expect(api.fileText("a", "x.txt", 10)).rejects.toMatchObject({ status: 502, code: "error" });
  });

  it("fails as a server that cannot be reached, unless it was told to stop", async () => {
    stub(new TypeError("fetch failed"));
    await expect(api.fileText("a", "x.txt", 10)).rejects.toBeInstanceOf(NetworkError);

    stub(new DOMException("Aborted", "AbortError"));
    await expect(api.fileText("a", "x.txt", 10)).rejects.toMatchObject({ name: "AbortError" });
  });

  it("fails as a server that cannot be reached when the connection drops while it is read, unless it was told to stop", async () => {
    const dropping = (error: unknown) =>
      new Response(
        new ReadableStream<Uint8Array>({
          pull(controller) {
            controller.error(error);
          },
        }),
      );

    stub(dropping(new TypeError("terminated")));
    await expect(api.fileText("a", "x.txt", 10)).rejects.toBeInstanceOf(NetworkError);

    stub(dropping(new DOMException("Aborted", "AbortError")));
    await expect(api.fileText("a", "x.txt", 10)).rejects.toMatchObject({ name: "AbortError" });
  });

  it("gives the signal it was given to the request", async () => {
    const fetch = stub(pieces(["x"]).response);
    const { signal } = new AbortController();

    await api.fileText("a", "x.txt", 10, signal);

    expect(fetch).toHaveBeenCalledWith(expect.any(String), { signal });
  });
});

describe("a conversation as a document", () => {
  const page = (disposition: string | null = "attachment; filename*=utf-8''A%20title.html") =>
    new Response("<!DOCTYPE html><p>Hello</p>", {
      headers: { "Content-Type": "text/html; charset=utf-8", ...(disposition === null ? {} : { "Content-Disposition": disposition }) },
    });

  it("asks for the format it wants, and gives the file with the name the server gave it", async () => {
    const fetch = stub(page());

    const { file, name } = await api.exportChat("a b", "html");

    expect(fetch).toHaveBeenCalledWith("/api/chats/a%20b/export?format=html", { signal: undefined });
    expect(name).toBe("A title.html");
    expect(await file.text()).toBe("<!DOCTYPE html><p>Hello</p>");
  });

  it("asks for a PDF as one, and names the file for what it is where the server named none", async () => {
    const fetch = stub(new Response("%PDF-1.7", { headers: { "Content-Type": "application/pdf" } }));

    const { file, name } = await api.exportChat("a", "pdf");

    expect(fetch).toHaveBeenCalledWith("/api/chats/a/export?format=pdf", { signal: undefined });
    expect(name).toBe("conversation.pdf");
    expect(file.size).toBe(8);
  });

  it("tells what the server said when it could not make the document, and not a file of it", async () => {
    stub(answer({ error: { code: "pdf_unavailable", message: "A PDF cannot be made here.", reason: "no Pango" } }, 501));

    await expect(api.exportChat("a", "pdf")).rejects.toMatchObject({
      status: 501,
      code: "pdf_unavailable",
      message: "A PDF cannot be made here.",
      details: { reason: "no Pango" },
    });
  });

  it("tells of a conversation that is gone, and of an answer that is not the server's", async () => {
    stub(answer({ error: { code: "not_found", message: "There is no conversation" } }, 404));
    await expect(api.exportChat("a", "html")).rejects.toMatchObject({ status: 404, code: "not_found" });

    stub(new Response("<html>Bad gateway</html>", { status: 502 }));
    await expect(api.exportChat("a", "html")).rejects.toMatchObject({ status: 502, code: "error", message: "The server answered 502" });
  });

  it("fails as a server that cannot be reached when the connection drops, or while the file is read, unless it was told to stop", async () => {
    stub(new TypeError("Failed to fetch"));
    await expect(api.exportChat("a", "html")).rejects.toBeInstanceOf(NetworkError);

    stub(new DOMException("Aborted", "AbortError"));
    await expect(api.exportChat("a", "html")).rejects.toMatchObject({ name: "AbortError" });

    const dropping = (error: unknown) =>
      new Response(
        new ReadableStream<Uint8Array>({
          pull(controller) {
            controller.error(error);
          },
        }),
      );
    stub(dropping(new TypeError("terminated")));
    await expect(api.exportChat("a", "html")).rejects.toBeInstanceOf(NetworkError);

    stub(dropping(new DOMException("Aborted", "AbortError")));
    await expect(api.exportChat("a", "html")).rejects.toMatchObject({ name: "AbortError" });
  });

  it("gives the signal it was given to the request", async () => {
    const fetch = stub(page());
    const { signal } = new AbortController();

    await api.exportChat("a", "html", signal);

    expect(fetch).toHaveBeenCalledWith(expect.any(String), { signal });
  });
});
