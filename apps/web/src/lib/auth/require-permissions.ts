import "server-only";

import { zAuthMeResponse } from "@motionile/api-contract";
import { forbidden } from "next/navigation";

import { serverFetch } from "@/lib/api/server";
import { hasPermissions, type PermissionMatchMode } from "@/lib/auth/permissions";

export async function requirePermissions(
  required: readonly string[],
  mode: PermissionMatchMode = "all",
): Promise<void> {
  const user = await serverFetch("/v1/auth/me", { schema: zAuthMeResponse });
  if (!hasPermissions(required, user.permissions, mode)) {
    forbidden();
  }
}
