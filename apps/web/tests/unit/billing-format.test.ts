import { describe, expect, it } from "vitest";

import { billingKeys } from "@/features/billing/query-keys";
import { creditsKeys } from "@/features/credits/query-keys";
import { buildProductJsonLd, serializeJsonLd } from "@/lib/seo/json-ld";
import {
  formatCredits,
  formatPaise,
  formatSignedCredits,
  paiseToDecimalString,
  titleCase,
} from "@/lib/utils/format";

const plain = (value: string): string => value.replace(/\s+/g, " ");

describe("money formatting", () => {
  it("formats whole rupees without decimals and fractions with two", () => {
    expect(plain(formatPaise(49_900))).toBe("₹499");
    expect(plain(formatPaise(79_950))).toBe("₹799.50");
    expect(plain(formatPaise(5))).toBe("₹0.05");
    expect(plain(formatPaise(0))).toBe("₹0");
  });

  it("groups digits the Indian way", () => {
    expect(plain(formatPaise(149_990_000))).toBe("₹14,99,900");
    expect(formatCredits(1_234_567)).toBe("12,34,567");
  });

  it("rejects money that is not a non-negative integer number of paise", () => {
    for (const invalid of [1.5, -1, Number.NaN, Number.MAX_SAFE_INTEGER + 2]) {
      expect(() => formatPaise(invalid)).toThrow(RangeError);
      expect(() => paiseToDecimalString(invalid)).toThrow(RangeError);
    }
  });

  it("builds decimal strings with integer maths", () => {
    expect(paiseToDecimalString(49_900)).toBe("499.00");
    expect(paiseToDecimalString(79_950)).toBe("799.50");
    expect(paiseToDecimalString(1)).toBe("0.01");
    expect(paiseToDecimalString(1_499_900)).toBe("14999.00");
  });

  it("signs credit changes", () => {
    expect(formatSignedCredits(120)).toBe("+120");
    expect(formatSignedCredits(-45)).toBe("-45");
    expect(formatSignedCredits(0)).toBe("0");
  });

  it("title-cases plan keys", () => {
    expect(titleCase("pro")).toBe("Pro");
    expect(titleCase("team_plus-annual")).toBe("Team Plus Annual");
  });
});

describe("product structured data", () => {
  const input = {
    code: "pack_creator",
    name: "Creator",
    description: "500 credits for a steady publishing rhythm.",
    pricePaise: 79_950,
    currency: "INR",
    path: "/pricing",
  };

  it("describes the product with an INR offer priced from paise", () => {
    expect(buildProductJsonLd(input)).toEqual({
      "@context": "https://schema.org",
      "@type": "Product",
      name: "Creator",
      description: "500 credits for a steady publishing rhythm.",
      sku: "pack_creator",
      url: "https://motionile.test/pricing",
      brand: { "@type": "Brand", name: "Motionile" },
      offers: {
        "@type": "Offer",
        price: "799.50",
        priceCurrency: "INR",
        availability: "https://schema.org/InStock",
        url: "https://motionile.test/pricing",
        priceSpecification: {
          "@type": "PriceSpecification",
          price: "799.50",
          priceCurrency: "INR",
          valueAddedTaxIncluded: true,
        },
      },
    });
  });

  it("falls back to a generated description and stays safe to embed", () => {
    const document = buildProductJsonLd({ ...input, description: null, name: "A <b> pack" });

    expect(document.description).toBe("A <b> pack from Motionile");
    expect(serializeJsonLd(document)).not.toContain("<b>");
  });
});

describe("query key factories", () => {
  it("nest billing keys under the billing root", () => {
    expect(billingKeys.products()).toEqual(["billing", "products"]);
    expect(billingKeys.subscription()).toEqual(["billing", "subscription"]);
    expect(billingKeys.order("abc")).toEqual(["billing", "order", "abc"]);
    expect(billingKeys.history()).toEqual(["billing", "history"]);
  });

  it("nest credit keys under the credits root", () => {
    expect(creditsKeys.wallet()).toEqual(["credits", "wallet"]);
    expect(creditsKeys.ledger()).toEqual(["credits", "ledger"]);
    expect(creditsKeys.usage("entries")).toEqual(["credits", "usage", "entries"]);
    expect(creditsKeys.usage("daily")).toEqual(["credits", "usage", "daily"]);
  });
});
