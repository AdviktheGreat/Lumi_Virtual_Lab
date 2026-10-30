"use client";

import { useState } from "react";
import { CircleAlert, CircleCheck, Clock, FileText, Loader2, Unplug } from "lucide-react";
import { CodeBlock } from "@/components/code";
import { useFileUrl } from "@/components/chat-files";
import { Button } from "@/components/ui/button";
import { formatDuration, stripAnsi } from "@/lib/format";
import type { Cell } from "@/lib/transcript";
import { cn } from "@/lib/utils";
import { ScrollBox } from "@/components/scroll-box";

// Lines of code shown before the rest is folded away
const CODE_LINES = 14;
// Figures and files that are shown before the rest are counted
const FILES_SHOWN = 12;

function Status({ status, duration }: { status: string; duration: number }) {
  const took = formatDuration(duration);
  switch (status) {
    case "ok":
      return (
        <span className="flex items-center gap-1.5 text-success">
          <CircleCheck className="size-3.5" aria-hidden />
          Ran{took && ` in ${took}`}
        </span>
      );
    case "error":
      return (
        <span className="flex items-center gap-1.5 text-destructive">
          <CircleAlert className="size-3.5" aria-hidden />
          Failed{took && ` after ${took}`}
        </span>
      );
    case "timeout":
      return (
        <span className="flex items-center gap-1.5 text-warning">
          <Clock className="size-3.5" aria-hidden />
          Stopped at its time limit{took && ` (${took})`}
        </span>
      );
    case "lost":
      return (
        <span className="flex items-center gap-1.5 text-warning">
          <Unplug className="size-3.5" aria-hidden />
          The session ended while it ran
        </span>
      );
    default:
      return <span>{status}</span>;
  }
}

function Plot({ path }: { path: string }) {
  const fileAddress = useFileUrl();
  const [failed, setFailed] = useState(false);
  const address = fileAddress(path);
  if (address === null || failed) {
    return <span className="text-xs italic text-muted-foreground">{path} is not available</span>;
  }

  return (
    <a href={address} target="_blank" rel="noopener noreferrer" className="block w-fit max-w-full overflow-hidden rounded-lg border border-border bg-white">
      {/* The file is the conversation's own, from the server's API, so there is nothing for next/image to optimize */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={address} alt={`Figure ${path}`} loading="lazy" onError={() => setFailed(true)} className="max-h-96 w-auto max-w-full" />
    </a>
  );
}

function Files({ paths }: { paths: string[] }) {
  const fileAddress = useFileUrl();
  const [all, setAll] = useState(false);
  const shown = all ? paths : paths.slice(0, FILES_SHOWN);

  return (
    <ul className="flex flex-wrap items-center gap-1.5" aria-label="Files it made">
      {shown.map((path) => {
        const address = fileAddress(path);
        const inside = (
          <>
            <FileText className="size-3 shrink-0 text-muted-foreground" aria-hidden />
            <span className="truncate">{path}</span>
          </>
        );
        const style = "flex max-w-xs items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs";

        return (
          <li key={path}>
            {address === null ? (
              <span className={style}>{inside}</span>
            ) : (
              <a href={address} target="_blank" rel="noopener noreferrer" className={`${style} hover:bg-muted`}>
                {inside}
              </a>
            )}
          </li>
        );
      })}
      {paths.length > shown.length && (
        <li>
          <Button type="button" variant="ghost" size="xs" onClick={() => setAll(true)}>
            {paths.length - shown.length} more
          </Button>
        </li>
      )}
    </ul>
  );
}

// Code that ran in the session, with what it printed, the figures it drew, and the files it made
export function CodeCell({ cell }: { cell: Cell }) {
  const output = stripAnsi(cell.output).replace(/\s+$/, "");
  const plots = cell.plots;
  const made = cell.producedFiles.filter((path) => !plots.includes(path));
  const value = cell.value === null || cell.value === undefined ? null : JSON.stringify(cell.value, null, 2);
  // A traceback is already in what the code printed, so the error is only said again where it is not
  const error = cell.error === null ? null : stripAnsi(cell.error).trim();
  const errorShown = error !== null && error !== "" && !output.includes(error);

  return (
    <div className="flex flex-col gap-2" data-testid="code-cell" data-status={cell.status}>
      <CodeBlock code={cell.code} language={cell.language} foldAfter={CODE_LINES} />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-0.5 text-xs text-muted-foreground">
        <Status status={cell.status} duration={cell.duration} />
      </div>
      {output !== "" && (
        <ScrollBox
          as="pre"
          role="group"
          aria-label="Output"
          className={cn(
            "max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-code px-3 py-2.5 font-mono text-[13px] leading-5",
          )}
          data-testid="code-output"
        >
          {cell.outputDropped > 0 && (
            <span className="mb-1 block text-xs italic text-muted-foreground">
              The middle of the output, {cell.outputDropped.toLocaleString("en")} bytes, is left out.
            </span>
          )}
          {output}
        </ScrollBox>
      )}
      {errorShown && (
        <p role="alert" className="whitespace-pre-wrap break-words rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 font-mono text-[13px] text-destructive">
          {error}
        </p>
      )}
      {value !== null && (
        <ScrollBox
          as="pre"
          role="group"
          className="max-h-48 overflow-auto rounded-lg border border-border bg-code px-3 py-2 font-mono text-[13px]"
          aria-label="Value"
        >
          {value}
        </ScrollBox>
      )}
      {plots.length > 0 && (
        <div role="group" className="grid gap-2 sm:grid-cols-2" aria-label="Figures">
          {plots.map((path) => (
            <Plot key={path} path={path} />
          ))}
        </div>
      )}
      {made.length > 0 && <Files paths={made} />}
    </div>
  );
}

// Code the lead has written that has not yet run, or has not said how it did
export function PendingCell({ code, language, running }: { code: string; language: string; running: boolean }) {
  return (
    <div className="flex flex-col gap-2" data-testid="code-cell" data-status={running ? "running" : "unknown"}>
      <CodeBlock code={code} language={language} foldAfter={CODE_LINES} />
      {running && (
        <div className="flex items-center gap-1.5 px-0.5 text-xs text-muted-foreground" role="status">
          <Loader2 className="size-3.5 animate-spin" aria-hidden />
          Running…
        </div>
      )}
    </div>
  );
}
