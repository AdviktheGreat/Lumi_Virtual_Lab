import type { Metadata } from "next";
import { Suspense } from "react";
import { ProjectsView } from "@/components/projects-view";

export const metadata: Metadata = { title: "Projects · Lumi Virtual Lab" };

export default function ProjectsPage() {
  return (
    <Suspense>
      <ProjectsView />
    </Suspense>
  );
}
