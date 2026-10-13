import { render, screen, within } from "@testing-library/react";
import type { Metadata } from "next";
import type { ComponentType } from "react";
import { describe, expect, it } from "vitest";

import * as about from "@/app/(public)/about/page";
import * as contact from "@/app/(public)/contact/page";
import * as privacy from "@/app/(public)/legal/privacy/page";
import * as refundPolicy from "@/app/(public)/legal/refund-policy/page";
import * as terms from "@/app/(public)/legal/terms/page";
import * as home from "@/app/(public)/page";
import * as pricing from "@/app/(public)/pricing/page";

interface PageModule {
  default: ComponentType;
  metadata: Metadata;
}

const pages: [string, string, PageModule][] = [
  ["/", "Motionile", home],
  ["/about", "About Motionile", about],
  ["/pricing", "Simple, credit-based pricing", pricing],
  ["/contact", "Get in touch", contact],
  ["/legal/terms", "Terms of Service", terms],
  ["/legal/privacy", "Privacy Policy", privacy],
  ["/legal/refund-policy", "Refund and Cancellation Policy", refundPolicy],
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

  it("does not invent prices on the pricing page", () => {
    const { container } = render(<pricing.default />);

    expect(container.textContent).not.toMatch(/₹\s?\d|Rs\.?\s?\d|INR\s?\d/);
    expect(screen.getByText(/Indian Rupees \(INR\) at checkout/)).toBeInTheDocument();
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
