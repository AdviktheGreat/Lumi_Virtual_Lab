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
