import { loadPricingProducts } from "@/features/billing/api/billing.server.api";
import { PricingContent } from "@/features/billing/components/pricing-content";
import { buildMetadata } from "@/lib/seo/metadata";

export const revalidate = 300;

export const metadata = buildMetadata({
  title: "Pricing",
  description:
    "Motionile subscription plans and credit packs in INR, with GST included. Subscription credits renew every period and credit pack credits never expire.",
  path: "/pricing",
});

export default async function PricingPage() {
  return <PricingContent products={await loadPricingProducts()} />;
}
