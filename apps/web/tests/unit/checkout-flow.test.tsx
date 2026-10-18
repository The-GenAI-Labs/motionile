import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";

import { CreditPackStore } from "@/features/billing/components/credit-pack-store";
import { useCheckout } from "@/features/billing/hooks/use-checkout";
import { ApiError } from "@/lib/api/api-error";
import type { CheckoutProps } from "@/lib/razorpay/checkout.types";

import { ORDER_ID, products } from "./billing-fixtures";
import { makeTestQueryClient, renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  listProducts: vi.fn(),
  createOrder: vi.fn(),
  createSubscription: vi.fn(),
  verifyPayment: vi.fn(),
  verifySubscription: vi.fn(),
}));
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
const launched = vi.hoisted(() => ({ props: null as CheckoutProps | null }));

vi.mock("@/features/billing/api/billing.api", () => api);
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/razorpay/checkout-launcher", () => ({
  CheckoutLauncher: (props: CheckoutProps) => {
    launched.props = props;
    return <p role="status">Checkout open for {props.target.description}</p>;
  },
}));

const KEY_ONE = "11111111-1111-4111-8111-111111111111";
const KEY_TWO = "22222222-2222-4222-8222-222222222222";
const KEY_THREE = "33333333-3333-4333-8333-333333333333";

const orderCheckout = {
  orderId: ORDER_ID,
  keyId: "rzp_test_key",
  razorpayOrderId: "order_Abc123",
  amountPaise: 19_900,
  currency: "INR",
  customerId: "cust_1",
  name: "Motionile",
  description: "Starter credit pack",
  prefill: { name: null, email: null, contact: null },
};

const subscriptionCheckout = {
  orderId: ORDER_ID,
  subscriptionId: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e02",
  keyId: "rzp_test_key",
  razorpaySubscriptionId: "sub_Abc123",
  customerId: "cust_1",
  name: "Motionile",
  description: "Pro monthly",
  prefill: { name: null, email: null, contact: null },
};

const httpError = (status: number, code: string) =>
  new ApiError({ kind: "http", status, code, title: "Problem", detail: null });

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={makeTestQueryClient()}>{children}</QueryClientProvider>
);

let randomUuid: MockInstance<Crypto["randomUUID"]>;

beforeEach(() => {
  vi.clearAllMocks();
  launched.props = null;
  api.listProducts.mockResolvedValue(products);
  randomUuid = vi.spyOn(globalThis.crypto, "randomUUID");
  randomUuid
    .mockReturnValueOnce(KEY_ONE)
    .mockReturnValueOnce(KEY_TWO)
    .mockReturnValueOnce(KEY_THREE);
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("useCheckout", () => {
  it("creates an order with a fresh idempotency key and exposes the checkout target", async () => {
    api.createOrder.mockResolvedValue(orderCheckout);
    const { result } = renderHook(() => useCheckout(), { wrapper });

    await act(async () => {
      await result.current.start("credit_pack", "pack_starter");
    });

    expect(api.createOrder).toHaveBeenCalledExactlyOnceWith({
      productCode: "pack_starter",
      idempotencyKey: KEY_ONE,
    });
    expect(result.current.target).toEqual({
      kind: "order",
      orderId: ORDER_ID,
      keyId: "rzp_test_key",
      razorpayOrderId: "order_Abc123",
      amountPaise: 19_900,
      currency: "INR",
      description: "Starter credit pack",
      prefill: { name: null, email: null, contact: null },
    });
    expect(result.current.error).toBeNull();
  });

  it("reuses the same idempotency key when the same click is retried after a transient failure", async () => {
    api.createOrder
      .mockRejectedValueOnce(ApiError.ofKind("network"))
      .mockRejectedValueOnce(httpError(409, "idempotency_request_in_progress"))
      .mockResolvedValueOnce(orderCheckout);
    const { result } = renderHook(() => useCheckout(), { wrapper });

    await act(async () => {
      await result.current.start("credit_pack", "pack_starter");
    });
    expect(result.current.error).not.toBeNull();
    expect(result.current.target).toBeNull();
    await act(async () => {
      await result.current.start("credit_pack", "pack_starter");
    });
    await act(async () => {
      await result.current.start("credit_pack", "pack_starter");
    });

    expect(
      api.createOrder.mock.calls.map(
        ([input]) => (input as { idempotencyKey: string }).idempotencyKey,
      ),
    ).toEqual([KEY_ONE, KEY_ONE, KEY_ONE]);
    expect(randomUuid).toHaveBeenCalledTimes(1);
    expect(result.current.target?.kind).toBe("order");
  });

  it("uses a new key for another product and after a success", async () => {
    api.createOrder
      .mockRejectedValueOnce(ApiError.ofKind("timeout"))
      .mockResolvedValue(orderCheckout);
    const { result } = renderHook(() => useCheckout(), { wrapper });

    await act(async () => {
      await result.current.start("credit_pack", "pack_starter");
    });
    await act(async () => {
      await result.current.start("credit_pack", "pack_creator");
    });
    await act(async () => {
      await result.current.start("credit_pack", "pack_creator");
    });

    expect(
      api.createOrder.mock.calls.map(
        ([input]) => (input as { idempotencyKey: string }).idempotencyKey,
      ),
    ).toEqual([KEY_ONE, KEY_TWO, KEY_THREE]);
  });

  it("does not reuse the key after a client error", async () => {
    api.createSubscription
      .mockRejectedValueOnce(httpError(409, "subscription_exists"))
      .mockResolvedValueOnce(subscriptionCheckout);
    const { result } = renderHook(() => useCheckout(), { wrapper });

    await act(async () => {
      await result.current.start("subscription", "pro_monthly");
    });
    expect(result.current.error).toBeInstanceOf(ApiError);
    await act(async () => {
      await result.current.start("subscription", "pro_monthly");
    });

    expect(
      api.createSubscription.mock.calls.map(
        ([input]) => (input as { idempotencyKey: string }).idempotencyKey,
      ),
    ).toEqual([KEY_ONE, KEY_TWO]);
    expect(result.current.target).toMatchObject({
      kind: "subscription",
      razorpaySubscriptionId: "sub_Abc123",
    });
    expect(result.current.error).toBeNull();
  });

  it("verifies orders and subscriptions with the matching endpoint and closes", async () => {
    api.createOrder.mockResolvedValue(orderCheckout);
    api.verifyPayment.mockResolvedValue({});
    api.verifySubscription.mockResolvedValue({});
    const { result } = renderHook(() => useCheckout(), { wrapper });

    await act(async () => {
      await result.current.start("credit_pack", "pack_starter");
    });
    await act(async () => {
      await result.current.verify({
        kind: "order",
        razorpayOrderId: "order_Abc123",
        razorpayPaymentId: "pay_Abc123",
        razorpaySignature: "sig",
      });
      await result.current.verify({
        kind: "subscription",
        razorpaySubscriptionId: "sub_Abc123",
        razorpayPaymentId: "pay_Sub123",
        razorpaySignature: "sub-sig",
      });
    });

    expect(api.verifyPayment).toHaveBeenCalledExactlyOnceWith({
      razorpayOrderId: "order_Abc123",
      razorpayPaymentId: "pay_Abc123",
      razorpaySignature: "sig",
    });
    expect(api.verifySubscription).toHaveBeenCalledExactlyOnceWith({
      razorpaySubscriptionId: "sub_Abc123",
      razorpayPaymentId: "pay_Sub123",
      razorpaySignature: "sub-sig",
    });
    act(() => {
      result.current.close();
    });
    expect(result.current.target).toBeNull();
  });
});

describe("CreditPackStore", () => {
  it("lists the packs and starts checkout for the chosen one", async () => {
    const user = userEvent.setup();
    api.createOrder.mockResolvedValue(orderCheckout);
    renderWithQuery(<CreditPackStore />);

    const creator = await screen.findByRole("article", { name: "Creator" });
    expect(creator).toHaveTextContent("500 credits that never expire");
    await user.click(await screen.findByRole("button", { name: "Buy Starter" }));

    expect(await screen.findByText("Checkout open for Starter credit pack")).toBeInTheDocument();
    expect(api.createOrder).toHaveBeenCalledExactlyOnceWith({
      productCode: "pack_starter",
      idempotencyKey: KEY_ONE,
    });
    expect(screen.getByRole("button", { name: "Buy Creator" })).toBeDisabled();
  });

  it("goes to the status page whatever the verification outcome", async () => {
    const user = userEvent.setup();
    api.createOrder.mockResolvedValue(orderCheckout);
    renderWithQuery(<CreditPackStore />);

    await user.click(await screen.findByRole("button", { name: "Buy Starter" }));
    await screen.findByText("Checkout open for Starter credit pack");
    act(() => {
      launched.props?.onFinished(ORDER_ID);
    });

    expect(router.push).toHaveBeenCalledExactlyOnceWith(`/billing/status/${ORDER_ID}`);
  });

  it("returns to the packs when checkout is dismissed", async () => {
    const user = userEvent.setup();
    api.createOrder.mockResolvedValue(orderCheckout);
    renderWithQuery(<CreditPackStore />);

    await user.click(await screen.findByRole("button", { name: "Buy Starter" }));
    await screen.findByText("Checkout open for Starter credit pack");
    act(() => {
      launched.props?.onDismiss();
    });

    expect(screen.queryByText("Checkout open for Starter credit pack")).toBeNull();
    expect(screen.getByRole("button", { name: "Buy Starter" })).toBeEnabled();
  });

  it("explains why an order could not be created", async () => {
    const user = userEvent.setup();
    api.createOrder.mockRejectedValue(httpError(502, "payment_provider_error"));
    renderWithQuery(<CreditPackStore />);

    await user.click(await screen.findByRole("button", { name: "Buy Starter" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The payment provider returned an error. Please try again shortly.",
    );
    expect(screen.queryByText(/Checkout open/)).toBeNull();
  });

  it("starts checkout for the pack in the link and cleans the address", async () => {
    api.createOrder.mockResolvedValue(orderCheckout);
    window.history.replaceState(null, "", "/billing/credits?pack=pack_creator");

    renderWithQuery(<CreditPackStore requestedPack="pack_creator" />);

    await screen.findByText("Checkout open for Starter credit pack");
    expect(api.createOrder).toHaveBeenCalledExactlyOnceWith({
      productCode: "pack_creator",
      idempotencyKey: KEY_ONE,
    });
    expect(window.location.pathname + window.location.search).toBe("/billing/credits");
  });

  it("says so when the linked pack no longer exists", async () => {
    renderWithQuery(<CreditPackStore requestedPack="pack_retired" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("no longer available");
    expect(api.createOrder).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Buy Starter" })).toBeEnabled();
  });

  it("shows a retryable error when the packs cannot be loaded", async () => {
    const user = userEvent.setup();
    api.listProducts.mockRejectedValueOnce(ApiError.ofKind("network")).mockResolvedValue(products);
    renderWithQuery(<CreditPackStore />);

    await user.click(await screen.findByRole("button", { name: "Try again" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Buy Starter" })).toBeInTheDocument();
    });
  });
});
