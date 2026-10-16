"use client";

import { useEffect } from "react";

import { subscribeAuth } from "@/lib/auth/broadcast";
import { AUTH_ROUTES, isAuthPath, safeNextPath } from "@/lib/auth/routes";
import { getQueryClient } from "@/lib/query/query-client";

export function SessionRuntime() {
  useEffect(() => {
    let redirected = false;
    return subscribeAuth((message) => {
      if (redirected) return;
      if (message === "signed-out" || message === "expired") {
        getQueryClient().clear();
        redirected = true;
        const next = safeNextPath(`${window.location.pathname}${window.location.search}`);
        window.location.replace(
          message === "expired"
            ? `${AUTH_ROUTES.login}?next=${encodeURIComponent(next)}&reason=expired`
            : AUTH_ROUTES.login,
        );
      } else if (message === "signed-in" && isAuthPath(window.location.pathname)) {
        redirected = true;
        window.location.replace(AUTH_ROUTES.dashboard);
      }
    });
  }, []);
  return null;
}
