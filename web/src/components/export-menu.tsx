"use client";

import { BookOpen, FileCode, FileDown, FileText, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { EXPORT_CHOICES, type ExportFormat } from "@/lib/export";
import type { Exporter } from "@/lib/use-export";

const ICONS = { html: FileCode, pdf: FileText, ipynb: BookOpen } satisfies Record<ExportFormat, typeof FileText>;

// What saves the conversation as a document: a web page, a PDF, or a notebook
export function ExportMenu({
  exporter: { saving, save },
  disabled,
}: {
  exporter: Exporter;
  // Whether there is nothing to save yet
  disabled: boolean;
}) {
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
