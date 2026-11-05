import type { Metadata } from "next";
import { Suspense } from "react";
import { SkillsView } from "@/components/skills-view";

export const metadata: Metadata = { title: "Skills Nexus · Lumi Virtual Lab" };

export default function SkillsPage() {
  return (
    <Suspense>
      <SkillsView />
    </Suspense>
  );
}
