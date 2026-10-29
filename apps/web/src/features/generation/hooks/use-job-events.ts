"use client";

import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { creditsKeys } from "@/features/credits/query-keys";
import { followJobEvents } from "@/features/generation/api/job-events.api";
import {
  applyEventToJob,
  hasTerminalEvent,
  lastStoredEventId,
  mergeEvent,
  newerJob,
  REFRESH_EVENT_TYPES,
  STORYBOARD_EVENT_TYPES,
} from "@/features/generation/job-cache";
import { generationKeys } from "@/features/generation/query-keys";
import { isTerminalEvent, type JobEvent } from "@/features/generation/schemas/generation.schema";
import { useJobUiStore } from "@/features/generation/store/job-ui.store";
import type { Job } from "@/features/generation/types/generation.types";

const recordEvent = (client: QueryClient, jobId: string, event: JobEvent): void => {
  client.setQueryData<readonly JobEvent[]>(generationKeys.events(jobId), (current) =>
    mergeEvent(current ?? [], event),
  );
  client.setQueryData<Job>(generationKeys.job(jobId), (job) =>
    job === undefined ? job : applyEventToJob(job, event),
  );
  if (STORYBOARD_EVENT_TYPES.has(event.type)) {
    void client.invalidateQueries({ queryKey: generationKeys.storyboard(jobId) });
  }
  if (REFRESH_EVENT_TYPES.has(event.type)) {
    void client.invalidateQueries({ queryKey: generationKeys.job(jobId) });
  }
  if (isTerminalEvent(event)) {
    void client.invalidateQueries({ queryKey: generationKeys.jobs() });
    void client.invalidateQueries({ queryKey: creditsKeys.wallet() });
  }
};

interface UseJobEventsOptions {
  enabled: boolean;
}

export const useJobEvents = (jobId: string, { enabled }: UseJobEventsOptions): void => {
  const client = useQueryClient();
  const setConnection = useJobUiStore((state) => state.setConnection);
  const clearConnection = useJobUiStore((state) => state.clearConnection);

  useEffect(() => {
    if (!enabled) {
      return undefined;
    }
    const known = client.getQueryData<readonly JobEvent[]>(generationKeys.events(jobId));
    if (hasTerminalEvent(known)) {
      return undefined;
    }
    const controller = new AbortController();
    void followJobEvents(jobId, {
      signal: controller.signal,
      lastEventId: () =>
        lastStoredEventId(client.getQueryData<readonly JobEvent[]>(generationKeys.events(jobId))),
      onState: (state) => {
        setConnection(jobId, state);
      },
      onSnapshot: (job) => {
        client.setQueryData<Job>(generationKeys.job(jobId), (current) => newerJob(current, job));
      },
      onEvent: (event) => {
        recordEvent(client, jobId, event);
      },
    });
    return () => {
      controller.abort();
      clearConnection(jobId);
    };
  }, [client, jobId, enabled, setConnection, clearConnection]);
};
