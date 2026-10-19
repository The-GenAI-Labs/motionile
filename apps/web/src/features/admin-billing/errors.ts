import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const adminBillingGuidance: Readonly<Record<string, string>> = {
  product_version_conflict:
    "This product was changed by someone else. Reload the latest version before saving again.",
  product_immutable:
    "Duplicate the product as a new version to change its price, credits, currency or interval.",
  product_code_exists: "Choose a different product code.",
  plan_not_synced: "Sync the Razorpay plan for this product, then activate it.",
  active_plan_exists:
    "Deactivate the product that is currently active for this plan and interval, then activate this one.",
  product_not_subscription: "Only subscription products have a Razorpay plan.",
  invalid_product_shape: "Check the product fields and try again.",
  payment_not_refundable: "Only a captured payment can be refunded.",
  refund_exceeds_refundable:
    "Lower the amount or refresh the payment to see what can still be refunded.",
  refund_rejected: "The payment provider rejected the refund. Nothing was refunded.",
  adjustment_exceeds_available:
    "Reserved credits cannot be removed. Lower the amount or wait until the reservation is released.",
  invalid_credit_expiry: "Choose an expiry in the future.",
  webhook_event_not_reprocessable: "This event cannot be reprocessed in its current state.",
  subscription_not_cancellable: "This subscription can no longer be cancelled.",
  reconciliation_report_not_found: "This run has no stored report.",
  payment_provider_unavailable:
    "The payment provider is unavailable. Check Razorpay before trying again.",
  idempotency_request_in_progress:
    "Your previous attempt is still being processed. Try again in a moment.",
  idempotency_key_reused: "This request was already used. Close the dialog and start again.",
  forbidden: "Your account is not allowed to do this.",
};

const DETAIL_CODES = new Set([
  "product_immutable",
  "active_plan_exists",
  "refund_exceeds_refundable",
  "payment_provider_unavailable",
  "invalid_product_shape",
]);

export const adminBillingErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  const guidance = adminBillingGuidance[normalized.code];
  if (guidance === undefined) {
    return authErrorMessage(error);
  }
  if (DETAIL_CODES.has(normalized.code) && normalized.detail !== null) {
    return `${normalized.detail} ${guidance}`;
  }
  return guidance;
};

export const hasErrorCode = (error: unknown, code: string): boolean =>
  error instanceof ApiError && error.code === code;

export const isRetryableAttemptError = (error: unknown): boolean => {
  const normalized = ApiError.from(error);
  return normalized.isTransient || normalized.code === "idempotency_request_in_progress";
};
