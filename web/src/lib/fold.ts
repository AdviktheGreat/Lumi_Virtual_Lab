export interface Folding {
  // What is shown: all of the code, or its first lines
  text: string;
  // Whether there is enough past the first lines to be worth folding
  foldable: boolean;
  // How many lines are folded away, which is those past the first lines
  hidden: number;
}

// Code with the lines past the first few folded away. One line over is not worth a button that takes as much room as
// the line, so code is only folded where there are two or more past it.
export function fold(code: string, after: number | undefined, open: boolean): Folding {
  const lines = code.split("\n");
  const foldable = after !== undefined && lines.length > after + 1;
  if (!foldable) return { text: code, foldable: false, hidden: 0 };

  return { text: open ? code : lines.slice(0, after).join("\n"), foldable: true, hidden: lines.length - after };
}
