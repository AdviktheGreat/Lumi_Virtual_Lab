"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { Hammer, Trash2 } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { ScopeResult } from "@/components/paper-agent-scope-result";
import { useServer } from "@/components/server-provider";
import { describedBy, Field } from "@/components/settings-fields";
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
import {
  canGoOn,
  checkMethodChange,
  describeFound,
  describeFullText,
  describeMethodPaper,
  describeStanding,
  isAsking,
  isBuildable,
  methodDraftOf,
  methodPaperLink,
  pointedTo,
  scopeViewOf,
} from "@/lib/bakeoff-methods";
import { agentAddress, repoName } from "@/lib/paperagents";
import { timeAgo } from "@/lib/format";
import type { Bakeoff, BakeoffMethod, BakeoffState, BakeoffBuildBody } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// What a standing looks like. A method that is waiting for the person is set apart, since it is the one that cannot go on without them.
const STANDING_BADGE: Record<BakeoffState, { variant: "default" | "secondary" | "outline" | "destructive"; className?: string }> = {
  new: { variant: "outline" },
  building: { variant: "secondary" },
  built: { variant: "secondary" },
  waiting: { variant: "outline", className: "border-warning/60 bg-warning/15 text-foreground" },
  blocked: { variant: "outline" },
  failed: { variant: "destructive" },
  pending: { variant: "outline" },
};

// Says again what a method is called and where its code is. Only what differs is sent, and an empty address takes the code away.
function ChangeMethod({
  bakeoff,
  method,
  onChanged,
}: {
  bakeoff: Bakeoff;
  method: BakeoffMethod;
  onChanged: (next: Bakeoff) => void;
}) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [draft, setDraft] = useState(() => methodDraftOf(method));
  const [tried, setTried] = useState(false);
  const checked = checkMethodChange(draft, method, bakeoff.limits);
  const problems = tried ? checked.problems : {};
  const unchanged = checked.value !== null && Object.keys(checked.value).length === 0;

  async function save() {
    setTried(true);
    const change = checked.value;
    if (change === null || Object.keys(change).length === 0) return;
    const next = await attempt.run(() => api.changeBakeoffMethod(bakeoff.id, method.id, change));
    if (next) {
      onChanged(next);
      setTried(false);
    }
  }

  return (
    <form
      aria-label={`Change ${method.name}`}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-3 pt-2"
    >
      <Field id={`${id}-name`} label="Name" problem={problems.name}>
        <Input
          id={`${id}-name`}
          value={draft.name}
          onChange={(event) => setDraft((was) => ({ ...was, name: event.target.value }))}
          maxLength={bakeoff.limits.max_name_chars * 4}
          autoComplete="off"
          aria-invalid={problems.name !== undefined}
          aria-describedby={describedBy(`${id}-name`, { problem: problems.name !== undefined })}
        />
      </Field>
      <Field
        id={`${id}-repo`}
        label="Where its code is"
        hint="The address of the project, such as https://github.com/owner/name. Blank takes it away. Changing it means building the method again."
        problem={problems.repo}
      >
        <Input
          id={`${id}-repo`}
          value={draft.repo}
          onChange={(event) => setDraft((was) => ({ ...was, repo: event.target.value }))}
          autoComplete="off"
          spellCheck={false}
          aria-invalid={problems.repo !== undefined}
          aria-describedby={describedBy(`${id}-repo`, { hint: true, problem: problems.repo !== undefined })}
        />
      </Field>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div>
        <Button type="submit" size="sm" disabled={attempt.busy || unchanged}>
          {attempt.busy ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}

// What the method's data being outside its card, or inside it, comes to, with the person's going on if it is outside. Going on is theirs
// to say, and is kept only for this data and this card.
function MethodScope({ bakeoff, method, onChanged, reload }: { bakeoff: Bakeoff; method: BakeoffMethod; onChanged: (next: Bakeoff) => void; reload: () => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const scope = method.scope;
  const view = scopeViewOf(scope);

  async function goOn() {
    if (scope.key === null) return;
    const key = scope.key;
    const next = await attempt.run(() => api.goOnWithBakeoffMethod(bakeoff.id, method.id, key));
    // What was shown may not be what is now, and then it is looked at again
    if (next) onChanged(next);
    else reload();
  }

  async function takeBack() {
    const next = await attempt.run(() => api.takeBackBakeoffMethod(bakeoff.id, method.id));
    if (next) onChanged(next);
  }

  if (view === null) {
    return (
      <p className="text-xs text-muted-foreground" data-testid="method-scope-none">
        {scope.reason}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2" data-testid="method-scope" data-outcome={view.outcome}>
      <details open={view.outcome === "outside"} className="rounded-lg border border-border px-3 py-2">
        <summary className="cursor-pointer text-sm">Your data against its card</summary>
        <div className="pt-2">
          <ScopeResult check={view} />
        </div>
      </details>
      {canGoOn(scope) && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs text-muted-foreground">
            Going on is yours to say. It is kept for this data and this card as they are shown, and is not kept if either changes.
          </p>
          <div>
            <Button variant="outline" size="sm" onClick={() => void goOn()} disabled={attempt.busy}>
              Go on with it on my data
            </Button>
          </div>
        </div>
      )}
      {scope.went_on && (
        <div className="flex flex-wrap items-center gap-2" data-testid="method-went-on">
          <Badge variant="secondary">You go on with it</Badge>
          <span className="text-xs text-muted-foreground">
            You said so {scope.went_on_at !== null ? `${timeAgo(scope.went_on_at)}, ` : ""}for this data as it is shown, outside what this card says.
          </span>
          <Button variant="outline" size="xs" onClick={() => void takeBack()} disabled={attempt.busy}>
            Take it back
          </Button>
        </div>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </div>
  );
}

// One method that is in the running: its paper, where it was found and why it was chosen if a search found it, where its code is, where
// it stands, what its data is against its card, and what a person can do with it
export function BakeoffMethodCard({
  bakeoff,
  method,
  working,
  onBuild,
  onChanged,
  reload,
}: {
  bakeoff: Bakeoff;
  method: BakeoffMethod;
  // Whether its methods are being found, built, or run, which nothing is changed in the meantime
  working: boolean;
  onBuild: (body: BakeoffBuildBody) => void;
  onChanged: (next: Bakeoff) => void;
  reload: () => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);
  const standing = describeStanding(method.standing);
  const badge = STANDING_BADGE[method.standing.state];
  const pointed = pointedTo(method);
  const fullText = method.found !== null ? describeFullText(method.found) : null;

  async function remove() {
    const next = await attempt.run(() => api.removeBakeoffMethod(bakeoff.id, method.id));
    if (next) onChanged(next);
  }

  async function saveCode(address: string) {
    const next = await attempt.run(() => api.changeBakeoffMethod(bakeoff.id, method.id, { repo: address }));
    if (next) onChanged(next);
  }

  return (
    <li
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4"
      data-testid="bakeoff-method"
      data-method={method.id}
      data-state={method.standing.state}
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 break-words text-sm font-medium">{method.name}</h3>
        <Badge variant={badge.variant} className={cn(badge.className)} data-testid="method-standing">
          {standing.label}
        </Badge>
        <Badge variant="outline">{method.added_by === "search" ? "Found by a search" : "Added by you"}</Badge>
      </div>

      <div className="flex flex-col gap-1 text-sm">
        {method.title !== "" && <p className="break-words">{method.title}</p>}
        <p className="break-words text-xs text-muted-foreground">
          <a href={methodPaperLink(method.paper)} target="_blank" rel="noreferrer" className={LINK}>
            {describeMethodPaper(method.paper)}
          </a>
        </p>
        {method.found !== null && <p className="text-xs text-muted-foreground">{describeFound(method.found)}</p>}
        {fullText !== null && <p className="text-xs text-muted-foreground">{fullText}</p>}
      </div>

      {method.fit !== null && (
        <figure className="flex flex-col gap-1" data-testid="method-fit">
          <figcaption className="text-xs text-muted-foreground">The words of its abstract that {method.fit.model} went by in choosing it</figcaption>
          <blockquote className="break-words border-l-2 border-border pl-2 text-xs">{method.fit.quote}</blockquote>
        </figure>
      )}

      <p className="break-words text-sm" data-testid="method-code">
        <span className="text-muted-foreground">Its code: </span>
        {method.repo !== null ? (
          <a href={method.repo} target="_blank" rel="noreferrer" className={LINK}>
            {repoName(method.repo)}
          </a>
        ) : (
          "not said"
        )}
      </p>
      {pointed.length > 0 && (
        <div className="flex flex-col gap-1.5" data-testid="method-pointed">
          <p className="text-xs text-muted-foreground">
            Its paper or abstract points to {pointed.length === 1 ? "this address" : "these addresses"}. They are not its code until you say
            so.
          </p>
          <ul aria-label="Addresses its paper points to" className="flex flex-col gap-1">
            {pointed.map((address) => (
              <li key={address} className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 break-all text-xs">{address}</span>
                <Button variant="outline" size="xs" onClick={() => void saveCode(address)} disabled={working || attempt.busy}>
                  It is its code
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-1" data-testid="method-standing-text">
        {standing.step !== null && <p className="text-xs text-muted-foreground">{standing.step}</p>}
        {method.standing.reason !== "" && <p className="break-words text-sm">{method.standing.reason}</p>}
        {method.standing.at !== undefined && <p className="text-xs text-muted-foreground">{timeAgo(method.standing.at)}</p>}
        {method.agent !== null && (
          <p className="text-xs text-muted-foreground">
            Its PaperAgent:{" "}
            <Link href={agentAddress(method.agent.id)} className={LINK}>
              {method.agent.title}
            </Link>
          </p>
        )}
      </div>

      <MethodScope bakeoff={bakeoff} method={method} onChanged={onChanged} reload={reload} />

      <div className="flex flex-wrap items-center gap-2">
        {isAsking(method) && (
          <Button size="sm" onClick={() => onBuild({ candidates: [method.id], go_on: [method.id] })} disabled={working}>
            <Hammer />
            Go on and build it
          </Button>
        )}
        {isBuildable(method) && !isAsking(method) && (
          <Button variant="outline" size="sm" onClick={() => onBuild({ candidates: [method.id] })} disabled={working} aria-label={`Build ${method.name}`}>
            <Hammer />
            {method.standing.state === "new" ? "Build" : "Build again"}
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={() => setAsking(true)} disabled={working || attempt.busy} aria-label={`Remove ${method.name}`}>
          <Trash2 />
          Remove
        </Button>
      </div>

      <details className="rounded-lg border border-border px-3 py-2">
        <summary className="cursor-pointer text-sm">Change its name or where its code is</summary>
        {/* Made again when what the method is changes, so that it shows what it is and not what was typed before */}
        <ChangeMethod key={JSON.stringify(methodDraftOf(method))} bakeoff={bakeoff} method={method} onChanged={onChanged} />
      </details>

      {attempt.problem && <ProblemNotice problem={attempt.problem} />}

      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove {method.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes it out of the bake-off, with what was kept of running it. Its PaperAgent, if it has one, stays, as it is of its paper.
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
    </li>
  );
}
