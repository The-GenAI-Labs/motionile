import * as contract from "@motionile/api-contract";

import type {
  AdminVoiceFilters,
  AdminVoiceUpdateInput,
} from "@/features/admin-voices/types/admin-voices.types";
import { voiceIdSchema } from "@/features/voices/schemas/voices.schema";
import { apiClient } from "@/lib/api/client";

export const ADMIN_VOICES_PAGE_SIZE = 25;
export const VOICE_SYNC_TIMEOUT_MS = 60_000;

const BASE = "/v1/admin/voices";

export const listAdminVoices = async (filters: AdminVoiceFilters, cursor?: string) =>
  contract.zAdminVoicesListBuiltinVoicesResponse.parse(
    (
      await apiClient.get<unknown>(BASE, {
        authenticated: true,
        params: contract.zAdminVoicesListBuiltinVoicesQuery.parse({
          ...filters,
          cursor,
          limit: ADMIN_VOICES_PAGE_SIZE,
        }),
      })
    ).data,
  );

export const syncVoices = async () =>
  contract.zAdminVoicesSyncBuiltinVoicesResponse.parse(
    (
      await apiClient.post<unknown>(BASE + "/sync", undefined, {
        authenticated: true,
        timeout: VOICE_SYNC_TIMEOUT_MS,
      })
    ).data,
  );

export const updateAdminVoice = async (voiceId: string, input: AdminVoiceUpdateInput) =>
  contract.zAdminVoicesUpdateBuiltinVoiceResponse.parse(
    (
      await apiClient.patch<unknown>(
        `${BASE}/${voiceIdSchema.parse(voiceId)}`,
        contract.zAdminVoicesUpdateBuiltinVoiceBody.parse(input),
        { authenticated: true, timeout: VOICE_SYNC_TIMEOUT_MS },
      )
    ).data,
  );

export const regenerateVoicePreview = async (voiceId: string) =>
  contract.zAdminVoicesRegenerateBuiltinVoicePreviewResponse.parse(
    (
      await apiClient.post<unknown>(`${BASE}/${voiceIdSchema.parse(voiceId)}/preview`, undefined, {
        authenticated: true,
        timeout: VOICE_SYNC_TIMEOUT_MS,
      })
    ).data,
  );
