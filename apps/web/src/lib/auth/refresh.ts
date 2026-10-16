import { zAuthRefreshResponse } from "@motionile/api-contract";

import { ApiError } from "@/lib/api/api-error";
import { apiClient } from "@/lib/api/client";
import { broadcastAuth } from "@/lib/auth/broadcast";
import { readCookie } from "@/lib/auth/cookies";
import { expireSession } from "@/lib/auth/session-expiry";

const refreshMarkerKey = "mo-auth-refresh-generation";
let pending: Promise<void> | undefined;

const readGeneration = (): string | null => {
  try {
    return localStorage.getItem(refreshMarkerKey);
  } catch {
    return null;
  }
};

const recordGeneration = (): void => {
  try {
    localStorage.setItem(refreshMarkerKey, crypto.randomUUID());
  } catch {
    return;
  }
};

export const waitForRefresh = (): Promise<void> =>
  new Promise((resolve) => {
    setTimeout(resolve, 250);
  });

const rotate = async (): Promise<void> => {
  try {
    await apiClient.post("/v1/auth/refresh", undefined, { skipAuthRefresh: true });
    zAuthRefreshResponse.parse(undefined);
    recordGeneration();
    broadcastAuth("refreshed");
  } catch (error) {
    const normalized = ApiError.from(error);
    if (normalized.code === "refresh_conflict") {
      await waitForRefresh();
      broadcastAuth("refreshed");
      return;
    }
    expireSession();
    throw normalized;
  }
};

export const refreshSession = (): Promise<void> => {
  if (pending) return pending;
  const hint = readCookie("mo_auth");
  const generation = readGeneration();
  const refresh = async (): Promise<void> => {
    if (typeof navigator !== "undefined" && "locks" in navigator) {
      await navigator.locks.request("mo-auth-refresh", async () => {
        if (readCookie("mo_auth") !== hint || readGeneration() !== generation) {
          broadcastAuth("refreshed");
          return;
        }
        await rotate();
      });
    } else {
      await rotate();
    }
  };
  pending = refresh().finally(() => {
    pending = undefined;
  });
  return pending;
};
