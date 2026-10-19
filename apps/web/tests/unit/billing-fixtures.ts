import type {
  Order,
  Product,
  Products,
  Subscription,
} from "@/features/billing/types/billing.types";
import type { Wallet } from "@/features/credits/types/credits.types";

export const ORDER_ID = "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e01";

export const product = (overrides: Partial<Product> & Pick<Product, "code" | "name">): Product => ({
  creditsGranted: 100,
  currency: "INR",
  description: null,
  features: [],
  interval: null,
  planKey: null,
  pricePaise: 19_900,
  sortOrder: 10,
  ...overrides,
});

export const products: Products = {
  creditPacks: [
    product({
      code: "pack_starter",
      name: "Starter",
      description: "100 credits for a handful of explainers.",
      features: ["Credits never expire"],
      pricePaise: 19_900,
      creditsGranted: 100,
    }),
    product({
      code: "pack_creator",
      name: "Creator",
      pricePaise: 79_950,
      creditsGranted: 500,
      sortOrder: 20,
    }),
  ],
  subscriptions: [
    product({
      code: "pro_monthly",
      name: "Pro monthly",
      interval: "month",
      planKey: "pro",
      pricePaise: 49_900,
      creditsGranted: 300,
      features: ["Priority rendering"],
    }),
    product({
      code: "pro_yearly",
      name: "Pro yearly",
      interval: "year",
      planKey: "pro",
      pricePaise: 499_900,
      creditsGranted: 3_600,
    }),
    product({
      code: "team_monthly",
      name: "Team monthly",
      interval: "month",
      planKey: "team",
      pricePaise: 149_900,
      creditsGranted: 1_200,
    }),
    product({
      code: "team_yearly",
      name: "Team yearly",
      interval: "year",
      planKey: "team",
      pricePaise: 1_499_900,
      creditsGranted: 14_400,
    }),
  ],
};

export const subscription = (overrides: Partial<Subscription> = {}): Subscription => ({
  id: "0197c5a2-1b2c-7d3e-8f40-5a6b7c8d9e02",
  status: "active",
  cancelAtPeriodEnd: false,
  cancelledAt: null,
  currentPeriodStart: "2026-10-01T00:00:00Z",
  currentPeriodEnd: "2026-11-01T00:00:00Z",
  endsAt: null,
  nextChargeAt: "2026-11-01T00:00:00Z",
  pendingProduct: null,
  product: {
    code: "pro_monthly",
    creditsGranted: 300,
    interval: "month",
    name: "Pro monthly",
    planKey: "pro",
    pricePaise: 49_900,
  },
  ...overrides,
});

export const order = (overrides: Partial<Order> = {}): Order => ({
  id: ORDER_ID,
  status: "pending",
  kind: "credit_pack",
  productCode: "pack_starter",
  productName: "Starter",
  amountPaise: 19_900,
  creditsGranted: 100,
  currency: "INR",
  paidAt: null,
  expiresAt: "2026-10-18T12:00:00Z",
  ...overrides,
});

export const wallet = (overrides: Partial<Wallet> = {}): Wallet => ({
  available: 240,
  balance: 300,
  reserved: 60,
  expiringSoon: [{ expiresAt: "2026-11-01T00:00:00Z", remaining: 80, source: "subscription" }],
  ...overrides,
});
