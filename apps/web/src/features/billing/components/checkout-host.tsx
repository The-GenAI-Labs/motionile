"use client";

import { useRouter } from "next/navigation";

import type { CheckoutController } from "@/features/billing/hooks/use-checkout";
import { CheckoutLauncher } from "@/lib/razorpay/checkout-launcher";

interface CheckoutHostProps {
  checkout: CheckoutController;
}

export function CheckoutHost({ checkout }: CheckoutHostProps) {
  const router = useRouter();
  if (checkout.target === null) {
    return null;
  }
  return (
    <CheckoutLauncher
      target={checkout.target}
      verify={checkout.verify}
      onFinished={(orderId) => {
        router.push(`/billing/status/${orderId}`);
      }}
      onDismiss={checkout.close}
    />
  );
}
