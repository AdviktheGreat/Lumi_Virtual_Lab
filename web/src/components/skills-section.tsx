"use client";

import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { SkillInstall } from "@/components/skill-install";
import { SkillRow } from "@/components/skill-row";
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
import { api } from "@/lib/api";
import { describeError } from "@/lib/errors";
import { disabledWhen, howManyOn, matching, SKILLS_SHOWN } from "@/lib/skills";
import type { SkillInfo, Skills } from "@/lib/types";

// A button that cannot be used right now but keeps the focus it has, which a disabled one would not
const UNAVAILABLE = "aria-disabled:pointer-events-none aria-disabled:opacity-50";

function Folders({ skills }: { skills: Skills }) {
  const lab = skills.folders.find((folder) => folder.source === "workspace");
  const own = skills.folders.find((folder) => folder.source === "user");
  const comes = skills.skills.filter((skill) => skill.source === "builtin").length;

  return (
    <p className="text-xs text-muted-foreground">
      {lab && (
        <>
          The skills you put in here are kept in <code className="break-all">{lab.path}</code>.{" "}
        </>
      )}
      {own && (
        <>
          The lab also reads <code className="break-all">{own.path}</code>
          {own.exists ? "" : ", which is not there yet"}, where other tools that use skills keep theirs. A skill in both is
          read from the lab&apos;s own folder.{" "}
        </>
      )}
      {comes > 0 && (
        <>
          The lab comes with {comes} skill{comes === 1 ? "" : "s"} of its own. {comes === 1 ? "It" : "They"} cannot be
          deleted, but {comes === 1 ? "it" : "they"} can be turned off, and a skill of yours with the same name is read in
          place of one.
        </>
      )}
    </p>
  );
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

// The skills there are: which a new conversation is given, what each tells the lead, and the putting in and deleting of
// them. A conversation is given the skills that are on when it begins, and each skill adds a line to what every message
// costs, since the lead is told what it is for.
export function SkillsSection({ skills, onChanged }: { skills: Skills; onChanged: (skills: Skills) => void }) {
  const { report } = useServer();
  const [query, setQuery] = useState("");
  const [shown, setShown] = useState(SKILLS_SHOWN);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  // What was chosen and is not yet kept, which is shown as it was chosen, so that a box answers at once, until every
  // change has been answered, and then what the server holds is what is shown, whether it kept them or not
  const [chosen, setChosen] = useState<Record<string, boolean>>({});
  // The skills as the server last gave them, which each change is made to. Changes are made one after another, so that
  // two in quick succession do not each start from what was shown before the other.
  const latest = useRef<SkillInfo[]>(skills.skills);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const waiting = useRef(0);
  const [removing, setRemoving] = useState<SkillInfo | null>(null);
  const [asking, setAsking] = useState(false);
  const asker = useRef<HTMLButtonElement | null>(null);
  const search = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (waiting.current === 0) latest.current = skills.skills;
  }, [skills]);

  function turn(names: string[], enabled: boolean) {
    waiting.current += 1;
    setChosen((was) => ({ ...was, ...Object.fromEntries(names.map((name) => [name, enabled])) }));
    queue.current = queue.current.then(async () => {
      try {
        setProblem(null);
        setDone(null);
        const kept = await api.saveSkills(disabledWhen(latest.current, names, enabled));
        latest.current = kept.skills;
        onChanged(kept);
      } catch (error) {
        report(error);
        setProblem(describeError(error));
      } finally {
        waiting.current -= 1;
        if (waiting.current === 0) setChosen({});
      }
    });
  }

  async function remove(skill: SkillInfo) {
    setProblem(null);
    setDone(null);
    try {
      const kept = await api.removeSkill(skill.name);
      latest.current = kept.skills;
      onChanged(kept);
      setDone(`Deleted ${skill.name}.`);
    } catch (error) {
      report(error);
      setProblem(describeError(error));
    }
  }

  const all = skills.skills.map((skill) => (skill.name in chosen ? { ...skill, enabled: chosen[skill.name] } : skill));
  const found = matching(all, query);
  const listed = found.slice(0, shown);
  const searching = query.trim() !== "";
  const allOn = found.every((skill) => skill.enabled);
  const allOff = found.every((skill) => !skill.enabled);

  return (
    <div className="flex flex-col gap-4">
      <SkillInstall
        onPutIn={(result) => {
          setProblem(null);
          setDone(null);
          latest.current = result.skills;
          onChanged(result);
        }}
      />
      {all.length === 0 ? (
        <p className="text-sm text-muted-foreground">There are no skills yet. Put some in above.</p>
      ) : (
        <div className="flex flex-col gap-3">
          <SkillsMeter catalog={skills.catalog} />
          <div className="flex flex-wrap items-center gap-2">
            <p role="status" className="text-sm text-muted-foreground" data-testid="skills-count">
              {howManyOn(all)}
            </p>
            <Button
              variant="outline"
              size="sm"
              className={`ml-auto ${UNAVAILABLE}`}
              aria-disabled={allOn}
              onClick={() => {
                if (!allOn) turn(found.map((skill) => skill.name), true);
              }}
            >
              {searching ? "Turn these on" : "Turn all on"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={UNAVAILABLE}
              aria-disabled={allOff}
              onClick={() => {
                if (!allOff) turn(found.map((skill) => skill.name), false);
              }}
            >
              {searching ? "Turn these off" : "Turn all off"}
            </Button>
          </div>
          <div className="relative">
            <Search aria-hidden className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              ref={search}
              type="search"
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setShown(SKILLS_SHOWN);
              }}
              placeholder="Search the skills"
              aria-label="Search the skills"
              autoComplete="off"
              className="pl-8"
            />
          </div>
          {problem && (
            <p role="alert" className="text-sm text-destructive">
              {problem}
            </p>
          )}
          {done && (
            <p role="status" className="text-xs text-muted-foreground">
              {done}
            </p>
          )}
          {found.length === 0 ? (
            <p role="status" className="text-sm text-muted-foreground">
              No skill has all of those words.
            </p>
          ) : (
            <ul aria-label="Skills" className="flex flex-col gap-2">
              {listed.map((skill) => (
                <SkillRow
                  key={skill.name}
                  skill={skill}
                  onTurn={(enabled) => turn([skill.name], enabled)}
                  onRemove={(button) => {
                    asker.current = button;
                    setRemoving(skill);
                    setAsking(true);
                  }}
                />
              ))}
            </ul>
          )}
          {found.length > listed.length && (
            <Button variant="outline" size="sm" className="self-start" onClick={() => setShown((was) => was + SKILLS_SHOWN)}>
              Show more ({found.length - listed.length} left)
            </Button>
          )}
        </div>
      )}
      <Problems skills={skills} />
      <Folders skills={skills} />
      <AlertDialog open={asking} onOpenChange={setAsking}>
        <AlertDialogContent
          onCloseAutoFocus={(event) => {
            // Nothing opened the question but a button of the list, which is gone when its skill was deleted
            event.preventDefault();
            (asker.current?.isConnected ? asker.current : search.current)?.focus();
          }}
        >
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
