import type { Metadata } from "next";
import { Suspense } from "react";
import { BenchmarksView } from "@/components/benchmarks-view";

export const metadata: Metadata = { title: "Benchmarks · Lumi Virtual Lab" };

export default function BenchmarksPage() {
  return (
    <Suspense>
      <BenchmarksView />
    </Suspense>
  );
}
