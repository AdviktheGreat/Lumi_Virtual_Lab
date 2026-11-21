"use client";

import { describedBy, Field } from "@/components/settings-fields";
import { Input } from "@/components/ui/input";
import { MAX_SCOPE_CHARS, MAX_UNIT_CHARS, type ScopeDraft } from "@/lib/paperagent-scope";

// What a person says their data is: its species, tissue, assay, input format, and sample size, any of it. It is asked where a method's
// card is put against the data, and where a bake-off is told what the data is that its methods are run on.
export function ScopeFields({
  draft,
  change,
  problems,
  id,
}: {
  draft: ScopeDraft;
  change: (part: keyof ScopeDraft, value: string) => void;
  problems: Partial<Record<keyof ScopeDraft, string>>;
  // The id that the ids of the fields are made from
  id: string;
}) {
  const text = (part: Exclude<keyof ScopeDraft, "size">, label: string, hint?: string, max = MAX_SCOPE_CHARS) => (
    <Field id={`${id}-${part}`} label={label} hint={hint} problem={problems[part]}>
      <Input
        id={`${id}-${part}`}
        value={draft[part]}
        onChange={(event) => change(part, event.target.value)}
        maxLength={max * 2}
        autoComplete="off"
        aria-invalid={problems[part] !== undefined}
        aria-describedby={describedBy(`${id}-${part}`, { hint: hint !== undefined, problem: problems[part] !== undefined })}
      />
    </Field>
  );

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {text("species", "Species", "Such as human, or Mus musculus.")}
      {text("tissue", "Tissue", "Such as liver, or PBMC.")}
      {text("assay", "Assay", "Such as single-cell RNA-seq.")}
      {text("format", "Input format", "Such as h5ad, or a CSV of counts.")}
      <Field id={`${id}-size`} label="Sample size" hint="A whole number. Say what it counts, if you can." problem={problems.size}>
        <Input
          id={`${id}-size`}
          value={draft.size}
          onChange={(event) => change("size", event.target.value)}
          inputMode="numeric"
          maxLength={20}
          autoComplete="off"
          aria-invalid={problems.size !== undefined}
          aria-describedby={describedBy(`${id}-size`, { hint: true, problem: problems.size !== undefined })}
        />
      </Field>
      {text("unit", "What the size counts", "Such as cells, nuclei, or patients.", MAX_UNIT_CHARS)}
    </div>
  );
}
