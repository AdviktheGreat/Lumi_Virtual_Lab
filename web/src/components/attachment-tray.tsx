import { CircleAlert, FileText, Loader2, RotateCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { TrayItem } from "@/lib/attachments";
import { formatBytes } from "@/lib/files";
import { cn } from "@/lib/utils";

function Chip({
  item,
  disabled,
  onRemove,
  onRetry,
}: {
  item: TrayItem;
  disabled: boolean;
  onRemove: (id: number) => void;
  onRetry: (id: number) => void;
}) {
  const name = item.attachment?.name ?? item.file.name;
  const failed = item.status === "failed";

  return (
    <li
      data-testid="attachment"
      data-status={item.status}
      className={cn(
        "relative flex max-w-full items-center gap-1.5 overflow-hidden rounded-lg border bg-background py-1 pl-2 pr-1 text-xs",
        failed ? "border-destructive/40 text-destructive" : "border-border text-foreground",
      )}
    >
      {failed ? (
        <CircleAlert className="size-3.5 shrink-0" aria-hidden />
      ) : item.status === "uploading" ? (
        <Loader2 className="size-3.5 shrink-0 animate-spin text-muted-foreground" aria-hidden />
      ) : (
        <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      )}
      <span className="min-w-0 max-w-48 truncate" title={name}>
        {name}
      </span>
      <span className="shrink-0 text-muted-foreground">{formatBytes(item.file.size)}</span>
      {failed && item.error && (
        <span className="min-w-0 max-w-64 truncate" title={item.error}>
          {item.error}
        </span>
      )}
      {failed && item.retryable && (
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label={`Retry ${name}`}
          disabled={disabled}
          onClick={() => onRetry(item.id)}
        >
          <RotateCw />
        </Button>
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon-xs"
        aria-label={`Remove ${name}`}
        disabled={disabled}
        onClick={() => onRemove(item.id)}
      >
        <X />
      </Button>
      {item.status === "uploading" && (
        <span
          role="progressbar"
          aria-label={`Uploading ${name}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(item.progress * 100)}
          className="absolute inset-x-0 bottom-0 h-0.5 bg-muted"
        >
          <span className="block h-full bg-brand transition-[width]" style={{ width: `${item.progress * 100}%` }} />
        </span>
      )}
    </li>
  );
}

// The files chosen to go with the next message, and how each is getting on
export function AttachmentTray({
  items,
  disabled = false,
  onRemove,
  onRetry,
}: {
  items: TrayItem[];
  disabled?: boolean;
  onRemove: (id: number) => void;
  onRetry: (id: number) => void;
}) {
  if (items.length === 0) return null;

  return (
    <ul aria-label="Attached files" className="flex flex-wrap gap-1.5 px-1 pt-0.5" data-testid="attachment-tray">
      {items.map((item) => (
        <Chip key={item.id} item={item} disabled={disabled} onRemove={onRemove} onRetry={onRetry} />
      ))}
    </ul>
  );
}
