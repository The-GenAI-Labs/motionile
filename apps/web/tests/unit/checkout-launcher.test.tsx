import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CheckoutProps } from "@/lib/razorpay/checkout.types";

vi.mock("@/lib/razorpay/razorpay-checkout", () => ({
  RazorpayCheckout: () => <p>Real Razorpay checkout</p>,
}));
vi.mock("@/lib/razorpay/fake-checkout", () => ({
  FakeCheckout: () => <p>Simulated checkout</p>,
}));

const props: CheckoutProps = {
  target: {
    kind: "order",
    orderId: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e01",
    keyId: "rzp_test_key",
    razorpayOrderId: "order_Abc123",
    amountPaise: 19_900,
    currency: "INR",
    description: "Starter credit pack",
    prefill: { name: null, email: null, contact: null },
  },
  verify: () => Promise.resolve(),
  onFinished: () => undefined,
  onDismiss: () => undefined,
};

const loadLauncher = async () => {
  vi.resetModules();
  return (await import("@/lib/razorpay/checkout-launcher")).CheckoutLauncher;
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("CheckoutLauncher", () => {
  it("loads the real Razorpay checkout by default", async () => {
    vi.stubEnv("NEXT_PUBLIC_PROVIDERS_MODE", "live");
    const CheckoutLauncher = await loadLauncher();

    render(<CheckoutLauncher {...props} />);

    expect(await screen.findByText("Real Razorpay checkout")).toBeInTheDocument();
    expect(screen.queryByText("Simulated checkout")).toBeNull();
  });

  it("loads the real checkout when no mode is configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_PROVIDERS_MODE", "");
    const CheckoutLauncher = await loadLauncher();

    render(<CheckoutLauncher {...props} />);

    expect(await screen.findByText("Real Razorpay checkout")).toBeInTheDocument();
  });

  it("loads the simulated checkout only in fake provider mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_PROVIDERS_MODE", "fake");
    const CheckoutLauncher = await loadLauncher();

    render(<CheckoutLauncher {...props} />);

    expect(await screen.findByText("Simulated checkout")).toBeInTheDocument();
    expect(screen.queryByText("Real Razorpay checkout")).toBeNull();
  });
});
