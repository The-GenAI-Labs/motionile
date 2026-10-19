"use client";

import { useEffect, useRef } from "react";

import type { CheckoutController } from "@/features/billing/hooks/use-checkout";
import type { Product, PurchaseKind } from "@/features/billing/types/billing.types";

interface AutoStartInput {
  kind: PurchaseKind;
  requestedCode: string | null;
  products: readonly Product[] | undefined;
  ready: boolean;
  checkout: CheckoutController;
  cleanPath: string;
}

export const useAutoStartCheckout = ({
  kind,
  requestedCode,
  products,
  ready,
  checkout,
  cleanPath,
}: AutoStartInput): { unavailable: boolean } => {
  const attempted = useRef(false);
  const found = products?.some((product) => product.code === requestedCode) ?? false;
  const { start } = checkout;

  useEffect(() => {
    if (!ready || attempted.current || requestedCode === null || products === undefined) {
      return;
    }
    attempted.current = true;
    window.history.replaceState(null, "", cleanPath);
    if (found) {
      void start(kind, requestedCode);
    }
  }, [ready, requestedCode, products, found, kind, start, cleanPath]);

  return { unavailable: ready && requestedCode !== null && products !== undefined && !found };
};
