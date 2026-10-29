import type {
  zEmbeddingStatus,
  zReseedView,
  zSkillDetailView,
  zSkillLayer,
  zSkillView,
} from "@motionile/api-contract";
import type { z } from "zod";

export type SystemSkill = z.output<typeof zSkillView>;
export type SystemSkillDetail = z.output<typeof zSkillDetailView>;
export type SkillLayer = z.output<typeof zSkillLayer>;
export type EmbeddingStatus = z.output<typeof zEmbeddingStatus>;
export type ReseedReport = z.output<typeof zReseedView>;

export interface SkillFilters {
  layer?: SkillLayer;
}
