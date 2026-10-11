import { describe, expect, it } from "vitest";
import { linkKind } from "./links";

describe("where a link in an answer may go", () => {
  it("may go to the web, and to an email, in any case of letters", () => {
    expect(linkKind("https://example.com/paper?id=1#top")).toBe("web");
    expect(linkKind("http://example.com")).toBe("web");
    expect(linkKind("HTTPS://EXAMPLE.COM")).toBe("web");
    expect(linkKind("mailto:lab@example.com")).toBe("web");
    expect(linkKind("MAILTO:lab@example.com")).toBe("web");
  });

  it("may go to a place in the page", () => {
    expect(linkKind("#findings")).toBe("place");
    expect(linkKind("#")).toBe("place");
  });

  it("may not go where it would run a script or open something of this machine", () => {
    expect(linkKind("javascript:alert(1)")).toBe("none");
    expect(linkKind("JavaScript:alert(1)")).toBe("none");
    expect(linkKind(" javascript:alert(1)")).toBe("none");
    expect(linkKind("java\tscript:alert(1)")).toBe("none");
    expect(linkKind("data:text/html,<script>alert(1)</script>")).toBe("none");
    expect(linkKind("vbscript:run")).toBe("none");
    expect(linkKind("file:///etc/passwd")).toBe("none");
    expect(linkKind("ftp://example.com/file")).toBe("none");
  });

  it("may not go to an address that is not written out, which a browser would read as it pleased", () => {
    expect(linkKind("//example.com/path")).toBe("none");
    expect(linkKind("/api/chats")).toBe("none");
    expect(linkKind("results.csv")).toBe("none");
    expect(linkKind(" https://example.com")).toBe("none");
    expect(linkKind("")).toBe("none");
  });
});
