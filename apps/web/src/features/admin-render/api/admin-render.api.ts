import * as contract from "@motionile/api-contract";
import { z } from "zod";

import { env } from "@/config/env";
import { type GoldenRequest, goldenRequestSchema } from "@/features/admin-render/multipart";
import {
  isTerminalStatus,
  type RenderProgressEvent,
  renderProgressEventSchema,
} from "@/features/admin-render/schemas/admin-render.schema";
import { createSseParser } from "@/features/admin-render/sse";
import { ApiError } from "@/lib/api/api-error";
import { apiClient } from "@/lib/api/client";
import { refreshSession } from "@/lib/auth/refresh";

export const RENDER_UPLOAD_TIMEOUT_MS = 300_000;

const BASE = "/v1/admin/render/testbed";

const renderId = (value: string): string => z.uuid().parse(value);

export const createTestbedRender = async (body: FormData) =>
  contract.zAdminRenderTestbedCreateTestbedRenderResponse.parse(
    (
      await apiClient.post<unknown>(BASE, body, {
        authenticated: true,
        timeout: RENDER_UPLOAD_TIMEOUT_MS,
        headers: { "Content-Type": "multipart/form-data" },
      })
    ).data,
  );

export const listGoldenCompositions = async () =>
  contract.zAdminRenderTestbedListGoldenCompositionsResponse.parse(
    (await apiClient.get<unknown>(`${BASE}/golden`, { authenticated: true })).data,
  );

export const createGoldenRender = async (name: string, request: GoldenRequest) =>
  contract.zAdminRenderTestbedCreateGoldenRenderResponse.parse(
    (
      await apiClient.post<unknown>(
        `${BASE}/golden/${contract.zGoldenName.parse(name)}`,
        goldenRequestSchema.parse(request),
        { authenticated: true },
      )
    ).data,
  );

export const listBedMusicTracks = async () =>
  contract.zAdminRenderTestbedListTestbedMusicTracksResponse.parse(
    (await apiClient.get<unknown>(`${BASE}/music-tracks`, { authenticated: true })).data,
  );

export const getTestbedRender = async (id: string) =>
  contract.zAdminRenderTestbedGetTestbedRenderResponse.parse(
    (await apiClient.get<unknown>(`${BASE}/${renderId(id)}`, { authenticated: true })).data,
  );

export const cancelTestbedRender = async (id: string) =>
  contract.zAdminRenderTestbedCancelTestbedRenderResponse.parse(
    (
      await apiClient.post<unknown>(`${BASE}/${renderId(id)}/cancel`, undefined, {
        authenticated: true,
      })
    ).data,
  );

export interface StreamHandlers {
  signal: AbortSignal;
  onOpen: () => void;
  onEvent: (event: RenderProgressEvent) => void;
  fetchImpl?: typeof fetch;
}

const EVENT_NAMES = new Set(["snapshot", "progress"]);

const connect = async (
  url: string,
  { signal, fetchImpl = fetch }: Pick<StreamHandlers, "signal" | "fetchImpl">,
): Promise<Response> => {
  const open = () =>
    fetchImpl(url, {
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers: { Accept: "text/event-stream" },
      signal,
    });
  const first = await open();
  if (first.status !== 401) {
    return first;
  }
  await refreshSession();
  return open();
};

const failureFrom = async (response: Response): Promise<ApiError> =>
  ApiError.fromResponse({
    status: response.status,
    body: await response.text().catch(() => ""),
    getHeader: (name) => response.headers.get(name),
  });

export const streamRenderEvents = async (
  id: string,
  handlers: StreamHandlers,
): Promise<boolean> => {
  const url = `${env.NEXT_PUBLIC_API_URL}${BASE}/${renderId(id)}/events`;
  const response = await connect(url, handlers);
  if (!response.ok) {
    throw await failureFrom(response);
  }
  if (response.body === null) {
    throw ApiError.ofKind("network");
  }
  handlers.onOpen();
  const outcome = { terminal: false };
  const parser = createSseParser((frame) => {
    if (!EVENT_NAMES.has(frame.event)) {
      return;
    }
    let payload: unknown;
    try {
      payload = JSON.parse(frame.data);
    } catch {
      return;
    }
    const parsed = renderProgressEventSchema.safeParse(payload);
    if (parsed.success) {
      outcome.terminal ||= isTerminalStatus(parsed.data.status);
      handlers.onEvent(parsed.data);
    }
  });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      parser.push(decoder.decode(value, { stream: true }));
      if (outcome.terminal) {
        break;
      }
    }
    parser.flush();
  } finally {
    await reader.cancel().catch(() => undefined);
  }
  return outcome.terminal;
};
