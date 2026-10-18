import { notFound } from "next/navigation";

import { PageHeader } from "@/components/shared/page-header";
import { OrderStatus } from "@/features/billing/components/order-status";
import { orderIdSchema } from "@/features/billing/schemas/billing.schema";
import { buildMetadata } from "@/lib/seo/metadata";

export const metadata = buildMetadata({
  title: "Payment status",
  description: "Follow the status of your Motionile payment and see when your credits arrive.",
  path: "/billing",
  noIndex: true,
});

interface OrderStatusPageProps {
  params: Promise<{ orderId: string }>;
}

export default async function OrderStatusPage({ params }: OrderStatusPageProps) {
  const { orderId } = await params;
  if (!orderIdSchema.safeParse(orderId).success) {
    notFound();
  }
  return (
    <div className="space-y-8">
      <PageHeader
        title="Payment status"
        description="We confirm your payment before adding credits."
      />
      <OrderStatus orderId={orderId} />
    </div>
  );
}
