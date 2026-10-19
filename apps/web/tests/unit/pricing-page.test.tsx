import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import PricingPage, * as pricing from "@/app/(public)/pricing/page";
import { PricingContent } from "@/features/billing/components/pricing-content";

import { products } from "./billing-fixtures";

const { loadPricingProducts } = vi.hoisted(() => ({ loadPricingProducts: vi.fn() }));

vi.mock("@/features/billing/api/billing.server.api", () => ({ loadPricingProducts }));

const plain = (value: string | null): string => (value ?? "").replace(/\s+/g, " ");

const clearSessionHint = () => {
  document.cookie = "mo_auth=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
};

afterEach(() => {
  clearSessionHint();
});

describe("pricing page", () => {
  it("fetches products on the server and revalidates on a timer as a fallback", async () => {
    loadPricingProducts.mockResolvedValue(products);

    render(await PricingPage());

    expect(loadPricingProducts).toHaveBeenCalledTimes(1);
    expect(pricing.revalidate).toBe(300);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Simple, credit-based pricing",
    );
  });

  it("has a unique description and a canonical url", () => {
    expect(pricing.metadata.alternates?.canonical).toBe("https://motionile.test/pricing");
    expect(pricing.metadata.description).toMatch(/GST/);
    expect(pricing.metadata.openGraph?.url).toBe("https://motionile.test/pricing");
  });
});

describe("pricing plans", () => {
  it("shows monthly prices first and switches to yearly with the keyboard", async () => {
    const user = userEvent.setup();
    render(<PricingContent products={products} />);

    const plans = screen.getByRole("region", { name: "Subscription plans" });
    const monthly = within(plans).getByRole("radio", { name: "Monthly" });
    const yearly = within(plans).getByRole("radio", { name: "Yearly" });
    expect(within(plans).getByRole("group", { name: "Billing period" })).toBeInTheDocument();
    expect(monthly).toBeChecked();
    expect(plain(within(plans).getByRole("article", { name: "Pro" }).textContent)).toContain(
      "₹499per month",
    );

    await user.tab();
    expect(monthly).toHaveFocus();
    await user.keyboard("{ArrowRight}");

    expect(yearly).toBeChecked();
    const pro = within(plans).getByRole("article", { name: "Pro" });
    expect(plain(pro.textContent)).toContain("₹4,999per year");
    expect(pro).toHaveTextContent("3,600 credits every year");
    expect(within(plans).getByRole("article", { name: "Team" })).toHaveTextContent(
      /14,99,900|14,999/,
    );
  });

  it("shows incl. GST next to every price", () => {
    render(<PricingContent products={products} />);

    const articles = screen.getAllByRole("article");
    expect(articles).toHaveLength(4);
    for (const article of articles) {
      expect(article).toHaveTextContent(/incl\. GST/);
    }
  });

  it("sends signed-out visitors to login with the purchase as the return path", () => {
    render(<PricingContent products={products} />);

    expect(screen.getByRole("link", { name: "Choose Pro" })).toHaveAttribute(
      "href",
      "/login?next=%2Fbilling%2Fplans%3Fplan%3Dpro_monthly",
    );
    expect(screen.getByRole("link", { name: "Buy Starter" })).toHaveAttribute(
      "href",
      "/login?next=%2Fbilling%2Fcredits%3Fpack%3Dpack_starter",
    );
  });

  it("sends signed-in visitors straight to checkout", async () => {
    document.cookie = "mo_auth=4102444800; path=/";
    const user = userEvent.setup();
    render(<PricingContent products={products} />);

    expect(screen.getByRole("link", { name: "Choose Team" })).toHaveAttribute(
      "href",
      "/billing/plans?plan=team_monthly",
    );
    expect(screen.getByRole("link", { name: "Buy Creator" })).toHaveAttribute(
      "href",
      "/billing/credits?pack=pack_creator",
    );

    await user.click(screen.getByRole("radio", { name: "Yearly" }));
    expect(screen.getByRole("link", { name: "Choose Team" })).toHaveAttribute(
      "href",
      "/billing/plans?plan=team_yearly",
    );
  });

  it("renders the signed-out destination on the server before hydration", () => {
    document.cookie = "mo_auth=4102444800; path=/";

    const html = renderToString(<PricingContent products={products} />);

    expect(html).toContain("/login?next=%2Fbilling%2Fplans%3Fplan%3Dpro_monthly");
  });

  it("lists each credit pack with its price, credits and permanence", () => {
    render(<PricingContent products={products} />);

    const packs = screen.getByRole("region", { name: "Credit packs" });
    const creator = within(packs).getByRole("article", { name: "Creator" });
    expect(plain(creator.textContent)).toContain("₹799.50");
    expect(creator).toHaveTextContent("500 credits that never expire");
    expect(creator).toHaveTextContent("incl. GST, one-time payment");
  });

  it("only offers the intervals plans actually have", () => {
    render(
      <PricingContent
        products={{
          creditPacks: [],
          subscriptions: products.subscriptions.filter((plan) => plan.interval === "month"),
        }}
      />,
    );

    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Choose Pro" })).toBeInTheDocument();
    expect(screen.getByText(/Credit packs are not available right now/)).toBeInTheDocument();
  });
});

describe("pricing explanations", () => {
  it("explains credits without inventing rates", () => {
    render(<PricingContent products={products} />);

    const credits = screen.getByRole("region", { name: "How credits work" });
    expect(credits).toHaveTextContent(
      "Credits are spent when a video is generated. You see the credit cost before you approve a storyboard.",
    );
    expect(credits).toHaveTextContent(
      "Subscription credits expire at the end of each billing period. Credits from credit packs never expire.",
    );
  });

  it("answers the billing questions and links the refund policy", async () => {
    const user = userEvent.setup();
    render(<PricingContent products={products} />);

    const faq = screen.getByRole("region", { name: "Billing questions" });
    for (const question of [
      "How does billing work?",
      "Can I cancel my subscription?",
      "Can I change my plan?",
      "Can I get a refund?",
      "Are prices inclusive of GST?",
    ]) {
      expect(within(faq).getByText(question)).toBeInTheDocument();
    }
    await user.click(within(faq).getByText("Can I get a refund?"));
    expect(
      within(faq).getByRole("link", { name: "refund and cancellation policy" }),
    ).toHaveAttribute("href", "/legal/refund-policy");
    expect(faq).toHaveTextContent("end of the current billing period");
    expect(faq).toHaveTextContent("next billing cycle");
  });
});

describe("pricing structured data", () => {
  it("publishes a Product with an INR Offer for every product", () => {
    const { container } = render(<PricingContent products={products} />);

    const documents = [...container.querySelectorAll('script[type="application/ld+json"]')].flatMap(
      (script) => JSON.parse(script.textContent) as Record<string, unknown>[],
    );
    expect(documents).toHaveLength(6);
    expect(documents.every((document) => document["@type"] === "Product")).toBe(true);
    const creator = documents.find((document) => document["sku"] === "pack_creator");
    expect(creator?.["offers"]).toMatchObject({
      "@type": "Offer",
      price: "799.50",
      priceCurrency: "INR",
    });
    expect(
      documents.find((document) => document["sku"] === "team_yearly")?.["offers"],
    ).toMatchObject({ price: "14999.00" });
  });

  it("omits structured data and still renders when products are unavailable", () => {
    const { container } = render(<PricingContent products={null} />);

    expect(container.querySelector('script[type="application/ld+json"]')).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument();
  });
});
