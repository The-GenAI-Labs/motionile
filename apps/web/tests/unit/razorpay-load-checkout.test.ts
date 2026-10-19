import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const loadModule = async () => {
  vi.resetModules();
  return import("@/lib/razorpay/load-checkout");
};

const injectedScripts = (): HTMLScriptElement[] =>
  [...document.head.querySelectorAll("script")].filter((script) =>
    script.src.startsWith("https://checkout.razorpay.com"),
  );

class FakeRazorpay {
  readonly open = vi.fn();
  readonly close = vi.fn();
  readonly on = vi.fn();
}

beforeEach(() => {
  delete window.Razorpay;
  document.head.innerHTML = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loadRazorpayCheckout", () => {
  it("injects the official script once and shares one promise", async () => {
    const { loadRazorpayCheckout, RAZORPAY_CHECKOUT_SCRIPT_URL } = await loadModule();

    const first = loadRazorpayCheckout();
    const second = loadRazorpayCheckout();

    expect(first).toBe(second);
    expect(injectedScripts()).toHaveLength(1);
    const [script] = injectedScripts();
    expect(script?.src).toBe(RAZORPAY_CHECKOUT_SCRIPT_URL);
    expect(RAZORPAY_CHECKOUT_SCRIPT_URL).toBe("https://checkout.razorpay.com/v1/checkout.js");

    window.Razorpay = FakeRazorpay;
    script?.onload?.(new Event("load"));

    await expect(first).resolves.toBe(FakeRazorpay);
    await expect(loadRazorpayCheckout()).resolves.toBe(FakeRazorpay);
    expect(injectedScripts()).toHaveLength(1);
  });

  it("reuses a Razorpay global that is already present", async () => {
    window.Razorpay = FakeRazorpay;
    const { loadRazorpayCheckout } = await loadModule();

    await expect(loadRazorpayCheckout()).resolves.toBe(FakeRazorpay);
    expect(injectedScripts()).toHaveLength(0);
  });

  it("retries with a fresh script after a failed load", async () => {
    const { loadRazorpayCheckout } = await loadModule();

    const failed = loadRazorpayCheckout();
    injectedScripts()[0]?.onerror?.(new Event("error"));
    await expect(failed).rejects.toThrow(/could not be loaded/);
    expect(injectedScripts()).toHaveLength(0);

    const retried = loadRazorpayCheckout();
    expect(injectedScripts()).toHaveLength(1);
    window.Razorpay = FakeRazorpay;
    injectedScripts()[0]?.onload?.(new Event("load"));
    await expect(retried).resolves.toBe(FakeRazorpay);
  });

  it("fails when the script loads without exposing Razorpay", async () => {
    const { loadRazorpayCheckout } = await loadModule();

    const pending = loadRazorpayCheckout();
    injectedScripts()[0]?.onload?.(new Event("load"));

    await expect(pending).rejects.toThrow(/without exposing/);
  });

  it("rejects instead of touching the document when rendered on the server", async () => {
    vi.stubGlobal("window", undefined);
    const { loadRazorpayCheckout } = await loadModule();

    await expect(loadRazorpayCheckout()).rejects.toThrow(/browser/);
  });
});
