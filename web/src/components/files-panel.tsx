"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Download, ExternalLink, File as FileIcon, FileImage, FileSpreadsheet, FileText, FolderOpen, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { describeError } from "@/lib/errors";
import { readTable } from "@/lib/csv";
import { baseName, dividerOf, fileUrl, folderOf, formatBytes, inFolders, matching, opensInPage, previewOf } from "@/lib/files";
import { timeAgoFromEpoch } from "@/lib/format";
import type { ChatFile } from "@/lib/types";
import { PREVIEW_BYTES, useFileText, type Listed } from "@/lib/use-files";

function KindIcon({ file, className }: { file: ChatFile; className?: string }) {
  switch (previewOf(file)) {
    case "image":
      return <FileImage className={className} aria-hidden />;
    case "table":
      return <FileSpreadsheet className={className} aria-hidden />;
    case "text":
      return <FileText className={className} aria-hidden />;
    case "none":
      return <FileIcon className={className} aria-hidden />;
  }
}

// What opens the panel, and says how many files there are once it is known
export function FilesButton({ count, open, onToggle }: { count: number | null; open: boolean; onToggle: () => void }) {
  return (
    <Button type="button" variant={open ? "secondary" : "ghost"} size="sm" onClick={onToggle} aria-pressed={open} data-testid="files-toggle">
      <FolderOpen aria-hidden />
      Files
      {count !== null && count > 0 && (
        <span className="rounded-full bg-muted px-1.5 text-xs tabular-nums text-muted-foreground" data-testid="files-count">
          {count}
        </span>
      )}
    </Button>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">{children}</p>;
}

function Problem({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
      {children}
    </p>
  );
}

function SaveIt({ id, file }: { id: string; file: ChatFile }) {
  return (
    <Button asChild variant="outline" size="sm" className="w-fit">
      <a href={fileUrl(id, file.path, true)} download={baseName(file.path)}>
        <Download aria-hidden />
        Download
      </a>
    </Button>
  );
}

function Picture({ id, file }: { id: string; file: ChatFile }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <Problem>The picture could not be shown.</Problem>;

  return (
    // The file is the conversation's own, from the server's API, so there is nothing for next/image to optimize
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`${fileUrl(id, file.path)}?v=${file.modified}-${file.size}`}
      alt={baseName(file.path)}
      onError={() => setFailed(true)}
      className="max-h-full max-w-full rounded-lg border border-border bg-white object-contain"
      data-testid="file-picture"
    />
  );
}

function Table({ text, file, truncated }: { text: string; file: ChatFile; truncated: boolean }) {
  const table = readTable(text, dividerOf(file), truncated);
  if (table.header.length === 0) return <Notice>There is no table to show in what could be read. It can be downloaded.</Notice>;

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-auto rounded-lg border border-border">
        <table className="w-full border-collapse text-xs" data-testid="file-table">
          <thead className="sticky top-0 bg-muted">
            <tr>
              {table.header.map((cell, at) => (
                <th key={at} className="whitespace-nowrap border-b border-border px-2.5 py-1.5 text-left font-medium">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, at) => (
              <tr key={at} className="odd:bg-muted/30">
                {row.map((cell, place) => (
                  <td key={place} className="max-w-48 truncate whitespace-nowrap border-b border-border/60 px-2.5 py-1" title={cell}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.cut && <p className="text-xs text-muted-foreground">Only the start of the table is shown. Download the file to see all of it.</p>}
    </div>
  );
}

function TextPreview({ id, file }: { id: string; file: ChatFile }) {
  const reading = useFileText(id, file);
  const shown = previewOf(file);

  if (reading.kind === "loading") {
    return (
      <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading the file">
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-3/5" />
        <Skeleton className="h-4 w-2/3" />
      </div>
    );
  }
  if (reading.kind === "failed") return <Problem>{describeError(reading.error)}</Problem>;
  if (reading.file.binary) {
    return (
      <div className="flex flex-col gap-3">
        <Notice>This file is not text, so it cannot be shown here.</Notice>
        <SaveIt id={id} file={file} />
      </div>
    );
  }
  if (reading.file.text === "") return <Notice>This file is empty.</Notice>;
  if (shown === "table") return <Table text={reading.file.text} file={file} truncated={reading.file.truncated} />;

  return (
    <div className="flex flex-col gap-2">
      <pre
        className="overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border bg-muted/40 px-3 py-2 font-mono text-xs leading-5"
        data-testid="file-text"
      >
        {reading.file.text}
      </pre>
      {reading.file.truncated && (
        <p className="text-xs text-muted-foreground">
          Only the first {formatBytes(PREVIEW_BYTES)} are shown. Download the file to see all of it.
        </p>
      )}
    </div>
  );
}

// What is in a file, as far as it can be shown in the page
function Preview({ id, file }: { id: string; file: ChatFile }) {
  switch (previewOf(file)) {
    case "image":
      // A picture that was made again under the same name is fetched and tried again
      return <Picture key={`${file.path}\n${file.size}\n${file.modified}`} id={id} file={file} />;
    case "table":
    case "text":
      return <TextPreview id={id} file={file} />;
    case "none":
      return (
        <div className="flex flex-col gap-3">
          <Notice>This kind of file cannot be shown here.</Notice>
          <SaveIt id={id} file={file} />
        </div>
      );
  }
}

function Detail({ id, file, onBack }: { id: string; file: ChatFile; onBack: () => void }) {
  const folder = folderOf(file.path);
  const changed = timeAgoFromEpoch(file.modified);

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="file-detail" data-path={file.path}>
      <div className="flex items-center gap-1.5 border-b border-border px-2 py-2">
        <Button type="button" variant="ghost" size="icon-sm" aria-label="Back to the files" onClick={onBack}>
          <ArrowLeft />
        </Button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium" title={file.path}>
            {baseName(file.path)}
          </div>
          <div className="truncate text-xs text-muted-foreground">{[folder, formatBytes(file.size), changed].filter(Boolean).join(" · ")}</div>
        </div>
        <Button asChild variant="ghost" size="icon-sm">
          <a href={fileUrl(id, file.path, true)} download={baseName(file.path)} aria-label="Download">
            <Download />
          </a>
        </Button>
        {opensInPage(file) && (
          <Button asChild variant="ghost" size="icon-sm">
            <a href={fileUrl(id, file.path)} target="_blank" rel="noopener noreferrer" aria-label="Open in a new tab">
              <ExternalLink />
            </a>
          </Button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <Preview id={id} file={file} />
      </div>
    </div>
  );
}

function List({ files, truncated, onOpen }: { files: ChatFile[]; truncated: boolean; onOpen: (path: string) => void }) {
  const [typed, setTyped] = useState("");
  const found = matching(files, typed);
  const folders = inFolders(found);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {files.length > 6 && (
        <div className="px-3 pt-3">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              type="search"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              placeholder="Find a file"
              aria-label="Find a file"
              className="h-8 w-full rounded-lg border border-input bg-transparent pl-8 pr-2.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            />
          </div>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto px-2 py-2" data-testid="file-list">
        {found.length === 0 && typed.trim() !== "" && <p className="px-2 py-3 text-sm text-muted-foreground">No file has that in its name.</p>}
        {folders.map((folder) => (
          <section key={folder.name} aria-label={folder.name === "" ? "Top level" : folder.name} className="pb-2">
            {(folders.length > 1 || folder.name !== "") && (
              <h3 className="truncate px-2 pb-1 pt-2 text-xs font-medium text-muted-foreground" title={folder.name}>
                {folder.name === "" ? "Top level" : folder.name}
              </h3>
            )}
            <ul>
              {folder.files.map((file) => (
                <li key={file.path}>
                  <button
                    type="button"
                    onClick={() => onOpen(file.path)}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                    data-testid="file-row"
                    data-path={file.path}
                  >
                    <KindIcon file={file} className="size-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate" title={file.path}>
                      {baseName(file.path)}
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{formatBytes(file.size)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))}
        {truncated && (
          <p className="px-2 py-2 text-xs text-muted-foreground">There are more files than are listed here, which is the first {files.length.toLocaleString("en")}.</p>
        )}
      </div>
    </div>
  );
}

// What the conversation was given and what its code made. It is a column beside the conversation where there is room, and
// over it where there is not.
export function FilesPanel({ id, listed, onClose }: { id: string; listed: Listed; onClose: () => void }) {
  const [chosen, setChosen] = useState<string | null>(null);
  const file = chosen === null ? undefined : listed.files.find((candidate) => candidate.path === chosen);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", close);

    return () => document.removeEventListener("keydown", close);
  }, [onClose]);

  return (
    <>
      <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={onClose} aria-hidden />
      <aside
        aria-label="Files"
        data-testid="files-panel"
        className="fixed inset-y-0 right-0 z-40 flex w-[min(24rem,100vw)] flex-col border-l border-border bg-background shadow-xl lg:static lg:z-auto lg:w-96 lg:shrink-0 lg:shadow-none"
      >
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
          <h2 className="flex-1 text-sm font-medium">Files</h2>
          <Button type="button" variant="ghost" size="icon-sm" aria-label="Close the files" onClick={onClose}>
            <X />
          </Button>
        </div>
        {listed.error !== null && !listed.loaded && (
          <div className="p-3">
            <Problem>{describeError(listed.error)}</Problem>
          </div>
        )}
        {!listed.loaded && listed.error === null && (
          <div className="flex flex-col gap-2 p-3" aria-busy="true" aria-label="Loading the files">
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-7 w-full" />
            <Skeleton className="h-7 w-4/5" />
          </div>
        )}
        {listed.loaded && file !== undefined && <Detail id={id} file={file} onBack={() => setChosen(null)} />}
        {listed.loaded && file === undefined && listed.files.length === 0 && (
          <div className="p-4 text-sm text-muted-foreground" data-testid="files-empty">
            <p className="font-medium text-foreground">No files yet</p>
            <p className="mt-1">The files you attach to a message, and the ones that code makes, are listed here.</p>
          </div>
        )}
        {listed.loaded && file === undefined && listed.files.length > 0 && (
          <List files={listed.files} truncated={listed.truncated} onOpen={setChosen} />
        )}
        {listed.loaded && listed.error !== null && (
          <div className="border-t border-border p-3">
            <Problem>The list could not be brought up to date. {describeError(listed.error)}</Problem>
          </div>
        )}
      </aside>
    </>
  );
}
