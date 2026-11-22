"use client";

import Link from "next/link";
import { Download } from "lucide-react";
import { Looked } from "@/components/looked";
import { Pinned } from "@/components/paper-agent-package";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { Aside } from "@/components/settings-fields";
import { useSetupJobs } from "@/components/setup-provider";
import { Badge } from "@/components/ui/badge";
import { statusVariant } from "@/lib/paperagent-living";
import { describeLibraryHealth, describePackageState, packageAddress, packageState } from "@/lib/paperagent-library";
import { agentAddress } from "@/lib/paperagents";
import type { PaperAgentLibrary } from "@/lib/types";
import { usePaperAgentLibrary } from "@/lib/use-paperagents";

const INTRO =
  "Each agent that has tools, as a version that is pinned: the commit of its code, the environment its tools were made in with the exact versions it installed, and each tool with the tier its checks come to now. It is made each time from what is kept, so a tool that was made again or an image that was taken away is shown as it is now. A package of an agent's tools, which runs anywhere as a server of the Model Context Protocol, is made on the agent's page.";

function Entry({ entry }: { entry: PaperAgentLibrary["agents"][number] }) {
  const state = packageState(entry);

  return (
    <li className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4" data-testid="library-entry" data-id={entry.id}>
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="min-w-0 break-words text-sm font-medium">
          <Link href={agentAddress(entry.id)} className="rounded-sm outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50">
            {entry.title}
          </Link>
        </h3>
        {entry.tier !== null && <Badge variant="outline">Tier {entry.tier}</Badge>}
        {entry.given && <Badge variant="secondary">In your conversations</Badge>}
      </div>
      <p className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground" data-testid="library-health" data-status={entry.health.status}>
        <Badge variant={statusVariant(entry.health.status)}>Health</Badge>
        {describeLibraryHealth(entry.health)}
      </p>
      <Pinned entry={entry} />
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs" data-testid="library-package" data-state={state}>
        <span className="text-muted-foreground">{describePackageState(entry)}</span>
        {state === "current" && entry.export !== null && (
          <a
            href={packageAddress(entry.id)}
            download={entry.export.file}
            className="inline-flex items-center gap-1 rounded-sm text-brand underline-offset-4 outline-none hover:underline focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <Download className="size-3" aria-hidden />
            Download {entry.export.file}
          </a>
        )}
      </div>
    </li>
  );
}

function Entries({ library }: { library: PaperAgentLibrary }) {
  if (library.agents.length === 0) {
    return (
      <div className="flex flex-col gap-1 rounded-xl border border-dashed border-border p-5" data-testid="library-empty">
        <p className="text-sm font-medium">No agent has tools yet</p>
        <p className="text-sm text-muted-foreground">An agent is listed here once its tools are made, on its page.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {!library.docker.ready && (
        <Aside tone="warning">{library.docker.message ?? "Docker is not running."} A package is checked in Docker, so none can be made until it runs.</Aside>
      )}
      <ul aria-label="The agents that have tools" className="flex flex-col gap-2">
        {library.agents.map((entry) => (
          <Entry key={entry.id} entry={entry} />
        ))}
      </ul>
      <p className="text-xs text-muted-foreground" data-testid="library-meaning">
        {library.meaning}
      </p>
    </div>
  );
}

// The lab's library: the agents that have tools, each as a version that is pinned, with the package of its tools if one was made
export function Library() {
  const { report } = useServer();
  const jobs = useSetupJobs();
  // What the library says changes as the steps that make tools, check them, look at an agent, or make a package end
  const library = usePaperAgentLibrary(report, String(jobs.finished));

  return (
    <PageSection title="Library" intro={INTRO}>
      <Looked state={library.value} label="Looking at the library" failure="The library could not be looked at." onRetry={library.reload}>
        {(value) => <Entries library={value} />}
      </Looked>
    </PageSection>
  );
}
