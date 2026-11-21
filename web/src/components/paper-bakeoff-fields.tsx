"use client";

import Link from "next/link";
import { ScopeFields } from "@/components/paper-agent-scope-fields";
import { describedBy, Field } from "@/components/settings-fields";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { formatBytes } from "@/lib/files";
import { MAX_COLUMN_CHARS, type BakeoffDraft, type BakeoffKey } from "@/lib/bakeoffs";
import type { BakeoffLimits, OwnDataSummary } from "@/lib/types";

const LINK = "rounded-sm underline underline-offset-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50";

// A file of the person's that right answers can be read from, which is a table in a .csv or a .tsv
export function isAnswersFile(data: OwnDataSummary): boolean {
  return data.kind === "file" && /\.(csv|tsv)$/i.test(data.name);
}

function describeOwn(data: OwnDataSummary): string {
  if (data.kind === "folder") return `${data.name} (a folder)`;

  return data.kind === "missing" ? `${data.name} (not where the Data page says it is)` : `${data.name} (${formatBytes(data.bytes)})`;
}

// What a bake-off is for, which of the person's data it is run on and what that is, where their right answers are if they have them,
// and the most it may spend. It is asked when a bake-off is made, and when one is said again.
export function BakeoffFields({
  draft,
  change,
  problems,
  busy,
  own,
  limits,
  field,
  settingsModel,
}: {
  draft: BakeoffDraft;
  change: (part: Partial<BakeoffDraft>) => void;
  problems: Partial<Record<BakeoffKey, string>>;
  busy: boolean;
  own: readonly OwnDataSummary[];
  limits: Pick<BakeoffLimits, "max_task_chars" | "max_title_chars">;
  // The id of a field of the form it is in, from its name
  field: (name: string) => string;
  // The model that reading papers is paid for with, which the limit is of
  settingsModel: string;
}) {
  // What the draft names is offered even if it is not there now, so that it is shown as what it is and not as nothing
  const named = (name: string) => (name !== "" && !own.some((one) => one.name === name) ? [{ name, description: "", kind: "missing", bytes: 0 }] : []);
  const data = [...own.filter((one) => one.kind !== "missing" || one.name === draft.data), ...named(draft.data)];
  const answers = [...own.filter((one) => isAnswersFile(one) || one.name === draft.answers), ...named(draft.answers)];
  const unique = <T extends { name: string }>(list: T[]) => list.filter((one, at) => list.findIndex((other) => other.name === one.name) === at);

  return (
    <>
      <Field
        id={field("task")}
        label="What you want done"
        hint="In your own words, such as: assign a cell type to each cell of my single-nucleus RNA-seq data."
        problem={problems.task}
      >
        <Textarea
          id={field("task")}
          value={draft.task}
          onChange={(event) => change({ task: event.target.value })}
          maxLength={limits.max_task_chars * 4}
          rows={3}
          readOnly={busy}
          aria-invalid={problems.task !== undefined}
          aria-describedby={describedBy(field("task"), { hint: true, problem: problems.task !== undefined })}
        />
      </Field>

      <Field id={field("title")} label="Title" hint="Optional. If it is left blank, the start of what you want done is used." problem={problems.title}>
        <Input
          id={field("title")}
          value={draft.title}
          onChange={(event) => change({ title: event.target.value })}
          maxLength={limits.max_title_chars * 4}
          autoComplete="off"
          readOnly={busy}
          aria-invalid={problems.title !== undefined}
          aria-describedby={describedBy(field("title"), { hint: true, problem: problems.title !== undefined })}
        />
      </Field>

      <Field
        id={field("data")}
        label="Your data"
        hint={
          <>
            The methods are run on it, with no network, and it is read-only to them. It can be said later, but nothing is run without it. Add data on the{" "}
            <Link href="/data" className={LINK}>
              Data page
            </Link>
            .
          </>
        }
        problem={problems.data}
      >
        <NativeSelect
          id={field("data")}
          value={draft.data}
          onChange={(event) => change({ data: event.target.value })}
          disabled={busy}
          aria-describedby={describedBy(field("data"), { hint: true, problem: problems.data !== undefined })}
        >
          <option value="">Not said yet</option>
          {unique(data).map((one) => (
            <option key={one.name} value={one.name}>
              {describeOwn(one)}
            </option>
          ))}
        </NativeSelect>
      </Field>

      <fieldset className="flex flex-col gap-3" disabled={busy}>
        <legend className="mb-1 text-sm font-medium">What your data is</legend>
        <p className="text-xs text-muted-foreground">
          Optional, any of it. It is put against what the paper of each method says the method was tested on, which warns if your data is
          outside, and stops nothing.
        </p>
        <ScopeFields draft={draft.scope} change={(part, value) => change({ scope: { ...draft.scope, [part]: value } })} problems={problems} id={field("scope")} />
      </fieldset>

      <fieldset className="flex flex-col gap-3" disabled={busy}>
        <legend className="mb-1 text-sm font-medium">Right answers</legend>
        <p className="text-xs text-muted-foreground">
          Optional. If you have them, a table of yours on the Data page with the right answer for each row, the methods are held to them and
          ranked by how many they match. They are your word, and nothing here checks them. Without them the methods are only compared with
          each other, and are not ranked.
        </p>
        <Field id={field("answers")} label="The file that has them" hint="A .csv or .tsv on the Data page." problem={problems.answers}>
          <NativeSelect
            id={field("answers")}
            value={draft.answers}
            onChange={(event) => change({ answers: event.target.value })}
            aria-invalid={problems.answers !== undefined}
            aria-describedby={describedBy(field("answers"), { hint: true, problem: problems.answers !== undefined })}
          >
            <option value="">None</option>
            {unique(answers).map((one) => (
              <option key={one.name} value={one.name}>
                {describeOwn(one)}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field id={field("column")} label="Its column of answers" hint="The name of the column, as it is written in the file." problem={problems.column}>
            <Input
              id={field("column")}
              value={draft.column}
              onChange={(event) => change({ column: event.target.value })}
              maxLength={MAX_COLUMN_CHARS * 2}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={problems.column !== undefined}
              aria-describedby={describedBy(field("column"), { hint: true, problem: problems.column !== undefined })}
            />
          </Field>
          <Field
            id={field("idColumn")}
            label="Its column of what each is the answer to"
            hint="Optional. Leave it blank if the rows are in the order of your data."
            problem={problems.idColumn}
          >
            <Input
              id={field("idColumn")}
              value={draft.idColumn}
              onChange={(event) => change({ idColumn: event.target.value })}
              maxLength={MAX_COLUMN_CHARS * 2}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={problems.idColumn !== undefined}
              aria-describedby={describedBy(field("idColumn"), { hint: true, problem: problems.idColumn !== undefined })}
            />
          </Field>
        </div>
      </fieldset>

      <Field
        id={field("limit")}
        label="Most it may spend, in dollars"
        hint={`One limit for the whole of it. Reading the papers of the methods is paid for with ${settingsModel}, the model in the settings, out of it, and the spending is looked at before each request, so that the one that is going may take a little more than is left.`}
        problem={problems.limit}
      >
        <Input
          id={field("limit")}
          value={draft.limit}
          onChange={(event) => change({ limit: event.target.value })}
          inputMode="decimal"
          autoComplete="off"
          readOnly={busy}
          className="sm:max-w-xs"
          aria-invalid={problems.limit !== undefined}
          aria-describedby={describedBy(field("limit"), { hint: true, problem: problems.limit !== undefined })}
        />
      </Field>
    </>
  );
}
