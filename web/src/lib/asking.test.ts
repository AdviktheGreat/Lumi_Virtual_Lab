import { describe, expect, it } from "vitest";
import { formFields, initialValues, isWebAddress, readAnswer, type FormValue } from "./asking";

const fieldsOf = (fields: Record<string, Record<string, unknown>>, required: string[] = []) => formFields({ fields, required });

function answer(fields: Record<string, Record<string, unknown>>, values: Record<string, FormValue>, required: string[] = []) {
  const form = fieldsOf(fields, required);

  return readAnswer(form, { ...initialValues(form), ...values });
}

describe("the fields of a question's form", () => {
  it("are made of the schemas the server gave, in the order it gave them", () => {
    const fields = fieldsOf(
      {
        name: { type: "string", title: "Sample name", description: "What to call it." },
        copies: { type: "integer" },
        weight: { type: "number" },
        fresh: { type: "boolean" },
        kind: { type: "string", enum: ["dna", "rna"] },
        tags: { type: "array", items: { type: "string" } },
      },
      ["name"],
    );

    expect(fields.map((field) => [field.name, field.label, field.kind, field.required])).toEqual([
      ["name", "Sample name", "string", true],
      ["copies", "copies", "integer", false],
      ["weight", "weight", "number", false],
      ["fresh", "fresh", "boolean", false],
      ["kind", "kind", "choice", false],
      ["tags", "tags", "array", false],
    ]);
    expect(fields[0].description).toBe("What to call it.");
  });

  it("take a type that is not one they know, or none, for text", () => {
    expect(fieldsOf({ a: {}, b: { type: ["string", "null"] }, c: { type: "object" } }).map((field) => field.kind)).toEqual([
      "string",
      "string",
      "string",
    ]);
  });

  it("are choices where the schema lists the values, with their titles where it gives them", () => {
    const [plain, titled, any] = fieldsOf({
      a: { enum: ["x", 2, true] },
      b: { oneOf: [{ const: "dna", title: "DNA" }, { const: "rna" }] },
      c: { anyOf: [{ const: 1, title: "One" }] },
    });

    expect(plain.options).toEqual([
      { value: "x", label: "x" },
      { value: 2, label: "2" },
      { value: true, label: "true" },
    ]);
    expect(titled.options).toEqual([
      { value: "dna", label: "DNA" },
      { value: "rna", label: "rna" },
    ]);
    expect(any.options).toEqual([{ value: 1, label: "One" }]);
    expect([plain, titled, any].map((field) => field.kind)).toEqual(["choice", "choice", "choice"]);
  });

  it("are not choices where some of the options name no value", () => {
    expect(fieldsOf({ a: { oneOf: [{ const: 1 }, { type: "string" }] } })[0].kind).toBe("string");
  });

  it("take the options of a list from its items", () => {
    const [list] = fieldsOf({ a: { type: "array", items: { enum: ["a", "b"] } } });

    expect([list.kind, list.options.map((option) => option.value)]).toEqual(["array", ["a", "b"]]);
  });

  it("start from what the schema says they are by default", () => {
    const form = fieldsOf({
      name: { type: "string", default: "S1" },
      copies: { type: "integer", default: 3 },
      fresh: { type: "boolean", default: true },
      stale: { type: "boolean" },
      kind: { enum: ["dna", "rna"], default: "rna" },
      other: { enum: ["dna", "rna"], default: "none" },
      tags: { type: "array", items: { type: "string" }, default: ["a", "b"] },
      picks: { type: "array", items: { enum: ["a", "b", "c"] }, default: ["c", "z", "a"] },
      bad: { type: "integer", default: "three" },
    });

    expect(initialValues(form)).toEqual({
      name: "S1",
      copies: "3",
      fresh: true,
      stale: false,
      kind: "1",
      other: "",
      tags: "a, b",
      picks: ["2", "0"],
      bad: "",
    });
  });

  it("do not take 1 for true, or the reverse, as a choice's default", () => {
    expect(initialValues(fieldsOf({ a: { enum: [true, 1], default: 1 } }))).toEqual({ a: "1" });
  });
});

describe("an answer to a question", () => {
  it("is what the form is filled in with, by the name of each field", () => {
    const result = answer(
      {
        name: { type: "string" },
        copies: { type: "integer" },
        weight: { type: "number" },
        fresh: { type: "boolean" },
        kind: { enum: ["dna", "rna"] },
        tags: { type: "array", items: { type: "string" } },
        picks: { type: "array", items: { enum: [1, 2, 3] } },
      },
      { name: "S 1", copies: "2", weight: "0.5", fresh: true, kind: "1", tags: "a, b ,,c", picks: ["2", "0"] },
    );

    expect(result).toEqual({
      ok: true,
      answer: { name: "S 1", copies: 2, weight: 0.5, fresh: true, kind: "rna", tags: ["a", "b", "c"], picks: [3, 1] },
    });
  });

  it("gives a choice back as the value it was, not as text", () => {
    expect(answer({ n: { enum: [10, 20] } }, { n: "1" })).toEqual({ ok: true, answer: { n: 20 } });
    expect(answer({ n: { enum: [true, false] } }, { n: "0" })).toEqual({ ok: true, answer: { n: true } });
  });

  it("always says yes or no for a field of that kind", () => {
    expect(answer({ fresh: { type: "boolean" } }, {})).toEqual({ ok: true, answer: { fresh: false } });
    expect(answer({ fresh: { type: "boolean", default: true } }, {})).toEqual({ ok: true, answer: { fresh: true } });
  });

  it("is empty for a form with no fields", () => {
    expect(answer({}, {})).toEqual({ ok: true, answer: {} });
  });

  it("leaves out a field that is empty if it need not be filled in, whatever it is", () => {
    const fields = {
      name: { type: "string" },
      copies: { type: "integer" },
      kind: { enum: ["a"] },
      tags: { type: "array", items: { type: "string" } },
      picks: { type: "array", items: { enum: ["a"] } },
    };

    expect(answer(fields, {})).toEqual({ ok: true, answer: {} });
    expect(answer(fields, { name: "   ", copies: "  ", tags: " , " })).toEqual({ ok: true, answer: {} });
  });

  it("says which fields that must be filled in are not", () => {
    const result = answer(
      {
        name: { type: "string" },
        copies: { type: "integer" },
        kind: { enum: ["a"] },
        tags: { type: "array", items: { type: "string" } },
        picks: { type: "array", items: { enum: ["a"] } },
        fresh: { type: "boolean" },
      },
      { name: "  " },
      ["name", "copies", "kind", "tags", "picks", "fresh"],
    );

    expect(result).toEqual({
      ok: false,
      errors: {
        name: "name must be filled in",
        copies: "copies must be filled in",
        kind: "kind must be filled in",
        tags: "tags must be filled in",
        picks: "picks must be filled in",
      },
    });
  });

  it("names a field by its title in what is wrong with it", () => {
    expect(answer({ n: { type: "integer", title: "Copies" } }, {}, ["n"])).toEqual({ ok: false, errors: { n: "Copies must be filled in" } });
  });

  it("keeps text as it was typed, spaces and all, and does not take empty text for an answer", () => {
    expect(answer({ n: { type: "string" } }, { n: "  hi " })).toEqual({ ok: true, answer: { n: "  hi " } });
  });

  it("takes whole numbers that are whole numbers, and no other number or text", () => {
    for (const text of ["7", "-7", "+7", " 7 "]) {
      expect(answer({ n: { type: "integer" } }, { n: text })).toEqual({ ok: true, answer: { n: Number(text) } });
    }
    for (const text of ["7.5", "7e2", "0x10", "seven", "1 2", "99999999999999999999"]) {
      expect(answer({ n: { type: "integer" } }, { n: text })).toEqual({ ok: false, errors: { n: "n is a whole number" } });
    }
  });

  it("takes numbers that are numbers, and no text, infinity, or hexadecimal", () => {
    for (const [text, value] of [["7", 7], ["-0.5", -0.5], [".5", 0.5], ["5.", 5], ["1e3", 1000], ["2E-2", 0.02]] as const) {
      expect(answer({ n: { type: "number" } }, { n: text })).toEqual({ ok: true, answer: { n: value } });
    }
    for (const text of ["Infinity", "NaN", "0x10", "1,5", "five", "1e999", "--1"]) {
      expect(answer({ n: { type: "number" } }, { n: text })).toEqual({ ok: false, errors: { n: "n is a number" } });
    }
  });

  it("takes each item of a list as the kind the items are", () => {
    expect(answer({ n: { type: "array", items: { type: "integer" } } }, { n: "1, 2,3" })).toEqual({ ok: true, answer: { n: [1, 2, 3] } });
    expect(answer({ n: { type: "array", items: { type: "number" } } }, { n: "1.5" })).toEqual({ ok: true, answer: { n: [1.5] } });
    expect(answer({ n: { type: "array", items: { type: "boolean" } } }, { n: "yes, no, True" })).toEqual({
      ok: true,
      answer: { n: [true, false, true] },
    });
    expect(answer({ n: { type: "array", items: { type: "integer" } } }, { n: "1, x" })).toEqual({
      ok: false,
      errors: { n: "n is a whole number" },
    });
    expect(answer({ n: { type: "array", items: { type: "boolean" } } }, { n: "maybe" })).toEqual({
      ok: false,
      errors: { n: "n is yes or no" },
    });
  });

  it("says what is wrong with each field that is wrong, and gives no answer", () => {
    expect(
      answer({ a: { type: "integer" }, b: { type: "number" }, c: { type: "string" } }, { a: "x", b: "y", c: "fine" }),
    ).toEqual({ ok: false, errors: { a: "a is a whole number", b: "b is a number" } });
  });

  it("does not take a choice that is not one of the options", () => {
    expect(answer({ n: { enum: ["a", "b"] } }, { n: "5" }, ["n"])).toEqual({ ok: false, errors: { n: "n must be filled in" } });
    expect(answer({ n: { enum: ["a", "b"] } }, { n: "-1" })).toEqual({ ok: true, answer: {} });
    expect(answer({ n: { enum: ["a", "b"] } }, { n: "0.5" })).toEqual({ ok: true, answer: {} });
    expect(answer({ n: { type: "array", items: { enum: ["a", "b"] } } }, { n: ["7", "x"] })).toEqual({ ok: true, answer: {} });
  });
});

describe("a web address", () => {
  it("is an http or https address with a host", () => {
    expect(isWebAddress("https://example.org/consent?x=1")).toBe(true);
    expect(isWebAddress("http://localhost:8080/")).toBe(true);
  });

  it("is not anything else, which a link must not be sent to", () => {
    for (const url of [null, "", "javascript:alert(1)", "data:text/html,<b>x</b>", "file:///etc/passwd", "ftp://example.org", "example.org", "https://", "//example.org"]) {
      expect(isWebAddress(url)).toBe(false);
    }
  });
});
