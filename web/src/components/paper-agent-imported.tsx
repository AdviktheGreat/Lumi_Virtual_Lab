"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { RefreshCw, Trash2 } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Aside, describedBy, Field } from "@/components/settings-fields";
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
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { addressProblem, describeHost, describeListed, describeMaker, describeWhen } from "@/lib/imported";
import { agentAddress, existingOf } from "@/lib/paperagents";
import type { ImportedTool, PaperAgent, PaperAgentImported } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// One tool that the server listed, by its name on the server
function ListedTool({ tool }: { tool: ImportedTool }) {
  return (
    <li className="flex flex-col gap-1 rounded-lg border border-border p-3" data-testid="imported-tool" data-name={tool.name}>
      <code className="break-all font-mono text-sm font-medium">
        {tool.name}({tool.parameters.join(", ")})
      </code>
      {tool.summary !== "" && <p className="break-words text-xs text-muted-foreground">{tool.summary}</p>}
    </li>
  );
}

// What an agent was imported from: where its server is, who made it as far as is known, what it listed, and that nothing of the lab's
// has been done to it. The server can be connected to again, to list its tools again, and taken away, which leaves the agent of the
// paper.
function Imported({ agent, imported, onChanged }: { agent: PaperAgent; imported: PaperAgentImported; onChanged: (agent: PaperAgent) => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // What the last connecting came to, in a live region, so that it is heard as well as seen
  const [done, setDone] = useState("");

  async function again() {
    setFailure(null);
    setDone("");
    const result = await attempt.run(() => api.checkPaperAgentImport(agent.id));
    if (!result) return;
    if (result.ok) {
      onChanged(result.agent);
      setDone(`Connected again. ${describeListed(result.agent.imported?.tools ?? [])}`);
    } else setFailure(result.reason ?? "The server could not be connected to.");
  }

  async function remove() {
    setFailure(null);
    setDone("");
    const next = await attempt.run(() => api.removePaperAgentImport(agent.id));
    if (next) onChanged(next);
  }

  return (
    <div className="flex flex-col gap-4" data-testid="imported" data-origin={imported.origin ?? ""}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">Tier {imported.tier}</Badge>
        <Badge variant="outline">Not checked here</Badge>
        <Badge variant="outline">{describeMaker(imported)}</Badge>
      </div>
      <p className="text-sm text-muted-foreground" data-testid="imported-meaning">
        {imported.meaning}
      </p>
      <div className="flex flex-col gap-1 text-sm text-muted-foreground">
        <p>{describeHost(imported)}</p>
        <p className="break-all">
          Address: <code className="font-mono text-xs">{imported.url}</code>
        </p>
        <p>
          {describeWhen(imported)} {describeListed(imported.tools)}
        </p>
      </div>
      {imported.tools.length > 0 && (
        <ul aria-label="Tools the server listed" className="flex flex-col gap-2">
          {imported.tools.map((tool) => (
            <ListedTool key={tool.name} tool={tool} />
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        These are the names that the server gives its tools, as it listed them. They are what it says of itself, and the lab has not checked them.
      </p>
      {failure !== null && (
        <Aside tone="warning">
          <span role="alert" data-testid="imported-failure">
            {failure} What was kept of the server is as it was.
          </span>
        </Aside>
      )}
      <p role="status" className="text-xs text-muted-foreground" data-testid="imported-done">
        {done}
      </p>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => void again()} disabled={attempt.busy}>
          <RefreshCw aria-hidden />
          {attempt.busy ? "Connecting…" : "Connect again"}
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={() => setAsking(true)} disabled={attempt.busy}>
          <Trash2 aria-hidden />
          Remove the server
        </Button>
      </div>
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove the server of {agent.title}?</AlertDialogTitle>
            <AlertDialogDescription>
              The agent of the paper is left as it is, without the server. Conversations that begin from now on are not given its tools. Nothing on the
              server is changed.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void remove()}>
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// Brings in a server that someone hosts for the paper of an agent that was made here, which is connected to for a look and nothing is
// called
function ImportServer({ agent, onChanged }: { agent: PaperAgent; onChanged: (agent: PaperAgent) => void }) {
  const { report } = useServer();
  const id = useId();
  const [address, setAddress] = useState("");
  const [tried, setTried] = useState(false);
  const [existing, setExisting] = useState<string | null>(null);
  const attempt = useAttempt(report);
  const problem = tried ? addressProblem(address) : null;

  async function bring() {
    setTried(true);
    setExisting(null);
    if (addressProblem(address) !== null) return;
    const next = await attempt.run(async () => {
      try {
        return await api.importPaperAgent({ url: address.trim(), agent: agent.id });
      } catch (error) {
        setExisting(existingOf(error));
        throw error;
      }
    });
    if (next) {
      setAddress("");
      setTried(false);
      onChanged(next);
    }
  }

  return (
    <form
      aria-label="Import a server for this agent"
      onSubmit={(event) => {
        event.preventDefault();
        void bring();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field
        id={`${id}-address`}
        label="Address of the server"
        hint="Where the MCP server of an agent that someone else made of this paper is reached. The lab connects to it to see which tools it gives, and calls none of them."
        problem={problem ?? undefined}
      >
        <Input
          id={`${id}-address`}
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          placeholder="https://"
          autoComplete="off"
          spellCheck={false}
          readOnly={attempt.busy}
          aria-invalid={problem !== null}
          aria-describedby={describedBy(`${id}-address`, { hint: true, problem: problem !== null })}
        />
      </Field>
      <Aside tone="warning">
        The server is run by someone else. What a call is given is sent there, and what it gives back is not checked by the lab. Each call asks you first.
      </Aside>
      {attempt.problem && (
        <div className="flex flex-col gap-1.5">
          <ProblemNotice problem={attempt.problem} />
          {existing !== null && (
            <Link href={agentAddress(existing)} className={cn("w-fit text-sm", LINK)}>
              Open that PaperAgent
            </Link>
          )}
        </div>
      )}
      <div>
        <Button type="submit" disabled={attempt.busy}>
          {attempt.busy ? "Connecting…" : "Import the server"}
        </Button>
      </div>
    </form>
  );
}

// The server that an agent was imported from, or the way to import one for it
export function ImportedSection({ agent, onChanged }: { agent: PaperAgent; onChanged: (agent: PaperAgent) => void }) {
  return agent.imported === null ? (
    <ImportServer agent={agent} onChanged={onChanged} />
  ) : (
    <Imported agent={agent} imported={agent.imported} onChanged={onChanged} />
  );
}
