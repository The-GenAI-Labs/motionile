import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BillingHistory } from "@/features/billing/components/billing-history";
import { ApiError } from "@/lib/api/api-error";

import { renderWithQuery } from "./render-with-query";

const billingApi = vi.hoisted(() => ({ listHistory: vi.fn() }));
const creditsApi = vi.hoisted(() => ({
  listLedger: vi.fn(),
  listUsage: vi.fn(),
  listDailyUsage: vi.fn(),
}));

vi.mock("@/features/billing/api/billing.api", () => billingApi);
vi.mock("@/features/credits/api/credits.api", () => creditsApi);

const ORDER_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e01";
const uuid = (suffix: number): string =>
  `0197c5a2-1b2c-7d3e-8f40-${String(suffix).padStart(12, "0")}`;

const historyItem = (index: number, overrides: Record<string, unknown> = {}) => ({
  id: uuid(index),
  type: "order",
  title: `Starter order ${String(index)}`,
  status: "paid",
  amountPaise: 19_900,
  currency: "INR",
  creditsGranted: 100,
  createdAt: "2026-10-17T10:30:00Z",
  orderId: ORDER_ID,
  paymentId: null,
  ...overrides,
});

const ledgerEntry = (index: number, overrides: Record<string, unknown> = {}) => ({
  id: uuid(100 + index),
  reason: "purchase",
  delta: 100,
  reservedDelta: 0,
  balanceAfter: 100,
  reservedAfter: 0,
  refType: "payment",
  refId: uuid(200 + index),
  createdAt: "2026-10-17T10:30:00Z",
  ...overrides,
});

const usageEntry = (index: number, overrides: Record<string, unknown> = {}) => ({
  id: uuid(300 + index),
  stage: "narration_audio",
  credits: 12,
  jobId: uuid(400 + index),
  publicationId: null,
  createdAt: "2026-10-17T11:00:00Z",
  ...overrides,
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(440);
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockReturnValue(800);
  billingApi.listHistory.mockResolvedValue({ items: [historyItem(1)], nextCursor: null });
  creditsApi.listLedger.mockResolvedValue({ items: [ledgerEntry(1)], nextCursor: null });
  creditsApi.listUsage.mockResolvedValue({ items: [usageEntry(1)], nextCursor: null });
  creditsApi.listDailyUsage.mockResolvedValue({
    items: [{ date: "2026-10-17", credits: 40, records: 4 }],
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BillingHistory payments tab", () => {
  it("lists orders, payments and refunds with INR amounts and links to the order", async () => {
    billingApi.listHistory.mockResolvedValue({
      items: [
        historyItem(1),
        historyItem(2, { type: "payment", title: "Payment for Starter", orderId: null }),
        historyItem(3, {
          type: "refund",
          title: "Refund for Starter",
          status: "processed",
          amountPaise: 5_000,
          creditsGranted: null,
        }),
      ],
      nextCursor: null,
    });

    renderWithQuery(<BillingHistory />);

    const table = await screen.findByRole("table", { name: "Payments and orders" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Date", "Description", "Status", "Amount (incl. GST)", "Credits", "Details"]);
    expect(within(table).getByText("Starter order 1")).toBeInTheDocument();
    expect(within(table).getAllByText("₹199")).toHaveLength(2);
    expect(within(table).getByText("-₹50")).toBeInTheDocument();
    expect(within(table).getByRole("link", { name: "View Starter order 1" })).toHaveAttribute(
      "href",
      `/billing/status/${ORDER_ID}`,
    );
    expect(within(table).queryByRole("link", { name: "View Payment for Starter" })).toBeNull();
  });

  it("loads the next page with the cursor", async () => {
    const user = userEvent.setup();
    billingApi.listHistory
      .mockResolvedValueOnce({ items: [historyItem(1)], nextCursor: "cursor-2" })
      .mockResolvedValueOnce({ items: [historyItem(2)], nextCursor: null });

    renderWithQuery(<BillingHistory />);
    await screen.findByText("Starter order 1");
    await user.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Starter order 2")).toBeInTheDocument();
    expect(billingApi.listHistory).toHaveBeenNthCalledWith(1, undefined);
    expect(billingApi.listHistory).toHaveBeenNthCalledWith(2, "cursor-2");
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("virtualizes a long history", async () => {
    billingApi.listHistory.mockResolvedValue({
      items: Array.from({ length: 500 }, (_, index) => historyItem(index + 1)),
      nextCursor: null,
    });

    renderWithQuery(<BillingHistory />);

    const table = await screen.findByRole("table", { name: "Payments and orders" });
    expect(table).toHaveAttribute("aria-rowcount", "501");
    expect(within(table).getAllByRole("row").length).toBeLessThan(60);
  });

  it("shows an empty state", async () => {
    billingApi.listHistory.mockResolvedValue({ items: [], nextCursor: null });

    renderWithQuery(<BillingHistory />);

    expect(await screen.findByText("No payments or orders yet.")).toBeInTheDocument();
  });

  it("shows a retryable error", async () => {
    const user = userEvent.setup();
    billingApi.listHistory
      .mockRejectedValueOnce(ApiError.ofKind("network"))
      .mockResolvedValue({ items: [historyItem(1)], nextCursor: null });

    renderWithQuery(<BillingHistory />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/Something went wrong/);
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Starter order 1")).toBeInTheDocument();
  });
});

describe("BillingHistory ledger tab", () => {
  it("shows credit changes with readable activity names", async () => {
    const user = userEvent.setup();
    creditsApi.listLedger.mockResolvedValue({
      items: [
        ledgerEntry(1),
        ledgerEntry(2, {
          reason: "reserve",
          delta: 0,
          reservedDelta: 30,
          balanceAfter: 100,
          reservedAfter: 30,
        }),
        ledgerEntry(3, {
          reason: "commit",
          delta: -25,
          reservedDelta: -30,
          balanceAfter: 75,
          reservedAfter: 0,
        }),
      ],
      nextCursor: null,
    });

    renderWithQuery(<BillingHistory />);
    await user.click(screen.getByRole("tab", { name: "Credit ledger" }));

    const table = await screen.findByRole("table", { name: "Credit ledger" });
    expect(within(table).getByText("Credit pack purchase")).toBeInTheDocument();
    expect(within(table).getByText("Reserved for a task")).toBeInTheDocument();
    expect(within(table).getByText("Spent on a task")).toBeInTheDocument();
    expect(within(table).getByText("+100")).toBeInTheDocument();
    expect(within(table).getByText("+30")).toBeInTheDocument();
    expect(within(table).getByText("-25")).toBeInTheDocument();
    expect(within(table).getByText("75")).toBeInTheDocument();
  });

  it("paginates the ledger", async () => {
    const user = userEvent.setup();
    creditsApi.listLedger
      .mockResolvedValueOnce({ items: [ledgerEntry(1)], nextCursor: "ledger-2" })
      .mockResolvedValueOnce({
        items: [ledgerEntry(2, { reason: "expiry", delta: -10 })],
        nextCursor: null,
      });

    renderWithQuery(<BillingHistory />);
    await user.click(screen.getByRole("tab", { name: "Credit ledger" }));
    await user.click(await screen.findByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Credits expired")).toBeInTheDocument();
    expect(creditsApi.listLedger).toHaveBeenLastCalledWith("ledger-2");
  });
});

describe("BillingHistory usage tab", () => {
  it("shows usage entries and switches to daily totals", async () => {
    const user = userEvent.setup();
    renderWithQuery(<BillingHistory />);

    await user.click(screen.getByRole("tab", { name: "Usage" }));
    const entries = await screen.findByRole("table", { name: "Credit usage" });
    expect(within(entries).getByText("Narration Audio")).toBeInTheDocument();
    expect(within(entries).getByText("Video generation")).toBeInTheDocument();
    expect(creditsApi.listDailyUsage).not.toHaveBeenCalled();

    const toggle = screen.getByRole("switch", { name: "Daily totals" });
    expect(toggle).not.toBeChecked();
    await user.click(toggle);

    const daily = await screen.findByRole("table", {
      name: "Daily credit usage for the last 30 days",
    });
    expect(within(daily).getByText("40")).toBeInTheDocument();
    expect(within(daily).getByText("4")).toBeInTheDocument();
    expect(toggle).toBeChecked();
  });

  it("shows an empty state for daily totals", async () => {
    const user = userEvent.setup();
    creditsApi.listDailyUsage.mockResolvedValue({ items: [] });
    renderWithQuery(<BillingHistory />);

    await user.click(screen.getByRole("tab", { name: "Usage" }));
    await user.click(screen.getByRole("switch", { name: "Daily totals" }));

    await waitFor(() => {
      expect(screen.getByText("No credits were used in the last 30 days.")).toBeInTheDocument();
    });
  });

  it("shows a retryable error for daily totals", async () => {
    const user = userEvent.setup();
    creditsApi.listDailyUsage
      .mockRejectedValueOnce(ApiError.ofKind("network"))
      .mockResolvedValue({ items: [{ date: "2026-10-16", credits: 7, records: 1 }] });
    renderWithQuery(<BillingHistory />);

    await user.click(screen.getByRole("tab", { name: "Usage" }));
    await user.click(screen.getByRole("switch", { name: "Daily totals" }));
    await user.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByText("7")).toBeInTheDocument();
  });
});
