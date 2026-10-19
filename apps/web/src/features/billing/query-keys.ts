export const billingKeys = {
  all: ["billing"] as const,
  products: () => [...billingKeys.all, "products"] as const,
  subscription: () => [...billingKeys.all, "subscription"] as const,
  order: (orderId: string) => [...billingKeys.all, "order", orderId] as const,
  history: () => [...billingKeys.all, "history"] as const,
};
