import type { Metadata } from "next";
import { Suspense } from "react";
import { PapersView } from "@/components/papers-view";

export const metadata: Metadata = { title: "Papers · Lumi Virtual Lab" };

export default function PapersPage() {
  return (
    <Suspense>
      <PapersView />
    </Suspense>
  );
}
