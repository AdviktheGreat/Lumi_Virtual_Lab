"use client";

import { useState } from "react";
import { Search } from "lucide-react";
import { Aside, Section } from "@/components/settings-fields";
import { JobProgress, StopButton, type SetupActions } from "@/components/setup-job";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { describeError } from "@/lib/errors";
import { formatBytes } from "@/lib/files";
import { activeJob, DATA_LAKE_BYTES, filterFiles, missingNames, roomWarning } from "@/lib/setup";
import type { DataLake, DataLakeFile, DataLakeSummary, Job } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

// What is to be fetched, which is asked about first when it is a good deal
interface Plan {
  // What the button that chooses it says
  button: string;
  names: string[];
}

function fileCount(count: number): string {
  return `${count} ${count === 1 ? "file" : "files"}`;
}

function Summary({ lake }: { lake: DataLakeSummary }) {
  const room = lake.free_bytes === null ? "" : `, ${formatBytes(lake.free_bytes)} free on that disk`;

  return (
    <div className="flex flex-col gap-1 text-sm">
      <p>
        <span className="font-medium">
          {lake.present} of {lake.files} files
        </span>{" "}
        are there, {formatBytes(lake.bytes)} in all{room}.
      </p>
      <p className="break-all text-xs text-muted-foreground">
        Kept in <code>{lake.directory}</code>
        {lake.custom ? ", the folder the settings name." : ", in the workspace."}
      </p>
    </div>
  );
}

function Confirm({
  plan,
  lake,
  actions,
  onDone,
}: {
  plan: Plan;
  lake: DataLakeSummary;
  actions: SetupActions;
  onDone: () => void;
}) {
  const warning = roomWarning(lake);

  return (
    <div role="group" aria-label="Fetch the data lake" className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <p className="text-sm">
        This fetches {fileCount(plan.names.length)}, which take up to about {formatBytes(DATA_LAKE_BYTES)} in all. It goes on in
        the background, and the files already fetched are kept if it is stopped.
      </p>
      {warning && <Aside tone="warning">{warning}</Aside>}
      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={() => {
            actions.fetch(plan.names);
            onDone();
          }}
          disabled={actions.busy}
        >
          Start fetching
        </Button>
        <Button variant="outline" size="sm" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function FileRow({ file, canFetch, actions }: { file: DataLakeFile; canFetch: boolean; actions: SetupActions }) {
  return (
    <li className="flex items-start gap-2 py-2">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <code className="break-all text-xs font-medium">{file.name}</code>
          {file.commercial && <Badge variant="outline">Commercial use</Badge>}
        </div>
        <p className="text-xs text-muted-foreground">{file.description}</p>
      </div>
      {file.present ? (
        <span className="shrink-0 text-xs text-muted-foreground">
          {file.bytes === null ? "There" : formatBytes(file.bytes)}
        </span>
      ) : (
        <Button
          variant="outline"
          size="xs"
          onClick={() => actions.fetch([file.name])}
          disabled={!canFetch || actions.busy}
          aria-label={`Fetch ${file.name}`}
        >
          Fetch
        </Button>
      )}
    </li>
  );
}

function Files({
  files,
  fetching,
  actions,
}: {
  files: DataLakeFile[];
  fetching: Job | undefined;
  actions: SetupActions;
}) {
  const [typed, setTyped] = useState("");
  const [onlyMissing, setOnlyMissing] = useState(false);
  const shown = filterFiles(files, typed, onlyMissing);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="relative min-w-48 flex-1">
          <Search aria-hidden className="pointer-events-none absolute left-2.5 top-2.5 size-3.5 text-muted-foreground" />
          <Input
            type="search"
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="Search the files"
            aria-label="Search the files"
            autoComplete="off"
            className="pl-8 [&::-webkit-search-cancel-button]:appearance-none"
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={onlyMissing} onChange={(event) => setOnlyMissing(event.target.checked)} />
          Only files that are not there
        </label>
      </div>
      <p role="status" className="text-xs text-muted-foreground">
        {shown.length === files.length ? `${files.length} files` : `${shown.length} of ${files.length} files`}
      </p>
      {shown.length === 0 ? (
        <p className="text-sm text-muted-foreground">No file has all of those words.</p>
      ) : (
        <ul aria-label="Files of the data lake" className="divide-y divide-border">
          {shown.map((file) => (
            <FileRow key={file.name} file={file} canFetch={fetching === undefined} actions={actions} />
          ))}
        </ul>
      )}
    </div>
  );
}

function Ready({ lake, jobs, actions }: { lake: DataLake; jobs: readonly Job[]; actions: SetupActions }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const fetching = activeJob(jobs, "data_lake");
  const missing = missingNames(lake.files);
  const commercial = missingNames(lake.files, true);
  // Fetching only the files for commercial use is a choice only when it leaves some out
  const plans: Plan[] = [
    ...(missing.length > 0 ? [{ button: `Fetch the ${fileCount(missing.length)} that ${missing.length === 1 ? "is" : "are"} not there`, names: missing }] : []),
    ...(commercial.length > 0 && commercial.length < missing.length
      ? [{ button: `Fetch only the ${commercial.length} for commercial use`, names: commercial }]
      : []),
  ];

  return (
    <>
      <Summary lake={lake.data_lake} />
      {fetching && (
        <div className="flex items-start gap-2 rounded-lg border border-border p-3">
          <div className="min-w-0 flex-1">
            <JobProgress job={fetching} />
          </div>
          <StopButton job={fetching} actions={actions} />
        </div>
      )}
      {!fetching && plan === null && (
        <div className="flex flex-wrap gap-2">
          {plans.map((choice, index) => (
            <Button
              key={choice.button}
              variant={index === 0 ? "default" : "outline"}
              size="sm"
              onClick={() => setPlan(choice)}
              disabled={actions.busy}
            >
              {choice.button}
            </Button>
          ))}
          {plans.length === 0 && <p className="text-sm text-muted-foreground">Every file is there.</p>}
        </div>
      )}
      {!fetching && plan !== null && <Confirm plan={plan} lake={lake.data_lake} actions={actions} onDone={() => setPlan(null)} />}
      <Files files={lake.files} fetching={fetching} actions={actions} />
    </>
  );
}

// What Biomni's data lake has, which of it is there, and the fetching of what is not
export function LakeTab({
  lake,
  jobs,
  actions,
  onRetry,
}: {
  lake: Loaded<DataLake>;
  jobs: readonly Job[];
  actions: SetupActions;
  onRetry: () => void;
}) {
  return (
    <Section>
      <p className="text-sm text-muted-foreground">
        Biomni&apos;s data lake is curated tables that some of its tools read, and that code in Docker can read in{" "}
        <code>/biomni_data/data_lake</code>. It is {formatBytes(DATA_LAKE_BYTES)} or so in all. The files are fetched from
        Biomni&apos;s release, and ones already there are left alone.
      </p>
      {lake.kind === "loading" && (
        <div className="flex flex-col gap-2" aria-busy="true" aria-label="Looking at the data lake">
          {[0, 1, 2, 3].map((row) => (
            <Skeleton key={row} className="h-10 w-full" />
          ))}
        </div>
      )}
      {lake.kind === "failed" && (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="text-sm text-destructive">
            The data lake could not be looked at. {describeError(lake.error)}
          </p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            Try again
          </Button>
        </div>
      )}
      {lake.kind === "ready" && <Ready lake={lake.value} jobs={jobs} actions={actions} />}
    </Section>
  );
}
