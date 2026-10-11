// Rows of a table written as text, with its cells divided by a comma or a tab. A cell may be in quotes, which is where it
// may hold the divider, a new line, or a quote written twice.
export function parseTable(text: string, divider: string, limits: { rows: number; columns: number }): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  let started = false;

  const endCell = () => {
    row.push(cell);
    cell = "";
  };
  const endRow = () => {
    endCell();
    rows.push(row);
    row = [];
    started = false;
  };

  for (let at = 0; at < text.length && rows.length < limits.rows; at += 1) {
    const letter = text[at];
    if (quoted) {
      if (letter !== '"') {
        cell += letter;
      } else if (text[at + 1] === '"') {
        cell += '"';
        at += 1;
      } else {
        quoted = false;
      }
    } else if (letter === '"' && cell === "") {
      quoted = true;
      started = true;
    } else if (letter === divider) {
      endCell();
      started = true;
    } else if (letter === "\n" || letter === "\r") {
      if (letter === "\r" && text[at + 1] === "\n") at += 1;
      endRow();
    } else {
      cell += letter;
      started = true;
    }
  }
  // What came after the last new line, if there is anything
  if (started || cell !== "") endRow();

  return rows.map((each) => each.slice(0, limits.columns));
}

export interface ReadTable {
  header: string[];
  rows: string[][];
  // Whether there was more than is given, in rows, in columns, or in the file past what was read
  cut: boolean;
}

// The most of a table that is shown
export const TABLE_LIMITS = { rows: 200, columns: 40 };

// A table to be shown: its first row as the header and the rows after it, as many as the limits allow. Text that was cut
// off where it was read from may end in the middle of a row, which is left out.
export function readTable(text: string, divider: string, truncated: boolean, limits = TABLE_LIMITS): ReadTable {
  // One more than is shown of each, which says if there was more
  const parsed = parseTable(text, divider, { rows: limits.rows + 2, columns: limits.columns + 1 });
  let cut = truncated;
  let rows = parsed;
  if (parsed.length > limits.rows + 1) {
    rows = parsed.slice(0, limits.rows + 1);
    cut = true;
  } else if (truncated) {
    rows = parsed.slice(0, -1);
  }
  if (rows.some((row) => row.length > limits.columns)) {
    rows = rows.map((row) => row.slice(0, limits.columns));
    cut = true;
  }

  return { header: rows[0] ?? [], rows: rows.slice(1), cut };
}
