import type { Metadata } from "next";
import Link from "next/link";

import { LegalDocument, type LegalSection } from "@/components/shared/legal-document";
import { siteConfig } from "@/config/site";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  title: "Terms of Service",
  description:
    "The terms that govern your use of Motionile, including accounts, credits, subscriptions, acceptable use, ownership of generated videos and Indian governing law.",
  path: "/legal/terms",
});

const { name } = siteConfig;
const { entityName, registeredAddress, jurisdictionCity, grievanceOfficerName } = siteConfig.legal;
const { supportEmail, grievanceEmail, legalEmail } = siteConfig.contact;

const sections: readonly LegalSection[] = [
  {
    id: "agreement",
    title: "About these terms",
    content: (
      <>
        <p>
          These Terms of Service (the &quot;Terms&quot;) form a binding agreement between you and{" "}
          {entityName}, a company incorporated in India with its registered office at{" "}
          {registeredAddress} (&quot;{name}&quot;, &quot;we&quot;, &quot;us&quot;). They govern your
          access to and use of the {name} website, web application, APIs, MCP server and related
          services (together, the &quot;Service&quot;).
        </p>
        <p>
          By creating an account, purchasing credits or a subscription, or otherwise using the
          Service, you confirm that you have read and accept these Terms, our{" "}
          <Link href="/legal/privacy">Privacy Policy</Link> and our{" "}
          <Link href="/legal/refund-policy">Refund and Cancellation Policy</Link>. If you do not
          agree, do not use the Service.
        </p>
        <p>
          These Terms are an electronic record under the Information Technology Act, 2000 and the
          rules made under it, and do not require a physical or digital signature.
        </p>
      </>
    ),
  },
  {
    id: "service",
    title: "The Service",
    content: (
      <>
        <p>
          {name} turns a topic or a question into a short narrated, animated explainer video. The
          Service plans a storyboard, writes and voices narration, generates animated scenes,
          renders them into video files and, if you choose, publishes them to accounts you connect
          through each platform&apos;s official API.
        </p>
        <p>
          Generated content is produced by automated systems, including artificial intelligence
          models operated by us and by third-party providers. Outputs can be inaccurate, incomplete
          or unsuitable for your purpose. You are responsible for reviewing every storyboard and
          video before you rely on, publish or share it.
        </p>
        <p>
          We may change, add or remove features to improve the Service, comply with law or respond
          to changes by our providers or by platforms. If a change materially reduces a paid feature
          you have already bought, we will tell you in advance where reasonably possible.
        </p>
      </>
    ),
  },
  {
    id: "eligibility",
    title: "Eligibility and accounts",
    content: (
      <>
        <p>
          You must be at least 18 years old and capable of entering into a binding contract under
          the Indian Contract Act, 1872 to use the Service. The Service is not directed at children,
          and we do not knowingly allow anyone under 18 to register.
        </p>
        <p>
          If you use the Service on behalf of an organisation, you confirm that you are authorised
          to accept these Terms for it, and &quot;you&quot; includes that organisation.
        </p>
        <ul>
          <li>Provide accurate registration details and keep them up to date.</li>
          <li>
            Keep your password and verification codes confidential and do not share your account.
          </li>
          <li>
            Tell us promptly at <a href={`mailto:${supportEmail}`}>{supportEmail}</a> if you suspect
            unauthorised access to your account.
          </li>
        </ul>
        <p>You are responsible for all activity that takes place under your account.</p>
      </>
    ),
  },
  {
    id: "credits",
    title: "Credits",
    content: (
      <>
        <p>
          Generations and certain other features consume credits. The number of credits an action
          needs is shown before you confirm it. Credits are reserved when a generation starts,
          charged according to the work actually completed and any unused reservation is released
          back to your wallet.
        </p>
        <ul>
          <li>
            Credits are a prepaid, limited licence to use the Service. They are not currency, have
            no cash value, earn no interest and cannot be exchanged for money except where a refund
            is required by our Refund and Cancellation Policy or by law.
          </li>
          <li>
            Credits are personal to your account and cannot be sold, transferred, gifted or pooled
            between accounts.
          </li>
          <li>
            Credits expire on the date shown at the time of purchase. Subscription credits expire at
            the end of the period stated in your plan. Expired credits cannot be reinstated.
          </li>
          <li>
            We keep an append-only ledger of every credit change, which you can view in your
            account. If you believe a balance is wrong, contact us within 30 days of the
            transaction.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "payments",
    title: "Prices, payments and taxes",
    content: (
      <>
        <p>
          Prices for credit packs and subscriptions are shown in Indian Rupees (INR) at checkout and
          include Goods and Services Tax (GST) unless stated otherwise. A tax invoice is issued for
          every payment under GSTIN {siteConfig.legal.gstin}. The price that applies is the one
          shown at checkout when you confirm the purchase; we never accept prices from your device
          as the basis for a charge.
        </p>
        <p>
          Payments are processed by Razorpay Software Private Limited (&quot;Razorpay&quot;), a
          payment aggregator authorised by the Reserve Bank of India. Your card, UPI, net banking
          and wallet details are entered on Razorpay&apos;s checkout and are processed under its
          terms and privacy policy. {name} never receives or stores your full card number, CVV or
          banking passwords.
        </p>
        <p>
          A purchase is complete only when Razorpay confirms the payment to us. If a payment is
          debited but not confirmed, we reconcile it automatically and either credit your account or
          the amount is returned to your original payment method in line with Razorpay and bank
          timelines.
        </p>
      </>
    ),
  },
  {
    id: "subscriptions",
    title: "Subscriptions and auto-renewal",
    content: (
      <>
        <p>
          Subscriptions renew automatically at the end of each billing period and the renewal amount
          is charged to the payment method you authorised (for example through a card mandate or UPI
          AutoPay), subject to the Reserve Bank of India rules on recurring payments, including any
          pre-debit notification your bank sends.
        </p>
        <ul>
          <li>
            You can cancel at any time from your billing settings. Cancellation takes effect at the
            end of the current billing period; you keep access and the credits already granted until
            then, and you will not be charged again.
          </li>
          <li>
            If a renewal payment fails, we may retry it for a short period. If it still fails, the
            subscription is paused or cancelled and no further credits are granted.
          </li>
          <li>
            If we change the price of a plan, we will notify you at least 7 days before the change
            applies to your next renewal, and you can cancel before then.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "refunds",
    title: "Refunds and chargebacks",
    content: (
      <>
        <p>
          Refunds are governed by our{" "}
          <Link href="/legal/refund-policy">Refund and Cancellation Policy</Link>. In short, credits
          used by a generation that fails on our side are returned to your wallet, and approved
          monetary refunds are made to your original payment method.
        </p>
        <p>
          Please contact us before raising a chargeback or payment dispute so we can resolve the
          issue quickly. If a chargeback is raised, we may suspend the related credits or the
          account while the dispute is reviewed, and we may share transaction records with Razorpay
          and the issuing bank. Chargebacks found to be unjustified may lead to account suspension.
        </p>
      </>
    ),
  },
  {
    id: "acceptable-use",
    title: "Acceptable use",
    content: (
      <>
        <p>You must not use the Service to create, upload, publish or share content that:</p>
        <ul>
          <li>
            depicts, imitates or clones the face, likeness or voice of a real person without that
            person&apos;s explicit consent, or presents synthetic media as real footage of a real
            event or person (deepfakes);
          </li>
          <li>
            impersonates any person, brand, government body or organisation, or misrepresents your
            affiliation with them;
          </li>
          <li>
            is unlawful, defamatory, obscene, pornographic, paedophilic, invasive of privacy,
            harassing, hateful, or that promotes violence, terrorism, self-harm or discrimination;
          </li>
          <li>
            is harmful to children, threatens the unity, integrity, defence, security or sovereignty
            of India, public order or friendly relations with foreign states, or is otherwise
            prohibited under Rule 3(1)(b) of the Information Technology (Intermediary Guidelines and
            Digital Media Ethics Code) Rules, 2021;
          </li>
          <li>
            is knowingly false or misleading, including misinformation about elections, health,
            finance or emergencies;
          </li>
          <li>infringes any copyright, trademark, patent, trade secret or other right;</li>
          <li>contains malware or attempts to probe, scrape, overload or bypass the Service.</li>
        </ul>
        <p>
          You must also comply with the terms, community guidelines and content policies of every
          platform you publish to through {name}, including YouTube, Instagram, Facebook, LinkedIn,
          Threads, X, TikTok and blogging platforms. You are responsible for disclosing synthetic or
          AI-generated content where a platform or the law requires it.
        </p>
        <p>
          We may refuse a prompt, block a generation, remove content or suspend accounts that breach
          this section, and we may report unlawful content to the authorities where the law
          requires.
        </p>
      </>
    ),
  },
  {
    id: "voice",
    title: "Voice cloning",
    content: (
      <>
        <p>
          If you create a custom voice, you may only upload recordings of your own voice, or of a
          person who has given you verifiable, informed and specific consent to clone their voice
          for use with {name}. Before a voice is created, you must complete our consent step, which
          may include reading a consent statement aloud.
        </p>
        <ul>
          <li>Custom voices are private to your account and are never offered to other users.</li>
          <li>
            You may delete a custom voice at any time; we then delete the voice model and the
            samples used to create it, subject to the retention periods in our Privacy Policy.
          </li>
          <li>
            We may disable a voice if we receive a credible complaint that consent was not given.
          </li>
        </ul>
      </>
    ),
  },
  {
    id: "connected-accounts",
    title: "Connected accounts and publishing",
    content: (
      <>
        <p>
          When you connect a third-party account, you authorise {name} to act on your behalf only
          within the permissions you grant through that platform&apos;s official authorisation
          screen, such as uploading videos and creating posts. We never ask for your platform
          passwords and never automate your accounts with hidden browsers.
        </p>
        <p>
          You can disconnect an account at any time from your settings or from the platform itself.
          Platforms may change or withdraw their APIs, rate limits or policies; we are not
          responsible for a platform&apos;s decision to reject, remove or limit your content.
        </p>
      </>
    ),
  },
  {
    id: "ownership",
    title: "Your content and ownership of outputs",
    content: (
      <>
        <p>
          You keep all rights in the prompts, documents, images, voice samples and other material
          you provide (&quot;Your Content&quot;). You grant {name} a non-exclusive, worldwide,
          royalty-free licence to host, process, transmit and display Your Content only as needed to
          provide, secure and improve the Service for you.
        </p>
        <p>
          As between you and {name}, and to the extent permitted by law, you own the storyboards,
          narration scripts, audio and videos generated for you (&quot;Outputs&quot;), and we assign
          to you any rights we may have in them. Because generation is automated, similar outputs
          may be produced for other users, and copyright protection for AI-assisted works may be
          limited under applicable law. You are responsible for ensuring that your use of Outputs
          does not infringe the rights of others.
        </p>
        <p>
          The {name} software, design, brand, system prompts, built-in skills, templates and
          animation runtime remain our property or that of our licensors. Except for the rights
          expressly granted in these Terms, no rights are transferred to you.
        </p>
      </>
    ),
  },
  {
    id: "providers",
    title: "Third-party providers",
    content: (
      <p>
        We use carefully selected third parties to run the Service, including cloud hosting and
        storage providers, AI model and text-to-speech providers, email and messaging providers, and
        Razorpay for payments. They process data on our behalf under contract, as described in our{" "}
        <Link href="/legal/privacy">Privacy Policy</Link>. Their outages may affect the Service; we
        will use reasonable efforts to restore it and to return credits for generations that fail as
        a result.
      </p>
    ),
  },
  {
    id: "termination",
    title: "Suspension and termination",
    content: (
      <>
        <p>
          You may close your account at any time from your settings or by contacting us. We may
          suspend or terminate your access if you breach these Terms, if required by law or a
          competent authority, or to protect the Service, other users or third parties.
        </p>
        <p>
          On termination, unused credits are forfeited except where a refund is due under our Refund
          and Cancellation Policy or applicable law, or where we terminate without cause, in which
          case we will refund unused paid credits proportionately. Sections that by their nature
          should survive termination, including ownership, disclaimers, limitation of liability and
          governing law, will survive.
        </p>
      </>
    ),
  },
  {
    id: "disclaimers",
    title: "Disclaimers",
    content: (
      <p>
        The Service is provided on an &quot;as is&quot; and &quot;as available&quot; basis. To the
        fullest extent permitted by law, we disclaim all implied warranties, including
        merchantability, fitness for a particular purpose and non-infringement. We do not warrant
        that Outputs will be accurate, error-free or suitable for your purpose, or that the Service
        will be uninterrupted. Nothing in these Terms excludes rights you have as a consumer under
        the Consumer Protection Act, 2019 that cannot lawfully be excluded.
      </p>
    ),
  },
  {
    id: "liability",
    title: "Limitation of liability",
    content: (
      <p>
        To the fullest extent permitted by law, {name} will not be liable for any indirect,
        incidental, special, consequential or punitive damages, or for loss of profits, revenue,
        data, goodwill or audience, arising out of or in connection with the Service. Our total
        liability for all claims relating to the Service in any 12-month period is limited to the
        amount you paid us in that period. These limits do not apply to liability that cannot be
        limited under applicable law, including for fraud.
      </p>
    ),
  },
  {
    id: "indemnity",
    title: "Indemnity",
    content: (
      <p>
        You agree to indemnify and hold harmless {name}, its directors, employees and partners from
        any claims, losses, liabilities and reasonable expenses, including legal fees, arising from
        Your Content, your use of Outputs, your breach of these Terms or your violation of any law
        or third-party right.
      </p>
    ),
  },
  {
    id: "grievances",
    title: "Grievance redressal",
    content: (
      <>
        <p>
          In accordance with the Information Technology Act, 2000, the rules made under it and the
          Consumer Protection (E-Commerce) Rules, 2020, our Grievance Officer is:
        </p>
        <address className="not-italic">
          {grievanceOfficerName}, Grievance Officer
          <br />
          {entityName}, {registeredAddress}
          <br />
          Email: <a href={`mailto:${grievanceEmail}`}>{grievanceEmail}</a>
        </address>
        <p>
          We acknowledge every complaint within 48 hours and aim to resolve it within one month of
          receipt.
        </p>
      </>
    ),
  },
  {
    id: "law",
    title: "Governing law and jurisdiction",
    content: (
      <p>
        These Terms are governed by the laws of India. Subject to any mandatory rights you have as a
        consumer to approach a consumer commission where you reside, the courts at{" "}
        {jurisdictionCity}, India have exclusive jurisdiction over any dispute arising out of or in
        connection with these Terms or the Service.
      </p>
    ),
  },
  {
    id: "changes",
    title: "Changes to these terms",
    content: (
      <p>
        We may update these Terms from time to time. We will post the updated Terms on this page
        with a new &quot;Last updated&quot; date and, for material changes, notify you by email or
        in the app at least 15 days before they take effect. Continuing to use the Service after
        that date means you accept the updated Terms.
      </p>
    ),
  },
  {
    id: "contact",
    title: "Contact",
    content: (
      <p>
        Questions about these Terms can be sent to <a href={`mailto:${legalEmail}`}>{legalEmail}</a>
        .
      </p>
    ),
  },
];

export default function TermsPage() {
  return (
    <LegalDocument
      title="Terms of Service"
      summary={`The rules for using ${name}: your account, credits and subscriptions, what you may create, who owns the videos and how disputes are resolved.`}
      sections={sections}
    />
  );
}
