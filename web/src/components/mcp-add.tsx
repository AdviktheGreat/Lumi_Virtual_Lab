"use client";

import { useId, useRef, useState } from "react";
import { Aside, Field } from "@/components/settings-fields";
import { useServer } from "@/components/server-provider";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { nameProblem, readEntry } from "@/lib/mcp";
import type { McpServer } from "@/lib/types";
import { cn } from "@/lib/utils";

const ENTRY_EXAMPLE = '{\n  "url": "https://example.com/mcp"\n}';

// Where a server of one's own is described: its name, and what a config of any other tool would say of it
export function AddServer({
  servers,
  onSaved,
  nameInput,
  heading = "Add a server of your own",
  bare = false,
}: {
  servers: McpServer[];
  onSaved: (servers: McpServer[], name: string) => void;
  nameInput: React.RefObject<HTMLInputElement | null>;
  // What the form is titled, or null where what it is in says so
  heading?: string | null;
  // Whether it is without a border of its own, as it is in a dialog
  bare?: boolean;
}) {
  const { report } = useServer();
  const id = useId();
  const [name, setName] = useState("");
  const [entry, setEntry] = useState("");
  const [problems, setProblems] = useState<{ name?: string; entry?: string }>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const entryInput = useRef<HTMLTextAreaElement>(null);

  async function add(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const wrongName = nameProblem(name, servers);
    const read = readEntry(entry);
    setProblem(null);
    if (wrongName !== null || !read.ok) {
      setProblems({ name: wrongName ?? undefined, entry: read.ok ? undefined : read.problem });
      (wrongName !== null ? nameInput.current : entryInput.current)?.focus();

      return;
    }
    setProblems({});
    setBusy(true);
    try {
      const kept = await api.saveMcpServer(name.trim(), read.entry);
      onSaved(kept, name.trim());
      setName("");
      setEntry("");
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(event) => void add(event)}
      className={cn("flex flex-col gap-3", !bare && "rounded-lg border border-dashed border-border p-3")}
      noValidate
    >
      {heading !== null && <h4 className="text-sm font-medium">{heading}</h4>}
      <Field id={`${id}-name`} label="Name" hint="What its tools' names start with." problem={problems.name}>
        <Input
          ref={nameInput}
          id={`${id}-name`}
          value={name}
          onChange={(event) => {
            setName(event.target.value);
            setProblems((was) => ({ ...was, name: undefined }));
          }}
          aria-invalid={problems.name !== undefined}
          aria-describedby={problems.name ? `${id}-name-problem` : `${id}-name-hint`}
          autoComplete="off"
          spellCheck={false}
          placeholder="my_tools"
        />
      </Field>
      <Field
        id={`${id}-entry`}
        label="How to reach it"
        hint={
          <>
            As a config of any other tool gives it: <code>url</code> for a server on the web, or <code>command</code> and{" "}
            <code>args</code> for a program to start.
          </>
        }
        problem={problems.entry}
      >
        <Textarea
          ref={entryInput}
          id={`${id}-entry`}
          value={entry}
          onChange={(event) => {
            setEntry(event.target.value);
            setProblems((was) => ({ ...was, entry: undefined }));
          }}
          aria-invalid={problems.entry !== undefined}
          aria-describedby={problems.entry ? `${id}-entry-problem` : `${id}-entry-hint`}
          className="font-mono text-[13px]"
          rows={5}
          spellCheck={false}
          placeholder={ENTRY_EXAMPLE}
        />
      </Field>
      <Aside tone="warning">A server that starts a program runs it on this computer, with the same access as you. Add only those you trust.</Aside>
      {problem && (
        <p role="alert" className="text-xs text-destructive">
          {problem}
        </p>
      )}
      <div>
        <Button type="submit" variant="outline" disabled={busy}>
          Add the server
        </Button>
      </div>
    </form>
  );
}

// The question asked before a server of one's own is taken away, which is answered where the button that asked it is, unless
// that has gone with the server
export function RemoveServer({
  server,
  open,
  onOpenChange,
  onRemove,
  returnFocus,
}: {
  server: McpServer | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRemove: (server: McpServer) => void;
  // What has the focus once the question is answered
  returnFocus: () => HTMLElement | null;
}) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent
        onCloseAutoFocus={(event) => {
          // Nothing opened the question but a button of the list, which is gone when its server was removed
          event.preventDefault();
          returnFocus()?.focus();
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>Remove {server?.name}?</AlertDialogTitle>
          <AlertDialogDescription>
            This forgets how to reach it. Programs that have begun keep the tools they were given. Add it again to use it
            afterwards.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Keep</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            onClick={() => {
              if (server !== null) onRemove(server);
            }}
          >
            Remove
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
