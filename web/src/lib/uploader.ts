import { api } from "./api";
import { attachedNames, canRetry, intake, tray, type TrayAction, type TrayItem } from "./attachments";
import { describeError } from "./errors";
import type { Attachment } from "./types";

type Send = (
  chatId: string,
  file: File,
  options: { signal: AbortSignal; onProgress: (fraction: number) => void },
) => Promise<Attachment>;

// The files to go with a message, and the sending of them. It holds the tray itself, so that what it does next is never
// based on a tray that has not caught up with what it did last.
export interface Uploader {
  items: () => TrayItem[];
  // Calls the listener when the tray changes, and returns what stops it being called
  subscribe: (listener: () => void) => () => void;
  // Takes the files chosen, and says in words why any of them was not. With a conversation to send them to, each goes
  // at once.
  choose: (files: File[], chatId: string | null, limit: number | null) => string[];
  // Tries a file that failed again, or, with no conversation to send it to, leaves it to be sent with the others
  retry: (id: number, chatId: string | null) => void;
  // Takes the files away, calling off those that are on their way
  remove: (ids: number[]) => void;
  // Calls off every file that is on its way, which is for when what they were for is gone
  cancelAll: () => void;
  // Waits for the files that have been sent to be sent again, as they must be to a conversation that is not the one
  // they went to
  requeue: () => void;
  // Sends the files that are waiting, and gives the name of every file there is once they have all been taken
  upload: (chatId: string) => Promise<string[]>;
}

export function createUploader(send: Send = api.upload): Uploader {
  const sending = new Map<number, AbortController>();
  const listeners = new Set<() => void>();
  let items: TrayItem[] = [];
  let numbered = 0;

  function happen(action: TrayAction) {
    items = tray(items, action);
    listeners.forEach((listener) => listener());
  }

  // Sends a file, and says how it is getting on until it has been taken or has failed, in which case this raises why
  function start(item: TrayItem, chatId: string): Promise<Attachment> {
    const controller = new AbortController();
    sending.set(item.id, controller);
    happen({ type: "begin", id: item.id });

    return send(chatId, item.file, {
      signal: controller.signal,
      onProgress: (progress) => happen({ type: "progress", id: item.id, progress }),
    })
      .then(
        (attachment) => {
          happen({ type: "ready", id: item.id, attachment });

          return attachment;
        },
        (error: unknown) => {
          // A file that was called off is no longer in the tray to be told that it failed
          happen({ type: "fail", id: item.id, error: describeError(error), retryable: canRetry(error) });
          throw error;
        },
      )
      .finally(() => sending.delete(item.id));
  }

  return {
    items: () => items,
    subscribe(listener) {
      listeners.add(listener);

      return () => {
        listeners.delete(listener);
      };
    },
    choose(files, chatId, limit) {
      const { items: added, refused } = intake(items, files, limit, numbered);
      numbered += files.length;
      if (added.length > 0) happen({ type: "add", items: added });
      if (chatId !== null) {
        for (const item of added) start(item, chatId).catch(() => undefined);
      }

      return refused;
    },
    retry(id, chatId) {
      const item = items.find((candidate) => candidate.id === id);
      if (item === undefined || item.status !== "failed") return;
      if (chatId === null) {
        happen({ type: "requeue", ids: [id] });
      } else {
        start(item, chatId).catch(() => undefined);
      }
    },
    remove(ids) {
      for (const id of ids) sending.get(id)?.abort();
      happen({ type: "remove", ids });
    },
    cancelAll() {
      for (const controller of sending.values()) controller.abort();
    },
    requeue() {
      happen({ type: "requeueReady" });
    },
    async upload(chatId) {
      const waiting = items.filter((item) => item.status === "queued");
      // Every file is given the time to finish before an error is raised, so that none is left going to a conversation
      // that its owner is about to take away
      const settled = await Promise.allSettled(waiting.map((item) => start(item, chatId)));
      const failed = settled.find((result): result is PromiseRejectedResult => result.status === "rejected");
      if (failed !== undefined) throw failed.reason;

      return attachedNames(items);
    },
  };
}
