import { authErrorMessage } from "@/features/auth/errors";
import { ApiError } from "@/lib/api/api-error";

export const billingErrorMessages: Readonly<Record<string, string>> = {
  insufficient_credits: "You do not have enough credits for this.",
  product_not_found: "That plan or credit pack is no longer available.",
  product_not_purchasable: "That plan or credit pack is not available to buy right now.",
  order_not_found: "We could not find that order.",
  order_not_payable: "That order can no longer be paid. Start a new purchase instead.",
  invalid_payment_signature:
    "We could not verify the payment. If you were charged, it will be applied automatically.",
  payment_order_mismatch:
    "The payment does not match the order. If you were charged, contact support.",
  payment_provider_unavailable: "The payment provider is unavailable. Please try again shortly.",
  payment_provider_rejected: "The payment provider rejected the request. Please try again.",
  payment_provider_error: "The payment provider returned an error. Please try again shortly.",
  subscription_exists: "You already have a subscription. Change or cancel it from the Plans page.",
  subscription_not_found: "You do not have a subscription.",
  subscription_not_changeable:
    "Your plan can only be changed while it is active and not scheduled to end.",
  subscription_not_cancellable: "This subscription can no longer be cancelled.",
  idempotency_request_in_progress:
    "Your previous attempt is still being processed. Try again in a moment.",
  idempotency_key_reused: "This request was already used. Start the action again.",
};

export const billingErrorMessage = (error: unknown): string =>
  billingErrorMessages[ApiError.from(error).code] ?? authErrorMessage(error);

export const isRetryableCheckoutError = (error: unknown): boolean => {
  const normalized = ApiError.from(error);
  return normalized.isTransient || normalized.code === "idempotency_request_in_progress";
};
