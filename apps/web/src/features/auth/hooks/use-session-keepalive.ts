"use client";

import { useEffect } from "react";

import { subscribeAuth } from "@/lib/auth/broadcast";
import { readAccessExpiry } from "@/lib/auth/cookies";
import { refreshSession } from "@/lib/auth/refresh";

export function useSessionKeepalive(): void {
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    const schedule = (): void => {
      clearTimeout(timer);
      const expiry = readAccessExpiry();
      if (disposed || document.visibilityState !== "visible" || expiry === null) return;
      timer = setTimeout(
        () => {
          void refreshSession().catch(() => undefined);
        },
        Math.max(1000, expiry - Date.now() - 60_000),
      );
    };
    const unsubscribe = subscribeAuth((message) => {
      if (message === "refreshed" || message === "signed-in") schedule();
      else clearTimeout(timer);
    });
    document.addEventListener("visibilitychange", schedule);
    schedule();
    return () => {
      disposed = true;
      clearTimeout(timer);
      unsubscribe();
      document.removeEventListener("visibilitychange", schedule);
    };
  }, []);
}
