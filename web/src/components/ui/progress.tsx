import * as React from "react"
import { cn } from "cn"

// How far something has got, from 0 to 1, or moving without a place when that cannot be told
function Progress({
  value,
  className,
  ...props
}: Omit<React.ComponentProps<"div">, "children"> & { value: number | null }) {
  return (
    <div
      role="progressbar"
      data-slot="progress"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value === null ? undefined : Math.round(value * 100)}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
      {...props}
    >
      <div
        className={cn("h-full rounded-full bg-primary transition-[width] duration-300", value === null && "w-full animate-pulse opacity-50 motion-reduce:animate-none")}
        style={value === null ? undefined : { width: `${value * 100}%` }}
      />
    </div>
  )
}

export { Progress }
