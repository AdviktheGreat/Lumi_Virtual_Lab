"use client";

import { useId, useState } from "react";
import { Download } from "lucide-react";
import { Looked } from "@/components/looked";
import { useServer } from "@/components/server-provider";
import { describedBy, Field } from "@/components/settings-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  answeredCount,
  checkTolerance,
  comparisonKey,
  describeAgreement,
  describeAsking,
  describeGroundTruth,
  describeOutcomes,
  describePairKept,
  describeRank,
  describeReading,
  describeScore,
  describeScoreDetail,
  describeSeconds,
  describeSinceShort,
  describeTolerance,
  describeWhy,
  EMPTY_TOLERANCE,
  KEPT_LABELS,
  nameOf,
  RUN_STATE_LABELS,
  tableAddress,
  VERDICT_LABELS,
  type TableKind,
  type ToleranceDraft,
} from "@/lib/bakeoff-runs";
import { describeSpending } from "@/lib/bakeoffs";
import type { Bakeoff, BakeoffComparedMethod, BakeoffComparison, BakeoffTolerance, BakeoffVerdict } from "@/lib/types";
import { useBakeoffComparison } from "@/lib/use-bakeoffs";
import { cn } from "@/lib/utils";

const LINK =
  "inline-flex items-center gap-1 rounded-sm text-xs text-brand underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50";
const WARNING = "rounded-md border border-warning/60 bg-warning/15 px-1.5 py-0.5 text-foreground";
const HEAD = "px-2.5 py-1.5 text-left font-medium align-bottom";
const CELL = "px-2.5 py-1.5 align-top";

const STATE_VARIANT = {
  ran: "secondary",
  failed: "destructive",
  not_run: "outline",
  not_built: "outline",
} as const;

const VERDICT_VARIANT: Record<BakeoffVerdict, "secondary" | "destructive" | "outline"> = {
  agree: "secondary",
  differ: "destructive",
  unknown: "outline",
};

// How the methods came out, one to a row: where each stands, what was called, how long it took, what it cost, which of the others it
// agrees with, and, if right answers were given, how it did against them. A method that was not run, or failed, or is not built is a row
// too, with why. A method that was not scored is not given a score of nothing.
function MethodsTable({ comparison }: { comparison: BakeoffComparison }) {
  const scored = comparison.ground_truth !== null;

  return (
    <div className="max-h-[32rem] overflow-auto rounded-lg border border-border">
      <table aria-label="Methods compared" className="w-full border-collapse text-xs" data-testid="compare-methods">
        <thead className="sticky top-0 bg-muted">
          <tr>
            <th scope="col" className={HEAD}>
              Method
            </th>
            <th scope="col" className={HEAD}>
              How it came out
            </th>
            <th scope="col" className={HEAD}>
              Tool called
            </th>
            <th scope="col" className={HEAD}>
              Took
            </th>
            <th scope="col" className={HEAD}>
              Reading its paper cost
            </th>
            <th scope="col" className={HEAD}>
              Asking a model for the call cost
            </th>
            <th scope="col" className={HEAD}>
              Call chosen by
            </th>
            <th scope="col" className={HEAD}>
              What was kept of its answer
            </th>
            <th scope="col" className={HEAD}>
              Against the other methods
            </th>
            {scored && (
              <>
                <th scope="col" className={HEAD}>
                  Against the right answers
                </th>
                <th scope="col" className={HEAD}>
                  Rank
                </th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {comparison.methods.map((method) => (
            <MethodRow key={method.id} method={method} methods={comparison.methods} scored={scored} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MethodRow({ method, methods, scored }: { method: BakeoffComparedMethod; methods: readonly BakeoffComparedMethod[]; scored: boolean }) {
  const why = describeWhy(method.state, method.why);
  const agreement = describeAgreement(method, methods);

  return (
    <tr className="border-t border-border" data-testid="compare-method" data-method={method.id} data-state={method.state} data-why={method.why ?? ""}>
      <th scope="row" className={cn(CELL, "text-left font-medium")}>
        <span className="break-words">{method.name}</span>
        {method.title !== "" && <span className="block break-words font-normal text-muted-foreground">{method.title}</span>}
      </th>
      <td className={CELL}>
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-1">
            <Badge variant={STATE_VARIANT[method.state]}>{RUN_STATE_LABELS[method.state]}</Badge>
            {why !== null && <span>{why}</span>}
          </div>
          {method.state !== "ran" && method.reason !== "" && <span className="break-words text-muted-foreground">{method.reason}</span>}
          {describeSinceShort(method.since).map((line) => (
            <span key={line} className={WARNING} data-testid="compare-since">
              {line}
            </span>
          ))}
        </div>
      </td>
      <td className={CELL}>
        {method.tool !== null ? (
          <>
            <span className="break-words">{method.tool}</span>
            {method.tier !== null && <span className="block text-muted-foreground">tier {method.tier}</span>}
          </>
        ) : (
          "—"
        )}
      </td>
      <td className={CELL}>{describeSeconds(method.seconds) || "—"}</td>
      <td className={CELL}>{describeReading(method)}</td>
      <td className={CELL}>{describeAsking(method)}</td>
      <td className={CELL}>{method.by === null ? "—" : method.by === "person" ? "You" : "A model"}</td>
      <td className={CELL}>{method.kept === null ? "—" : KEPT_LABELS[method.kept]}</td>
      <td className={CELL}>
        {agreement.length === 0 ? (
          "—"
        ) : (
          <ul className="flex flex-col gap-0.5">
            {agreement.map((line) => (
              <li key={line.label}>
                <span className="text-muted-foreground">{line.label}</span> {line.names.join(", ")}
              </li>
            ))}
          </ul>
        )}
      </td>
      {scored && (
        <>
          <td className={CELL} data-testid="compare-score">
            {method.score === null ? (
              "—"
            ) : (
              <div className="flex flex-col gap-0.5">
                <span className={cn(!method.score.scored && "text-muted-foreground")}>{describeScore(method.score)}</span>
                {describeScoreDetail(method.score).map((line) => (
                  <span key={line} className="text-muted-foreground">
                    {line}
                  </span>
                ))}
                {method.score.examples.length > 0 && (
                  <details>
                    <summary className="cursor-pointer text-muted-foreground">Some it got wrong</summary>
                    <ul className="list-disc pl-4">
                      {method.score.examples.map((example) => (
                        <li key={example} className="break-words">
                          {example}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}
          </td>
          <td className={CELL} data-testid="compare-rank">
            {describeRank(method, methods)}
          </td>
        </>
      )}
    </tr>
  );
}

// Each two methods that gave an answer, and whether the answers are the same as far as what was kept of them shows
function PairsTable({ comparison }: { comparison: BakeoffComparison }) {
  if (comparison.pairs.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="compare-pairs-none">
        {answeredCount(comparison) < 2
          ? "Fewer than two methods gave an answer, so none is compared with another."
          : "No two of the methods have answers that can be compared."}
      </p>
    );
  }

  return (
    <div className="max-h-[32rem] overflow-auto rounded-lg border border-border">
      <table aria-label="Methods against each other" className="w-full border-collapse text-xs" data-testid="compare-pairs">
        <thead className="sticky top-0 bg-muted">
          <tr>
            <th scope="col" className={HEAD}>
              One method
            </th>
            <th scope="col" className={HEAD}>
              The other
            </th>
            <th scope="col" className={HEAD}>
              Their answers
            </th>
            <th scope="col" className={HEAD}>
              How it was seen
            </th>
            <th scope="col" className={HEAD}>
              Where they differ
            </th>
          </tr>
        </thead>
        <tbody>
          {comparison.pairs.map((pair) => (
            <tr key={`${pair.first}|${pair.second}`} className="border-t border-border" data-testid="compare-pair" data-verdict={pair.verdict}>
              <th scope="row" className={cn(CELL, "text-left font-medium")}>
                {nameOf(pair.first, comparison.methods)}
              </th>
              <td className={CELL}>{nameOf(pair.second, comparison.methods)}</td>
              <td className={CELL}>
                <Badge variant={VERDICT_VARIANT[pair.verdict]}>{VERDICT_LABELS[pair.verdict]}</Badge>
              </td>
              <td className={CELL}>
                <span className="break-words">{pair.how}</span>
                <span className="block text-muted-foreground">{describePairKept(pair)}</span>
              </td>
              <td className={CELL}>
                {pair.differences.length === 0 ? (
                  "—"
                ) : (
                  <ul className="flex list-disc flex-col gap-0.5 pl-4">
                    {pair.differences.map((line) => (
                      <li key={line} className="break-words">
                        {line}
                      </li>
                    ))}
                  </ul>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// How closely two numbers must be to be the same, which is the person's to say and is said back with the table. Nothing typed is what the
// checks hold the tools to.
function ToleranceForm({
  held,
  onApply,
  onReset,
  applied,
}: {
  held: BakeoffTolerance;
  onApply: (tolerance: Partial<BakeoffTolerance>) => void;
  onReset: () => void;
  applied: boolean;
}) {
  const id = useId();
  const [typed, setTyped] = useState<ToleranceDraft>(EMPTY_TOLERANCE);
  const [tried, setTried] = useState(false);
  const checked = checkTolerance(typed);
  const problems = tried ? checked.problems : {};
  const blank = typed.relative.trim() === "" && typed.absolute.trim() === "";

  return (
    <form
      aria-label="How closely numbers must agree"
      onSubmit={(event) => {
        event.preventDefault();
        setTried(true);
        if (checked.value !== null && !blank) onApply(checked.value);
      }}
      className="flex flex-col gap-3 rounded-lg border border-border p-3"
    >
      <p className="text-xs text-muted-foreground" data-testid="compare-tolerance">
        {describeTolerance(held)}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id={`${id}-relative`} label="As a part of the larger number" hint="Less than 1, such as 0.001. Blank keeps what it is." problem={problems.relative}>
          <Input
            id={`${id}-relative`}
            value={typed.relative}
            onChange={(event) => setTyped((was) => ({ ...was, relative: event.target.value }))}
            inputMode="decimal"
            autoComplete="off"
            aria-invalid={problems.relative !== undefined}
            aria-describedby={describedBy(`${id}-relative`, { hint: true, problem: problems.relative !== undefined })}
          />
        </Field>
        <Field id={`${id}-absolute`} label="For two numbers near zero" hint="Such as 0.000001. Blank keeps what it is." problem={problems.absolute}>
          <Input
            id={`${id}-absolute`}
            value={typed.absolute}
            onChange={(event) => setTyped((was) => ({ ...was, absolute: event.target.value }))}
            inputMode="decimal"
            autoComplete="off"
            aria-invalid={problems.absolute !== undefined}
            aria-describedby={describedBy(`${id}-absolute`, { hint: true, problem: problems.absolute !== undefined })}
          />
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" variant="outline" size="sm" disabled={blank}>
          Compare again with these
        </Button>
        {applied && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              setTyped(EMPTY_TOLERANCE);
              setTried(false);
              onReset();
            }}
          >
            Go back to what it was
          </Button>
        )}
      </div>
    </form>
  );
}

function ComparisonBody({
  comparison,
  applied,
  onApply,
  onReset,
}: {
  comparison: BakeoffComparison;
  applied: Partial<BakeoffTolerance>;
  onApply: (tolerance: Partial<BakeoffTolerance>) => void;
  onReset: () => void;
}) {
  const truth = comparison.ground_truth;
  const link = (kind: TableKind, what: string) => (
    <a href={tableAddress(comparison.id, kind, applied)} download aria-label={`Download as a table, ${what}`} className={LINK}>
      <Download className="size-3" aria-hidden />
      Download as a table, {what}
    </a>
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <p className="text-sm" data-testid="compare-says">
          {comparison.says}
        </p>
        <p className="text-xs text-muted-foreground" data-testid="compare-outcomes">
          {describeOutcomes(comparison.methods)} {describeSpending(comparison)}.
        </p>
        <details className="rounded-lg border border-border px-3 py-2">
          <summary className="cursor-pointer text-sm">What agreeing, and a score, mean</summary>
          <p className="pt-2 text-xs text-muted-foreground" data-testid="compare-meaning">
            {comparison.meaning}
          </p>
        </details>
      </div>
      {truth !== null && (
        <div className="flex flex-col gap-1 text-sm" data-testid="compare-truth">
          <h3 className="text-sm font-medium">Right answers</h3>
          {describeGroundTruth(truth).map((line) => (
            <p key={line} className="break-words text-xs text-muted-foreground">
              {line}
            </p>
          ))}
          {!truth.ok && (
            <p className={cn("text-xs", WARNING)} data-testid="compare-truth-problem">
              {truth.problem}. The methods are not scored or ranked until that is put right.
            </p>
          )}
          {truth.ok && !comparison.ranked && (
            <p className="text-xs text-muted-foreground">No method could be held to them, so none is ranked. Each row says why.</p>
          )}
        </div>
      )}
      <MethodsTable comparison={comparison} />
      <div className="flex flex-col gap-2">
        <h3 className="text-sm font-medium">Against each other</h3>
        <PairsTable comparison={comparison} />
      </div>
      <ToleranceForm
        // Made again when the table is for another tolerance, so that it does not keep what was typed for one that is gone
        key={`${comparison.tolerance.relative}|${comparison.tolerance.absolute}`}
        held={comparison.tolerance}
        onApply={onApply}
        onReset={onReset}
        applied={applied.relative !== undefined || applied.absolute !== undefined}
      />
      <div className="flex flex-wrap items-center gap-4">
        {link("methods", "the methods")}
        {link("pairs", "each two of them")}
      </div>
    </div>
  );
}

// The methods of a bake-off side by side, as of now, made of what is kept: nothing is run and no model is asked for it. It is looked at
// again whenever the methods are built or run, or the bake-off is said again.
export function Comparison({ bakeoff, again }: { bakeoff: Bakeoff; again: string }) {
  const { report } = useServer();
  const [applied, setApplied] = useState<Partial<BakeoffTolerance>>({});
  const comparison = useBakeoffComparison(bakeoff.id, applied, report, comparisonKey(bakeoff, again));

  return (
    <Looked
      state={comparison.value}
      label="Putting the methods side by side"
      failure="The methods could not be put side by side."
      onRetry={comparison.reload}
    >
      {(found) => <ComparisonBody comparison={found} applied={applied} onApply={setApplied} onReset={() => setApplied({})} />}
    </Looked>
  );
}
