import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("flex size-7 shrink-0 items-center justify-center rounded-lg bg-brand text-brand-foreground", className)}
    >
      <FlaskConical className="size-4" strokeWidth={2.25} />
    </span>
  );
}

export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2 font-semibold tracking-tight", className)}>
      <BrandMark />
      Virtual Lab
    </span>
  );
}
