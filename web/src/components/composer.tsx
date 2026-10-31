"use client";

import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowUp, Paperclip, Pause, Play, Slash, Square } from "lucide-react";
import { AttachmentTray } from "@/components/attachment-tray";
import { SlashMenu } from "@/components/slash-menu";
import { Button } from "@/components/ui/button";
import type { TrayItem } from "@/lib/attachments";
import { rowsFor, type Invocation, type Place, type Row } from "@/lib/commands";
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

// The commands that can be written in the box, which is a slash and a name
export interface ComposerCommands {
  place: Place;
  // How many turns the conversation has had, and how many of them the lead answered
  turns: number;
  answered: number;
  // Why the conversation cannot be given each command that goes with a message, once there is one
  directives?: Record<string, string | null> | null;
  onRun: (invocation: Invocation) => void;
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
  commands?: ComposerCommands;
  autoFocus?: boolean;
  // What goes beside the buttons
  footer?: React.ReactNode;
  // Room for a longer message, as the box of a conversation that is not yet begun has
  roomy?: boolean;
  className?: string;
}

function hasFiles(dataTransfer: DataTransfer | null): boolean {
  return dataTransfer !== null && Array.from(dataTransfer.types).includes("Files");
}

// The row to light for where the highlight is: the one it is on if that can be chosen, or the next that can, and none if none can
function litRow(rows: Row[], at: number): number {
  const from = Math.min(Math.max(at, 0), rows.length - 1);
  if (rows[from].reason === null) return from;
  const next = rows.findIndex((row, index) => index > from && row.reason === null);

  return next >= 0 ? next : rows.findIndex((row) => row.reason === null);
}

// The row a step up or down from the lit one lands on, going round, over those that cannot be chosen
function stepRow(rows: Row[], from: number, by: 1 | -1): number {
  if (from < 0) return 0;
  for (let step = 1; step <= rows.length; step += 1) {
    const at = (((from + by * step) % rows.length) + rows.length) % rows.length;
    if (rows[at].reason === null) return at;
  }

  return from;
}

// What Tab writes in the box for a row: the command as the row has it, with room to go on where it takes something, and
// what has been written already where that is the same command with the words it takes
function completion(row: Row, written: string): string {
  if ("fill" in row.action) return row.action.fill;

  return written.toLowerCase().startsWith(row.label.toLowerCase()) ? written : row.label;
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
  commands,
  autoFocus = false,
  footer,
  roomy = false,
  className,
}: ComposerProps) {
  const input = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  // Where the menu of commands has the highlight, and the words it was put away at, which are shown it again once they change
  const [cursor, setCursor] = useState(0);
  const [putAwayAt, setPutAwayAt] = useState<string | null>(null);
  const menuId = useId();
  const controls = controlsFor(state);
  const place = commands?.place;
  const turns = commands?.turns ?? 0;
  const answered = commands?.answered ?? 0;
  const directives = commands?.directives ?? null;
  const rows = useMemo(
    () =>
      place === undefined || putAwayAt === value ? [] : rowsFor(value, { place, state, turns, answered, holdUp, directives }),
    [place, state, turns, answered, holdUp, directives, value, putAwayAt],
  );
  const menuOpen = rows.length > 0;
  const lit = menuOpen ? litRow(rows, cursor) : -1;
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

  function change(next: string) {
    setCursor(0);
    onValueChange(next);
  }

  // A command that is chosen is run, or begun in the box where it takes something to be finished
  function pick(row: Row) {
    if (row.reason !== null || disabled) return;
    input.current?.focus();
    if ("fill" in row.action) {
      change(row.action.fill);
    } else {
      change("");
      commands?.onRun(row.action.run);
    }
  }

  return (
    <form
      data-dragging={dragging}
      className={cn(
        "relative flex flex-col gap-2 rounded-3xl border border-input bg-card p-3 shadow-sm transition-shadow focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/25 data-[dragging=true]:border-dashed data-[dragging=true]:border-brand",
        className,
      )}
      onSubmit={(event) => {
        event.preventDefault();
        // While commands are offered, sending is choosing one, and where none can be chosen it is nothing
        if (menuOpen) {
          if (lit >= 0) pick(rows[lit]);
        } else if (messaging) {
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
        onChange={(event) => change(event.target.value)}
        aria-autocomplete={menuOpen ? "list" : undefined}
        aria-controls={menuOpen ? menuId : undefined}
        aria-activedescendant={lit >= 0 ? `${menuId}-${lit}` : undefined}
        onKeyDown={(event) => {
          if (menuOpen && !event.nativeEvent.isComposing) {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              setCursor(stepRow(rows, lit, event.key === "ArrowDown" ? 1 : -1));

              return;
            }
            if (event.key === "Escape") {
              event.preventDefault();
              setPutAwayAt(value);

              return;
            }
            if (event.key === "Tab" && !event.shiftKey && lit >= 0) {
              event.preventDefault();
              change(completion(rows[lit], value));

              return;
            }
          }
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
        className={cn(
          "max-h-60 w-full resize-none bg-transparent px-1.5 py-1 text-[15px] leading-6 outline-none placeholder:text-muted-foreground",
          roomy ? "min-h-24" : "min-h-11",
        )}
      />
      {menuOpen && <SlashMenu id={menuId} rows={rows} lit={lit} onLight={setCursor} onPick={pick} />}
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
          {commands && (
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Commands"
              aria-pressed={value === "/"}
              disabled={disabled || (value !== "" && value !== "/")}
              title={value !== "" && value !== "/" ? "Commands are written in an empty box, which begins with a slash" : "Commands"}
              data-testid="commands-button"
              onClick={() => {
                input.current?.focus();
                change(value === "/" ? "" : "/");
              }}
              className="rounded-full text-muted-foreground"
            >
              <Slash />
            </Button>
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
