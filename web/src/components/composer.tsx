"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowUp, Paperclip, Pause, Play, Square } from "lucide-react";
import { AttachmentTray } from "@/components/attachment-tray";
import { Button } from "@/components/ui/button";
import type { TrayItem } from "@/lib/attachments";
import { controlsFor } from "@/lib/steering";
import type { ChatState } from "@/lib/types";
import { cn } from "@/lib/utils";

// The files that go with the next message, for the composer to show and to take more of
export interface ComposerFiles {
  items: TrayItem[];
  onAdd: (files: File[]) => void;
  onRemove: (id: number) => void;
  onRetry: (id: number) => void;
}

interface ComposerProps {
  value: string;
  onValueChange: (value: string) => void;
  // Sends what is written as a message. The draft is the parent's to clear, once what it was sent for has been done
  onSend: () => void;
  // Where the conversation stands. While the lead is at work, what is written is a note it reads before its next step,
  // and the way to hold it, let it go on, or stop it is here.
  state?: ChatState;
  onNote?: () => void;
  onPause?: () => void;
  onResume?: () => void;
  onStop?: () => void;
  // Whether a message is being sent, or cannot be
  disabled?: boolean;
  // What keeps a message from being sent as it is, in words, such as a file that is still going
  holdUp?: string | null;
  files?: ComposerFiles;
  autoFocus?: boolean;
  // What goes beside the buttons
  footer?: React.ReactNode;
  className?: string;
}

function hasFiles(dataTransfer: DataTransfer | null): boolean {
  return dataTransfer !== null && Array.from(dataTransfer.types).includes("Files");
}

export function Composer({
  value,
  onValueChange,
  onSend,
  state = "idle",
  onNote,
  onPause,
  onResume,
  onStop,
  disabled = false,
  holdUp = null,
  files,
  autoFocus = false,
  footer,
  className,
}: ComposerProps) {
  const input = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const controls = controlsFor(state);
  const empty = value.trim() === "";
  const messaging = controls.writes === "message";
  const withFiles = files?.items.some((item) => item.status === "ready" || item.status === "queued") ?? false;
  const canSend = !disabled && holdUp === null && (!empty || withFiles);
  const canNote = !disabled && controls.canNote && !empty;

  useEffect(() => {
    if (autoFocus) input.current?.focus();
  }, [autoFocus]);

  // The box is as tall as what is in it, up to its limit, in browsers that cannot do that by themselves
  useLayoutEffect(() => {
    const box = input.current;
    if (box === null) return;
    box.style.height = "auto";
    box.style.height = `${box.scrollHeight}px`;
  }, [value]);

  function take(chosen: File[]) {
    if (chosen.length > 0 && !disabled) files?.onAdd(chosen);
  }

  return (
    <form
      data-dragging={dragging}
      className={cn(
        "flex flex-col gap-2 rounded-2xl border border-input bg-card p-2.5 shadow-sm transition-shadow focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/25 data-[dragging=true]:border-dashed data-[dragging=true]:border-brand",
        className,
      )}
      onSubmit={(event) => {
        event.preventDefault();
        if (messaging) {
          if (canSend) onSend();
        } else if (canNote) {
          onNote?.();
        }
      }}
      // A file that is dropped anywhere on the composer is taken, rather than opened in place of the page
      onDragOver={(event) => {
        if (files === undefined || !hasFiles(event.dataTransfer)) return;
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
      }}
      onDrop={(event) => {
        if (files === undefined || !hasFiles(event.dataTransfer)) return;
        event.preventDefault();
        setDragging(false);
        take(Array.from(event.dataTransfer.files));
      }}
    >
      {files && (
        <AttachmentTray items={files.items} disabled={disabled} onRemove={files.onRemove} onRetry={files.onRetry} />
      )}
      <textarea
        ref={input}
        aria-label="Message"
        rows={1}
        value={value}
        placeholder={controls.placeholder}
        onChange={(event) => onValueChange(event.target.value)}
        onKeyDown={(event) => {
          // Enter that picks a character of an input method is not a message
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        onPaste={(event) => {
          // Files that are pasted are attached, unless there is text with them, which is what is meant to be pasted
          const pasted = Array.from(event.clipboardData.files);
          if (files === undefined || pasted.length === 0 || event.clipboardData.types.includes("text/plain")) return;
          event.preventDefault();
          take(pasted);
        }}
        className="max-h-60 min-h-11 w-full resize-none bg-transparent px-1.5 py-1 text-[15px] leading-6 outline-none placeholder:text-muted-foreground"
      />
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5">
          {files && (
            <>
              <input
                ref={picker}
                type="file"
                multiple
                hidden
                data-testid="file-input"
                onChange={(event) => {
                  take(Array.from(event.target.files ?? []));
                  // The same file chosen again is a change too
                  event.target.value = "";
                }}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label="Attach files"
                disabled={disabled}
                onClick={() => picker.current?.click()}
                className="rounded-full text-muted-foreground"
              >
                <Paperclip />
              </Button>
            </>
          )}
          <div className="min-w-0 flex-1 truncate text-xs text-muted-foreground" aria-live="polite">
            {holdUp ?? footer}
          </div>
        </div>
        {messaging ? (
          <Button type="submit" size="icon" aria-label="Send" disabled={!canSend} className="rounded-full">
            <ArrowUp className="size-4" />
          </Button>
        ) : (
          <div className="flex items-center gap-1.5">
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label={controls.pause === "pause" ? "Pause" : "Resume"}
              disabled={!controls.canPause}
              onClick={controls.pause === "pause" ? onPause : onResume}
              className="rounded-full"
            >
              {controls.pause === "pause" ? <Pause className="size-3.5 fill-current" /> : <Play className="size-3.5 fill-current" />}
            </Button>
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label="Stop"
              disabled={!controls.canStop}
              onClick={onStop}
              className="rounded-full"
            >
              <Square className="size-3.5 fill-current" />
            </Button>
            <Button type="submit" size="icon" aria-label="Add note" disabled={!canNote} className="rounded-full">
              <ArrowUp className="size-4" />
            </Button>
          </div>
        )}
      </div>
    </form>
  );
}
