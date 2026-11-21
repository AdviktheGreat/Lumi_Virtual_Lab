import { Badge } from "@/components/ui/badge";

// What a function written from a paper is labelled wherever it is shown, so that it is not taken for the authors' code
export function ReimplementationLabel({ label }: { label: string }) {
  return (
    <Badge variant="outline" className="h-auto whitespace-normal border-warning/60 bg-warning/15 text-left" data-testid="reimplementation-label">
      {label}
    </Badge>
  );
}
