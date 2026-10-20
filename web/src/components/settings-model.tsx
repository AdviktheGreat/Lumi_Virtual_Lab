"use client";

import { useState } from "react";
import { ModelDialog } from "@/components/model-dialog";
import { describedBy, Field, Section } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { isOffered, keysMissingFor, type Draft, type Problems } from "@/lib/settings";
import type { Loaded } from "@/lib/use-settings-data";
import type { KeyStatuses, Models } from "@/lib/types";

// What the choice of "another model" has for a value, which no model is named
const OTHER = "@other";

// The models, grouped by whose they are, in the order the server gives them
function byProvider(models: Models): [string, Models["models"]][] {
  const groups = new Map<string, Models["models"]>();
  for (const choice of models.models) {
    const name = choice.provider ?? "Others";
    groups.set(name, [...(groups.get(name) ?? []), choice]);
  }

  return [...groups];
}

function ModelPicker({
  value,
  onChange,
  chosenToType,
  onChooseToType,
  models,
  problem,
  describedByIds,
}: {
  value: string;
  onChange: (model: string) => void;
  // A name that is typed stays typed while it is, even when it is the name of one that is offered, and one that is not
  // offered can only be typed
  chosenToType: boolean;
  onChooseToType: (typing: boolean) => void;
  models: Loaded<Models>;
  problem?: string;
  describedByIds?: string;
}) {
  const offered = models.kind === "ready" ? models.value : null;

  if (offered === null) {
    return (
      <Input
        id="settings-model"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={problem !== undefined}
        aria-describedby={describedByIds}
        placeholder={models.kind === "loading" ? "Loading the models…" : "The name of a model"}
        autoComplete="off"
        spellCheck={false}
      />
    );
  }

  const typing = chosenToType || !isOffered(value, offered);

  return (
    <div className="flex flex-col gap-2">
      <NativeSelect
        id="settings-model"
        value={typing ? OTHER : value}
        onChange={(event) => {
          if (event.target.value === OTHER) {
            onChooseToType(true);
          } else {
            onChooseToType(false);
            onChange(event.target.value);
          }
        }}
        aria-invalid={problem !== undefined}
        aria-describedby={describedByIds}
      >
        {byProvider(offered).map(([provider, choices]) => (
          <optgroup key={provider} label={provider}>
            {choices.map((choice) => (
              <option key={choice.id} value={choice.id}>
                {choice.ready ? choice.id : `${choice.id} (needs a key)`}
              </option>
            ))}
          </optgroup>
        ))}
        <option value={OTHER}>Another model…</option>
      </NativeSelect>
      {typing && (
        <Input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-label="Name of the model"
          aria-invalid={problem !== undefined}
          placeholder="The name of a model"
          autoComplete="off"
          spellCheck={false}
        />
      )}
    </div>
  );
}

export function ModelTab({
  draft,
  onChange,
  typing,
  onTyping,
  problems,
  models,
  keys,
  onAddKey,
}: {
  draft: Draft;
  onChange: (changes: Partial<Draft>) => void;
  // Whether the model is being named rather than chosen, which is kept by whoever holds the settings, so that it is not
  // forgotten on moving to another part of them
  typing: boolean;
  onTyping: (typing: boolean) => void;
  problems: Problems;
  models: Loaded<Models>;
  keys: Loaded<KeyStatuses>;
  // Goes to where the key is given
  onAddKey: () => void;
}) {
  const [browsing, setBrowsing] = useState(false);
  const missing = keysMissingFor(
    draft.model.trim(),
    models.kind === "ready" ? models.value : null,
    keys.kind === "ready" ? keys.value : null,
  );

  return (
    <div className="flex flex-col gap-6">
      <Section>
        <Field
          id="settings-model"
          label="Model"
          problem={problems.model}
          hint={
            models.kind === "failed"
              ? "The list of models could not be read, so the model is named here."
              : "The lead and the team of a new conversation use it."
          }
        >
          <ModelPicker
            value={draft.model}
            onChange={(model) => onChange({ model })}
            chosenToType={typing}
            onChooseToType={onTyping}
            models={models}
            problem={problems.model}
            describedByIds={describedBy("settings-model", { hint: true, problem: problems.model !== undefined })}
          />
        </Field>
        <Button
          type="button"
          variant="link"
          size="xs"
          onClick={() => setBrowsing(true)}
          className="h-auto self-start p-0 text-xs"
        >
          Search all models, including OpenRouter&apos;s
        </Button>
        {browsing && (
          <ModelDialog
            title="Choose the model"
            description="The lead and the team of a new conversation use it. A conversation that has begun keeps its own, which can be changed from it."
            current={draft.model.trim()}
            onChoose={async (model) => {
              onChange({ model });
              setBrowsing(false);
            }}
            onClose={() => setBrowsing(false)}
          />
        )}
        {missing.length > 0 && (
          <p role="status" className="flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
            <span>
              This model needs {missing.join(", ")}, which {missing.length === 1 ? "is" : "are"} not set.
            </span>
            <Button type="button" variant="link" size="xs" onClick={onAddKey} className="h-auto p-0 text-xs">
              Add {missing.length === 1 ? "it" : "them"}
            </Button>
          </p>
        )}
      </Section>

      <Section title="Spending and replies">
        <Field
          id="settings-limit"
          label="Spending limit for a conversation (US dollars)"
          problem={problems.limit}
          hint="The most one conversation may spend. Leave it empty for no limit."
        >
          <Input
            id="settings-limit"
            value={draft.limit}
            onChange={(event) => onChange({ limit: event.target.value })}
            inputMode="decimal"
            placeholder="No limit"
            aria-invalid={problems.limit !== undefined}
            aria-describedby={describedBy("settings-limit", { hint: true, problem: problems.limit !== undefined })}
            autoComplete="off"
          />
        </Field>
        <label className="flex items-start gap-2.5 text-sm">
          <Checkbox
            checked={draft.stream}
            onChange={(event) => onChange({ stream: event.target.checked })}
            className="mt-0.5"
          />
          <span className="flex flex-col gap-0.5">
            <span className="font-medium">Show replies as they are written</span>
            <span className="text-xs text-muted-foreground">Otherwise a reply is shown once it is whole.</span>
          </span>
        </label>
      </Section>
    </div>
  );
}
