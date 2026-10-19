export interface CheckoutPrefill {
  name: string | null;
  email: string | null;
  contact: string | null;
}

export interface OrderCheckoutTarget {
  kind: "order";
  orderId: string;
  keyId: string;
  razorpayOrderId: string;
  amountPaise: number;
  currency: string;
  description: string;
  prefill: CheckoutPrefill;
}

export interface SubscriptionCheckoutTarget {
  kind: "subscription";
  orderId: string;
  keyId: string;
  razorpaySubscriptionId: string;
  description: string;
  prefill: CheckoutPrefill;
}

export type CheckoutTarget = OrderCheckoutTarget | SubscriptionCheckoutTarget;

export interface OrderCompletion {
  kind: "order";
  razorpayOrderId: string;
  razorpayPaymentId: string;
  razorpaySignature: string;
}

export interface SubscriptionCompletion {
  kind: "subscription";
  razorpaySubscriptionId: string;
  razorpayPaymentId: string;
  razorpaySignature: string;
}

export type CheckoutCompletion = OrderCompletion | SubscriptionCompletion;

export interface CheckoutProps {
  target: CheckoutTarget;
  verify: (completion: CheckoutCompletion) => Promise<unknown>;
  onFinished: (orderId: string) => void;
  onDismiss: () => void;
}
