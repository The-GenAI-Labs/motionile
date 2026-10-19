import { randomUUID } from "node:crypto";

import { type APIRequestContext, type APIResponse, expect } from "@playwright/test";

import {
  ALLOWED_ORIGIN,
  type Problem,
  PROBLEM_JSON,
  uniqueClientIp,
} from "../security/api/support.js";
import { AuthApi, type SessionUser } from "./auth.js";

const apiBaseUrl = process.env["API_BASE_URL"] ?? "http://localhost:8000";
const FAKE_RAZORPAY_PATH = "/v1/_test/razorpay";

export interface Product {
  code: string;
  name: string;
  pricePaise: number;
  currency: string;
  creditsGranted: number;
  interval: string | null;
  planKey: string | null;
}

export interface Products {
  creditPacks: Product[];
  subscriptions: Product[];
}

export interface Checkout {
  orderId: string;
  keyId: string;
  razorpayOrderId: string;
  amountPaise: number;
  currency: string;
}

export interface SubscriptionCheckout {
  orderId: string;
  subscriptionId: string;
  razorpaySubscriptionId: string;
}

export interface Wallet {
  balance: number;
  reserved: number;
  available: number;
}

export interface LedgerEntry {
  reason: string;
  delta: number;
  balanceAfter: number;
  refType: string | null;
}

export interface HistoryItem {
  type: string;
  id: string;
  status: string;
  amountPaise: number;
  orderId: string | null;
  paymentId: string | null;
}

export interface CursorPage<Item> {
  items: Item[];
  nextCursor: string | null;
}

export interface SubscriptionView {
  id: string;
  status: string;
  product: { code: string; name: string };
  pendingProduct: { code: string; name: string } | null;
  cancelAtPeriodEnd: boolean;
  endsAt: string | null;
}

export interface PaidOrder {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string | null;
  paymentStatus: string;
}

export interface AuthorizedSubscription {
  razorpay_payment_id: string;
  razorpay_subscription_id: string;
  razorpay_signature: string;
  subscriptionStatus: string;
}

export interface Verified {
  orderId: string;
  status: string;
  creditsGranted: number;
}

export interface Refund {
  id: string;
  status: string;
  amountPaise: number;
  creditsClawedBack: number;
  razorpayRefundId: string | null;
}

export type OrderWebhook = "payment.captured" | "order.paid" | "payment.failed";
export type SubscriptionTransitionEvent = "activated" | "charged" | "halted" | "cancelled";

export async function expectProblem(
  response: APIResponse,
  status: number,
  code: string,
): Promise<void> {
  expect(response.status(), await response.text()).toBe(status);
  expect(response.headers()["content-type"]).toBe(PROBLEM_JSON);
  expect(((await response.json()) as Problem).code).toBe(code);
}

export class BillingSession {
  readonly auth: AuthApi;
  private current: SessionUser | undefined;

  constructor(request: APIRequestContext) {
    this.auth = new AuthApi(request);
  }

  get userId(): string {
    if (this.current === undefined) throw new Error("The session has not signed up yet");
    return this.current.id;
  }

  async signup(): Promise<SessionUser> {
    this.current = await this.auth.signup();
    return this.current;
  }

  async call(
    method: string,
    path: string,
    data?: Record<string, unknown>,
    extra: Record<string, string> = {},
  ): Promise<APIResponse> {
    const response = await this.auth.send(method, path, data, extra);
    if (response.status() !== 401) return response;
    expect((await this.auth.send("POST", "/v1/auth/refresh")).status()).toBe(204);
    return this.auth.send(method, path, data, extra);
  }

  async keyed(
    method: string,
    path: string,
    data: Record<string, unknown>,
    key: string = randomUUID(),
  ): Promise<APIResponse> {
    return this.call(method, path, data, { "Idempotency-Key": key });
  }

  async json<Body>(response: APIResponse, status: number): Promise<Body> {
    expect(response.status(), await response.text()).toBe(status);
    return (await response.json()) as Body;
  }

  async products(): Promise<Products> {
    return this.json<Products>(await this.call("GET", "/v1/billing/products"), 200);
  }

  async createOrder(productCode: string, key?: string): Promise<Checkout> {
    return this.json<Checkout>(
      await this.keyed("POST", "/v1/billing/orders", { productCode }, key),
      201,
    );
  }

  async createSubscription(productCode: string, key?: string): Promise<SubscriptionCheckout> {
    return this.json<SubscriptionCheckout>(
      await this.keyed("POST", "/v1/billing/subscriptions", { productCode }, key),
      201,
    );
  }

  async verifyOrder(paid: PaidOrder, key?: string): Promise<APIResponse> {
    return this.keyed(
      "POST",
      "/v1/billing/payments/verify",
      {
        razorpayOrderId: paid.razorpay_order_id,
        razorpayPaymentId: paid.razorpay_payment_id,
        razorpaySignature: paid.razorpay_signature ?? "",
      },
      key,
    );
  }

  async verifySubscription(authorized: AuthorizedSubscription, key?: string): Promise<APIResponse> {
    return this.keyed(
      "POST",
      "/v1/billing/subscriptions/verify",
      {
        razorpayPaymentId: authorized.razorpay_payment_id,
        razorpaySubscriptionId: authorized.razorpay_subscription_id,
        razorpaySignature: authorized.razorpay_signature,
      },
      key,
    );
  }

  async wallet(): Promise<Wallet> {
    return this.json<Wallet>(await this.call("GET", "/v1/credits/wallet"), 200);
  }

  async ledger(): Promise<CursorPage<LedgerEntry>> {
    return this.json<CursorPage<LedgerEntry>>(
      await this.call("GET", "/v1/credits/ledger?limit=100"),
      200,
    );
  }

  async history(): Promise<CursorPage<HistoryItem>> {
    return this.json<CursorPage<HistoryItem>>(
      await this.call("GET", "/v1/billing/history?limit=100"),
      200,
    );
  }

  async subscription(): Promise<SubscriptionView | null> {
    const body = await this.json<{ subscription: SubscriptionView | null }>(
      await this.call("GET", "/v1/billing/subscription"),
      200,
    );
    return body.subscription;
  }

  async paymentIdForOrder(orderId: string): Promise<string> {
    const payment = (await this.history()).items.find(
      (item) => item.type === "payment" && item.orderId === orderId,
    );
    if (payment === undefined) throw new Error(`No payment is recorded for order ${orderId}`);
    return payment.id;
  }

  async waitForBalance(expected: number, timeout = 60000): Promise<void> {
    await expect
      .poll(async () => (await this.wallet()).balance, { timeout, intervals: [250, 500, 1000] })
      .toBe(expected);
  }
}

export class FakeRazorpay {
  private readonly ip = uniqueClientIp();

  constructor(private readonly request: APIRequestContext) {}

  async payOrder(
    razorpayOrderId: string,
    options: {
      outcome?: "success" | "failure";
      amountPaise?: number;
      currency?: string;
      webhooks?: OrderWebhook[];
    } = {},
  ): Promise<PaidOrder> {
    return this.post<PaidOrder>(`/orders/${razorpayOrderId}/pay`, {
      outcome: options.outcome ?? "success",
      ...(options.amountPaise === undefined ? {} : { amountPaise: options.amountPaise }),
      ...(options.currency === undefined ? {} : { currency: options.currency }),
      webhooks: options.webhooks ?? [],
    });
  }

  async authorizeSubscription(razorpaySubscriptionId: string): Promise<AuthorizedSubscription> {
    return this.post<AuthorizedSubscription>(`/subscriptions/${razorpaySubscriptionId}/authorize`, {
      webhooks: [],
    });
  }

  async transitionSubscription(
    razorpaySubscriptionId: string,
    event: SubscriptionTransitionEvent,
  ): Promise<void> {
    await this.post(`/subscriptions/${razorpaySubscriptionId}/transition`, { event, emit: true });
  }

  async settleRefund(razorpayRefundId: string, outcome: "processed" | "failed"): Promise<void> {
    await this.post(`/refunds/${razorpayRefundId}/settle`, { outcome });
  }

  async deliverRefundProcessed(razorpayRefundId: string): Promise<void> {
    await this.post("/webhooks", { event: "refund.processed", refundId: razorpayRefundId });
  }

  private async post<Body>(path: string, data: Record<string, unknown>): Promise<Body> {
    const response = await this.request.post(
      new URL(`${FAKE_RAZORPAY_PATH}${path}`, apiBaseUrl).toString(),
      { headers: { Origin: ALLOWED_ORIGIN, "X-Forwarded-For": this.ip }, data },
    );
    expect(response.status(), await response.text()).toBe(200);
    return (await response.json()) as Body;
  }
}

export async function buyPack(
  session: BillingSession,
  fake: FakeRazorpay,
  productCode = "pack_starter",
): Promise<{ checkout: Checkout; paid: PaidOrder }> {
  const checkout = await session.createOrder(productCode);
  const paid = await fake.payOrder(checkout.razorpayOrderId, {
    webhooks: ["payment.captured", "order.paid"],
  });
  return { checkout, paid };
}

export async function creditsOf(session: BillingSession, productCode: string): Promise<number> {
  const { creditPacks, subscriptions } = await session.products();
  const product = [...creditPacks, ...subscriptions].find((item) => item.code === productCode);
  if (product === undefined) throw new Error(`Product ${productCode} is not listed`);
  return product.creditsGranted;
}
