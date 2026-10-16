import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionRuntime } from "@/features/auth/components/session-runtime";
import { type AuthMessage, broadcastAuth, subscribeAuth } from "@/lib/auth/broadcast";

vi.mock("@/lib/auth/broadcast", () => ({ broadcastAuth: vi.fn(), subscribeAuth: vi.fn() }));
vi.mock("@/lib/query/query-client", () => ({ getQueryClient: () => ({ clear }) }));

const { clear } = vi.hoisted(() => ({ clear: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("cross-tab session navigation", () => {
  it.each(["signed-out", "expired"] as const)(
    "clears cache and redirects once for %s",
    (message) => {
      let receive: ((message: AuthMessage) => void) | undefined;
      const unsubscribe = vi.fn();
      vi.mocked(subscribeAuth).mockImplementation((listener) => {
        receive = listener;
        return unsubscribe;
      });
      const { unmount } = render(<SessionRuntime />);
      const replace = vi.fn();
      vi.stubGlobal("window", {
        location: { pathname: "/settings/security", search: "?tab=sessions", replace },
      });
      receive?.(message);
      receive?.(message);
      expect(clear).toHaveBeenCalledTimes(1);
      expect(replace).toHaveBeenCalledExactlyOnceWith(
        message === "expired"
          ? "/login?next=%2Fsettings%2Fsecurity%3Ftab%3Dsessions&reason=expired"
          : "/login",
      );
      vi.unstubAllGlobals();
      unmount();
      expect(unsubscribe).toHaveBeenCalledTimes(1);
    },
  );

  it("navigates a signed-in auth tab but leaves other pages in place", () => {
    let receive: ((message: AuthMessage) => void) | undefined;
    vi.mocked(subscribeAuth).mockImplementation((listener) => {
      receive = listener;
      return vi.fn();
    });
    render(<SessionRuntime />);
    const replace = vi.fn();
    const location = { pathname: "/about", replace };
    vi.stubGlobal("window", { location });
    receive?.("signed-in");
    expect(replace).not.toHaveBeenCalled();
    location.pathname = "/login";
    receive?.("signed-in");
    expect(replace).toHaveBeenCalledExactlyOnceWith("/dashboard");
    vi.unstubAllGlobals();
  });

  it("expires once per page lifetime with a safe preserved return path", async () => {
    const { expireSession } = await import("@/lib/auth/session-expiry");
    const replace = vi.fn();
    vi.stubGlobal("window", {
      location: { pathname: "/settings/security", search: "?tab=sessions", replace },
    });
    expireSession();
    expireSession();
    expect(clear).toHaveBeenCalledTimes(1);
    expect(broadcastAuth).toHaveBeenCalledExactlyOnceWith("expired");
    expect(replace).toHaveBeenCalledExactlyOnceWith(
      "/login?next=%2Fsettings%2Fsecurity%3Ftab%3Dsessions&reason=expired",
    );
  });
});
