"use client";

import { useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { PutInResult } from "@/components/skill-put-in-result";
import { SkillCard } from "@/components/skill-card";
import { SkillDetail } from "@/components/skill-detail";
import { SkillsMeter } from "@/components/skills-meter";
import { useServer } from "@/components/server-provider";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import {
  catalogAdded,
  HUB_SHOWN,
  HUB_SOURCES,
  hubCounts,
  hubSaid,
  hubSkills,
  licenseWarnings,
  matchingHub,
  tokensSaid,
  type HubSkill,
  type HubSource,
} from "@/lib/skills";
import type { LibraryCategory, SkillLibrary, Skills, SkillsPutIn } from "@/lib/types";
import { useSkillSwitches } from "@/lib/use-skill-switches";
import { cn } from "@/lib/utils";

// The categories under the group each is in, in the order the library lists them
function groupsOf(categories: LibraryCategory[]): { group: string; categories: LibraryCategory[] }[] {
  const groups: { group: string; categories: LibraryCategory[] }[] = [];
  for (const category of categories) {
    const found = groups.find((each) => each.group === category.group);
    if (found) found.categories.push(category);
    else groups.push({ group: category.group, categories: [category] });
  }

  return groups;
}

// What is said where no skill is shown: that there are none of a kind, where that is what was asked for, or that none matches
function emptySaid(skills: number, source: HubSource | "", searched: boolean): string {
  if (skills === 0) return "There are no skills yet. Add some.";
  if (searched || source === "") return "No skill matches those words.";
  if (source === "mine") return "You have not added any skills of your own yet.";
  if (source === "builtin") return "The lab has no skills built in.";

  return "The library has no skills.";
}

function Problems({ skills }: { skills: Skills }) {
  if (skills.problems.length === 0) return null;

  return (
    <details className="text-xs" data-testid="skill-problems">
      <summary className="cursor-pointer text-muted-foreground">
        {skills.problems.length} SKILL.md file{skills.problems.length === 1 ? "" : "s"} could not be used
      </summary>
      <ul aria-label="Skills that could not be used" className="mt-1.5 flex flex-col gap-1.5">
        {skills.problems.map((problem) => (
          <li key={problem.path} className="break-words">
            <code className="break-all">{problem.path}</code>: {problem.message}
          </li>
        ))}
      </ul>
    </details>
  );
}

// The skills of the lab and of its library as cards, found by their words, where they come from, and their category. A
// skill the lab has is turned on or off, and one it does not have is added. What is shown can be added, turned on, or
// turned off together. A conversation is given the skills that are on when it begins, and each adds a line to what every
// message costs, since the lead is told what it is for.
export function SkillsHub({
  skills,
  library,
  onChanged,
  onPutIn,
}: {
  skills: Skills;
  library: SkillLibrary;
  onChanged: (skills: Skills) => void;
  onPutIn: (result: SkillsPutIn) => void;
}) {
  const { report } = useServer();
  const switches = useSkillSwitches(skills, onChanged, report);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<HubSource | "">("");
  const [category, setCategory] = useState("");
  const [shown, setShown] = useState(HUB_SHOWN);
  const [openName, setOpenName] = useState<string | null>(null);
  const [adding, setAdding] = useState<string[] | null>(null);
  const [working, setWorking] = useState(false);
  const [putProblem, setPutProblem] = useState<string | null>(null);
  const [result, setResult] = useState<SkillsPutIn | null>(null);
  const [removing, setRemoving] = useState<HubSkill | null>(null);
  const [asking, setAsking] = useState(false);
  const [askingToAdd, setAskingToAdd] = useState(false);
  // The button a question was asked from, and the card that was opened, which are given the focus back unless they have gone
  const asker = useRef<HTMLElement | null>(null);
  const opener = useRef<HTMLElement | null>(null);
  const search = useRef<HTMLInputElement | null>(null);
  const groups = useMemo(() => groupsOf(library.categories), [library.categories]);
  const all = useMemo(() => hubSkills(switches.skills, library.skills), [switches.skills, library.skills]);
  const counts = hubCounts(all);

  const found = matchingHub(all, query, source, category);
  const listed = found.slice(0, shown);
  const filtering = query.trim() !== "" || source !== "" || category !== "";
  const toAdd = found.filter((skill) => skill.info === null);
  const toTurnOn = found.filter((skill) => skill.info !== null && !skill.info.enabled);
  const toTurnOff = found.filter((skill) => skill.info?.enabled);
  const open = openName === null ? null : (all.find((skill) => skill.name === openName) ?? null);
  const adds = all.filter((skill) => adding?.includes(skill.name) && skill.library !== null);
  const addedLibrary = adds.flatMap((skill) => (skill.library === null ? [] : [skill.library]));
  const warnings = licenseWarnings(addedLibrary);
  const problem = putProblem ?? switches.problem;
  const these = filtering ? "these" : "all";

  function showFirst() {
    setShown(HUB_SHOWN);
  }

  function askToAdd(names: string[], from: HTMLElement | null) {
    asker.current = from;
    setPutProblem(null);
    setAdding(names);
    setAskingToAdd(true);
  }

  async function putIn(names: string[]) {
    setWorking(true);
    setPutProblem(null);
    setResult(null);
    switches.clear();
    try {
      const done = await api.putInLibrarySkills(names);
      setResult(done);
      onPutIn(done);
    } catch (error) {
      report(error);
      setPutProblem(describeError(error));
    } finally {
      setWorking(false);
    }
  }

  async function remove(skill: HubSkill) {
    if (skill.info === null) return;
    setResult(null);
    setPutProblem(null);
    if (await switches.remove(skill.info)) setOpenName(null);
  }

  function focusOn(from: HTMLElement | null, event: Event) {
    event.preventDefault();
    (from?.isConnected ? from : search.current)?.focus();
  }

  function pickFocus(event: Event) {
    focusOn(asker.current, event);
  }

  const chips: { value: HubSource | ""; label: string; count: number }[] = [
    { value: "", label: "All", count: counts.all },
    ...HUB_SOURCES.map((each) => ({ value: each.source, label: each.label, count: counts[each.source] })),
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="relative">
        <Search aria-hidden className="pointer-events-none absolute left-4 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          ref={search}
          type="search"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            showFirst();
          }}
          placeholder="Search all skills…"
          aria-label="Search all skills"
          autoComplete="off"
          className="h-11 rounded-full bg-card pl-10 text-sm [&::-webkit-search-cancel-button]:appearance-none"
        />
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div role="group" aria-label="Where skills come from" className="flex flex-wrap items-center gap-2">
          <span className="mr-1 text-sm text-muted-foreground">Source</span>
          {chips.map((chip) => (
            <button
              key={chip.value}
              type="button"
              aria-pressed={source === chip.value}
              onClick={() => {
                setSource(chip.value);
                showFirst();
              }}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-sm outline-none transition-colors focus-visible:ring-3 focus-visible:ring-ring/40",
                source === chip.value
                  ? "border-foreground/25 bg-secondary font-medium text-foreground"
                  : "border-border bg-card text-muted-foreground hover:border-ring/60 hover:text-foreground",
              )}
            >
              {chip.label}
              <span className="text-xs tabular-nums text-muted-foreground">{chip.count}</span>
            </button>
          ))}
        </div>
        <div className="sm:ml-auto sm:w-60">
          <NativeSelect
            value={category}
            onChange={(event) => {
              setCategory(event.target.value);
              showFirst();
            }}
            aria-label="Category"
            className="h-8 rounded-full bg-card pl-3.5"
          >
            <option value="">All categories</option>
            {groups.map(({ group, categories }) => (
              <optgroup key={group} label={group}>
                {categories.map((each) => (
                  <option key={each.name} value={each.name}>
                    {each.name} ({each.count})
                  </option>
                ))}
              </optgroup>
            ))}
          </NativeSelect>
        </div>
      </div>
      <SkillsMeter catalog={skills.catalog} />
      <div className="flex flex-wrap items-center gap-2">
        <p role="status" className="text-sm text-muted-foreground" data-testid="skills-count">
          {hubSaid(found, all.length)}
        </p>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {toTurnOn.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => switches.turn(toTurnOn.map((skill) => skill.name), true)}
            >
              Turn {these} on
            </Button>
          )}
          {toTurnOff.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => switches.turn(toTurnOff.map((skill) => skill.name), false)}
            >
              Turn {these} off
            </Button>
          )}
          {toAdd.length > 0 && (
            <Button
              size="sm"
              disabled={working}
              onClick={(event) =>
                askToAdd(
                  toAdd.map((skill) => skill.name),
                  event.currentTarget,
                )
              }
            >
              {working ? "Adding…" : `Add ${these} ${toAdd.length}`}
            </Button>
          )}
        </div>
      </div>
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      {result !== null && <PutInResult result={result} />}
      {switches.done && (
        <p role="status" className="text-xs text-muted-foreground">
          {switches.done}
        </p>
      )}
      {found.length === 0 ? (
        <p role="status" className="py-8 text-center text-sm text-muted-foreground">
          {emptySaid(all.length, source, query.trim() !== "" || category !== "")}
        </p>
      ) : (
        <ul aria-label="Skills" className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {listed.map((skill) => (
            <SkillCard
              key={skill.name}
              skill={skill}
              onOpen={(button) => {
                opener.current = button;
                setOpenName(skill.name);
              }}
              onTurn={(enabled) => switches.turn([skill.name], enabled)}
              onAdd={(button) => askToAdd([skill.name], button)}
            />
          ))}
        </ul>
      )}
      {found.length > listed.length && (
        <Button variant="outline" size="sm" className="self-center" onClick={() => setShown((was) => was + HUB_SHOWN)}>
          Show more ({found.length - listed.length} left)
        </Button>
      )}
      <Problems skills={skills} />
      <SkillDetail
        skill={open}
        onClose={() => setOpenName(null)}
        onCloseAutoFocus={(event) => focusOn(opener.current, event)}
        onTurn={(enabled) => {
          if (open !== null) switches.turn([open.name], enabled);
        }}
        onAdd={(button) => {
          if (open !== null) askToAdd([open.name], button);
        }}
        onRemove={(button) => {
          if (open === null) return;
          asker.current = button;
          setRemoving(open);
          setAsking(true);
        }}
      />
      <AlertDialog open={askingToAdd} onOpenChange={setAskingToAdd}>
        <AlertDialogContent onCloseAutoFocus={pickFocus}>
          <AlertDialogHeader>
            <AlertDialogTitle>
              Add {addedLibrary.length === 1 ? addedLibrary[0].name : `${addedLibrary.length} skills`}?
            </AlertDialogTitle>
            <AlertDialogDescription>
              A skill is instructions that the lead follows, and it may come with scripts that code can run in a
              conversation. {addedLibrary.length === 1 ? "It is" : "These are"} copied into your skills, where{" "}
              {addedLibrary.length === 1 ? "it is" : "they are"} on like any other. {addedLibrary.length === 1 ? "It adds" : "Together they add"}{" "}
              {tokensSaid(catalogAdded(addedLibrary))} to the start of every conversation, and you can turn{" "}
              {addedLibrary.length === 1 ? "it" : "them"} off, or delete {addedLibrary.length === 1 ? "it" : "them"}, here.
            </AlertDialogDescription>
          </AlertDialogHeader>
          {warnings.length > 0 && (
            <ul aria-label="About their licenses" className="flex flex-col gap-1 text-sm">
              {warnings.map((warning) => (
                <li key={warning} className="break-words">
                  {warning}
                </li>
              ))}
            </ul>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void putIn(addedLibrary.map((skill) => skill.name))}>Add</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent onCloseAutoFocus={pickFocus}>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {removing?.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Its folder and everything in it are deleted from the lab&apos;s skills. A conversation that was given it
              goes on without it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (removing !== null) void remove(removing);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
