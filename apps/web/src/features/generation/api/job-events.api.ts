import { type EventSourceMessage, fetchEventSource } from "@microsoft/fetch-event-source";
import { zJobsGetJobResponse } from "@motionile/api-contract";
import { z } from "zod";

import { env } from "@/config/env";
import {
  isTerminalEvent,
  type JobEvent,
  parseJobEvent,
} from "@/features/generation/schemas/generation.schema";
import type { ConnectionState, Job } from "@/features/generation/types/generation.types";
import { ApiError } from "@/lib/api/api-error";
import { refreshSession } from "@/lib/auth/refresh";

export const MAX_STREAM_FAILURES = 4;
export const BASE_RECONNECT_DELAY_MS = 1_000;
export const MAX_RECONNECT_DELAY_MS = 15_000;
export const POLL_INTERVAL_MS = 3_000;
export const SNAPSHOT_EVENT = "snapshot";
export const MESSAGE_EVENT = "job_event";
export const LAST_EVENT_ID_HEADER = "Last-Event-ID";

export type StreamOutcome = "terminal" | "aborted" | "polling";

export interface JobStreamHandlers {
  signal: AbortSignal;
  lastEventId: () => string | null;
  onState: (state: ConnectionState) => void;
  onSnapshot: (job: Job) => void;
  onEvent: (event: JobEvent) => void;
}

const FATAL_STATUSES: ReadonlySet<number> = new Set([401, 403, 404]);

class StreamClosedError extends Error {
  constructor() {
    super("The event stream closed before the job finished.");
    this.name = "StreamClosedError";
  }
}

export const reconnectDelayMs = (failures: number): number =>
  Math.min(BASE_RECONNECT_DELAY_MS * 2 ** Math.max(0, failures - 1), MAX_RECONNECT_DELAY_MS);

const failureFrom = async (response: Response): Promise<ApiError> =>
  ApiError.fromResponse({
    status: response.status,
    body: await response.text().catch(() => ""),
    getHeader: (name) => response.headers.get(name),
  });

const isFatal = (error: unknown): boolean => {
  const normalized = ApiError.from(error);
  return normalized.status !== null && FATAL_STATUSES.has(normalized.status);
};

const retryDelayMs = (error: unknown, failures: number): number => {
  const retryAfter = ApiError.from(error).retryAfterSeconds;
  const backoff = reconnectDelayMs(failures);
  return retryAfter === null
    ? backoff
    : Math.min(Math.max(backoff, retryAfter * 1_000), MAX_RECONNECT_DELAY_MS);
};

const parseSnapshot = (raw: string): Job | null => {
  try {
    const parsed = zJobsGetJobResponse.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
};

export const followJobEvents = async (
  jobId: string,
  handlers: JobStreamHandlers,
): Promise<StreamOutcome> => {
  const url = `${env.NEXT_PUBLIC_API_URL}/v1/jobs/${z.uuid().parse(jobId)}/events`;
  const progress = { failures: 0, terminal: false, lastEventId: handlers.lastEventId() };

  const requestInit = (init: RequestInit | undefined): RequestInit => {
    const headers = new Headers(init?.headers);
    if (progress.lastEventId !== null) {
      headers.set(LAST_EVENT_ID_HEADER, progress.lastEventId);
    } else {
      headers.delete(LAST_EVENT_ID_HEADER);
    }
    return { ...init, headers };
  };

  const authenticatedFetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const first = await fetch(input, requestInit(init));
    if (first.status !== 401) {
      return first;
    }
    await refreshSession();
    return fetch(input, requestInit(init));
  };

  const handleMessage = (message: EventSourceMessage): void => {
    if (message.id !== "") {
      progress.lastEventId = message.id;
    }
    if (message.event === SNAPSHOT_EVENT) {
      const job = parseSnapshot(message.data);
      if (job !== null) {
        handlers.onSnapshot(job);
      }
      return;
    }
    if (message.event === MESSAGE_EVENT) {
      const event = parseJobEvent(message.data);
      if (event !== null) {
        progress.terminal ||= isTerminalEvent(event);
        handlers.onEvent(event);
      }
    }
  };

  handlers.onState("connecting");
  try {
    await fetchEventSource(url, {
      signal: handlers.signal,
      method: "GET",
      credentials: "include",
      cache: "no-store",
      headers: { Accept: "text/event-stream" },
      fetch: authenticatedFetch,
      onopen: async (response) => {
        if (!response.ok) {
          throw await failureFrom(response);
        }
        if (!(response.headers.get("content-type") ?? "").startsWith("text/event-stream")) {
          throw ApiError.ofKind("network");
        }
        progress.failures = 0;
        handlers.onState("live");
      },
      onmessage: handleMessage,
      onclose: () => {
        if (!progress.terminal) {
          throw new StreamClosedError();
        }
      },
      onerror: (error: unknown) => {
        if (progress.terminal || handlers.signal.aborted || isFatal(error)) {
          throw error;
        }
        progress.failures += 1;
        if (progress.failures >= MAX_STREAM_FAILURES) {
          throw error;
        }
        handlers.onState("reconnecting");
        return retryDelayMs(error, progress.failures);
      },
    });
  } catch {
    if (handlers.signal.aborted) {
      return "aborted";
    }
    handlers.onState("polling");
    return "polling";
  }
  if (progress.terminal) {
    return "terminal";
  }
  return handlers.signal.aborted ? "aborted" : "polling";
};
