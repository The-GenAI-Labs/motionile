import { act, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OrderStatus } from "@/features/billing/components/order-status";
import {
  buildPollSchedule,
  isOrderSettled,
  ORDER_POLL_BUDGET_MS,
  ORDER_POLL_SCHEDULE,
} from "@/features/billing/hooks/use-order-status";
import { billingKeys } from "@/features/billing/query-keys";
import { creditsKeys } from "@/features/credits/query-keys";
import { ApiError } from "@/lib/api/api-error";

import { order, ORDER_ID, subscription } from "./billing-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({ getOrder: vi.fn(), getSubscription: vi.fn() }));

vi.mock("@/features/billing/api/billing.api", () => api);

const notFound = () =>
  new ApiError({
    kind: "http",
    status: 404,
    code: "order_not_found",
    title: "Not found",
    detail: null,
  });

const flush = async (ms = 0) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  api.getSubscription.mockResolvedValue({ subscription: null });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("order polling schedule", () => {
  it("backs off from one second to eight and stops after about two minutes", () => {
    expect(ORDER_POLL_SCHEDULE.slice(0, 6)).toEqual([1_000, 2_000, 4_000, 8_000, 8_000, 8_000]);
    expect(Math.max(...ORDER_POLL_SCHEDULE)).toBe(8_000);
    const total = ORDER_POLL_SCHEDULE.reduce((sum, delay) => sum + delay, 0);
    expect(total).toBeGreaterThanOrEqual(ORDER_POLL_BUDGET_MS);
    expect(total - (ORDER_POLL_SCHEDULE.at(-1) ?? 0)).toBeLessThan(ORDER_POLL_BUDGET_MS);
  });

  it("builds custom schedules", () => {
    expect(buildPollSchedule(100, 300, 1_000)).toEqual([100, 200, 300, 300, 300]);
  });

  it("treats paid, failed, expired and cancelled as final", () => {
    expect(
      ["paid", "failed", "expired", "cancelled"].map((s) => isOrderSettled(s as never)),
    ).toEqual([true, true, true, true]);
    expect(isOrderSettled("created")).toBe(false);
    expect(isOrderSettled("pending")).toBe(false);
  });
});

describe("OrderStatus", () => {
  it("shows a checking state while the first response is pending", () => {
    api.getOrder.mockReturnValue(new Promise(() => undefined));

    renderWithQuery(<OrderStatus orderId={ORDER_ID} />);

    expect(screen.getByRole("heading", { name: "Checking your payment" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Checking your payment");
  });

  it("polls with backoff until the order is paid, then reports the credits", async () => {
    api.getOrder
      .mockResolvedValueOnce(order({ status: "pending" }))
      .mockResolvedValueOnce(order({ status: "pending" }))
      .mockResolvedValue(order({ status: "paid", paidAt: "2026-10-18T10:00:00Z" }));

    const { client } = renderWithQuery(<OrderStatus orderId={ORDER_ID} />);
    const invalidate = vi.spyOn(client, "invalidateQueries");

    await flush();
    expect(api.getOrder).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "Confirming your payment" })).toBeInTheDocument();

    await flush(999);
    expect(api.getOrder).toHaveBeenCalledTimes(1);
    await flush(1);
    expect(api.getOrder).toHaveBeenCalledTimes(2);

    await flush(1_999);
    expect(api.getOrder).toHaveBeenCalledTimes(2);
    await flush(1);
    expect(api.getOrder).toHaveBeenCalledTimes(3);

    expect(screen.getByRole("heading", { name: "Payment received" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("100 credits were added to your wallet.");
    expect(screen.getByRole("link", { name: "View billing overview" })).toHaveAttribute(
      "href",
      "/billing",
    );
    expect(screen.getByRole("link", { name: "Create a video" })).toHaveAttribute("href", "/create");
    const keys = invalidate.mock.calls.map(([filters]) => filters?.queryKey);
    expect(keys).toEqual(
      expect.arrayContaining([
        creditsKeys.wallet(),
        creditsKeys.ledger(),
        billingKeys.history(),
        billingKeys.subscription(),
      ]),
    );

    await flush(60_000);
    expect(api.getOrder).toHaveBeenCalledTimes(3);
  });

  it("announces a paid order the webhook already settled without polling again", async () => {
    api.getOrder.mockResolvedValue(order({ status: "paid" }));

    renderWithQuery(<OrderStatus orderId={ORDER_ID} />);
    await flush();

    expect(screen.getByRole("heading", { name: "Payment received" })).toBeInTheDocument();
    await flush(30_000);
    expect(api.getOrder).toHaveBeenCalledTimes(1);
  });

  it("shows the subscription state for a paid subscription order", async () => {
    api.getOrder.mockResolvedValue(
      order({
        status: "paid",
        kind: "subscription",
        productName: "Pro monthly",
        creditsGranted: 0,
      }),
    );
    api.getSubscription.mockResolvedValue({ subscription: subscription() });

    renderWithQuery(<OrderStatus orderId={ORDER_ID} />);
    await flush();

    expect(screen.getByRole("status")).toHaveTextContent("Pro monthly: Active");
    expect(screen.getByRole("status")).toHaveTextContent("added as each billing period is charged");
  });

  it("explains a failed payment and offers another try", async () => {
    api.getOrder.mockResolvedValue(order({ status: "failed", failureReason: "Card declined" }));

    renderWithQuery(<OrderStatus orderId={ORDER_ID} />);
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent("Card declined");
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute(
      "href",
      "/billing/credits",
    );
    await flush(30_000);
    expect(api.getOrder).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["expired", "Order expired", /expired before a payment/],
    ["cancelled", "Order cancelled", /no payment was taken/],
  ] as const)("shows a %s order", async (status, heading, message) => {
    api.getOrder.mockResolvedValue(order({ status, kind: "subscription" }));

    renderWithQuery(<OrderStatus orderId={ORDER_ID} />);
    await flush();

    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute(
      "href",
      "/billing/plans",
    );
  });

  it("reports an order that does not exist and stops polling", async () => {
    api.getOrder.mockRejectedValue(notFound());

    renderWithQuery(<OrderStatus orderId={ORDER_ID} />);
    await flush();

    expect(screen.getByRole("heading", { name: "Order not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View payment history" })).toHaveAttribute(
      "href",
      "/billing/history",
    );
    await flush(30_000);
    expect(api.getOrder).toHaveBeenCalledTimes(1);
  });

  it("shows a retryable error when the first request fails", async () => {
    api.getOrder.mockRejectedValueOnce(ApiError.ofKind("network")).mockResolvedValue(order());

    renderWithQuery(<OrderStatus orderId={ORDER_ID} />);
    await flush();

    expect(screen.getByRole("alert")).toHaveTextContent(/Something went wrong|try again/i);
    await act(async () => {
      screen.getByRole("button", { name: "Try again" }).click();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByRole("heading", { name: "Confirming your payment" })).toBeInTheDocument();
  });

  it("stops polling after the budget and lets the user check again", async () => {
    api.getOrder.mockResolvedValue(order({ status: "pending" }));

    renderWithQuery(<OrderStatus orderId={ORDER_ID} />);
    await flush();
    await flush(ORDER_POLL_BUDGET_MS + 10_000);

    expect(screen.getByRole("heading", { name: "Still processing" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("taking longer than usual");
    const calls = api.getOrder.mock.calls.length;
    expect(calls).toBe(ORDER_POLL_SCHEDULE.length + 1);
    await flush(60_000);
    expect(api.getOrder).toHaveBeenCalledTimes(calls);

    api.getOrder.mockResolvedValue(order({ status: "paid" }));
    await act(async () => {
      screen.getByRole("button", { name: "Check again" }).click();
      await vi.advanceTimersByTimeAsync(0);
    });
    await flush();

    expect(screen.getByRole("heading", { name: "Payment received" })).toBeInTheDocument();
  });
});
