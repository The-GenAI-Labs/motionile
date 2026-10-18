import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelSubscription,
  changeSubscription,
  createOrder,
  createSubscription,
  getOrder,
  getSubscription,
  listHistory,
  listProducts,
  verifyPayment,
  verifySubscription,
} from "@/features/billing/api/billing.api";
import { parseProductCode } from "@/features/billing/schemas/billing.schema";
import {
  getWallet,
  listDailyUsage,
  listLedger,
  listUsage,
} from "@/features/credits/api/credits.api";

import { order, ORDER_ID, products, subscription, wallet } from "./billing-fixtures";

const client = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));

vi.mock("@/lib/api/client", () => ({ apiClient: client }));

const KEY = "11111111-1111-4111-8111-111111111111";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("billing api", () => {
  it("reads the public products without authentication", async () => {
    client.get.mockResolvedValue({ data: products });

    await expect(listProducts()).resolves.toEqual(products);

    expect(client.get).toHaveBeenCalledExactlyOnceWith("/v1/billing/products");
  });

  it("rejects a products response that breaks the contract", async () => {
    client.get.mockResolvedValue({ data: { creditPacks: [{ code: "pack" }], subscriptions: [] } });

    await expect(listProducts()).rejects.toThrow();
  });

  it("creates an order from a product code only, with the idempotency key header", async () => {
    client.post.mockResolvedValue({
      data: {
        orderId: ORDER_ID,
        keyId: "rzp_test_key",
        razorpayOrderId: "order_Abc123",
        amountPaise: 19_900,
        currency: "INR",
        customerId: "cust_1",
        name: "Motionile",
        description: "Starter",
        prefill: { name: null, email: null, contact: null },
      },
    });

    await createOrder({ productCode: "pack_starter", idempotencyKey: KEY });

    expect(client.post).toHaveBeenCalledExactlyOnceWith(
      "/v1/billing/orders",
      { productCode: "pack_starter" },
      { authenticated: true, headers: { "Idempotency-Key": KEY } },
    );
  });

  it("refuses an invalid product code or idempotency key before calling the API", async () => {
    await expect(createOrder({ productCode: "Bad Code!", idempotencyKey: KEY })).rejects.toThrow();
    await expect(
      createSubscription({ productCode: "pro_monthly", idempotencyKey: "has space" }),
    ).rejects.toThrow();
    expect(client.post).not.toHaveBeenCalled();
  });

  it("verifies a payment with a key derived from the payment id", async () => {
    client.post.mockResolvedValue({
      data: { orderId: ORDER_ID, status: "paid", creditsGranted: 100 },
    });

    await expect(
      verifyPayment({
        razorpayOrderId: "order_Abc123",
        razorpayPaymentId: "pay_Abc123",
        razorpaySignature: "sig",
      }),
    ).resolves.toEqual({ orderId: ORDER_ID, status: "paid", creditsGranted: 100 });

    expect(client.post).toHaveBeenCalledExactlyOnceWith(
      "/v1/billing/payments/verify",
      {
        razorpayOrderId: "order_Abc123",
        razorpayPaymentId: "pay_Abc123",
        razorpaySignature: "sig",
      },
      { authenticated: true, headers: { "Idempotency-Key": "verify:pay_Abc123" } },
    );
  });

  it("verifies a subscription with a key derived from the payment id", async () => {
    client.post.mockResolvedValue({ data: subscription() });

    await verifySubscription({
      razorpaySubscriptionId: "sub_Abc123",
      razorpayPaymentId: "pay_Sub123",
      razorpaySignature: "sig",
    });

    expect(client.post).toHaveBeenCalledExactlyOnceWith(
      "/v1/billing/subscriptions/verify",
      {
        razorpaySubscriptionId: "sub_Abc123",
        razorpayPaymentId: "pay_Sub123",
        razorpaySignature: "sig",
      },
      { authenticated: true, headers: { "Idempotency-Key": "verify:pay_Sub123" } },
    );
  });

  it("reads an order only for a valid id", async () => {
    client.get.mockResolvedValue({ data: order() });

    await expect(getOrder(ORDER_ID)).resolves.toMatchObject({ id: ORDER_ID });
    await expect(getOrder("not-a-uuid")).rejects.toThrow();

    expect(client.get).toHaveBeenCalledExactlyOnceWith(`/v1/billing/orders/${ORDER_ID}`, {
      authenticated: true,
    });
  });

  it("pages through history with a cursor", async () => {
    client.get.mockResolvedValue({ data: { items: [], nextCursor: null } });

    await listHistory("cursor-2");

    expect(client.get).toHaveBeenCalledExactlyOnceWith("/v1/billing/history", {
      authenticated: true,
      params: { cursor: "cursor-2", limit: 20 },
    });
  });

  it("reads, cancels and changes the subscription", async () => {
    client.get.mockResolvedValue({ data: { subscription: subscription() } });
    client.post.mockResolvedValue({ data: subscription() });

    await getSubscription();
    await cancelSubscription();
    await changeSubscription("team_monthly");

    expect(client.get).toHaveBeenCalledWith("/v1/billing/subscription", { authenticated: true });
    expect(client.post).toHaveBeenNthCalledWith(1, "/v1/billing/subscription/cancel", undefined, {
      authenticated: true,
    });
    expect(client.post).toHaveBeenNthCalledWith(
      2,
      "/v1/billing/subscription/change",
      { productCode: "team_monthly" },
      { authenticated: true },
    );
  });

  it("accepts only well-formed product codes from links", () => {
    expect(parseProductCode("pack_starter")).toBe("pack_starter");
    expect(parseProductCode("PACK")).toBeNull();
    expect(parseProductCode(["pack_a", "pack_b"])).toBeNull();
    expect(parseProductCode(undefined)).toBeNull();
    expect(parseProductCode("../admin")).toBeNull();
  });
});

describe("credits api", () => {
  it("reads the wallet", async () => {
    client.get.mockResolvedValue({ data: wallet() });

    await expect(getWallet()).resolves.toEqual(wallet());

    expect(client.get).toHaveBeenCalledExactlyOnceWith("/v1/credits/wallet", {
      authenticated: true,
    });
  });

  it("pages through the ledger and usage", async () => {
    client.get.mockResolvedValue({ data: { items: [], nextCursor: null } });

    await listLedger("l-2");
    await listUsage("u-2");

    expect(client.get).toHaveBeenNthCalledWith(1, "/v1/credits/ledger", {
      authenticated: true,
      params: { cursor: "l-2", limit: 20 },
    });
    expect(client.get).toHaveBeenNthCalledWith(2, "/v1/credits/usage", {
      authenticated: true,
      params: { cursor: "u-2", limit: 20 },
    });
  });

  it("asks for the daily aggregate", async () => {
    client.get.mockResolvedValue({
      data: { items: [{ date: "2026-10-17", credits: 4, records: 1 }] },
    });

    await expect(listDailyUsage()).resolves.toEqual({
      items: [{ date: "2026-10-17", credits: 4, records: 1 }],
    });

    expect(client.get).toHaveBeenCalledExactlyOnceWith("/v1/credits/usage", {
      authenticated: true,
      params: { aggregate: "daily", limit: 20 },
    });
  });
});
