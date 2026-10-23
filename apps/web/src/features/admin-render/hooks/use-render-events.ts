"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useReducer } from "react";

import { streamRenderEvents } from "@/features/admin-render/api/admin-render.api";
import {
  initialProgressState,
  MAX_STREAM_ATTEMPTS,
  progressReducer,
  reconnectDelayMs,
} from "@/features/admin-render/progress-reducer";
import { adminRenderKeys } from "@/features/admin-render/query-keys";

const sleep = (milliseconds: number, signal: AbortSignal): Promise<void> =>
  new Promise((resolve) => {
    const timer = setTimeout(resolve, milliseconds);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });

interface UseRenderEventsOptions {
  enabled: boolean;
  stream?: typeof streamRenderEvents;
  delay?: (milliseconds: number, signal: AbortSignal) => Promise<void>;
}

export const useRenderEvents = (
  renderId: string,
  { enabled, stream = streamRenderEvents, delay = sleep }: UseRenderEventsOptions,
) => {
  const client = useQueryClient();
  const [state, dispatch] = useReducer(progressReducer, initialProgressState);

  useEffect(() => {
    if (!enabled) {
      return undefined;
    }
    const controller = new AbortController();
    const stopped = (): boolean => controller.signal.aborted;
    const run = async (): Promise<void> => {
      let failures = 0;
      while (!stopped() && failures < MAX_STREAM_ATTEMPTS) {
        dispatch({ type: "connecting" });
        try {
          const finished = await stream(renderId, {
            signal: controller.signal,
            onOpen: () => {
              failures = 0;
              dispatch({ type: "opened" });
            },
            onEvent: (event) => {
              dispatch({ type: "event", event });
            },
          });
          if (finished || stopped()) {
            return;
          }
        } catch {
          if (stopped()) {
            return;
          }
        }
        failures += 1;
        dispatch({ type: "failed" });
        if (failures >= MAX_STREAM_ATTEMPTS) {
          return;
        }
        await delay(reconnectDelayMs(failures), controller.signal);
      }
    };
    void run();
    return () => {
      controller.abort();
    };
  }, [renderId, enabled, stream, delay]);

  const { terminal } = state;
  useEffect(() => {
    if (terminal) {
      void client.invalidateQueries({ queryKey: adminRenderKeys.render(renderId) });
    }
  }, [terminal, client, renderId]);

  return state;
};
