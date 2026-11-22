"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { Search } from "lucide-react";
import { Looked } from "@/components/looked";
import { ProblemNotice } from "@/components/messages";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { Field } from "@/components/settings-fields";
import { useSetupJobs } from "@/components/setup-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { NativeSelect } from "@/components/ui/native-select";
import { api, graphQuery } from "@/lib/api";
import {
  circleLayout,
  describeBasis,
  describeClaimStatus,
  describeCommits,
  describeGraphPaper,
  describeLimits,
  describeReference,
  describeRelationCount,
  describeReproduction,
  describeShared,
  describeShown,
  describeVersions,
  describeWhere,
  isNarrowed,
  KIND_HINTS,
  KIND_STROKES,
  KIND_SWATCHES,
  KIND_TITLES,
  linesOf,
  shortTitle,
} from "@/lib/paperagent-graph";
import { agentAddress } from "@/lib/paperagents";
import type { GraphEvidence, GraphKind, GraphPaper, GraphPlace, GraphQuery, GraphRelation, PaperAgentGraph } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";
import { usePaperAgentGraph, usePaperAgentsList } from "@/lib/use-paperagents";
import { cn } from "@/lib/utils";

const INTRO =
  "How the papers of the agents relate: the datasets, methods, software, and code they share, where one names another, and claims on the same words that have a number in common or none. It is made from what is kept of each agent when it is looked at, with nothing run and no model asked, and it is what the lead of a conversation is told when it asks how the papers relate.";

const KINDS: GraphKind[] = ["refers", "code", "dataset", "software", "method", "agrees", "differs"];

const LINK = "rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50";

// The size of the circle, the room that is left around it for the titles above and below, and the room at its sides for the titles
// there, which run out from their points and are as wide as SIDE_TITLE characters of the picture's font
const SIZE = 360;
const MARGIN = 70;
const SIDE = 110;
const SIDE_TITLE = 22;
// With more papers than this, their titles would run over each other, and are only said when a point is hovered
const MOST_TITLED = 12;

function Swatch({ kind }: { kind: GraphKind }) {
  return <span className={cn("inline-block size-2.5 shrink-0 rounded-full", KIND_SWATCHES[kind])} aria-hidden />;
}

// The papers around a circle, with a line between two for each kind of relation they have
function Picture({ graph }: { graph: PaperAgentGraph }) {
  const ids = graph.papers.map((paper) => paper.id);
  const placed = circleLayout(ids, SIZE, MARGIN);
  const lines = linesOf(graph.relations);
  const kinds = KINDS.filter((kind) => graph.counts[kind] > 0);
  const titled = ids.length <= MOST_TITLED;

  return (
    <figure className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4" data-testid="graph-picture">
      <svg
        viewBox={`${-SIDE} 0 ${SIZE + 2 * SIDE} ${SIZE}`}
        className="mx-auto w-full max-w-xl"
        role="img"
        aria-label={`${describeShown(graph)}, drawn as lines between the papers. Each relation is listed below.`}
      >
        {lines.map((line) => {
          const from = placed[line.a];
          const to = placed[line.b];
          if (from === undefined || to === undefined) return null;
          // Two kinds between the same papers are drawn side by side, each moved off the line between them
          const length = Math.hypot(to.x - from.x, to.y - from.y) || 1;
          const dx = (-(to.y - from.y) / length) * line.offset * 5;
          const dy = ((to.x - from.x) / length) * line.offset * 5;

          return (
            <line
              key={`${line.a}-${line.b}-${line.kind}`}
              x1={from.x + dx}
              y1={from.y + dy}
              x2={to.x + dx}
              y2={to.y + dy}
              className={cn(KIND_STROKES[line.kind], line.kind === "differs" && "[stroke-dasharray:5_4]")}
              strokeWidth={2}
              strokeLinecap="round"
              data-kind={line.kind}
            />
          );
        })}
        {graph.papers.map((paper) => {
          const at = placed[paper.id];
          const outward = at.x < SIZE / 2 - 1 ? "end" : at.x > SIZE / 2 + 1 ? "start" : "middle";
          const below = at.y > SIZE / 2 + 1;

          return (
            <g key={paper.id}>
              <title>{paper.title}</title>
              <circle cx={at.x} cy={at.y} r={7} className={cn("stroke-2", paper.read ? "fill-foreground stroke-foreground" : "fill-card stroke-muted-foreground")} />
              {titled && (
                <text
                  x={at.x + (outward === "end" ? -11 : outward === "start" ? 11 : 0)}
                  y={at.y + (outward === "middle" ? (below ? 20 : -13) : 4)}
                  textAnchor={outward}
                  className="fill-muted-foreground text-[10px]"
                >
                  {shortTitle(paper.title, outward === "middle" ? 40 : SIDE_TITLE)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <figcaption className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" data-testid="graph-legend">
        {kinds.map((kind) => (
          <span key={kind} className="inline-flex items-center gap-1.5">
            <Swatch kind={kind} />
            {KIND_TITLES[kind]} ({graph.counts[kind]})
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block size-2.5 rounded-full border-2 border-muted-foreground" aria-hidden />
          Not read
        </span>
        {!titled && <span>Hover a point for its paper</span>}
      </figcaption>
    </figure>
  );
}

function Quote({ place, title }: { place: GraphPlace; title: string }) {
  const status = describeClaimStatus(place.reproduction);

  return (
    <figure className="flex flex-col gap-0.5 border-l-2 border-border pl-3" data-testid="graph-quote">
      <blockquote className="break-words text-xs leading-5">“{place.quote}”</blockquote>
      <figcaption className="text-xs text-muted-foreground">
        {title}, {describeWhere(place)}
        {status !== null && <>. {status}</>}
      </figcaption>
    </figure>
  );
}

function Evidence({ relation, evidence, titles }: { relation: GraphRelation; evidence: GraphEvidence; titles: Record<string, string> }) {
  const title = (id: string) => titles[id] ?? id;

  if (relation.kind === "code") return <p className="break-words text-xs text-muted-foreground">{describeCommits(evidence, titles)}</p>;
  if (relation.kind === "refers") {
    return (
      <div className="flex flex-col gap-1">
        <p className="text-xs text-muted-foreground">{describeReference(evidence, title(relation.a), title(relation.b))}</p>
        {evidence.at !== undefined && <Quote place={evidence.at} title={title(relation.a)} />}
      </div>
    );
  }
  const versions = relation.kind === "software" ? describeVersions(evidence, titles) : null;

  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-xs text-muted-foreground">
        {relation.kind === "agrees" || relation.kind === "differs" ? describeShared(evidence) : <>Named as {evidence.matched}</>}
        {versions !== null && <> {versions}</>}
      </p>
      {evidence.a !== undefined && <Quote place={evidence.a} title={title(relation.a)} />}
      {evidence.b !== undefined && <Quote place={evidence.b} title={title(relation.b)} />}
    </div>
  );
}

function Relation({ relation, titles }: { relation: GraphRelation; titles: Record<string, string> }) {
  const basis = describeBasis(relation);
  const places = relation.evidence.length;

  return (
    <li className="flex flex-col gap-2 rounded-xl border border-border bg-card p-4" data-testid="graph-relation" data-kind={relation.kind}>
      <div className="flex flex-wrap items-center gap-2">
        <Swatch kind={relation.kind} />
        <Badge variant="outline" title={KIND_HINTS[relation.kind]}>
          {KIND_TITLES[relation.kind]}
        </Badge>
        {relation.corroborated === true && <Badge variant="secondary">Corroborated</Badge>}
      </div>
      <p className="break-words text-sm">{relation.summary}</p>
      {basis !== null && <p className="text-xs text-muted-foreground">{basis}.</p>}
      {places > 0 && (
        <details className="group">
          <summary className="w-fit cursor-pointer rounded-sm text-xs text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50">
            {places === 1 ? "Where it is found" : `Where it is found (${places} places)`}
          </summary>
          <div className="mt-2 flex flex-col gap-3">
            {relation.evidence.map((evidence, index) => (
              <Evidence key={index} relation={relation} evidence={evidence} titles={titles} />
            ))}
          </div>
        </details>
      )}
    </li>
  );
}

function PaperRow({
  paper,
  shown,
  chosen,
  busy,
  onChoose,
}: {
  paper: GraphPaper;
  // How many of the relations that are shown it is in, if only some are, as the server's count is of all of them
  shown: number | null;
  chosen: boolean;
  busy: boolean;
  onChoose: (id: string | undefined) => void;
}) {
  const reproduction = describeReproduction(paper.reproduction);

  return (
    <li className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-4" data-testid="graph-paper" data-id={paper.id}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 break-words text-sm font-medium">
          <Link href={agentAddress(paper.id)} className={LINK}>
            {paper.title}
          </Link>
        </h3>
        {!paper.read && <Badge variant="outline">Not read</Badge>}
        <span className="text-xs text-muted-foreground">{describeRelationCount(paper.relations, shown)}</span>
      </div>
      <p className="text-xs text-muted-foreground">{describeGraphPaper(paper)}</p>
      {reproduction !== null && <p className="text-xs text-muted-foreground">{reproduction}</p>}
      {paper.relations > 0 && (
        <div>
          <Button variant="outline" size="xs" onClick={() => onChoose(chosen ? undefined : paper.id)} aria-pressed={chosen} disabled={busy}>
            {chosen ? "Show every paper's relations" : "Only its relations"}
          </Button>
        </div>
      )}
    </li>
  );
}

function Empty({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-dashed border-border p-5" data-testid="graph-empty">
      <p className="text-sm font-medium">{title}</p>
      <p className="text-sm text-muted-foreground">{children}</p>
    </div>
  );
}

function Shown({
  graph,
  query,
  titles,
  busy,
  onChoose,
  onClear,
}: {
  graph: PaperAgentGraph;
  query: GraphQuery;
  titles: Record<string, string>;
  busy: boolean;
  onChoose: (id: string | undefined) => void;
  onClear: () => void;
}) {
  const narrowed = isNarrowed(query);
  const limits = describeLimits(graph);
  const shownOf = (id: string) => graph.relations.filter((each) => each.a === id || each.b === id).length;
  // A paper that is asked for is among the papers whenever it is in the graph, so one that is not was left out, or is gone
  const outside = query.agent !== undefined && !graph.papers.some((paper) => paper.id === query.agent);

  if (outside) {
    return (
      <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-border p-5" data-testid="graph-empty">
        <p className="text-sm font-medium">This agent is not in the graph</p>
        <p className="text-sm text-muted-foreground">
          {graph.left_out > 0
            ? `Only the first ${graph.limits.most_papers} agents are put against each other, and it is not one of them, so it was not compared with the others.`
            : "It is not among the agents there are now."}
        </p>
        <Button variant="outline" size="xs" onClick={onClear} disabled={busy}>
          Show every relation
        </Button>
      </div>
    );
  }

  if (!narrowed && graph.papers.length === 0) {
    return <Empty title="There are no agents yet">The graph relates the papers of the agents, so it has something to show once there are two.</Empty>;
  }

  return (
    <div className="flex flex-col gap-6">
      {graph.relations.length === 0 ? (
        narrowed ? (
          <div className="flex flex-col items-start gap-2 rounded-xl border border-dashed border-border p-5" data-testid="graph-empty">
            <p className="text-sm font-medium">No relation is of what is asked for</p>
            <Button variant="outline" size="xs" onClick={onClear} disabled={busy}>
              Show every relation
            </Button>
          </div>
        ) : graph.papers.length === 1 ? (
          <Empty title="There is one agent">With one agent there is no other paper to put it against. Make another, and how the two relate is shown here.</Empty>
        ) : (
          <Empty title="No relation was found between the papers">That does not say there is none: a relation is found only by names, addresses, and words that the papers have in common, and a paper that was not read has few of them.</Empty>
        )
      ) : (
        <>
          <Picture graph={graph} />
          <section aria-label="Relations" className="flex flex-col gap-2">
            <p className="text-sm font-medium" data-testid="graph-shown">
              {describeShown(graph)}
            </p>
            <ul className="flex flex-col gap-2">
              {graph.relations.map((relation, index) => (
                <Relation key={`${relation.kind}-${relation.a}-${relation.b}-${index}`} relation={relation} titles={titles} />
              ))}
            </ul>
          </section>
        </>
      )}
      {graph.papers.length > 0 && (
        <section aria-label="Papers" className="flex flex-col gap-2">
          <p className="text-sm font-medium">{narrowed ? "The papers of these relations" : "The papers"}</p>
          <ul className="flex flex-col gap-2">
            {graph.papers.map((paper) => (
              <PaperRow
                key={paper.id}
                paper={paper}
                shown={narrowed ? shownOf(paper.id) : null}
                chosen={query.agent === paper.id}
                busy={busy}
                onChoose={onChoose}
              />
            ))}
          </ul>
        </section>
      )}
      {limits.map((said) => (
        <p key={said} className="text-xs text-muted-foreground" data-testid="graph-limits">
          {said}
        </p>
      ))}
      <p className="text-xs text-muted-foreground" data-testid="graph-meaning">
        {graph.meaning}
      </p>
    </div>
  );
}

// The graph of how the papers of the agents relate, which can be asked for the relations of one paper, of one kind, or on words.
// `of` is the agent whose relations are asked for first, as the address of its page's link says
export function Graph({ of }: { of: string | null }) {
  const { report } = useServer();
  const jobs = useSetupJobs();
  const id = useId();
  const [query, setQuery] = useState<GraphQuery>(() => (of ? { agent: of } : {}));
  const [words, setWords] = useState("");
  const attempt = useAttempt(report);
  // The graph is made from what the steps keep, so it is looked at again as any of them ends
  const graph = usePaperAgentGraph(query, report, String(jobs.finished));
  const list = usePaperAgentsList(report, String(jobs.finished));
  const agents = list.value.kind === "ready" ? list.value.value.agents : [];
  const titles: Record<string, string> = Object.fromEntries(agents.map((agent) => [agent.id, agent.title]));
  if (graph.value.kind === "ready") for (const paper of graph.value.value.graph?.papers ?? []) titles[paper.id] = paper.title;
  const field = (name: string) => `${id}-${name}`;

  function choose(part: Partial<GraphQuery>) {
    attempt.forget();
    setQuery((was) => ({ ...was, ...part }));
  }

  // Words are asked of the server before they are kept, as words that have none of their own are refused, and the graph that was
  // shown must not be left beside words that it is not of
  // Nothing else can be asked while the words are, so the query they are asked with is still the one when the answer comes
  async function look() {
    const next = { ...query, about: words.trim() || undefined };
    const found = await attempt.run(() => api.paperAgentGraph(next));
    if (found === undefined) return;
    setQuery(next);
    graph.set({ key: graphQuery(next), graph: found, problem: null });
  }

  function clear() {
    attempt.forget();
    setWords("");
    setQuery({});
  }

  return (
    <PageSection title="Graph" intro={INTRO}>
      <form
        aria-label="Ask the graph"
        onSubmit={(event) => {
          event.preventDefault();
          void look();
        }}
        className="flex flex-col gap-3 rounded-lg border border-border p-3"
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <Field id={field("paper")} label="Paper">
            <NativeSelect
              id={field("paper")}
              value={query.agent ?? ""}
              onChange={(event) => choose({ agent: event.target.value || undefined })}
              disabled={attempt.busy}
            >
              <option value="">Every paper</option>
              {query.agent !== undefined && !agents.some((agent) => agent.id === query.agent) && <option value={query.agent}>{titles[query.agent] ?? query.agent}</option>}
              {agents.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.title}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id={field("kind")} label="Kind">
            <NativeSelect
              id={field("kind")}
              value={query.kind ?? ""}
              onChange={(event) => choose({ kind: (event.target.value || undefined) as GraphKind | undefined })}
              disabled={attempt.busy}
            >
              <option value="">Every kind</option>
              {KINDS.map((kind) => (
                <option key={kind} value={kind}>
                  {KIND_TITLES[kind]}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field id={field("words")} label="Words" hint="Any of them, in what a relation says or in its quotes.">
            <div className="flex gap-2">
              <Input
                id={field("words")}
                value={words}
                onChange={(event) => setWords(event.target.value)}
                maxLength={300}
                autoComplete="off"
                placeholder="A dataset, a method, a measure"
                aria-describedby={`${field("words")}-hint`}
              />
              <Button type="submit" variant="outline" disabled={attempt.busy}>
                <Search />
                Look
              </Button>
            </div>
          </Field>
        </div>
        {query.about !== undefined && (
          <p className="text-xs text-muted-foreground" data-testid="graph-about">
            Only the relations that have any of these words: {query.about}
          </p>
        )}
        {attempt.problem && <ProblemNotice problem={attempt.problem} />}
        {isNarrowed(query) && (
          <div>
            <Button type="button" variant="ghost" size="xs" onClick={clear} disabled={attempt.busy}>
              Show every relation
            </Button>
          </div>
        )}
      </form>
      <Looked state={graph.value} label="Looking at the graph" failure="The graph could not be looked at." onRetry={graph.reload}>
        {(answered) =>
          answered.key !== graphQuery(query) ? (
            <div className="flex flex-col gap-2" role="status" aria-busy="true" aria-label="Looking at the graph" data-testid="graph-looking">
              <Skeleton className="h-16 w-full" />
            </div>
          ) : answered.graph === null ? (
            <div className="flex flex-col items-start gap-2" data-testid="graph-failed">
              {answered.problem !== null && <ProblemNotice problem={answered.problem} />}
              <Button variant="outline" size="xs" onClick={graph.reload}>
                Try again
              </Button>
            </div>
          ) : (
            <Shown graph={answered.graph} query={query} titles={titles} busy={attempt.busy} onChoose={(agent) => choose({ agent })} onClear={clear} />
          )
        }
      </Looked>
    </PageSection>
  );
}
