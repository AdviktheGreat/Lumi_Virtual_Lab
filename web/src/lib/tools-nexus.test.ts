import { describe, expect, it } from "vitest";
import { catalogNeeds, catalogToAdd, engineSaid, needsText, readiness, webSearchState, webTools } from "./tools-nexus";
import type { KeyStatuses, McpCatalogServer, McpServer, ToolInfo } from "./types";

const server = (fields: Partial<McpServer> = {}): McpServer => ({
  name: "mine",
  title: "Mine",
  about: null,
  preset: false,
  added: true,
  enabled: true,
  auth: null,
  auth_choices: [],
  transport: "http",
  target: "https://example.com/mcp",
  asks: false,
  signed_in: null,
  missing: [],
  keys_set: [],
  problem: null,
  setup: null,
  ...fields,
});

const catalog = (name: string, group: string, fields: Partial<McpCatalogServer> = {}): McpCatalogServer => ({
  name,
  title: name,
  about: "What it is for",
  group,
  maker: "Someone",
  site: "https://example.org",
  target: "https://example.org/mcp",
  signs_in: false,
  asks: false,
  added: false,
  ...fields,
});

const tool = (name: string, group: string, enabled = true): ToolInfo => ({ name, group, summary: "", needs_code: false, enabled });

const keys = (sources: KeyStatuses["sources"] = {}): KeyStatuses => ({
  settable: [],
  providers: [],
  keychain: { available: false, name: "keychain", problem: null },
  sources,
  problem: null,
});

describe("whether a server is ready", () => {
  it("is when nothing stands in its way", () => {
    expect(readiness(server())).toEqual({ tone: "ready", label: "Ready" });
    expect(readiness(server({ signed_in: true, auth: "oauth" }))).toEqual({ tone: "ready", label: "Ready" });
  });

  it("is not while a key that this page may give is missing", () => {
    const missing = [{ name: "PAPERCLIP_API_KEY", settable: true }];

    expect(readiness(server({ missing }))).toEqual({ tone: "needs", label: "Needs a key" });
  });

  it("is not while a key that must be set where the server was started is missing, which is said as setup", () => {
    const missing = [{ name: "SEARCH_TOKEN", settable: false }];

    expect(readiness(server({ missing }))).toEqual({ tone: "needs", label: "Needs setup" });
    expect(readiness(server({ missing: [...missing, { name: "K", settable: true }] })).label).toBe("Needs a key");
  });

  it("is not while a sign-in to it is not kept, but is when whether it is is not known", () => {
    expect(readiness(server({ auth: "oauth", signed_in: false }))).toEqual({ tone: "needs", label: "Needs sign-in" });
    expect(readiness(server({ auth: "oauth", signed_in: null })).tone).toBe("ready");
  });

  it("is a problem first of all, whatever else it needs", () => {
    const problem = server({ problem: "The program proto-tools-mcp is not installed here.", missing: [{ name: "K", settable: true }] });

    expect(readiness(problem)).toEqual({ tone: "problem", label: "Problem" });
  });
});

describe("what a server takes", () => {
  it("is nothing for a server on the web that asks for no key", () => {
    expect(needsText(server())).toBe("Nothing");
  });

  it("is an account to sign in to, for a server that is signed in to", () => {
    expect(needsText(server({ auth: "oauth" }))).toBe("Your account, signed in to in the browser");
  });

  it("is a key or an account, for a preset that can be given either", () => {
    expect(needsText(server({ auth: "key", auth_choices: ["key", "oauth"] }))).toBe(
      "An API key, or your account signed in to in the browser",
    );
    expect(needsText(server({ auth: "oauth", auth_choices: ["key", "oauth"] }))).toBe(
      "An API key, or your account signed in to in the browser",
    );
  });

  it("is a program that is installed, for a server that is started here", () => {
    expect(needsText(server({ transport: "stdio" }))).toBe("A program installed on this computer");
  });

  it("is the keys it asks for, whether they are set or not, and where those are to be set", () => {
    expect(needsText(server({ missing: [{ name: "K", settable: true }] }))).toBe("An API key");
    expect(needsText(server({ keys_set: ["K"] }))).toBe("An API key");
    expect(needsText(server({ missing: [{ name: "K", settable: false }] }))).toBe("A key set where the server was started");
    expect(needsText(server({ transport: "stdio", keys_set: ["K"] }))).toBe("A program installed on this computer, and an API key");
  });

  it("is nothing, or a sign-in, for a server of the catalog", () => {
    expect(catalogNeeds(catalog("a", "Biology"))).toBe("Nothing");
    expect(catalogNeeds(catalog("a", "Biology", { signs_in: true }))).toBe("Your account, signed in to in the browser");
  });
});

describe("the catalog still to add", () => {
  it("is grouped by what the servers are for, in the order the catalog gives them", () => {
    const groups = catalogToAdd([catalog("a", "Biology"), catalog("b", "Software"), catalog("c", "Biology")]);

    expect(groups.map((group) => [group.group, group.servers.map((each) => each.name)])).toEqual([
      ["Biology", ["a", "c"]],
      ["Software", ["b"]],
    ]);
  });

  it("leaves out the servers that are set up, and the group that has none left", () => {
    const groups = catalogToAdd([catalog("a", "Biology", { added: true }), catalog("b", "Software"), catalog("c", "Biology", { added: true })]);

    expect(groups.map((group) => group.group)).toEqual(["Software"]);
    expect(catalogToAdd([catalog("a", "Biology", { added: true })])).toEqual([]);
    expect(catalogToAdd([])).toEqual([]);
  });
});

describe("the search of the web", () => {
  const tools = [tool("pubmed_search", "Literature"), tool("web_search", "Web"), tool("web_fetch", "Web", false)];

  it("is the tools of the web group, and no others", () => {
    expect(webTools(tools).map((each) => each.name)).toEqual(["web_search", "web_fetch"]);
    expect(webTools([])).toEqual([]);
  });

  it("is on while any of those is on, and off when none is", () => {
    expect(webSearchState(tools, keys()).on).toBe(true);
    expect(webSearchState([tool("web_search", "Web", false), tool("web_fetch", "Web", false)], keys()).on).toBe(false);
    expect(webSearchState([tool("pubmed_search", "Literature")], keys()).on).toBe(false);
  });

  it("is made with DuckDuckGo until the key of Exa is set, wherever it came from, and then with Exa", () => {
    expect(webSearchState(tools, keys()).engine).toBe("DuckDuckGo");
    expect(webSearchState(tools, keys({ EXA_API_KEY: "keychain" })).engine).toBe("Exa");
    expect(webSearchState(tools, keys({ EXA_API_KEY: "environment" })).engine).toBe("Exa");
    expect(webSearchState(tools, keys({ OPENAI_API_KEY: "keychain" })).engine).toBe("DuckDuckGo");
  });

  it("is told of with the engine, and what it takes to use the other", () => {
    expect(engineSaid("Exa")).toMatch(/^Searches with Exa/);
    expect(engineSaid("DuckDuckGo")).toMatch(/needs no key/);
    expect(engineSaid("DuckDuckGo")).toMatch(/key for Exa/);
  });
});
