import * as contract from "@motionile/api-contract";
import { z } from "zod";

import { apiClient } from "@/lib/api/client";

export const evaluatedFlags = async () =>
  contract.zEvaluatedFlagsResponse.parse((await apiClient.get<unknown>("/v1/flags")).data);
export const publicSettings = async () =>
  contract.zPublicSettingsResponse.parse(
    (await apiClient.get<unknown>("/v1/settings/public")).data,
  );
export const adminSettings = async () =>
  z
    .array(contract.zSettingResponse)
    .parse((await apiClient.get<unknown>("/v1/admin/settings", { authenticated: true })).data);
export const updateSetting = async (
  key: string,
  input: z.input<typeof contract.zSettingUpdateRequest>,
) =>
  contract.zSettingResponse.parse(
    (
      await apiClient.put<unknown>(
        `/v1/admin/settings/${encodeURIComponent(key)}`,
        contract.zSettingUpdateRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const adminFlags = async () =>
  z
    .array(contract.zFeatureFlagResponse)
    .parse((await apiClient.get<unknown>("/v1/admin/flags", { authenticated: true })).data);
export const updateFlag = async (
  key: string,
  input: z.input<typeof contract.zFeatureFlagUpdateRequest>,
) =>
  contract.zFeatureFlagResponse.parse(
    (
      await apiClient.put<unknown>(
        `/v1/admin/flags/${encodeURIComponent(key)}`,
        contract.zFeatureFlagUpdateRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const createFlag = async (input: z.input<typeof contract.zFeatureFlagWriteRequest>) =>
  contract.zFeatureFlagResponse.parse(
    (
      await apiClient.post<unknown>(
        "/v1/admin/flags",
        contract.zFeatureFlagWriteRequest.parse(input),
        { authenticated: true },
      )
    ).data,
  );
export const deleteFlag = async (key: string, version: number) => {
  await apiClient.delete(`/v1/admin/flags/${encodeURIComponent(key)}`, {
    authenticated: true,
    data: contract.zFeatureFlagDeleteRequest.parse({ version }),
  });
};
