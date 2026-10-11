"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import type { TrayItem } from "./attachments";
import { createUploader } from "./uploader";

export interface Attachments {
  items: TrayItem[];
  // Takes the files chosen, and says in words why any of them was not
  add: (files: File[]) => string[];
  // Takes the files away, calling off those that are on their way
  remove: (ids: number[]) => void;
  retry: (id: number) => void;
  // Sends the files that are waiting, which is for a conversation that was not there when they were chosen, and gives
  // the name of every file there is once they have all been taken
  upload: (chatId: string) => Promise<string[]>;
  // Waits for the files to be sent again, as they must be to a conversation that is not the one they were sent to
  requeue: () => void;
}

// The files to go with the researcher's next message. With a conversation to send them to, each goes as soon as it is
// chosen, so that it is there by the time the message is written; without one, they wait for upload.
export function useAttachments(chatId: string | null, limit: number | null): Attachments {
  const [uploader] = useState(() => createUploader());
  const items = useSyncExternalStore(uploader.subscribe, uploader.items, uploader.items);

  // Files that are still on their way are called off when the page that wants them goes
  useEffect(() => () => uploader.cancelAll(), [uploader]);

  const add = useCallback((files: File[]) => uploader.choose(files, chatId, limit), [uploader, chatId, limit]);
  const retry = useCallback((id: number) => uploader.retry(id, chatId), [uploader, chatId]);

  return { items, add, remove: uploader.remove, retry, upload: uploader.upload, requeue: uploader.requeue };
}
