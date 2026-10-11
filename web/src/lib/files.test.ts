import { describe, expect, it } from "vitest";
import {
  baseName,
  dividerOf,
  fileUrl,
  filesChanged,
  folderOf,
  formatBytes,
  inFolders,
  insidePath,
  isImage,
  localPath,
  matching,
  opensInPage,
  previewOf,
} from "./files";
import { emptyTranscript, replay } from "./transcript";
import type { ChatEvent, ChatEventKind } from "./types";

describe("the address of a file", () => {
  it("is under the conversation's files, with each part of the path written as an address", () => {
    expect(fileUrl("2026-10-11_1200_chat", "plots/figure_1.png")).toBe("/api/chats/2026-10-11_1200_chat/files/plots/figure_1.png");
    expect(fileUrl("c", "my plots/a#b?.png")).toBe("/api/chats/c/files/my%20plots/a%23b%3F.png");
  });

  it("asks to be saved, where that is wanted", () => {
    expect(fileUrl("c", "out.csv", true)).toBe("/api/chats/c/files/out.csv?download=true");
  });

  it("names the conversation as an address, whatever it is called", () => {
    expect(fileUrl("a/b", "x")).toBe("/api/chats/a%2Fb/files/x");
  });
});

describe("a file that is an image", () => {
  it("is one by its ending, in either case", () => {
    for (const name of ["a.png", "a.PNG", "b.jpg", "b.jpeg", "c.gif", "d.webp", "e.svg", "dir/f.Png"]) {
      expect(isImage(name)).toBe(true);
    }
    for (const name of ["a.csv", "png", "a.png.txt", "a.pngx", "a.tiff"]) {
      expect(isImage(name)).toBe(false);
    }
  });
});

describe("a path from where the code ran", () => {
  it("is inside the files, tidied, when it stays in them", () => {
    expect(insidePath("plots/figure_1.png")).toBe("plots/figure_1.png");
    expect(insidePath("./a//b.csv")).toBe("a/b.csv");
    // It is a path as it is written, and not an address, so a percent sign in a name is a percent sign
    expect(insidePath("100%.csv")).toBe("100%.csv");
    expect(insidePath("a b/c#d.txt")).toBe("a b/c#d.txt");
  });

  it("is nothing when it starts from the root, goes up, or is not a path", () => {
    for (const path of ["", ".", "./", "/etc/passwd", "//host/a", "../a", "a/../../b", "a\\b", "a\0b"]) {
      expect(insidePath(path)).toBeNull();
    }
  });
});

describe("what an address in an answer names", () => {
  it("is a file of the conversation when it is a path from where the code ran", () => {
    expect(localPath("plots/figure_1.png")).toBe("plots/figure_1.png");
    expect(localPath("./plots/figure_1.png")).toBe("plots/figure_1.png");
    expect(localPath("plots//a.png")).toBe("plots/a.png");
    expect(localPath("  out/a%20b.png  ")).toBe("out/a b.png");
    expect(localPath("a.png?raw=1#top")).toBe("a.png");
  });

  it("is nothing when it would take the page elsewhere", () => {
    for (const address of [
      "https://example.com/a.png",
      "http://example.com/a.png",
      "//example.com/a.png",
      "data:image/png;base64,AAAA",
      "javascript:alert(1)",
      "file:///etc/passwd",
      "mailto:a@b.c",
      "/etc/passwd",
      "\\\\host\\share\\a.png",
    ]) {
      expect(localPath(address)).toBeNull();
    }
  });

  it("is nothing when it would leave the files, or names none", () => {
    for (const address of ["", "   ", ".", "./", "../a.png", "a/../../b.png", "a/%2e%2e/b.png", "a\\b.png", "a%00b.png", "%E0%A4%A"]) {
      expect(localPath(address)).toBeNull();
    }
  });
});

describe("a size", () => {
  it("is said as a person would say it", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1023)).toBe("1023 B");
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(10 * 1024)).toBe("10 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatBytes(3 * 1024 ** 3)).toBe("3.0 GB");
    expect(formatBytes(5000 * 1024 ** 4)).toBe("5000 TB");
  });
});

describe("how a file is shown", () => {
  it("is as a picture for the types a page can show as one", () => {
    for (const type of ["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"]) {
      expect(previewOf({ path: "x", type })).toBe("image");
    }
    expect(previewOf({ path: "x.png", type: "IMAGE/PNG; charset=binary" })).toBe("image");
  });

  it("is as a table for a CSV or a TSV, by what the server calls it or by its name", () => {
    expect(previewOf({ path: "a.csv", type: "text/csv" })).toBe("table");
    expect(previewOf({ path: "a.tsv", type: "text/tab-separated-values" })).toBe("table");
    expect(previewOf({ path: "a.CSV", type: "application/octet-stream" })).toBe("table");
    expect(previewOf({ path: "a.TSV", type: "application/octet-stream" })).toBe("table");
  });

  it("is as text for what is written to be read, by its type or by its name", () => {
    expect(previewOf({ path: "notes.txt", type: "text/plain" })).toBe("text");
    expect(previewOf({ path: "run.py", type: "text/x-python" })).toBe("text");
    expect(previewOf({ path: "r.json", type: "application/json" })).toBe("text");
    expect(previewOf({ path: "seqs.fasta", type: "application/octet-stream" })).toBe("text");
    expect(previewOf({ path: "dir/protein.PDB", type: "chemical/x-pdb" })).toBe("text");
  });

  it("is not shown for the rest, which are saved", () => {
    expect(previewOf({ path: "paper.pdf", type: "application/pdf" })).toBe("none");
    expect(previewOf({ path: "model.pkl", type: "application/octet-stream" })).toBe("none");
    expect(previewOf({ path: "archive.zip", type: "application/zip" })).toBe("none");
    // A name that is only an extension has none
    expect(previewOf({ path: ".py", type: "application/octet-stream" })).toBe("none");
    expect(previewOf({ path: "py", type: "application/octet-stream" })).toBe("none");
  });

  it("opens in a tab where the server shows it in the page, which a PDF and a download are not", () => {
    expect(opensInPage({ type: "image/png" })).toBe(true);
    expect(opensInPage({ type: "text/csv" })).toBe(true);
    expect(opensInPage({ type: "text/plain; charset=utf-8" })).toBe(true);
    expect(opensInPage({ type: "application/json" })).toBe(true);
    expect(opensInPage({ type: "application/pdf" })).toBe(false);
    expect(opensInPage({ type: "text/x-python" })).toBe(false);
  });
});

describe("names of files", () => {
  it("are the last part of the path, and the rest is the folder", () => {
    expect(baseName("plots/fig 1.png")).toBe("fig 1.png");
    expect(baseName("a.csv")).toBe("a.csv");
    expect(folderOf("plots/deep/fig.png")).toBe("plots/deep");
    expect(folderOf("a.csv")).toBe("");
  });
});

describe("files in folders", () => {
  const file = (path: string) => ({ path, size: 1, modified: 0, type: "text/plain" });

  it("are what is at the top first, then each folder in order, and the files of each in order", () => {
    const folders = inFolders(["uploads/b.csv", "z.txt", "plots/fig10.png", "plots/fig2.png", "a.txt", "uploads/a.csv"].map(file));

    expect(folders.map((folder) => [folder.name, folder.files.map((each) => each.path)])).toEqual([
      ["", ["a.txt", "z.txt"]],
      ["plots", ["plots/fig2.png", "plots/fig10.png"]],
      ["uploads", ["uploads/a.csv", "uploads/b.csv"]],
    ]);
  });

  it("are a folder for each directory, however deep, and none where there are no files", () => {
    expect(inFolders(["a/b/c.txt", "a/d.txt"].map(file)).map((folder) => folder.name)).toEqual(["a", "a/b"]);
    expect(inFolders([])).toEqual([]);
    expect(inFolders(["only/one.txt"].map(file)).map((folder) => folder.name)).toEqual(["only"]);
  });

  it("do not change the list that they are made from", () => {
    const given = ["b.txt", "a.txt"].map(file);
    inFolders(given);

    expect(given.map((each) => each.path)).toEqual(["b.txt", "a.txt"]);
  });
});

describe("finding files", () => {
  const files = ["plots/Volcano.png", "uploads/expression.csv", "uploads/notes.txt"].map((path) => ({ path }));

  it("is by the words typed, in any order and whatever their case, all of which a path must have", () => {
    expect(matching(files, "vol").map((file) => file.path)).toEqual(["plots/Volcano.png"]);
    expect(matching(files, "CSV uploads").map((file) => file.path)).toEqual(["uploads/expression.csv"]);
    expect(matching(files, "uploads").map((file) => file.path)).toEqual(["uploads/expression.csv", "uploads/notes.txt"]);
    expect(matching(files, "uploads png")).toEqual([]);
  });

  it("gives all of them for nothing typed", () => {
    expect(matching(files, "")).toBe(files);
    expect(matching(files, "   ")).toBe(files);
  });
});

describe("when files may have changed", () => {
  let next = 0;
  const event = (kind: ChatEventKind, turn: number, fields: Partial<ChatEvent> = {}): ChatEvent => ({
    kind,
    id: ++next,
    turn,
    speaker: null,
    text: "",
    data: {},
    time: 0,
    ...fields,
  });
  const calling = (id: string, name = "run_code") => event("tool_calls", 1, { data: { calls: [{ id, name, arguments: "{}" }] } });
  const cell = (call: string) => event("cell", 1, { data: { call, language: "python", code: "1", status: "ok" } });
  const lab = (kind: string, details: Record<string, unknown> = {}) =>
    event("lab", 1, { data: { call: "t", event: kind, meeting: "m", round: 1, details } });
  const counted = (events: ChatEvent[]) => events.map((_, at) => filesChanged(replay(events.slice(0, at + 1))));

  it("is not at all for a conversation with nothing in it", () => {
    expect(filesChanged(emptyTranscript)).toBe(0);
  });

  it("goes up when code runs, a file is sent, or a turn ends, and not for what does not touch a file", () => {
    next = 0;
    const attachments = [
      { name: "a", path: "uploads/a", size: 1 },
      { name: "b", path: "uploads/b", size: 1 },
    ];

    expect(
      counted([
        event("user", 1, { data: { attachments } }),
        event("note", 1, { text: "Use the other file.", data: { to: "lead" } }),
        calling("a"),
        cell("a"),
        cell("a"),
        event("tool_output", 1, { text: "ok", data: { call: "a" } }),
        event("answer", 1, { text: "Done" }),
      ]),
    ).toEqual([2, 2, 2, 3, 4, 4, 5]);
  });

  it("goes up for the code that the team runs, which is with the call that brought it in", () => {
    next = 0;

    expect(
      counted([
        event("user", 1),
        calling("t", "convene_team"),
        lab("started"),
        lab("turn"),
        lab("code", { code: "1", language: "python" }),
        lab("cell", { code: "1", status: "ok" }),
        lab("cell", { code: "2", status: "ok" }),
        lab("message", { kind: "response" }),
      ]),
    ).toEqual([0, 0, 0, 0, 0, 1, 2, 2]);
  });
});

describe("what a table is divided by", () => {
  it("is a tab for a TSV, by its type or its name, and a comma for anything else", () => {
    expect(dividerOf({ path: "a.tsv", type: "application/octet-stream" })).toBe("\t");
    expect(dividerOf({ path: "a", type: "text/tab-separated-values; charset=utf-8" })).toBe("\t");
    expect(dividerOf({ path: "a.csv", type: "text/csv" })).toBe(",");
    expect(dividerOf({ path: "table", type: "text/plain" })).toBe(",");
  });
});
