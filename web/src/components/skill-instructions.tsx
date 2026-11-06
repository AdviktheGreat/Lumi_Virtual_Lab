"use client";

import { useEffect, useState } from "react";
import { useServer } from "@/components/server-provider";
import { describeError } from "@/lib/errors";
import type { SkillPreview } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

// What a skill tells the lead, and the files that come with it, which are read before a skill is trusted. `load` must be
// the same function on every render.
export function Instructions({
  name,
  load,
}: {
  name: string;
  load: (name: string, signal?: AbortSignal) => Promise<SkillPreview>;
}) {
  const { report } = useServer();
  const [preview, setPreview] = useState<Loaded<SkillPreview>>({ kind: "loading" });

  useEffect(() => {
    const abort = new AbortController();
    load(name, abort.signal).then(
      (value) => setPreview({ kind: "ready", value }),
      (error: unknown) => {
        if (abort.signal.aborted) return;
        report(error);
        setPreview({ kind: "failed", error });
      },
    );

    return () => abort.abort();
  }, [name, load, report]);

  if (preview.kind === "loading") {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        Reading {name}…
      </p>
    );
  }
  if (preview.kind === "failed") {
    return (
      <p role="alert" className="text-xs text-destructive">
        {describeError(preview.error)}
      </p>
    );
  }

  const { instructions, characters, files, more_files: more } = preview.value;

  return (
    <div className="flex flex-col gap-2">
      <div
        role="region"
        aria-label={`What ${name} tells the lead`}
        tabIndex={0}
        className="max-h-72 overflow-auto rounded-md bg-muted/60 p-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-5">{instructions}</pre>
      </div>
      {instructions.length < characters && (
        <p className="text-xs text-muted-foreground">
          Only the first {instructions.length.toLocaleString()} of its {characters.toLocaleString()} characters are shown.
        </p>
      )}
      {files.length > 0 && (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium">Files that come with it</p>
          <ul aria-label={`Files of ${name}`} className="grid gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2">
            {files.map((file) => (
              <li key={file} className="min-w-0 truncate" title={file}>
                <code>{file}</code>
              </li>
            ))}
          </ul>
          {more > 0 && <p className="text-xs text-muted-foreground">And {more} more.</p>}
        </div>
      )}
    </div>
  );
}
