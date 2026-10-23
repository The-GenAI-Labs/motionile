import type { zVoiceSyncView } from "@motionile/api-contract";
import type { z } from "zod";

import type { VoiceStatus } from "@/features/voices/types/voices.types";

export type { AdminVoice } from "@/features/voices/types/voices.types";

export type VoiceSyncResult = z.output<typeof zVoiceSyncView>;

export interface AdminVoiceFilters {
  status?: VoiceStatus;
  language?: string;
}

export interface AdminVoiceUpdateInput {
  name?: string;
  language?: string;
  tags?: string[];
  status?: "ready" | "disabled";
}
