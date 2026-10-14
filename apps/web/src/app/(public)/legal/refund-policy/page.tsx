import type { Metadata } from "next";
import Link from "next/link";

import { LegalDocument, type LegalSection } from "@/components/shared/legal-document";
import { siteConfig } from "@/config/site";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata: Metadata = buildMetadata({
  title: "Refund and Cancellation Policy",
  description:
    "When Motionile refunds credits or money, how to cancel a subscription, refund timelines to your original payment method and how chargebacks are handled.",
  path: "/legal/refund-policy",
});

const { name } = siteConfig;
const { entityName, registeredAddress, grievanceOfficerName } = siteConfig.legal;
const { billingEmail, grievanceEmail } = siteConfig.contact;

const sections: readonly LegalSection[] = [
  {
    id: "scope",
    title: "Scope",
    content: (
      <p>
        This policy explains how cancellations and refunds work for credit packs and subscriptions
        bought from {entityName} (&quot;{name}&quot;). It forms part of our{" "}
        <Link href="/legal/terms">Terms of Service</Link> and is published in line with the Consumer
        Protection (E-Commerce) Rules, 2020. All payments are processed in Indian Rupees (INR) by
        Razorpay.
      </p>
    ),
  },
  {
    id: "failed-generations",
    title: "Failed generations",
    content: (
      <>
        <p>
          Credits are reserved when a generation starts and charged only for work that is completed.
          If a generation fails because of an error on our side or at one of our providers, all
          credits reserved or charged for it are returned to your wallet automatically, usually
          within minutes. You will see the reversal in your credit history.
        </p>
        <p>
          Credits are not returned when a generation is stopped or rejected because the request
          breaches our acceptable use rules, or when you cancel a generation after rendering has
          started; in that case only the credits for work not yet done are released.
        </p>
        <p>
          Refunds for failed generations are made as credits, not money, because the original
          purchase was for credits that remain usable.
        </p>
      </>
    ),
  },
  {
    id: "credit-packs",
    title: "Credit packs",
    content: (
      <ul>
        <li>
          You can request a full refund of a credit pack within 7 days of purchase if none of its
          credits have been used.
        </li>
        <li>
          Once credits from a pack have been used, the pack is not refundable, except where the
          Service was materially unavailable or defective and we could not fix it within a
          reasonable time.
        </li>
        <li>Expired credits are not refundable.</li>
        <li>
          When a refund is approved, the unused credits from that purchase are removed from your
          wallet.
        </li>
      </ul>
    ),
  },
  {
    id: "subscriptions",
    title: "Subscriptions and cancellation",
    content: (
      <>
        <ul>
          <li>
            You can cancel your subscription at any time from your billing settings. Cancellation
            stops future renewals and takes effect at the end of the current billing period.
          </li>
          <li>
            You keep access and the credits already granted for the current period until it ends.
          </li>
          <li>
            Subscription payments are not refunded for partially used periods. If you were charged
            for a renewal and have not used any credits from that renewal, you can request a refund
            of that renewal within 7 days of the charge.
          </li>
          <li>
            If we cancel your subscription without cause, we refund the unused portion of the
            current period proportionately.
          </li>
        </ul>
        <p>
          Cancelling a UPI AutoPay or card mandate directly with your bank also stops renewals, but
          please cancel in {name} as well so your account reflects the change.
        </p>
      </>
    ),
  },
  {
    id: "duplicate-payments",
    title: "Duplicate or failed payments",
    content: (
      <p>
        If you are charged twice for the same order, or money is debited but the purchase is not
        confirmed, our reconciliation process detects it and the extra or unconfirmed amount is
        refunded automatically to your original payment method. You do not need to raise a request,
        but you can contact us if you do not see the refund within the timelines below.
      </p>
    ),
  },
  {
    id: "how-to-request",
    title: "How to request a refund",
    content: (
      <>
        <p>
          Email <a href={`mailto:${billingEmail}`}>{billingEmail}</a> from the address registered to
          your account with your order or payment reference and the reason for the request. We will
          confirm receipt within 48 hours and tell you our decision within 7 working days.
        </p>
        <p>
          Approved refunds are reduced by the value of any credits from the purchase that have
          already been used, and the related unused credits are removed from your wallet.
        </p>
      </>
    ),
  },
  {
    id: "timelines",
    title: "Refund method and timelines",
    content: (
      <>
        <p>
          Approved monetary refunds are always made to the original payment method through Razorpay.
          We do not refund in cash or to a different account.
        </p>
        <ul>
          <li>We initiate approved refunds within 2 working days of approval.</li>
          <li>UPI and wallets: usually credited within 2 to 5 working days after initiation.</li>
          <li>
            Debit cards, credit cards and net banking: usually credited within 5 to 10 working days
            after initiation, depending on your bank.
          </li>
        </ul>
        <p>
          The refund includes the GST charged on the refunded amount, and we issue a credit note for
          it.
        </p>
      </>
    ),
  },
  {
    id: "chargebacks",
    title: "Chargebacks",
    content: (
      <p>
        Please contact us before disputing a payment with your bank; most issues are resolved faster
        directly. If a chargeback is raised, the credits from the disputed payment are suspended
        while the bank reviews it, and we provide the transaction and usage records to Razorpay and
        the bank. If the chargeback is decided in your favour, the related credits are removed. If
        it is decided in our favour, the credits are restored. Repeated unjustified chargebacks may
        lead to account suspension.
      </p>
    ),
  },
  {
    id: "grievances",
    title: "Grievances",
    content: (
      <>
        <p>
          If you are not satisfied with how a refund request was handled, contact our Grievance
          Officer:
        </p>
        <address className="not-italic">
          {grievanceOfficerName}, Grievance Officer
          <br />
          {entityName}, {registeredAddress}
          <br />
          Email: <a href={`mailto:${grievanceEmail}`}>{grievanceEmail}</a>
        </address>
        <p>
          We acknowledge complaints within 48 hours and aim to resolve them within one month. This
          does not affect your right to approach a consumer commission under the Consumer Protection
          Act, 2019.
        </p>
      </>
    ),
  },
];

export default function RefundPolicyPage() {
  return (
    <LegalDocument
      title="Refund and Cancellation Policy"
      summary={`When ${name} returns credits or money, how to cancel a subscription and how long refunds take to reach your account.`}
      sections={sections}
    />
  );
}
