import * as contract from "@motionile/api-contract";

import { renderIdSchema } from "@/features/library/schemas/library.schema";
import { apiClient } from "@/lib/api/client";

export const getMediaSession = async () =>
  contract.zMediaGetSessionResponse.parse(
    (await apiClient.get<unknown>("/v1/media/session", { authenticated: true })).data,
  );

export const getRender = async (renderId: string) =>
  contract.zRendersGetRenderResponse.parse(
    (
      await apiClient.get<unknown>(`/v1/renders/${renderIdSchema.parse(renderId)}`, {
        authenticated: true,
      })
    ).data,
  );

export const listRenditions = async (renderId: string) =>
  contract.zRendersListRenditionsResponse.parse(
    (
      await apiClient.get<unknown>(`/v1/renders/${renderIdSchema.parse(renderId)}/renditions`, {
        authenticated: true,
      })
    ).data,
  );
