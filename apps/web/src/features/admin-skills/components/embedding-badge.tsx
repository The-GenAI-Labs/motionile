import { Badge } from "@/components/ui/badge";
import {
  embeddingGuidance,
  embeddingLabels,
} from "@/features/admin-skills/schemas/admin-skills.schema";
import type { EmbeddingStatus } from "@/features/admin-skills/types/admin-skills.types";

const variants = {
  ready: "success",
  stale: "outline",
  missing: "destructive",
} as const satisfies Record<EmbeddingStatus, "success" | "outline" | "destructive">;

export function EmbeddingBadge({ status }: { status: EmbeddingStatus }) {
  return (
    <Badge variant={variants[status]} title={embeddingGuidance[status]}>
      Embedding {embeddingLabels[status].toLowerCase()}
    </Badge>
  );
}
