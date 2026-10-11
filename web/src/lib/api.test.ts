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
        body: JSON.stringify({ text: "Hello there" }),
      }),
    );
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
