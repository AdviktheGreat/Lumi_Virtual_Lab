// Where a conversation's files are, which the server sends with a type that runs nothing, so that a page may show
// what the agents' code wrote

const IMAGE_TYPES = /\.(png|jpe?g|gif|webp|svg)$/i;

export function isImage(path: string): boolean {
  return IMAGE_TYPES.test(path);
}

// The address of a file, by its path from the conversation's files
export function fileUrl(chatId: string, path: string, download = false): string {
  const encoded = path.split("/").map(encodeURIComponent).join("/");

  return `/api/chats/${encodeURIComponent(chatId)}/files/${encoded}${download ? "?download=true" : ""}`;
}

// A path from where the code ran, tidied, if it stays inside the conversation's files: nothing that starts from the
// root, goes up a directory, or is not a path on any system
export function insidePath(path: string): string | null {
  if (path.startsWith("/")) return null;
  const parts = path.split("/").filter((part) => part !== "" && part !== ".");
  if (parts.length === 0 || parts.some((part) => part === ".." || part.includes("\\") || part.includes("\0"))) {
    return null;
  }

  return parts.join("/");
}

// What an address in an answer names, if it names a file of the conversation: a path, with nothing in front of it that
// would take the page elsewhere
export function localPath(address: string): string | null {
  const given = address.trim();
  if (given === "" || /^[a-z][a-z0-9+.-]*:/i.test(given)) {
    return null;
  }
  try {
    return insidePath(decodeURI(given.split(/[?#]/)[0]));
  } catch {
    return null;
  }
}

// A size, as a person would say it
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }

  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}
