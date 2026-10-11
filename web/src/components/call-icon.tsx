import { MessageSquareText, Search, Terminal, Users, Wrench } from "lucide-react";

// What marks a call to the tool of this name
export function CallIcon({ name, className }: { name: string; className?: string }) {
  switch (name) {
    case "run_code":
      return <Terminal className={className} aria-hidden />;
    case "find_resources":
      return <Search className={className} aria-hidden />;
    case "convene_team":
      return <Users className={className} aria-hidden />;
    case "consult":
      return <MessageSquareText className={className} aria-hidden />;
    default:
      return <Wrench className={className} aria-hidden />;
  }
}
