"use client";

import { useId, useState } from "react";
import { Ban, Check, CircleAlert, ExternalLink, KeyRound, Loader2, MessageCircleQuestion, Minus, ShieldQuestion } from "lucide-react";
import { useChatId } from "@/components/chat-files";
import { CodeBlock } from "@/components/code";
import { useSettings } from "@/components/settings-provider";
import { Field } from "@/components/settings-fields";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { api } from "@/lib/api";
import { formFields, initialValues, isWebAddress, readAnswer, type FormField, type FormValue } from "@/lib/asking";
import { describeError } from "@/lib/errors";
import type { Approval, Connection, Question } from "@/lib/transcript";
import { cn } from "@/lib/utils";

const CARD = "rounded-xl border border-border bg-card";

// What is waited on is set apart from what has been done
const WAITING_CARD = "rounded-xl border border-warning/60 bg-card";

function IconTile({ icon }: { icon: React.ReactNode }) {
  return (
    <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground" aria-hidden>
      {icon}
    </span>
  );
}

// What was asked, as a line, once it has been answered
function Line({
  icon,
  title,
  detail,
  status,
  testid,
  state,
}: {
  icon: React.ReactNode;
  title: string;
  detail?: string;
  status: string;
  testid: string;
  state: string;
}) {
  return (
    <div className={cn(CARD, "flex items-center gap-2.5 px-3 py-2")} data-testid={testid} data-state={state}>
      <IconTile icon={icon} />
      <span className="shrink-0 text-sm font-medium">{title}</span>
      {detail ? <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{detail}</span> : <span className="flex-1" />}
      <span className="shrink-0 text-xs text-muted-foreground">{status}</span>
    </div>
  );
}

// Why an answer was not taken, which the person can act on where it is theirs to put right
function Problem({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="flex items-start gap-1.5 text-xs text-destructive">
      <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
      <span className="min-w-0 whitespace-pre-wrap break-words">{children}</span>
    </p>
  );
}

// What it takes to send an answer to the server: one at a time, with what went wrong to say
function useSending() {
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function send(answer: () => Promise<unknown>) {
    setSending(true);
    setProblem(null);
    try {
      await answer();
    } catch (error) {
      setProblem(describeError(error));
      setSending(false);
    }
    // What was sent is settled by the conversation saying so, which takes this card's place, so there is nothing to
    // do here once it has gone well
  }

  return { sending, problem, send };
}

const APPROVAL_END = { approved: "Allowed", declined: "Declined", withdrawn: "Not answered, so not called" } as const;

// A call to a tool that waits for the researcher to allow it
export function ApprovalCard({ approval }: { approval: Approval }) {
  const id = useChatId();
  const { sending, problem, send } = useSending();
  const heading = useId();
  const shown = approval.arguments.trim();

  if (approval.state !== "waiting") {
    const icon = approval.state === "approved" ? <Check className="size-3.5" /> : approval.state === "declined" ? <Ban className="size-3.5" /> : <Minus className="size-3.5" />;

    return (
      <Line
        icon={icon}
        title={approval.tool || "A tool"}
        detail={approval.title}
        status={APPROVAL_END[approval.state]}
        testid="approval"
        state={approval.state}
      />
    );
  }

  return (
    <div className={WAITING_CARD} data-testid="approval" data-state="waiting" role="group" aria-labelledby={heading}>
      <div className="flex items-center gap-2.5 px-3 py-2">
        <IconTile icon={<ShieldQuestion className="size-3.5" />} />
        <span id={heading} className="min-w-0 flex-1 truncate text-sm font-medium">
          Allow {approval.tool || "this call"}?
        </span>
        <span className="shrink-0 text-xs text-muted-foreground">{approval.title}</span>
      </div>
      <div className="flex flex-col gap-3 border-t border-border/70 p-3">
        <p role="status" className="sr-only">
          Waiting for you to allow or decline {approval.tool}
        </p>
        <p className="text-sm">
          {approval.tool ? <span className="font-mono text-[13px]">{approval.tool}</span> : "This tool"} is a tool of {approval.title}, and each call to
          it needs your approval.
        </p>
        {approval.description !== "" && <p className="text-sm text-muted-foreground">{approval.description}</p>}
        {shown !== "" && shown !== "{}" && (
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium text-muted-foreground">It is to be called with</span>
            <CodeBlock code={approval.arguments} language="json" foldAfter={12} />
          </div>
        )}
        {problem !== null && <Problem>{problem}</Problem>}
        <div className="flex gap-2">
          <Button type="button" size="sm" disabled={sending} onClick={() => void send(() => api.approve(id, approval.request, true))}>
            Allow
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={sending} onClick={() => void send(() => api.approve(id, approval.request, false))}>
            Decline
          </Button>
          {sending && <Loader2 className="size-4 animate-spin self-center text-muted-foreground" aria-label="Sending" role="status" />}
        </div>
      </div>
    </div>
  );
}

const QUESTION_END = { answered: "Answered", declined: "Declined", withdrawn: "Not answered" } as const;

// Where a field is told what it takes, beside what the server said of it
function hintOf(field: FormField): string | undefined {
  const takes = field.kind === "integer" ? "A whole number." : field.kind === "number" ? "A number." : field.kind === "array" && field.options.length === 0 ? "Separate them with commas." : "";
  const said = [field.description, takes].filter((part) => part !== "").join(" ");

  return said === "" ? undefined : said;
}

function FieldInput({
  field,
  id,
  value,
  problem,
  onChange,
}: {
  field: FormField;
  id: string;
  value: FormValue;
  problem?: string;
  onChange: (value: FormValue) => void;
}) {
  const hint = hintOf(field);
  const described = [hint ? `${id}-hint` : null, problem ? `${id}-problem` : null].filter(Boolean).join(" ") || undefined;
  const label = field.required ? field.label : `${field.label} (optional)`;

  if (field.kind === "boolean") {
    return (
      <div className="flex flex-col gap-1">
        <label className="flex items-center gap-2 text-sm font-medium">
          <Checkbox name={field.name} checked={value === true} onChange={(event) => onChange(event.target.checked)} aria-describedby={described} />
          {field.label}
        </label>
        {hint && (
          <p id={`${id}-hint`} className="text-xs text-muted-foreground">
            {hint}
          </p>
        )}
      </div>
    );
  }

  if (field.kind === "array" && field.options.length > 0) {
    const chosen = Array.isArray(value) ? value : [];

    return (
      <fieldset className="flex flex-col gap-1.5" aria-describedby={described} aria-invalid={problem ? true : undefined}>
        <legend className="mb-1.5 text-sm font-medium">{label}</legend>
        {field.options.map((option, at) => (
          <label key={at} className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={chosen.includes(String(at))}
              onChange={(event) => onChange(event.target.checked ? [...chosen, String(at)] : chosen.filter((one) => one !== String(at)))}
            />
            {option.label}
          </label>
        ))}
        {hint && (
          <p id={`${id}-hint`} className="text-xs text-muted-foreground">
            {hint}
          </p>
        )}
        {problem && (
          <p id={`${id}-problem`} role="alert" className="text-xs text-destructive">
            {problem}
          </p>
        )}
      </fieldset>
    );
  }

  return (
    <Field id={id} label={label} hint={hint} problem={problem}>
      {field.kind === "choice" ? (
        <NativeSelect id={id} value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value)} aria-describedby={described} aria-invalid={problem ? true : undefined}>
          <option value="">{field.required ? "Choose one" : "Leave it out"}</option>
          {field.options.map((option, at) => (
            <option key={at} value={String(at)}>
              {option.label}
            </option>
          ))}
        </NativeSelect>
      ) : (
        <Input
          id={id}
          value={typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value)}
          inputMode={field.kind === "integer" ? "numeric" : field.kind === "number" ? "decimal" : undefined}
          aria-describedby={described}
          aria-invalid={problem ? true : undefined}
          autoComplete="off"
        />
      )}
    </Field>
  );
}

// The form a server's question is answered with
function QuestionForm({ question }: { question: Question }) {
  const id = useChatId();
  const form = useId();
  const fields = formFields(question);
  const [values, setValues] = useState(() => initialValues(fields));
  const [problems, setProblems] = useState<Record<string, string>>({});
  const { sending, problem, send } = useSending();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const read = readAnswer(fields, values);
    if (!read.ok) {
      setProblems(read.errors);
      // What is wrong is where the person is taken to
      const first = fields.find((field) => read.errors[field.name] !== undefined);
      if (first) document.getElementById(`${form}-${first.name}`)?.focus();

      return;
    }
    setProblems({});
    void send(() => api.answer(id, question.request, read.answer));
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
      {fields.map((field) => (
        <FieldInput
          key={field.name}
          field={field}
          id={`${form}-${field.name}`}
          value={values[field.name]}
          problem={problems[field.name]}
          onChange={(value) => {
            setValues((was) => ({ ...was, [field.name]: value }));
            // What was wrong with what is being changed is not known to be wrong any more
            setProblems((was) => Object.fromEntries(Object.entries(was).filter(([name]) => name !== field.name)));
          }}
        />
      ))}
      {problem !== null && <Problem>{problem}</Problem>}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={sending}>
          {fields.length === 0 ? "Agree" : "Send"}
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={sending} onClick={() => void send(() => api.answer(id, question.request, null))}>
          Decline
        </Button>
        {sending && <Loader2 className="size-4 animate-spin self-center text-muted-foreground" aria-label="Sending" role="status" />}
      </div>
    </form>
  );
}

// What a question that is answered at a web page asks: to go there, and to say that it was done
function QuestionPage({ question, url }: { question: Question; url: string | null }) {
  const id = useChatId();
  const { sending, problem, send } = useSending();

  return (
    <div className="flex flex-col gap-3">
      {url !== null ? (
        <p className="text-sm">
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 break-all font-medium text-primary underline underline-offset-4"
          >
            {url}
            <ExternalLink className="size-3.5 shrink-0" aria-hidden />
          </a>
        </p>
      ) : (
        <Problem>It asks for a page that is not a web address, so it cannot be opened from here. Decline it.</Problem>
      )}
      {problem !== null && <Problem>{problem}</Problem>}
      <div className="flex gap-2">
        <Button type="button" size="sm" disabled={sending || url === null} onClick={() => void send(() => api.answer(id, question.request, {}))}>
          I have done it
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={sending} onClick={() => void send(() => api.answer(id, question.request, null))}>
          Decline
        </Button>
        {sending && <Loader2 className="size-4 animate-spin self-center text-muted-foreground" aria-label="Sending" role="status" />}
      </div>
    </div>
  );
}

// What a server asks while one of its tools runs
export function QuestionCard({ question }: { question: Question }) {
  const heading = useId();
  const firstLine = question.text.trim().split("\n")[0];

  if (question.state !== "waiting") {
    const icon = question.state === "answered" ? <Check className="size-3.5" /> : question.state === "declined" ? <Ban className="size-3.5" /> : <Minus className="size-3.5" />;

    return (
      <Line
        icon={icon}
        title={`${question.title} asked`}
        detail={firstLine}
        status={QUESTION_END[question.state]}
        testid="question"
        state={question.state}
      />
    );
  }

  return (
    <div className={WAITING_CARD} data-testid="question" data-state="waiting" role="group" aria-labelledby={heading}>
      <div className="flex items-center gap-2.5 px-3 py-2">
        <IconTile icon={<MessageCircleQuestion className="size-3.5" />} />
        <span id={heading} className="min-w-0 flex-1 truncate text-sm font-medium">
          {question.title} asks
        </span>
      </div>
      <div className="flex flex-col gap-3 border-t border-border/70 p-3">
        <p role="status" className="sr-only">
          Waiting for your answer to {question.title}
        </p>
        {question.text.trim() !== "" && <p className="whitespace-pre-wrap break-words text-sm">{question.text.trim()}</p>}
        {question.url !== null ? <QuestionPage question={question} url={isWebAddress(question.url) ? question.url : null} /> : <QuestionForm question={question} />}
      </div>
    </div>
  );
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

// A server whose tools the lead is given, as it is connected to
export function ConnectionCard({ connection }: { connection: Connection }) {
  const settings = useSettings();
  const { state, title } = connection;

  if (state === "connecting") {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="connection" data-state={state} role="status">
        <Loader2 className="size-3.5 animate-spin" aria-hidden />
        Connecting to {title}
      </div>
    );
  }

  if (state === "ready") {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground" data-testid="connection" data-state={state}>
        <Check className="size-3.5" aria-hidden />
        Connected to {title}
        {connection.tools !== null && `, which gave ${plural(connection.tools, "tool")}`}
      </div>
    );
  }

  if (state === "signing_in") {
    const url = isWebAddress(connection.url) ? connection.url : null;

    return (
      <div className={cn(WAITING_CARD, "flex flex-col gap-3 p-3")} data-testid="connection" data-state={state} role="group" aria-label={`Sign in to ${title}`}>
        <div className="flex items-center gap-2.5">
          <IconTile icon={<KeyRound className="size-3.5" />} />
          <span className="text-sm font-medium">Sign in to {title}</span>
        </div>
        <p className="text-sm text-muted-foreground">
          {title} needs you to sign in. Open its page, sign in there, and come back: the lead goes on once you have.
        </p>
        <div className="flex items-center gap-3">
          {url !== null ? (
            <Button asChild size="sm">
              <a href={url} target="_blank" rel="noopener noreferrer">
                Open the sign-in page
                <ExternalLink className="size-3.5" aria-hidden />
              </a>
            </Button>
          ) : (
            <Problem>The sign-in page is not a web address, so it cannot be opened from here.</Problem>
          )}
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground" role="status">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            Waiting for you to sign in
          </span>
        </div>
      </div>
    );
  }

  return (
    <div
      role="alert"
      data-testid="connection"
      data-state={state}
      className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"
    >
      <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 whitespace-pre-wrap break-words">
        <span className="font-medium">Could not connect to {title}.</span>
        {connection.text !== "" && ` ${connection.text}`}
      </div>
      <Button variant="outline" size="xs" onClick={() => settings.open("tools")} className="shrink-0 text-foreground">
        Tool settings
      </Button>
    </div>
  );
}
