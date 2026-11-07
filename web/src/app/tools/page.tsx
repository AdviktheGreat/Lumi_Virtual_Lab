import type { Metadata } from "next";
import { ToolsView } from "@/components/tools-view";

export const metadata: Metadata = { title: "Tools Nexus · Lumi Virtual Lab" };

export default function ToolsPage() {
  return <ToolsView />;
}
