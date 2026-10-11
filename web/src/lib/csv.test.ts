import { describe, expect, it } from "vitest";
import { parseTable, readTable, TABLE_LIMITS } from "./csv";

const all = { rows: 1000, columns: 1000 };

describe("a table in text", () => {
  it("is its rows, each of its cells", () => {
    expect(parseTable("gene,count\nTP53,12\nBRCA1,7\n", ",", all)).toEqual([
      ["gene", "count"],
      ["TP53", "12"],
      ["BRCA1", "7"],
    ]);
  });

  it("divides by a tab as well, which leaves commas alone", () => {
    expect(parseTable("a,b\tc\n1\t2", "\t", all)).toEqual([
      ["a,b", "c"],
      ["1", "2"],
    ]);
  });

  it("has the last row though no new line ends it, and none for the new line that ends the last", () => {
    expect(parseTable("a,b\n1,2", ",", all)).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
    expect(parseTable("a,b\n", ",", all)).toEqual([["a", "b"]]);
    expect(parseTable("", ",", all)).toEqual([]);
  });

  it("takes a Windows or old Mac line end for one", () => {
    expect(parseTable("a,b\r\n1,2\r3,4\r\n", ",", all)).toEqual([
      ["a", "b"],
      ["1", "2"],
      ["3", "4"],
    ]);
  });

  it("holds what is in quotes whole: the divider, new lines, and a quote written twice", () => {
    expect(parseTable('name,note\n"Smith, J","said ""no""\nthen left"\n', ",", all)).toEqual([
      ["name", "note"],
      ["Smith, J", 'said "no"\nthen left'],
    ]);
  });

  it("leaves a quote that is inside a cell alone, and keeps empty cells and empty rows' places", () => {
    expect(parseTable('5" pipe,,x\n\n,,\n', ",", all)).toEqual([['5" pipe', "", "x"], [""], ["", "", ""]]);
  });

  it("has a quoted empty cell as the last of the text", () => {
    expect(parseTable('a,""', ",", all)).toEqual([["a", ""]]);
  });

  it("stops at the rows it is limited to, and drops the columns it is limited to", () => {
    expect(parseTable("1,2,3\n4,5,6\n7,8,9", ",", { rows: 2, columns: 2 })).toEqual([
      ["1", "2"],
      ["4", "5"],
    ]);
    expect(parseTable("1,2\n3,4\n", ",", { rows: 2, columns: 5 })).toHaveLength(2);
  });

  it("reads no more rows than the limit, though the text has more, with or without a new line at its end", () => {
    expect(parseTable("1\n2\n3\n4\n", ",", { rows: 2, columns: 5 })).toEqual([["1"], ["2"]]);
    expect(parseTable("1\n2\n3", ",", { rows: 2, columns: 5 })).toEqual([["1"], ["2"]]);
    expect(parseTable("1\n2\n3", ",", { rows: 0, columns: 5 })).toEqual([]);
  });
});

describe("a table to be shown", () => {
  const limits = { rows: 2, columns: 3 };

  it("is its first row as the header and the rows after it", () => {
    expect(readTable("a,b\n1,2\n3,4\n", ",", false, limits)).toEqual({
      header: ["a", "b"],
      rows: [
        ["1", "2"],
        ["3", "4"],
      ],
      cut: false,
    });
  });

  it("is said to be cut where there are more rows than the limit, which are as many as it says and no more", () => {
    const table = readTable("a\n1\n2\n3\n4\n", ",", false, limits);

    expect(table.rows).toEqual([["1"], ["2"]]);
    expect(table.cut).toBe(true);
    // As many as the limit is not more than it
    expect(readTable("a\n1\n2\n", ",", false, limits)).toMatchObject({ rows: [["1"], ["2"]], cut: false });
  });

  it("is said to be cut where a row has more columns than the limit, which are left out", () => {
    const table = readTable("a,b,c,d\n1,2,3,4\n", ",", false, limits);

    expect(table).toEqual({ header: ["a", "b", "c"], rows: [["1", "2", "3"]], cut: true });
    expect(readTable("a,b,c\n1,2,3\n", ",", false, limits).cut).toBe(false);
  });

  it("leaves out the last row of text that was cut off, which may be half of one, and says it was cut", () => {
    const table = readTable("a,b\n1,2\n3,", ",", true, limits);

    expect(table).toEqual({ header: ["a", "b"], rows: [["1", "2"]], cut: true });
  });

  it("keeps all the rows of cut text when there are more than the limit, none of which can be half of one", () => {
    const table = readTable("a\n1\n2\n3\n4", ",", true, limits);

    expect(table.rows).toEqual([["1"], ["2"]]);
    expect(table.cut).toBe(true);
  });

  it("has nothing for text with nothing in it, or whose first row was cut off", () => {
    expect(readTable("", ",", false, limits)).toEqual({ header: [], rows: [], cut: false });
    expect(readTable("a,b", ",", true, limits)).toEqual({ header: [], rows: [], cut: true });
  });

  it("is limited as it should be by default", () => {
    const text = `${Array.from({ length: 300 }, (_, row) => Array.from({ length: 60 }, (_, column) => `${row}.${column}`).join(",")).join("\n")}\n`;
    const table = readTable(text, ",", false);

    // The most that the page says it shows
    expect(TABLE_LIMITS).toEqual({ rows: 200, columns: 40 });
    expect(table.rows).toHaveLength(200);
    expect(table.header).toHaveLength(40);
    expect(table.cut).toBe(true);
  });
});
