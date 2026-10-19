import type { CheckoutCompletion, CheckoutTarget } from "@/lib/razorpay/checkout.types";
import type { RazorpaySuccessResponse } from "@/lib/razorpay/razorpay.types";

export const VERIFY_TIMEOUT_MS = 10_000;

export const completionFrom = (
  target: CheckoutTarget,
  response: RazorpaySuccessResponse,
): CheckoutCompletion | null => {
  const paymentId = response.razorpay_payment_id;
  const signature = response.razorpay_signature;
  if (target.kind === "order") {
    const orderId = response.razorpay_order_id ?? target.razorpayOrderId;
    return paymentId && signature
      ? {
          kind: "order",
          razorpayOrderId: orderId,
          razorpayPaymentId: paymentId,
          razorpaySignature: signature,
        }
      : null;
  }
  const subscriptionId = response.razorpay_subscription_id ?? target.razorpaySubscriptionId;
  return paymentId && signature
    ? {
        kind: "subscription",
        razorpaySubscriptionId: subscriptionId,
        razorpayPaymentId: paymentId,
        razorpaySignature: signature,
      }
    : null;
};

const settleWithin = (work: Promise<unknown>, timeoutMs: number): Promise<void> =>
  new Promise((resolve) => {
    const timer = setTimeout(resolve, timeoutMs);
    const finish = () => {
      clearTimeout(timer);
      resolve();
    };
    void work.then(finish, finish);
  });

interface CompleteCheckoutInput {
  completion: CheckoutCompletion | null;
  verify: (completion: CheckoutCompletion) => Promise<unknown>;
  timeoutMs?: number;
}

export const completeCheckout = async ({
  completion,
  verify,
  timeoutMs = VERIFY_TIMEOUT_MS,
}: CompleteCheckoutInput): Promise<void> => {
  if (completion === null) {
    return;
  }
  await settleWithin(
    Promise.resolve().then(() => verify(completion)),
    timeoutMs,
  );
};
