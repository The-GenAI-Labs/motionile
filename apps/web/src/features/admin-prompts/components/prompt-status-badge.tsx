import { Badge } from "@/components/ui/badge";
import { titleCase } from "@/lib/utils/format";

const POSITIVE = new Set(["passed", "finished", "active"]);
const NEGATIVE = new Set(["failed", "errored"]);

export function PromptStatusBadge({ status }: { status: string | null }) {
  if (status === null) {
    return <Badge variant="outline">No runs</Badge>;
  }
  const variant = POSITIVE.has(status)
    ? "success"
    : NEGATIVE.has(status)
      ? "destructive"
      : "outline";
  return <Badge variant={variant}>{titleCase(status)}</Badge>;
}
