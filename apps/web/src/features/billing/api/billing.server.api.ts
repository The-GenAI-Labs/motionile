import "server-only";

import { zBillingListProductsResponse } from "@motionile/api-contract";
import { PHASE_PRODUCTION_BUILD } from "next/constants";

import { serverEnv } from "@/config/server-env";
import { BILLING_PRODUCTS_TAG } from "@/lib/revalidation/tags";

export const BILLING_PRODUCTS_REVALIDATE_SECONDS = 300;

const BILLING_PRODUCTS_TIMEOUT_MS = 10_000;

export const billingProducts = async () => {
  const response = await fetch(new URL("v1/billing/products", `${serverEnv.apiBaseUrl}/`), {
    headers: { accept: "application/json" },
    next: { revalidate: BILLING_PRODUCTS_REVALIDATE_SECONDS, tags: [BILLING_PRODUCTS_TAG] },
    signal: AbortSignal.timeout(BILLING_PRODUCTS_TIMEOUT_MS),
  });
  if (!response.ok) {
    throw new Error(`Billing products request failed with status ${String(response.status)}`);
  }
  return zBillingListProductsResponse.parse(await response.json());
};

const canRenderWithoutProducts = (): boolean =>
  process.env["NEXT_PHASE"] === PHASE_PRODUCTION_BUILD || process.env.NODE_ENV !== "production";

export const loadPricingProducts = async () => {
  try {
    return await billingProducts();
  } catch (error) {
    if (canRenderWithoutProducts()) {
      return null;
    }
    throw error;
  }
};
