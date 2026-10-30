import { cn } from "@/lib/utils";

// The lab's mark, a cell with its nucleus, and its logo, which has the name beside it. They are the Lumigenic files, with
// their own colours: a green cell, and a nucleus that is the paper colour, which reads as a pale centre on a dark page and as
// an opening in the cell on a light one.
export function BrandMark({ className }: { className?: string }) {
  return (
    // A file of the app's own, so there is nothing for next/image to optimize
    // eslint-disable-next-line @next/next/no-img-element
    <img src="/brand/lumigenic-mark.svg" alt="" aria-hidden className={cn("size-9 shrink-0 object-contain", className)} />
  );
}

export function BrandLogo({ className }: { className?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src="/brand/lumigenic-logo.svg" alt="Lumigenic" className={cn("h-20 w-auto", className)} />
  );
}

export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5 font-serif text-lg font-medium tracking-tight", className)}>
      <BrandMark className="size-8" />
      Virtual Lab
    </span>
  );
}
