"use client";

import { Aside, describedBy, Field, Section } from "@/components/settings-fields";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Radio } from "@/components/ui/radio";
import { keyRows } from "@/lib/keys";
import { CODE_PLACES, SANDBOXES, type Draft } from "@/lib/settings";
import type { KeyStatuses } from "@/lib/types";
import type { Loaded } from "@/lib/use-settings-data";

function Places({ draft, onChange }: { draft: Draft; onChange: (changes: Partial<Draft>) => void }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="pb-1.5 text-sm font-medium">Where the lab runs code</legend>
      {CODE_PLACES.map((place) => (
        <label key={place.value} className="flex items-start gap-2.5 text-sm">
          <Radio
            name="settings-code-place"
            value={place.value}
            checked={draft.code === place.value}
            onChange={() => onChange({ code: place.value })}
            className="mt-0.5"
          />
          <span className="flex flex-col gap-0.5">
            <span className="font-medium">{place.label}</span>
            <span className="text-xs text-muted-foreground">{place.about}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

function ForwardedKeys({
  draft,
  onChange,
  keys,
}: {
  draft: Draft;
  onChange: (changes: Partial<Draft>) => void;
  keys: Loaded<KeyStatuses>;
}) {
  const rows = keys.kind === "ready" ? keyRows(keys.value) : [];

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="pb-1.5 text-sm font-medium">Keys that code can read</legend>
      <p className="text-xs text-muted-foreground">
        Some of Biomni&apos;s tools call a model, and need a key to do it. Code can read the keys chosen here, and with the
        network, send them anywhere. Code cannot run while one of them is not set.
      </p>
      {keys.kind === "loading" && <p className="text-xs text-muted-foreground">Looking at which keys there are…</p>}
      {keys.kind === "failed" && <p className="text-xs text-destructive">The keys could not be listed.</p>}
      {rows.map((row) => (
        <label key={row.name} className="flex items-center gap-2.5 text-sm">
          <Checkbox
            checked={draft.forwardKeys.includes(row.name)}
            onChange={(event) =>
              onChange({
                forwardKeys: event.target.checked
                  ? [...draft.forwardKeys, row.name]
                  : draft.forwardKeys.filter((name) => name !== row.name),
              })
            }
          />
          <span>{row.provider} key</span>
          <code className="text-xs text-muted-foreground">{row.name}</code>
          {!row.set && <span className="ml-auto text-xs text-muted-foreground">Not set</span>}
        </label>
      ))}
    </fieldset>
  );
}

export function CodeTab({
  draft,
  onChange,
  keys,
}: {
  draft: Draft;
  onChange: (changes: Partial<Draft>) => void;
  keys: Loaded<KeyStatuses>;
}) {
  const sandbox = SANDBOXES.find((choice) => choice.value === draft.sandbox);

  return (
    <div className="flex flex-col gap-6">
      <Section>
        <Places draft={draft} onChange={onChange} />
        {draft.code === "local" && (
          <>
            <Aside tone="warning">
              Code on this computer is not held in anything. It can read and change your files and reach the network as you do.
            </Aside>
            <Field
              id="settings-python"
              label="Python to run code with"
              hint="The path of a Python on this computer. Leave it empty to use the server's own."
            >
              <Input
                id="settings-python"
                value={draft.python}
                onChange={(event) => onChange({ python: event.target.value })}
                aria-describedby={describedBy("settings-python", { hint: true })}
                placeholder="The server's own Python"
                autoComplete="off"
                spellCheck={false}
              />
            </Field>
          </>
        )}
      </Section>

      {draft.code === "docker" && (
        <Section title="Docker">
          <Field id="settings-sandbox" label="Image" hint={sandbox?.about}>
            <NativeSelect
              id="settings-sandbox"
              value={draft.sandbox}
              onChange={(event) => onChange({ sandbox: event.target.value })}
              aria-describedby={describedBy("settings-sandbox", { hint: sandbox !== undefined })}
            >
              {SANDBOXES.map((choice) => (
                <option key={choice.value} value={choice.value}>
                  {choice.label}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <label className="flex items-start gap-2.5 text-sm">
            <Checkbox checked={draft.network} onChange={(event) => onChange({ network: event.target.checked })} className="mt-0.5" />
            <span className="flex flex-col gap-0.5">
              <span className="font-medium">Code can reach the network</span>
              <span className="text-xs text-muted-foreground">Without it, code cannot download data or install what it needs.</span>
            </span>
          </label>
          {draft.sandbox !== "python" && (
            <Field
              id="settings-data-lake"
              label="Data lake"
              hint="The folder of Biomni's data that is shared with code, read-only. Leave it empty to use the workspace's own."
            >
              <Input
                id="settings-data-lake"
                value={draft.dataLake}
                onChange={(event) => onChange({ dataLake: event.target.value })}
                aria-describedby={describedBy("settings-data-lake", { hint: true })}
                placeholder="Inside the workspace"
                autoComplete="off"
                spellCheck={false}
              />
            </Field>
          )}
          <ForwardedKeys draft={draft} onChange={onChange} keys={keys} />
        </Section>
      )}
    </div>
  );
}
