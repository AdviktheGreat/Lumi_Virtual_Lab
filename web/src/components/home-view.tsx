"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { KeyRound } from "lucide-react";
import { BrandLogo } from "@/components/brand";
import { CapabilityCards } from "@/components/capability-cards";
import { useChats } from "@/components/chats-provider";
import { CommandsHelp } from "@/components/commands-help";
import { Composer } from "@/components/composer";
import { LabDialog } from "@/components/lab-dialog";
import { LimitsDialog } from "@/components/limits-dialog";
import { Notice, ProblemNotice } from "@/components/messages";
import { ModelButton, ModelDialog } from "@/components/model-dialog";
import { PageHeader } from "@/components/page-header";
import { PROGRAM_CODE_ID, PROGRAM_INSTRUCTIONS_ID, PROGRAM_NAME_ID, ProgramStart } from "@/components/program-start";
import { useServer } from "@/components/server-provider";
import { useSettings } from "@/components/settings-provider";
import { SkillsDialog } from "@/components/skills-dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { readiness } from "@/lib/attachments";
import { givenAs, isDirective, written, type Invocation, type PromptInvocation, type Sendable } from "@/lib/commands";
import { plainProblem, problemOf, type Problem } from "@/lib/errors";
import { formatAmount } from "@/lib/limits";
import { checkProgram, type ProgramDraft, type ProgramProblems } from "@/lib/programs";
import { withPrompt } from "@/lib/prompts";
import { choiceButtonText, choiceKept, choiceStart, vanished } from "@/lib/skills";
import { DEFAULT_LEAD_TITLE } from "@/lib/team-choice";
import { useAttachments } from "@/lib/use-attachments";
import { useMissingKeys } from "@/lib/use-missing-keys";
import { usePromptChoices } from "@/lib/use-prompt-choices";
import { useSkillChoices } from "@/lib/use-skill-choices";
import type { ChatInfo, LabChoice, LimitsChange, ProgramKind } from "@/lib/types";

// What shows what is chosen of the skills, beside the model, and opens the choice
function SkillsButton({ chosen, disabled, onClick }: { chosen: string[] | null; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      data-testid="skills-button"
      disabled={disabled}
      onClick={onClick}
      title="Choose the skills the lead can read"
      className="-mx-1 inline-flex shrink-0 items-center gap-1 rounded px-1 py-0.5 outline-none transition-colors enabled:hover:bg-accent enabled:hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span>{choiceButtonText(chosen)}</span>
    </button>
  );
}

// The page where a program is begun, which begins as the one that a link to it names (build_skill), and as a quick task
// otherwise, and in the campaign that the link names. It begins again when the link changes, as a new program does, with
// nothing typed.
export function HomeView() {
  const params = useSearchParams();
  const kind: ProgramKind = params.get("program") === "build_skill" ? "build_skill" : "quick_task";
  const campaign = params.get("campaign") ?? "";

  return <Home key={`${kind}:${campaign}`} kind={kind} linked={campaign} />;
}

function Home({ kind, linked }: { kind: ProgramKind; linked: string }) {
  const router = useRouter();
  const { server, report } = useServer();
  const { refresh, campaigns } = useChats();
  const settings = useSettings();
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  // The model chosen here for the conversation to begin, in place of the one the settings name, and whether it is being chosen
  const [chosen, setChosen] = useState<string | null>(null);
  const [choosing, setChoosing] = useState(false);
  // The limits chosen here for it, which are only those that differ from what the settings say, and whether they are being chosen
  const [limitsChosen, setLimitsChosen] = useState<LimitsChange>({});
  const [limiting, setLimiting] = useState(false);
  // The skills chosen here for it, which are null while it is to be given those that are on for new conversations, and whether
  // they are being chosen
  const [skillsChosen, setSkillsChosen] = useState<string[] | null>(null);
  const [skilling, setSkilling] = useState(false);
  // What was written after /lab while it is being chosen who works on it, which is null while it is not
  const [labbing, setLabbing] = useState<string | null>(null);
  const [helping, setHelping] = useState(false);
  // What it is to be begun as, and what is wrong with what was typed of it, which is shown once it has been tried to begin it
  const [program, setProgram] = useState<ProgramDraft>({ kind, name: "", instructions: "" });
  const [shown, setShown] = useState<ProgramProblems>({});
  // The campaign it is to be begun in, which is "" for none, and is none where the campaign that was asked for is not there
  const [campaignChosen, setCampaignChosen] = useState(linked);
  const campaign = campaigns === null || campaigns.some((each) => each.id === campaignChosen) ? campaignChosen : "";
  // There is no conversation to send files to until the message is, so they are held until then
  const attachments = useAttachments(null, server.status === "ready" ? server.settings.max_upload_bytes : null);

  function attach(files: File[]) {
    const refused = attachments.add(files);
    if (refused.length > 0) setProblem(plainProblem(refused.join("\n")));
  }

  // A conversation is begun with a message, which a command may be given with, and with /lab who is to work on it. If it could
  // not be, there is no conversation, and the error is thrown.
  async function begin(text: string, directive?: string, lab?: LabChoice, skill?: string) {
    let chat: ChatInfo | null = null;
    try {
      chat = await api.createChat({
        ...checkProgram(program, !codeOff).begin,
        ...(campaign === "" ? {} : { campaign }),
        ...(chosen === null ? {} : { model: chosen }),
        ...limitsChosen,
        ...(skillsChosen === null ? {} : { skills: skillsChosen }),
      });
      const names = await attachments.upload(chat.id);
      await api.send(chat.id, text, names, false, directive, lab, skill);
      void refresh();
      router.push(`/chat?id=${encodeURIComponent(chat.id)}`);
    } catch (error) {
      if (chat !== null) {
        // A conversation that was never begun is not left in the list, and the files it took go with it
        await api.deleteChat(chat.id).catch(() => undefined);
        attachments.requeue();
      }
      throw error;
    }
  }

  // Where a conversation could not be begun, the skills that were chosen for it and have been taken away since are dropped from
  // the choice, so that the next try is not refused for them again
  async function forgetGoneSkills() {
    if (skillsChosen === null) return;
    const library = await api.skills().catch(() => null);
    if (library === null || vanished(library.skills, skillsChosen).length === 0) return;
    setSkillsChosen(choiceKept(library.skills, choiceStart(library.skills, skillsChosen)));
  }

  // A conversation is begun with what is in the box, or with a command, which is given with the message that begins it
  async function start(command?: Sendable) {
    if (!programReady()) return;
    const text = command ? command.arg.trim() : draft.trim();
    setSending(true);
    setProblem(null);
    try {
      const { directive, skill } = givenAs(command);
      await begin(text, directive, undefined, skill);
    } catch (error) {
      if (command) setDraft(written(command));
      report(error);
      setProblem(problemOf(error));
      await forgetGoneSkills();
      setSending(false);
    }
  }

  // A prompt of an MCP server is written out by the server into the box, and is not sent: the person reads it, and may change it,
  // before they send it. Where the server could not write it out, what was typed is put back in the box.
  async function writePrompt(command: PromptInvocation) {
    setSending(true);
    setProblem(null);
    try {
      const { text } = await api.renderMcpPrompt(command.prompt.server, command.prompt.name, command.values);
      setDraft((was) => withPrompt(was, text));
    } catch (error) {
      setDraft((was) => withPrompt(was, written(command)));
      report(error);
      setProblem(problemOf(error));
    } finally {
      setSending(false);
    }
  }

  // Whether what was typed of the program is enough to begin it, which if it is not is shown, with the focus on the first of it
  function programReady(): boolean {
    const { problems } = checkProgram(program, !codeOff);
    setShown(problems);
    if (Object.keys(problems).length === 0) return true;
    const first = problems.code !== undefined ? PROGRAM_CODE_ID : problems.name === undefined ? PROGRAM_INSTRUCTIONS_ID : PROGRAM_NAME_ID;
    document.getElementById(first)?.focus();

    return false;
  }

  // The same, from the panel that chose who is to work on it, which stays open to be changed where it could not be begun
  async function startLab(agenda: string, lab: LabChoice) {
    setSending(true);
    setProblem(null);
    try {
      await begin(agenda, "lab", lab);
    } catch (error) {
      report(error);
      await forgetGoneSkills();
      setSending(false);
      throw error;
    }
  }

  const model = chosen ?? (server.status === "ready" ? server.settings.model : null);
  const missing = useMissingKeys(model, settings.closed);
  const ready = server.status === "ready" ? server.settings : null;

  // Where code cannot run, what asks for it is not offered, which is known before there is a conversation
  const codeOff = ready !== null && ready.code === "none";
  const noCode = codeOff ? "code is turned off in the settings" : null;
  const directives = ready === null ? null : { code: noCode, plot: noCode };
  // Which skills are on is not known until they are read, which is done as the page opens, so that a command pasted in whole is
  // not taken for a message
  const skillChoices = useSkillChoices(skillsChosen, true);
  const promptChoices = usePromptChoices(null, true);

  // What a custom program may spend, in words, as it will be where nothing was chosen for it
  const spendLimit = "max_cost" in limitsChosen ? (limitsChosen.max_cost ?? null) : (ready?.max_cost ?? null);
  const spending = spendLimit === null ? "Spending limit: none" : `Spending limit: $${formatAmount(spendLimit)}`;

  function run(invocation: Invocation) {
    if ("prompt" in invocation) {
      void writePrompt(invocation);

      return;
    }
    if ("skill" in invocation) {
      void start(invocation);

      return;
    }
    const { name, arg } = invocation;
    if (name === "lab") {
      if (programReady()) setLabbing(arg);
    } else if (isDirective(name)) {
      void start(invocation);
    } else if (name === "budget") {
      setLimiting(true);
    } else if (name === "model") {
      setChoosing(true);
    } else if (name === "skills") {
      setSkilling(true);
    } else if (name === "help") {
      setHelping(true);
    }
  }

  return (
    <>
      <PageHeader className="border-transparent" />
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-[radial-gradient(55%_45%_at_88%_0%,var(--highlight),transparent)] px-4 py-8">
        <div className="mx-auto my-auto flex w-full max-w-3xl flex-col gap-10">
          <div className="flex flex-col gap-6">
            <div className="flex flex-col items-start gap-4">
              <BrandLogo className="mb-3" />
              <h1 className="max-w-2xl text-balance font-serif text-4xl font-medium leading-[1.06] tracking-tight sm:text-5xl">
                What would you like to investigate?
              </h1>
              <p className="max-w-xl text-balance text-base leading-7 text-muted-foreground">
                Ask the lead scientist. When a question needs more expertise, the lead brings in the lab&apos;s team.
              </p>
            </div>

            <ProgramStart
              draft={program}
              onChange={(next) => {
                setProgram(next);
                setShown({});
              }}
              problems={shown}
              disabled={sending}
              spending={spending}
              onSpending={() => setLimiting(true)}
              noCode={codeOff}
              onCode={() => settings.open("code")}
              campaigns={campaigns ?? []}
              campaign={campaign}
              onCampaign={setCampaignChosen}
            />

            <div className="flex flex-col gap-2">
              {problem && <ProblemNotice problem={problem} />}
              {missing.length > 0 && problem?.fix !== "keys" && (
                <Notice
                  tone="muted"
                  icon={KeyRound}
                  action={
                    <Button variant="outline" size="xs" onClick={() => settings.open("keys")} className="shrink-0 text-foreground">
                      Add the key{missing.length === 1 ? "" : "s"}
                    </Button>
                  }
                >
                  {model} needs {missing.join(", ")}, which {missing.length === 1 ? "is" : "are"} not set.
                </Notice>
              )}
              <Composer
                value={draft}
                onValueChange={setDraft}
                onSend={() => void start()}
                disabled={sending}
                holdUp={readiness(attachments.items)}
                files={{
                  items: attachments.items,
                  onAdd: attach,
                  onRemove: (id) => attachments.remove([id]),
                  onRetry: attachments.retry,
                }}
                commands={{ place: "home", turns: 0, answered: 0, directives, skills: skillChoices, prompts: promptChoices, onRun: run }}
                autoFocus
                roomy
                footer={
                  model ? (
                    <span className="flex min-w-0 items-center gap-3">
                      <ModelButton model={model} disabled={sending} onClick={() => setChoosing(true)} />
                      <SkillsButton chosen={skillsChosen} disabled={sending} onClick={() => setSkilling(true)} />
                    </span>
                  ) : undefined
                }
                className="shadow-md"
              />
            </div>
          </div>

          {choosing && model !== null && (
            <ModelDialog
              title="Choose the model"
              description="The lead and the team of this program answer with it. You can change it later, from the program."
              current={model}
              onChoose={async (next) => {
                setChosen(next);
                setChoosing(false);
              }}
              onClose={() => setChoosing(false)}
            />
          )}

          {limiting && ready !== null && (
            <LimitsDialog
              current={{
                max_cost: "max_cost" in limitsChosen ? (limitsChosen.max_cost ?? null) : ready.max_cost,
                max_delegations: limitsChosen.max_delegations ?? ready.chat_limits.max_delegations.default,
                max_rounds: limitsChosen.max_rounds ?? ready.chat_limits.max_rounds.default,
              }}
              limits={ready.chat_limits}
              spent={null}
              begun={false}
              onSave={async (changes) => setLimitsChosen((was) => ({ ...was, ...changes }))}
              onClose={() => setLimiting(false)}
            />
          )}
          {skilling && (
            <SkillsDialog
              kind="choose"
              chosen={skillsChosen}
              onDone={(next) => {
                setSkillsChosen(next);
                setSkilling(false);
              }}
              onClose={() => setSkilling(false)}
            />
          )}
          {labbing !== null && ready !== null && (
            <LabDialog
              agenda={labbing}
              lead={DEFAULT_LEAD_TITLE}
              team={null}
              ceiling={limitsChosen.max_rounds ?? ready.chat_limits.max_rounds.default}
              onStart={startLab}
              onClose={(left) => {
                setLabbing(null);
                if (left !== null && left.trim() !== "") setDraft(written({ name: "lab", arg: left.trim() }));
              }}
            />
          )}
          {helping && <CommandsHelp place="home" onClose={() => setHelping(false)} />}

          <CapabilityCards onChoose={setDraft} />
        </div>
      </div>
    </>
  );
}
