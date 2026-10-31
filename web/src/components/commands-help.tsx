"use client";

import { useCallback, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { commandsFor, type Place } from "@/lib/commands";

// What the commands are, for the person who has not found them in the menu
export function CommandsHelp({ place, onClose }: { place: Place; onClose: () => void }) {
  // A list that is longer than the room for it is scrolled, which is a part of the page that the keyboard can reach only if it
  // can be focused, so it can when it is that. The dialog puts its content on the page after this has first run, so the list is
  // measured when it arrives and again whenever its size changes
  const [scrolls, setScrolls] = useState(false);
  const measure = useCallback((element: HTMLDListElement | null) => {
    if (element === null) return;
    const check = () => setScrolls(element.scrollHeight > element.clientHeight);
    check();
    const watcher = new ResizeObserver(check);
    watcher.observe(element);
    return () => watcher.disconnect();
  }, []);

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="commands-help">
        <DialogHeader>
          <DialogTitle>Commands</DialogTitle>
          <DialogDescription>
            Write a slash in the box to see them. The arrow keys choose one, Enter runs it, Tab writes it out, and Escape puts the list away.
          </DialogDescription>
        </DialogHeader>
        <dl ref={measure} tabIndex={scrolls ? 0 : undefined} className="-mx-1 flex max-h-96 flex-col gap-2.5 overflow-y-auto px-1 text-sm">
          {commandsFor(place).map((command) => (
            <div key={command.name} className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
              <dt className="shrink-0 font-mono font-medium sm:w-36">
                /{command.name}
                {command.takes && (
                  <span className="font-normal text-muted-foreground">
                    {" "}
                    {command.takes.kind === "text" ? command.takes.hint : command.takes.choices.map((choice) => choice.value).join(" | ")}
                  </span>
                )}
              </dt>
              <dd className="text-muted-foreground">{command.summary}</dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  );
}
