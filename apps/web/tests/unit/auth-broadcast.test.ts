import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("auth broadcast channel", () => {
  it("accepts only typed messages from other tabs and unsubscribes", async () => {
    const instances: TestChannel[] = [];
    class TestChannel {
      onmessage: ((event: MessageEvent<unknown>) => void) | null = null;
      postMessage = vi.fn();
      constructor(readonly name: string) {
        instances.push(this);
      }
    }
    vi.stubGlobal("BroadcastChannel", TestChannel);
    const { subscribeAuth, broadcastAuth } = await import("@/lib/auth/broadcast");
    const listener = vi.fn();
    const unsubscribe = subscribeAuth(listener);
    const channel = instances[0];
    expect(channel?.name).toBe("mo-auth");
    channel?.onmessage?.(new MessageEvent("message", { data: { token: "untrusted" } }));
    channel?.onmessage?.(new MessageEvent("message", { data: "unknown" }));
    expect(listener).not.toHaveBeenCalled();
    for (const data of ["signed-in", "signed-out", "expired", "refreshed"]) {
      channel?.onmessage?.(new MessageEvent("message", { data }));
      expect(listener).toHaveBeenLastCalledWith(data);
    }
    broadcastAuth("signed-out");
    expect(channel?.postMessage).toHaveBeenCalledWith("signed-out");
    expect(listener).toHaveBeenCalledTimes(4);
    unsubscribe();
    channel?.onmessage?.(new MessageEvent("message", { data: "expired" }));
    expect(listener).toHaveBeenCalledTimes(4);
  });

  it("supports browsers without BroadcastChannel", async () => {
    vi.stubGlobal("BroadcastChannel", undefined);
    const { subscribeAuth, broadcastAuth } = await import("@/lib/auth/broadcast");
    const listener = vi.fn();
    const unsubscribe = subscribeAuth(listener);
    expect(() => {
      broadcastAuth("signed-in");
    }).not.toThrow();
    broadcastAuth("refreshed");
    expect(listener).toHaveBeenCalledWith("refreshed");
    unsubscribe();
  });
});
