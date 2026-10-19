import { PageHeader } from "@/components/shared/page-header";
import { WebhookDetail } from "@/features/admin-billing/components/webhook-detail";
import { requirePermissions } from "@/lib/auth/require-permissions";
import { buildMetadata } from "@/lib/seo/metadata";
import { uuidParam } from "@/lib/utils/route-params";

export const metadata = buildMetadata({
  title: "Webhook event",
  description: "Inspect a Razorpay webhook event and reprocess it.",
  path: "/admin/billing/webhooks",
  noIndex: true,
});

export default async function BillingWebhookPage({
  params,
}: {
  params: Promise<{ eventId: string }>;
}) {
  await requirePermissions(["billing.webhooks.manage"]);
  const { eventId } = await params;
  return (
    <div className="space-y-8">
      <PageHeader
        title="Webhook event"
        description="The stored event, its payload and processing history."
      />
      <WebhookDetail eventId={uuidParam(eventId)} />
    </div>
  );
}
