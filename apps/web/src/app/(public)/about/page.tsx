import type { Metadata } from "next";
import Link from "next/link";

import { PageHeader } from "@/components/shared/page-header";
import { siteConfig } from "@/config/site";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  title: "About",
  description:
    "Why Motionile exists, how it turns questions into narrated animated explainers and the principles behind the product.",
  path: "/about",
});

const principles = [
  {
    title: "You stay in control",
    description:
      "Every video starts as a storyboard you can edit and approve. Nothing expensive runs until you say so.",
  },
  {
    title: "Narration comes first",
    description:
      "We generate the voice before the visuals, so every animation lands exactly on the words it illustrates.",
  },
  {
    title: "Official APIs only",
    description:
      "Publishing goes through each platform's official API. We never automate your accounts with hidden browsers.",
  },
  {
    title: "Honest billing",
    description:
      "Credits are recorded in an append-only ledger. If a generation fails, the credits it used come back to you.",
  },
] as const;

export default function AboutPage() {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-16 px-6 py-16 sm:py-24">
      <PageHeader
        eyebrow="About"
        title={`About ${siteConfig.name}`}
        description="We make it effortless to explain an idea well. Ask a question, approve a plan and get a narrated, animated video you can publish anywhere."
      />
      <section aria-labelledby="story-title" className="flex flex-col gap-4">
        <h2 id="story-title" className="text-2xl font-semibold tracking-tight">
          Why we built it
        </h2>
        <p className="text-subtle-foreground">
          Great explainers take hours of scripting, recording, animating and editing. Most people
          with something worth teaching never get past the first step. {siteConfig.name} plans a
          storyboard from your topic, writes and voices the narration, animates every scene to the
          exact timing of the audio and renders the result as a video in the formats each platform
          expects.
        </p>
        <p className="text-subtle-foreground">
          We are building {siteConfig.name} in India for creators, teachers, developers and teams
          everywhere who would rather spend their time on ideas than on timelines.
        </p>
      </section>
      <section aria-labelledby="principles-title" className="flex flex-col gap-6">
        <h2 id="principles-title" className="text-2xl font-semibold tracking-tight">
          What we believe
        </h2>
        <ul className="grid gap-4 sm:grid-cols-2">
          {principles.map((principle) => (
            <li key={principle.title} className="rounded-lg border bg-surface p-6">
              <h3 className="font-medium">{principle.title}</h3>
              <p className="mt-2 text-sm text-subtle-foreground">{principle.description}</p>
            </li>
          ))}
        </ul>
      </section>
      <p className="text-subtle-foreground">
        Questions or ideas?{" "}
        <Link
          href="/contact"
          className="rounded-sm text-foreground underline underline-offset-4 focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
        >
          Get in touch
        </Link>
        .
      </p>
    </div>
  );
}
