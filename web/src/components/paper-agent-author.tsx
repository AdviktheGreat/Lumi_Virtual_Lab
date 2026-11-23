"use client";

import { Download, RefreshCw } from "lucide-react";
import { CopyButton } from "@/components/copy-button";
import { Markdown } from "@/components/markdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AREA_TITLES,
  authorPackageAddress,
  bySeverity,
  describeCarried,
  describeCounts,
  describeFile,
  describeUnchecked,
  SEVERITY_TITLES,
  SEVERITY_WORDS,
  severityVariant,
  VERDICT_TITLES,
  verdictVariant,
  whyNoAuthorPackage,
} from "@/lib/paperagent-authoring";
import type { AuthorFinding, PaperAgentAuthor } from "@/lib/types";

const LINK =
  "inline-flex items-center gap-1 rounded-sm text-sm text-brand underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50";

function Finding({ finding }: { finding: AuthorFinding }) {
  return (
    <li className="flex flex-col gap-1.5 rounded-xl border border-border bg-card p-4" data-testid="author-finding" data-id={finding.id} data-severity={finding.severity}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={severityVariant(finding.severity)}>{SEVERITY_WORDS[finding.severity]}</Badge>
        <Badge variant="outline">{AREA_TITLES[finding.area]}</Badge>
        <h4 className="min-w-0 break-words text-sm font-medium">{finding.title}</h4>
      </div>
      <p className="break-words text-sm text-muted-foreground">{finding.detail}</p>
      {finding.where.length > 0 && (
        <ul aria-label="Where it is" className="flex flex-col gap-0.5">
          {finding.where.map((place) => (
            <li key={place} className="break-all font-mono text-xs">
              {place}
            </li>
          ))}
        </ul>
      )}
      {finding.fix !== null && (
        <p className="text-sm">
          <span className="font-medium">To mend it: </span>
          {finding.fix}
        </p>
      )}
    </li>
  );
}

// A text for the authors, which is shown as it would read and can be copied as it is, in Markdown
function Written({ title, text, testId }: { title: string; text: string; testId: string }) {
  return (
    <details className="rounded-xl border border-border bg-card p-4" data-testid={testId}>
      <summary className="cursor-pointer rounded-sm text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50">{title}</summary>
      <div className="mt-3 flex flex-col gap-3">
        <div>
          <CopyButton text={text} label="Copy as Markdown" />
        </div>
        <Markdown text={text} className="text-sm leading-6" />
      </div>
    </details>
  );
}

// What a reader who takes the paper's code as a stranger would hit, the steps that would look at more, and the package for the authors
export function AuthorSection({ view, onReload }: { view: PaperAgentAuthor; onReload: () => void }) {
  const groups = bySeverity(view.findings);
  const why = whyNoAuthorPackage(view);
  const looked = view.verdict !== "not_checked";

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2" data-testid="author-verdict" data-verdict={view.verdict}>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={verdictVariant(view.verdict)}>{VERDICT_TITLES[view.verdict]}</Badge>
          <p className="text-sm">{view.summary}</p>
        </div>
        {looked && <p className="text-xs text-muted-foreground">{describeCounts(view.counts)}</p>}
        <div>
          <Button variant="outline" size="xs" onClick={onReload}>
            <RefreshCw />
            Look again
          </Button>
        </div>
      </div>

      {view.not_checked.length > 0 && (
        <section aria-label="Steps that were not run" className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Steps that were not run</h3>
          <ul className="flex flex-col gap-1 text-sm text-muted-foreground" data-testid="author-unchecked">
            {view.not_checked.map((item) => (
              <li key={item.id} data-id={item.id}>
                {describeUnchecked(item)}
              </li>
            ))}
          </ul>
        </section>
      )}

      {groups.map((group) => (
        <section key={group.severity} aria-label={SEVERITY_TITLES[group.severity]} className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">
            {SEVERITY_TITLES[group.severity]} ({group.findings.length})
          </h3>
          <ul className="flex flex-col gap-2">
            {group.findings.map((finding, index) => (
              <Finding key={`${finding.id}-${index}`} finding={finding} />
            ))}
          </ul>
        </section>
      ))}

      {looked && (
        <section aria-label="For the authors" className="flex flex-col gap-3">
          <h3 className="text-sm font-medium">For the authors</h3>
          <p className="text-sm text-muted-foreground">
            A reproducibility card and a statement of where the code, the data, and the software are, to read before they go in a paper or
            its repository. What is not known is left in [brackets] for you to fill.
          </p>
          <Written title="The reproducibility card" text={view.card} testId="author-card" />
          <Written title="The availability statement" text={view.statement} testId="author-statement" />
        </section>
      )}

      <section aria-label="The package for the authors" className="flex flex-col gap-2" data-testid="author-package" data-ready={String(view.package.ready)}>
        <h3 className="text-sm font-medium">The package for the authors</h3>
        {why !== null ? (
          <p className="text-sm text-muted-foreground">{why}</p>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">A ZIP of one folder, with these files. {describeCarried(view)}</p>
            <ul aria-label="What the package has" className="flex flex-col gap-0.5">
              {view.package.files.map((file) => (
                <li key={file.name} className="break-all font-mono text-xs">
                  {describeFile(file)}
                </li>
              ))}
            </ul>
            <div>
              <a href={authorPackageAddress(view.id)} download className={LINK}>
                <Download className="size-3.5" aria-hidden />
                Download the package
              </a>
            </div>
          </>
        )}
      </section>

      <p className="text-xs text-muted-foreground" data-testid="author-meaning">
        {view.meaning}
      </p>
    </div>
  );
}
