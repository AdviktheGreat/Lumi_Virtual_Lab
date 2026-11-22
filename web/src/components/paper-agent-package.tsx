"use client";

import { useState } from "react";
import { Download, Package, Trash2 } from "lucide-react";
import { JobOutput } from "@/components/job-output";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Aside } from "@/components/settings-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { api, ApiError } from "@/lib/api";
import {
  describeEnvironment,
  describeLicense,
  describePackage,
  describeTested,
  describeToolCount,
  describeVersion,
  FLAG_TITLES,
  needsAccepting,
  packageAddress,
  packageState,
  shortHash,
  whyNoPackage,
} from "@/lib/paperagent-library";
import type { Job, LibraryEntry, PaperAgent, PaperAgentExport, ToolPackage } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";

// What the agent's tools are pinned to: the commit of the code, the environment they were made in with the lock of its versions, the
// code's license, and each tool with its tier and the hash of its wrapper
export function Pinned({ entry }: { entry: LibraryEntry }) {
  return (
    <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]" data-testid="library-pin">
      <dt className="text-muted-foreground">The code</dt>
      <dd className="min-w-0 break-words" data-testid="library-version">
        {describeVersion(entry.version)}
      </dd>
      <dt className="text-muted-foreground">The environment</dt>
      <dd className="min-w-0 break-words" data-testid="library-environment">
        {describeEnvironment(entry.environment)}
        <span className="block text-xs text-muted-foreground">
          Image <code className="font-mono">{shortHash(entry.environment.image.id)}</code>, lock{" "}
          <code className="font-mono">{shortHash(entry.environment.lock.sha256)}</code>
        </span>
      </dd>
      <dt className="text-muted-foreground">The license</dt>
      <dd className="flex min-w-0 flex-wrap items-baseline gap-x-2 break-words" data-testid="library-license" data-flag={entry.license.flag ?? ""}>
        <span>{describeLicense(entry.license)}</span>
        {entry.license.flag !== null && <Badge variant="secondary">{FLAG_TITLES[entry.license.flag]}</Badge>}
      </dd>
      <dt className="text-muted-foreground">The tools</dt>
      <dd className="min-w-0">
        <span className="text-xs text-muted-foreground">{describeToolCount(entry)}</span>
        <ul aria-label="The tools that are pinned" className="mt-1 flex flex-col gap-1">
          {entry.tools.map((tool) => (
            <li key={tool.name} className="flex flex-wrap items-baseline gap-x-2" data-testid="library-tool" data-name={tool.name} data-tier={tool.tier}>
              <code className="font-mono text-xs font-medium">{tool.name}</code>
              <Badge variant="outline">Tier {tool.tier}</Badge>
              <span className="min-w-0 break-all text-xs text-muted-foreground">
                {tool.function}, wrapper <code className="font-mono">{shortHash(tool.wrapper_sha256)}</code>
              </span>
            </li>
          ))}
        </ul>
      </dd>
    </dl>
  );
}

// The package that was made, which can be downloaded only while it is of what is kept
function Made({ made, agent, busy, onRemoved }: { made: ToolPackage; agent: PaperAgent; busy: boolean; onRemoved: (next: PaperAgentExport) => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);

  async function remove() {
    const next = await attempt.run(() => api.removePaperAgentExport(agent.id));
    if (next) onRemoved(next);
  }

  return (
    <section
      aria-label="The package"
      className="flex flex-col gap-2 rounded-lg border border-border p-3"
      data-testid="package-made"
      data-current={made.current ? "true" : "false"}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Package className="size-4 text-muted-foreground" aria-hidden />
        <h3 className="text-sm font-medium">The package</h3>
        <Badge variant={made.current ? "default" : "secondary"}>{made.current ? "Of what is kept" : "Out of date"}</Badge>
      </div>
      <p className="text-sm" data-testid="package-summary">
        {describePackage(made)}
      </p>
      <p className="text-xs text-muted-foreground" data-testid="package-tested">
        {describeTested(made.tested)}
      </p>
      <p className="break-all text-xs text-muted-foreground">
        SHA-256 <code className="font-mono">{made.sha256}</code>
      </p>
      {made.accepted_license && made.license.flag !== null && (
        <p className="text-xs text-muted-foreground" data-testid="package-accepted">
          Made after you said to go on with code whose license is flagged: {FLAG_TITLES[made.license.flag].toLowerCase()}. Its README begins with what
          that means.
        </p>
      )}
      {!made.current && (
        <Aside tone="warning">
          It was made of tools, a version of the code, or an environment that are not what is kept now, so it cannot be downloaded. Make it again.
        </Aside>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {made.current && (
          <Button asChild size="sm" variant="outline">
            <a href={packageAddress(agent.id)} download={made.file}>
              <Download />
              Download {made.file}
            </a>
          </Button>
        )}
        <Button type="button" variant="ghost" size="sm" onClick={() => void remove()} disabled={busy || attempt.busy}>
          <Trash2 />
          Take the package away
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </section>
  );
}

// Makes the package, once what is said of a license that is flagged has been read
function MakePackage({
  agent,
  entry,
  busy,
  jobs,
  again,
  onStale,
}: {
  agent: PaperAgent;
  entry: LibraryEntry;
  busy: boolean;
  jobs: JobsData;
  // Whether there is a package already, which this makes again
  again: boolean;
  onStale: () => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [accepted, setAccepted] = useState(false);
  const asks = needsAccepting(entry);

  async function make() {
    const job = await attempt.run(async () => {
      try {
        return await api.exportPaperAgent(agent.id, asks && accepted);
      } catch (error) {
        // What the page showed of the tools, the environment, or the license is not what is kept, which it looks at again
        if (error instanceof ApiError && (error.code === "license" || error.code === "no_tools" || error.code === "docker_missing" || error.code === "image_missing")) onStale();
        throw error;
      }
    });
    if (job) jobs.track(job);
  }

  return (
    <div className="flex flex-col gap-2">
      {asks && entry.license.said !== null && (
        <div className="flex flex-col gap-2 rounded-lg bg-warning/15 px-3 py-2" data-testid="package-license">
          <p className="text-sm">{entry.license.said}</p>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox checked={accepted} onChange={(event) => setAccepted(event.target.checked)} />I have read this, and go on
          </label>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Button type="button" onClick={() => void make()} disabled={busy || attempt.busy || (asks && !accepted)}>
          <Package />
          {attempt.busy ? "Starting…" : again ? "Make the package again" : "Make a package"}
        </Button>
        <span className="text-xs text-muted-foreground">
          A ZIP that is a server of the Model Context Protocol, with the code, the tools, the lock, and a Dockerfile. It is kept only if it gives
          what the tutorials got when it is run in a clean container.
        </span>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </div>
  );
}

// The agent's tools as a version that is pinned, and a package of them that runs anywhere, made and checked here
export function PackageSection({
  agent,
  exported,
  busy,
  making,
  jobs,
  onChanged,
  onStale,
}: {
  agent: PaperAgent;
  exported: PaperAgentExport;
  // Whether anything is being done to the agent, which making a package waits for
  busy: boolean;
  // The making of a package that is at work, if there is one
  making: Job | undefined;
  jobs: JobsData;
  onChanged: (next: PaperAgentExport) => void;
  onStale: () => void;
}) {
  const { entry } = exported;
  const why = whyNoPackage(entry, exported.docker);

  if (entry === null) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="package-no-tools">
        {why}
      </p>
    );
  }
  const idle = making === undefined && exported.job === null;

  return (
    <div className="flex flex-col gap-4">
      <Pinned entry={entry} />
      {making !== undefined && <JobOutput key={making.id} job={making} jobs={jobs} />}
      {idle && entry.export !== null && <Made made={entry.export} agent={agent} busy={busy} onRemoved={onChanged} />}
      {idle &&
        (why !== null ? (
          <Aside tone="warning">{why}</Aside>
        ) : (
          <MakePackage key={entry.state} agent={agent} entry={entry} busy={busy} jobs={jobs} again={packageState(entry) !== "none"} onStale={onStale} />
        ))}
      <p className="text-xs text-muted-foreground" data-testid="package-meaning">
        {exported.meaning}
      </p>
    </div>
  );
}
