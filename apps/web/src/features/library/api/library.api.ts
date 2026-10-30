import * as contract from "@motionile/api-contract";

import {
  LIBRARY_PAGE_SIZE,
  renderIdSchema,
  shareSlugSchema,
} from "@/features/library/schemas/library.schema";
import type { LibraryFilters } from "@/features/library/types/library.types";
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

export const listLibrary = async (
  filters: LibraryFilters,
  cursor?: string,
  limit: number = LIBRARY_PAGE_SIZE,
) =>
  contract.zLibraryListLibraryResponse.parse(
    (
      await apiClient.get<unknown>("/v1/library", {
        authenticated: true,
        params: contract.zLibraryListLibraryQuery.parse({ ...filters, cursor, limit }),
      })
    ).data,
  );

export const recordShareView = async (slug: string): Promise<void> => {
  await apiClient.post<unknown>(`/v1/share/${shareSlugSchema.parse(slug)}/views`, undefined, {
    skipAuthRefresh: true,
  });
};
