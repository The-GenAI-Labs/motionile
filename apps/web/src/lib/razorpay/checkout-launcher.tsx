"use client";

import dynamic from "next/dynamic";

import { LoadingSpinner } from "@/components/shared/loading-spinner";
import type { CheckoutProps } from "@/lib/razorpay/checkout.types";

const checkoutLoading = () => <LoadingSpinner label="Loading secure checkout" showLabel />;

const RealCheckout = dynamic(
  () => import("@/lib/razorpay/razorpay-checkout").then((module) => module.RazorpayCheckout),
  { ssr: false, loading: checkoutLoading },
);

const FakeCheckout =
  process.env.NEXT_PUBLIC_PROVIDERS_MODE === "fake"
    ? dynamic(() => import("@/lib/razorpay/fake-checkout").then((module) => module.FakeCheckout), {
        ssr: false,
        loading: checkoutLoading,
      })
    : null;

export function CheckoutLauncher(props: CheckoutProps) {
  const Checkout = FakeCheckout ?? RealCheckout;
  return <Checkout {...props} />;
}
