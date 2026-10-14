import type { Metadata } from "next";
import Link from "next/link";

import { LegalDocument, type LegalSection } from "@/components/shared/legal-document";
import { siteConfig } from "@/config/site";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  title: "Data Deletion",
  description:
    "How to delete your Motionile account and data, remove Motionile from connected Google, Meta, LinkedIn, X and TikTok accounts, and what records we must retain.",
  path: "/legal/data-deletion",
});

const { name } = siteConfig;
const { entityName, registeredAddress, grievanceOfficerName } = siteConfig.legal;
const { privacyEmail, grievanceEmail } = siteConfig.contact;

const sections: readonly LegalSection[] = [
  {
    id: "scope",
    title: "Scope",
    content: (
      <p>
        This page explains how you can ask {entityName} (&quot;{name}&quot;, &quot;we&quot;,
        &quot;us&quot;) to delete your personal data, and how to remove {name}&apos;s access to
        accounts you connected on other platforms. It forms part of our{" "}
        <Link href="/legal/privacy">Privacy Policy</Link>, which describes your rights as a Data
        Principal under the Digital Personal Data Protection Act, 2023.
      </p>
    ),
  },
  {
    id: "what-you-can-delete",
    title: "What you can delete",
    content: (
      <>
        <p>You can ask us to delete your {name} account and everything linked to it, including:</p>
        <ul>
          <li>your profile, sign-in details and preferences;</li>
          <li>generated videos, storyboards, scripts and narration;</li>
          <li>voice samples, consent recordings and cloned voices;</li>
          <li>
            connected social accounts, including the OAuth access and refresh tokens we store for
            them, which we revoke where the platform allows it;
          </li>
          <li>custom skills and the memory you asked us to keep;</li>
          <li>documents and other files you uploaded.</li>
        </ul>
        <p>
          You can also delete individual videos, voices, skills and connected accounts at any time
          without closing your account.
        </p>
      </>
    ),
  },
  {
    id: "how-to-request",
    title: "How to request deletion",
    content: (
      <>
        <p>You can request deletion of your account in either of these ways:</p>
        <ul>
          <li>
            <strong>In the app:</strong> once available, go to{" "}
            <strong>Settings → Account → Delete account</strong> and follow the steps.
          </li>
          <li>
            <strong>By email:</strong> write to{" "}
            <a href={`mailto:${privacyEmail}`}>{privacyEmail}</a> from, or quoting, the email
            address registered to your {name} account and ask us to delete it.
          </li>
        </ul>
        <p>
          To protect your account, we confirm your identity before deleting anything, for example by
          sending a one-time code to your registered email address. We never ask for your password.
        </p>
        <p>
          Once your identity is confirmed, we delete or anonymise your personal data within 30 days,
          except the records described in <a href="#what-we-retain">What we retain and why</a>. We
          email you when deletion is complete. Deletion is permanent and cannot be undone. Unused
          credits are forfeited as set out in our <Link href="/legal/terms">Terms of Service</Link>,
          except where a refund is due under our{" "}
          <Link href="/legal/refund-policy">Refund and Cancellation Policy</Link> or applicable law.
        </p>
      </>
    ),
  },
  {
    id: "connected-platforms",
    title: "Removing Motionile from a connected platform",
    content: (
      <>
        <p>
          You can disconnect a platform from your {name} settings, or revoke {name}&apos;s access
          directly in the platform&apos;s own settings. Once access is revoked, {name} can no longer
          read from or publish to that account, and we delete the stored tokens for it.
        </p>
        <ul>
          <li>
            <strong>Google and YouTube:</strong> open your Google Account, go to Security, then
            Third-party apps and services, select {name} and remove its access.
          </li>
          <li>
            <strong>Facebook:</strong> go to Settings and privacy, Settings, Apps and websites,
            select {name} and choose Remove.
          </li>
          <li>
            <strong>Instagram and Threads:</strong> remove {name} under Apps and websites in your
            account settings, or through the Meta Accounts Centre for the linked Facebook account.
          </li>
          <li>
            <strong>LinkedIn:</strong> go to Settings, Data privacy, Permitted services, and remove{" "}
            {name}.
          </li>
          <li>
            <strong>X:</strong> go to Settings and privacy, Security and account access, Apps and
            sessions, Connected apps, select {name} and revoke its permissions.
          </li>
          <li>
            <strong>TikTok:</strong> go to Settings and privacy, Security and permissions, Apps and
            services permissions, select {name} and remove access.
          </li>
        </ul>
        <p>
          When you remove {name} from Facebook and ask for your data to be deleted, Facebook sends
          us a data deletion request. You receive a confirmation code and a link where you can check
          the status of that request. Quote the confirmation code if you contact us about it.
        </p>
        <p>
          Revoking access on a platform does not delete videos already published there; delete those
          on the platform itself. It also does not close your {name} account; to delete your
          account, follow the steps in <a href="#how-to-request">How to request deletion</a>.
        </p>
      </>
    ),
  },
  {
    id: "what-we-retain",
    title: "What we retain and why",
    content: (
      <>
        <p>
          Some records must be kept after your account is deleted, and only for the stated purpose:
        </p>
        <ul>
          <li>
            <strong>Invoices, payment and GST records</strong> are kept for 8 years to meet tax and
            accounting obligations under the Central Goods and Services Tax Act, 2017 and the
            Companies Act, 2013.
          </li>
          <li>
            <strong>Credit ledger entries</strong> are kept for the same period to keep our accounts
            consistent, anonymised so they are no longer linked to you.
          </li>
          <li>
            <strong>Security and access logs</strong> are kept for up to 180 days, or longer where
            required by law, to detect and investigate abuse.
          </li>
          <li>
            <strong>Backups</strong> are not edited individually; deleted data rolls off them within
            the backup retention period.
          </li>
        </ul>
        <p>
          We may also keep data where the law requires it, for example to comply with a lawful order
          or to establish, exercise or defend legal claims.
        </p>
      </>
    ),
  },
  {
    id: "grievance-officer",
    title: "Grievance Officer",
    content: (
      <>
        <p>
          If you have a concern about a deletion request or how we handle your personal data,
          contact our Grievance Officer:
        </p>
        <address className="not-italic">
          {grievanceOfficerName}, Grievance Officer
          <br />
          {entityName}, {registeredAddress}
          <br />
          Email: <a href={`mailto:${grievanceEmail}`}>{grievanceEmail}</a>
        </address>
        <p>
          We acknowledge complaints within 48 hours and resolve them within the period prescribed by
          law. If you are not satisfied with our response, you may file a complaint with the Data
          Protection Board of India after exhausting this grievance redressal process.
        </p>
      </>
    ),
  },
];

export default function DataDeletionPage() {
  return (
    <LegalDocument
      title="Data Deletion"
      summary={`How to delete your ${name} account and data, how to remove ${name} from accounts you connected on other platforms, and which records we must keep.`}
      sections={sections}
    />
  );
}
