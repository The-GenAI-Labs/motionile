import { render, waitFor } from "@testing-library/react";
import { NextRequest } from "next/server";
import { StrictMode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RefreshSession } from "@/features/auth/components/refresh-session";
import { proxy } from "@/proxy";

const mocks = vi.hoisted(() => ({ refresh: vi.fn(), expire: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("next=%2Fsettings%2Fsecurity"),
}));
vi.mock("@/lib/auth/refresh", () => ({ refreshSession: mocks.refresh }));
vi.mock("@/lib/auth/session-expiry", () => ({ expireSession: mocks.expire }));

beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  mocks.refresh.mockResolvedValue(undefined);
});

describe("refresh bridge", () => {
  it("attempts once in StrictMode and preserves the destination", async () => {
    render(
      <StrictMode>
        <RefreshSession />
      </StrictMode>,
    );
    vi.stubGlobal(
      "window",
      Object.create(window, { location: { value: { replace: mocks.replace } } }),
    );
    await waitFor(() => {
      expect(mocks.replace).toHaveBeenCalledWith("/settings/security");
    });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });
  it("does not attempt again within ten seconds", () => {
    sessionStorage.setItem("mo-refresh-at", String(Date.now()));
    render(<RefreshSession />);
    expect(mocks.refresh).not.toHaveBeenCalled();
    expect(mocks.expire).toHaveBeenCalledExactlyOnceWith("/settings/security");
  });
  it("routes failure through the single expiry handler", async () => {
    mocks.refresh.mockRejectedValue(new Error("expired"));
    render(<RefreshSession />);
    await waitFor(() => {
      expect(mocks.expire).toHaveBeenCalledExactlyOnceWith("/settings/security");
    });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });
});

describe("navigation proxy", () => {
  it("preserves the protected path when no session cookies exist", () => {
    const result = proxy(new NextRequest("https://motionile.test/settings/security?tab=sessions"));
    expect(result.headers.get("location")).toBe(
      "https://motionile.test/login?next=%2Fsettings%2Fsecurity%3Ftab%3Dsessions",
    );
  });
  it("overwrites caller-supplied navigation headers", () => {
    const result = proxy(
      new NextRequest("https://motionile.test/admin", {
        headers: { cookie: "mo_auth=1", "x-mo-path": "https://evil.test" },
      }),
    );
    expect(result.headers.get("x-middleware-request-x-mo-path")).toBe("/admin");
  });
  it("redirects signed-in hints from auth pages but never redirects an expiry landing", () => {
    const headers = { cookie: `mo_auth=${String(Math.floor(Date.now() / 1000) + 900)}` };
    expect(
      proxy(new NextRequest("https://motionile.test/login", { headers })).headers.get("location"),
    ).toBe("https://motionile.test/dashboard");
    expect(
      proxy(
        new NextRequest("https://motionile.test/login?reason=expired", { headers }),
      ).headers.get("location"),
    ).toBeNull();
    expect(
      proxy(new NextRequest("https://motionile.test/refresh", { headers })).headers.get("location"),
    ).toBeNull();
  });
});
