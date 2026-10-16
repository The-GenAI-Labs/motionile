"use client";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { refreshSession } from "@/lib/auth/refresh";
import { safeNextPath } from "@/lib/auth/routes";
import { expireSession } from "@/lib/auth/session-expiry";
export function RefreshSession() {
  const params = useSearchParams();
  const started = useRef(false);
  const next = safeNextPath(params.get("next"));
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const fail = () => {
      expireSession(next);
    };
    try {
      const previous = Number(sessionStorage.getItem("mo-refresh-at"));
      if (previous && Date.now() - previous < 10_000) {
        fail();
        return;
      }
      sessionStorage.setItem("mo-refresh-at", String(Date.now()));
    } catch {
      fail();
      return;
    }
    void refreshSession()
      .then(() => {
        window.location.replace(next);
      })
      .catch(fail);
  }, [next]);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Restoring your session</h1>
      <p role="status">Please wait while we securely reconnect you.</p>
    </div>
  );
}
