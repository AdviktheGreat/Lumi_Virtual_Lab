"use client";

import { Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatCost } from "@/lib/format";
import { count } from "@/lib/checks";
import { FINDING_LABELS, statusLabel } from "@/lib/papers";
import type { FindingKind, PaperResult, PaperRun } from "@/lib/types";

const FINDING_KINDS = Object.keys(FINDING_LABELS) as FindingKind[];

function ResultRow({ result }: { result: PaperResult }) {
  const read = result.status === "read";

  return (
    <tr className="odd:bg-muted/30 align-top" data-testid="paper-result">
      <td className="px-2.5 py-1.5">
        <div className="break-words font-medium">{result.title}</div>
        {result.doi && <div className="break-all text-muted-foreground">{result.doi}</div>}
        {result.error && <div className="break-words text-destructive">{result.error}</div>}
      </td>
      <td className="whitespace-nowrap px-2.5 py-1.5">
        <Badge variant={result.status === "failed" ? "destructive" : result.status === "read" ? "secondary" : "outline"}>
          {statusLabel(result.status)}
        </Badge>
      </td>
      <td className="px-2.5 py-1.5 text-right tabular-nums">{read ? result.tasks : "–"}</td>
      <td className="px-2.5 py-1.5 text-right tabular-nums">{read ? result.databases : "–"}</td>
      <td className="px-2.5 py-1.5 text-right tabular-nums">{read ? result.software : "–"}</td>
      <td className="whitespace-nowrap px-2.5 py-1.5 text-right tabular-nums">{formatCost(result.cost) || "–"}</td>
    </tr>
  );
}

// What was found in each paper of a run, as far as it has been read
export function Results({ run }: { run: PaperRun }) {
  if (run.results.length === 0) return <p className="text-sm text-muted-foreground">There are no papers in this run yet.</p>;
  const read = run.results.filter((result) => result.status === "read").length;

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        {read} of {count(run.results.length, "paper")} read.
      </p>
      <div className="max-h-96 overflow-auto rounded-lg border border-border">
        <table aria-label="Papers" className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-muted">
            <tr>
              <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                Paper
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                Status
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                Tasks
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                Databases
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                Software
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                Cost
              </th>
            </tr>
          </thead>
          <tbody>
            {run.results.map((result) => (
              <ResultRow key={result.key} result={result} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Counts({ run, kind }: { run: PaperRun; kind: FindingKind }) {
  const rows = run.summary[kind];
  const more = run.summary.more[kind];
  if (rows.length === 0) return null;
  const label = FINDING_LABELS[kind];

  return (
    <div className="flex flex-col gap-2" data-testid={`paper-${kind}`}>
      <div className="flex items-center gap-2">
        <h3 className="flex-1 text-sm font-medium">{label}</h3>
        <a
          href={`/api/papers/runs/${encodeURIComponent(run.id)}/tables/${kind}`}
          download
          aria-label={`Download as a table, ${label.toLowerCase()}`}
          className="inline-flex items-center gap-1 rounded-sm text-xs text-brand underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
        >
          <Download className="size-3" aria-hidden />
          Download as a table
        </a>
      </div>
      <div className="max-h-72 overflow-auto rounded-lg border border-border">
        <table aria-label={label} className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-muted">
            <tr>
              <th scope="col" className="px-2.5 py-1.5 text-left font-medium">
                Name
              </th>
              <th scope="col" className="px-2.5 py-1.5 text-right font-medium">
                Papers it is found in
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.name} className="odd:bg-muted/30">
                <td className="break-words px-2.5 py-1">{row.name}</td>
                <td className="px-2.5 py-1 text-right tabular-nums">{row.papers}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {more > 0 && (
        <p className="text-xs text-muted-foreground">
          {more} more {more === 1 ? "is" : "are"} in the table that can be downloaded.
        </p>
      )}
    </div>
  );
}

// What the papers that were read have in common, the most common first
export function Shared({ run }: { run: PaperRun }) {
  if (run.summary.papers === 0) {
    return <p className="text-sm text-muted-foreground">Nothing is counted until some papers have been read.</p>;
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-xs text-muted-foreground">Counted from {count(run.summary.papers, "paper")}.</p>
      {FINDING_KINDS.map((kind) => (
        <Counts key={kind} run={run} kind={kind} />
      ))}
    </div>
  );
}
