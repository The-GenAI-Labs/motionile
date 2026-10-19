import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, type Mock, vi } from "vitest";

import type { CheckoutCompletion, CheckoutTarget } from "@/lib/razorpay/checkout.types";
import { buildRazorpayOptions } from "@/lib/razorpay/checkout-options";
import {
  completeCheckout,
  completionFrom,
  VERIFY_TIMEOUT_MS,
} from "@/lib/razorpay/complete-checkout";
import type {
  RazorpayFailureResponse,
  RazorpayOptions,
  RazorpaySuccessResponse,
} from "@/lib/razorpay/razorpay.types";
import { RazorpayCheckout } from "@/lib/razorpay/razorpay-checkout";

const { loadRazorpayCheckout } = vi.hoisted(() => ({ loadRazorpayCheckout: vi.fn() }));

vi.mock("@/lib/razorpay/load-checkout", () => ({ loadRazorpayCheckout }));

const ORDER_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e01";

const orderTarget: CheckoutTarget = {
  kind: "order",
  orderId: ORDER_ID,
  keyId: "rzp_test_key",
  razorpayOrderId: "order_Abc123",
  amountPaise: 19_900,
  currency: "INR",
  description: "Starter credit pack",
  prefill: { name: "Asha", email: null, contact: "+919876543210" },
};

const subscriptionTarget: CheckoutTarget = {
  kind: "subscription",
  orderId: ORDER_ID,
  keyId: "rzp_test_key",
  razorpaySubscriptionId: "sub_Abc123",
  description: "Pro monthly",
  prefill: { name: null, email: "asha@example.com", contact: null },
};

type FailureHandler = (response: RazorpayFailureResponse) => void;

let instances: FakeRazorpay[] = [];

class FakeRazorpay {
  readonly open = vi.fn();
  readonly close = vi.fn();
  failureHandler: FailureHandler | null = null;

  constructor(readonly options: RazorpayOptions) {
    instances.push(this);
  }

  on(_event: "payment.failed", handler: FailureHandler): void {
    this.failureHandler = handler;
  }
}

const paid = (overrides: Partial<RazorpaySuccessResponse> = {}): RazorpaySuccessResponse => ({
  razorpay_payment_id: "pay_Abc123",
  razorpay_order_id: "order_Abc123",
  razorpay_signature: "signature",
  ...overrides,
});

const paidSubscription = (): RazorpaySuccessResponse => ({
  razorpay_payment_id: "pay_Abc123",
  razorpay_subscription_id: "sub_Abc123",
  razorpay_signature: "signature",
});

const latest = (): FakeRazorpay => {
  const instance = instances.at(-1);
  if (!instance) {
    throw new Error("Razorpay was not constructed");
  }
  return instance;
};

type VerifyMock = Mock<(completion: CheckoutCompletion) => Promise<unknown>>;

const verifyMock = (implementation: () => Promise<unknown>): VerifyMock =>
  vi.fn<(completion: CheckoutCompletion) => Promise<unknown>>(implementation);

const renderCheckout = (
  overrides: {
    target?: CheckoutTarget;
    verify?: VerifyMock;
  } = {},
) => {
  const verify = overrides.verify ?? verifyMock(() => Promise.resolve({}));
  const onFinished = vi.fn();
  const onDismiss = vi.fn();
  const view = render(
    <RazorpayCheckout
      target={overrides.target ?? orderTarget}
      verify={verify}
      onFinished={onFinished}
      onDismiss={onDismiss}
    />,
  );
  return { verify, onFinished, onDismiss, ...view };
};

beforeEach(() => {
  instances = [];
  loadRazorpayCheckout.mockReset();
  loadRazorpayCheckout.mockResolvedValue(FakeRazorpay);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("checkout options", () => {
  const handlers = { onPaid: vi.fn(), onDismiss: vi.fn() };

  it("opens an order with its amount, the brand name and prefill", () => {
    const options = buildRazorpayOptions(orderTarget, handlers);

    expect(options).toMatchObject({
      key: "rzp_test_key",
      name: "Motionile",
      description: "Starter credit pack",
      order_id: "order_Abc123",
      amount: 19_900,
      currency: "INR",
      prefill: { name: "Asha", contact: "+919876543210" },
      theme: { color: "#0E0E10" },
      modal: { confirm_close: true },
    });
    expect(options.prefill).not.toHaveProperty("email");
    expect(options).not.toHaveProperty("subscription_id");
  });

  it("opens a subscription without an amount", () => {
    const options = buildRazorpayOptions(subscriptionTarget, handlers);

    expect(options.subscription_id).toBe("sub_Abc123");
    expect(options).not.toHaveProperty("order_id");
    expect(options).not.toHaveProperty("amount");
    expect(options.prefill).toEqual({ email: "asha@example.com" });
  });
});

describe("completion mapping", () => {
  it("maps Razorpay responses for orders and subscriptions", () => {
    expect(completionFrom(orderTarget, paid())).toEqual({
      kind: "order",
      razorpayOrderId: "order_Abc123",
      razorpayPaymentId: "pay_Abc123",
      razorpaySignature: "signature",
    });
    expect(completionFrom(subscriptionTarget, paidSubscription())).toEqual({
      kind: "subscription",
      razorpaySubscriptionId: "sub_Abc123",
      razorpayPaymentId: "pay_Abc123",
      razorpaySignature: "signature",
    });
  });

  it("returns nothing to verify when the signature is missing", () => {
    expect(completionFrom(orderTarget, paid({ razorpay_signature: "" }))).toBeNull();
    expect(completionFrom(subscriptionTarget, paid({ razorpay_payment_id: "" }))).toBeNull();
  });

  it("never waits longer than the timeout for verification", async () => {
    vi.useFakeTimers();
    const completion = completionFrom(orderTarget, paid());
    const verify = vi.fn(() => new Promise<never>(() => undefined));

    const done = vi.fn();
    void completeCheckout({ completion, verify }).then(done);
    await vi.advanceTimersByTimeAsync(VERIFY_TIMEOUT_MS - 1);
    expect(done).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("swallows a synchronous verification failure", async () => {
    const completion = completionFrom(orderTarget, paid());

    await expect(
      completeCheckout({
        completion,
        verify: () => {
          throw new Error("boom");
        },
      }),
    ).resolves.toBeUndefined();
  });
});

describe("RazorpayCheckout", () => {
  it("opens checkout and tells the user to finish paying", async () => {
    renderCheckout();

    expect(screen.getByRole("status")).toHaveTextContent("Opening secure checkout");
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Complete your payment");
    });
    expect(latest().open).toHaveBeenCalledTimes(1);
    expect(instances).toHaveLength(1);
  });

  it("verifies the payment and then goes to the status page", async () => {
    const { verify, onFinished } = renderCheckout();
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    act(() => {
      latest().options.handler(paid());
    });

    expect(screen.getByRole("status")).toHaveTextContent("Confirming your payment");
    await waitFor(() => {
      expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
    });
    expect(verify).toHaveBeenCalledExactlyOnceWith({
      kind: "order",
      razorpayOrderId: "order_Abc123",
      razorpayPaymentId: "pay_Abc123",
      razorpaySignature: "signature",
    });
    expect(verify.mock.invocationCallOrder[0]).toBeLessThan(
      onFinished.mock.invocationCallOrder[0] ?? 0,
    );
  });

  it("verifies a subscription authorisation", async () => {
    const { verify, onFinished } = renderCheckout({ target: subscriptionTarget });
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    act(() => {
      latest().options.handler(paidSubscription());
    });

    await waitFor(() => {
      expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
    });
    expect(verify).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "subscription", razorpaySubscriptionId: "sub_Abc123" }),
    );
  });

  it("still goes to the status page when verification fails", async () => {
    const { verify, onFinished } = renderCheckout({
      verify: verifyMock(() => Promise.reject(new Error("verify failed"))),
    });
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    act(() => {
      latest().options.handler(paid());
    });

    await waitFor(() => {
      expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
    });
    expect(verify).toHaveBeenCalledTimes(1);
  });

  it("still goes to the status page when verification is slow", async () => {
    const { onFinished } = renderCheckout({
      verify: verifyMock(() => new Promise(() => undefined)),
    });
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });
    vi.useFakeTimers();

    act(() => {
      latest().options.handler(paid());
    });
    await vi.advanceTimersByTimeAsync(VERIFY_TIMEOUT_MS);

    expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
  });

  it("goes to the status page without verifying when the response is incomplete", async () => {
    const { verify, onFinished } = renderCheckout();
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    act(() => {
      latest().options.handler(paid({ razorpay_signature: "" }));
    });

    await waitFor(() => {
      expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
    });
    expect(verify).not.toHaveBeenCalled();
  });

  it("explains a failed payment while the checkout window stays open", async () => {
    renderCheckout();
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    act(() => {
      latest().failureHandler?.({ error: { description: "Your card was declined" } });
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Payment failed: Your card was declined");
  });

  it("uses a generic message when the failure has no description", async () => {
    renderCheckout();
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    act(() => {
      latest().failureHandler?.({ error: {} });
    });

    expect(screen.getByRole("alert")).toHaveTextContent("The payment did not go through");
  });

  it("offers a retry on the same order after the window is dismissed", async () => {
    const user = userEvent.setup();
    const { onDismiss, onFinished } = renderCheckout();
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    act(() => {
      latest().options.modal.ondismiss();
    });

    expect(screen.getByRole("status")).toHaveTextContent("Checkout was closed before the payment");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => {
      expect(instances).toHaveLength(2);
    });

    expect(latest().options.order_id).toBe("order_Abc123");
    expect(latest().open).toHaveBeenCalledTimes(1);
    expect(onDismiss).not.toHaveBeenCalled();
    expect(onFinished).not.toHaveBeenCalled();
  });

  it("keeps the failure message when the window is dismissed after a failed payment", async () => {
    renderCheckout();
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    act(() => {
      latest().failureHandler?.({ error: { description: "Insufficient funds" } });
    });
    act(() => {
      latest().options.modal.ondismiss();
    });

    expect(screen.getByRole("alert")).toHaveTextContent("Payment failed: Insufficient funds");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("lets the user cancel after dismissing", async () => {
    const user = userEvent.setup();
    const { onDismiss } = renderCheckout();
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    act(() => {
      latest().options.modal.ondismiss();
    });
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("reports an unavailable checkout and retries loading it", async () => {
    const user = userEvent.setup();
    loadRazorpayCheckout.mockRejectedValueOnce(new Error("offline"));
    renderCheckout();

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    await user.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });
    expect(loadRazorpayCheckout).toHaveBeenCalledTimes(2);
  });

  it("closes the checkout window when it unmounts", async () => {
    const { unmount } = renderCheckout();
    await waitFor(() => {
      expect(instances).toHaveLength(1);
    });

    unmount();

    expect(latest().close).toHaveBeenCalledTimes(1);
  });
});
