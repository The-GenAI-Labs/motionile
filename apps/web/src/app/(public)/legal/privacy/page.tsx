import type { Metadata } from "next";
import Link from "next/link";

import { LegalDocument, type LegalSection } from "@/components/shared/legal-document";
import { siteConfig } from "@/config/site";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  title: "Privacy Policy",
  description:
    "How Motionile collects, uses, shares and protects personal data, including voice samples and connected accounts, and your rights under India's DPDP Act, 2023.",
  path: "/legal/privacy",
});

const { name } = siteConfig;
const { entityName, registeredAddress, grievanceOfficerName } = siteConfig.legal;
const { privacyEmail, grievanceEmail } = siteConfig.contact;

const sections: readonly LegalSection[] = [
  {
    id: "who-we-are",
    title: "Who we are",
    content: (
      <>
        <p>
          {entityName}, with its registered office at {registeredAddress} (&quot;{name}&quot;,
          &quot;we&quot;, &quot;us&quot;), is the Data Fiduciary for the personal data described in
          this Privacy Policy under the Digital Personal Data Protection Act, 2023 (the &quot;DPDP
          Act&quot;). This policy also reflects our obligations under the Information Technology
          Act, 2000 and the Information Technology (Reasonable Security Practices and Procedures and
          Sensitive Personal Data or Information) Rules, 2011.
        </p>
        <p>
          It applies to the {name} website, web application, APIs and MCP server (the
          &quot;Service&quot;). Words with capital letters that are not defined here have the
          meaning given in our <Link href="/legal/terms">Terms of Service</Link>.
        </p>
      </>
    ),
  },
  {
    id: "data-we-collect",
    title: "Personal data we collect",
    content: (
      <>
        <ul>
          <li>
            <strong>Account data:</strong> name, email address, phone number, hashed password,
            sign-in method (including Google, GitHub or Microsoft profile identifiers if you use
            them) and verification status.
          </li>
          <li>
            <strong>Content you provide:</strong> prompts, questions, uploaded documents, edited
            storyboards, custom skills, preferences and memory you ask us to keep.
          </li>
          <li>
            <strong>Voice data:</strong> voice recordings you upload for a custom voice, your
            recorded consent statement and the resulting voice model.
          </li>
          <li>
            <strong>Connected accounts:</strong> the identifiers, display names and access tokens
            issued by platforms you connect, such as YouTube, Instagram, Facebook, LinkedIn,
            Threads, X, TikTok and blogging platforms, and the status of posts we publish for you.
          </li>
          <li>
            <strong>Billing data:</strong> order, payment, subscription and refund records, invoice
            details such as billing name, state and GSTIN, and the payment reference and method type
            returned by Razorpay. We never receive or store your full card number, CVV, UPI PIN or
            banking credentials.
          </li>
          <li>
            <strong>Usage and device data:</strong> IP address, browser and device type, pages
            visited, actions taken, request identifiers, error logs and security events.
          </li>
          <li>
            <strong>Communications:</strong> messages you send to support and our replies.
          </li>
        </ul>
        <p>
          We do not intentionally collect sensitive categories of data. Please do not include
          health, financial account or similar sensitive information in prompts or uploads.
        </p>
      </>
    ),
  },
  {
    id: "consent-and-purposes",
    title: "Consent and purposes of processing",
    content: (
      <>
        <p>
          We process your personal data on the basis of the consent you give when you create an
          account and use specific features, and for the legitimate uses permitted by Section 7 of
          the DPDP Act, such as complying with law. When we ask for consent, we give you a clear
          notice of the data and the purpose, and you can withdraw consent at any time as easily as
          you gave it. We use personal data to:
        </p>
        <ul>
          <li>create and secure your account, verify your email or phone and prevent fraud;</li>
          <li>generate storyboards, narration, voices and videos at your request;</li>
          <li>publish videos to the accounts you connect, only when you ask us to;</li>
          <li>
            process payments, maintain the credit ledger, issue GST invoices and handle refunds;
          </li>
          <li>provide support and send service messages about your account and purchases;</li>
          <li>maintain, debug and improve the reliability, safety and quality of the Service;</li>
          <li>comply with legal obligations and respond to lawful requests from authorities.</li>
        </ul>
        <p>
          We do not sell your personal data. We do not use your prompts, uploads, voice data or
          videos to train general-purpose AI models. We do not send marketing messages without your
          separate consent.
        </p>
      </>
    ),
  },
  {
    id: "voice-data",
    title: "Voice samples and voice cloning",
    content: (
      <p>
        Voice recordings are collected only after you complete our explicit consent step, are used
        only to create and run the custom voice for your account, and are never shared with other
        users. You can delete a custom voice at any time; we then delete the voice model and its
        source recordings from our systems and instruct our text-to-speech provider to do the same
        within 30 days, unless we must keep a record of your consent to meet a legal obligation.
      </p>
    ),
  },
  {
    id: "connected-accounts",
    title: "Connected social accounts",
    content: (
      <p>
        When you connect a platform, we receive access tokens through that platform&apos;s official
        authorisation flow, limited to the permissions you approve. Tokens are encrypted at rest
        with AES-256-GCM, are never shown in logs or responses, and are used only to upload and
        publish content you choose and to check its status. Disconnecting an account, or revoking
        access from the platform, deletes the stored tokens. We also honour data deletion callbacks
        sent by platforms.
      </p>
    ),
  },
  {
    id: "sharing",
    title: "Who we share data with",
    content: (
      <>
        <p>
          We share personal data only with Data Processors who act on our instructions under written
          contracts that require them to protect it, and only to the extent needed:
        </p>
        <ul>
          <li>cloud hosting, database, storage and content delivery providers;</li>
          <li>
            AI model, text-to-speech and web search providers that process prompts, scripts and
            voice data to produce your outputs;
          </li>
          <li>
            email and WhatsApp messaging providers for verification codes and service messages;
          </li>
          <li>Razorpay, as our payment aggregator, for payments, subscriptions and refunds;</li>
          <li>error monitoring and security providers.</li>
        </ul>
        <p>
          We share data with platforms you connect only when you ask us to publish. We may disclose
          data where required by law, court order or a lawful request from a government agency, or
          to protect the rights and safety of our users and the public. If {name} is involved in a
          merger or acquisition, personal data may be transferred subject to this policy.
        </p>
      </>
    ),
  },
  {
    id: "cross-border",
    title: "Cross-border transfers",
    content: (
      <p>
        Some of our processors store or process data outside India, for example AI model providers
        and cloud regions in other countries. We transfer personal data outside India only as
        permitted by the DPDP Act and never to a country or territory restricted by the Central
        Government under Section 16 of the Act, and we require processors to protect transferred
        data to the standard described in this policy.
      </p>
    ),
  },
  {
    id: "retention",
    title: "Data retention",
    content: (
      <>
        <ul>
          <li>Account data is kept while your account is active.</li>
          <li>
            Prompts, storyboards and videos are kept until you delete them or close your account.
          </li>
          <li>Voice data is kept until you delete the voice or close your account.</li>
          <li>
            Billing, invoice and credit ledger records are kept for 8 years to meet tax and
            accounting obligations under the Central Goods and Services Tax Act, 2017 and the
            Companies Act, 2013.
          </li>
          <li>
            Security and access logs are kept for up to 180 days, or longer where required by law.
          </li>
        </ul>
        <p>
          When you close your account, we delete or anonymise your personal data within 30 days,
          except data we must keep for the legal reasons above. Backups are overwritten on a rolling
          cycle of up to 35 days.
        </p>
      </>
    ),
  },
  {
    id: "security",
    title: "How we protect your data",
    content: (
      <p>
        We use reasonable security practices, including encryption in transit with TLS, encryption
        of third-party credentials at rest, hashed passwords, refresh tokens and one-time codes,
        private storage with signed, owner-scoped access to videos, access controls, audit logs and
        rate limiting. No system is perfectly secure. If a personal data breach occurs, we will
        notify the Data Protection Board of India and affected users as required by the DPDP Act and
        its rules, and report to CERT-In where required.
      </p>
    ),
  },
  {
    id: "your-rights",
    title: "Your rights as a Data Principal",
    content: (
      <>
        <p>Under the DPDP Act you have the right to:</p>
        <ul>
          <li>obtain a summary of the personal data we process and the processing activities;</li>
          <li>know the identities of the Data Fiduciaries and Data Processors we share it with;</li>
          <li>correct, complete or update inaccurate or incomplete personal data;</li>
          <li>erase personal data that is no longer needed, unless we must keep it by law;</li>
          <li>
            withdraw consent at any time, without affecting processing done before withdrawal;
          </li>
          <li>nominate another person to exercise your rights in case of death or incapacity;</li>
          <li>have your grievances addressed by our Grievance Officer.</li>
        </ul>
        <p>
          You can exercise most rights in your account settings, or by emailing{" "}
          <a href={`mailto:${privacyEmail}`}>{privacyEmail}</a>. We may need to verify your
          identity. We will respond within the period prescribed under the DPDP Act and its rules,
          and in any case within 30 days.
        </p>
      </>
    ),
  },
  {
    id: "cookies",
    title: "Cookies",
    content: (
      <>
        <p>
          We use only cookies that are needed to run the Service securely. We do not use advertising
          or cross-site tracking cookies.
        </p>
        <ul>
          <li>
            <strong>Authentication cookies</strong> (prefixed <code>mo_</code>) keep you signed in
            and protect your session. They are HttpOnly where possible and expire automatically.
          </li>
          <li>
            <strong>Security cookies</strong> protect against cross-site request forgery.
          </li>
          <li>
            <strong>Third-party cookies</strong> may be set by Cloudflare Turnstile when it checks
            that a request comes from a person, and by Razorpay during checkout.
          </li>
        </ul>
        <p>Blocking these cookies in your browser will prevent you from signing in or paying.</p>
      </>
    ),
  },
  {
    id: "children",
    title: "Children",
    content: (
      <p>
        The Service is meant only for people aged 18 and over. We do not knowingly process the
        personal data of children as defined in the DPDP Act, and we do not track, profile or target
        advertising at children. If you believe a child has created an account, contact us and we
        will delete it.
      </p>
    ),
  },
  {
    id: "grievance-officer",
    title: "Grievance Officer and the Data Protection Board",
    content: (
      <>
        <p>
          If you have a concern or complaint about how we handle your personal data, please contact
          our Grievance Officer:
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
  {
    id: "changes",
    title: "Changes to this policy",
    content: (
      <p>
        We will post any update on this page with a new &quot;Last updated&quot; date. If we make a
        material change, or want to use your data for a new purpose, we will notify you in advance
        and ask for fresh consent where the law requires it.
      </p>
    ),
  },
];

export default function PrivacyPage() {
  return (
    <LegalDocument
      title="Privacy Policy"
      summary={`What personal data ${name} collects, why we use it, who we share it with, how long we keep it and how you can exercise your rights under Indian law.`}
      sections={sections}
    />
  );
}
