"use client";

import { createContext, useContext } from "react";
import { fileUrl, insidePath } from "@/lib/files";

// The conversation whose files are shown, so that a figure or a link in an answer can be given its address
const ChatId = createContext<string | null>(null);

export const ChatFilesProvider = ChatId.Provider;

// The address of a file of the conversation, or null where there is no conversation, or the path is not inside its
// files, which a server of another version, or a model, may name
export function useFileUrl(): (path: string, download?: boolean) => string | null {
  const id = useContext(ChatId);

  return (path, download = false) => {
    const inside = insidePath(path);

    return id === null || inside === null ? null : fileUrl(id, inside, download);
  };
}
