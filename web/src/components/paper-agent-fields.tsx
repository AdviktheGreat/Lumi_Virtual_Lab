"use client";

import { describedBy, Field } from "@/components/settings-fields";
import { Input } from "@/components/ui/input";
import { Radio } from "@/components/ui/radio";
import { formatBytes } from "@/lib/files";
import { MAX_AGENT_TITLE, PAPER_KIND_LABELS, PAPER_KINDS, type AgentDraft } from "@/lib/paperagents";
import type { PaperAgentsList } from "@/lib/types";

// Which paper an agent is of, what it is called, and where its code is, which is asked for when an agent is made, and again when one
// that someone else made is imported
export function AgentFields({
  draft,
  change,
  problems,
  busy,
  list,
  field,
}: {
  draft: AgentDraft;
  change: (part: Partial<AgentDraft>) => void;
  problems: Partial<Record<"title" | "doi" | "url" | "repo", string>>;
  busy: boolean;
  list: Pick<PaperAgentsList, "suffixes" | "max_paper_bytes" | "repo_hosts">;
  // The id of a field of the form it is in, from its name
  field: (name: string) => string;
}) {
  return (
    <>
      <fieldset className="flex flex-wrap gap-x-5 gap-y-2" disabled={busy}>
        <legend className="mb-1.5 text-sm font-medium">Which paper</legend>
        {PAPER_KINDS.map((kind) => (
          <label key={kind} className="flex items-center gap-2 text-sm">
            <Radio name={field("kind")} checked={draft.kind === kind} onChange={() => change({ kind })} />
            {PAPER_KIND_LABELS[kind]}
          </label>
        ))}
      </fieldset>

      {draft.kind === "doi" && (
        <Field id={field("doi")} label="DOI" hint="Such as 10.1038/s41586-020-2649-2. A link to a DOI works too." problem={problems.doi}>
          <Input
            id={field("doi")}
            value={draft.doi}
            onChange={(event) => change({ doi: event.target.value })}
            autoComplete="off"
            spellCheck={false}
            readOnly={busy}
            aria-invalid={problems.doi !== undefined}
            aria-describedby={describedBy(field("doi"), { hint: true, problem: problems.doi !== undefined })}
          />
        </Field>
      )}

      {draft.kind === "url" && (
        <Field id={field("url")} label="Link to the paper" hint="Where it can be read on the web." problem={problems.url}>
          <Input
            id={field("url")}
            value={draft.url}
            onChange={(event) => change({ url: event.target.value })}
            placeholder="https://"
            autoComplete="off"
            spellCheck={false}
            readOnly={busy}
            aria-invalid={problems.url !== undefined}
            aria-describedby={describedBy(field("url"), { hint: true, problem: problems.url !== undefined })}
          />
        </Field>
      )}

      {draft.kind === "file" && (
        <p className="text-xs text-muted-foreground">
          You upload it to the agent once it is made. {list.suffixes.join(", ")} files are read, of up to {formatBytes(list.max_paper_bytes)}.
        </p>
      )}

      <Field
        id={field("title")}
        label="Title"
        hint={draft.kind === "file" ? "What the agent is called." : "What the agent is called. If it is left blank, the DOI or the link is used."}
        problem={problems.title}
      >
        <Input
          id={field("title")}
          value={draft.title}
          onChange={(event) => change({ title: event.target.value })}
          maxLength={MAX_AGENT_TITLE * 4}
          autoComplete="off"
          readOnly={busy}
          aria-invalid={problems.title !== undefined}
          aria-describedby={describedBy(field("title"), { hint: true, problem: problems.title !== undefined })}
        />
      </Field>

      <Field
        id={field("repo")}
        label="Where its code is"
        hint={`Optional. The address of the project, such as https://github.com/owner/name, at ${list.repo_hosts.join(", ")}.`}
        problem={problems.repo}
      >
        <Input
          id={field("repo")}
          value={draft.repo}
          onChange={(event) => change({ repo: event.target.value })}
          placeholder="https://github.com/owner/name"
          autoComplete="off"
          spellCheck={false}
          readOnly={busy}
          aria-invalid={problems.repo !== undefined}
          aria-describedby={describedBy(field("repo"), { hint: true, problem: problems.repo !== undefined })}
        />
      </Field>
    </>
  );
}
