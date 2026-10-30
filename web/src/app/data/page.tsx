import type { Metadata } from "next";
import { DataView } from "@/components/data-view";

export const metadata: Metadata = { title: "Data · Lumi Virtual Lab" };

export default function DataPage() {
  return <DataView />;
}
