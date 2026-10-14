"use client";

import { useEffect, useRef, useState } from "react";
import { FileCode, FileDown, FileText, Loader2 } from "lucide-react";
import { useServer } from "@/components/server-provider";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import { problemOf, type Problem } from "@/lib/errors";
import { EXPORT_CHOICES, saveFile, type ExportFormat } from "@/lib/export";

const ICONS = { html: FileCode, pdf: FileText } satisfies Record<ExportFormat, typeof FileText>;

// What saves the conversation as a document: a web page, or a PDF. The document is made by the server, which can fail to
// make a PDF, so what it says is given to onProblem, to be shown where the page shows what went wrong.
export function ExportMenu({
  id,
  disabled,
  onProblem,
}: {
  id: string;
  // Whether there is nothing to save yet
  disabled: boolean;
  onProblem: (problem: Problem | null) => void;
}) {
  const { report } = useServer();
  const [saving, setSaving] = useState<ExportFormat | null>(null);
  const running = useRef<AbortController | null>(null);

  // A document that is still being made when the conversation is left is not saved, which would be a surprise
  useEffect(() => () => running.current?.abort(), []);

  async function save(format: ExportFormat) {
    // Only one at a time: the server does the work, and a second would be a second file
    if (running.current) return;
    const controller = new AbortController();
    running.current = controller;
    setSaving(format);
    onProblem(null);
    try {
      const { file, name } = await api.exportChat(id, format, controller.signal);
      saveFile(file, name);
    } catch (error) {
      // A request given up because the conversation was left did not fail, so there is nothing to tell of
      if (!controller.signal.aborted) {
        report(error);
        onProblem(problemOf(error));
      }
    } finally {
      running.current = null;
      setSaving(null);
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          aria-busy={saving !== null}
          title={disabled ? "There is nothing to save yet" : "Save this conversation as a document"}
          data-testid="export-toggle"
        >
          {saving === null ? <FileDown aria-hidden /> : <Loader2 className="animate-spin motion-reduce:animate-none" aria-hidden />}
          <span className="max-sm:sr-only">{saving === null ? "Save" : "Saving…"}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        {EXPORT_CHOICES.map(({ format, label, hint }) => {
          const Icon = ICONS[format];

          return (
            <DropdownMenuItem key={format} disabled={saving !== null} onSelect={() => void save(format)} data-testid={`export-${format}`}>
              <Icon aria-hidden />
              <span className="flex flex-col">
                <span>{label}</span>
                <span className="text-xs text-muted-foreground">{hint}</span>
              </span>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
