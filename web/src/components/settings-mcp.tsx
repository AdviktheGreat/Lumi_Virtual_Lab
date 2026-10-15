"use client";

import { useId, useRef, useState } from "react";
import { Plug } from "lucide-react";
import { Aside, Field, Section } from "@/components/settings-fields";
import { KeyForm } from "@/components/settings-keys";
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
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Radio } from "@/components/ui/radio";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { describeTransport, howManyOn, keysToGive, keysToSetElsewhere, nameProblem, readEntry } from "@/lib/mcp";
import type { McpChange, McpServer } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

function ServerRow({
  server,
  onChange,
  onKeysChanged,
  onRemove,
}: {
  server: McpServer;
  onChange: (change: McpChange) => void;
  onKeysChanged: () => void;
  onRemove: (button: HTMLButtonElement) => void;
}) {
  const id = useId();
  const transport = describeTransport(server);
  const elsewhere = keysToSetElsewhere(server);
  const keys = keysToGive(server);

  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid={`mcp-${server.name}`}>
      <div className="flex items-start gap-2.5">
        <Checkbox
          id={`${id}-on`}
          checked={server.enabled}
          onChange={(event) => onChange({ enabled: event.target.checked })}
          aria-describedby={`${id}-about`}
          className="mt-0.5"
        />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <label htmlFor={`${id}-on`} className="text-sm font-medium">
              {server.title}
            </label>
            {server.title !== server.name && <code className="text-xs text-muted-foreground">{server.name}</code>}
            {server.asks && <Badge variant="outline">Asks before a call</Badge>}
            {server.auth === "oauth" && <Badge variant="outline">Signs in</Badge>}
          </div>
          <p id={`${id}-about`} className="text-xs text-muted-foreground">
            {[server.about, transport].filter(Boolean).join(". ")}
          </p>
          {server.target !== null && <code className="truncate text-xs text-muted-foreground">{server.target}</code>}
        </div>
        {!server.preset && (
          <Button type="button" variant="ghost" size="xs" onClick={(event) => onRemove(event.currentTarget)} aria-label={`Remove ${server.name}`}>
            Remove
          </Button>
        )}
      </div>

      {server.auth_choices.length > 0 && (
        <fieldset className="flex flex-col gap-1.5 pl-6.5">
          <legend className="pb-1 text-xs font-medium text-muted-foreground">How it is signed in to</legend>
          <label className="flex items-center gap-2 text-sm">
            <Radio name={`${id}-auth`} checked={server.auth === "key"} onChange={() => onChange({ auth: "key" })} />
            An API key
          </label>
          <label className="flex items-center gap-2 text-sm">
            <Radio name={`${id}-auth`} checked={server.auth === "oauth"} onChange={() => onChange({ auth: "oauth" })} />
            Your account, signed in to in the browser
          </label>
        </fieldset>
      )}

      {keys.length > 0 && (
        <div className="flex flex-col gap-2 pl-6.5">
          {keys.map((key) => (
            <KeyForm key={key.name} row={{ name: key.name, provider: server.title, set: key.set }} onChanged={onKeysChanged} />
          ))}
        </div>
      )}

      {elsewhere.length > 0 && (
        <p className="pl-6.5 text-xs text-muted-foreground">
          It needs {elsewhere.map((name, at) => (
            <span key={name}>
              {at > 0 && ", "}
              <code>{name}</code>
            </span>
          ))}
          , which this page cannot give: set {elsewhere.length === 1 ? "it" : "them"} where the server was started, and start it again.
        </p>
      )}

      {server.problem !== null && (
        <p role="alert" className="pl-6.5 text-xs text-destructive">
          {server.problem}
        </p>
      )}

      {server.setup !== null && (
        <details className="pl-6.5 text-xs text-muted-foreground">
          <summary className="cursor-pointer rounded outline-none focus-visible:ring-3 focus-visible:ring-ring/50">How to set it up</summary>
          <p className="mt-1.5 whitespace-pre-wrap break-words">{server.setup}</p>
        </details>
      )}
    </li>
  );
}

const ENTRY_EXAMPLE = '{\n  "url": "https://example.com/mcp"\n}';

// Where a server of one's own is described: its name, and what a config of any other tool would say of it
function AddServer({
  servers,
  onSaved,
  nameInput,
}: {
  servers: McpServer[];
  onSaved: (servers: McpServer[], name: string) => void;
  nameInput: React.RefObject<HTMLInputElement | null>;
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
    <form onSubmit={(event) => void add(event)} className="flex flex-col gap-3 rounded-lg border border-dashed border-border p-3" noValidate>
      <h4 className="text-sm font-medium">Add a server of your own</h4>
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

// The MCP servers whose tools the lead can be given. Each is kept as it is chosen, as the tools are, and a conversation is
// given the servers that are on when it begins.
export function McpSection({ servers, onChanged }: { servers: Loaded<McpServer[]>; onChanged: (servers: McpServer[]) => void }) {
  const { report } = useServer();
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  // What was chosen and is not yet kept, shown as it was chosen so that a box answers at once, until every change has been
  // answered, and then what the server holds is what is shown, whether it kept them or not
  const [chosen, setChosen] = useState<Record<string, McpChange>>({});
  // The changes are made one after another, so that the list each gives back is not replaced by one that was asked for
  // before it and answered after
  const queue = useRef<Promise<void>>(Promise.resolve());
  const waiting = useRef(0);
  const [removing, setRemoving] = useState<McpServer | null>(null);
  const [asking, setAsking] = useState(false);
  const asker = useRef<HTMLButtonElement | null>(null);
  const nameInput = useRef<HTMLInputElement | null>(null);

  function change(name: string, what: McpChange) {
    waiting.current += 1;
    setChosen((was) => ({ ...was, [name]: { ...was[name], ...what } }));
    queue.current = queue.current.then(async () => {
      try {
        setProblem(null);
        setDone(null);
        onChanged(await api.changeMcpServer(name, what));
      } catch (error) {
        report(error);
        setProblem(describeError(error));
      } finally {
        waiting.current -= 1;
        if (waiting.current === 0) setChosen({});
      }
    });
  }

  // What a key that was given or taken away changes is what the server says it is missing
  async function refresh() {
    try {
      onChanged(await api.mcp());
    } catch (error) {
      report(error);
    }
  }

  async function remove(server: McpServer) {
    setProblem(null);
    setDone(null);
    try {
      onChanged(await api.removeMcpServer(server.name));
      setDone(`Removed ${server.name}.`);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    }
  }

  const shown = servers.kind === "ready" ? servers.value.map((server) => (server.name in chosen ? { ...server, ...chosen[server.name] } : server)) : [];

  return (
    <Section title="MCP servers">
      <Aside>
        <Plug className="mr-1.5 inline size-3.5 align-text-bottom" aria-hidden />
        An MCP server gives the lead more tools, such as other databases and services. A conversation is given the servers that
        are on when it begins, connects to them when you send its first message, and asks you in the conversation before a call
        that costs money or cannot be undone.
      </Aside>
      {servers.kind === "loading" && <p className="text-sm text-muted-foreground">Looking at the servers…</p>}
      {servers.kind === "failed" && (
        <p role="alert" className="text-sm text-destructive">
          {describeError(servers.error)}
        </p>
      )}
      {servers.kind === "ready" && (
        <>
          <p role="status" className="text-sm text-muted-foreground" data-testid="mcp-count">
            {howManyOn(shown)}
          </p>
          {problem && (
            <p role="alert" className="text-xs text-destructive">
              {problem}
            </p>
          )}
          {done && (
            <p role="status" className="text-xs text-muted-foreground">
              {done}
            </p>
          )}
          <ul aria-label="MCP servers" className="flex flex-col gap-3">
            {shown.map((server) => (
              <ServerRow
                key={server.name}
                server={server}
                onChange={(what) => change(server.name, what)}
                onKeysChanged={() => void refresh()}
                onRemove={(button) => {
                  asker.current = button;
                  setRemoving(server);
                  setAsking(true);
                }}
              />
            ))}
          </ul>
          <AddServer
            servers={servers.value}
            nameInput={nameInput}
            onSaved={(kept, name) => {
              onChanged(kept);
              setProblem(null);
              setDone(`Saved ${name}. It is on, so conversations begun from now on are given its tools.`);
            }}
          />
          <AlertDialog open={asking} onOpenChange={setAsking}>
            <AlertDialogContent
              onCloseAutoFocus={(event) => {
                // Nothing opened the question but a button of the list, which is gone when its server was removed
                event.preventDefault();
                const back = asker.current?.isConnected ? asker.current : nameInput.current;
                back?.focus();
              }}
            >
              <AlertDialogHeader>
                <AlertDialogTitle>Remove {removing?.name}?</AlertDialogTitle>
                <AlertDialogDescription>
                  This forgets how to reach it. Conversations that have begun keep the tools they were given. Add it again to use
                  it afterwards.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Keep</AlertDialogCancel>
                <AlertDialogAction
                  variant="destructive"
                  onClick={() => {
                    if (removing !== null) void remove(removing);
                  }}
                >
                  Remove
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </>
      )}
    </Section>
  );
}
