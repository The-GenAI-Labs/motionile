import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlansManager } from "@/features/billing/components/plans-manager";
import { ApiError } from "@/lib/api/api-error";
import type { CheckoutProps } from "@/lib/razorpay/checkout.types";

import { ORDER_ID, products, subscription } from "./billing-fixtures";
import { renderWithQuery } from "./render-with-query";

const api = vi.hoisted(() => ({
  listProducts: vi.fn(),
  getSubscription: vi.fn(),
  createSubscription: vi.fn(),
  cancelSubscription: vi.fn(),
  changeSubscription: vi.fn(),
  createOrder: vi.fn(),
  verifyPayment: vi.fn(),
  verifySubscription: vi.fn(),
}));

vi.mock("@/features/billing/api/billing.api", () => api);
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }));
vi.mock("@/lib/razorpay/checkout-launcher", () => ({
  CheckoutLauncher: (props: CheckoutProps) => (
    <p role="status">Checkout open for {props.target.description}</p>
  ),
}));

const KEY = "11111111-1111-4111-8111-111111111111";

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

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(KEY);
  api.listProducts.mockResolvedValue(products);
  api.getSubscription.mockResolvedValue({ subscription: null });
});

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("PlansManager without a subscription", () => {
  it("offers every plan with a subscribe button and a billing period toggle", async () => {
    const user = userEvent.setup();
    renderWithQuery(<PlansManager />);

    expect(await screen.findByRole("heading", { name: "Choose a plan" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Monthly" })).toBeChecked();
    expect(screen.getByRole("article", { name: "Pro" })).toHaveTextContent("₹499");
    expect(screen.getByRole("button", { name: "Subscribe to Pro" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Subscribe to Team" })).toBeEnabled();
    expect(
      screen.getByText(/subscription credits expire at the end of each billing period/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Yearly" }));

    expect(screen.getByRole("article", { name: "Pro" })).toHaveTextContent("₹4,999");
  });

  it("starts a subscription checkout with an idempotency key", async () => {
    const user = userEvent.setup();
    api.createSubscription.mockResolvedValue(subscriptionCheckout);
    renderWithQuery(<PlansManager />);

    await user.click(await screen.findByRole("button", { name: "Subscribe to Pro" }));

    expect(await screen.findByText("Checkout open for Pro monthly")).toBeInTheDocument();
    expect(api.createSubscription).toHaveBeenCalledExactlyOnceWith({
      productCode: "pro_monthly",
      idempotencyKey: KEY,
    });
  });

  it("starts the subscription from the link and removes the plan from the address", async () => {
    api.createSubscription.mockResolvedValue(subscriptionCheckout);
    window.history.replaceState(null, "", "/billing/plans?plan=team_yearly");

    renderWithQuery(<PlansManager requestedPlan="team_yearly" />);

    await screen.findByText("Checkout open for Pro monthly");
    expect(api.createSubscription).toHaveBeenCalledExactlyOnceWith({
      productCode: "team_yearly",
      idempotencyKey: KEY,
    });
    expect(window.location.search).toBe("");
    expect(screen.getByRole("radio", { name: "Yearly" })).toBeChecked();
  });

  it("reports a linked plan that no longer exists", async () => {
    renderWithQuery(<PlansManager requestedPlan="plan_retired" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("no longer available");
    expect(api.createSubscription).not.toHaveBeenCalled();
  });

  it("explains an existing-subscription conflict", async () => {
    const user = userEvent.setup();
    api.createSubscription.mockRejectedValue(
      new ApiError({
        kind: "http",
        status: 409,
        code: "subscription_exists",
        title: "Conflict",
        detail: null,
      }),
    );
    renderWithQuery(<PlansManager />);

    await user.click(await screen.findByRole("button", { name: "Subscribe to Team" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("You already have a subscription");
  });
});

describe("PlansManager with an active subscription", () => {
  beforeEach(() => {
    api.getSubscription.mockResolvedValue({ subscription: subscription() });
  });

  it("shows the current plan, the next charge and marks the current plan card", async () => {
    renderWithQuery(<PlansManager />);

    const plan = await screen.findByRole("region", { name: "Current plan" });
    expect(plan).toHaveTextContent("Pro monthly");
    expect(plan).toHaveTextContent("Active");
    expect(plan).toHaveTextContent(/₹499 incl\. GST on/);
    expect(screen.getByRole("heading", { name: "Change plan" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Current plan" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Subscribe to/ })).toBeNull();
  });

  it("asks for confirmation before cancelling at the end of the period", async () => {
    const user = userEvent.setup();
    api.cancelSubscription.mockResolvedValue(
      subscription({ cancelAtPeriodEnd: true, endsAt: "2026-11-01T00:00:00Z" }),
    );
    renderWithQuery(<PlansManager />);

    await user.click(await screen.findByRole("button", { name: "Cancel subscription" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Cancel your subscription?" });
    expect(dialog).toHaveTextContent("stays active until");
    expect(dialog).toHaveTextContent("you will not be charged again");
    expect(api.cancelSubscription).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Keep subscription" }));
    expect(api.cancelSubscription).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Cancel subscription" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Cancel subscription",
      }),
    );

    await waitFor(() => {
      expect(api.cancelSubscription).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("Your cancellation has been recorded.")).toBeInTheDocument();
  });

  it("shows the end date and hides the cancel button once cancellation is scheduled", async () => {
    api.getSubscription.mockResolvedValue({
      subscription: subscription({ cancelAtPeriodEnd: true, endsAt: "2026-11-01T00:00:00Z" }),
    });
    renderWithQuery(<PlansManager />);

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("Your subscription ends on");
    expect(note).toHaveTextContent("You will not be charged again");
    expect(screen.queryByRole("button", { name: "Cancel subscription" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Switch from next cycle" })).toBeNull();
  });

  it("explains an immediate cancellation for a subscription that never started billing", async () => {
    const user = userEvent.setup();
    api.getSubscription.mockResolvedValue({ subscription: subscription({ status: "created" }) });
    renderWithQuery(<PlansManager />);

    await user.click(await screen.findByRole("button", { name: "Cancel subscription" }));

    expect(await screen.findByRole("alertdialog")).toHaveTextContent(
      "has not started billing yet, so it is cancelled immediately",
    );
  });

  it("reports a cancellation that fails", async () => {
    const user = userEvent.setup();
    api.cancelSubscription.mockRejectedValue(
      new ApiError({
        kind: "http",
        status: 502,
        code: "payment_provider_unavailable",
        title: "Bad gateway",
        detail: null,
      }),
    );
    renderWithQuery(<PlansManager />);

    await user.click(await screen.findByRole("button", { name: "Cancel subscription" }));
    await user.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Cancel subscription",
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The payment provider is unavailable. Please try again shortly.",
    );
  });

  it("changes plan from the next cycle after confirmation", async () => {
    const user = userEvent.setup();
    api.changeSubscription.mockResolvedValue(
      subscription({
        pendingProduct: {
          code: "team_monthly",
          creditsGranted: 1_200,
          interval: "month",
          name: "Team monthly",
          planKey: "team",
          pricePaise: 149_900,
        },
      }),
    );
    renderWithQuery(<PlansManager />);

    const team = await screen.findByRole("article", { name: "Team" });
    await user.click(within(team).getByRole("button", { name: "Switch from next cycle" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Switch to Team monthly?" });
    expect(dialog).toHaveTextContent("at the start of your next billing period");
    expect(dialog).toHaveTextContent("you keep Pro monthly and its credits");

    await user.click(within(dialog).getByRole("button", { name: "Switch plan" }));

    await waitFor(() => {
      expect(api.changeSubscription).toHaveBeenCalledExactlyOnceWith("team_monthly");
    });
    expect(
      await screen.findByText(
        "Your plan change is scheduled for the start of your next billing period.",
      ),
    ).toBeInTheDocument();
  });

  it("marks the scheduled plan and shows the pending change", async () => {
    api.getSubscription.mockResolvedValue({
      subscription: subscription({
        pendingProduct: {
          code: "team_monthly",
          creditsGranted: 1_200,
          interval: "month",
          name: "Team monthly",
          planKey: "team",
          pricePaise: 149_900,
        },
      }),
    });
    renderWithQuery(<PlansManager />);

    expect(await screen.findByRole("button", { name: "Scheduled for next cycle" })).toBeDisabled();
    expect(screen.getByRole("region", { name: "Current plan" })).toHaveTextContent(
      "Your plan changes to Team monthly on",
    );
  });

  it("does not offer changes while the subscription is not active", async () => {
    api.getSubscription.mockResolvedValue({ subscription: subscription({ status: "halted" }) });
    renderWithQuery(<PlansManager />);

    expect(await screen.findByRole("region", { name: "Current plan" })).toHaveTextContent(
      "Payment failed",
    );
    expect(screen.queryByRole("button", { name: "Switch from next cycle" })).toBeNull();
  });

  it("does not start a new checkout from a link when a subscription exists", async () => {
    renderWithQuery(<PlansManager requestedPlan="team_monthly" />);

    expect(await screen.findByText(/You already have a subscription/)).toBeInTheDocument();
    expect(api.createSubscription).not.toHaveBeenCalled();
  });
});

describe("PlansManager loading", () => {
  it("shows a retryable error when the plans cannot be loaded", async () => {
    const user = userEvent.setup();
    api.listProducts.mockRejectedValueOnce(ApiError.ofKind("network")).mockResolvedValue(products);
    renderWithQuery(<PlansManager />);

    await user.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { name: "Choose a plan" })).toBeInTheDocument();
  });
});
