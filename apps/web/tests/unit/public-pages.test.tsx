import { render, screen, within } from "@testing-library/react";
import type { Metadata } from "next";
import type { ComponentType } from "react";
import { describe, expect, it } from "vitest";

import * as about from "@/app/(public)/about/page";
import * as contact from "@/app/(public)/contact/page";
import * as dataDeletion from "@/app/(public)/legal/data-deletion/page";
import * as privacy from "@/app/(public)/legal/privacy/page";
import * as refundPolicy from "@/app/(public)/legal/refund-policy/page";
import * as terms from "@/app/(public)/legal/terms/page";
import * as home from "@/app/(public)/page";
import * as pricing from "@/app/(public)/pricing/page";
import { PricingContent } from "@/features/billing/components/pricing-content";

interface PageModule {
  default: ComponentType;
  metadata: Metadata;
}

const pricingPage: PageModule = {
  default: () => <PricingContent products={null} />,
  metadata: pricing.metadata,
};

const pages: [string, string, PageModule][] = [
  ["/", "Motionile", home],
  ["/about", "About Motionile", about],
  ["/pricing", "Simple, credit-based pricing", pricingPage],
  ["/contact", "Get in touch", contact],
  ["/legal/terms", "Terms of Service", terms],
  ["/legal/privacy", "Privacy Policy", privacy],
  ["/legal/refund-policy", "Refund and Cancellation Policy", refundPolicy],
  ["/legal/data-deletion", "Data Deletion", dataDeletion],
];

const legalPages = pages.filter(([path]) => path.startsWith("/legal"));

describe("public pages", () => {
  it.each(pages)("%s renders one level one heading", (_path, heading, page) => {
    const Page = page.default;
    render(<Page />);

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
  });

  it.each(pages)("%s has a canonical url and indexable metadata", (path, _heading, page) => {
    expect(page.metadata.alternates?.canonical).toBe(
      path === "/" ? "https://motionile.test/" : `https://motionile.test${path}`,
    );
    expect(page.metadata.robots).toEqual({ index: true, follow: true });
    expect(page.metadata.openGraph?.url).toBe(page.metadata.alternates?.canonical);
  });

  it("gives every page a unique description", () => {
    const descriptions = pages.map(([, , page]) => page.metadata.description);

    expect(new Set(descriptions).size).toBe(pages.length);
  });

  it.each(legalPages)("%s shows the draft notice and dates", (_path, _heading, page) => {
    const Page = page.default;
    render(<Page />);

    expect(screen.getByRole("note", { name: "Draft notice" })).toHaveTextContent(
      "Draft pending legal review.",
    );
    expect(screen.getByText("Effective date:")).toBeInTheDocument();
    expect(screen.getByText("Last updated:")).toBeInTheDocument();
    const contents = screen.getByRole("navigation", { name: "Table of contents" });
    const sectionLinks = within(contents).getAllByRole("link");
    expect(sectionLinks.length).toBeGreaterThan(5);
    for (const link of sectionLinks) {
      const target = link.getAttribute("href")?.slice(1) ?? "";
      expect(document.getElementById(target)).toBeInTheDocument();
    }
  });

  it("covers Indian law and payments in the terms", () => {
    render(<terms.default />);

    for (const text of [
      /Information Technology Act, 2000/,
      /Razorpay/,
      /Goods and Services Tax/,
      /renew automatically/,
      /deepfakes/,
      /Voice cloning/,
      /Grievance Officer/,
      /\[City\], India/,
    ]) {
      expect(screen.getAllByText(text).length).toBeGreaterThan(0);
    }
  });

  it("covers DPDP rights in the privacy policy", () => {
    render(<privacy.default />);

    for (const text of [
      /Digital Personal Data Protection Act, 2023/,
      /Data Protection Board of India/,
      /withdraw consent/,
      /Cross-border transfers/,
      /Cookies/,
      /aged 18 and over/,
    ]) {
      expect(screen.getAllByText(text).length).toBeGreaterThan(0);
    }
  });

  it("explains refunds to the original payment method", () => {
    render(<refundPolicy.default />);

    expect(screen.getByRole("heading", { name: /Failed generations/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Chargebacks/ })).toBeInTheDocument();
    expect(screen.getAllByText(/original payment method/).length).toBeGreaterThan(0);
  });

  it("explains how to delete data and revoke connected platforms", () => {
    render(<dataDeletion.default />);

    for (const heading of [
      /What you can delete/,
      /How to request deletion/,
      /Removing Motionile from a connected platform/,
      /What we retain and why/,
      /Grievance Officer/,
    ]) {
      expect(screen.getByRole("heading", { level: 2, name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("link", { name: "privacy@motionile.com" })[0]).toHaveAttribute(
      "href",
      "mailto:privacy@motionile.com",
    );
    expect(screen.getByRole("link", { name: "grievance@motionile.com" })).toHaveAttribute(
      "href",
      "mailto:grievance@motionile.com",
    );
    for (const text of [
      /Settings → Account → Delete account/,
      /within 30 days/,
      /confirmation code/,
      /Central Goods and Services Tax Act, 2017/,
      /anonymised/,
      /backup retention period/,
    ]) {
      expect(screen.getAllByText(text).length).toBeGreaterThan(0);
    }
  });

  it("does not invent prices on the pricing page when the products are unavailable", () => {
    const { container } = render(<PricingContent products={null} />);

    expect(container.textContent).not.toMatch(/₹\s?\d|Rs\.?\s?\d|INR\s?\d/);
    expect(
      screen.getByRole("heading", { name: "Pricing is temporarily unavailable" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How credits work" })).toBeInTheDocument();
  });

  it("lists contact emails as mail links", () => {
    render(<contact.default />);

    expect(screen.getByRole("link", { name: "support@motionile.com" })).toHaveAttribute(
      "href",
      "mailto:support@motionile.com",
    );
    expect(screen.getByRole("link", { name: /^YouTube/ })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
  });
});
