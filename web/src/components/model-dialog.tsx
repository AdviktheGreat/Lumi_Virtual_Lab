"use client";

import { useEffect, useMemo, useState } from "react";
import { Check, ChevronDown, Loader2, Search } from "lucide-react";
import { Notice } from "@/components/messages";
import { useSettings } from "@/components/settings-provider";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { problemOf, type Problem } from "@/lib/errors";
import { grouped, matching, rowsOf, typedModel, type ModelRow } from "@/lib/models";
import type { Loaded } from "@/lib/use-settings-data";
import type { Models, OpenRouterList } from "@/lib/types";
import { cn } from "@/lib/utils";

function Row({ row, current, disabled, onChoose }: { row: ModelRow; current: boolean; disabled: boolean; onChoose: () => void }) {
  const details = [row.name, row.price, row.context].filter(Boolean).join(" · ");

  return (
    <button
      type="button"
      role="option"
      aria-selected={current}
      disabled={disabled}
      data-testid="model-option"
      data-model={row.id}
      onClick={onChoose}
      className={cn(
        "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-none transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
        current && "bg-accent/60",
      )}
    >
      <Check className={cn("mt-0.5 size-4 shrink-0 text-brand", !current && "invisible")} aria-hidden />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="break-all font-medium">{row.id}</span>
        {details && <span className="text-xs text-muted-foreground">{details}</span>}
      </span>
      {!row.ready && <span className="shrink-0 text-xs text-muted-foreground">needs a key</span>}
    </button>
  );
}

// What shows the model in use, beside the composer, and opens the choice of another
export function ModelButton({
  model,
  prefix,
  disabled = false,
  onClick,
}: {
  model: string;
  // What goes before the model, as the name of the one who answers
  prefix?: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-testid="model-button"
      disabled={disabled}
      onClick={onClick}
      title={disabled ? "The model can be changed when the lead has finished" : "Change the model"}
      className="-mx-1 inline-flex max-w-full items-center gap-1 rounded px-1 py-0.5 outline-none transition-colors enabled:hover:bg-accent enabled:hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="truncate">{prefix ? `${prefix} · ${model}` : model}</span>
      {!disabled && <ChevronDown className="size-3 shrink-0" aria-hidden />}
    </button>
  );
}

// Where a model is chosen from every one that can be reached: those of each provider, and all of OpenRouter's, which are
// searched, as they are many. What is typed that is not in the list can be used as it is typed. Choosing one gives its name to
// onChoose, which may refuse it by throwing, and whose refusal is shown here, and which closes the dialog when it is done.
export function ModelDialog({
  title,
  description,
  current,
  onChoose,
  onClose,
}: {
  title: string;
  description: string;
  // The model in use, which is marked
  current: string;
  onChoose: (model: string) => Promise<void>;
  onClose: () => void;
}) {
  const settings = useSettings();
  const [models, setModels] = useState<Loaded<Models>>({ kind: "loading" });
  const [openrouter, setOpenrouter] = useState<Loaded<OpenRouterList>>({ kind: "loading" });
  const [query, setQuery] = useState("");
  const [choosing, setChoosing] = useState<string | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    api.models(abort.signal).then(
      (value) => {
        if (!abort.signal.aborted) setModels({ kind: "ready", value });
      },
      (error: unknown) => {
        if (!abort.signal.aborted) setModels({ kind: "failed", error });
      },
    );
    api.openRouterModels(abort.signal).then(
      (value) => {
        if (!abort.signal.aborted) setOpenrouter({ kind: "ready", value });
      },
      (error: unknown) => {
        if (!abort.signal.aborted) setOpenrouter({ kind: "failed", error });
      },
    );

    return () => abort.abort();
  }, []);

  const rows = useMemo(
    () => rowsOf(models.kind === "ready" ? models.value : null, openrouter.kind === "ready" ? openrouter.value : null),
    [models, openrouter],
  );
  const shown = useMemo(() => matching(rows, query), [rows, query]);
  const typed = typedModel(rows, query);
  const busy = choosing !== null;
  const trouble = openrouter.kind === "ready" ? openrouter.value.problem : null;

  async function choose(model: string) {
    if (busy) return;
    setChoosing(model);
    setProblem(null);
    try {
      await onChoose(model);
    } catch (error) {
      setProblem(problemOf(error));
    } finally {
      setChoosing(null);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="sm:max-w-lg" data-testid="model-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              // Enter takes what is first, or what is typed where nothing in the list is like it
              if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
              event.preventDefault();
              const first = shown[0];
              if (first !== undefined) void choose(first.id);
              else if (typed !== null) void choose(typed);
            }}
            aria-label="Search the models"
            placeholder="Search, or type a model's name"
            autoComplete="off"
            spellCheck={false}
            autoFocus
            className="pl-8"
          />
        </div>

        {problem && (
          <Notice
            tone="error"
            action={
              problem.fix === "keys" ? (
                <Button
                  variant="outline"
                  size="xs"
                  onClick={() => {
                    onClose();
                    settings.open("keys");
                  }}
                  className="shrink-0 text-foreground"
                >
                  Add the key
                </Button>
              ) : undefined
            }
          >
            {problem.text}
          </Notice>
        )}

        <div
          role="listbox"
          aria-label="Models"
          aria-busy={models.kind === "loading" || openrouter.kind === "loading"}
          className="-mx-1 flex max-h-80 min-h-24 flex-col gap-2 overflow-y-auto px-1"
        >
          {grouped(shown).map(([provider, group]) => (
            <div key={provider} role="group" aria-label={provider} className="flex flex-col">
              <div className="sticky top-0 z-10 bg-popover px-2 py-1 text-xs font-medium text-muted-foreground">{provider}</div>
              {group.map((row) => (
                <Row key={row.id} row={row} current={row.id === current} disabled={busy} onChoose={() => void choose(row.id)} />
              ))}
            </div>
          ))}
          {typed !== null && (
            <button
              type="button"
              disabled={busy}
              data-testid="model-typed"
              onClick={() => void choose(typed)}
              className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm outline-none hover:bg-accent focus-visible:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            >
              <span className="size-4 shrink-0" aria-hidden />
              <span className="min-w-0 flex-1 break-all">
                Use <span className="font-medium">{typed}</span>
              </span>
            </button>
          )}
          {shown.length === 0 && typed === null && models.kind !== "loading" && openrouter.kind !== "loading" && (
            <p className="px-2 py-3 text-sm text-muted-foreground">No model has all of those words in its name.</p>
          )}
          {openrouter.kind === "loading" && (
            <p className="flex items-center gap-2 px-2 py-1 text-xs text-muted-foreground" role="status">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> Reading OpenRouter&apos;s models…
            </p>
          )}
        </div>

        {(trouble || openrouter.kind === "failed") && (
          <p className="text-xs text-muted-foreground" role="status" data-testid="model-trouble">
            {trouble ??
              "OpenRouter's models could not be read, so only those named here are listed. One of OpenRouter's can still be typed, as openrouter/<author>/<model>."}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
