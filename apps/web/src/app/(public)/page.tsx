import type { Metadata } from "next";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { showcaseCategories } from "@/config/showcase";
import { siteConfig } from "@/config/site";
import { buildOrganizationJsonLd, buildSoftwareApplicationJsonLd, JsonLd } from "@/lib/seo/json-ld";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  description: siteConfig.description,
  path: "/",
});

const steps = [
  {
    title: "Topic",
    description: "Pick a topic from the catalog or ask any question in your own words.",
  },
  {
    title: "Storyboard",
    description:
      "Motionile plans every scene. Review, edit and approve the storyboard before anything renders.",
  },
  {
    title: "Narration",
    description:
      "Each scene gets natural narration first, so the visuals are timed to the real audio.",
  },
  {
    title: "Video",
    description:
      "Scenes become smooth animations, rendered to video in 16:9, 9:16 and 1:1, ready to publish.",
  },
] as const;

export default function HomePage() {
  return (
    <>
      <JsonLd data={[buildOrganizationJsonLd(), buildSoftwareApplicationJsonLd()]} />
      <section
        aria-labelledby="hero-title"
        className="mx-auto w-full max-w-6xl px-6 py-24 sm:py-32"
      >
        <p className="font-mono text-xs tracking-[0.2em] text-muted-foreground uppercase">
          AI animated explainer videos
        </p>
        <h1 id="hero-title" className="mt-6 text-5xl font-semibold tracking-tight sm:text-7xl">
          {siteConfig.name}
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-subtle-foreground sm:text-xl">
          {siteConfig.tagline}
        </p>
        <p className="mt-4 max-w-2xl text-base text-muted-foreground">
          Videos from 10 seconds to 2 minutes, narrated and animated, then published to your
          channels through their official APIs.
        </p>
        <div className="mt-10 flex flex-wrap gap-3">
          <Button asChild size="lg">
            <a href="#how-it-works">See how it works</a>
          </Button>
          <Button asChild size="lg" variant="outline">
            <Link href="/pricing">How credits work</Link>
          </Button>
        </div>
      </section>
      <section id="how-it-works" aria-labelledby="how-it-works-title" className="border-t">
        <div className="mx-auto w-full max-w-6xl px-6 py-20">
          <h2 id="how-it-works-title" className="text-2xl font-semibold tracking-tight">
            How it works
          </h2>
          <ol aria-label="Steps" className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map((step, index) => (
              <li key={step.title} className="rounded-lg border bg-surface p-6">
                <span className="font-mono text-sm text-muted-foreground">0{index + 1}</span>
                <h3 className="mt-3 text-lg font-medium">{step.title}</h3>
                <p className="mt-2 text-sm text-subtle-foreground">{step.description}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>
      <section aria-labelledby="categories-title" className="border-t">
        <div className="mx-auto w-full max-w-6xl px-6 py-20">
          <h2 id="categories-title" className="text-2xl font-semibold tracking-tight">
            Explain anything
          </h2>
          <p className="mt-3 max-w-2xl text-subtle-foreground">
            Start from a curated catalog of categories and topics, or type any question.
          </p>
          <ul aria-label="Categories" className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {showcaseCategories.map((category) => (
              <li key={category.slug} className="flex flex-col gap-3 rounded-lg border p-6">
                <h3 className="text-lg font-medium">{category.name}</h3>
                <p className="text-sm text-subtle-foreground">{category.description}</p>
                <ul aria-label={`${category.name} sample topics`} className="flex flex-wrap gap-2">
                  {category.sampleTopics.map((topic) => (
                    <li key={topic}>
                      <Badge variant="outline">{topic}</Badge>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </div>
      </section>
      <section aria-labelledby="cta-title" className="border-t">
        <div className="mx-auto flex w-full max-w-6xl flex-col items-start gap-6 px-6 py-20">
          <h2 id="cta-title" className="text-3xl font-semibold tracking-tight">
            Your next explainer is one question away
          </h2>
          <p className="max-w-2xl text-subtle-foreground">
            Pay only for what you generate with credits, or subscribe for a monthly allowance.
            Prices are shown in INR at checkout.
          </p>
          <Button asChild size="lg">
            <Link href="/pricing">See pricing</Link>
          </Button>
        </div>
      </section>
    </>
  );
}
