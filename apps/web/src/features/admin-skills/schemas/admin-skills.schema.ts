import { z } from "zod";

import type { EmbeddingStatus } from "@/features/admin-skills/types/admin-skills.types";

export const SKILLS_PAGE_SIZE = 25;

export const skillSlugSchema = z
  .string()
  .max(64)
  .regex(/^[a-z0-9]+(-[a-z0-9]+)*$/);

export const embeddingLabels = {
  ready: "Ready",
  stale: "Stale",
  missing: "Missing",
} as const satisfies Record<EmbeddingStatus, string>;

export const embeddingGuidance = {
  ready: "The description is embedded with the configured model.",
  stale: "The description was embedded with another model. Reseed to embed it again.",
  missing: "The description has no embedding yet. Reseed to create it.",
} as const satisfies Record<EmbeddingStatus, string>;

export const CHECKSUM_PREFIX_LENGTH = 12;

export const checksumPrefix = (checksum: string): string =>
  checksum.slice(0, CHECKSUM_PREFIX_LENGTH);
