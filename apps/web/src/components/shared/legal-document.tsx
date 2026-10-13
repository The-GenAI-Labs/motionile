import { TriangleAlertIcon } from "lucide-react";
import type { ReactNode } from "react";

import { PageHeader } from "@/components/shared/page-header";
import { siteConfig } from "@/config/site";

export interface LegalSection {
  id: string;
  title: string;
  content: ReactNode;
}

interface LegalDocumentProps {
  title: string;
  summary: string;
  sections: readonly LegalSection[];
}

export function LegalDocument({ title, summary, sections }: LegalDocumentProps) {
  return (
    <article className="mx-auto flex w-full max-w-4xl flex-col gap-10 px-6 py-16 sm:py-24">
      <PageHeader eyebrow="Legal" title={title} description={summary} />
      <aside
        role="note"
        aria-label="Draft notice"
        className="flex gap-3 rounded-lg border border-destructive/60 bg-destructive/10 p-4 text-sm"
      >
        <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-destructive" />
        <p>
          <strong className="font-semibold">Draft pending legal review.</strong> This document is a
          draft and has not yet been reviewed by a lawyer. Placeholders in square brackets will be
          completed before it takes effect.
        </p>
      </aside>
      <dl className="grid gap-2 font-mono text-sm text-muted-foreground sm:grid-cols-2">
        <div className="flex gap-2">
          <dt>Effective date:</dt>
          <dd className="text-subtle-foreground">{siteConfig.legal.effectiveDate}</dd>
        </div>
        <div className="flex gap-2">
          <dt>Last updated:</dt>
          <dd className="text-subtle-foreground">{siteConfig.legal.lastUpdated}</dd>
        </div>
      </dl>
      <nav aria-label="Table of contents" className="rounded-lg border bg-surface p-6">
        <h2 className="text-sm font-medium">Contents</h2>
        <ol className="mt-3 grid list-decimal gap-1.5 pl-5 text-sm text-subtle-foreground sm:grid-cols-2">
          {sections.map((section) => (
            <li key={section.id}>
              <a
                href={`#${section.id}`}
                className="rounded-sm hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none"
              >
                {section.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>
      <div className="flex flex-col gap-10">
        {sections.map((section, index) => (
          <section
            key={section.id}
            id={section.id}
            aria-labelledby={`${section.id}-title`}
            className="scroll-mt-24"
          >
            <h2 id={`${section.id}-title`} className="text-xl font-semibold tracking-tight">
              {index + 1}. {section.title}
            </h2>
            <div className="mt-4 flex flex-col gap-3 text-subtle-foreground [&_a]:text-foreground [&_a]:underline [&_a]:underline-offset-4 [&_li]:ml-5 [&_ol]:list-decimal [&_strong]:text-foreground [&_ul]:list-disc [&_ul]:space-y-1.5">
              {section.content}
            </div>
          </section>
        ))}
      </div>
    </article>
  );
}
