"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminBillingError } from "@/features/admin-billing/components/admin-billing-error";
import { DetailList, DetailSection } from "@/features/admin-billing/components/detail-section";
import { ProductActions } from "@/features/admin-billing/components/product-actions";
import { ProductEditForm } from "@/features/admin-billing/components/product-form";
import { useAdminProduct } from "@/features/admin-billing/hooks/use-admin-products";
import { adminBillingPaths } from "@/features/admin-billing/paths";
import {
  IMMUTABILITY_EXPLANATION,
  intervalLabels,
  productKindLabels,
} from "@/features/admin-billing/schemas/admin-billing.schema";
import type { AdminProductDetail } from "@/features/admin-billing/types/admin-billing.types";
import { usePermissions } from "@/features/auth/hooks/use-permissions";
import { formatCredits, formatDateTime, formatPaise } from "@/lib/utils/format";

function ProductSummary({ product }: { product: AdminProductDetail }) {
  return (
    <DetailSection title={product.name}>
      <div className="flex flex-wrap gap-2">
        <Badge variant={product.isActive ? "success" : "outline"}>
          {product.isActive ? "Active" : "Inactive"}
        </Badge>
        <Badge variant="outline">{productKindLabels[product.kind]}</Badge>
        {product.isSample ? <Badge variant="outline">Sample</Badge> : null}
        {product.isUsed ? <Badge variant="outline">In use</Badge> : null}
      </div>
      <DetailList
        items={[
          { label: "Code", value: <span className="font-mono">{product.code}</span> },
          {
            label: "Price (incl. GST)",
            value: (
              <span className="font-mono">
                {formatPaise(product.pricePaise)}
                {product.interval ? ` ${intervalLabels[product.interval].toLowerCase()}` : ""}
              </span>
            ),
          },
          {
            label: "Credits",
            value: <span className="font-mono">{formatCredits(product.creditsGranted)}</span>,
          },
          { label: "Currency", value: product.currency },
          ...(product.planKey
            ? [{ label: "Plan key", value: <span className="font-mono">{product.planKey}</span> }]
            : []),
          ...(product.kind === "subscription"
            ? [
                {
                  label: "Razorpay plan",
                  value: product.razorpayPlanId ? (
                    <span className="font-mono">{product.razorpayPlanId}</span>
                  ) : (
                    "Not synced"
                  ),
                },
              ]
            : []),
          { label: "Version", value: <span className="font-mono">v{product.version}</span> },
          { label: "Created", value: formatDateTime(product.createdAt) },
          { label: "Updated", value: formatDateTime(product.updatedAt) },
        ]}
      />
      {product.supersedes || product.supersededBy.length > 0 ? (
        <div className="space-y-1 text-sm">
          {product.supersedes ? (
            <p>
              Supersedes{" "}
              <Link href={adminBillingPaths.product(product.supersedes.id)} className="underline">
                {product.supersedes.name} (v{product.supersedes.version})
              </Link>
              .
            </p>
          ) : null}
          {product.supersededBy.map((next) => (
            <p key={next.id}>
              Superseded by{" "}
              <Link href={adminBillingPaths.product(next.id)} className="underline">
                {next.name} (v{next.version})
              </Link>
              .
            </p>
          ))}
        </div>
      ) : null}
    </DetailSection>
  );
}

export function ProductDetail({ productId }: { productId: string }) {
  const product = useAdminProduct(productId);
  const { can } = usePermissions();
  if (product.isPending) {
    return <Skeleton role="status" aria-label="Loading product" className="h-96" />;
  }
  if (product.isError) {
    return (
      <AdminBillingError
        error={product.error}
        onRetry={() => {
          void product.refetch();
        }}
      />
    );
  }
  const data = product.data;
  const canManage = can("billing.products.manage");
  return (
    <div className="space-y-6">
      <ProductSummary product={data} />
      {canManage ? (
        <>
          <DetailSection title="Actions">
            <ProductActions product={data} />
          </DetailSection>
          <DetailSection title="Edit product">
            <ProductEditForm
              key={data.version}
              product={data}
              onReload={() => {
                void product.refetch();
              }}
            />
          </DetailSection>
        </>
      ) : (
        <DetailSection title="Editing">
          <p className="text-sm text-muted-foreground">
            Changing products needs the billing.products.manage permission, which your account does
            not have. {IMMUTABILITY_EXPLANATION}
          </p>
        </DetailSection>
      )}
    </div>
  );
}
