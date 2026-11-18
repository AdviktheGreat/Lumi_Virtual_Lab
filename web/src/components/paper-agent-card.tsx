"use client";

import { useId, useState } from "react";
import { Check, Plus, Undo2 } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { Place } from "@/components/paper-agent-place";
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
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { sentence } from "@/lib/checks";
import {
  approvalBlock,
  ASPECTS,
  canChange,
  CARD_FACTS_SHOWN,
  CARD_KINDS,
  CARD_TEXT,
  cardLines,
  checkCardFact,
  describeEdits,
  describeStatus,
  describeWhose,
  draftOf,
  EMPTY_CARD_DRAFT,
  isAdded,
  MAX_DETAIL_CHARS,
  MAX_QUOTE_CHARS,
  type CardLine,
} from "@/lib/paperagent-card";
import type { CardKind, PaperAgent, PaperAgentReading } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";

// How many characters of a fact are said in the names of the buttons that act on it
const NAME_CHARS = 60;

interface Shared {
  agent: PaperAgent;
  // What a person does to the card, which gives back the reading as it is then, or nothing if it was refused. One is done at a
  // time, and the others wait.
  act: (call: () => Promise<PaperAgentReading>) => Promise<boolean>;
  busy: boolean;
  onChanged: (reading: PaperAgentReading) => void;
}

// What a fact is called in the name of a button that acts on it, which is what it says, or its words if it says nothing
function nameOf(line: CardLine): string {
  const said = line.title ?? line.fact.quote;

  return said.length > NAME_CHARS ? `${said.slice(0, NAME_CHARS)}…` : said;
}

// Says a fact, or changes one: what a kind of fact has, and for one that is a person's own, their words
function FactForm({
  agent,
  kind,
  line,
  onChanged,
  onClose,
}: Pick<Shared, "agent" | "onChanged"> & { kind: CardKind; line: CardLine | null; onClose: () => void }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [draft, setDraft] = useState(line === null ? EMPTY_CARD_DRAFT : draftOf(line));
  const [tried, setTried] = useState(false);
  // The words of a fact that was read are the paper's, and are not changed
  const ownWords = line === null || isAdded(line.fact);
  const checked = checkCardFact(kind, draft, ownWords);
  const problems = tried ? checked.problems : {};
  const set = (part: keyof typeof draft) => (value: string) => setDraft((was) => ({ ...was, [part]: value }));

  async function save() {
    setTried(true);
    const fields = checked.value;
    if (fields === null) return;
    const next = await attempt.run(() =>
      line === null ? api.addPaperAgentCardFact(agent.id, kind, fields) : api.changePaperAgentCardFact(agent.id, line.fact.id, fields),
    );
    if (next) {
      onChanged(next);
      onClose();
    }
  }

  return (
    <form
      aria-label={line === null ? CARD_TEXT[kind].add : `Change: ${nameOf(line)}`}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
      className="flex flex-col gap-3 rounded-lg border border-border bg-muted/30 p-3"
    >
      {(kind === "methods" || kind === "datasets") && (
        <Field id={`${id}-name`} label="What it is called" problem={problems.name}>
          <Input
            id={`${id}-name`}
            value={draft.name}
            onChange={(event) => set("name")(event.target.value)}
            maxLength={MAX_DETAIL_CHARS * 2}
            autoComplete="off"
            aria-invalid={problems.name !== undefined}
            aria-describedby={describedBy(`${id}-name`, { problem: problems.name !== undefined })}
          />
        </Field>
      )}
      {kind === "datasets" && (
        <Field id={`${id}-accession`} label="Its accession, if it has one" problem={problems.accession}>
          <Input
            id={`${id}-accession`}
            value={draft.accession}
            onChange={(event) => set("accession")(event.target.value)}
            maxLength={MAX_DETAIL_CHARS * 2}
            autoComplete="off"
            aria-invalid={problems.accession !== undefined}
            aria-describedby={describedBy(`${id}-accession`, { problem: problems.accession !== undefined })}
          />
        </Field>
      )}
      {kind === "scope" && (
        <>
          <Field id={`${id}-aspect`} label="What it is about" problem={problems.aspect}>
            <NativeSelect id={`${id}-aspect`} value={draft.aspect} onChange={(event) => set("aspect")(event.target.value)}>
              {ASPECTS.map((aspect) => (
                <option key={aspect} value={aspect}>
                  {sentence(aspect)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id={`${id}-value`} label="What it was tested on" problem={problems.value}>
            <Input
              id={`${id}-value`}
              value={draft.value}
              onChange={(event) => set("value")(event.target.value)}
              maxLength={MAX_DETAIL_CHARS * 2}
              autoComplete="off"
              aria-invalid={problems.value !== undefined}
              aria-describedby={describedBy(`${id}-value`, { problem: problems.value !== undefined })}
            />
          </Field>
        </>
      )}
      {ownWords && (
        <Field
          id={`${id}-quote`}
          label={kind === "limitations" ? "The limit, in words" : "Your words for it, if you have some"}
          hint={kind === "limitations" ? undefined : "These are yours and not the paper's, and are shown as yours."}
          problem={problems.quote}
        >
          <Textarea
            id={`${id}-quote`}
            value={draft.quote}
            onChange={(event) => set("quote")(event.target.value)}
            maxLength={MAX_QUOTE_CHARS * 2}
            aria-invalid={problems.quote !== undefined}
            aria-describedby={describedBy(`${id}-quote`, { hint: kind !== "limitations", problem: problems.quote !== undefined })}
          />
        </Field>
      )}
      {!ownWords && line !== null && (
        <p className="text-xs text-muted-foreground">
          The paper&apos;s words for it stay as they are, and the card says what the model read it as.
        </p>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={attempt.busy}>
          {attempt.busy ? "Saving…" : line === null ? "Add it" : "Save it"}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onClose} disabled={attempt.busy}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

// What a fact says, whose it is, what it was read as if a person changed it, and the words and place that it has
function FactBody({ agent, line }: { agent: string; line: CardLine }) {
  const { fact, title, tag } = line;

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {title !== null && <span className="min-w-0 break-words text-sm font-medium">{title}</span>}
        {tag !== null && <Badge variant="outline">{tag}</Badge>}
        {fact.by === "person" ? (
          <Badge variant="secondary">{describeWhose(fact)}</Badge>
        ) : (
          <span className="text-xs text-muted-foreground">{describeWhose(fact)}</span>
        )}
      </div>
      {line.readAs !== null && <p className="break-words text-xs text-muted-foreground">The model read it as: {line.readAs}</p>}
      {fact.quote !== "" && (
        <>
          {isAdded(fact) && <span className="text-xs text-muted-foreground">Your words</span>}
          <blockquote className="break-words border-l-2 border-border pl-2 text-sm text-muted-foreground">{fact.quote}</blockquote>
        </>
      )}
      {fact.anchor !== null && <Place agent={agent} quote={fact.quote} anchor={fact.anchor} />}
    </>
  );
}

// A fact on the card, with the way to change it, and to take it off
function CardFact({
  kind,
  line,
  onTakeOff,
  ...shared
}: Shared & { kind: CardKind; line: CardLine; onTakeOff: (line: CardLine) => void }) {
  const [changing, setChanging] = useState(false);
  const name = nameOf(line);

  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-border px-3 py-2" data-testid="card-fact" data-by={line.fact.by}>
      {changing ? (
        <FactForm agent={shared.agent} kind={kind} line={line} onChanged={shared.onChanged} onClose={() => setChanging(false)} />
      ) : (
        <>
          <FactBody agent={shared.agent.id} line={line} />
          <div className="flex flex-wrap items-center gap-2">
            {canChange(kind, line.fact) && (
              <Button variant="ghost" size="xs" onClick={() => setChanging(true)} disabled={shared.busy} aria-label={`Change: ${name}`}>
                Change
              </Button>
            )}
            {line.changed && (
              <Button
                variant="ghost"
                size="xs"
                onClick={() => void shared.act(() => api.restorePaperAgentCardFact(shared.agent.id, line.fact.id))}
                disabled={shared.busy}
                aria-label={`Change back: ${name}`}
              >
                Change back
              </Button>
            )}
            <Button variant="ghost" size="xs" onClick={() => onTakeOff(line)} disabled={shared.busy} aria-label={`Take off: ${name}`}>
              Take off
            </Button>
            {!canChange(kind, line.fact) && (
              <span className="text-xs text-muted-foreground">The authors&apos; sentence is not changed. Take it off, and add yours.</span>
            )}
          </div>
        </>
      )}
    </li>
  );
}

// The facts of one sort, the way to add one, and those that a person took off, which they can put back
function Group({
  kind,
  lines,
  off,
  onTakeOff,
  ...shared
}: Shared & { kind: CardKind; lines: CardLine[]; off: CardLine[]; onTakeOff: (line: CardLine) => void }) {
  const id = useId();
  const [all, setAll] = useState(false);
  const [adding, setAdding] = useState(false);
  const text = CARD_TEXT[kind];
  const shown = all ? lines : lines.slice(0, CARD_FACTS_SHOWN);

  return (
    <section aria-labelledby={id} className="flex flex-col gap-2" data-testid="card-group" data-kind={kind}>
      <h3 id={id} className="text-sm font-medium">
        {text.label} <span className="font-normal text-muted-foreground">({lines.length})</span>
      </h3>
      {lines.length === 0 ? (
        <p className="text-sm text-muted-foreground">{text.none}</p>
      ) : (
        <ul aria-label={text.label} className="flex flex-col gap-2">
          {shown.map((line) => (
            // Whose a fact is is in its key, so that a form that is open on it is closed when a person's change to it is gone,
            // since what it was begun from is not what the fact is
            <CardFact key={`${line.fact.id}:${line.fact.by}:${line.changed}`} kind={kind} line={line} onTakeOff={onTakeOff} {...shared} />
          ))}
        </ul>
      )}
      {shown.length < lines.length && (
        <div>
          <Button variant="outline" size="xs" onClick={() => setAll(true)} aria-label={`Show all ${lines.length}: ${text.label}`}>
            Show all {lines.length}
          </Button>
        </div>
      )}
      {adding ? (
        <FactForm agent={shared.agent} kind={kind} line={null} onChanged={shared.onChanged} onClose={() => setAdding(false)} />
      ) : (
        <div>
          <Button variant="outline" size="xs" onClick={() => setAdding(true)} disabled={shared.busy}>
            <Plus />
            {text.add}
          </Button>
        </div>
      )}
      {off.length > 0 && (
        <details className="rounded-lg border border-border px-3 py-2">
          <summary className="cursor-pointer text-sm">Taken off ({off.length})</summary>
          <ul aria-label={`Taken off: ${text.label.toLowerCase()}`} className="flex flex-col gap-2 pt-2">
            {off.map((line) => (
              <li key={line.fact.id} className="flex flex-col gap-1.5" data-testid="card-taken-off">
                <FactBody agent={shared.agent.id} line={line} />
                <div>
                  <Button
                    variant="outline"
                    size="xs"
                    disabled={shared.busy}
                    onClick={() => void shared.act(() => api.restorePaperAgentCardFact(shared.agent.id, line.fact.id))}
                    aria-label={`Put back: ${nameOf(line)}`}
                  >
                    <Undo2 />
                    Put back
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

// What the card is, with the way to approve it, to take the approval back, and to take away what a person did to it
function Status({ reading, working, ...shared }: Shared & { reading: PaperAgentReading; working: boolean }) {
  const { card } = reading;
  const [discarding, setDiscarding] = useState(false);
  const status = describeStatus(card);
  const edits = describeEdits(card);
  const block = approvalBlock(card, working);

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="card-status" data-status={card.status}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={card.status === "approved" ? "default" : "outline"}>{status.label}</Badge>
        <p className="min-w-0 text-sm">{status.text}</p>
      </div>
      {edits !== null && <p className="text-xs text-muted-foreground">{edits}</p>}
      <div className="flex flex-wrap items-center gap-2">
        {card.status === "approved" ? (
          <Button variant="outline" size="sm" disabled={shared.busy} onClick={() => void shared.act(() => api.withdrawPaperAgentCardApproval(shared.agent.id))}>
            Take the approval back
          </Button>
        ) : (
          <Button size="sm" disabled={shared.busy || block !== null} onClick={() => void shared.act(() => api.approvePaperAgentCard(shared.agent.id))}>
            <Check />
            Approve the card
          </Button>
        )}
        {card.edited && (
          <Button variant="outline" size="sm" disabled={shared.busy} onClick={() => setDiscarding(true)}>
            Discard what I did
          </Button>
        )}
        {block !== null && card.status !== "approved" && <span className="text-xs text-muted-foreground">{block}</span>}
      </div>
      <AlertDialog open={discarding} onOpenChange={setDiscarding}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard what you did to the card?</AlertDialogTitle>
            <AlertDialogDescription>
              This takes away every fact you added or changed, and puts back every fact you took off, so that the card is what the model
              read. The approval goes with them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void shared.act(() => api.discardPaperAgentCardEdits(shared.agent.id))}>
              Discard
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// The method card of an agent: what the method was done with and tested on, and where it falls short, which a model drafted from
// the paper and a person reads, corrects, and approves. What they did is marked as theirs.
export function CardSection({
  agent,
  reading,
  working,
  onChanged,
}: {
  agent: PaperAgent;
  reading: PaperAgentReading;
  // Whether the paper is being read, which the card is not approved while
  working: boolean;
  onChanged: (reading: PaperAgentReading) => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [taking, setTaking] = useState<CardLine | null>(null);

  if (!reading.has_paper) {
    return (
      <p className="text-sm text-muted-foreground">
        The card is kept with the paper&apos;s file, which is not here yet. Upload it, or read the paper, which fetches it, to have a card.
      </p>
    );
  }

  async function act(call: () => Promise<PaperAgentReading>): Promise<boolean> {
    const next = await attempt.run(call);
    if (!next) return false;
    onChanged(next);

    return true;
  }

  const shared: Shared = { agent, act, busy: attempt.busy, onChanged };
  const lines = cardLines(reading.card);
  const off = cardLines(reading.card.removed);
  // A fact that a person added is gone when it is taken off, so that is asked; one that was read can be put back
  const takeOff = (line: CardLine) => {
    if (isAdded(line.fact)) setTaking(line);
    else void act(() => api.removePaperAgentCardFact(agent.id, line.fact.id));
  };

  return (
    <div className="flex flex-col gap-4">
      <Status reading={reading} working={working} {...shared} />
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      {CARD_KINDS.map((kind) => (
        <Group key={kind} kind={kind} lines={lines[kind]} off={off[kind]} onTakeOff={takeOff} {...shared} />
      ))}
      <AlertDialog open={taking !== null} onOpenChange={(open) => !open && setTaking(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Take this off the card?</AlertDialogTitle>
            <AlertDialogDescription>
              You added this, so it is gone when it is taken off, and cannot be put back.
              {taking !== null && ` It is: ${nameOf(taking)}`}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                const line = taking;
                setTaking(null);
                if (line !== null) void act(() => api.removePaperAgentCardFact(agent.id, line.fact.id));
              }}
            >
              Take off
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
