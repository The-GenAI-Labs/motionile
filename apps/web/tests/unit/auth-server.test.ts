import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  verify: vi.fn(),
  cookie: vi.fn(),
  redirect: vi.fn(),
  headers: vi.fn(),
}));
vi.mock("jose", async (original) => ({
  ...(await original<typeof Jose>()),
  createRemoteJWKSet: vi.fn(),
  jwtVerify: mocks.verify,
}));
vi.mock("next/headers", () => ({
  cookies: () => ({ get: mocks.cookie }),
  headers: () => ({ get: mocks.headers }),
}));
vi.mock("next/navigation", () => ({ redirect: mocks.redirect }));

import type * as Jose from "jose";
import { errors } from "jose";

import { protectedNextPath, requireRole, requireUser } from "@/lib/auth/guards";
import { readSession } from "@/lib/auth/session";

const id = "0199aabb-1111-7111-8111-111111111111";
const principal = { id, sessionId: id, roles: ["user"], expiry: 2000000000 };

beforeEach(() => {
  vi.clearAllMocks();
  mocks.cookie.mockImplementation((name: string) =>
    name === "__Secure-mo_at" ? { value: "token" } : undefined,
  );
  mocks.verify.mockResolvedValue({
    payload: { sub: id, sid: id, roles: ["user"], exp: principal.expiry },
  });
  mocks.redirect.mockImplementation((path: string) => {
    throw new Error(`redirect:${path}`);
  });
});

describe("server sessions", () => {
  it("verifies algorithm, issuer and audience before returning the principal", async () => {
    expect(await readSession()).toEqual({ status: "valid", principal });
    expect(mocks.verify).toHaveBeenCalledWith(
      "token",
      undefined,
      expect.objectContaining({
        algorithms: ["EdDSA"],
        issuer: "https://api.motionile.local",
        audience: "motionile",
      }),
    );
  });
  it("does not verify absent cookies", async () => {
    mocks.cookie.mockReturnValue(undefined);
    expect(await readSession()).toEqual({ status: "none" });
    expect(mocks.verify).not.toHaveBeenCalled();
  });
  it("recognizes expired tokens", async () => {
    mocks.verify.mockRejectedValue(new errors.JWTExpired("expired", {}, "exp", "check_failed"));
    expect(await readSession()).toEqual({ status: "expired" });
  });
  it("rejects invalid signatures and malformed principals", async () => {
    mocks.verify.mockRejectedValueOnce(new errors.JWSSignatureVerificationFailed());
    expect(await readSession()).toEqual({ status: "none" });
    mocks.verify.mockResolvedValue({ payload: { sub: "bad" } });
    expect(await readSession()).toEqual({ status: "none" });
  });
  it("surfaces key service outages instead of redirecting in a login loop", async () => {
    mocks.verify.mockRejectedValue(new TypeError("offline"));
    await expect(readSession()).rejects.toThrow("offline");
  });
});

describe("server guards", () => {
  it("returns an authenticated principal", async () => {
    expect(await requireUser("/settings/security")).toEqual(principal);
  });
  it("sends missing sessions to login preserving a safe destination", async () => {
    mocks.cookie.mockReturnValue(undefined);
    await expect(requireUser("/settings/security")).rejects.toThrow(
      "redirect:/login?next=%2Fsettings%2Fsecurity",
    );
    await expect(requireUser("//evil.test")).rejects.toThrow("redirect:/login?next=%2Fdashboard");
  });
  it("uses the refresh bridge when cookies expired but a hint remains", async () => {
    mocks.cookie.mockImplementation((name: string) =>
      name === "mo_auth" ? { value: "1" } : undefined,
    );
    await expect(requireUser("/settings/security")).rejects.toThrow(
      "redirect:/refresh?next=%2Fsettings%2Fsecurity",
    );
  });
  it("rejects users without an allowed role", () => {
    expect(() => {
      requireRole(principal, ["admin", "super_admin"]);
    }).toThrow("redirect:/forbidden");
    requireRole({ ...principal, roles: ["admin"] }, ["admin"]);
  });
  it("sanitizes the proxy-provided path", async () => {
    mocks.headers.mockReturnValue("/settings/security?tab=sessions");
    expect(await protectedNextPath("/dashboard")).toBe("/settings/security?tab=sessions");
    mocks.headers.mockReturnValue("https://evil.test");
    expect(await protectedNextPath("/dashboard")).toBe("/dashboard");
  });
});
