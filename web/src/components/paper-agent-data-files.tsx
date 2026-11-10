"use client";

import { useId, useState } from "react";
import { Download, ExternalLink, Trash2 } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Aside, describedBy, Field } from "@/components/settings-fields";
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
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { api, ApiError } from "@/lib/api";
import { formatBytes } from "@/lib/files";
import { timeAgo } from "@/lib/format";
import {
  checkedBy,
  checkDataFetch,
  describeChecksum,
  describeKept,
  describeKeptCheck,
  describeDataLicense,
  emptyDataFetch,
  fetchable,
  keptNames,
  shortDigest,
  totalBytes,
  whyNot,
  type DataFetchDraft,
} from "@/lib/paperagent-data";
import { isLink } from "@/lib/paperagents";
import { count } from "@/lib/checks";
import type { DataListing, KeptDataSource, PaperAgent, PaperAgentData } from "@/lib/types";
import type { JobsData } from "@/lib/use-jobs";
import { useAttempt } from "@/lib/use-looked";
import { cn } from "@/lib/utils";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// A page where a place is shown, as a link to it if it can be one
function Place({ label, url }: { label: string; url: string | null }) {
  if (url === null || !isLink(url)) return <span className="break-words">{label}</span>;

  return (
    <a href={url} target="_blank" rel="noreferrer noopener" className={cn("inline-flex min-w-0 items-center gap-1 break-words", LINK)}>
      {label}
      <ExternalLink className="size-3 shrink-0" aria-hidden />
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

interface FilesProps {
  agent: PaperAgent;
  data: PaperAgentData;
  listing: DataListing;
  // Whether anything is being done to the agent, which fetching waits for
  busy: boolean;
  jobs: JobsData;
  // Asks the place what it has again, as is done when what it has is not what the person was shown
  onRelist: () => void;
}

// What a place has, with the way to choose files of it, to see what they come to, and to agree to fetching them. Nothing is
// fetched until the person has done all three.
export function Files({ agent, data, listing, busy, jobs, onRelist }: FilesProps) {
  const { report } = useServer();
  const id = useId();
  const attempt = useAttempt(report);
  const [chosen, setChosen] = useState<ReadonlySet<string>>(new Set());
  const [draft, setDraft] = useState<DataFetchDraft>(() => emptyDataFetch(data.limits));
  const [tried, setTried] = useState(false);
  const [asking, setAsking] = useState(false);
  const kept = keptNames(data, listing.key);
  const info = data.sources.find((source) => source.source === listing.source);
  // What was chosen of what the place has, which leaves out a file that it no longer lists, or that is kept since
  const picked = listing.files.filter((file) => chosen.has(file.name) && fetchable(file, kept));
  const checked = checkDataFetch(listing.url, picked, draft, data.limits);
  const problems = tried ? checked.problems : {};
  const total = totalBytes(picked);
  const available = listing.files.filter((file) => fetchable(file, kept));
  const by = checkedBy(picked);

  function toggle(name: string, on: boolean) {
    const next = new Set(chosen);
    if (on) next.add(name);
    else next.delete(name);
    setChosen(next);
  }

  async function fetchFiles() {
    setAsking(false);
    const options = checked.value;
    if (options === null) return;
    const job = await attempt.run(async () => {
      try {
        return await api.fetchPaperAgentData(agent.id, options);
      } catch (error) {
        // What the place has is not what was shown, or a file is kept that was not: what is shown is out of date, so it is
        // asked for again, and what was chosen is not what is agreed to
        if (error instanceof ApiError && (error.code === "changed" || error.code === "kept")) {
          setChosen(new Set());
          setTried(false);
          onRelist();
        }
        throw error;
      }
    });
    if (job) {
      jobs.track(job);
      setChosen(new Set());
      setTried(false);
    }
  }

  return (
    <section aria-label={`Files of ${listing.label}`} className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="data-files">
      <div className="flex flex-col gap-1">
        <h3 className="break-words text-sm font-medium">
          <Place label={listing.label} url={listing.url} />
        </h3>
        {listing.title !== listing.label && <p className="break-words text-sm">{listing.title}</p>}
        <p className="text-xs text-muted-foreground" data-testid="data-license">
          {describeDataLicense(listing.license)}. {listing.total_files.toLocaleString("en-US")} {listing.total_files === 1 ? "file" : "files"} in all
          {listing.truncated ? `, of which the first ${listing.files.length.toLocaleString("en-US")} are listed` : ""}.
        </p>
        {info && info.note !== "" && <p className="break-words text-xs text-muted-foreground">{info.note}</p>}
      </div>
      {!listing.downloads && (
        <Aside tone="warning">
          {listing.label} gives its files only to someone who has an account, so they are not fetched here. Get them in a browser and add
          them on the Data page.
        </Aside>
      )}
      {listing.notes.map((note) => (
        <p key={note} className="break-words text-xs text-muted-foreground">
          {note}
        </p>
      ))}
      {listing.files.length === 0 ? (
        <p className="text-sm text-muted-foreground">It lists no files.</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="xs"
              disabled={available.length === 0 || busy}
              onClick={() => setChosen(new Set(available.map((file) => file.name)))}
            >
              Choose all that can be fetched
            </Button>
            <Button type="button" variant="outline" size="xs" disabled={chosen.size === 0} onClick={() => setChosen(new Set())}>
              Choose none
            </Button>
          </div>
          <ul aria-label={`Files of ${listing.label}`} className="flex max-h-96 flex-col gap-1.5 overflow-auto pr-1">
            {listing.files.map((file, place) => {
              const reason = whyNot(file, kept);
              const inputId = `${id}-file-${place}`;

              return (
                <li key={file.name} className="flex items-start gap-2 rounded-md border border-border px-2.5 py-1.5" data-testid="data-file" data-name={file.name}>
                  <Checkbox
                    id={inputId}
                    className="mt-0.5"
                    checked={picked.some((item) => item.name === file.name)}
                    disabled={reason !== null || busy}
                    onChange={(event) => toggle(file.name, event.target.checked)}
                    aria-describedby={`${inputId}-about`}
                  />
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <label htmlFor={inputId} className="break-all text-sm">
                      {file.name}
                    </label>
                    <p id={`${inputId}-about`} className="break-words text-xs text-muted-foreground">
                      {file.bytes === null ? "Size not given" : formatBytes(file.bytes)}
                      {" · "}
                      {describeChecksum(file)}
                      {reason !== null && (
                        <>
                          {" · "}
                          <span className="text-foreground">{reason}</span>
                        </>
                      )}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
          <form
            aria-label="Fetch the files that are chosen"
            onSubmit={(event) => {
              event.preventDefault();
              setTried(true);
              if (checked.value !== null) setAsking(true);
            }}
            className="flex flex-col gap-3 border-t border-border pt-3"
          >
            <p role="status" className="text-sm" data-testid="data-chosen">
              {picked.length === 0 ? "No files are chosen." : `${count(picked.length, "file")} chosen, ${formatBytes(total)} in all.`}
            </p>
            {problems.files && (
              <p role="alert" className="text-xs text-destructive">
                {problems.files}
              </p>
            )}
            <Field
              id={`${id}-megabytes`}
              label="Most to fetch, in megabytes"
              hint={`Nothing more than this is fetched. At most ${data.limits.max_megabytes.toLocaleString("en-US")}.`}
              problem={problems.megabytes}
              className="max-w-xs"
            >
              <Input
                id={`${id}-megabytes`}
                value={draft.megabytes}
                onChange={(event) => setDraft({ ...draft, megabytes: event.target.value })}
                inputMode="numeric"
                autoComplete="off"
                aria-invalid={problems.megabytes !== undefined}
                aria-describedby={describedBy(`${id}-megabytes`, { hint: true, problem: problems.megabytes !== undefined })}
              />
            </Field>
            {attempt.problem && <ProblemNotice problem={attempt.problem} />}
            <div>
              <Button type="submit" disabled={busy || attempt.busy || !listing.downloads}>
                <Download />
                {attempt.busy ? "Starting…" : busy ? "Waiting…" : "Fetch the files that are chosen"}
              </Button>
            </div>
          </form>
        </>
      )}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Fetch {count(picked.length, "file")}, {formatBytes(total)}, from {listing.label}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              They are fetched from {info ? info.hosts.join(", ") : listing.source} and kept under data/{listing.source}/ in this agent&apos;s
              folder. {by.checksum > 0 && `${count(by.checksum, "file")} will be checked by the checksum that the place gives. `}
              {by.size > 0 && `${count(by.size, "file")} will be checked by their size only, since the place gives no checksum. `}
              A file that does not match is thrown away, and fetching stops at {Number(draft.megabytes).toLocaleString("en-US")} MB.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Do not fetch</AlertDialogCancel>
            <AlertDialogAction onClick={() => void fetchFiles()}>Fetch</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}

// Takes away the files of one place, or of every place, after asking
function TakeAway({
  agent,
  data,
  source,
  busy,
  onData,
}: {
  agent: PaperAgent;
  data: PaperAgentData;
  // The place whose files they are, or none for all of them
  source?: KeptDataSource;
  busy: boolean;
  onData: (data: PaperAgentData) => void;
}) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const [asking, setAsking] = useState(false);
  const label = source ? `Take away the files from ${source.label}` : "Take away every file";
  const files = source ? source.files.length : data.kept.files;

  async function clear() {
    setAsking(false);
    const next = await attempt.run(() => api.clearPaperAgentData(agent.id, source?.key));
    if (next) onData(next);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div>
        <Button variant="outline" size="xs" onClick={() => setAsking(true)} disabled={busy || attempt.busy} aria-label={label}>
          <Trash2 />
          {source ? "Take away" : "Take away all"}
        </Button>
      </div>
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {source ? `Take away the files from ${source.label}?` : `Take away every file of ${agent.title}?`}
            </AlertDialogTitle>
            <AlertDialogDescription>
              This deletes {count(files, "file")} from this agent&apos;s folder, with what was recorded of them. Your own data, and what stands
              in for a dataset, are not touched. They can be fetched again.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => void clear()}>
              Take away
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

// What was fetched of one place, with where it came from, and how far each file was checked
function KeptSource({
  agent,
  data,
  source,
  busy,
  onData,
}: {
  agent: PaperAgent;
  data: PaperAgentData;
  source: KeptDataSource;
  busy: boolean;
  onData: (data: PaperAgentData) => void;
}) {
  const bytes = source.files.reduce((sum, file) => sum + file.bytes, 0);

  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="data-kept-source" data-key={source.key}>
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="min-w-0 break-words text-sm font-medium">
          <Place label={source.label} url={source.url} />
        </h4>
        <Badge variant="outline">{describeKept({ files: source.files.length, bytes })}</Badge>
      </div>
      {source.title !== source.label && <p className="break-words text-sm">{source.title}</p>}
      <p className="text-xs text-muted-foreground">
        {describeDataLicense(source.license)}. Kept in data/{source.folder}/.
      </p>
      <ul aria-label={`Files kept from ${source.label}`} className="flex flex-col gap-1.5">
        {source.files.map((file) => (
          <li key={file.name} className="flex flex-col gap-0.5 rounded-md bg-muted/40 px-2.5 py-1.5" data-testid="data-kept-file">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <code className="min-w-0 break-all text-sm">{file.name}</code>
              <span className="text-xs text-muted-foreground">{formatBytes(file.bytes)}</span>
              {!file.present && <Badge variant="destructive">Not on disk</Badge>}
            </div>
            <p className="break-words text-xs text-muted-foreground">
              {describeKeptCheck(file)}. SHA-256 <code className="font-mono">{shortDigest(file.sha256)}…</code>. Fetched{" "}
              {timeAgo(file.fetched_at) || "a while ago"}.
            </p>
          </li>
        ))}
      </ul>
      <TakeAway agent={agent} data={data} source={source} busy={busy} onData={onData} />
    </li>
  );
}

// What has been fetched, by place, with how big it all is, and the way to take it away
export function KeptData({
  agent,
  data,
  busy,
  onData,
}: {
  agent: PaperAgent;
  data: PaperAgentData;
  busy: boolean;
  onData: (data: PaperAgentData) => void;
}) {
  const id = useId();
  if (data.kept.sources.length === 0) {
    return <p className="text-sm text-muted-foreground">No data has been fetched for this agent.</p>;
  }

  return (
    <section aria-labelledby={id} className="flex flex-col gap-2" data-testid="data-kept">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={id} className="text-sm font-medium">
          What was fetched
        </h3>
        <Badge variant="secondary" data-testid="data-kept-total">
          {describeKept(data.kept)}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        Each file was kept only if it is as big as the place said it was, and, where the place gave a checksum, if it matches. That is
        all that is checked: it says the file is what the place has, and not that the data is what the paper used.
      </p>
      <ul aria-label="Where data was fetched from" className="flex flex-col gap-2">
        {data.kept.sources.map((source) => (
          <KeptSource key={source.key} agent={agent} data={data} source={source} busy={busy} onData={onData} />
        ))}
      </ul>
      {data.kept.sources.length > 1 && <TakeAway agent={agent} data={data} busy={busy} onData={onData} />}
    </section>
  );
}
