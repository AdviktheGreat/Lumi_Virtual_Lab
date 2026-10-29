import { cn } from "@/lib/utils";

// A flask with a leaf in it, drawn in the colour it is given
export function BrandGlyph({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn("size-4", className)}
    >
      <path d="M9 3h6" />
      <path d="M10 3v5.2L4.6 18a2 2 0 0 0 1.75 3h11.3a2 2 0 0 0 1.75-3L14 8.2V3" />
      <path d="M12 18.5c-.2-2.3 1.2-3.9 3.4-4.1.2 2.3-1.1 4-3.4 4.1Z" fill="currentColor" strokeWidth={1.25} />
    </svg>
  );
}

export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("flex size-8 shrink-0 items-center justify-center rounded-xl bg-brand text-brand-foreground", className)}
    >
      <BrandGlyph />
    </span>
  );
}

export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5 font-serif text-lg font-semibold tracking-tight", className)}>
      <BrandMark />
      Virtual Lab
    </span>
  );
}
