import type { Metadata, Viewport } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource-variable/newsreader";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { ServerGate } from "@/components/server-gate";
import { ServerProvider } from "@/components/server-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { themeScript } from "@/lib/theme-script";

export const metadata: Metadata = {
  title: "Lumi Virtual Lab",
  description: "Talk to the head of a lab of scientists, who brings in the team when a question needs it.",
};

export const viewport: Viewport = {
  colorScheme: "light dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // The theme is set on the page before it is shown, which React was not there to do
    <html lang="en" className="h-full" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="h-full">
        <TooltipProvider delayDuration={300}>
          <ServerProvider>
            <ServerGate>
              <AppShell>{children}</AppShell>
            </ServerGate>
          </ServerProvider>
        </TooltipProvider>
      </body>
    </html>
  );
}
