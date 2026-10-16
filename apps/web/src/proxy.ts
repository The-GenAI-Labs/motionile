import { type NextRequest, NextResponse } from "next/server";

import { isAuthPath, safeNextPath } from "@/lib/auth/routes";

export function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  const hint = Number(request.cookies.get("mo_auth")?.value ?? 0);
  if (isAuthPath(path)) {
    if (
      path !== "/refresh" &&
      request.nextUrl.searchParams.get("reason") !== "expired" &&
      hint > Date.now() / 1000
    )
      return NextResponse.redirect(new URL("/dashboard", request.url));
    return NextResponse.next();
  }
  const next = safeNextPath(`${path}${request.nextUrl.search}`);
  if (!request.cookies.has("__Secure-mo_at") && !request.cookies.has("mo_auth")) {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", next);
    return NextResponse.redirect(url);
  }
  const headers = new Headers(request.headers);
  headers.set("x-mo-path", next);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: [
    "/dashboard/:path*",
    "/settings/:path*",
    "/admin/:path*",
    "/login",
    "/register",
    "/verify",
    "/forgot-password",
    "/reset-password",
    "/refresh",
  ],
};
