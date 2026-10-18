import { siteConfig } from "@/config/site";
import type { CheckoutTarget } from "@/lib/razorpay/checkout.types";
import type {
  RazorpayOptions,
  RazorpayPrefill,
  RazorpaySuccessResponse,
} from "@/lib/razorpay/razorpay.types";

interface CheckoutOptionHandlers {
  onPaid: (response: RazorpaySuccessResponse) => void;
  onDismiss: () => void;
}

const buildPrefill = (target: CheckoutTarget): RazorpayPrefill => ({
  ...(target.prefill.name === null ? {} : { name: target.prefill.name }),
  ...(target.prefill.email === null ? {} : { email: target.prefill.email }),
  ...(target.prefill.contact === null ? {} : { contact: target.prefill.contact }),
});

const buildPaymentReference = (
  target: CheckoutTarget,
): Pick<RazorpayOptions, "order_id" | "subscription_id" | "amount" | "currency"> =>
  target.kind === "order"
    ? { order_id: target.razorpayOrderId, amount: target.amountPaise, currency: target.currency }
    : { subscription_id: target.razorpaySubscriptionId };

export const buildRazorpayOptions = (
  target: CheckoutTarget,
  handlers: CheckoutOptionHandlers,
): RazorpayOptions => ({
  key: target.keyId,
  name: siteConfig.name,
  description: target.description,
  ...buildPaymentReference(target),
  prefill: buildPrefill(target),
  theme: { color: siteConfig.themeColor },
  handler: handlers.onPaid,
  modal: { ondismiss: handlers.onDismiss, confirm_close: true },
});
