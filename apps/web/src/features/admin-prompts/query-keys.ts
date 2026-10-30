import type {
  DiffRequest,
  EvalRunFilters,
} from "@/features/admin-prompts/types/admin-prompts.types";

export const adminPromptsKeys = {
  all: ["admin-prompts"] as const,
  templates: () => [...adminPromptsKeys.all, "templates"] as const,
  versions: (key: string) => [...adminPromptsKeys.all, "versions", key] as const,
  diff: (request: DiffRequest | null) => [...adminPromptsKeys.all, "diff", request] as const,
  evalRuns: () => [...adminPromptsKeys.all, "eval-runs"] as const,
  evalRunList: (filters: EvalRunFilters) => [...adminPromptsKeys.evalRuns(), filters] as const,
};
