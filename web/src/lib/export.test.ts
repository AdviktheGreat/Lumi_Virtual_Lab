import { afterEach, describe, expect, it, vi } from "vitest";
import { EXPORT_CHOICES, exportNameOf, saveFile } from "./export";

describe("the name a document is saved as", () => {
  it("is the one the server sent, read as it is sent when it is not ASCII", () => {
    expect(exportNameOf("attachment; filename*=utf-8''Nanobody%20design.html", "html")).toBe("Nanobody design.html");
    expect(exportNameOf("attachment; filename*=utf-8''%E6%8A%97%E4%BD%93%20%C3%BCber.pdf", "pdf")).toBe("抗体 über.pdf");
    expect(exportNameOf("attachment; filename*=UTF-8'en'Plan-%20CRISPR.html", "html")).toBe("Plan- CRISPR.html");
  });

  it("is read from the plain form too, quoted or not", () => {
    expect(exportNameOf('attachment; filename="plan.html"', "html")).toBe("plan.html");
    expect(exportNameOf("attachment; filename=plan.html", "html")).toBe("plan.html");
    expect(exportNameOf('attachment; filename="the \\"plan\\".html"', "html")).toBe('the "plan".html');
    expect(exportNameOf('attachment; filename="a;b.html"', "html")).toBe("a;b.html");
  });

  it("is not read from the middle of another parameter", () => {
    expect(exportNameOf("attachment; filename=\"x-filename*=utf-8''evil.html\"", "html")).toBe("x-filename*=utf-8''evil.html");
    expect(exportNameOf("attachment; xfilename=\"other.html\"", "html")).toBe("conversation.html");
  });

  it("is the one that is not ASCII where both are sent", () => {
    expect(exportNameOf("attachment; filename=\"uber.html\"; filename*=utf-8''%C3%BCber.html", "html")).toBe("über.html");
  });

  it("is the plain one where the other is not encoded as it says", () => {
    expect(exportNameOf("attachment; filename*=utf-8''100%.html; filename=\"plan.html\"", "html")).toBe("plan.html");
    expect(exportNameOf("attachment; filename*=utf-8''100%.html", "html")).toBe("conversation.html");
  });

  it("is not a path or a hidden file, and has no control characters in it", () => {
    expect(exportNameOf("attachment; filename*=utf-8''..%2F..%2Fetc%2Fpasswd", "html")).toBe("conversation.html");
    expect(exportNameOf("attachment; filename*=utf-8''a%2Fb%5Cc.html", "html")).toBe("a-b-c.html");
    expect(exportNameOf("attachment; filename*=utf-8''a%0D%0Ab.html", "html")).toBe("a-b.html");
    expect(exportNameOf("attachment; filename*=utf-8''.html", "html")).toBe("conversation.html");
  });

  it("is made for what it is where the server sent none", () => {
    expect(exportNameOf(null, "html")).toBe("conversation.html");
    expect(exportNameOf(null, "pdf")).toBe("conversation.pdf");
    expect(exportNameOf("attachment", "pdf")).toBe("conversation.pdf");
    expect(exportNameOf("attachment; filename=", "pdf")).toBe("conversation.pdf");
    expect(exportNameOf('attachment; filename=""', "pdf")).toBe("conversation.pdf");
  });
});

describe("what it can be saved as", () => {
  it("is a page and a PDF, each with what it is for", () => {
    expect(EXPORT_CHOICES.map((choice) => choice.format)).toEqual(["html", "pdf"]);
    for (const choice of EXPORT_CHOICES) {
      expect(choice.label).not.toBe("");
      expect(choice.hint).not.toBe("");
    }
  });
});

describe("handing a document to the browser", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function stubPage() {
    const link = { href: "", download: "", hidden: false, click: vi.fn(), remove: vi.fn() };
    const body = { append: vi.fn() };
    vi.stubGlobal("document", { createElement: vi.fn(() => link), body });
    const created = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:the-file");
    const revoked = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    return { link, body, created, revoked };
  }

  it("clicks a link that downloads it, as it is named, and takes the link away", () => {
    const { link, body, created } = stubPage();
    const file = new Blob(["x"]);

    saveFile(file, "A title.html");

    expect(created).toHaveBeenCalledWith(file);
    expect(link).toMatchObject({ href: "blob:the-file", download: "A title.html", hidden: true });
    expect(body.append).toHaveBeenCalledWith(link);
    expect(link.click).toHaveBeenCalledTimes(1);
    expect(link.remove).toHaveBeenCalledTimes(1);
    // It is in the page when it is clicked
    expect(body.append.mock.invocationCallOrder[0]).toBeLessThan(link.click.mock.invocationCallOrder[0]);
  });

  it("lets go of the file only after the browser has had time to begin to save it", () => {
    vi.useFakeTimers();
    const { revoked } = stubPage();

    saveFile(new Blob(["x"]), "a.html");

    expect(revoked).not.toHaveBeenCalled();
    vi.advanceTimersByTime(29_000);
    expect(revoked).not.toHaveBeenCalled();
    vi.advanceTimersByTime(2_000);
    expect(revoked).toHaveBeenCalledWith("blob:the-file");
  });
});
