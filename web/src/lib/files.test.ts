import { describe, expect, it } from "vitest";
import { fileUrl, formatBytes, insidePath, isImage, localPath } from "./files";

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
