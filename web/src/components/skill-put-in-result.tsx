"use client";

import { filesLeftOut, putInSaid } from "@/lib/skills";
import type { SkillsPutIn } from "@/lib/types";

// What putting in skills did: how many were put in and how many were left, which files were too many or too big to copy,
// and which skills were left and why
export function PutInResult({ result }: { result: SkillsPutIn }) {
  const left = filesLeftOut(result);

  return (
    <div role="status" className="flex flex-col gap-2 text-sm" data-testid="skills-put-in">
      <p>{putInSaid(result)}</p>
      {left.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Some files were too many or too big to copy: {left.map((skill) => `${skill.left_out} of ${skill.name}`).join(", ")}.
        </p>
      )}
      {result.skipped.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted-foreground">Which were left, and why</summary>
          <ul aria-label="Skills that were left" className="mt-1.5 flex flex-col gap-1">
            {result.skipped.map((skill, index) => (
              <li key={`${skill.name}-${index}`} className="break-words">
                <code>{skill.name}</code>: {skill.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
