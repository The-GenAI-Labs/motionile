import { PageHeader } from "@/components/shared/page-header";
import { CreditPackStore } from "@/features/billing/components/credit-pack-store";
import { parseProductCode } from "@/features/billing/schemas/billing.schema";
import { WalletBalance } from "@/features/credits/components/wallet-balance";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Buy credits",
  description: "Buy a one-time Motionile credit pack. Purchased credits never expire.",
  path: "/billing/credits",
  noIndex: true,
});

interface CreditsPageProps {
  searchParams: Promise<{ pack?: string | string[] }>;
}

export default async function CreditsPage({ searchParams }: CreditsPageProps) {
  const { pack } = await searchParams;
  return (
    <div className="space-y-8">
      <PageHeader
        title="Buy credits"
        description="Credit packs are one-time payments. Prices include GST and purchased credits never expire."
      />
      <WalletBalance />
      <CreditPackStore requestedPack={parseProductCode(pack)} />
    </div>
  );
}
