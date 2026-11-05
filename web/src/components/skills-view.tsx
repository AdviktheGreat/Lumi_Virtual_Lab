"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { Given } from "@/components/given";
import { PageFrame } from "@/components/page-frame";
import { PageSection } from "@/components/page-section";
import { useServer } from "@/components/server-provider";
import { SkillsDiscover } from "@/components/skills-discover";
import { SkillsSection } from "@/components/skills-section";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useSkillLibrary } from "@/lib/use-skill-library";
import { useSkills } from "@/lib/use-skills";
import type { SkillsPutIn } from "@/lib/types";

type Tab = "discover" | "yours";

// The skills the lab can be given: those that come with it, to be found and put in, and those that are in use, which are
// turned on and off, read, and deleted, and put in from a Git repository or a folder
export function SkillsView() {
  const { report } = useServer();
  const kept = useSkills(report);
  const offered = useSkillLibrary(report);
  const asked = useSearchParams().get("tab");
  const [tab, setTab] = useState<Tab>(asked === "yours" ? "yours" : "discover");
  const count = kept.skills.kind === "ready" ? kept.skills.value.skills.length : null;

  function putIn(result: SkillsPutIn) {
    kept.set(result);
    offered.reload();
  }

  return (
    <PageFrame
      title="Skills Nexus"
      intro="Written guidance on how to do a kind of work, in the Agent Skills format that Claude Code and Codex read too. The lead is told what each skill is for, and reads one when a task calls for it. Find skills that come with the lab and put in the ones you want, or put in your own."
    >
      <Tabs value={tab} onValueChange={(value) => setTab(value === "yours" ? "yours" : "discover")}>
        <TabsList aria-label="Skills">
          <TabsTrigger value="discover">Discover</TabsTrigger>
          <TabsTrigger value="yours">Your skills{count === null ? "" : ` (${count})`}</TabsTrigger>
        </TabsList>
        <TabsContent value="discover" className="flex flex-col gap-6 pt-3">
          <PageSection
            title="Skills that come with the lab"
            intro="Skills for science, as K-Dense released them. They are not used until you put them in, which copies them into your skills. A conversation is given the skills that are on when you start it."
          >
            <Given given={offered.library} label="Looking at the library" failure="The library could not be looked at." onRetry={offered.reload}>
              {(library) => (
                <Given given={kept.skills} label="Looking at the skills" failure="The skills could not be looked at." onRetry={kept.reload}>
                  {(skills) => (
                    <SkillsDiscover library={library} skills={skills} onPutIn={putIn} onShowYours={() => setTab("yours")} />
                  )}
                </Given>
              )}
            </Given>
          </PageSection>
        </TabsContent>
        <TabsContent value="yours" className="flex flex-col gap-6 pt-3">
          <PageSection
            title="Your skills"
            intro="The skills the lab can use. A conversation is given the skills that are on when you start it, and each adds a line to what every message costs, since the lead is told what it is for."
          >
            <Given given={kept.skills} label="Looking at the skills" failure="The skills could not be looked at." onRetry={kept.reload}>
              {(skills) => (
                <SkillsSection
                  skills={skills}
                  onChanged={(result) => {
                    kept.set(result);
                    offered.reload();
                  }}
                />
              )}
            </Given>
          </PageSection>
        </TabsContent>
      </Tabs>
    </PageFrame>
  );
}
