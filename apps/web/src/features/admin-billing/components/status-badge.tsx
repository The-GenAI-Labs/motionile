import { Badge } from "@/components/ui/badge";
import { titleCase } from "@/lib/utils/format";

const POSITIVE_STATUSES = new Set(["captured", "paid", "processed", "completed", "active"]);

const NEGATIVE_STATUSES = new Set(["failed", "halted"]);

type BadgeVariant = "success" | "destructive" | "outline";

export const statusVariant = (status: string): BadgeVariant => {
  if (POSITIVE_STATUSES.has(status)) {
    return "success";
  }
  if (NEGATIVE_STATUSES.has(status)) {
    return "destructive";
  }
  return "outline";
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={statusVariant(status)}>{titleCase(status)}</Badge>;
}
