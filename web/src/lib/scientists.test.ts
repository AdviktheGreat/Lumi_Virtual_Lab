import { describe, expect, it } from "vitest";
import { checkScientist, draftOfScientist, EMPTY_SCIENTIST, isChanged, sameTitle, tidy } from "./scientists";
import type { LibraryScientist } from "./types";

const library: LibraryScientist[] = [
  { title: "Principal Investigator", expertise: "Leading", goal: "Discover", role: "Lead", builtin: true },
  { title: "Chemist", expertise: "Bonds", goal: "Make", role: "Bench", builtin: false },
];

const written = { title: "Geneticist", expertise: "Variants", goal: "Find causes", role: "Analyse" };

describe("tidying what was written", () => {
  it("leaves words with one space between them, as the server keeps them", () => {
    expect(tidy("  Many   words\n\nacross\tlines  ")).toBe("Many words across lines");
    expect(tidy("   ")).toBe("");
    expect(tidy("")).toBe("");
  });

  it("takes titles as the same that differ in case and spacing", () => {
    expect(sameTitle("Chemist", " chemist ")).toBe(true);
    expect(sameTitle("Computational  Biologist", "computational biologist")).toBe(true);
    expect(sameTitle("Chemist", "Chemists")).toBe(false);
  });
});

describe("a scientist as it is edited", () => {
  it("is the four parts, and nothing more of what the library says", () => {
    expect(draftOfScientist(library[1])).toEqual({ title: "Chemist", expertise: "Bonds", goal: "Make", role: "Bench" });
  });

  it("is changed by what was written in any part, but not by the spacing", () => {
    const draft = draftOfScientist(library[1]);

    expect(isChanged(draft, library[1])).toBe(false);
    expect(isChanged({ ...draft, role: " Bench " }, library[1])).toBe(false);
    for (const key of ["title", "expertise", "goal", "role"] as const) {
      expect(isChanged({ ...draft, [key]: "Different" }, library[1]), key).toBe(true);
    }
  });
});

describe("whether a scientist can be saved", () => {
  it("can, and is sent tidy, when every part has something in it", () => {
    const checked = checkScientist({ title: "  Gene  ticist ", expertise: "Var\niants", goal: " Find ", role: "Analyse" }, library, true);

    expect(checked.problems).toEqual({});
    expect(checked.scientist).toEqual({ title: "Gene ticist", expertise: "Var iants", goal: "Find", role: "Analyse" });
  });

  it("cannot while a part is empty, and says which", () => {
    const checked = checkScientist({ ...written, goal: "   ", role: "" }, library, true);

    expect(checked.scientist).toBeNull();
    expect(checked.problems).toEqual({ goal: "Goal is needed.", role: "Role is needed." });
  });

  it("says every part is needed of a form that has not been written in", () => {
    expect(Object.keys(checkScientist(EMPTY_SCIENTIST, library, true).problems)).toEqual(["title", "expertise", "goal", "role"]);
  });

  it("cannot, as someone new, take the title of one in the library, in any case", () => {
    const checked = checkScientist({ ...written, title: " principal  investigator" }, library, true);

    expect(checked.scientist).toBeNull();
    expect(checked.problems.title).toMatch(/There is a scientist with this title/);
  });

  it("can, as an edit, keep its own title, which is how it takes the place of what it edits", () => {
    const checked = checkScientist({ ...written, title: "Chemist" }, library, false);

    expect(checked.problems).toEqual({});
    expect(checked.scientist?.title).toBe("Chemist");
  });

  it("says a title is needed, and not that it is taken, when there is none", () => {
    expect(checkScientist({ ...written, title: " " }, library, true).problems).toEqual({ title: "Title is needed." });
  });
});
