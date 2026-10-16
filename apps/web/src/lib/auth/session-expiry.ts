import { broadcastAuth } from "@/lib/auth/broadcast";
import { AUTH_ROUTES, safeNextPath } from "@/lib/auth/routes";
import { getQueryClient } from "@/lib/query/query-client";

let expired = false;

export const expireSession = (nextPath?: string): void => {
  if (expired || typeof window === "undefined") return;
  expired = true;
  getQueryClient().clear();
  broadcastAuth("expired");
  const destination =
    window.location.pathname === AUTH_ROUTES.refresh
      ? new URLSearchParams(window.location.search).get("next")
      : `${window.location.pathname}${window.location.search}`;
  const next = safeNextPath(nextPath ?? destination);
  window.location.replace(`${AUTH_ROUTES.login}?next=${encodeURIComponent(next)}&reason=expired`);
};
