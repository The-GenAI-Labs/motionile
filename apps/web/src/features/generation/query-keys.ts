import type { JobFilters } from "@/features/generation/types/generation.types";

export const generationKeys = {
  all: ["generation"] as const,
  styles: () => [...generationKeys.all, "styles"] as const,
  estimate: (signature: string) => [...generationKeys.all, "estimate", signature] as const,
  jobs: () => [...generationKeys.all, "jobs"] as const,
  list: (filters: JobFilters) => [...generationKeys.jobs(), "list", filters] as const,
  job: (jobId: string) => [...generationKeys.jobs(), "detail", jobId] as const,
  events: (jobId: string) => [...generationKeys.jobs(), "events", jobId] as const,
  storyboard: (jobId: string) => [...generationKeys.jobs(), "storyboard", jobId] as const,
  topicRef: (reference: string) => [...generationKeys.all, "topic-ref", reference] as const,
};
