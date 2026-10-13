import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { siteConfig } from "@/config/site";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  title: "Pricing",
  description:
    "How Motionile credits work: what consumes them, credit packs and subscriptions, refunds for failed generations and prices in INR at checkout.",
  path: "/pricing",
});

const purchaseOptions = [
  {
    title: "Credit packs",
    description: "One-time purchases for occasional videos.",
    points: [
      "Buy a pack of credits once and use them whenever you like.",
      "Credits from packs stay in your wallet until the expiry shown at checkout.",
      "No recurring charge.",
    ],
  },
  {
    title: "Subscriptions",
    description: "A monthly credit allowance for regular creators.",
    points: [
      "Credits are added to your wallet at the start of each billing period.",
      "Renews automatically until you cancel; cancellation takes effect at the end of the period.",
      "Manage or cancel any time from your billing settings.",
    ],
  },
] as const;

const creditUses = [
  {
    title: "Generating a video",
    description:
      "The main cost. It depends on the length of the video and the work needed to narrate, animate and render it.",
  },
  {
    title: "Rendering extra formats",
    description: "Producing 16:9, 9:16 and 1:1 versions of the same video.",
  },
  {
    title: "Publishing",
    description:
      "Writing platform-specific captions and publishing to connected accounts through official APIs.",
  },
] as const;

export default function PricingPage() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-16 px-6 py-16 sm:py-24">
      <PageHeader
        eyebrow="Pricing"
        title="Simple, credit-based pricing"
        description={`${siteConfig.name} runs on credits. You only spend credits on work that is actually done, and you always see the cost before a generation starts.`}
      />
      <section aria-labelledby="options-title" className="flex flex-col gap-6">
        <h2 id="options-title" className="text-2xl font-semibold tracking-tight">
          Two ways to get credits
        </h2>
        <div className="grid gap-4 md:grid-cols-2">
          {purchaseOptions.map((option) => (
            <Card key={option.title}>
              <CardHeader>
                <CardTitle>
                  <h3>{option.title}</h3>
                </CardTitle>
                <CardDescription>{option.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="flex list-disc flex-col gap-2 pl-5 text-sm text-subtle-foreground">
                  {option.points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
      <section aria-labelledby="uses-title" className="flex flex-col gap-6">
        <h2 id="uses-title" className="text-2xl font-semibold tracking-tight">
          What uses credits
        </h2>
        <dl className="grid gap-4 sm:grid-cols-3">
          {creditUses.map((use) => (
            <div key={use.title} className="rounded-lg border bg-surface p-6">
              <dt className="font-medium">{use.title}</dt>
              <dd className="mt-2 text-sm text-subtle-foreground">{use.description}</dd>
            </div>
          ))}
        </dl>
        <p className="text-sm text-muted-foreground">
          Reviewing and editing a storyboard is free. Credits are reserved when a generation starts,
          the actual cost is charged when it completes, and anything left over is released back to
          your wallet straight away.
        </p>
      </section>
      <section aria-labelledby="fairness-title" className="flex flex-col gap-4">
        <h2 id="fairness-title" className="text-2xl font-semibold tracking-tight">
          Fair by design
        </h2>
        <ul className="flex list-disc flex-col gap-2 pl-5 text-subtle-foreground">
          <li>
            If a generation fails on our side, the credits it used are returned to your wallet.
          </li>
          <li>
            Prices are shown in Indian Rupees (INR) at checkout, inclusive of applicable GST, and
            payments are processed securely by Razorpay.
          </li>
          <li>Every credit change is recorded so you can see exactly where your credits went.</li>
        </ul>
        <p className="text-subtle-foreground">
          Read the{" "}
          <Link
            href="/legal/refund-policy"
            className="rounded-sm text-foreground underline underline-offset-4 focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
          >
            refund and cancellation policy
          </Link>{" "}
          for the details.
        </p>
      </section>
    </div>
  );
}
