import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CheckoutTarget } from "@/lib/razorpay/checkout.types";
import { FakeCheckout } from "@/lib/razorpay/fake-checkout";

const api = vi.hoisted(() => ({
  payFakeOrder: vi.fn(),
  authorizeFakeSubscription: vi.fn(),
  transitionFakeSubscription: vi.fn(),
  deliverFakeSubscriptionCharge: vi.fn(),
}));

vi.mock("@/lib/razorpay/fake-api", () => api);

const ORDER_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e01";

const orderTarget: CheckoutTarget = {
  kind: "order",
  orderId: ORDER_ID,
  keyId: "rzp_test_key",
  razorpayOrderId: "order_Abc123",
  amountPaise: 19_900,
  currency: "INR",
  description: "Starter credit pack",
  prefill: { name: null, email: null, contact: null },
};

const subscriptionTarget: CheckoutTarget = {
  kind: "subscription",
  orderId: ORDER_ID,
  keyId: "rzp_test_key",
  razorpaySubscriptionId: "sub_Abc123",
  description: "Pro monthly",
  prefill: { name: null, email: null, contact: null },
};

const orderPayment = {
  razorpay_order_id: "order_Abc123",
  razorpay_payment_id: "pay_Abc123",
  razorpay_signature: "signature",
  paymentStatus: "captured",
  webhooks: [],
};

const authorization = {
  razorpay_payment_id: "pay_Sub123",
  razorpay_subscription_id: "sub_Abc123",
  razorpay_signature: "sub-signature",
  subscriptionStatus: "authenticated",
  webhooks: [],
};

const renderFake = (target: CheckoutTarget = orderTarget) => {
  const verify = vi.fn(() => Promise.resolve({}));
  const onFinished = vi.fn();
  const onDismiss = vi.fn();
  render(
    <FakeCheckout target={target} verify={verify} onFinished={onFinished} onDismiss={onDismiss} />,
  );
  return { verify, onFinished, onDismiss };
};

beforeEach(() => {
  vi.clearAllMocks();
  api.payFakeOrder.mockResolvedValue(orderPayment);
  api.authorizeFakeSubscription.mockResolvedValue(authorization);
  api.transitionFakeSubscription.mockResolvedValue({});
  api.deliverFakeSubscriptionCharge.mockResolvedValue({});
});

describe("FakeCheckout for orders", () => {
  it("offers every simulated outcome in an accessible dialog", () => {
    renderFake();

    const dialog = screen.getByRole("dialog", { name: "Simulated checkout" });
    expect(dialog).toHaveTextContent("Starter credit pack");
    for (const name of [
      "Pay successfully",
      "Pay and skip verification",
      "Fail payment",
      "Close without paying",
    ]) {
      expect(screen.getByRole("button", { name })).toBeEnabled();
    }
  });

  it("pays, verifies and then goes to the status page", async () => {
    const user = userEvent.setup();
    const { verify, onFinished } = renderFake();

    await user.click(screen.getByRole("button", { name: "Pay successfully" }));

    await waitFor(() => {
      expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
    });
    expect(api.payFakeOrder).toHaveBeenCalledExactlyOnceWith("order_Abc123", "success");
    expect(verify).toHaveBeenCalledExactlyOnceWith({
      kind: "order",
      razorpayOrderId: "order_Abc123",
      razorpayPaymentId: "pay_Abc123",
      razorpaySignature: "signature",
    });
  });

  it("goes straight to the status page and asks for webhooks when skipping verification", async () => {
    const user = userEvent.setup();
    const { verify, onFinished } = renderFake();

    await user.click(screen.getByRole("button", { name: "Pay and skip verification" }));

    await waitFor(() => {
      expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
    });
    expect(api.payFakeOrder).toHaveBeenCalledExactlyOnceWith("order_Abc123", "success", [
      "payment.captured",
      "order.paid",
    ]);
    expect(verify).not.toHaveBeenCalled();
  });

  it("still goes to the status page when verification fails", async () => {
    const user = userEvent.setup();
    const { verify, onFinished } = renderFake();
    verify.mockRejectedValueOnce(new Error("verify failed"));

    await user.click(screen.getByRole("button", { name: "Pay successfully" }));

    await waitFor(() => {
      expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
    });
  });

  it("reports a simulated failure and stays open for another attempt", async () => {
    const user = userEvent.setup();
    const { onFinished } = renderFake();

    await user.click(screen.getByRole("button", { name: "Fail payment" }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts[0]).toHaveTextContent("Payment failed");
    expect(api.payFakeOrder).toHaveBeenCalledExactlyOnceWith("order_Abc123", "failure");
    expect(onFinished).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Pay successfully" })).toBeEnabled();
  });

  it("explains when the simulation cannot reach the API", async () => {
    const user = userEvent.setup();
    api.payFakeOrder.mockRejectedValueOnce(new Error("offline"));
    const { onFinished } = renderFake();

    await user.click(screen.getByRole("button", { name: "Pay successfully" }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts[0]).toHaveTextContent("could not reach the API");
    expect(onFinished).not.toHaveBeenCalled();
  });

  it("closes without paying and can be reopened or cancelled", async () => {
    const user = userEvent.setup();
    const { onDismiss, onFinished } = renderFake();

    await user.click(screen.getByRole("button", { name: "Close without paying" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Checkout was closed");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByRole("dialog", { name: "Simulated checkout" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close without paying" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
    expect(onFinished).not.toHaveBeenCalled();
    expect(api.payFakeOrder).not.toHaveBeenCalled();
  });
});

describe("FakeCheckout for subscriptions", () => {
  it("authorizes, verifies and then activates the subscription", async () => {
    const user = userEvent.setup();
    const { verify, onFinished } = renderFake(subscriptionTarget);

    await user.click(screen.getByRole("button", { name: "Pay successfully" }));

    await waitFor(() => {
      expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
    });
    expect(api.authorizeFakeSubscription).toHaveBeenCalledExactlyOnceWith("sub_Abc123");
    expect(verify).toHaveBeenCalledExactlyOnceWith({
      kind: "subscription",
      razorpaySubscriptionId: "sub_Abc123",
      razorpayPaymentId: "pay_Sub123",
      razorpaySignature: "sub-signature",
    });
    expect(api.transitionFakeSubscription).toHaveBeenCalledExactlyOnceWith(
      "sub_Abc123",
      "activated",
    );
    expect(api.deliverFakeSubscriptionCharge).toHaveBeenCalledExactlyOnceWith(
      "sub_Abc123",
      "pay_Sub123",
    );
    expect(verify.mock.invocationCallOrder[0]).toBeLessThan(
      api.transitionFakeSubscription.mock.invocationCallOrder[0] ?? 0,
    );
  });

  it("activates without verifying when skipping verification", async () => {
    const user = userEvent.setup();
    const { verify, onFinished } = renderFake(subscriptionTarget);

    await user.click(screen.getByRole("button", { name: "Pay and skip verification" }));

    await waitFor(() => {
      expect(onFinished).toHaveBeenCalledExactlyOnceWith(ORDER_ID);
    });
    expect(verify).not.toHaveBeenCalled();
    expect(api.transitionFakeSubscription).toHaveBeenCalledTimes(1);
    expect(api.deliverFakeSubscriptionCharge).toHaveBeenCalledTimes(1);
  });

  it("fails without touching the API", async () => {
    const user = userEvent.setup();
    const { onFinished } = renderFake(subscriptionTarget);

    await user.click(screen.getByRole("button", { name: "Fail payment" }));

    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("Payment failed");
    expect(api.authorizeFakeSubscription).not.toHaveBeenCalled();
    expect(onFinished).not.toHaveBeenCalled();
  });
});
