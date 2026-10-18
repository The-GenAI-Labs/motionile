import Link from "next/link";
import type { ReactNode } from "react";

import { EmptyState } from "@/components/shared/empty-state";
import { PageHeader } from "@/components/shared/page-header";
import { siteConfig } from "@/config/site";
import { PricingPacks } from "@/features/billing/components/pricing-packs";
import { PricingPlans } from "@/features/billing/components/pricing-plans";
import type { Products } from "@/features/billing/types/billing.types";
import { buildProductJsonLd, JsonLd } from "@/lib/seo/json-ld";

interface PricingContentProps {
  products: Products | null;
}

interface FaqEntry {
  question: string;
  answer: ReactNode;
}

const linkClass =
  "rounded-sm text-foreground underline underline-offset-4 focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none";

const creditFacts = [
  {
    term: "What is a credit?",
    description:
      "A credit is the unit Motionile uses to pay for the work behind a video: planning, narration, animation, rendering and publishing.",
  },
  {
    term: "When are credits spent?",
    description:
      "Credits are spent when a video is generated. You see the credit cost before you approve a storyboard.",
  },
  {
    term: "Do credits expire?",
    description:
      "Subscription credits expire at the end of each billing period. Credits from credit packs never expire.",
  },
  {
    term: "What if a generation fails?",
    description:
      "Credits are held when a generation starts, charged only for work that completes, and anything left over returns to your wallet straight away.",
  },
] as const;

const faqEntries: readonly FaqEntry[] = [
  {
    question: "How does billing work?",
    answer:
      "Subscriptions renew automatically at the end of each billing period and credit packs are one-time payments. Payments are processed securely by Razorpay in Indian Rupees, and you get a payment receipt by email. GST tax invoices are not issued yet.",
  },
  {
    question: "Can I cancel my subscription?",
    answer:
      "Yes, at any time from your billing settings. Cancellation takes effect at the end of the current billing period, so you keep your plan and its credits until then and are not charged again.",
  },
  {
    question: "Can I change my plan?",
    answer:
      "Yes. A plan change applies from your next billing cycle, so nothing changes mid-period and you keep the credits you already have.",
  },
  {
    question: "Can I get a refund?",
    answer: (
      <>
        Refunds follow our{" "}
        <Link href="/legal/refund-policy" className={linkClass}>
          refund and cancellation policy
        </Link>
        . If a payment succeeded but credits did not arrive, contact{" "}
        {siteConfig.contact.billingEmail}.
      </>
    ),
  },
  {
    question: "Are prices inclusive of GST?",
    answer:
      "Yes. Every price on this page includes GST and is shown as incl. GST. The amount you see is exactly the amount you pay at checkout.",
  },
];

export function PricingContent({ products }: PricingContentProps) {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-16 px-6 py-16 sm:py-24">
      <PageHeader
        eyebrow="Pricing"
        title="Simple, credit-based pricing"
        description={`${siteConfig.name} runs on credits. Choose a subscription for credits that renew every billing period, or buy a credit pack once and use it whenever you like. All prices include GST.`}
      />
      {products === null ? (
        <EmptyState
          title="Pricing is temporarily unavailable"
          description="We could not load plans and credit packs right now. Please check back in a few minutes."
        />
      ) : (
        <>
          <section aria-labelledby="plans-title" className="flex flex-col gap-6">
            <h2 id="plans-title" className="text-2xl font-semibold tracking-tight">
              Subscription plans
            </h2>
            <PricingPlans subscriptions={products.subscriptions} />
          </section>
          <section aria-labelledby="packs-title" className="flex flex-col gap-6">
            <h2 id="packs-title" className="text-2xl font-semibold tracking-tight">
              Credit packs
            </h2>
            <PricingPacks packs={products.creditPacks} />
          </section>
          <JsonLd
            data={[...products.creditPacks, ...products.subscriptions].map((product) =>
              buildProductJsonLd({ ...product, path: "/pricing" }),
            )}
          />
        </>
      )}
      <section aria-labelledby="credits-title" className="flex flex-col gap-6">
        <h2 id="credits-title" className="text-2xl font-semibold tracking-tight">
          How credits work
        </h2>
        <dl className="grid gap-4 sm:grid-cols-2">
          {creditFacts.map((fact) => (
            <div key={fact.term} className="rounded-lg border bg-surface p-6">
              <dt className="font-medium">{fact.term}</dt>
              <dd className="mt-2 text-sm text-subtle-foreground">{fact.description}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section aria-labelledby="faq-title" className="flex flex-col gap-6">
        <h2 id="faq-title" className="text-2xl font-semibold tracking-tight">
          Billing questions
        </h2>
        <div className="flex flex-col gap-3">
          {faqEntries.map((entry) => (
            <details key={entry.question} className="group rounded-lg border bg-surface p-4">
              <summary className="cursor-pointer rounded-sm font-medium focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none">
                {entry.question}
              </summary>
              <div className="mt-3 text-sm text-subtle-foreground">{entry.answer}</div>
            </details>
          ))}
        </div>
      </section>
    </div>
  );
}
