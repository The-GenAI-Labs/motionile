import "server-only";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { safeNextPath } from "@/lib/auth/routes";
import { type Principal, readSession } from "@/lib/auth/session";

export async function requireUser(nextPath: string): Promise<Principal> {
  const session = await readSession();
  if (session.status === "valid") return session.principal;
  const next = encodeURIComponent(safeNextPath(nextPath));
  const hint = (await cookies()).get("mo_auth")?.value;
  if (hint) redirect(`/refresh?next=${next}`);
  redirect(`/login?next=${next}`);
}

export function requireRole(principal: Principal, roles: readonly string[]): void {
  if (!roles.some((role) => principal.roles.includes(role))) redirect("/forbidden");
}

export async function protectedNextPath(fallback: string): Promise<string> {
  return safeNextPath((await headers()).get("x-mo-path") ?? fallback);
}
