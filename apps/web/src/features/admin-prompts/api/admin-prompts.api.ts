import * as contract from "@motionile/api-contract";

import {
  EVAL_RUNS_PAGE_SIZE,
  promptKeySchema,
  PROMPTS_PAGE_SIZE,
  versionNumberSchema,
} from "@/features/admin-prompts/schemas/admin-prompts.schema";
import type {
  DiffRequest,
  DraftInput,
  EvalRunFilters,
  StartEvalRunInput,
} from "@/features/admin-prompts/types/admin-prompts.types";
import { apiClient } from "@/lib/api/client";

const BASE = "/v1/admin/prompts";

const templatePath = (key: string): string =>
  `${BASE}/templates/${encodeURIComponent(promptKeySchema.parse(key))}`;

export const listPromptTemplates = async () =>
  contract.zAdminPromptsListPromptTemplatesResponse.parse(
    (await apiClient.get<unknown>(`${BASE}/templates`, { authenticated: true })).data,
  );

export const listPromptVersions = async (key: string, cursor?: string) =>
  contract.zAdminPromptsListPromptVersionsResponse.parse(
    (
      await apiClient.get<unknown>(`${templatePath(key)}/versions`, {
        authenticated: true,
        params: contract.zAdminPromptsListPromptVersionsQuery.parse({
          cursor,
          limit: PROMPTS_PAGE_SIZE,
        }),
      })
    ).data,
  );

export const diffPromptVersions = async ({ key, from, to }: DiffRequest) =>
  contract.zAdminPromptsDiffPromptVersionsResponse.parse(
    (
      await apiClient.get<unknown>(`${templatePath(key)}/diff`, {
        authenticated: true,
        params: contract.zAdminPromptsDiffPromptVersionsQuery.parse({ from, to }),
      })
    ).data,
  );

export const createPromptDraft = async (key: string, input: DraftInput) =>
  contract.zAdminPromptsCreatePromptDraftResponse.parse(
    (
      await apiClient.post<unknown>(
        `${templatePath(key)}/versions`,
        contract.zAdminPromptsCreatePromptDraftBody.parse(input),
        { authenticated: true },
      )
    ).data,
  );

export const activatePromptVersion = async (key: string, version: number) =>
  contract.zAdminPromptsActivatePromptVersionResponse.parse(
    (
      await apiClient.post<unknown>(
        `${templatePath(key)}/versions/${String(versionNumberSchema.parse(version))}/activate`,
        undefined,
        { authenticated: true },
      )
    ).data,
  );

export const rollbackPromptTemplate = async (key: string) =>
  contract.zAdminPromptsRollbackPromptTemplateResponse.parse(
    (
      await apiClient.post<unknown>(`${templatePath(key)}/rollback`, undefined, {
        authenticated: true,
      })
    ).data,
  );

export const listEvalRuns = async (filters: EvalRunFilters, cursor?: string) =>
  contract.zAdminPromptsListEvalRunsResponse.parse(
    (
      await apiClient.get<unknown>(`${BASE}/eval-runs`, {
        authenticated: true,
        params: contract.zAdminPromptsListEvalRunsQuery.parse({
          ...filters,
          cursor,
          limit: EVAL_RUNS_PAGE_SIZE,
        }),
      })
    ).data,
  );

export const startEvalRun = async (input: StartEvalRunInput) =>
  contract.zAdminPromptsStartEvalRunResponse.parse(
    (
      await apiClient.post<unknown>(
        `${BASE}/eval-runs`,
        contract.zAdminPromptsStartEvalRunBody.parse(input),
        { authenticated: true },
      )
    ).data,
  );
