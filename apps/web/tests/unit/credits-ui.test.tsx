import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BillingNav } from "@/features/billing/components/billing-nav";
import { BillingOverview } from "@/features/billing/components/billing-overview";
import { CreditsCard } from "@/features/credits/components/credits-card";
import { WalletSummary } from "@/features/credits/components/wallet-summary";
import { ApiError } from "@/lib/api/api-error";

import { products, subscription, wallet } from "./billing-fixtures";
import { renderWithQuery } from "./render-with-query";

const billingApi = vi.hoisted(() => ({
  listProducts: vi.fn(),
  getSubscription: vi.fn(),
  createOrder: vi.fn(),
  createSubscription: vi.fn(),
  verifyPayment: vi.fn(),
  verifySubscription: vi.fn(),
}));
const creditsApi = vi.hoisted(() => ({ getWallet: vi.fn() }));
const navigation = vi.hoisted(() => ({ pathname: "/billing" }));

vi.mock("@/features/billing/api/billing.api", () => billingApi);
vi.mock("@/features/credits/api/credits.api", () => creditsApi);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => navigation.pathname,
}));

beforeEach(() => {
  vi.clearAllMocks();
  navigation.pathname = "/billing";
  billingApi.listProducts.mockResolvedValue(products);
  billingApi.getSubscription.mockResolvedValue({ subscription: null });
  creditsApi.getWallet.mockResolvedValue(wallet());
});

describe("WalletSummary", () => {
  it("shows available, reserved and total credits and what expires soon", () => {
    render(<WalletSummary wallet={wallet()} />);

    const summary = screen.getByRole("region", { name: "Your credits" });
    const terms = within(summary)
      .getAllByRole("term")
      .map((term) => term.textContent);
    expect(terms).toEqual(["Available", "Reserved", "Total"]);
    const definitions = within(summary)
      .getAllByRole("definition")
      .map((definition) => definition.textContent);
    expect(definitions).toEqual(["240", "60", "300"]);
    expect(within(summary).getByRole("heading", { name: "Expiring soon" })).toBeInTheDocument();
    expect(summary).toHaveTextContent(/80 credits from subscription expire on/);
  });

  it("says when nothing is expiring", () => {
    render(<WalletSummary wallet={wallet({ expiringSoon: [] })} />);

    expect(screen.getByText("No credits are expiring soon.")).toBeInTheDocument();
  });
});

describe("dashboard credits card", () => {
  it("shows the real wallet with links to buy and manage credits", async () => {
    renderWithQuery(<CreditsCard />);

    const card = await screen.findByRole("region", { name: "Credits" });
    expect(await within(card).findByText("240")).toBeInTheDocument();
    expect(card).toHaveTextContent("credits available");
    expect(card).toHaveTextContent("60 reserved for work in progress");
    expect(card).toHaveTextContent(/80 expire on/);
    expect(within(card).getByRole("link", { name: "Buy credits" })).toHaveAttribute(
      "href",
      "/billing/credits",
    );
    expect(within(card).getByRole("link", { name: "View billing" })).toHaveAttribute(
      "href",
      "/billing",
    );
  });

  it("hides the reserved line when nothing is reserved", async () => {
    creditsApi.getWallet.mockResolvedValue(
      wallet({ reserved: 0, available: 300, expiringSoon: [] }),
    );

    renderWithQuery(<CreditsCard />);

    expect(await screen.findByText("300")).toBeInTheDocument();
    expect(screen.queryByText(/reserved for work in progress/)).toBeNull();
  });

  it("shows a loading state", () => {
    creditsApi.getWallet.mockReturnValue(new Promise(() => undefined));

    renderWithQuery(<CreditsCard />);

    expect(screen.getByRole("status", { name: "Loading credits" })).toBeInTheDocument();
  });

  it("shows a retryable error", async () => {
    const user = userEvent.setup();
    creditsApi.getWallet.mockRejectedValueOnce(ApiError.ofKind("network"));

    renderWithQuery(<CreditsCard />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("240")).toBeInTheDocument();
  });
});

describe("billing overview", () => {
  it("combines credits, the plan and quick purchase of packs", async () => {
    billingApi.getSubscription.mockResolvedValue({ subscription: subscription() });

    renderWithQuery(<BillingOverview />);

    expect(await screen.findByRole("region", { name: "Your credits" })).toHaveTextContent("300");
    const plan = await screen.findByRole("region", { name: "Current plan" });
    expect(plan).toHaveTextContent("Pro monthly");
    expect(within(plan).getByRole("link", { name: "Manage plan" })).toHaveAttribute(
      "href",
      "/billing/plans",
    );
    expect(await screen.findByRole("button", { name: "Buy Starter" })).toBeEnabled();
    expect(screen.getByText(/prices include GST/)).toBeInTheDocument();
  });

  it("invites users without a subscription to see plans", async () => {
    renderWithQuery(<BillingOverview />);

    const empty = await screen.findByRole("region", { name: "No subscription" });
    expect(within(empty).getByRole("link", { name: "See plans" })).toHaveAttribute(
      "href",
      "/billing/plans",
    );
  });

  it("shows retryable errors for the wallet and the plan independently", async () => {
    creditsApi.getWallet.mockRejectedValue(ApiError.ofKind("network"));
    billingApi.getSubscription.mockRejectedValue(ApiError.ofKind("timeout"));

    renderWithQuery(<BillingOverview />);

    expect(await screen.findAllByRole("alert")).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Try again" })).toHaveLength(2);
    expect(await screen.findByRole("button", { name: "Buy Starter" })).toBeEnabled();
  });
});

describe("billing navigation", () => {
  it("links every section and marks the current one", () => {
    navigation.pathname = "/billing/plans";

    render(<BillingNav />);

    const nav = screen.getByRole("navigation", { name: "Billing sections" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Overview", "Plans", "Credits", "History"]);
    expect(within(nav).getByRole("link", { name: "Plans" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    expect(within(nav).getByRole("link", { name: "History" })).toHaveAttribute(
      "href",
      "/billing/history",
    );
  });

  it("marks only the overview on the billing home and nothing on the status page", () => {
    const { rerender } = render(<BillingNav />);
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute("aria-current", "page");

    navigation.pathname = "/billing/status/abc";
    rerender(<BillingNav />);
    expect(screen.queryByRole("link", { current: "page" })).toBeNull();
  });
});
