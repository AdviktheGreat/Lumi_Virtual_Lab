"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Download, ExternalLink } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { AgentFields } from "@/components/paper-agent-fields";
import { useServer } from "@/components/server-provider";
import { Aside, describedBy, Field } from "@/components/settings-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { checkImport, describeHosted, describeNote, EMPTY_IMPORT, importState, quickImport, titleOf, type ImportDraft } from "@/lib/imported";
import { agentAddress, existingOf, isLink } from "@/lib/paperagents";
import type { ImportableAgent, PaperAgentsList } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// A link to somewhere on the web, which opens in a new tab. What is not a web address is shown as the words and not a link, since it
// is from the server.
function Outside({ href, children }: { href: string; children: React.ReactNode }) {
  if (!isLink(href)) return <span>{children}</span>;

  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className={cn("inline-flex items-center gap-1", LINK)}>
      {children}
      <ExternalLink className="size-3" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

// The agent that already has what is asked for, if that is why the server refused, which is shown with the way to it
function Existing({ id }: { id: string | null }) {
  if (id === null) return null;

  return (
    <Link href={agentAddress(id)} className={cn("w-fit text-sm", LINK)}>
      Open that PaperAgent
    </Link>
  );
}

// A server that others host, which is known to be an agent of a paper, and which is imported with a click
function QuickPick({ server, list }: { server: ImportableAgent; list: PaperAgentsList }) {
  const { report } = useServer();
  const router = useRouter();
  const attempt = useAttempt(report);
  const [existing, setExisting] = useState<string | null>(null);
  const state = importState(server);
  const note = describeNote(server);

  async function bring() {
    setExisting(null);
    const agent = await attempt.run(async () => {
      try {
        return await api.importPaperAgent(quickImport(server, state));
      } catch (error) {
        setExisting(existingOf(error));
        throw error;
      }
    });
    if (agent) router.push(agentAddress(agent.id));
  }

  return (
    <li
      className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4"
      data-testid="importable"
      data-key={server.key}
      data-state={state.kind}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="min-w-0 break-words text-sm font-medium">{server.title}</h4>
        <Badge variant="outline">Made by {server.made_by}</Badge>
      </div>
      <p className="text-sm text-muted-foreground">{server.about}.</p>
      <p className="text-xs text-muted-foreground" data-testid="importable-hosted">
        {describeHosted(server)}
      </p>
      {note !== null && <p className="text-xs text-muted-foreground">{note}</p>}
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <Outside href={`https://doi.org/${server.paper.doi}`}>Its paper</Outside>
        <Outside href={server.repo}>Its code</Outside>
        <Outside href={server.site}>Its page</Outside>
      </p>
      {state.kind === "imported" && (
        <p className="text-sm" data-testid="importable-done">
          Imported as{" "}
          <Link href={agentAddress(state.agent)} className={LINK}>
            {titleOf(list, state.agent)}
          </Link>
          .
        </p>
      )}
      {state.kind === "add" && (
        <Aside>There is a PaperAgent of this paper already, {titleOf(list, state.agent)}. The server is added to it, and nothing else of it is changed.</Aside>
      )}
      {state.kind !== "imported" && (
        <div>
          <Button type="button" variant="outline" size="sm" onClick={() => void bring()} disabled={attempt.busy}>
            <Download aria-hidden />
            {attempt.busy ? "Connecting…" : state.kind === "add" ? `Add the server to ${titleOf(list, state.agent)}` : `Import ${server.title}`}
          </Button>
        </div>
      )}
      {attempt.problem && (
        <div className="flex flex-col gap-1.5">
          <ProblemNotice problem={attempt.problem} />
          <Existing id={existing} />
        </div>
      )}
    </li>
  );
}

// Brings in the agent of a server that is not listed, by its address and the paper it is of
function ImportForm({ list }: { list: PaperAgentsList }) {
  const { report } = useServer();
  const router = useRouter();
  const id = useId();
  const [draft, setDraft] = useState<ImportDraft>(EMPTY_IMPORT);
  const [tried, setTried] = useState(false);
  const [existing, setExisting] = useState<string | null>(null);
  const attempt = useAttempt(report);
  const checked = checkImport(draft, list.repo_hosts);
  const problems = tried ? checked.problems : {};
  const field = (name: string) => `${id}-${name}`;

  async function bring() {
    setTried(true);
    setExisting(null);
    const body = checked.value;
    if (body === null) return;
    const agent = await attempt.run(async () => {
      try {
        return await api.importPaperAgent(body);
      } catch (error) {
        setExisting(existingOf(error));
        throw error;
      }
    });
    if (agent) router.push(agentAddress(agent.id));
  }

  return (
    <form
      aria-label="Import an agent"
      onSubmit={(event) => {
        event.preventDefault();
        void bring();
      }}
      className="flex flex-col gap-4 rounded-lg border border-border p-3"
    >
      <Field
        id={field("address")}
        label="Address of the server"
        hint="Where the MCP server is reached, such as https://example.org/mcp. The lab connects to it to see which tools it gives, and calls none of them."
        problem={problems.address}
      >
        <Input
          id={field("address")}
          value={draft.address}
          onChange={(event) => setDraft((was) => ({ ...was, address: event.target.value }))}
          placeholder="https://"
          autoComplete="off"
          spellCheck={false}
          readOnly={attempt.busy}
          aria-invalid={problems.address !== undefined}
          aria-describedby={describedBy(field("address"), { hint: true, problem: problems.address !== undefined })}
        />
      </Field>
      <AgentFields
        draft={draft}
        change={(part) => setDraft((was) => ({ ...was, ...part }))}
        problems={problems}
        busy={attempt.busy}
        list={list}
        field={field}
      />
      <Aside tone="warning">
        The server is run by someone else. What a call is given is sent there, and what it gives back is not checked by the lab. Each call asks you first.
      </Aside>
      {attempt.problem && (
        <div className="flex flex-col gap-1.5">
          <ProblemNotice problem={attempt.problem} />
          <Existing id={existing} />
        </div>
      )}
      <div>
        <Button type="submit" disabled={attempt.busy}>
          <Download aria-hidden />
          {attempt.busy ? "Connecting…" : "Import the agent"}
        </Button>
      </div>
    </form>
  );
}

// The servers that others host and that can be imported with a click, and the way to import one that is not listed
export function ImportAgents({ list }: { list: PaperAgentsList }) {
  return (
    <div className="flex flex-col gap-6">
      {list.importable.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Agents that others host</h3>
          <ul aria-label="Agents that others host" className="flex flex-col gap-2">
            {list.importable.map((server) => (
              <QuickPick key={server.key} server={server} list={list} />
            ))}
          </ul>
        </div>
      )}
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium">A server that is not listed</h3>
        <ImportForm list={list} />
      </div>
    </div>
  );
}
