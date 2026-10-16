"use client";

import { Download } from "lucide-react";
import { ProblemNotice } from "@/components/messages";
import { useServer } from "@/components/server-provider";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { BenchmarksList } from "@/lib/types";
import { useAttempt } from "@/lib/use-looked";

// The files the benchmarks' questions are in, which are about 4 MB, and are fetched once. A run cannot be made until they
// are there.
export function FilesCard({ list, onChanged }: { list: BenchmarksList; onChanged: (list: BenchmarksList) => void }) {
  const { report } = useServer();
  const attempt = useAttempt(report);
  const { files } = list;

  async function fetchFiles() {
    const next = await attempt.run(() => api.fetchBenchmarkFiles());
    if (next) onChanged(next);
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-3">
      {files.ready ? (
        <p className="text-sm break-words">The files of the benchmarks are in {files.directory}.</p>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {files.missing.length > 0
              ? "The questions of the benchmarks are in files that are fetched once, and are about 4 MB. They are checked against the files that Biomni's scores were made on, so that the scores can be compared."
              : "The benchmarks' files are there, but cannot be read."}
          </p>
          {files.problem && (
            <p role="alert" className="break-words text-sm text-destructive">
              {files.problem}
            </p>
          )}
          {files.missing.length > 0 && (
            <>
              <p className="break-words text-xs text-muted-foreground">Not there yet: {files.missing.join(", ")}</p>
              <div>
                <Button onClick={() => void fetchFiles()} disabled={attempt.busy}>
                  <Download />
                  {attempt.busy ? "Fetching…" : "Fetch the files"}
                </Button>
              </div>
            </>
          )}
        </>
      )}
      {attempt.problem && <ProblemNotice problem={attempt.problem} />}
    </div>
  );
}
