import type { Metadata } from "next";

import { Button } from "@/components/ui/button";
import { siteConfig } from "@/config/site";

export const metadata: Metadata = {
  title: { absolute: siteConfig.title },
  description: siteConfig.description,
  alternates: { canonical: "/" },
};

const steps = [
  {
    title: "Plan",
    description:
      "Describe a topic or ask a question. Review and approve the storyboard before anything renders.",
  },
  {
    title: "Narrate",
    description:
      "Every scene gets natural narration first, so the visuals are timed to the real audio.",
  },
  {
    title: "Animate",
    description: "Scenes become smooth animations, rendered to video in 16:9, 9:16 and 1:1.",
  },
] as const;

export default function HomePage() {
  return (
    <>
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
        <div className="mt-10">
          <Button asChild size="lg">
            <a href="#how-it-works">See how it works</a>
          </Button>
        </div>
      </section>
      <section id="how-it-works" aria-labelledby="how-it-works-title" className="border-t">
        <div className="mx-auto w-full max-w-6xl px-6 py-20">
          <h2 id="how-it-works-title" className="text-2xl font-semibold tracking-tight">
            How it works
          </h2>
          <ol className="mt-10 grid gap-4 sm:grid-cols-3">
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
    </>
  );
}
