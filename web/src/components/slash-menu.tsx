"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Row } from "@/lib/commands";
import { cn } from "@/lib/utils";

// The commands that can be written in the box, over it, for the one that is lit to be chosen with Enter, or any with a
// click. The focus stays in the box, which is where the words that narrow the list are written, so the one that is lit is
// told to assistive technology through the box (aria-activedescendant), and each line has the id that is given there.
export function SlashMenu({
  id,
  rows,
  lit,
  onLight,
  onPick,
}: {
  id: string;
  rows: Row[];
  // The line that is lit, or -1 where none can be chosen
  lit: number;
  onLight: (at: number) => void;
  onPick: (row: Row) => void;
}) {
  const list = useRef<HTMLDivElement>(null);
  // A list that is longer than the room for it is scrolled, which is a part of the page that the keyboard can reach only if it
  // can be focused, so it can when it is that
  const [scrolls, setScrolls] = useState(false);

  useLayoutEffect(() => {
    const element = list.current;
    if (element !== null) setScrolls(element.scrollHeight > element.clientHeight);
  }, [rows]);

  useEffect(() => {
    if (lit >= 0) document.getElementById(`${id}-${lit}`)?.scrollIntoView({ block: "nearest" });
  }, [id, lit]);

  return (
    <div
      ref={list}
      id={id}
      role="listbox"
      aria-label="Commands"
      data-testid="slash-menu"
      tabIndex={scrolls ? 0 : undefined}
      className="absolute inset-x-0 bottom-full z-30 mb-2 flex max-h-72 flex-col gap-0.5 overflow-y-auto rounded-2xl border border-border bg-popover p-1.5 text-popover-foreground shadow-lg"
    >
      {rows.map((row, at) => {
        const unavailable = row.reason !== null;

        return (
          <div
            key={row.key}
            id={`${id}-${at}`}
            role="option"
            aria-selected={at === lit}
            aria-disabled={unavailable || undefined}
            data-testid="slash-option"
            data-command={row.label}
            // The box keeps the focus, where the words are, which a click on a line would take
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => onPick(row)}
            onMouseMove={() => {
              if (!unavailable && at !== lit) onLight(at);
            }}
            className={cn(
              "flex items-baseline gap-3 rounded-lg px-2.5 py-1.5 text-sm",
              unavailable ? "cursor-not-allowed" : "cursor-pointer",
              at === lit && "bg-accent text-accent-foreground",
            )}
          >
            <span className={cn("shrink-0 font-mono font-medium", unavailable && "text-muted-foreground")}>{row.label}</span>
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{row.reason ?? row.summary}</span>
          </div>
        );
      })}
    </div>
  );
}
