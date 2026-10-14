import type { Metadata } from "next";

import { PageHeader } from "@/components/shared/page-header";
import { siteConfig } from "@/config/site";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  title: "Contact",
  description:
    "Contact Motionile support, billing, privacy and grievance teams by email, or follow Motionile on social media.",
  path: "/contact",
});

const contactChannels = [
  {
    title: "Support",
    description: "Help with your account, generations and publishing.",
    email: siteConfig.contact.supportEmail,
  },
  {
    title: "Billing",
    description: "Payments, invoices, subscriptions and refunds.",
    email: siteConfig.contact.billingEmail,
  },
  {
    title: "Privacy",
    description: "Requests about your personal data and consent.",
    email: siteConfig.contact.privacyEmail,
  },
  {
    title: "Grievances",
    description: "Complaints for our Grievance Officer under Indian law.",
    email: siteConfig.contact.grievanceEmail,
  },
] as const;

const socialLinks = [
  { title: "YouTube", href: siteConfig.social.youtube },
  { title: "LinkedIn", href: siteConfig.social.linkedin },
  { title: "X", href: siteConfig.social.x },
] as const;

const linkClassName =
  "rounded-sm text-foreground underline underline-offset-4 focus-visible:ring-[3px] focus-visible:ring-ring focus-visible:outline-none";

export default function ContactPage() {
  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-16 px-6 py-16 sm:py-24">
      <PageHeader
        eyebrow="Contact"
        title="Get in touch"
        description="Email the right team and we will get back to you, usually within two working days."
      />
      <section aria-labelledby="email-title" className="flex flex-col gap-6">
        <h2 id="email-title" className="text-2xl font-semibold tracking-tight">
          Email us
        </h2>
        <ul className="grid gap-4 sm:grid-cols-2">
          {contactChannels.map((channel) => (
            <li key={channel.title} className="rounded-lg border bg-surface p-6">
              <h3 className="font-medium">{channel.title}</h3>
              <p className="mt-2 text-sm text-subtle-foreground">{channel.description}</p>
              <a
                href={`mailto:${channel.email}`}
                className={`mt-4 inline-block text-sm ${linkClassName}`}
              >
                {channel.email}
              </a>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="address-title" className="flex flex-col gap-3">
        <h2 id="address-title" className="text-2xl font-semibold tracking-tight">
          Registered office
        </h2>
        <address className="text-subtle-foreground not-italic">
          {siteConfig.legal.entityName}
          <br />
          {siteConfig.legal.registeredAddress}
        </address>
      </section>
      <section aria-labelledby="social-title" className="flex flex-col gap-3">
        <h2 id="social-title" className="text-2xl font-semibold tracking-tight">
          Follow {siteConfig.name}
        </h2>
        <ul className="flex flex-wrap gap-6">
          {socialLinks.map((link) => (
            <li key={link.title}>
              <a
                href={link.href}
                rel="noopener noreferrer"
                target="_blank"
                className={linkClassName}
              >
                {link.title}
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
