import {
  isTerminalStatus,
  type RenderProgressEvent,
} from "@/features/admin-render/schemas/admin-render.schema";
import type {
  ConnectionState,
  RenderStage,
  RenderStatus,
} from "@/features/admin-render/types/admin-render.types";

export const MAX_STREAM_ATTEMPTS = 4;
export const BASE_RECONNECT_DELAY_MS = 1_000;
export const MAX_RECONNECT_DELAY_MS = 15_000;
export const POLL_INTERVAL_MS = 3_000;

export interface RenderProgressState {
  status: RenderStatus | null;
  stage: RenderStage | null;
  progress: number;
  errorCode: string | null;
  errorMessage: string | null;
  connection: ConnectionState;
  failures: number;
  terminal: boolean;
}

export type RenderProgressAction =
  | { type: "connecting" }
  | { type: "opened" }
  | { type: "event"; event: RenderProgressEvent }
  | { type: "failed" };

export const initialProgressState: RenderProgressState = {
  status: null,
  stage: null,
  progress: 0,
  errorCode: null,
  errorMessage: null,
  connection: "connecting",
  failures: 0,
  terminal: false,
};

export const reconnectDelayMs = (failures: number): number =>
  Math.min(BASE_RECONNECT_DELAY_MS * 2 ** Math.max(0, failures - 1), MAX_RECONNECT_DELAY_MS);

export const progressReducer = (
  state: RenderProgressState,
  action: RenderProgressAction,
): RenderProgressState => {
  switch (action.type) {
    case "connecting":
      return state.terminal || state.connection === "polling"
        ? state
        : { ...state, connection: state.failures === 0 ? "connecting" : "reconnecting" };
    case "opened":
      return state.terminal ? state : { ...state, connection: "live", failures: 0 };
    case "failed": {
      if (state.terminal) {
        return state;
      }
      const failures = state.failures + 1;
      return {
        ...state,
        failures,
        connection: failures >= MAX_STREAM_ATTEMPTS ? "polling" : "reconnecting",
      };
    }
    case "event": {
      if (state.terminal) {
        return state;
      }
      const { event } = action;
      const terminal = isTerminalStatus(event.status);
      return {
        ...state,
        status: event.status,
        stage: event.stage ?? null,
        progress:
          terminal && event.status === "completed" ? 100 : Math.max(state.progress, event.progress),
        errorCode: event.errorCode ?? null,
        errorMessage: event.errorMessage ?? null,
        terminal,
      };
    }
  }
};
