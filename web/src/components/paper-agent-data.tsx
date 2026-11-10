"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { ExternalLink, Search, X } from "lucide-react";
import { JobOutput } from "@/components/job-output";
import { KeptData, Files } from "@/components/paper-agent-data-files";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Aside, describedBy, Field } from "@/components/settings-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { api } from "@/lib/api";
import {
  describeCandidate,
  describeOwn,
  describeSaid,
  MAX_REFERENCE_CHARS,
  otherStandIns,
  referenceProblem,
  standInPresent,
} from "@/lib/paperagent-data";
import { describeAnchor, isLink } from "@/lib/paperagents";
import type { DataCandidate, DataDataset, DataListing, DataStandIn, Job, PaperAgent, PaperAgentData } from "@/lib/types";
import type { Problem } from "@/lib/errors";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// How many of the places in the paper that say where data is are shown, with their words
const PLACES_SHOWN = 2;

interface Shared {
  agent: PaperAgent;
  data: PaperAgentData;
  // Whether anything is being done to the agent, which what is done to its data waits for
  busy: boolean;
  // Shows the data as it now is, as what changed it gives it back
  onData: (data: PaperAgentData) => void;
}

// The names of the person's own data that can stand in for something, to choose one
function OwnChoice({
  id,
  data,
  value,
  onChange,
  disabled,
}: {
  id: string;
  data: PaperAgentData;
  value: string;
  onChange: (own: string) => void;
  disabled: boolean;
}) {
  return (
    <NativeSelect id={id} value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
      <option value="">Choose some of your data</option>
      {data.own.map((own) => (
        <option key={own.name} value={own.name}>
          {describeOwn(own)}
        </option>
      ))}
    </NativeSelect>
  );
}

// What a stand-in is for: a dataset that the paper names, or one that is not named and is typed
type Target = { key: string; name: string; standIn: DataStandIn | null } | null;

// Says which of the person's own data stands in for a dataset of the paper, or takes that away. It is a note: nothing is copied.
function StandIn({ agent, data, target, busy, onData }: Shared & { target: Target }) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [own, setOwn] = useState("");
  const [name, setName] = useState("");
  const standIn = target === null ? null : target.standIn;
  const label = target === null ? name.trim() : target.name;

  async function set() {
    const key = target === null ? name : target.key;
    const next = await attempt.run(() => api.setPaperAgentStandIn(agent.id, key, own));
    if (next) {
      onData(next);
      setOwn("");
      setName("");
    }
  }

  async function clear(key: string) {
    const next = await attempt.run(() => api.clearPaperAgentStandIn(agent.id, key));
    if (next) onData(next);
  }

  if (standIn !== null) {
    const present = data.stand_ins.find((item) => item.key === standIn.key);

    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">Stood in for</Badge>
          <span className="min-w-0 break-words text-sm">
            Your data <code className="break-all text-xs">{standIn.own}</code> stands in for it
          </span>
          <Button
            variant="outline"
            size="xs"
            onClick={() => void clear(standIn.key)}
            disabled={busy || attempt.busy}
            aria-label={`Take it away: ${standIn.own} in place of ${standIn.name}`}
          >
            <X />
            Take it away
          </Button>
        </div>
        {present !== undefined && !standInPresent(present) && (
          <Aside tone="warning">There is no data of yours called {standIn.own} now. Add it on the Data page again, or take this away.</Aside>
        )}
        {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {target === null && (
        <Field id={`${id}-name`} label="What it stands in for" hint="The name of a dataset that the paper used.">
          <Input
            id={`${id}-name`}
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={400}
            autoComplete="off"
            aria-describedby={describedBy(`${id}-name`, { hint: true })}
          />
        </Field>
      )}
      {data.own.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          You have no data of your own to put in its place yet. Add some on the{" "}
          <Link href="/data" className={LINK}>
            Data page
          </Link>
          .
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor={`${id}-own`} className="sr-only">
            {label === "" ? "Your data to put in its place" : `Your data to put in the place of ${label}`}
          </label>
          <OwnChoice id={`${id}-own`} data={data} value={own} onChange={setOwn} disabled={busy || attempt.busy} />
          <Button
            variant="outline"
            size="xs"
            onClick={() => void set()}
            disabled={busy || attempt.busy || own === "" || (target === null && name.trim() === "")}
          >
            {attempt.busy ? "Saving…" : "Use it in its place"}
          </Button>
        </div>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </div>
  );
}

// A dataset that the paper names, with the paper's words for it, the place that its accession is of, and what stands in for it
function Dataset({ dataset, ...shared }: Shared & { dataset: DataDataset; onSee: (candidate: DataCandidate) => void; seeing: boolean }) {
  const { data, onSee, seeing } = shared;
  const candidate = dataset.candidate === null ? undefined : data.candidates.find((item) => item.key === dataset.candidate);

  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-border px-3 py-2" data-testid="data-dataset" data-key={dataset.key}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 break-words text-sm font-medium">{dataset.name}</span>
        {dataset.accession !== "" && <Badge variant="outline">{dataset.accession}</Badge>}
      </div>
      <blockquote className="break-words border-l-2 border-border pl-2 text-sm text-muted-foreground">{dataset.quote}</blockquote>
      <span className="text-xs text-muted-foreground">{describeAnchor(dataset.anchor)}</span>
      {candidate !== undefined && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">Its accession is of {candidate.label}.</span>
          {candidate.supported && (
            <Button variant="outline" size="xs" onClick={() => onSee(candidate)} disabled={seeing} aria-label={`See the files of ${candidate.label}`}>
              See the files
            </Button>
          )}
        </div>
      )}
      <StandIn agent={shared.agent} data={data} target={{ key: dataset.key, name: dataset.name, standIn: dataset.stand_in }} busy={shared.busy} onData={shared.onData} />
    </li>
  );
}

// The datasets that the paper names, for a person to say which of their own data stands in for any
function Datasets({ onSee, seeing, ...shared }: Shared & { onSee: (candidate: DataCandidate) => void; seeing: boolean }) {
  const id = useId();
  const { data } = shared;
  const others = otherStandIns(data);

  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <h3 id={id} className="text-sm font-medium">
        The data the paper used <span className="font-normal text-muted-foreground">({data.datasets.length})</span>
      </h3>
      <p className="text-xs text-muted-foreground">
        These are the datasets the paper names. Your own data can stand in for one, which only notes which to use in its place: it
        stays where it is, as yours, and is not copied.
      </p>
      {data.datasets.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {data.read ? "The paper names no dataset." : "The paper has not been read to the end, so what it names is not known yet."}
        </p>
      ) : (
        <ul aria-label="Datasets the paper names" className="flex flex-col gap-2">
          {data.datasets.map((dataset) => (
            <Dataset key={dataset.key} dataset={dataset} onSee={onSee} seeing={seeing} {...shared} />
          ))}
        </ul>
      )}
      {others.length > 0 && (
        <ul aria-label="Other data that stands in" className="flex flex-col gap-2">
          {others.map((standIn) => (
            <li key={standIn.key} className="flex flex-col gap-1.5 rounded-lg border border-border px-3 py-2" data-testid="data-other-stand-in">
              <span className="min-w-0 break-words text-sm font-medium">{standIn.name}</span>
              <StandIn
                agent={shared.agent}
                data={data}
                target={{ key: standIn.key, name: standIn.name, standIn }}
                busy={shared.busy}
                onData={shared.onData}
              />
            </li>
          ))}
        </ul>
      )}
      <details className="rounded-lg border border-border px-3 py-2">
        <summary className="cursor-pointer text-sm">Stand in for a dataset that is not listed</summary>
        <div className="pt-2">
          <StandIn agent={shared.agent} data={data} target={null} busy={shared.busy} onData={shared.onData} />
        </div>
      </details>
    </section>
  );
}

// A place that the paper or its code says its data is at, with the words that say it, and the way to see what it has
function Candidate({ candidate, onSee, seeing }: { candidate: DataCandidate; onSee: (candidate: DataCandidate) => void; seeing: boolean }) {
  const shown = candidate.facts.slice(0, PLACES_SHOWN);
  const said = describeSaid(candidate);

  return (
    <li className="flex flex-col gap-1.5 rounded-lg border border-border px-3 py-2" data-testid="data-candidate" data-key={candidate.key}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 text-sm font-medium">
          {candidate.url !== null && isLink(candidate.url) ? (
            <a href={candidate.url} target="_blank" rel="noreferrer noopener" className={cn("inline-flex min-w-0 items-center gap-1 break-words", LINK)}>
              {candidate.label}
              <ExternalLink className="size-3 shrink-0" aria-hidden />
              <span className="sr-only">(opens in a new tab)</span>
            </a>
          ) : (
            <span className="break-words">{candidate.label}</span>
          )}
        </span>
        <Badge variant={candidate.supported ? "secondary" : "outline"}>{describeCandidate(candidate)}</Badge>
      </div>
      {said !== null && <p className="text-xs text-muted-foreground">{said}.</p>}
      {candidate.reason !== null && <p className="break-words text-xs text-muted-foreground">{candidate.reason}</p>}
      {shown.map((fact) => (
        <div key={fact.id} className="flex flex-col gap-0.5">
          <blockquote className="break-words border-l-2 border-border pl-2 text-sm text-muted-foreground">{fact.quote}</blockquote>
          <span className="text-xs text-muted-foreground">{describeAnchor(fact.anchor)}</span>
        </div>
      ))}
      {candidate.facts.length > shown.length && (
        <p className="text-xs text-muted-foreground">And {candidate.facts.length - shown.length} more places in the paper.</p>
      )}
      {candidate.supported && (
        <div>
          <Button variant="outline" size="xs" onClick={() => onSee(candidate)} disabled={seeing} aria-label={`See the files of ${candidate.label}`}>
            <Search />
            See the files
          </Button>
        </div>
      )}
    </li>
  );
}

// Where the paper and its code say the data is, and the way to look at a place that is not among them
function Places({
  data,
  onSee,
  onType,
  seeing,
  problem,
}: {
  data: PaperAgentData;
  onSee: (candidate: DataCandidate) => void;
  onType: (reference: string) => void;
  seeing: boolean;
  problem: Problem | null;
}) {
  const id = useId();
  const [typed, setTyped] = useState("");
  const [tried, setTried] = useState(false);
  const wrong = referenceProblem(typed);

  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h3 id={id} className="text-sm font-medium">
          Where the data is <span className="font-normal text-muted-foreground">({data.candidates.length})</span>
        </h3>
        <p className="text-xs text-muted-foreground">
          These are the places that the paper and its code name. Seeing the files of one asks that place what it has, and fetches none
          of them.
        </p>
      </div>
      {data.candidates.length === 0 ? (
        <p className="text-sm text-muted-foreground">No place is named for the data. Say where it is below.</p>
      ) : (
        <ul aria-label="Places the paper names for its data" className="flex flex-col gap-2">
          {data.candidates.map((candidate) => (
            <Candidate key={candidate.key} candidate={candidate} onSee={onSee} seeing={seeing} />
          ))}
        </ul>
      )}
      <form
        aria-label="See the files of a place"
        onSubmit={(event) => {
          event.preventDefault();
          setTried(true);
          if (wrong === null) onType(typed.trim());
        }}
        className="flex flex-col gap-2"
      >
        <Field
          id={`${id}-where`}
          label="Another place"
          hint="An address, a DOI, or an accession, such as https://zenodo.org/records/1234567, 10.5281/zenodo.1234567, or GSE12345. Only the places listed below are asked."
          problem={tried && wrong !== null ? wrong : undefined}
        >
          <Input
            id={`${id}-where`}
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            maxLength={MAX_REFERENCE_CHARS * 2}
            autoComplete="off"
            spellCheck={false}
            aria-invalid={tried && wrong !== null}
            aria-describedby={describedBy(`${id}-where`, { hint: true, problem: tried && wrong !== null })}
          />
        </Field>
        <div>
          <Button type="submit" variant="outline" size="sm" disabled={seeing}>
            <Search />
            {seeing ? "Asking…" : "See the files"}
          </Button>
        </div>
      </form>
      {problem && <ProblemNotice problem={problem} />}
    </section>
  );
}

// The places that data is fetched from here, with the hosts of each, which are the only hosts that are asked
function Approved({ data }: { data: PaperAgentData }) {
  const id = useId();
  const [open, setOpen] = useState(false);

  return (
    <section className="flex flex-col gap-2">
      <div>
        <Button variant="link" size="xs" className="h-auto p-0" onClick={() => setOpen(!open)} aria-expanded={open} aria-controls={id}>
          {open ? "Hide the places data is fetched from" : "Show the places data is fetched from"}
        </Button>
      </div>
      {open && (
        <div id={id} className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">
            Only these hosts are asked, over https, and a download is only sent on to the hosts named with it. A link in a paper, or in what a
            place lists, does not add a host.
          </p>
          <ul aria-label="Places data is fetched from" className="flex flex-col gap-1.5">
            {data.sources.map((source) => (
              <li key={source.source} className="flex flex-col gap-0.5 rounded-md bg-muted/40 px-2.5 py-1.5" data-testid="data-approved">
                <span className="text-sm font-medium">{source.name}</span>
                <span className="break-words text-xs text-muted-foreground">
                  {[...source.hosts, ...source.via].join(", ")}
                  {source.downloads ? "" : ". Listed only: its files are not given without an account"}
                </span>
                {source.note !== "" && <span className="break-words text-xs text-muted-foreground">{source.note}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

// The data of an agent's paper: what the paper says it used and where, what its places have, the files that were chosen and
// fetched, and what stands in for data that is the person's own
export function DataSection({
  agent,
  data,
  busy,
  fetching,
  jobs,
  onData,
}: Shared & {
  // The fetching that is at work, if there is one
  fetching: Job | undefined;
  jobs: JobsData;
}) {
  const { report } = useServer();
  const look = useAttempt(report);
  const [listing, setListing] = useState<DataListing | null>(null);
  const [asking, setAsking] = useState(false);
  const shared = { agent, data, busy: busy || fetching !== undefined, onData };

  // Asks a place what it has, by what names it: its address, which round-trips to the same place
  async function see(reference: string) {
    setAsking(true);
    const found = await look.run(() => api.paperAgentDataFiles(agent.id, reference));
    setAsking(false);
    if (found) setListing(found);
  }

  return (
    <div className="flex flex-col gap-5">
      <Aside>
        Nothing is fetched until you have seen what a place has, chosen the files, and agreed to what they come to. Data is only fetched from
        the places listed at the end, and what is kept is in this agent&apos;s own folder.
      </Aside>
      {fetching !== undefined && <JobOutput key={fetching.id} job={fetching} jobs={jobs} />}
      <Datasets {...shared} onSee={(candidate) => void see(candidate.url ?? "")} seeing={asking} />
      <Places
        data={data}
        onSee={(candidate) => void see(candidate.url ?? "")}
        onType={(reference) => void see(reference)}
        seeing={asking}
        problem={look.problem}
      />
      {listing !== null && (
        <Files
          key={listing.key}
          agent={agent}
          data={data}
          listing={listing}
          busy={shared.busy}
          jobs={jobs}
          onRelist={() => void see(listing.url)}
        />
      )}
      <KeptData agent={agent} data={data} busy={shared.busy} onData={onData} />
      <Approved data={data} />
    </div>
  );
}
