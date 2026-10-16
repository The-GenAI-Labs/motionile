"use client";

import { useSessionKeepalive } from "@/features/auth/hooks/use-session-keepalive";

export function SessionKeepalive() {
  useSessionKeepalive();
  return null;
}
