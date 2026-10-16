// Saving a conversation as a document: what it can be saved as, the name the server gives the file, and handing the file
// to the browser to be saved

export type ExportFormat = "html" | "pdf" | "ipynb";

export interface ExportChoice {
  format: ExportFormat;
  label: string;
  hint: string;
}

export const EXPORT_CHOICES: ExportChoice[] = [
  { format: "html", label: "A web page", hint: "Opens in any browser, with the figures in it" },
  { format: "pdf", label: "A PDF", hint: "To print, or to send" },
  { format: "ipynb", label: "A notebook", hint: "Opens in Jupyter, with the code, what it printed, and the figures" },
];

// What the server sent the file's name as, if it did, taken from the header that says how the file is to be saved.
// The server sends it twice: as the header says to send one that is not ASCII (filename*=utf-8''…), which is the whole
// name and so the one taken, and plain, without what is not ASCII, which is taken where the first is not as it says.
function namedIn(disposition: string | null): string | null {
  if (disposition === null) return null;
  const encoded = /(?:^|;)\s*filename\*\s*=\s*([^;]+)/i.exec(disposition);
  if (encoded) {
    const value = encoded[1].trim();
    const parts = /^[^']*'[^']*'(.*)$/.exec(value);
    try {
      return decodeURIComponent(parts ? parts[1] : value);
    } catch {
      // Not encoded as it says it is, so the plain name, if there is one, is the one to take
    }
  }
  const plain = /(?:^|;)\s*filename\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]+))/i.exec(disposition);
  if (!plain) return null;

  return plain[1] !== undefined ? plain[1].replace(/\\(.)/g, "$1") : plain[2].trim();
}

// The name to save the file as: the server's, with nothing in it that is not for a file name, or one made here where the
// server gave none
export function exportNameOf(disposition: string | null, format: ExportFormat): string {
  const name = (namedIn(disposition) ?? "")
    .replace(/[\u0000-\u001f\u007f/\\]+/g, "-")
    .trim();

  return name === "" || name.startsWith(".") ? `conversation.${format}` : name;
}

// Gives the browser a file to save, which it does as it does for a link that downloads
export function saveFile(file: Blob, name: string): void {
  const address = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = address;
  link.download = name;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  // Not at once, which could be before the browser has begun to save it
  setTimeout(() => URL.revokeObjectURL(address), 30_000);
}
