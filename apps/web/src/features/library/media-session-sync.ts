import { zMediaSessionView } from "@motionile/api-contract";

import { getMediaSession } from "@/features/library/api/library.api";
import type { MediaSession } from "@/features/library/types/library.types";

export const REFRESH_LEAD_MS = 60_000;
export const MIN_REFRESH_DELAY_MS = 10_000;

const STORAGE_KEY = "mo-media-session";
const LOCK_NAME = "mo-media-session";

export const refreshAtMs = (session: MediaSession | undefined): number | null => {
  if (session?.mode !== "cloudfront" || !session.expiresAt) {
    return null;
  }
  return Date.parse(session.expiresAt) - REFRESH_LEAD_MS;
};

const readShared = (): MediaSession | null => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === null) {
      return null;
    }
    const parsed = zMediaSessionView.safeParse(JSON.parse(raw));
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
};

const recordShared = (session: MediaSession): void => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } catch {
    return;
  }
};

const inLock = <Result>(task: () => Promise<Result>): Promise<Result> => {
  if (typeof navigator !== "undefined" && "locks" in navigator) {
    return navigator.locks.request(LOCK_NAME, task);
  }
  return task();
};

const isFreshEnough = (session: MediaSession | null): session is MediaSession => {
  const at = refreshAtMs(session ?? undefined);
  return at !== null && at - Date.now() > MIN_REFRESH_DELAY_MS;
};

export const syncMediaSession = (reuseShared: boolean): Promise<MediaSession> =>
  inLock(async () => {
    const shared = reuseShared ? readShared() : null;
    if (isFreshEnough(shared)) {
      return shared;
    }
    const session = await getMediaSession();
    recordShared(session);
    return session;
  });
