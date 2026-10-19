import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import * as credits from "@/app/(user)/billing/credits/page";
import * as history from "@/app/(user)/billing/history/page";
import * as overview from "@/app/(user)/billing/page";
import * as plans from "@/app/(user)/billing/plans/page";
import * as status from "@/app/(user)/billing/status/[orderId]/page";
import { CreditPackStore } from "@/features/billing/components/credit-pack-store";
import { OrderStatus } from "@/features/billing/components/order-status";
import { PlansManager } from "@/features/billing/components/plans-manager";

import { ORDER_ID } from "./billing-fixtures";

const { notFound } = vi.hoisted(() => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));

vi.mock("next/navigation", () => ({ notFound }));

const findElement = (node: ReactElement, type: unknown): ReactElement | undefined => {
  if (node.type === type) {
    return node;
  }
  const children = (node.props as { children?: unknown }).children;
  for (const child of Array.isArray(children) ? (children as unknown[]) : [children]) {
    if (typeof child === "object" && child !== null && "type" in child) {
      const match = findElement(child as ReactElement, type);
      if (match) {
        return match;
      }
    }
  }
  return undefined;
};

describe("billing pages", () => {
  it.each([
    ["/billing", overview.metadata],
    ["/billing/plans", plans.metadata],
    ["/billing/credits", credits.metadata],
    ["/billing/history", history.metadata],
    ["/billing", status.metadata],
  ])("%s is private and has a canonical url", (path, metadata) => {
    expect(metadata.robots).toEqual({ index: false, follow: false });
    expect(metadata.alternates?.canonical).toBe(`https://motionile.test${path}`);
    expect(metadata.description).toBeTruthy();
  });

  it("gives every billing page its own description", () => {
    const descriptions = [overview, plans, credits, history, status].map(
      (page) => page.metadata.description,
    );

    expect(new Set(descriptions).size).toBe(descriptions.length);
  });

  it("passes a valid plan from the link to the plans manager", async () => {
    const page = await plans.default({ searchParams: Promise.resolve({ plan: "pro_yearly" }) });

    expect(findElement(page, PlansManager)?.props).toEqual({ requestedPlan: "pro_yearly" });
  });

  it("ignores a malformed plan or pack in the link", async () => {
    const plansPage = await plans.default({ searchParams: Promise.resolve({ plan: "../etc" }) });
    const creditsPage = await credits.default({
      searchParams: Promise.resolve({ pack: ["a", "b"] }),
    });

    expect(findElement(plansPage, PlansManager)?.props).toEqual({ requestedPlan: null });
    expect(findElement(creditsPage, CreditPackStore)?.props).toEqual({ requestedPack: null });
  });

  it("passes a valid pack from the link to the credit store", async () => {
    const page = await credits.default({
      searchParams: Promise.resolve({ pack: "pack_starter" }),
    });

    expect(findElement(page, CreditPackStore)?.props).toEqual({ requestedPack: "pack_starter" });
  });

  it("shows the status of a valid order id", async () => {
    const page = await status.default({ params: Promise.resolve({ orderId: ORDER_ID }) });

    expect(findElement(page, OrderStatus)?.props).toEqual({ orderId: ORDER_ID });
  });

  it("answers not found for an order id that is not a uuid", async () => {
    await expect(
      status.default({ params: Promise.resolve({ orderId: "not-a-uuid" }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalledTimes(1);
  });
});
