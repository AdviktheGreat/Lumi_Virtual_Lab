"use client";

import { useEffect, useRef, useState } from "react";
import { api, type FileText } from "./api";
import type { ChatFile } from "./types";

// How long after the last thing that may have changed a file the list is asked for again, so that code that runs often
// is not followed by as many requests
const SETTLE_MS = 300;

export interface Listed {
  files: ChatFile[];
  truncated: boolean;
  // Whether the list has come once
  loaded: boolean;
  // Why the last attempt to get it failed, which is nothing if it did not
  error: unknown;
}

const none: Listed = { files: [], truncated: false, loaded: false, error: null };

// The files of a conversation, which are got again when what the conversation is up to may have changed them: the
// number given is one that goes up when it may have. What is shown stays until what is newer comes.
export function useFiles(id: string, changed: number): Listed {
  const [listed, setListed] = useState<Listed>(none);
  const first = useRef(true);

  useEffect(() => {
    const abort = new AbortController();
    const wait = first.current ? 0 : SETTLE_MS;
    first.current = false;
    const timer = setTimeout(() => {
      api.files(id, abort.signal).then(
        (found) => setListed({ files: found.files, truncated: found.truncated, loaded: true, error: null }),
        (error: unknown) => {
          if (!abort.signal.aborted) setListed((was) => ({ ...was, error }));
        },
      );
    }, wait);

    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [id, changed]);

  return listed;
}

export type Reading =
  | { kind: "loading" }
  | { kind: "ready"; file: FileText }
  | { kind: "failed"; error: unknown };

type Read = { key: string; reading: Reading };

// How much of a file is read to show it
export const PREVIEW_BYTES = 200_000;

// What a file says, from its start. The file is read again when it has changed, which its size and the time it was
// changed tell.
export function useFileText(id: string, file: ChatFile): Reading {
  const key = `${file.path}\n${file.size}\n${file.modified}`;
  const [read, setRead] = useState<Read | null>(null);
  const { path } = file;

  useEffect(() => {
    const abort = new AbortController();
    api.fileText(id, path, PREVIEW_BYTES, abort.signal).then(
      (found) => setRead({ key, reading: { kind: "ready", file: found } }),
      (error: unknown) => {
        if (!abort.signal.aborted) setRead({ key, reading: { kind: "failed", error } });
      },
    );

    return () => abort.abort();
  }, [id, path, key]);

  return read !== null && read.key === key ? read.reading : { kind: "loading" };
}
