import type { RazorpayConstructor } from "@/lib/razorpay/razorpay.types";

export const RAZORPAY_CHECKOUT_SCRIPT_URL = "https://checkout.razorpay.com/v1/checkout.js";

let pendingLoad: Promise<RazorpayConstructor> | null = null;

const injectCheckoutScript = (): Promise<RazorpayConstructor> =>
  new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = RAZORPAY_CHECKOUT_SCRIPT_URL;
    script.async = true;
    script.onload = () => {
      if (window.Razorpay) {
        resolve(window.Razorpay);
        return;
      }
      script.remove();
      reject(new Error("Razorpay Checkout loaded without exposing its API."));
    };
    script.onerror = () => {
      script.remove();
      reject(new Error("Razorpay Checkout could not be loaded."));
    };
    document.head.append(script);
  });

export const loadRazorpayCheckout = (): Promise<RazorpayConstructor> => {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Razorpay Checkout can only load in a browser."));
  }
  if (window.Razorpay) {
    return Promise.resolve(window.Razorpay);
  }
  pendingLoad ??= injectCheckoutScript().catch((error: unknown) => {
    pendingLoad = null;
    throw error;
  });
  return pendingLoad;
};
